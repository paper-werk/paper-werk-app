"""Randfälle beim Absetzen von Abschlägen.

Ergänzt ``faktura/tests/test_abnahme.py`` (Regelfall: Teil- und
Schlussrechnung, BT-113, BR-CO-16, Korrektur) um die Fälle aus
``docs/rechenregister.md``, Abschnitt L, in denen ein Abschlag doppelt
oder gar nicht abgesetzt würde und der Zahlbetrag falsch wäre:

* zwei Entwürfe zugleich (R-167, "ein Entwurf zählt mit")
* eine korrigierte Abschlagsrechnung: der stornierte zählt nicht, der neue
  genau einmal (R-165)
* ein Abschlag mit zwei Steuersätzen: die Abzugszeilen je Satz, BT-113 als
  Differenz (R-166, R-168)
* der Hinweis "noch nicht bezahlt" mit einem Teilbetrag (R-169)
* das Entgelt einer Teilleistung mit Mengen, die je Position runden (R-170)
* die Summen über Positionen, in denen die Abzugszeile mitläuft
"""

from datetime import date
from decimal import Decimal

import pytest

from faktura import facturx, services
from faktura.models import (
    Abnahme,
    Abnahmeart,
    BelegStatus,
    BelegTyp,
    Kontakt,
    Projekt,
    Rechnungsart,
)
from faktura.tests.test_pdf import xml_wert

pytestmark = pytest.mark.django_db

ABNAHME = date(2026, 3, 10)


@pytest.fixture
def projekt(db):
    kunde = Kontakt.anlegen(
        nummer='K-3000', name='Stadtwerke Beispiel', strasse='Ring 1',
        plz='80331', ort='München', ust_id='DE111222333')
    return Projekt.objects.create(
        nummer='2026-201', bezeichnung='Pumpwerk Ost', kunde=kunde)


@pytest.fixture
def auftrag(projekt):
    beleg = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.AUFTRAG,
                                   betreff='Planung Pumpwerk')
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Planung', menge=Decimal('1'),
        einheit='pausch', einzelpreis=Decimal('40000.00'),
        steuersatz='19.00')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


def _abschlag(projekt, *zeilen, festschreiben=True):
    """Abschlag mit ``(betrag, steuersatz)`` je Zeile."""
    beleg = services.beleg_anlegen(
        projekt=projekt, typ=BelegTyp.RECHNUNG,
        rechnungsart=Rechnungsart.ABSCHLAG, betreff='Abschlag',
        leistungsdatum=date(2025, 11, 1), leistungsdatum_bis=date(2025, 11, 30))
    for betrag, satz in zeilen:
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung=f'Abschlag {satz}', menge=Decimal('1'),
            einheit='pausch', einzelpreis=Decimal(betrag), steuersatz=satz)
    if festschreiben:
        return services.beleg_festschreiben(beleg_id=beleg.pk)
    return beleg


def _schluss(auftrag, leistung='40000.00'):
    """Schlussrechnung zur Gesamtabnahme mit einer Leistungszeile."""
    gesamt = Abnahme.objects.filter(auftrag=auftrag, art=Abnahmeart.GESAMT).first()
    if gesamt is None:
        gesamt = Abnahme.objects.create(
            auftrag=auftrag, art=Abnahmeart.GESAMT, abgenommen_am=ABNAHME)
    schluss = services.rechnung_aus_abnahme(abnahme_id=gesamt.pk)
    services.position_hinzufuegen(
        beleg=schluss, bezeichnung='Planung', menge=Decimal('1'),
        einheit='pausch', einzelpreis=Decimal(leistung),
        steuersatz='19.00')
    return schluss


def _bezahlen(beleg):
    """Voll bezahlt, weil die Schlussrechnung den Abschlag sonst als
    Restzeile erneut fordert (R-174) und netto nichts abgesetzt bleibt."""
    services.zahlung_verbuchen(beleg_id=beleg.pk, datum=ABNAHME,
                               betrag=services.belegsummen(beleg).brutto)
    return beleg


def _abgesetzt(rechnung) -> list:
    """Von der Rechnung abgesetzte Abschläge, ohne Restzeilen."""
    return [p.abgesetzte_position.beleg
            for p in rechnung.positionen.filter(ist_abzug=True,
                                                ist_abschlagsrest=False)
            .select_related('abgesetzte_position__beleg')]


class TestGenauEinmal:

    def test_ein_zweiter_entwurf_setzt_nicht_noch_einmal_ab(self, projekt, auftrag):
        """R-167: Ein Entwurf zählt mit, weil derselbe Abschlag sonst auf zwei
        Rechnungen stünde und nach dem Festschreiben beider zweimal
        abgesetzt wäre."""
        abschlag = _abschlag(projekt, ('3000.00', '19.00'))
        erster = _schluss(auftrag)

        # Zweite Schlussrechnung manuell angelegt, dann absetzen.
        zweiter = services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG,
            rechnungsart=Rechnungsart.SCHLUSS, betreff='Zweiter Versuch',
            leistungsdatum=ABNAHME)
        services.abschlaege_absetzen(beleg_id=zweiter.pk)

        assert _abgesetzt(erster) == [abschlag]
        assert _abgesetzt(zweiter) == []

    def test_ein_geloeschter_entwurf_gibt_den_abschlag_frei(self, projekt, auftrag):
        abschlag = _abschlag(projekt, ('3000.00', '19.00'))
        erster = _schluss(auftrag)
        erster.positionen.all().delete()
        erster.delete()

        zweiter = _schluss(auftrag)

        assert _abgesetzt(zweiter) == [abschlag]

    def test_ein_korrigierter_abschlag_zaehlt_nur_einmal(self, projekt, auftrag):
        """R-165: Der stornierte Abschlag gilt nicht als gestellt, sein Storno
        setzt nichts ab, der neue zählt ab dem Festschreiben."""
        alt = _abschlag(projekt, ('3000.00', '19.00'))
        _storno, neu = services.rechnung_korrigieren(beleg_id=alt.pk)
        neu = _bezahlen(services.beleg_festschreiben(beleg_id=neu.pk))
        alt.refresh_from_db()
        assert alt.status == BelegStatus.STORNIERT

        schluss = _schluss(auftrag)

        assert _abgesetzt(schluss) == [neu]
        assert services.belegsummen(schluss).netto == Decimal('37000.00')

    def test_ein_abschlag_im_entwurf_wird_nicht_abgesetzt(self, projekt, auftrag):
        """Nur gestellte Abschläge, weil ein Entwurf keine Forderung ist."""
        _abschlag(projekt, ('3000.00', '19.00'), festschreiben=False)

        assert _abgesetzt(_schluss(auftrag)) == []


class TestZweiSaetze:
    """R-166/R-168: Abschlag mit 19 % und 7 %; Abzugszeilen je Satz, Steuer
    je Satz, BT-113 als Differenz der Bruttosummen."""

    @pytest.fixture
    def schluss(self, projekt, auftrag):
        _bezahlen(_abschlag(projekt, ('1000.01', '19.00'),
                            ('333.33', '7.00')))
        return services.beleg_festschreiben(beleg_id=_schluss(auftrag).pk)

    def test_je_satz_eine_abzugszeile(self, schluss):
        abzuege = {p.steuersatz: p.einzelpreis
                   for p in schluss.positionen.filter(ist_abzug=True)}
        assert not schluss.positionen.filter(ist_abschlagsrest=True).exists()

        assert abzuege == {'19.00': Decimal('-1000.01'),
                           '7.00': Decimal('-333.33')}

    def test_die_summen_rechnen_je_satz(self, schluss):
        summen = services.belegsummen(schluss)
        anteile = {a.satz: (a.netto, a.steuer) for a in summen.anteile}

        # 40.000,00 - 1.000,01 = 38.999,99 zu 19 % -> 7.409,9981 -> 7.410,00
        # -333,33 zu 7 % -> -23,3331 -> -23,33
        assert anteile[Decimal('19')] == (Decimal('38999.99'), Decimal('7410.00'))
        assert anteile[Decimal('7')] == (Decimal('-333.33'), Decimal('-23.33'))
        assert summen.brutto == Decimal('38999.99') + Decimal('7410.00') \
            - Decimal('333.33') - Decimal('23.33')

    def test_bt_113_ist_die_differenz_und_bt_115_der_zahlbetrag(self, schluss):
        voll = services.leistungssummen(schluss)
        zahlbetrag = services.belegsummen(schluss).brutto
        xml = facturx.xml_erzeugen(schluss).decode()

        assert voll.brutto == Decimal('47600.00')
        assert Decimal(xml_wert(xml, 'GrandTotalAmount')) == voll.brutto
        assert Decimal(xml_wert(xml, 'TotalPrepaidAmount')) == voll.brutto - zahlbetrag
        assert Decimal(xml_wert(xml, 'DuePayableAmount')) == zahlbetrag

    def test_offener_posten_ist_der_zahlbetrag(self, schluss):
        """Der offene Posten entspricht dem Zahlbetrag in PDF und XML."""
        assert services.offener_betrag(schluss) == services.belegsummen(schluss).brutto


class TestHinweisNochNichtBezahlt:

    def test_nennt_den_offenen_rest_nicht_den_abschlag(self, projekt, auftrag):
        """R-169: Der Hinweis rechnet über R-147 und nennt nach einer
        Teilzahlung den Rest."""
        abschlag = _abschlag(projekt, ('3000.00', '19.00'))
        services.zahlung_verbuchen(beleg_id=abschlag.pk, datum=ABNAHME,
                                   betrag=Decimal('1000.00'))

        befund = services.offene_abgesetzte_abschlaege(_schluss(auftrag))

        assert [(o.abschlag, o.offen) for o in befund] == [
            (abschlag, Decimal('2570.00'))]
        assert '2.570,00' in str(befund[0])


class TestEntgeltDerTeilleistung:

    def test_rundet_je_position_wie_der_beleg(self, auftrag):
        """R-170: Summe der Positionsnetti nach R-001, nicht Menge mal Preis
        über alles gerundet. 0,125 x 100,02 = 12,5025 je Position auf 12,50;
        zwei Positionen 25,00, über alles gerundet 25,01."""
        stunden = services.beleg_anlegen(
            projekt=auftrag.projekt, typ=BelegTyp.AUFTRAG, betreff='Stunden')
        for bezeichnung in ('Prüfung A', 'Prüfung B'):
            services.position_hinzufuegen(
                beleg=stunden, bezeichnung=bezeichnung, menge=Decimal('0.125'),
                einheit='Std', einzelpreis=Decimal('100.02'),
                steuersatz='19.00')
        stunden = services.beleg_festschreiben(beleg_id=stunden.pk)
        teil = Abnahme.objects.create(
            auftrag=stunden, art=Abnahmeart.TEIL, abgenommen_am=ABNAHME)
        teil.positionen.add(*stunden.positionen.all())

        assert teil.entgelt_netto == Decimal('25.00')
        assert teil.entgelt_netto == sum(
            (services.positionssumme(menge=p.menge, einzelpreis=p.einzelpreis)
             for p in stunden.positionen.all()), Decimal('0.00'))


class TestAndereSummen:
    """Verhalten der Abzugszeile in anderen Summen über Positionen
    (``docs/rechenregister.md``, Regeln für Änderungen)."""

    @pytest.fixture
    def schluss(self, projekt, auftrag):
        _abschlag(projekt, ('3000.00', '19.00'))
        return services.beleg_festschreiben(beleg_id=_schluss(auftrag).pk)

    def test_die_abzugszeile_haengt_an_keiner_auftragsposition(self, schluss):
        """Voraussetzung dafür, dass R-008, R-162 und R-163 sie nicht zählen,
        weil sie je Auftragsposition summieren."""
        abzuege = schluss.positionen.filter(ist_abzug=True)

        assert abzuege.exists()
        assert not abzuege.filter(auftragsposition__isnull=False).exists()

    def test_fakturiert_ist_die_volle_leistung_nicht_mehr(self, projekt, schluss):
        """R-023, R-028, R-031: Abschlag plus Schlussrechnung mit Abzug
        ergeben netto genau die volle Leistung."""
        voll = services.leistungssummen(schluss).netto
        stand = next(s for s in services.projektstaende(nur_laufende=False)
                     if s.projekt == projekt)

        assert voll == Decimal('40000.00')
        assert stand.fakturiert == voll
        assert stand.abgerechnete_leistung == voll
        # Beide Belege haben das Datum ihres Festschreibens.
        jahre = {schluss.belegdatum.year, stand.projekt.belege.filter(
            rechnungsart=Rechnungsart.ABSCHLAG).get().belegdatum.year}
        assert sum(services.fakturiert_im_jahr(j) for j in jahre) == voll
