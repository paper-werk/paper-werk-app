"""HTTP-Client für das Archiv (Paperless-ngx). Wann ein Beleg archiviert
wird, entscheidet ``services``.

Ablauf: ``POST /api/documents/post_document/`` liefert eine Task-ID,
``GET /api/tasks/?task_id=`` einige Sekunden später die Dokumentnummer.

Verhalten von Paperless (geprüft):

* Die Dokumentnummer steht in ``result_data.document_id`` (oder
  ``related_document_ids``). Das ältere ``related_document`` bleibt bei
  Erfolg null.
* Paperless nimmt dieselbe Datei mehrfach an; Duplikate verhindern
  ``paperless_id`` und ``paperless_task_id`` am Beleg.
* ``custom_fields`` nimmt ein JSON-Objekt ``{feld-id: wert}``, Geldbeträge
  als ``"EUR123.45"``.

Titel, Datum, Typ, Speicherpfad, Korrespondent und Custom Fields gehen im
selben ``post_document`` mit, weil für ein späteres PATCH die Dokumentnummer
noch fehlt. Typen, Pfade und Felder werden über ihren Namen gesucht (die IDs
sind je Installation verschieden) und gecacht; fehlt einer, bleibt das Feld
leer, mit Warnung.
"""

import hashlib
import json
import logging

import requests
from django.conf import settings
from django.core.cache import cache

from .models import Beleg, BelegTyp

logger = logging.getLogger(__name__)


class ArchivFehler(Exception):
    """Das Archiv war nicht erreichbar oder hat abgelehnt; kapselt
    ``requests``-Fehler für den Aufrufer."""


#: Dokumenttyp in Paperless je Belegart, mit den Namen des Starterpakets.
#: Rechnung, Storno, Korrektur und Mahnung teilen einen Typ, weil das Archiv
#: nach Buchungsrelevanz ordnet; gesucht wird über die Nummer im Titel.
#
# Im Code; wird ein Typ in Paperless umbenannt, entstehen Dokumente ohne Typ
# (mit Warnung). Langfristig gehört die Zuordnung in den Admin.
DOKUMENTTYPEN = {
    BelegTyp.ANGEBOT: 'Angebot',
    # Bezeichnung wie auf dem Beleg.
    BelegTyp.AUFTRAG: 'Auftragsbestätigung',
    BelegTyp.LIEFERSCHEIN: 'Lieferschein',
    BelegTyp.RECHNUNG: 'Rechnung',
    BelegTyp.STORNO: 'Rechnung',
    BelegTyp.GUTSCHRIFT: 'Rechnung',
    BelegTyp.MAHNUNG: 'Rechnung',
}


#: Cache-Dauer einer aufgelösten ID in Sekunden, kurz, damit Umbenennungen
#: in Paperless bald wirken.
CACHE_SEKUNDEN = 3600

#: Custom Fields in Paperless, die der Beleg füllt, nach Namen.
#
# "Projektnummer" als Textfeld, weil das Auswahlfeld "Projekt" feste
# Optionen hat, die für jedes neue Projekt zu pflegen wären.
FELD_PROJEKTNUMMER = 'Projektnummer'
FELD_RECHNUNGSNUMMER = 'Rechnungsnummer'
FELD_GESAMTBETRAG = 'Gesamtbetrag'
FELD_FAELLIG_AM = 'Fällig am'
# Felder des Eingangswegs: Die Texterkennung füllt sie, ``erfassung``
# verwendet die Namen beim Einlesen einer E-Rechnung aus dem Archiv.
FELD_NETTOBETRAG = 'Nettobetrag'
FELD_RECHNUNGSDATUM = 'Rechnungsdatum'

#: Tags des Eingangswegs: Auftrag des Benutzers und Ergebnis, benannt wie
#: "Steuer-senden" und "Steuer-gesendet".
TAG_SENDEN = 'Paper-Werk senden'
TAG_GESENDET = 'Paper-Werk gesendet'

#: Tag, mit dem die Erkennung eine E-Rechnung kennzeichnet. Bei diesem Tag
#: liest paper-werk bei der Übernahme das XML und nicht die Felder.
TAG_ERECHNUNG = 'E-Rechnung'


def ist_eingerichtet() -> bool:
    """Ob Schalter, URL und Token gesetzt sind. Der Schalter allein führte
    bei leerer URL bei jedem Festschreiben zu einem Fehler."""
    return bool(
        settings.PAPERLESS_ARCHIVIERUNG
        and settings.PAPERLESS_URL
        and settings.PAPERLESS_TOKEN
    )


def dokument_adresse(beleg) -> str:
    """URL des Archivdokuments für den Browser, leer ohne Archivierung.
    Für alle Objekte mit ``paperless_id``, auch Eingangsrechnungen.

    Aus ``PAPERLESS_ANSICHT_URL``, weil ``PAPERLESS_URL`` die URL aus Sicht
    des Servers ist ("http://paperless:8000"). Ohne Ansichts-URL gilt
    ``PAPERLESS_URL`` (bei runserver identisch).
    """
    if not beleg.paperless_id:
        return ''
    basis = settings.PAPERLESS_ANSICHT_URL or settings.PAPERLESS_URL
    if not basis:
        return ''
    return f'{basis}/documents/{beleg.paperless_id}/details'


def _kopf() -> dict[str, str]:
    """Authorization-Header mit Token, wie in der eigenen API."""
    return {'Authorization': f'Token {settings.PAPERLESS_TOKEN}'}


def _hole(pfad: str, parameter: dict | None = None) -> dict:
    """GET gegen das Archiv mit Timeout und ``ArchivFehler``."""
    try:
        antwort = requests.get(
            f'{settings.PAPERLESS_URL}{pfad}',
            headers=_kopf(), params=parameter,
            timeout=settings.PAPERLESS_TIMEOUT,
        )
        antwort.raise_for_status()
        return antwort.json()
    except requests.RequestException as fehler:
        raise ArchivFehler(f'GET {pfad} scheiterte: {fehler}') from fehler


def nummer_fuer(bereich: str, name: str, *, anlegen: bool = False) -> int | None:
    """ID eines benannten Objekts im Archiv (``document_types``,
    ``storage_paths``, ``correspondents``, ``custom_fields``) oder None.

    Angelegt wird nur mit ``anlegen=True`` und nur bei Korrespondenten. Typen
    und Pfade richtet das Setup ein, weil automatisches Anlegen
    Konfigurationsfehler verdeckte. Das Ergebnis, auch ein Fehlschlag, wird
    eine Stunde gecacht.
    """
    if not name:
        return None

    # Gehasht, weil "Fällig am" als memcached-Schlüssel unzulässig wäre.
    kennung = hashlib.sha1(name.casefold().encode()).hexdigest()[:16]
    schluessel = f'archiv:{bereich}:{kennung}'
    if (gemerkt := cache.get(schluessel)) is not None:
        return gemerkt or None

    # iexact, damit "Buchführung" auch "buchführung" findet.
    daten = _hole(f'/api/{bereich}/', {'name__iexact': name, 'page_size': 1})
    treffer = daten.get('results') or []

    if not treffer:
        if anlegen:
            nummer = _anlegen(bereich, name)
            cache.set(schluessel, nummer, CACHE_SEKUNDEN)
            return nummer
        logger.warning(
            'Archiv: %s "%s" gibt es dort nicht; das Feld bleibt leer.',
            bereich, name,
        )
        # Auch ein Fehlschlag wird gecacht, als 0, weil None "nicht gecacht"
        # bedeutet.
        cache.set(schluessel, 0, CACHE_SEKUNDEN)
        return None

    nummer = treffer[0]['id']
    cache.set(schluessel, nummer, CACHE_SEKUNDEN)
    return nummer


def _anlegen(bereich: str, name: str) -> int | None:
    """Legt ein benanntes Objekt im Archiv an, nur für Korrespondenten.

    Korrespondenten entsprechen dem Kundenstamm, der in Django wächst; von
    Hand gepflegt fehlten sie mit der Zeit.
    """
    try:
        antwort = requests.post(
            f'{settings.PAPERLESS_URL}/api/{bereich}/',
            headers=_kopf(), json={'name': name},
            timeout=settings.PAPERLESS_TIMEOUT,
        )
        antwort.raise_for_status()
    except requests.RequestException as fehler:
        # Kein Abbruch, weil der Beleg auch ohne Korrespondent archiviert ist.
        logger.warning('Archiv: %s "%s" ließ sich nicht anlegen: %s',
                       bereich, name, fehler)
        return None

    nummer = antwort.json().get('id')
    logger.info('Archiv: %s "%s" neu angelegt (%s).', bereich, name, nummer)
    return nummer


def _kunde(beleg: Beleg):
    """Kunde des Belegs, direkt oder über das Projekt
    (``services.anschriftgeber``)."""
    from . import services
    return services.anschriftgeber(beleg)


def _titel(beleg: Beleg) -> str:
    """Titel im Archiv: Belegnummer, nach der gesucht wird, dann der Kunde."""
    teile = [beleg.get_typ_display(), beleg.nummer or f'(Entwurf {beleg.pk})']
    if kunde := _kunde(beleg):
        teile.append(f'- {kunde}')
    return ' '.join(teile)


def hochladen(beleg: Beleg) -> str:
    """Lädt das PDF ins Archiv und gibt die Task-ID zurück; das Ergebnis
    liefert ``aufgabe_abfragen``."""
    if not beleg.pdf:
        raise ArchivFehler(
            f'{beleg} hat kein Dokument. Ein Beleg wird beim Festschreiben '
            f'archiviert, nicht davor.'
        )

    felder: dict[str, str] = {'title': _titel(beleg)}

    # Belegdatum, damit eine Rechnung vom 30.12. nicht im Speicherpfad des
    # Folgejahres landet.
    if beleg.belegdatum:
        felder['created'] = beleg.belegdatum.isoformat()

    typ_name = DOKUMENTTYPEN.get(beleg.typ)
    if typ_name and (nummer := nummer_fuer('document_types', typ_name)):
        felder['document_type'] = str(nummer)

    pfad_name = settings.PAPERLESS_SPEICHERPFAD
    if pfad_name and (nummer := nummer_fuer('storage_paths', pfad_name)):
        felder['storage_path'] = str(nummer)

    # Der Kunde wird Korrespondent und bei Bedarf angelegt.
    if (kunde := _kunde(beleg)) and (
        nummer := nummer_fuer('correspondents', kunde.name, anlegen=True)
    ):
        felder['correspondent'] = str(nummer)

    if zusatz := _zusatzfelder(beleg):
        # JSON-Objekt {feld-id: wert} in einem Formularfeld.
        felder['custom_fields'] = json.dumps(zusatz)

    return _absenden(beleg, felder)


def _zusatzfelder(beleg: Beleg) -> dict[int, str]:
    """Custom Fields des Archivdokuments, nur mit Werten des Belegs."""
    # Lokaler Import, weil services archiv importiert.
    from . import services

    werte: dict[int, str] = {}

    def setzen(feldname: str, wert) -> None:
        if wert in (None, ''):
            return
        if nummer := nummer_fuer('custom_fields', feldname):
            werte[nummer] = wert

    if beleg.nummer:
        setzen(FELD_RECHNUNGSNUMMER, beleg.nummer)

    if beleg.projekt_id:
        setzen(FELD_PROJEKTNUMMER, beleg.projekt.nummer)

    if beleg.faellig_am:
        setzen(FELD_FAELLIG_AM, beleg.faellig_am.isoformat())

    # Nur bei Wertbelegen, weil ein Lieferschein keine Preise zeigt.
    if beleg.ist_wertbeleg:
        summen = services.belegsummen(beleg)
        # Paperless erwartet bei "monetary" den Währungscode vor dem Betrag.
        setzen(FELD_GESAMTBETRAG, f'EUR{summen.brutto}')

    return werte


def _absenden(beleg: Beleg, felder: dict[str, str]) -> str:
    """Sendet Datei und alle Eigenschaften in einem POST."""

    try:
        beleg.pdf.open('rb')
        try:
            antwort = requests.post(
                f'{settings.PAPERLESS_URL}/api/documents/post_document/',
                headers=_kopf(),
                data=felder,
                files={'document': (beleg.pdf.name.rsplit('/', 1)[-1],
                                    beleg.pdf.read(), 'application/pdf')},
                timeout=settings.PAPERLESS_TIMEOUT,
            )
        finally:
            beleg.pdf.close()
        antwort.raise_for_status()
    except FileNotFoundError as fehler:
        raise ArchivFehler(
            f'{beleg}: Das Dokument ist vermerkt, die Datei fehlt aber im '
            f'Ablageverzeichnis.'
        ) from fehler
    except requests.RequestException as fehler:
        raise ArchivFehler(f'{beleg} ließ sich nicht ablegen: {fehler}') from fehler

    # Die Antwort ist ein nackter JSON-String: "f6344ce5-...".
    aufgabe = antwort.json()
    if not isinstance(aufgabe, str) or not aufgabe:
        raise ArchivFehler(
            f'{beleg}: Das Archiv hat die Datei angenommen, aber keine '
            f'Aufgabennummer geliefert (Antwort: {antwort.text[:200]}).'
        )
    return aufgabe


def aufgabe_abfragen(aufgabe: str) -> tuple[str, int | None, str]:
    """Fragt den Stand einer Aufgabe ab.

    Liefert ``(zustand, dokumentnummer, meldung)``:

    * ``zustand`` ist ``pending``, ``started``, ``success``, ``failure`` -
      oder ``unbekannt``, wenn Paperless die Aufgabe nicht mehr kennt.
    * ``dokumentnummer`` ist nur bei ``success`` gesetzt.
    * ``meldung`` trägt bei ``failure`` den Grund.

    ``unbekannt`` bedeutet nicht gescheitert: Paperless löscht alte Tasks,
    das Dokument kann vorhanden sein. Deshalb nicht erneut hochladen.
    """
    daten = _hole('/api/tasks/', {'task_id': aufgabe})

    # Seit Paperless 2.x paginiert, vorher eine Liste.
    treffer = daten.get('results', daten) if isinstance(daten, dict) else daten
    if not treffer:
        return 'unbekannt', None, 'Das Archiv kennt diese Aufgabe nicht (mehr).'

    stand = treffer[0]
    zustand = (stand.get('status') or '').lower()

    if zustand == 'success':
        # Siehe Modul-Docstring: related_document bleibt null.
        nummer = (stand.get('result_data') or {}).get('document_id')
        if nummer is None:
            nummern = stand.get('related_document_ids') or []
            nummer = nummern[0] if nummern else None
        if nummer is None:
            return 'failure', None, (
                'Das Archiv meldet Erfolg, nennt aber keine Dokumentnummer.'
            )
        return 'success', int(nummer), ''

    if zustand == 'failure':
        return 'failure', None, str(stand.get('result') or 'ohne Angabe')

    return zustand or 'pending', None, ''
