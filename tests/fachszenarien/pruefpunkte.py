"""Prüfpunkte der Fälle als Funktionen.

Die Fälle führen jeden Prüfpunkt mit ``regel`` als Pseudocode. Hier steht
je Regeltext eine Funktion ``(lauf) -> bool``; ein Regeltext ohne Funktion
wird als "nicht geprüft" gemeldet. Der Pseudocode wird nicht ausgewertet,
weil er keine feste Syntax hat.

``JE_SCHRITT`` gilt nach jedem Schritt, ``AM_ENDE`` nach dem letzten.
"""

from __future__ import annotations

from decimal import Decimal

from faktura import services
from faktura.models import (
    Beleg,
    BelegStatus,
    BelegTyp,
    Rechnungsart,
    Zahlung,
    Zahlungszuordnung,
)

from . import istwerte
from .aktionen import Lauf, rechnungen

NULL = Decimal('0.00')
SCHLUSSARTEN = (Rechnungsart.SCHLUSS, Rechnungsart.TEILSCHLUSS)


def _schluss(lauf: Lauf):
    """Die zuletzt festgeschriebene Schlussrechnung."""
    return rechnungen(lauf).filter(rechnungsart__in=SCHLUSSARTEN).order_by('pk').last()


def _zahlungen(lauf: Lauf):
    """Eingegangene Zahlungen mit mindestens einer Zuordnung auf eine
    Rechnung des Projekts."""
    return Zahlung.objects.filter(zuordnungen__beleg__projekt=lauf.projekt).distinct()


def summe_zahlungen(lauf: Lauf) -> Decimal:
    """Volle Beträge der Zahlungen, auch der unverteilte Rest."""
    return sum((z.betrag for z in _zahlungen(lauf)), NULL)


def summe_skonti(lauf: Lauf) -> Decimal:
    return sum((z.skonto for z in Zahlungszuordnung.objects.filter(
        beleg__projekt=lauf.projekt)), NULL)


def summe_forderungen(lauf: Lauf) -> Decimal:
    """Zahlbeträge aller festgeschriebenen Rechnungen. Eine Schlussrechnung
    fordert nur, was nach Abzug der Abschläge bleibt, deshalb ohne
    Doppelzählung."""
    return sum((services.zahlbetrag(b) for b in rechnungen(lauf)), NULL)


def _offen_nicht_ueber_forderung(lauf):
    return istwerte.offen_gesamt(lauf) <= summe_forderungen(lauf) - summe_zahlungen(lauf)


def _leistung(beleg):
    return services.leistungssummen(beleg)


def _schluss_netto_gleich_auftragssumme(lauf):
    return _leistung(_schluss(lauf)).netto == services.auftragssumme(lauf.projekt, 'netto')


def _zahlungen_gleich_schluss_brutto(lauf):
    return summe_zahlungen(lauf) == _leistung(_schluss(lauf)).brutto


def _zahlungen_gleich_schluss_brutto_bis_auf_rundung(lauf):
    """Wie ``_zahlungen_gleich_schluss_brutto``, mit höchstens einem Cent
    je Abschlag: Die Restzeile (R-174) rundet netto je Position, ihr Brutto
    kann vom nicht vereinnahmten Betrag abweichen."""
    abschlaege = rechnungen(lauf).filter(
        rechnungsart=Rechnungsart.ABSCHLAG).count()
    differenz = summe_zahlungen(lauf) - _leistung(_schluss(lauf)).brutto
    return abs(differenz) <= Decimal('0.01') * abschlaege


def _zahlungen_und_skonti_gleich_schluss_brutto(lauf):
    return summe_zahlungen(lauf) + summe_skonti(lauf) == _leistung(_schluss(lauf)).brutto


def _saldo_null(lauf):
    return istwerte.offen_gesamt(lauf) == NULL


def _steuer_abgesetzt_plus_rest(lauf):
    """Abgesetzte Steuer (Leistung minus Umsatzbeitrag) plus Steuer des
    Zahlbetrags gleich Steuer der Leistung. Weicht ab, wenn eine Restzeile
    die Steuer eines nicht bezahlten Abschlags erneut fordert."""
    schluss = _schluss(lauf)
    leistung = _leistung(schluss).steuer
    abgesetzt = leistung - services.umsatzsummen(schluss).steuer
    return abgesetzt + services.belegsummen(schluss).steuer == leistung


def _netto_gleich(betrag):
    def pruefen(lauf):
        return _leistung(_schluss(lauf)).netto == Decimal(betrag)
    return pruefen


def _zeithonorar_hoechstens(betrag):
    def pruefen(lauf):
        return istwerte.zeithonorar(lauf, _schluss(lauf), None) <= Decimal(betrag)
    return pruefen


def _nummernkreis(name, jahr):
    def pruefen(lauf):
        return str(jahr) in lauf.beleg(name).nummer
    return pruefen


def _einbehalt_mindert_nichts(lauf):
    """Netto und Steuer jeder Rechnung ergeben sich aus den Positionen
    allein; Einbehalt und Umlage nach Steuer stehen nur im Zahlbetrag."""
    return all(services.zahlbetrag(b) == services.belegsummen(b).brutto
               - b.einbehalt - b.umlage_nach_steuer for b in rechnungen(lauf))


def _betrag_der_position(name, kennung, betrag):
    def pruefen(lauf):
        bezeichnung = lauf.katalog[kennung]['bezeichnung']
        positionen = lauf.beleg(name).positionen.filter(
            bezeichnung=bezeichnung, ist_abzug=False)
        return sum((services.positionssumme(menge=p.menge, einzelpreis=p.einzelpreis)
                    for p in positionen), NULL) == Decimal(betrag)
    return pruefen


def _steuersatz_der_position(name, kennung, satz):
    def pruefen(lauf):
        bezeichnung = lauf.katalog[kennung]['bezeichnung']
        positionen = lauf.beleg(name).positionen.filter(bezeichnung=bezeichnung)
        return positionen.exists() and all(p.steuersatz == satz for p in positionen)
    return pruefen


def _summe_nicht_stornierter(betrag):
    def pruefen(lauf):
        return sum((_leistung(b).netto for b in rechnungen(lauf).exclude(
            rechnungsart=Rechnungsart.ABSCHLAG)), NULL) == Decimal(betrag)
    return pruefen


def _rechnung_plus_storno_null(lauf):
    a = services.belegsummen(lauf.beleg('RE1'))
    b = services.belegsummen(lauf.beleg('Storno-RE1'))
    return (a.netto + b.netto, a.steuer + b.steuer, a.brutto + b.brutto) == (NULL,) * 3


def _dritter_ohne_saldo(kennung):
    """Weder offene Forderung noch unverteilte Zahlung oder Zuordnung auf
    eine stornierte Rechnung beim Kunden ``kennung``."""
    def pruefen(lauf):
        kunde = lauf.kunden[kennung]
        offen = istwerte.offen_je_kunde(lauf, None, None)[kennung]
        guthaben = sum((z.rest for z in Zahlung.objects.filter(kunde=kunde)), NULL)
        auf_storniertem = Zahlungszuordnung.objects.filter(
            zahlung__kunde=kunde, beleg__status=BelegStatus.STORNIERT).exists()
        return offen == NULL and guthaben == NULL and not auf_storniertem
    return pruefen


def _zahlung_einmal_angerechnet(betrag):
    """Die Zahlung über ``betrag`` ist genau einer festgeschriebenen,
    nicht stornierten Rechnung zugeordnet."""
    def pruefen(lauf):
        zahlungen = [z for z in _zahlungen(lauf) if z.betrag == Decimal(betrag)]
        return len(zahlungen) == 1 and zahlungen[0].zuordnungen.filter(
            beleg__status=BelegStatus.FESTGESCHRIEBEN).count() == 1
    return pruefen


def _nummern_nach_jahreswechsel(lauf):
    return ('2027' in lauf.beleg('Storno-RE1').nummer
            and '2027' in lauf.beleg('RE2').nummer
            and '2026' in lauf.beleg('RE1').nummer)


def _zeitraum_re2(lauf):
    beleg = lauf.beleg('RE2')
    return bool(beleg.leistungsdatum and beleg.leistungsdatum_bis
                and (beleg.leistungsdatum.year, beleg.leistungsdatum.month) == (2026, 6)
                and (beleg.leistungsdatum_bis.year,
                     beleg.leistungsdatum_bis.month) == (2026, 11))


def _schlussrechnungen_netto(betrag):
    def pruefen(lauf):
        return sum((_leistung(b).netto for b in rechnungen(lauf).filter(
            rechnungsart__in=SCHLUSSARTEN)), NULL) == Decimal(betrag)
    return pruefen


def _keine_leistung_doppelt(lauf):
    """Keine Auftragsposition auf zwei festgeschriebenen
    Schlussrechnungen."""
    gesehen = set()
    for b in rechnungen(lauf).filter(rechnungsart__in=SCHLUSSARTEN):
        positionen = set(b.positionen.filter(ist_abzug=False, auftragsposition__isnull=False)
                         .values_list('auftragsposition_id', flat=True))
        if gesehen & positionen:
            return False
        gesehen |= positionen
    return True


def _abschlag_ohne_abzug(name):
    """Die kumulierte Sicht des Abschlags zieht keinen früheren Abschlag
    ab."""
    def pruefen(lauf):
        kumuliert = services.kumulierter_abschlag(lauf.beleg(name))
        return kumuliert is None or not kumuliert.abzuege
    return pruefen


def _zahlungen_und_skonti_gleich(betrag):
    def pruefen(lauf):
        return summe_zahlungen(lauf) + summe_skonti(lauf) == Decimal(betrag)
    return pruefen


def _keine_rechnungskorrektur_ueber(betrag):
    def pruefen(lauf):
        korrekturen = Beleg.objects.filter(projekt=lauf.projekt, typ=BelegTyp.GUTSCHRIFT)
        return not any(services.belegsummen(k).brutto.copy_abs() == Decimal(betrag)
                       for k in korrekturen)
    return pruefen


JE_SCHRITT = {
    'in jedem Schritt: offen_gesamt <= summe_forderungen - summe_zahlungen':
        _offen_nicht_ueber_forderung,
}

AM_ENDE = {
    # Fall 01
    'schluss_netto == auftragssumme_netto': _schluss_netto_gleich_auftragssumme,
    'summe_zahlungen == schluss_brutto': _zahlungen_gleich_schluss_brutto,
    'offen_gesamt == 0': _saldo_null,
    'schluss_ust_abgesetzt + schluss_ust_rest == schluss_ust':
        _steuer_abgesetzt_plus_rest,
    # Fall 02
    'schluss_netto == 60840.00': _netto_gleich('60840.00'),
    'summe_zahlungen == schluss_brutto bis auf 0.01 je Abschlag':
        _zahlungen_gleich_schluss_brutto_bis_auf_rundung,
    'schluss_zeithonorar <= 10500.00': _zeithonorar_hoechstens('10500.00'),
    'für jede Rechnung: netto und ust unabhängig vom Einbehalt':
        _einbehalt_mindert_nichts,
    'nummernkreis(AR3) == 2026': _nummernkreis('AR3', 2026),
    # Fall 03
    'steuersatz(SR, LABOR) == 19.00': _steuersatz_der_position('SR', 'LABOR', '19.00'),
    'summe_zahlungen + summe_skonti == schluss_brutto':
        _zahlungen_und_skonti_gleich_schluss_brutto,
    'betrag(SR, BERICHT) == 7800.00': _betrag_der_position('SR', 'BERICHT', '7800.00'),
    # Fall 04
    'summe_netto(nicht storniert) == 19540.00': _summe_nicht_stornierter('19540.00'),
    'RE1 + Storno(RE1) == 0': _rechnung_plus_storno_null,
    'offen(HOLDING) == 0 and guthaben(HOLDING) == 0': _dritter_ohne_saldo('HOLDING'),
    'anrechnungen(Zahlung Schritt 5) == 1': _zahlung_einmal_angerechnet('10000.00'),
    'nummernkreis(Storno) == nummernkreis(RE2) == 2027 and nummernkreis(RE1) == 2026':
        _nummern_nach_jahreswechsel,
    'leistungszeitraum(RE2) == 2026-06 bis 2026-11': _zeitraum_re2,
    # Fall 05
    'summe_netto(Schlussrechnungen, nicht storniert) == 46080.00':
        _schlussrechnungen_netto('46080.00'),
    'für jede Leistung: anzahl(Schlussrechnungen, nicht storniert) <= 1':
        _keine_leistung_doppelt,
    'abgesetzt(AR2) == 0': _abschlag_ohne_abzug('AR2'),
    'summe_zahlungen + summe_skonti_berechtigt == 54835.20':
        _zahlungen_und_skonti_gleich('54835.20'),
    'in R2.A: keine Rechnungskorrektur über 411,26 €':
        _keine_rechnungskorrektur_ueber('411.26'),
}
