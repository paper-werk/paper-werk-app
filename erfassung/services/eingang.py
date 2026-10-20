"""Übernahme von Eingangsrechnungen aus dem Archiv (n8n), aus einer
E-Rechnung (Upload im Admin) oder aus einer E-Rechnung im Archiv (n8n).

Angelegt wird nur der Einkauf. Weiterberechnung und Preis legt der Benutzer
beim Übernehmen in die Rechnung fest.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from faktura import archiv
from faktura.models import Kontakt, Projekt

from ..models import Eingangsrechnung, Fremdleistung
from .fehler import (
    LieferantFehlt,
    ProjektUnbekannt,
    RechnungBereitsErfasst,
    UebertragGesperrt,
)

if TYPE_CHECKING:
    # Lokaler Import, weil erechnung drafthorse lädt.
    from ..erechnung import GeleseneRechnung


def eingangsrechnung_aus_archiv(
    *, paperless_id: int, lieferant: str, nummer: str, datum,
    betrag_netto, projekt: str = '', notiz: str = '',
) -> tuple[Eingangsrechnung, bool]:
    """Übernimmt eine Rechnung aus dem Archiv, anlegen oder aktualisieren.

    Ein Benutzer hat die Felder in Paperless geprüft, n8n sendet die Werte;
    das PDF bleibt im Archiv (``paperless_id``). Rückgabe ``(rechnung, neu)``
    für 201 oder 200. Regeln:

    * Eine wiederholte Übernahme ist ein Update; Korrekturen in Paperless
      werden übernommen, solange nichts weiterberechnet ist.
    * Ein unbekannter Lieferant wird angelegt und gekennzeichnet.
    * Ohne Projektnummer entsteht die Rechnung mit offenem Rest; eine
      unbekannte Nummer ist ein Fehler.
    * Mit Projekt entsteht eine Position über den vollen Betrag.

    Netto, weil die Projektauswertung netto rechnet.
    """
    vorhanden = Eingangsrechnung.objects.filter(
        paperless_id=paperless_id).first()
    if vorhanden is not None:
        _pruefe_uebertrag_erlaubt(vorhanden)

    ziel = _projekt_fuer_uebertrag(projekt)

    with transaction.atomic():
        rechnung = vorhanden or Eingangsrechnung(paperless_id=paperless_id)
        rechnung.lieferant = _lieferant_fuer_uebertrag(lieferant)
        rechnung.nummer = nummer
        rechnung.datum = datum
        rechnung.betrag_netto = betrag_netto
        if notiz:
            rechnung.notiz = notiz
        rechnung.save()

        if ziel is not None:
            _position_nachziehen(rechnung, ziel)

    return rechnung, vorhanden is None


def _pruefe_uebertrag_erlaubt(rechnung: Eingangsrechnung) -> None:
    """Lehnt eine erneute Übernahme ab, sobald eine Position auf einer
    Ausgangsrechnung steht."""
    abgerechnet = rechnung.positionen.filter(
        abgerechnet_in__isnull=False).select_related('abgerechnet_in__beleg')
    belege = sorted({str(p.abgerechnet_in.beleg) for p in abgerechnet})
    if belege:
        raise UebertragGesperrt(
            f'{rechnung} ist bereits weiterberechnet '
            f'({", ".join(belege)}) und wird nicht mehr aus dem Archiv '
            f'aktualisiert. Was sich am Dokument geändert hat, gehört '
            f'hier von Hand nachgezogen oder über eine Korrektur der '
            f'Ausgangsrechnung.'
        )


def _lieferant_fuer_uebertrag(name: str, herkunft: str = 'aus dem Archiv',
                              ) -> Kontakt:
    """Findet den Lieferanten unter den Kontakten oder legt ihn an.

    Ohne Rücksicht auf Groß- und Kleinschreibung. Ein Lieferant mit dem
    Namen hat Vorrang; sonst bekommt ein gleichnamiger Kontakt (etwa ein
    Kunde) die Rolle dazu. Ein neuer Kontakt trägt einen Vermerk, damit
    Dubletten wie "ISARTAL" und "Isartal GmbH" beim Aufräumen auffallen.
    ``herkunft`` steht nur im Vermerk: Archiv oder E-Rechnung.
    """
    sauber = (name or '').strip()
    if not sauber:
        raise LieferantFehlt(
            'Ohne Lieferant lässt sich eine Eingangsrechnung nicht '
            'zuordnen. Im Archiv ist das der Korrespondent des Dokuments, '
            'in einer E-Rechnung der Verkäufer (BT-27).')

    gleichnamig = Kontakt.objects.filter(name__iexact=sauber).order_by(
        '-ist_lieferant', 'pk')
    gefunden = gleichnamig.first()
    if gefunden is not None:
        if not gefunden.ist_lieferant:
            gefunden.ist_lieferant = True
            gefunden.save(update_fields=['ist_lieferant'])
        return gefunden

    return Kontakt.objects.create(
        name=sauber,
        ist_kunde=False,
        ist_lieferant=True,
        notiz=f'Automatisch {herkunft} angelegt am '
              f'{timezone.localdate():%d.%m.%Y}. Bitte prüfen, ob es '
              f'diesen Kontakt schon unter anderer Schreibweise gibt.',
    )


def _projekt_fuer_uebertrag(nummer: str):
    """Vorhaben zur Nummer; None bei leerer, Fehler bei unbekannter Nummer."""
    sauber = (nummer or '').strip()
    if not sauber:
        return None

    gefunden = Projekt.objects.filter(nummer=sauber).first()
    if gefunden is None:
        raise ProjektUnbekannt(
            f'Es gibt kein Projekt mit der Nummer "{sauber}". Entweder '
            f'ist die Nummer am Dokument falsch, oder das Projekt ist '
            f'hier noch nicht angelegt.')
    return gefunden


def _position_nachziehen(rechnung: Eingangsrechnung, projekt) -> None:
    """Legt die Position an oder passt ihren Betrag an, nur wenn die
    Übernahme sie erzeugt hat. Hat ein Benutzer aufgeteilt, umbenannt oder
    Preise geändert, bleibt alles unverändert."""
    positionen = list(rechnung.positionen.all())

    if len(positionen) > 1:
        return
    if positionen:
        eine = positionen[0]
        unberuehrt = (
            eine.projekt_id == projekt.pk
            and eine.menge == Decimal('1')
            and eine.einkaufspreis == rechnung.betrag_netto
        )
        if not unberuehrt:
            # Nur der Betrag ist geändert: Position anpassen.
            nur_betrag = (eine.projekt_id == projekt.pk
                          and eine.menge == Decimal('1'))
            if not nur_betrag:
                return
        eine.einkaufspreis = rechnung.betrag_netto
        eine.save()
        return

    Fremdleistung.objects.create(
        rechnung=rechnung,
        projekt=projekt,
        bezeichnung=f'Rechnung {rechnung.nummer}',
        menge=Decimal('1'),
        einheit='Stk',
        einkaufspreis=rechnung.betrag_netto,
    )


def eingangsrechnung_aus_xml(*, daten: bytes, dateiname: str = '',
                             projekt: Projekt | None = None
                             ) -> tuple[Eingangsrechnung, 'GeleseneRechnung']:
    """Legt aus einer E-Rechnung (ZUGFeRD-PDF oder XML) eine
    Eingangsrechnung samt Positionen an.

    Unterschiede zur Übernahme aus dem Archiv: nur Anlegen, ein zweiter
    Upload wird als Fehler gemeldet; keine ``paperless_id``; alle Positionen
    der Rechnung an Stelle einer Summenzeile. ``projekt`` wählt der Benutzer;
    ohne Auswahl gilt die Projektreferenz der Rechnung (BT-11), wenn sie
    eindeutig ist (``projekt_aus_referenz``). Rückgabe ``(rechnung,
    gelesen)``, damit der Aufrufer den Inhalt der Datei melden kann.
    """
    # Lokaler Import, weil erechnung drafthorse lädt.
    from .. import erechnung

    gelesen = erechnung.lesen(daten)
    lieferant = _lieferant_fuer_uebertrag(
        gelesen.lieferant, herkunft='aus einer E-Rechnung')

    vorhanden = Eingangsrechnung.objects.filter(
        lieferant=lieferant, nummer=gelesen.nummer).first()
    if vorhanden is not None:
        raise RechnungBereitsErfasst(
            f'Die Rechnung {gelesen.nummer} von {lieferant.name} ist bereits '
            f'erfasst (vom {vorhanden.datum:%d.%m.%Y}). Dieselbe Rechnung '
            f'ein zweites Mal anzulegen würde die Fremdkosten des Projekts '
            f'verdoppeln.')

    rechnung = _anlegen_aus_xml(gelesen, lieferant, projekt,
                                notiz=erechnung.notiz_bauen(gelesen, dateiname))
    return rechnung, gelesen


def _anlegen_aus_xml(gelesen, lieferant: Kontakt, projekt, *, notiz: str,
                     paperless_id: int | None = None) -> Eingangsrechnung:
    """Legt Kopf und Positionen aus einer gelesenen E-Rechnung an, für
    Upload und Archiv. Ohne Projekt gilt die Projektreferenz."""
    with transaction.atomic():
        rechnung = Eingangsrechnung.objects.create(
            lieferant=lieferant,
            nummer=gelesen.nummer,
            datum=gelesen.datum,
            betrag_netto=gelesen.betrag_netto,
            notiz=notiz,
            paperless_id=paperless_id,
        )
        if projekt is None:
            projekt = projekt_aus_referenz(gelesen.projektreferenz)
        if projekt is not None:
            _positionen_aus_xml(rechnung, gelesen, projekt)
    return rechnung


@dataclass(frozen=True)
class ERechnungBefund:
    """Ergebnis der Vorprüfung eines Archivdokuments.

    ``erechnung``: ob das PDF XML enthält; ``lesbar``: ob daraus eine
    Eingangsrechnung entsteht. Ein PDF mit UBL oder eine Gutschrift ist eine
    E-Rechnung, aber nicht lesbar; ``meldung`` nennt dann den Grund.

    ``felder`` verwendet die Namen der Custom Fields in Paperless, die sonst
    die Texterkennung füllt, damit der Workflow sie direkt zurückschreibt.
    """

    erechnung: bool
    lesbar: bool = False
    meldung: str = ''
    lieferant: str = ''
    projektreferenz: str = ''
    felder: dict[str, str] = field(default_factory=dict)


def erechnung_befund(daten: bytes) -> ERechnungBefund:
    """Prüft ein Archivdokument auf eine E-Rechnung und liest ihre Felder.

    Legt nichts an. Ein PDF ohne XML ist der Regelfall; dann füllt die
    Texterkennung die Felder.

    Die Projektnummer steht nur in ``felder``, wenn die Projektreferenz
    (BT-11) eindeutig auf ein laufendes Projekt zeigt, weil eine unsichere
    Nummer bei der Übernahme als unbekannt abgelehnt würde.
    """
    from .. import erechnung

    if not erechnung.enthaelt_erechnung(daten):
        return ERechnungBefund(
            erechnung=False,
            meldung='Keine E-Rechnung: Im Dokument steckt kein XML.')

    try:
        gelesen = erechnung.lesen(daten)
    except erechnung.ERechnungFehler as fehler:
        return ERechnungBefund(erechnung=True, meldung=str(fehler))

    felder = {
        archiv.FELD_RECHNUNGSNUMMER: gelesen.nummer,
        archiv.FELD_RECHNUNGSDATUM: gelesen.datum.isoformat(),
        archiv.FELD_NETTOBETRAG: f'{gelesen.betrag_netto:.2f}',
    }
    if gelesen.betrag_brutto is not None:
        felder[archiv.FELD_GESAMTBETRAG] = f'{gelesen.betrag_brutto:.2f}'
    if gelesen.faellig_am is not None:
        felder[archiv.FELD_FAELLIG_AM] = gelesen.faellig_am.isoformat()
    projekt = projekt_aus_referenz(gelesen.projektreferenz)
    if projekt is not None:
        felder[archiv.FELD_PROJEKTNUMMER] = projekt.nummer

    return ERechnungBefund(
        erechnung=True,
        lesbar=True,
        lieferant=gelesen.lieferant,
        projektreferenz=gelesen.projektreferenz,
        felder=felder,
    )


def eingangsrechnung_aus_archiv_erechnung(
    *, daten: bytes, paperless_id: int, projekt: str = '',
) -> tuple[Eingangsrechnung, bool]:
    """Übernimmt eine E-Rechnung aus dem Archiv mit ihren Positionen.

    Die Werte kommen aus dem XML wie beim Upload, das PDF bleibt im Archiv
    wie bei der Übernahme der Felder. Rückgabe ``(rechnung, neu)`` für 201
    oder 200.

    * ``projekt`` ist die in Paperless geprüfte Projektnummer und hat
      Vorrang vor der Projektreferenz; eine unbekannte Nummer ist ein
      Fehler, eine leere lässt die Referenz entscheiden.
    * Eine wiederholte Übernahme ändert nichts, weil das XML gleich ist.
      Positionen werden nur angelegt, wenn die Rechnung noch keine hat und
      jetzt ein Projekt übergeben wird.
    * Ist dieselbe Rechnung schon per Upload erfasst, erhält sie den Verweis
      ins Archiv. Verweist sie bereits auf ein anderes Dokument, liegt sie
      doppelt im Archiv, und die Übernahme schlägt fehl.
    """
    from .. import erechnung

    gelesen = erechnung.lesen(daten)
    ziel = _projekt_fuer_uebertrag(projekt)

    vorhanden = Eingangsrechnung.objects.filter(
        paperless_id=paperless_id).first()
    if vorhanden is None:
        lieferant = _lieferant_fuer_uebertrag(
            gelesen.lieferant, herkunft='aus einer E-Rechnung')
        vorhanden = Eingangsrechnung.objects.filter(
            lieferant=lieferant, nummer=gelesen.nummer).first()
        if vorhanden is None:
            rechnung = _anlegen_aus_xml(
                gelesen, lieferant, ziel,
                notiz=erechnung.notiz_bauen(
                    gelesen, f'Archivdokument {paperless_id}'),
                paperless_id=paperless_id)
            return rechnung, True
        if vorhanden.paperless_id is not None:
            raise RechnungBereitsErfasst(
                f'Die Rechnung {gelesen.nummer} von {lieferant.name} ist '
                f'bereits aus dem Archivdokument {vorhanden.paperless_id} '
                f'übernommen. Dasselbe Papier liegt offenbar zweimal im '
                f'Archiv; eines davon gehört gelöscht.')

    with transaction.atomic():
        if vorhanden.paperless_id is None:
            vorhanden.paperless_id = paperless_id
            vorhanden.save(update_fields=['paperless_id'])
        if ziel is None:
            ziel = projekt_aus_referenz(gelesen.projektreferenz)
        if ziel is not None and not vorhanden.positionen.exists():
            _positionen_aus_xml(vorhanden, gelesen, ziel)
    return vorhanden, False


def projekt_aus_referenz(referenz: str):
    """Laufendes Projekt zur Projektreferenz der Rechnung (BT-11) oder None.

    Zwei Regeln, in dieser Reihenfolge:

    1. Die Referenz **ist** eine Projektnummer ("2026-042").
    2. In der Referenz steht **genau eine** Projektnummer als eigenes Wort
       ("BV Turnhalle, Projekt 2026-042"). Bei mehreren entscheidet der
       Benutzer.

    Abgeschlossene Projekte sind ausgeschlossen, weil auf sie nicht mehr
    kontiert wird.
    """
    sauber = (referenz or '').strip()
    if not sauber:
        return None

    laufend = Projekt.objects.filter(abgeschlossen=False)
    genau = laufend.filter(nummer__iexact=sauber).first()
    if genau is not None:
        return genau

    treffer = [
        projekt for projekt in laufend.only('pk', 'nummer')
        if re.search(rf'(?<![\w-]){re.escape(projekt.nummer)}(?![\w-])',
                     sauber, re.IGNORECASE)
    ]
    return treffer[0] if len(treffer) == 1 else None


def _positionen_aus_xml(rechnung: Eingangsrechnung, gelesen, projekt) -> None:
    """Zeilen des Dokuments als Fremdleistungen mit Zeilenbetrag (BT-131);
    ohne Zeilen eine Summenzeile über den Kopfbetrag."""
    if not gelesen.positionen:
        Fremdleistung.objects.create(
            rechnung=rechnung,
            projekt=projekt,
            bezeichnung=f'Rechnung {rechnung.nummer}',
            menge=Decimal('1'),
            einheit='Stk',
            einkaufspreis=rechnung.betrag_netto,
        )
        return

    for position in gelesen.positionen:
        Fremdleistung.objects.create(
            rechnung=rechnung,
            projekt=projekt,
            bezeichnung=position.bezeichnung[:300],
            menge=position.menge,
            einheit=position.einheit[:20],
            einkaufspreis=position.einzelpreis,
            einkauf_netto=position.betrag,
        )
