"""Titel und Zuschläge auf Grundlage der Positionsnummer.

**Bezug über die Nummer.** Ein Titel "01" fasst alle Zeilen zusammen, deren
Nummer mit "01." beginnt, entsprechend der Gliederung eines
Leistungsverzeichnisses. Ein Zuschlag bezieht sich auf ein Präfix: leer auf
alle Leistungen, "01" auf den Titel 01, "01.0020" auf genau diese Position.
Eine zusätzlich zu pflegende Zuordnung entfällt.

**Basis eines Zuschlags** (R-180) sind die Positionsnetti (R-001) der
bezogenen Leistungen, ohne optionale (R-178), ohne Abzugszeilen, nie ein
anderer Zuschlag. Der Betrag ist Basis mal Satz durch 100, auf den Cent
gerundet, als Einzelpreis bei Menge 1, damit Summen, SQL und E-Rechnung
ihn ohne Sonderfall verarbeiten.

**Ein optionaler Zuschlag** ("Samstag 50 %") hat den Betrag 0 und im PDF
nur Satz und Bezug, weil der Anteil der Basis erst bei der Abrechnung
feststeht. Wie jede Option wird er nicht automatisch in die Rechnung
übernommen; ``optionale_zuschlaege`` zeigt die offenen in der
Rechnungsmaske.

**Die Titelsumme** (R-181) ist nur Anzeige im PDF: die Positionsnetti aller
Leistungen und Zuschläge des Titels, ohne optionale. Sie geht in keine
Belegsumme, weil die Positionen dort bereits zählen.
"""

from dataclasses import dataclass
from decimal import Decimal

from core import rechnen
from core.optimistic_locking import version_erhoehen

from ..models import Beleg, Belegposition, BelegStatus, BelegTyp, Zeilenart
from .summen import positionssumme


def gehoert_zu(nummer: str, anfang: str) -> bool:
    """Ob die Positionsnummer unter dieses Präfix fällt: dieselbe Nummer
    oder eine, die mit ihr und einem Punkt beginnt. "01" trifft "01.0010",
    nicht "010"; leer trifft alle."""
    if not anfang:
        return True
    return nummer == anfang or nummer.startswith(anfang + '.')


def _netto(position: Belegposition) -> Decimal:
    return positionssumme(menge=position.menge,
                          einzelpreis=position.einzelpreis)


def zuschlagsbasis(positionen, auf: str) -> Decimal:
    """Basis eines Zuschlags mit diesem "auf" (R-180)."""
    return sum(
        (_netto(p) for p in positionen
         if p.zeilenart == Zeilenart.LEISTUNG and not p.optional
         and not p.ist_abzug and gehoert_zu(p.position, auf)),
        Decimal('0.00'))


def ohne_bezug(positionen) -> list[Belegposition]:
    """Zuschläge, deren "auf" keine Leistung trifft, auch keine optionale.
    Ihr Betrag wäre ohne Meldung 0,00, meist wegen eines Tippfehlers in der
    Nummer."""
    positionen = list(positionen)
    leistungen = [p.position for p in positionen
                  if p.zeilenart == Zeilenart.LEISTUNG and not p.ist_abzug]
    return [p for p in positionen
            if p.zeilenart == Zeilenart.ZUSCHLAG
            and not any(gehoert_zu(n, p.zuschlag_auf) for n in leistungen)]


def bezugsfehler(zuschlag: Belegposition) -> str:
    if zuschlag.zuschlag_auf:
        return (f'Keine Leistung mit der Nummer {zuschlag.zuschlag_auf} '
                f'oder darunter; der Zuschlag ergäbe 0,00.')
    return 'Der Beleg hat keine Leistung, auf die der Zuschlag rechnet.'


def zuschlagsbetrag(basis: Decimal, prozent: Decimal) -> Decimal:
    return rechnen.auf_cent(basis * prozent / Decimal('100'))


#: Belegarten, deren Zuschläge neu berechnet werden. Ohne Storno, weil es
#: die Beträge der Rechnung einschließlich Zuschlag spiegelt.
NACHZURECHNEN = (BelegTyp.ANGEBOT, BelegTyp.AUFTRAG, BelegTyp.RECHNUNG,
                 BelegTyp.GUTSCHRIFT)


def zuschlaege_nachrechnen(beleg: Beleg) -> list[Belegposition]:
    """Setzt den Betrag jedes Zuschlags auf Basis mal Satz, nur im Entwurf.
    Gibt die geänderten Zeilen zurück; idempotent.

    Aufgerufen beim Speichern des Formulars, beim Anlegen per Service, beim
    Kopieren und vor dem Festschreiben, weil jede Änderung einer Position
    den Zuschlag ändern kann.
    """
    if beleg.status != BelegStatus.ENTWURF or beleg.typ not in NACHZURECHNEN:
        return []
    # Die meisten Belege haben keinen Zuschlag; dann genügt eine Abfrage,
    # ohne alle Positionen bei jeder neuen Zeile zu laden.
    if not beleg.positionen.filter(zeilenart=Zeilenart.ZUSCHLAG).exists():
        return []
    # Über den Manager, weil ``beleg.positionen.all()`` aus dem Formular
    # einen Prefetch-Cache vom Stand vor dem Speichern liefert.
    positionen = list(Belegposition.objects.filter(beleg=beleg))
    geaendert = []
    for zuschlag in positionen:
        if zuschlag.zeilenart != Zeilenart.ZUSCHLAG:
            continue
        betrag = Decimal('0.00') if zuschlag.optional else zuschlagsbetrag(
            zuschlagsbasis(positionen, zuschlag.zuschlag_auf),
            zuschlag.zuschlag_prozent or Decimal('0'))
        if zuschlag.einzelpreis != betrag or zuschlag.menge != 1:
            # update(), weil der Betrag berechnet ist und save() nichts
            # prüft, was sich hier ändert.
            Belegposition.objects.filter(pk=zuschlag.pk).update(
                einzelpreis=betrag, menge=Decimal('1'))
            zuschlag.einzelpreis = betrag
            zuschlag.menge = Decimal('1')
            geaendert.append(zuschlag)
    if geaendert:
        version_erhoehen(Beleg, beleg.pk)
    return geaendert


@dataclass(frozen=True)
class Titelsumme:
    titel: Belegposition
    netto: Decimal

    @property
    def text(self) -> str:
        return f'Summe Titel {self.titel.position} {self.titel.bezeichnung}'


def titelsummen(positionen) -> dict[int, list[Titelsumme]]:
    """Je Position die Titelsummen, die nach ihr stehen (nach der letzten
    Zeile des Titels, innere Titel zuerst). Schlüssel ist der Index in
    ``positionen`` (Reihenfolge des Belegs). Ein Titel ohne Unterpositionen
    erhält keine Summe (R-181)."""
    positionen = list(positionen)
    nach: dict[int, list[Titelsumme]] = {}
    for titel in positionen:
        if titel.zeilenart != Zeilenart.TITEL or not titel.position:
            continue
        zugehoerig = [
            (i, p) for i, p in enumerate(positionen)
            if p is not titel and not p.ist_abzug
            and p.position.startswith(titel.position + '.')]
        if not zugehoerig:
            continue
        netto = sum(
            (_netto(p) for _, p in zugehoerig
             if p.zeilenart in (Zeilenart.LEISTUNG, Zeilenart.ZUSCHLAG)
             and not p.optional),
            Decimal('0.00'))
        letzte = max(i for i, _ in zugehoerig)
        nach.setdefault(letzte, []).append(Titelsumme(titel, netto))
    for liste in nach.values():
        # Innerer Titel zuerst: "01.02" vor "01".
        liste.sort(key=lambda s: -len(s.titel.position))
    return nach


def zuschlagsbeschreibung(zuschlag: Belegposition, positionen) -> str:
    """Rechenweg unter der Bezeichnung im PDF ("3 % auf 9.500,00"), damit
    der Betrag nachvollziehbar ist. Optional ohne Basis: "50 % auf
    Pos. 3.1"."""
    from ..formate import geld, prozent

    satz = prozent(zuschlag.zuschlag_prozent or Decimal('0'))
    worauf = ''
    if zuschlag.zuschlag_auf:
        titel = next((p for p in positionen
                      if p.zeilenart == Zeilenart.TITEL
                      and p.position == zuschlag.zuschlag_auf), None)
        worauf = (f'Titel {zuschlag.zuschlag_auf}' if titel
                  else f'Pos. {zuschlag.zuschlag_auf}')
    if zuschlag.optional:
        return f'{satz} auf {worauf or "alle Leistungen"}'
    basis = zuschlagsbasis(positionen, zuschlag.zuschlag_auf)
    return f'{satz} auf {geld(basis)}' + (f' ({worauf})' if worauf else '')


def optionale_zuschlaege(rechnung: Beleg) -> list[Belegposition]:
    """Optionale Zuschläge der zugrunde liegenden Aufträge, die die Rechnung
    noch nicht enthält, für den Hinweis in der Maske.

    Zugrunde liegende Aufträge: der Vorgänger, der Auftrag der Abnahme, die
    Aufträge der Positionsbezüge, die festgeschriebenen des Projekts und
    jeweils ihre Nachträge. Ein Zuschlag gilt als enthalten, wenn die
    Rechnung einen mit gleicher Bezeichnung hat."""
    from django.db.models import Q

    kennungen = {rechnung.vorgaenger_id,
                 rechnung.abnahme.auftrag_id if rechnung.abnahme_id else None,
                 *rechnung.positionen.exclude(auftragsposition=None)
                 .values_list('auftragsposition__beleg_id', flat=True)}
    kennungen.discard(None)
    bedingung = Q(pk__in=kennungen) | Q(nachtrag_zu__in=kennungen)
    if rechnung.projekt_id:
        bedingung |= Q(projekt=rechnung.projekt_id)
    auftraege = Beleg.objects.filter(
        bedingung, typ=BelegTyp.AUFTRAG, status=BelegStatus.FESTGESCHRIEBEN)

    vorhanden = {p.bezeichnung.strip().casefold()
                 for p in rechnung.positionen.filter(
                     zeilenart=Zeilenart.ZUSCHLAG)}
    return [p for p in Belegposition.objects
            .filter(beleg__in=auftraege, zeilenart=Zeilenart.ZUSCHLAG,
                    optional=True)
            .select_related('beleg').order_by('beleg__nummer', 'sortierung')
            if p.bezeichnung.strip().casefold() not in vorhanden]
