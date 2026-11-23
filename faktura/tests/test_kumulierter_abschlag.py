"""Kumulierte Abschlagsrechnung (R-183 bis R-186).

Ab dem zweiten Abschlag zeigen PDF, XML und Maske den Leistungsstand, die
bereits berechneten Abschläge und als Abschlagsbetrag die Differenz.
Gespeichert bleibt der Zuwachs; geprüft wird vor allem, dass Leistungsstand
minus Vorgänger je Steuersatz auf den Cent die Belegsumme ergibt.
"""

import re
from datetime import date
from decimal import Decimal

import pytest

from faktura import facturx, pdf, services
from faktura.models import (
    Abnahme,
    Abnahmeart,
    BelegTyp,
    Kontakt,
    Projekt,
    Rechnungsart,
)
from faktura.tests.test_pdf import xml_wert


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-4200', name='Rizgar GmbH', strasse='Winzererstraße 90',
        plz='80797', ort='München', ust_id='DE222333444')


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(
        nummer='2026-011', bezeichnung='Hort Tagesraum', kunde=kunde)


@pytest.fixture
def auftrag(projekt):
    beleg = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.AUFTRAG,
                                   betreff='Deklaration')
    for nummer, text, menge, einheit, preis in (
            ('1.1', 'Stundenleistung Dipl.-Ing.', '40', 'HUR', '85.00'),
            ('2.3', 'LVGBT', '20', 'C62', '198.00'),
            ('3.1', 'Gutachten', '1', 'LS', '6000.00')):
        services.position_hinzufuegen(
            beleg=beleg, position=nummer, bezeichnung=text,
            menge=Decimal(menge), einheit=einheit,
            einzelpreis=Decimal(preis), steuersatz='19.00')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


def _ap(auftrag, nummer):
    return auftrag.positionen.get(position=nummer)


def _abschlag(projekt, *zeilen, tag, festschreiben=True):
    """``zeilen``: (Auftragsposition oder None, Bezeichnung, Menge, Einheit,
    Preis, Satz)."""
    beleg = services.beleg_anlegen(
        projekt=projekt, typ=BelegTyp.RECHNUNG,
        rechnungsart=Rechnungsart.ABSCHLAG, betreff='Abschlag',
        leistungsdatum=tag, leistungsdatum_bis=tag, belegdatum=tag)
    for ap, text, menge, einheit, preis, satz in zeilen:
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung=text, menge=Decimal(menge),
            einheit=einheit, einzelpreis=Decimal(preis), steuersatz=satz,
            auftragsposition=ap, leistung_von=tag, leistung_bis=tag)
    if festschreiben:
        beleg = services.beleg_festschreiben(beleg_id=beleg.pk)
    return beleg


def _zeilen(kumuliert):
    return [(p.position, p.bezeichnung, p.menge, p.einheit, p.einzelpreis)
            for p in kumuliert.positionen]


def _netto_je_satz(kumuliert) -> dict[Decimal, Decimal]:
    """Leistungsstand plus Abzüge je Satz."""
    summe: dict[Decimal, Decimal] = {}
    for p in kumuliert.positionen:
        summe[p.steuersatz_dezimal] = summe.get(
            p.steuersatz_dezimal, Decimal('0.00')) + services.positionssumme(
                menge=p.menge, einzelpreis=p.einzelpreis)
    for a in kumuliert.abzuege:
        summe[a.steuersatz_dezimal] = summe.get(
            a.steuersatz_dezimal, Decimal('0.00')) + a.betrag
    return summe


def _belegnetto_je_satz(beleg) -> dict[Decimal, Decimal]:
    return {a.satz: a.netto for a in services.belegsummen(beleg).anteile}


@pytest.fixture
def zwei_abschlaege(projekt, auftrag):
    """AB 1: 1,5 h, 6 LVGBT, Gutachten 2.000 von 6.000, Nebenkosten 50.
    AB 2: 4,5 h, 4 LVGBT, Gutachten 1.000, Nebenkosten 30."""
    stunde, lvgbt, gutachten = (_ap(auftrag, n) for n in ('1.1', '2.3', '3.1'))
    ab1 = _abschlag(
        projekt,
        (stunde, 'Stundenleistung Dipl.-Ing.', '1.5', 'HUR', '85.00', '19.00'),
        (lvgbt, 'LVGBT', '6', 'C62', '198.00', '19.00'),
        (gutachten, 'Gutachten', '1', 'LS', '2000.00', '19.00'),
        (None, 'Nebenkosten', '1', 'LS', '50.00', '19.00'),
        tag=date(2026, 1, 5))
    ab2 = _abschlag(
        projekt,
        (stunde, 'Stundenleistung Dipl.-Ing.', '4.5', 'HUR', '85.00', '19.00'),
        (lvgbt, 'LVGBT', '4', 'C62', '198.00', '19.00'),
        (gutachten, 'Gutachten', '1', 'LS', '1000.00', '19.00'),
        (None, 'Nebenkosten', '1', 'LS', '30.00', '19.00'),
        tag=date(2026, 2, 4), festschreiben=False)
    return ab1, ab2


@pytest.mark.django_db
class TestLeistungsstand:

    def test_der_erste_abschlag_bleibt_einfach(self, zwei_abschlaege):
        ab1, _ = zwei_abschlaege

        assert services.kumulierter_abschlag(ab1) is None

    def test_der_leistungszeitraum_spannt_ueber_die_abschlaege(
            self, zwei_abschlaege):
        _, ab2 = zwei_abschlaege

        kumuliert = services.kumulierter_abschlag(ab2)

        assert {(p.leistung_von, p.leistung_bis)
                for p in kumuliert.positionen} == {
            (date(2026, 1, 5), date(2026, 2, 4))}

    def test_je_auftragsposition_eine_zeile_mit_gesamtmenge(
            self, zwei_abschlaege):
        """Stunden und LVGBT zum Vertragspreis: Mengen addiert. Gutachten in
        Teilbeträgen: als Pauschale 3.000. Nebenkosten ohne Auftrag mit
        verschiedenen Beträgen: eine Zeile, pauschal 80."""
        _, ab2 = zwei_abschlaege

        kumuliert = services.kumulierter_abschlag(ab2)

        assert _zeilen(kumuliert) == [
            ('1.1', 'Stundenleistung Dipl.-Ing.', Decimal('6.000'), 'HUR',
             Decimal('85.00')),
            ('2.3', 'LVGBT', Decimal('10.000'), 'C62', Decimal('198.00')),
            ('3.1', 'Gutachten', Decimal('1'), 'LS', Decimal('3000.00')),
            ('', 'Nebenkosten', Decimal('1'), 'LS', Decimal('80.00')),
        ]

    def test_abgezogen_wird_der_gestellte_vorgaenger(self, zwei_abschlaege):
        """AB 1 netto: 127,50 + 1.188 + 2.000 + 50 = 3.365,50; gestellt,
        nicht bezahlt (es ist keine Zahlung verbucht)."""
        ab1, ab2 = zwei_abschlaege

        (abzug,) = services.kumulierter_abschlag(ab2).abzuege

        assert abzug.bezeichnung == (
            f'1. Abschlagsrechnung {ab1.nummer} vom 05.01.2026')
        assert abzug.betrag == Decimal('-3365.50')

    def test_leistungsstand_minus_vorgaenger_ist_die_belegsumme(
            self, zwei_abschlaege):
        _, ab2 = zwei_abschlaege

        kumuliert = services.kumulierter_abschlag(ab2)

        # AB 2: 382,50 + 792 + 1.000 + 30.
        assert _netto_je_satz(kumuliert) == {Decimal('19.00'):
                                             Decimal('2204.50')}
        assert _netto_je_satz(kumuliert) == _belegnetto_je_satz(ab2)

    def test_rundung_je_position_bleibt_erhalten(self, projekt, auftrag):
        """0,333 h zu 85,00 sind je Abschlag 28,31 (28,305 gerundet),
        zusammen 56,62; 0,666 h zu 85,00 wären 56,61. Die Zeile steht
        deshalb pauschal mit 56,62."""
        stunde = _ap(auftrag, '1.1')
        _abschlag(projekt, (stunde, 'Std', '0.333', 'HUR', '85.00', '19.00'),
                  tag=date(2026, 1, 5))
        ab2 = _abschlag(projekt,
                        (stunde, 'Std', '0.333', 'HUR', '85.00', '19.00'),
                        tag=date(2026, 2, 4), festschreiben=False)

        kumuliert = services.kumulierter_abschlag(ab2)

        assert _zeilen(kumuliert)[0][2:] == (Decimal('1'), 'LS',
                                             Decimal('56.62'))
        assert _netto_je_satz(kumuliert) == _belegnetto_je_satz(ab2)

    def test_zwei_steuersaetze_je_satz_abgezogen(self, projekt, auftrag):
        _abschlag(projekt,
                  (None, 'Planung', '1', 'LS', '1000.00', '19.00'),
                  (None, 'Druckkosten', '1', 'LS', '100.00', '7.00'),
                  tag=date(2026, 1, 5))
        ab2 = _abschlag(projekt,
                        (None, 'Planung', '1', 'LS', '500.00', '19.00'),
                        (None, 'Druckkosten', '1', 'LS', '33.33', '7.00'),
                        tag=date(2026, 2, 4), festschreiben=False)

        kumuliert = services.kumulierter_abschlag(ab2)

        assert sorted((a.steuersatz_dezimal, a.betrag)
                      for a in kumuliert.abzuege) == [
            (Decimal('7.00'), Decimal('-100.00')),
            (Decimal('19.00'), Decimal('-1000.00'))]
        assert _netto_je_satz(kumuliert) == _belegnetto_je_satz(ab2)

    def test_drei_abschlaege_ziehen_beide_vorgaenger_ab(
            self, projekt, auftrag, zwei_abschlaege):
        ab1, ab2 = zwei_abschlaege
        ab2 = services.beleg_festschreiben(beleg_id=ab2.pk)
        ab3 = _abschlag(
            projekt, (_ap(auftrag, '2.3'), 'LVGBT', '2', 'C62', '198.00',
                      '19.00'),
            tag=date(2026, 3, 2), festschreiben=False)

        kumuliert = services.kumulierter_abschlag(ab3)

        assert [a.bezeichnung.split(' vom ')[0] for a in kumuliert.abzuege] \
            == [f'1. Abschlagsrechnung {ab1.nummer}',
                f'2. Abschlagsrechnung {ab2.nummer}']
        assert _zeilen(kumuliert)[1][2] == Decimal('12.000')
        assert _netto_je_satz(kumuliert) == _belegnetto_je_satz(ab3)

    def test_stornierter_vorgaenger_zaehlt_nicht(self, zwei_abschlaege):
        """Nach dem Storno von AB 1 bleibt für AB 2 kein Vorgänger; die
        Neufassung ist ein Entwurf und zählt nicht."""
        ab1, ab2 = zwei_abschlaege
        services.rechnung_korrigieren(beleg_id=ab1.pk, benutzer=None)

        assert services.kumulierter_abschlag(ab2) is None

    def test_vorgaenger_im_entwurf_zaehlt_nicht(self, projekt, auftrag):
        _abschlag(projekt, (None, 'Planung', '1', 'LS', '1000.00',
                            '19.00'),
                  tag=date(2026, 1, 5), festschreiben=False)
        ab2 = _abschlag(projekt, (None, 'Planung', '1', 'LS', '500.00',
                                  '19.00'),
                        tag=date(2026, 2, 4), festschreiben=False)

        assert services.kumulierter_abschlag(ab2) is None

    def test_nicht_in_einem_projekt_mit_teilabnahme(
            self, auftrag, zwei_abschlaege):
        _, ab2 = zwei_abschlaege
        Abnahme.objects.create(auftrag=auftrag, art=Abnahmeart.TEIL)

        assert services.kumulierter_abschlag(ab2) is None

    def test_die_gespeicherten_positionen_bleiben_der_zuwachs(
            self, zwei_abschlaege):
        _, ab2 = zwei_abschlaege
        services.kumulierter_abschlag(ab2)

        assert ab2.positionen.count() == 4
        assert services.belegsummen(ab2).netto == Decimal('2204.50')


def _neufassen(abschlag):
    """Storniert den Abschlag und schreibt die Neufassung fest."""
    _, neu = services.rechnung_korrigieren(beleg_id=abschlag.pk,
                                           benutzer=None)
    return services.beleg_festschreiben(beleg_id=neu.pk)


class TestNeufassung:
    """Die Neufassung eines stornierten Abschlags trägt dessen Nummer und
    steht an dessen Stelle in der Reihe der Abschläge."""

    def test_traegt_die_nummer_des_stornierten(self, zwei_abschlaege):
        ab1, ab2 = zwei_abschlaege
        _, neu = services.rechnung_korrigieren(beleg_id=ab1.pk, benutzer=None)
        ab1.refresh_from_db()

        assert [ab1.abschlagsnummer, neu.abschlagsnummer,
                ab2.abschlagsnummer] == [1, 1, 2]

    def test_der_naechste_abschlag_zaehlt_weiter(self, projekt, auftrag):
        ab1 = _abschlag(projekt, (None, 'Planung', '1', 'LS', '1000.00',
                                  '19.00'), tag=date(2026, 1, 5))
        neu = _neufassen(ab1)
        ab2 = _abschlag(projekt, (None, 'Planung', '1', 'LS', '500.00',
                                  '19.00'), tag=date(2026, 2, 4),
                        festschreiben=False)

        assert neu.abschlagsnummer == 1
        assert ab2.abschlagsnummer == 2

    def test_zweite_neufassung_traegt_dieselbe_nummer(self, zwei_abschlaege):
        ab1, ab2 = zwei_abschlaege
        neu = _neufassen(_neufassen(ab1))

        assert neu.abschlagsnummer == 1
        assert ab2.abschlagsnummer == 2

    def test_hat_die_vorgaenger_des_originals(self, zwei_abschlaege):
        """Die Neufassung von AB 1 hat keinen Vorgänger, für AB 2 ist sie
        der Vorgänger, obwohl ihr Belegdatum später liegt."""
        ab1, ab2 = zwei_abschlaege
        neu = _neufassen(ab1)

        assert services.kumulierter_abschlag(neu) is None
        assert services.kumulierter_abschlag(ab2).vorgaenger == [neu]

    def test_duplikat_der_neufassung_ist_ein_neuer_abschlag(
            self, zwei_abschlaege):
        ab1, ab2 = zwei_abschlaege
        neu = _neufassen(ab1)
        kopie = services.beleg_duplizieren(beleg_id=neu.pk).beleg

        assert kopie.abschlagsnummer == 3
        assert neu.abschlagsnummer == 1


@pytest.mark.django_db
class TestPdfUndXml:

    def test_pdf_zeigt_stand_vorgaenger_und_abschlagsbetrag(
            self, zwei_abschlaege):
        ab1, ab2 = zwei_abschlaege

        html = pdf.beleg_als_html(ab2)

        oben, unten = html.split('Bereits berechnete')
        assert 'LVGBT' in oben and '<td class="menge">10</td>' in oben
        assert f'1. Abschlagsrechnung {ab1.nummer} vom 05.01.2026' in unten
        assert '-3.365,50' in unten
        assert 'Abschlagsbetrag' in unten
        assert '2.623,36' in unten   # 2.204,50 + 19 % (418,86)

    def test_pdf_des_ersten_abschlags_ohne_abzuege(self, zwei_abschlaege):
        ab1, _ = zwei_abschlaege

        assert 'Bereits berechnete' not in pdf.beleg_als_html(ab1)

    def test_xml_hat_dieselben_zeilen_und_die_belegsumme(
            self, zwei_abschlaege):
        _, ab2 = zwei_abschlaege
        ab2 = services.beleg_festschreiben(beleg_id=ab2.pk)

        xml = facturx.xml_erzeugen(ab2).decode()

        namen = re.findall(r'<ram:Name>([^<]*)</ram:Name>', xml)
        assert 'LVGBT' in namen
        assert any(n.startswith('1. Abschlagsrechnung') for n in namen)
        zeilen = [Decimal(b) for b in re.findall(
            r'<ram:SpecifiedTradeSettlementLineMonetarySummation>\s*'
            r'<ram:LineTotalAmount>([^<]*)</ram:LineTotalAmount>', xml)]
        # BR-CO-10: Summe der Zeilen gleich BT-106, gleich Belegnetto.
        kopf = xml.split('SpecifiedTradeSettlementHeaderMonetarySummation')[1]
        assert sum(zeilen) == Decimal(xml_wert(kopf, 'LineTotalAmount')) \
            == Decimal('2204.50')
        assert Decimal('-3365.50') in zeilen
        # Kein BT-113, weil nicht das Bezahlte abgezogen wird.
        assert 'TotalPrepaidAmount' not in xml
        assert Decimal(xml_wert(xml, 'DuePayableAmount')) == \
            services.belegsummen(ab2).brutto
        assert Decimal(xml_wert(xml, 'TaxTotalAmount')) == Decimal('418.86')

    def test_vorgaenger_mit_negativer_menge_im_xml(self, zwei_abschlaege):
        """BR-27: Der Einzelpreis ist nie negativ; das Minus steht in der
        Menge."""
        _, ab2 = zwei_abschlaege
        ab2 = services.beleg_festschreiben(beleg_id=ab2.pk)

        xml = facturx.xml_erzeugen(ab2).decode()

        assert re.search(r'<ram:BilledQuantity unitCode="[^"]+">-1',
                         xml)
        assert not re.search(r'<ram:ChargeAmount>-', xml)


@pytest.mark.django_db
class TestMaske:

    def test_maske_zeigt_die_kumulierte_sicht(self, buero, zwei_abschlaege):
        from django.urls import reverse
        ab1, ab2 = zwei_abschlaege

        html = buero.get(reverse('admin:faktura_abschlagsrechnung_change',
                                 args=[ab2.pk])).content.decode()

        assert 'Kumuliert, wie im PDF' in html
        assert f'abzüglich 1. Abschlagsrechnung {ab1.nummer}' in html
        assert '2.204,50 €' in html

    def test_maske_des_ersten_abschlags_ohne_block(self, buero,
                                                   zwei_abschlaege):
        from django.urls import reverse
        ab1, _ = zwei_abschlaege

        html = buero.get(reverse('admin:faktura_abschlagsrechnung_change',
                                 args=[ab1.pk])).content.decode()

        assert 'Kumuliert, wie im PDF' not in html


@pytest.fixture
def schlussgerechnet(projekt, auftrag):
    """AB 1 und AB 2 auf den Auftrag, Schlussrechnung vom 01.03.2026 setzt
    beide ab; danach ein Folgeauftrag im selben Projekt."""
    gutachten = _ap(auftrag, '3.1')
    ab1 = _abschlag(projekt, (gutachten, 'Gutachten', '1', 'LS', '2000.00',
                              '19.00'), tag=date(2026, 1, 5))
    ab2 = _abschlag(projekt, (gutachten, 'Gutachten', '1', 'LS', '1000.00',
                              '19.00'), tag=date(2026, 2, 4))
    gesamt = Abnahme.objects.create(auftrag=auftrag, art=Abnahmeart.GESAMT,
                                    abgenommen_am=date(2026, 2, 27))
    schluss = services.rechnung_aus_abnahme(abnahme_id=gesamt.pk)
    schluss.belegdatum = date(2026, 3, 1)
    schluss.save()
    schluss = services.beleg_festschreiben(beleg_id=schluss.pk)

    folge = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.AUFTRAG,
                                   betreff='Folgeauftrag')
    services.position_hinzufuegen(
        beleg=folge, position='5', bezeichnung='Ausführungsplanung',
        menge=Decimal('1'), einheit='LS', einzelpreis=Decimal('9000.00'),
        steuersatz='19.00')
    folge = services.beleg_festschreiben(beleg_id=folge.pk)
    return ab1, ab2, schluss, folge


def _folgeabschlag(projekt, folge, preis, tag, festschreiben=True):
    return _abschlag(projekt, (_ap(folge, '5'), 'Ausführungsplanung', '1',
                               'LS', preis, '19.00'),
                     tag=tag, festschreiben=festschreiben)


@pytest.mark.django_db
class TestNachDerSchlussrechnung:
    """R-183: Mit der Schlussrechnung endet die Reihe der Abschläge, die sie
    absetzt. Regression: Der Abschlag zum Folgeauftrag zeigte den
    schlussgerechneten Auftrag und zog dessen Abschläge ab."""

    def test_der_folgeabschlag_hat_keine_vorgaenger(self, projekt,
                                                    schlussgerechnet):
        _, _, _, folge = schlussgerechnet
        ab3 = _folgeabschlag(projekt, folge, '4000.00', date(2026, 4, 1))

        assert services.vorgaenger_abschlaege(ab3) == []
        assert services.kumulierter_abschlag(ab3) is None

    def test_auch_als_entwurf_ohne_belegdatum(self, projekt,
                                              schlussgerechnet):
        _, _, _, folge = schlussgerechnet
        ab3 = _folgeabschlag(projekt, folge, '4000.00', date(2026, 4, 1),
                             festschreiben=False)
        ab3.belegdatum = None
        ab3.save()

        assert services.vorgaenger_abschlaege(ab3) == []

    def test_die_reihe_des_folgeauftrags_kumuliert_wieder(
            self, projekt, schlussgerechnet):
        _, _, _, folge = schlussgerechnet
        ab3 = _folgeabschlag(projekt, folge, '4000.00', date(2026, 4, 1))
        ab4 = _folgeabschlag(projekt, folge, '3000.00', date(2026, 5, 4),
                             festschreiben=False)

        kumuliert = services.kumulierter_abschlag(ab4)

        assert kumuliert.vorgaenger == [ab3]
        assert _netto_je_satz(kumuliert) == _belegnetto_je_satz(ab4)

    def test_der_abschlag_vor_der_schlussrechnung_behaelt_den_vorgaenger(
            self, schlussgerechnet):
        ab1, ab2, _, _ = schlussgerechnet

        assert services.vorgaenger_abschlaege(ab2) == [ab1]

    def test_nach_storno_der_schlussrechnung_zaehlt_der_abschlag_wieder(
            self, projekt, schlussgerechnet):
        ab1, ab2, schluss, folge = schlussgerechnet
        services.rechnung_korrigieren(beleg_id=schluss.pk)
        ab3 = _folgeabschlag(projekt, folge, '4000.00', date(2026, 4, 1))

        assert services.vorgaenger_abschlaege(ab3) == [ab1, ab2]

    def test_die_nummer_bleibt_je_projekt_fortlaufend(
            self, projekt, schlussgerechnet):
        _, _, _, folge = schlussgerechnet
        ab3 = _folgeabschlag(projekt, folge, '4000.00', date(2026, 4, 1))

        assert ab3.abschlagsnummer == 3

    def test_der_einbehalt_rechnet_nur_mit_der_neuen_reihe(
            self, projekt, schlussgerechnet):
        """R-190 kumuliert über dieselben Vorgänger: 5 % aus 4.000,00 netto,
        ohne die Abschläge vor der Schlussrechnung."""
        _, _, _, folge = schlussgerechnet
        projekt.einbehalt_prozent = Decimal('5')
        projekt.save()
        ab3 = _folgeabschlag(projekt, folge, '4000.00', date(2026, 4, 1))

        assert ab3.einbehalt == Decimal('200.00')
