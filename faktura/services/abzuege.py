"""Umlage und Sicherheitseinbehalt des Auftraggebers (R-189 bis R-191).

Eingestellt am Projekt (``Projekt.umlage_*``, ``Projekt.einbehalt_*``), weil
Abschläge je Projekt gezählt und kumuliert werden.

**Umlage vom Netto** ist eine Zuschlagszeile mit negativem Satz auf alle
Leistungen (R-180) und mindert damit die Bemessungsgrundlage. Sie wird wie
die Zuschläge des Auftrags beim Anlegen einer Rechnung ergänzt
(``umlage_ergaenzen``) und ist danach eine gewöhnliche Zeile; gelöscht wird
sie nicht neu angelegt. Fehlt sie, nennt die Rechnungsmaske das
(``fehlende_umlage``).

**Umlage vom Brutto und Sicherheitseinbehalt** werden nach der Umsatzsteuer
abgezogen und stehen als Betrag mit Rechenweg am Beleg
(``Beleg.umlage_nach_steuer``, ``Beleg.einbehalt``). Berechnet im Entwurf
mit jedem Nachrechnen der Zuschläge, fest mit dem Festschreiben, weil der
Einbehalt von Vorgängern und Projekteinstellungen zum Zeitpunkt abhängt.

**Einbehalt kumuliert** über die Abschläge des Projekts: Satz mal Grundlage
aller Abschläge bis einschließlich diesem, höchstens Grenze mal
Auftragssumme, minus die Einbehalte der Vorgänger (R-183), nie negativ. So
behält der letzte Abschlag vor der Grenze nur den Rest ein, und ein
Nachtrag hebt die Grenze. Grundlage netto ist die Summe vor einer Umlage vom
Netto, brutto die Bruttosumme.

**Schlussrechnung** ohne Einbehalt. Was der Auftraggeber einbehalten hat,
ist nicht vereinnahmt; die Schlussrechnung setzt es nicht ab und fordert es
über die Restzeile mit Umsatzsteuer erneut (R-174). Ebenso die Umlage vom
Brutto eines Abschlags, die die Schlussrechnung dafür auf die volle
Leistung rechnet.

**E-Rechnung**: EN 16931 kennt keinen Abzug nach der Steuer (BR-CO-16).
BT-115 bleibt das Brutto; Abzüge und Zahlbetrag stehen in den
Zahlungsbedingungen (BT-20, ``facturx``).
"""

from decimal import Decimal

from core import rechnen
from core.optimistic_locking import version_erhoehen

from ..models import (
    Abzugsgrundlage,
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Rechnungsart,
    Zeilenart,
)
from .summen import _summen, belegsummen

NULL = Decimal('0.00')


def _umlagebezeichnung(projekt) -> str:
    return projekt.umlage_bezeichnung.strip() or 'Umlage'


def _umlagezeilen(positionen, projekt) -> list[Belegposition]:
    """Zuschlagszeilen der Umlage vom Netto, erkannt an der Bezeichnung."""
    name = _umlagebezeichnung(projekt).casefold()
    return [p for p in positionen
            if p.zeilenart == Zeilenart.ZUSCHLAG and not p.ist_abzug
            and p.bezeichnung.strip().casefold() == name]


def _umlage_vom_netto(beleg: Beleg) -> bool:
    projekt = beleg.projekt
    return (beleg.typ == BelegTyp.RECHNUNG and projekt is not None
            and projekt.umlage_prozent is not None
            and projekt.umlage_grundlage == Abzugsgrundlage.NETTO)


def fehlende_umlage(beleg: Beleg) -> str:
    """Bezeichnung und Satz der Umlage vom Netto, wenn das Projekt sie
    vorsieht und der Entwurf keine Zeile dafür hat, sonst leer."""
    if beleg.status != BelegStatus.ENTWURF or not _umlage_vom_netto(beleg):
        return ''
    if _umlagezeilen(beleg.positionen.all(), beleg.projekt):
        return ''
    from ..formate import prozent
    return (f'{_umlagebezeichnung(beleg.projekt)} '
            f'-{prozent(beleg.projekt.umlage_prozent)}')


def umlage_ergaenzen(beleg: Beleg) -> Belegposition | None:
    """Legt die Zeile der Umlage vom Netto an, wenn das Projekt sie vorsieht
    und der Entwurf noch keine hat. Steuersatz der ersten Leistung; ohne
    Leistung keine Zeile, weil ihr Betrag 0 wäre."""
    from .anlegen import position_hinzufuegen

    if beleg.status != BelegStatus.ENTWURF or not _umlage_vom_netto(beleg):
        return None
    positionen = list(Belegposition.objects.filter(beleg=beleg))
    if _umlagezeilen(positionen, beleg.projekt):
        return None
    leistung = next((p for p in positionen
                     if p.zeilenart == Zeilenart.LEISTUNG
                     and not p.ist_abzug and not p.optional), None)
    if leistung is None:
        return None
    return position_hinzufuegen(
        beleg=beleg, bezeichnung=_umlagebezeichnung(beleg.projekt),
        zeilenart=Zeilenart.ZUSCHLAG, menge=Decimal('1'), einheit='',
        einzelpreis=NULL, steuersatz=leistung.steuersatz,
        zuschlag_prozent=-beleg.projekt.umlage_prozent, zuschlag_auf='')


def _leistung(beleg: Beleg) -> list[Belegposition]:
    """Positionen ohne Abzugs- und Restzeilen. Über den Manager, weil
    ``beleg.positionen.all()`` aus dem Formular den Stand vor dem Speichern
    liefern kann."""
    return list(Belegposition.objects.filter(beleg=beleg, ist_abzug=False))


def _umlage_nach_steuer(beleg: Beleg) -> tuple[Decimal, str]:
    """Umlage vom Brutto (R-189): Satz mal Brutto der Leistung, bei der
    Schlussrechnung der vollen Leistung ohne abgesetzte Abschläge."""
    from ..formate import geld, prozent

    projekt = beleg.projekt
    if (projekt is None or projekt.umlage_prozent is None
            or projekt.umlage_grundlage != Abzugsgrundlage.BRUTTO):
        return NULL, ''
    basis = _summen(_leistung(beleg)).brutto
    if basis <= 0:
        return NULL, ''
    betrag = rechnen.auf_cent(basis * projekt.umlage_prozent / 100)
    return betrag, (f'{_umlagebezeichnung(projekt)} '
                    f'{prozent(projekt.umlage_prozent)} aus {geld(basis)} '
                    f'brutto')


def einbehaltsgrundlage(beleg: Beleg) -> Decimal:
    """Grundlage des Einbehalts eines Abschlags nach Einstellung des
    Projekts: Netto vor der Umlage vom Netto oder Brutto."""
    projekt = beleg.projekt
    positionen = _leistung(beleg)
    summen = _summen(positionen)
    if projekt.einbehalt_grundlage == Abzugsgrundlage.BRUTTO:
        return summen.brutto
    umlage = _summen(_umlagezeilen(positionen, projekt)).netto
    return summen.netto - umlage


def auftragssumme(projekt, grundlage: str) -> Decimal:
    """Summe der festgeschriebenen Aufträge des Projekts einschließlich
    Nachträgen, netto oder brutto, ohne optionale Positionen (R-178)."""
    auftraege = Beleg.objects.filter(projekt=projekt, typ=BelegTyp.AUFTRAG,
                                     status=BelegStatus.FESTGESCHRIEBEN)
    summe = NULL
    for auftrag in auftraege.prefetch_related('positionen'):
        s = belegsummen(auftrag)
        summe += s.brutto if grundlage == Abzugsgrundlage.BRUTTO else s.netto
    return summe


def _einbehalt(beleg: Beleg) -> tuple[Decimal, str]:
    """Sicherheitseinbehalt eines Abschlags (R-190), kumuliert über die
    festgeschriebenen Vorgänger."""
    from ..formate import geld, prozent
    from .kumuliert import vorgaenger_abschlaege

    projekt = beleg.projekt
    if (beleg.rechnungsart != Rechnungsart.ABSCHLAG or projekt is None
            or projekt.einbehalt_prozent is None):
        return NULL, ''
    vorgaenger = vorgaenger_abschlaege(beleg)
    basis = sum((einbehaltsgrundlage(b) for b in [*vorgaenger, beleg]), NULL)
    if basis <= 0:
        return NULL, ''
    soll = rechnen.auf_cent(basis * projekt.einbehalt_prozent / 100)

    begrenzt = ''
    if projekt.einbehalt_grenze is not None:
        summe = auftragssumme(projekt, projekt.einbehalt_grundlage)
        grenze = rechnen.auf_cent(summe * projekt.einbehalt_grenze / 100)
        if summe > 0 and soll > grenze:
            soll = grenze
            begrenzt = (f', höchstens {prozent(projekt.einbehalt_grenze)} '
                        f'von {geld(summe)} Auftragssumme')

    bisher = sum((b.einbehalt for b in vorgaenger), NULL)
    betrag = max(soll - bisher, NULL)
    text = (f'Sicherheitseinbehalt {prozent(projekt.einbehalt_prozent)} aus '
            f'{geld(basis)} {projekt.get_einbehalt_grundlage_display().lower()}'
            + (f', bisher einbehalten {geld(bisher)}' if bisher else '')
            + begrenzt)
    return betrag, text


def abzuege_nachrechnen(beleg: Beleg) -> bool:
    """Setzt Umlage vom Brutto und Einbehalt einer Rechnung im Entwurf nach
    den Einstellungen des Projekts. True, wenn sich etwas geändert hat;
    idempotent. Aufgerufen von ``zuschlaege_nachrechnen``, weil beide von
    denselben Positionen abhängen."""
    if beleg.status != BelegStatus.ENTWURF or beleg.typ != BelegTyp.RECHNUNG:
        return False
    umlage, umlage_text = _umlage_nach_steuer(beleg)
    einbehalt, einbehalt_text = _einbehalt(beleg)
    neu = {'umlage_nach_steuer': umlage, 'umlage_text': umlage_text,
           'einbehalt': einbehalt, 'einbehalt_text': einbehalt_text}
    if all(getattr(beleg, feld) == wert for feld, wert in neu.items()):
        return False
    # update(), weil die Werte berechnet sind und save() nichts prüft, was
    # sich hier ändert.
    Beleg.objects.filter(pk=beleg.pk).update(**neu)
    for feld, wert in neu.items():
        setattr(beleg, feld, wert)
    version_erhoehen(Beleg, beleg.pk)
    return True


def abzuege_nach_steuer(beleg: Beleg) -> list[tuple[str, Decimal]]:
    """Zeilen unter dem Brutto für PDF und Maske: Rechenweg und Betrag,
    positiv. Der Einbehalt auch mit 0,00, wenn die Grenze erreicht ist."""
    zeilen = []
    if beleg.umlage_text:
        zeilen.append((beleg.umlage_text, beleg.umlage_nach_steuer))
    if beleg.einbehalt_text:
        zeilen.append((beleg.einbehalt_text, beleg.einbehalt))
    return zeilen


def zahlbetrag(beleg: Beleg, brutto: Decimal | None = None) -> Decimal:
    """Brutto minus Umlage nach Steuer minus Einbehalt (R-191): was der
    Auftraggeber auf diese Rechnung zahlt. ``brutto``, wenn schon
    berechnet."""
    if brutto is None:
        brutto = belegsummen(beleg).brutto
    return brutto - beleg.umlage_nach_steuer - beleg.einbehalt
