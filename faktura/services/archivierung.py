"""Archivierung von Belegen in Paperless und Prüfung des Belegarchivs.

Das Festschreiben ist der handelsrechtliche Vorgang, die Archivierung eine
Kopie an einem zweiten Ort. Ist das Archiv nicht erreichbar, wird die
Rechnung trotzdem festgeschrieben; ``belege_archivieren`` holt die
Archivierung nach.
"""

import hashlib
import logging
import time
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .. import archiv
from ..archiv import ArchivFehler
from ..models import Beleg, BelegStatus, BelegTyp
from .fehler import BereitsArchiviert, FalscherStatus

logger = logging.getLogger(__name__)


def _archivierung_anstossen(beleg_id: int) -> None:
    """Archiviert den Beleg nach dem Festschreiben und fängt jede Exception.

    Läuft als on_commit-Callback, in dem eine Exception den Aufrufer
    träfe, obwohl der Beleg bereits festgeschrieben ist. Gewartet wird nur
    bei ``PAPERLESS_WARTEN_BEIM_FESTSCHREIBEN``, weil der Callback im
    Request des Benutzers läuft.
    """
    warten = getattr(settings, 'PAPERLESS_WARTEN_BEIM_FESTSCHREIBEN', False)
    try:
        beleg_archivieren(beleg_id=beleg_id, warten=warten)
    except Exception:
        # Mit Traceback ins Log, damit die auslösende Zeile erkennbar ist.
        logger.exception('Archivierung von Beleg %s gescheitert.', beleg_id)


def beleg_archivieren(*, beleg_id: int, warten: bool = True) -> Beleg:
    """Lädt das Beleg-PDF ins Archiv und speichert die Dokumentnummer.

    Idempotent aus jedem Zwischenzustand:

    * ``paperless_id`` gesetzt: nichts zu tun.
    * ``paperless_task_id`` gesetzt: Status abfragen, nie erneut hochladen,
      weil Paperless die Datei ein zweites Mal ablegte.
    * sonst: hochladen.

    ``warten=False`` kehrt nach dem Upload sofort zurück, für den Lauf über
    viele Belege.
    """
    beleg = Beleg.objects.get(pk=beleg_id)

    if not archiv.ist_eingerichtet():
        logger.debug('Archivierung ist nicht eingerichtet; Beleg %s bleibt liegen.',
                     beleg_id)
        return beleg

    if beleg.ist_entwurf:
        raise FalscherStatus(
            f'{beleg} ist ein Entwurf. Ins Archiv gehört nur, was '
            f'festgeschrieben ist.'
        )

    # Belegarten ohne Dokument überspringen; hier und im Command, damit
    # auch ein manueller Aufruf nichts anlegt.
    if beleg.typ not in BelegTyp.mit_dokument():
        logger.debug('%s ist eine Belegart ohne Dokument; nichts zu '
                     'archivieren.', beleg)
        return beleg

    if beleg.paperless_id is not None:
        return beleg

    if beleg.paperless_task_id:
        return _aufgabe_aufloesen(beleg)

    aufgabe = archiv.hochladen(beleg)
    _aufgabe_merken(beleg, aufgabe)
    logger.info('Beleg %s ans Archiv übergeben (Aufgabe %s).', beleg.nummer, aufgabe)

    if not warten:
        return beleg

    return _aufgabe_aufloesen(beleg)


def _aufgabe_merken(beleg: Beleg, aufgabe: str) -> None:
    """Speichert die Task-ID über ``update()``, wie jedes Archivfeld."""
    Beleg.objects.filter(pk=beleg.pk).update(paperless_task_id=aufgabe)
    beleg.paperless_task_id = aufgabe


def _aufgabe_aufloesen(beleg: Beleg) -> Beleg:
    """Fragt den Status eines offenen Tasks ab und speichert das Ergebnis.

    Wartet bis ``PAPERLESS_WARTEZEIT``. Ohne Ergebnis bleibt die Task-ID
    gesetzt, und der nächste Lauf fragt erneut.
    """
    grenze = time.monotonic() + settings.PAPERLESS_WARTEZEIT

    while True:
        zustand, nummer, meldung = archiv.aufgabe_abfragen(beleg.paperless_task_id)

        if zustand == 'success':
            Beleg.objects.filter(pk=beleg.pk).update(paperless_task_id='')
            beleg.paperless_task_id = ''
            beleg = archivierung_vermerken(beleg_id=beleg.pk, paperless_id=nummer)
            logger.info('Beleg %s liegt im Archiv als Dokument %s.',
                        beleg.nummer, nummer)
            return beleg

        if zustand == 'failure':
            # Nur nach einem fehlgeschlagenen Task ist ein neuer Upload
            # sicher; deshalb wird die Task-ID nur hier gelöscht.
            Beleg.objects.filter(pk=beleg.pk).update(paperless_task_id='')
            beleg.paperless_task_id = ''
            raise ArchivFehler(f'{beleg}: Das Archiv hat abgelehnt; {meldung}')

        if zustand == 'unbekannt':
            # Kein neuer Upload, weil ein von Paperless gelöschter Task nicht
            # bedeutet, dass das Dokument fehlt.
            logger.warning(
                'Beleg %s: Das Archiv kennt Aufgabe %s nicht mehr. Bitte dort '
                'nachsehen, ob das Dokument vorhanden ist, und den Vermerk von '
                'Hand setzen.',
                beleg.nummer, beleg.paperless_task_id,
            )
            return beleg

        if time.monotonic() >= grenze:
            logger.info(
                'Beleg %s: Das Archiv verarbeitet noch (Aufgabe %s). Die '
                'Dokumentnummer holt der nächste Lauf.',
                beleg.nummer, beleg.paperless_task_id,
            )
            return beleg

        time.sleep(1)


@transaction.atomic
def archivierung_vermerken(*, beleg_id: int, paperless_id: int) -> Beleg:
    """Speichert die Dokumentnummer des Belegs im Archiv.

    Nur für festgeschriebene Belege. Derselbe Wert erneut ist zulässig
    (wiederholter Lauf), ein anderer nicht, weil der Beleg dann doppelt im
    Archiv läge. Beim Wiedereröffnen entfernt ``beleg_wiedereroeffnen`` den
    Verweis.
    """
    # Row Lock, damit zwei gleichzeitige Aufrufe nicht beide ein leeres Feld
    # lesen und sich überschreiben.
    beleg = Beleg.objects.select_for_update().get(pk=beleg_id)

    if beleg.ist_entwurf:
        raise FalscherStatus(
            f'{beleg} ist ein Entwurf und hat kein Dokument, das ins Archiv '
            f'gehört. Erst festschreiben.'
        )

    if beleg.paperless_id is not None and beleg.paperless_id != paperless_id:
        raise BereitsArchiviert(
            f'{beleg} ist bereits als Dokument {beleg.paperless_id} '
            f'vermerkt, jetzt käme {paperless_id} dazu. Ein Beleg gehört zu '
            f'genau einem Archivdokument; vermutlich wurde er zweimal '
            f'abgelegt.'
        )

    if beleg.paperless_id == paperless_id:
        return beleg

    zeitpunkt = timezone.now()

    Beleg.objects.filter(pk=beleg.pk).update(
        paperless_id=paperless_id, archiviert_am=zeitpunkt,
    )
    beleg.paperless_id = paperless_id
    beleg.archiviert_am = zeitpunkt
    return beleg


# ── Belegarchiv prüfen ────────────────────────────────────────────────────
#
# Die Prüfsummen am Beleg sind nur ein Nachweis, wenn sie regelmäßig mit den
# Dateien verglichen werden. Berechnet mit hashlib, weil faktura.pdf
# WeasyPrint samt GTK lädt, auch auf einem Server ohne PDF-Erzeugung.


@dataclass(frozen=True)
class Archivbefund:
    beleg_id: int
    beleg: str
    problem: str


@dataclass(frozen=True)
class Archivbericht:
    geprueft: int = 0
    befunde: list[Archivbefund] = field(default_factory=list)

    @property
    def in_ordnung(self) -> bool:
        return not self.befunde


def belegarchiv_pruefen() -> Archivbericht:
    """Prüft jeden festgeschriebenen Beleg gegen sein gespeichertes Dokument.

    Je Datei: Ist sie eingetragen, liegt sie im Speicherverzeichnis, stimmt
    die SHA-256-Prüfsumme? Bei E-Rechnungen dasselbe für das XML als eigener
    Befund, dazu die ersetzten Fassungen.

    Stornierte Belege werden geprüft (aufbewahrungspflichtig), Entwürfe und
    Belegarten ohne Dokument nicht, damit der ordnungsgemäße Zustand keine
    Befunde erzeugt.
    """
    befunde = []
    geprueft = 0

    zu_pruefen = (Beleg.objects
                  .exclude(status=BelegStatus.ENTWURF)
                  .filter(typ__in=BelegTyp.mit_dokument())
                  .order_by('nummer'))
    for beleg in zu_pruefen:
        geprueft += 1
        problem = None

        # Prüft .name, nicht den Wahrheitswert des FieldFile: gleiches
        # Ergebnis, aber der Type Checker leitet ab, dass .name nicht None
        # ist.
        if not beleg.pdf.name:
            problem = 'kein PDF hinterlegt'
        elif not beleg.pdf.storage.exists(beleg.pdf.name):
            problem = f'Datei {beleg.pdf.name} fehlt im Ablageverzeichnis'
        elif not beleg.pdf_sha256:
            problem = 'keine Prüfsumme gespeichert'
        else:
            with beleg.pdf.open('rb') as datei:
                ist = hashlib.sha256(datei.read()).hexdigest()
            if ist != beleg.pdf_sha256:
                problem = (
                    'Prüfsumme weicht ab; die Datei wurde nach der '
                    'Festschreibung verändert'
                )

        if problem:
            befunde.append(
                Archivbefund(beleg_id=beleg.pk, beleg=str(beleg), problem=problem)
            )

        problem = _xml_pruefen(beleg)
        if problem:
            befunde.append(
                Archivbefund(beleg_id=beleg.pk, beleg=str(beleg), problem=problem)
            )

        for fassung in beleg.fassungen.all():
            for problem in _fassung_pruefen(fassung):
                befunde.append(Archivbefund(
                    beleg_id=beleg.pk, beleg=str(beleg),
                    problem=f'Fassung bis {fassung.abgeloest_am:%d.%m.%Y}: '
                            f'{problem}'))

    return Archivbericht(geprueft=geprueft, befunde=befunde)


def _fassung_pruefen(fassung) -> list[str]:
    """Prüft PDF und XML einer ersetzten Fassung gegen ihre Prüfsummen."""
    probleme = []
    for datei, soll, art in ((fassung.pdf, fassung.pdf_sha256, 'PDF'),
                             (fassung.xml, fassung.xml_sha256, 'XML')):
        if not datei.name:
            continue
        if not datei.storage.exists(datei.name):
            probleme.append(f'{art} {datei.name} fehlt im Ablageverzeichnis')
            continue
        with datei.open('rb') as offen:
            ist = hashlib.sha256(offen.read()).hexdigest()
        if ist != soll:
            probleme.append(f'Prüfsumme des {art} weicht ab')
    return probleme


def _xml_pruefen(beleg: Beleg) -> str | None:
    """XML-Teil der Archivprüfung.

    Nur bei E-Rechnungen mit PDF, weil ein fehlendes PDF bereits als Befund
    gemeldet wird.
    """
    from .. import facturx

    if not facturx.ist_erechnungsfaehig(beleg) or not beleg.pdf.name:
        return None
    if not beleg.xml.name:
        return 'kein XML hinterlegt'
    if not beleg.xml.storage.exists(beleg.xml.name):
        return f'Datei {beleg.xml.name} fehlt im Ablageverzeichnis'
    if not beleg.xml_sha256:
        return 'keine Prüfsumme für das XML gespeichert'
    with beleg.xml.open('rb') as datei:
        ist = hashlib.sha256(datei.read()).hexdigest()
    if ist != beleg.xml_sha256:
        return ('Prüfsumme des XML weicht ab; die E-Rechnung wurde nach '
                'der Festschreibung verändert')
    return None
