"""Offene Beträge unter einem Euro (R-147, R-150, R-174, R-176, R-192).

Ein Rest von wenigen Cent ist offen wie jeder andere, etwa nach einer
Zahlung mit Rundungsdifferenz. Die Tests sichern die Grenze bei null.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from faktura import services
from faktura.models import (
    Abnahme,
    Abnahmeart,
    Abzugsgrundlage,
    Beleg,
    BelegTyp,
    Kontakt,
    Projekt,
    Rechnungsart,
    Zahlung,
    Zahlungszuordnung,
)
from faktura.services.zahlungen import (
    ZAHLUNGSSTAND_BEZAHLT,
    ZAHLUNGSSTAND_OFFEN,
    Einbehalten,
)

pytestmark = pytest.mark.django_db

EINGANG = date(2026, 2, 20)


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(nummer='K-5300', name='Muster GmbH',
                           strasse='Hauptstraße 1', plz='10115',
                           ort='Berlin')


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(nummer='2026-530', bezeichnung='Anbau',
                                  kunde=kunde)


def _rechnung(kunde, preis, **felder):
    beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG,
                                   betreff='Beratung',
                                   leistungsdatum=EINGANG, **felder)
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Beratung', menge=Decimal('1'),
        einheit='LS', einzelpreis=Decimal(preis), steuersatz='19.00')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


def _zahlen(beleg, betrag, **felder):
    return services.zahlung_verbuchen(
        beleg_id=beleg.pk, datum=EINGANG, betrag=Decimal(betrag),
        **{k: Decimal(v) for k, v in felder.items()})


def _offene_posten():
    return {p.beleg: p.offen for p in services.offene_posten().posten}


class TestRechnung:

    @pytest.fixture
    def rechnung(self, kunde):
        """1.000,00 netto, 1.190,00 brutto, bezahlt 1.189,50."""
        beleg = _rechnung(kunde, '1000.00')
        _zahlen(beleg, '1189.50')
        return beleg

    def test_offener_betrag(self, rechnung):
        assert services.offener_betrag(rechnung) == Decimal('0.50')

    def test_zahlungsstand(self, rechnung):
        assert services.zahlungsstand(rechnung) == ZAHLUNGSSTAND_OFFEN

    def test_offener_posten(self, rechnung):
        assert _offene_posten() == {rechnung: Decimal('0.50')}

    def test_zahlung_von_5_cent(self, kunde):
        Zahlung(datum=EINGANG, betrag=Decimal('0.05'),
                kunde=kunde).full_clean()

    def test_kuerzung_von_50_cent_nur_am_abschlag(self, kunde):
        rechnung = _rechnung(kunde, '1000.00')
        zahlung = Zahlung.objects.create(datum=EINGANG,
                                         betrag=Decimal('1189.50'),
                                         kunde=kunde)
        zuordnung = Zahlungszuordnung(zahlung=zahlung, beleg=rechnung,
                                      betrag=Decimal('1189.50'),
                                      kuerzung=Decimal('0.50'))

        with pytest.raises(ValidationError) as fehler:
            zuordnung.full_clean()

        assert 'kuerzung' in fehler.value.message_dict

    def test_rechnung_unter_einem_euro_ohne_zahlung(self, kunde):
        """0,42 netto, 0,50 brutto."""
        rechnung = _rechnung(kunde, '0.42')

        assert _offene_posten() == {rechnung: Decimal('0.50')}

    def test_zahlung_von_50_cent_verbuchen(self, kunde):
        rechnung = _rechnung(kunde, '0.42')
        _zahlen(rechnung, '0.50')

        assert _offene_posten() == {}

    def test_skonto_ueber_dem_gezahlten(self, kunde):
        """0,50 brutto, gezahlt 0,10, Skonto 0,40."""
        rechnung = _rechnung(kunde, '0.42')
        _zahlen(rechnung, '0.10', skonto='0.40')

        assert services.offener_betrag(rechnung) == Decimal('0.00')

    def test_ohne_betrag_und_skonto_nichts_zu_verbuchen(self, rechnung):
        with pytest.raises(services.UngueltigerBetrag):
            _zahlen(rechnung, '0.00')


class TestAbschlag:

    def test_voll_bezahlt_heisst_bezahlt(self, projekt):
        """Ohne Schlussrechnung ist ein bezahlter Abschlag bezahlt, nicht
        abgerechnet."""
        abschlag = _abschlag(projekt)
        _zahlen(abschlag, '3570.00')

        assert services.zahlungsstand(abschlag) == ZAHLUNGSSTAND_BEZAHLT

    def test_restzeile_fuer_50_cent(self, projekt):
        """3.570,00 brutto, bezahlt 3.569,50: Restzeile
        3.000 x 0,50 / 3.570 = 0,42; gemeldet werden 0,50 offen."""
        auftrag = _auftrag(projekt)
        abschlag = _abschlag(projekt)
        _zahlen(abschlag, '3569.50')

        schluss = services.rechnung_aus_abnahme(
            abnahme_id=Abnahme.objects.create(
                auftrag=auftrag, art=Abnahmeart.GESAMT,
                abgenommen_am=EINGANG).pk)

        rest = schluss.positionen.get(ist_abschlagsrest=True)
        assert rest.einzelpreis == Decimal('0.42')
        assert [(o.abschlag, o.offen) for o in
                services.offene_abgesetzte_abschlaege(schluss)] == [
            (abschlag, Decimal('0.50'))]


    def test_hinweis_auf_kuerzung_von_50_cent(self, projekt, kunde):
        """Kürzung 0,50 am Abschlag, danach 0,50 ohne Zuordnung."""
        abschlag = _abschlag(projekt)
        _zahlen(abschlag, '3569.50', kuerzung='0.50')
        nachzahlung = Zahlung.objects.create(datum=EINGANG,
                                             betrag=Decimal('0.50'),
                                             kunde=kunde)

        assert [z.beleg for z in services.gekuerzte_abschlaege(
            nachzahlung)] == [abschlag]

    def test_sicherheitseinbehalt_von_50_cent(self, kunde):
        """5 % von 10,00 brutto (8,40 netto)."""
        projekt = Projekt.objects.create(
            nummer='2026-531', bezeichnung='Carport', kunde=kunde,
            einbehalt_prozent=Decimal('5'),
            einbehalt_grundlage=Abzugsgrundlage.BRUTTO)
        abschlag = _abschlag(projekt, '8.40')

        assert abschlag.einbehalt == Decimal('0.50')
        assert services.einbehalten(
            Beleg.objects.filter(projekt=projekt)).abschlaege == Decimal(
            '0.50')


def test_maengeleinbehalt_von_50_cent(projekt):
    """Schlussrechnung über 11.900,00 brutto, bezahlt 11.899,50."""
    auftrag = _auftrag(projekt)
    schluss = services.rechnung_aus_abnahme(
        abnahme_id=Abnahme.objects.create(
            auftrag=auftrag, art=Abnahmeart.GESAMT,
            abgenommen_am=EINGANG).pk)
    services.position_hinzufuegen(
        beleg=schluss, bezeichnung='Planung', menge=Decimal('1'),
        einheit='LS', einzelpreis=Decimal('10000.00'), steuersatz='19.00',
        auftragsposition=auftrag.positionen.get())
    schluss = services.beleg_festschreiben(beleg_id=schluss.pk)
    _zahlen(schluss, '11899.50', einbehalten='0.50')

    assert services.einbehalten(
        Beleg.objects.filter(projekt=projekt)).schlussrechnungen == Decimal(
        '0.50')


def _auftrag(projekt):
    beleg = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.AUFTRAG,
                                   betreff='Planung')
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Planung', menge=Decimal('1'), einheit='LS',
        einzelpreis=Decimal('10000.00'), steuersatz='19.00')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


def _abschlag(projekt, preis='3000.00'):
    """Vorgabe 3.000,00 netto, 3.570,00 brutto."""
    beleg = services.beleg_anlegen(
        projekt=projekt, typ=BelegTyp.RECHNUNG,
        rechnungsart=Rechnungsart.ABSCHLAG, betreff='Abschlag',
        leistungsdatum=date(2026, 1, 1), leistungsdatum_bis=date(2026, 1, 31))
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Leistungsstand', menge=Decimal('1'),
        einheit='LS', einzelpreis=Decimal(preis), steuersatz='19.00')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


def test_einbehalten_gesamt():
    """R-192: Sicherheitseinbehalt der Abschläge plus Einbehalten an
    Schlussrechnungen."""
    assert Einbehalten(abschlaege=Decimal('238.00'),
                       schlussrechnungen=Decimal('357.00')
                       ).gesamt == Decimal('595.00')
