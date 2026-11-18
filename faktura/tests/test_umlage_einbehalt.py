"""Umlage und Sicherheitseinbehalt des Auftraggebers (R-189 bis R-191).

Referenzfall: 1. Abschlag über 0,9 × 6.211,00 = 5.589,90 netto, Umlage
„Anteil Versicherung“ 1,1 % vom Netto, Einbehalt 10 % vom Netto bis 5 % der
Auftragssumme. Zahlbetrag **6.019,82**: 5.589,90 − 61,49 = 5.528,41,
zzgl. 1.050,40 USt = 6.578,81, abzgl. 558,99 Einbehalt.

Zweiter Fall: Einbehalt 5 % vom Brutto ohne Grenze, kumuliert über zwei
Abschläge (13.081,00 und 16.410,50 netto): 778,32, dann 976,42, zusammen
5 % von 35.094,89.
"""

from datetime import date
from decimal import Decimal

import pytest

from faktura import facturx, pdf, services
from faktura.models import (
    Abnahme,
    Abnahmeart,
    Abzugsgrundlage,
    BelegStatus,
    BelegTyp,
    Kontakt,
    Projekt,
    Rechnungsart,
    Zeilenart,
)
from faktura.tests.test_pdf import xml_wert

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-3200', name='Planungsgesellschaft Nord', strasse='Hafenweg 3',
        plz='84028', ort='Landshut', ust_id='DE123123124')


def _projekt(kunde, **einstellungen):
    return Projekt.objects.create(
        nummer=f'2026-{Projekt.objects.count() + 400}',
        bezeichnung='Revitalisierung Hauptgebäude', kunde=kunde,
        **einstellungen)


@pytest.fixture
def versicherung(kunde):
    """Umlage 1,1 % netto, Einbehalt 10 % netto bis 5 %."""
    return _projekt(
        kunde, umlage_bezeichnung='Anteil Versicherung',
        umlage_prozent=D('1.1'), einbehalt_prozent=D('10'),
        einbehalt_grenze=D('5'))


def _auftrag(projekt, betrag, nachtrag_zu=None):
    if nachtrag_zu is None:
        beleg = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.AUFTRAG,
                                       betreff='Planung')
    else:
        beleg = services.nachtrag_anlegen(beleg_id=nachtrag_zu.pk)
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Planung', menge=D('1'), einheit='pausch',
        einzelpreis=D(betrag), steuersatz='19.00')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


def _abschlag(projekt, menge, preis, festschreiben=True):
    beleg = services.beleg_anlegen(
        projekt=projekt, typ=BelegTyp.RECHNUNG,
        rechnungsart=Rechnungsart.ABSCHLAG, betreff='Abschlag',
        leistungsdatum=date(2026, 1, 1), leistungsdatum_bis=date(2026, 6, 30))
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Restleistungen Schadstoffplanung',
        menge=D(menge), einheit='pausch', einzelpreis=D(preis),
        steuersatz='19.00')
    services.zuschlaege_ergaenzen(beleg)
    if festschreiben:
        return services.beleg_festschreiben(beleg_id=beleg.pk)
    beleg.refresh_from_db()
    return beleg


class TestReferenzfall:
    """Umlage vom Netto, Einbehalt vom Netto."""

    @pytest.fixture
    def abschlag(self, versicherung):
        _auftrag(versicherung, '100000.00')
        return _abschlag(versicherung, '0.9', '6211.00')

    def test_umlage_als_zeile_vor_der_steuer(self, abschlag):
        umlage = abschlag.positionen.get(zeilenart=Zeilenart.ZUSCHLAG)
        assert umlage.bezeichnung == 'Anteil Versicherung'
        assert umlage.zuschlag_prozent == D('-1.10')
        assert umlage.einzelpreis == D('-61.49')
        summen = services.belegsummen(abschlag)
        assert (summen.netto, summen.steuer, summen.brutto) == (
            D('5528.41'), D('1050.40'), D('6578.81'))

    def test_einbehalt_vom_netto_vor_der_umlage(self, abschlag):
        assert abschlag.einbehalt == D('558.99')
        assert abschlag.umlage_nach_steuer == D('0.00')
        assert services.zahlbetrag(abschlag) == D('6019.82')
        assert abschlag.einbehalt_text == (
            'Sicherheitseinbehalt 10 % aus 5.589,90 netto')

    def test_offener_posten_ist_der_zahlbetrag(self, abschlag):
        assert services.offener_betrag(abschlag) == D('6019.82')
        services.zahlung_verbuchen(beleg_id=abschlag.pk,
                                   datum=date(2026, 7, 20),
                                   betrag=D('6019.82'))
        assert services.offener_betrag(abschlag) == D('0.00')
        assert abschlag not in [p.beleg for p in services.offene_posten(
            date(2026, 12, 31)).posten]

    def test_pdf(self, abschlag):
        html = pdf.beleg_als_html(abschlag)
        assert 'Summe brutto' in html
        assert 'Sicherheitseinbehalt 10 % aus 5.589,90 netto' in html
        assert '-558,99 EUR' in html
        assert '6.019,82 EUR' in html

    def test_e_rechnung(self, abschlag):
        xml = facturx.xml_erzeugen(abschlag).decode()
        assert D(xml_wert(xml, 'GrandTotalAmount')) == D('6578.81')
        assert D(xml_wert(xml, 'DuePayableAmount')) == D('6578.81')
        assert 'Zahlbetrag 6.019,82 EUR' in xml_wert(xml, 'Description')

    def test_maske(self, abschlag):
        from faktura.admin.spalten import SpaltenMixin
        html = SpaltenMixin().summenaufstellung(abschlag)
        assert 'Sicherheitseinbehalt' in html
        assert '6.019,82' in html

    def test_storno_spiegelt_neufassung_rechnet_neu(self, abschlag):
        storno, neu = services.rechnung_korrigieren(beleg_id=abschlag.pk)
        assert storno.einbehalt == D('-558.99')
        assert services.zahlbetrag(storno) == D('-6019.82')
        neu.refresh_from_db()
        assert neu.einbehalt == D('558.99')


class TestUmlageVomBrutto:
    def test_gleicher_zahlbetrag_hoehere_steuer(self, kunde):
        projekt = _projekt(
            kunde, umlage_bezeichnung='Anteil Versicherung',
            umlage_prozent=D('1.1'), umlage_grundlage=Abzugsgrundlage.BRUTTO,
            einbehalt_prozent=D('10'))
        abschlag = _abschlag(projekt, '0.9', '6211.00')

        assert not abschlag.positionen.filter(
            zeilenart=Zeilenart.ZUSCHLAG).exists()
        summen = services.belegsummen(abschlag)
        assert (summen.steuer, summen.brutto) == (D('1062.08'), D('6651.98'))
        assert abschlag.umlage_nach_steuer == D('73.17')
        assert abschlag.einbehalt == D('558.99')
        assert services.zahlbetrag(abschlag) == D('6019.82')
        assert abschlag.umlage_text == (
            'Anteil Versicherung 1,1 % aus 6.651,98 brutto')


class TestUmlagezeile:
    def test_nicht_doppelt(self, versicherung):
        beleg = _abschlag(versicherung, '1', '1000.00', festschreiben=False)
        assert services.umlage_ergaenzen(beleg) is None
        assert beleg.positionen.filter(
            zeilenart=Zeilenart.ZUSCHLAG).count() == 1

    def test_geloescht_bleibt_geloescht_mit_hinweis(self, versicherung):
        beleg = _abschlag(versicherung, '1', '1000.00', festschreiben=False)
        beleg.positionen.filter(zeilenart=Zeilenart.ZUSCHLAG).delete()
        services.zuschlaege_nachrechnen(beleg)
        assert not beleg.positionen.filter(
            zeilenart=Zeilenart.ZUSCHLAG).exists()
        assert services.fehlende_umlage(beleg) == 'Anteil Versicherung -1,1 %'


class TestGrenze:
    """Auftrag 10.000 netto, Grenze 5 % = 500, Einbehalt 10 % je Abschlag
    über 3.000: 300, dann der Rest 200, dann nichts."""

    @pytest.fixture
    def projekt(self, kunde):
        return _projekt(kunde, einbehalt_prozent=D('10'),
                        einbehalt_grenze=D('5'))

    def test_rest_bis_zur_grenze(self, projekt):
        _auftrag(projekt, '10000.00')
        ab1 = _abschlag(projekt, '1', '3000.00')
        ab2 = _abschlag(projekt, '1', '3000.00')
        ab3 = _abschlag(projekt, '1', '3000.00')
        assert [ab1.einbehalt, ab2.einbehalt, ab3.einbehalt] == [
            D('300.00'), D('200.00'), D('0.00')]
        assert ab2.einbehalt_text == (
            'Sicherheitseinbehalt 10 % aus 6.000,00 netto, bisher '
            'einbehalten 300,00, höchstens 5 % von 10.000,00 Auftragssumme')
        # Die Zeile bleibt mit 0,00 sichtbar.
        assert services.abzuege_nach_steuer(ab3) == [
            (ab3.einbehalt_text, D('0.00'))]

    def test_nachtrag_hebt_die_grenze(self, projekt):
        haupt = _auftrag(projekt, '10000.00')
        _abschlag(projekt, '1', '3000.00')
        _abschlag(projekt, '1', '3000.00')
        _auftrag(projekt, '4000.00', nachtrag_zu=haupt)
        ab3 = _abschlag(projekt, '1', '3000.00')
        # 5 % von 14.000 = 700, bisher 500.
        assert ab3.einbehalt == D('200.00')

    def test_ohne_auftrag_keine_grenze(self, projekt):
        assert _abschlag(projekt, '1', '3000.00').einbehalt == D('300.00')


class TestKumuliertVomBrutto:
    """5 % vom Brutto ohne Grenze über zwei Abschläge."""

    def test_zweiter_abschlag(self, kunde):
        projekt = _projekt(kunde, einbehalt_prozent=D('5'),
                           einbehalt_grundlage=Abzugsgrundlage.BRUTTO)
        ab1 = _abschlag(projekt, '1', '13081.00')
        ab2 = _abschlag(projekt, '1', '16410.50')
        assert ab1.einbehalt == D('778.32')
        assert services.zahlbetrag(ab1) == D('14788.07')
        assert ab2.einbehalt == D('976.42')
        assert services.zahlbetrag(ab2) == D('18552.08')
        assert ab1.einbehalt + ab2.einbehalt == D('1754.74')
        assert ab2.einbehalt_text == (
            'Sicherheitseinbehalt 5 % aus 35.094,89 brutto, bisher '
            'einbehalten 778,32')

    def test_entwurf_als_vorgaenger_zaehlt_nicht(self, kunde):
        projekt = _projekt(kunde, einbehalt_prozent=D('5'))
        _abschlag(projekt, '1', '1000.00', festschreiben=False)
        assert _abschlag(projekt, '1', '2000.00').einbehalt == D('100.00')


class TestSchlussrechnung:
    """Nach dem Referenzabschlag, bezahlt mit dem Zahlbetrag, die volle
    Leistung 6.211,00: Die Restzeile fordert den Einbehalt mit Steuer
    zurück. Insgesamt 7.309,79 = 6.142,68 zzgl. 19 % USt."""

    def test_einbehalt_kommt_ueber_die_restzeile(self, versicherung):
        auftrag = _auftrag(versicherung, '100000.00')
        abschlag = _abschlag(versicherung, '0.9', '6211.00')
        services.zahlung_verbuchen(beleg_id=abschlag.pk,
                                   datum=date(2026, 7, 20),
                                   betrag=D('6019.82'))
        gesamt = Abnahme.objects.create(
            auftrag=auftrag, art=Abnahmeart.GESAMT,
            abgenommen_am=date(2026, 9, 1))
        schluss = services.rechnung_aus_abnahme(abnahme_id=gesamt.pk)
        services.position_hinzufuegen(
            beleg=schluss, bezeichnung='Planung LPH 3', menge=D('1'),
            einheit='pausch', einzelpreis=D('6211.00'), steuersatz='19.00')
        services.abschlaege_absetzen(beleg_id=schluss.pk)
        schluss = services.beleg_festschreiben(beleg_id=schluss.pk)

        assert schluss.status == BelegStatus.FESTGESCHRIEBEN
        assert schluss.einbehalt == D('0.00')
        assert schluss.positionen.filter(
            zeilenart=Zeilenart.ZUSCHLAG, ist_abzug=False).count() == 1
        assert services.zahlbetrag(schluss) == D('1289.97')
        assert D('6019.82') + services.zahlbetrag(schluss) == D('7309.79')
        assert services.offener_betrag(abschlag) == D('0.00')
