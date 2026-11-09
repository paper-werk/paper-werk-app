"""Kumulierter Abschlag: Titel, Titelsummen und Zuschläge in der Ausgabe.

Ab dem zweiten Abschlag bleibt der Aufbau des ersten erhalten. Die Beträge
regeln R-184 bis R-186 (``test_kumulierter_abschlag.py``).
"""

import re
from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from faktura import facturx, pdf, services
from faktura.models import BelegTyp, Kontakt, Projekt, Rechnungsart, Zeilenart

ERSTER_TAG = date(2026, 10, 1)
ZWEITER_TAG = date(2026, 11, 1)


@pytest.fixture
def projekt(db):
    kunde = Kontakt.anlegen(
        nummer='K-4300', name='Muster GmbH', strasse='Hauptstraße 1',
        plz='80797', ort='München', ust_id='DE222333444')
    return Projekt.objects.create(
        nummer='2026-012', bezeichnung='Probe', kunde=kunde)


@pytest.fixture
def auftrag(projekt):
    beleg = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.AUFTRAG,
                                   betreff='Auftrag')
    _titel(beleg, '1', 'Erkundung')
    _titel(beleg, '2', 'Gutachten')
    for nummer, text in (('1.1', 'Probenahme'), ('2.1', 'Bericht')):
        services.position_hinzufuegen(
            beleg=beleg, position=nummer, bezeichnung=text,
            menge=Decimal('40'), einheit='Std',
            einzelpreis=Decimal('100.00'), steuersatz='19.00')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


def _titel(beleg, nummer, text):
    services.position_hinzufuegen(
        beleg=beleg, position=nummer, bezeichnung=text,
        zeilenart=Zeilenart.TITEL, menge=Decimal('0'),
        einzelpreis=Decimal('0'), steuersatz='19.00')


def _abschlag(projekt, auftrag, tag, *, prozent='5', preis='100.00',
              mit_titel_2=False, frei=None):
    beleg = services.beleg_anlegen(
        projekt=projekt, typ=BelegTyp.RECHNUNG,
        rechnungsart=Rechnungsart.ABSCHLAG, betreff='Abschlag',
        leistungsdatum=tag, leistungsdatum_bis=tag, belegdatum=tag)
    _titel(beleg, '1', 'Erkundung')
    services.position_hinzufuegen(
        beleg=beleg, position='1.1', bezeichnung='Probenahme',
        menge=Decimal('10'), einheit='Std', einzelpreis=Decimal(preis),
        steuersatz='19.00',
        auftragsposition=auftrag.positionen.get(position='1.1'),
        leistung_von=tag, leistung_bis=tag)
    services.position_hinzufuegen(
        beleg=beleg, position='1.2', bezeichnung='Nebenkosten',
        zeilenart=Zeilenart.ZUSCHLAG, zuschlag_prozent=Decimal(prozent),
        zuschlag_auf='1', menge=Decimal('1'), einzelpreis=Decimal('0'),
        steuersatz='19.00')
    if frei:
        services.position_hinzufuegen(
            beleg=beleg, position=frei, bezeichnung='Fahrt',
            menge=Decimal('1'), einheit='pausch',
            einzelpreis=Decimal('30.00'), steuersatz='19.00')
    if mit_titel_2:
        _titel(beleg, '2', 'Gutachten')
        services.position_hinzufuegen(
            beleg=beleg, position='2.1', bezeichnung='Bericht',
            menge=Decimal('1'), einheit='Std', einzelpreis=Decimal('100.00'),
            steuersatz='19.00',
            auftragsposition=auftrag.positionen.get(position='2.1'),
            leistung_von=tag, leistung_bis=tag)
    services.zuschlaege_nachrechnen(beleg)
    return beleg


def _fest(beleg):
    return services.beleg_festschreiben(beleg_id=beleg.pk)


def _zeilen(html):
    """(CSS-Klasse, Zellen) je Zeile der Positionstabelle."""
    koerper = re.search(r'<tbody>(.*?)</tbody>', html, re.S).group(1)
    return [
        (klasse.strip(), ' | '.join(
            ' '.join(re.sub(r'<[^>]+>', ' ', zelle).split())
            for zelle in re.findall(r'<td[^>]*>(.*?)</td>', zeile, re.S)))
        for klasse, zeile in re.findall(
            r'<tr class="([^"]*)">(.*?)</tr>', koerper, re.S)]


@pytest.mark.django_db
class TestAufbauWieImErstenAbschlag:

    def test_titel_zuschlag_und_titelsumme(self, projekt, auftrag):
        erster = _fest(_abschlag(projekt, auftrag, ERSTER_TAG))
        zweiter = _abschlag(projekt, auftrag, ZWEITER_TAG)

        zeilen_1 = _zeilen(pdf.beleg_als_html(erster))
        zeilen_2 = _zeilen(pdf.beleg_als_html(zweiter))

        assert [k for k, _ in zeilen_2] == [k for k, _ in zeilen_1]
        assert [z for _, z in zeilen_2] == [
            '1 | Erkundung',
            '1.1 | Probenahme | 20 | Std | 100,00 | 19 % | 2.000,00',
            '1.2 | Nebenkosten 5 % auf 2.000,00 (Titel 1) |  |  |  | 19 % '
            '| 100,00',
            ' | Summe Titel 1 Erkundung | 2.100,00',
        ]

    def test_dritter_abschlag_wie_der_erste(self, projekt, auftrag):
        erster = _fest(_abschlag(projekt, auftrag, ERSTER_TAG))
        _fest(_abschlag(projekt, auftrag, ZWEITER_TAG))
        dritter = _abschlag(projekt, auftrag, date(2026, 12, 1))

        zeilen_1 = _zeilen(pdf.beleg_als_html(erster))
        zeilen_3 = _zeilen(pdf.beleg_als_html(dritter))

        assert [k for k, _ in zeilen_3] == [k for k, _ in zeilen_1]
        assert [z for _, z in zeilen_3] == [
            '1 | Erkundung',
            '1.1 | Probenahme | 30 | Std | 100,00 | 19 % | 3.000,00',
            '1.2 | Nebenkosten 5 % auf 3.000,00 (Titel 1) |  |  |  | 19 % '
            '| 150,00',
            ' | Summe Titel 1 Erkundung | 3.150,00',
        ]
        kumuliert = services.kumulierter_abschlag(dritter)
        assert sum(a.betrag for a in kumuliert.abzuege) == Decimal('-2100.00')

    def test_zuschlag_steht_in_seinem_titel(self, projekt, auftrag):
        """Nach Positionsnummer: der Zuschlag zu Titel 1 vor Titel 2."""
        _fest(_abschlag(projekt, auftrag, ERSTER_TAG))
        zweiter = _abschlag(projekt, auftrag, ZWEITER_TAG, mit_titel_2=True)

        nummern = [p.position for p in
                   services.kumulierter_abschlag(zweiter).positionen]

        assert nummern == ['1', '1.1', '1.2', '2', '2.1']

    def test_freie_position_unter_titel_zaehlt_zur_titelsumme(
            self, projekt, auftrag):
        _fest(_abschlag(projekt, auftrag, ERSTER_TAG, frei='1.3'))
        zweiter = _abschlag(projekt, auftrag, ZWEITER_TAG, frei='1.3')

        zeilen = [z for _, z in _zeilen(pdf.beleg_als_html(zweiter))]

        assert '1.3 | Fahrt | 2 | pausch | 30,00 | 19 % | 60,00' in zeilen
        # 2.000,00 + 60,00 + Zuschlag 5 % auf je 1.030,00 = 103,00.
        assert ' | Summe Titel 1 Erkundung | 2.163,00' in zeilen

    def test_titel_ohne_zeilen_erscheint_nicht(self, projekt, auftrag):
        erster = _abschlag(projekt, auftrag, ERSTER_TAG)
        _titel(erster, '9', 'Leer')
        _fest(erster)
        zweiter = _abschlag(projekt, auftrag, ZWEITER_TAG)

        nummern = [p.position for p in
                   services.kumulierter_abschlag(zweiter).positionen]

        assert '9' not in nummern


@pytest.mark.django_db
class TestBetraegeBleiben:

    def test_titel_aendern_keinen_betrag(self, projekt, auftrag):
        """R-186: Leistungsstand minus Vorgänger ist das Netto des
        Abschlags."""
        _fest(_abschlag(projekt, auftrag, ERSTER_TAG))
        zweiter = _abschlag(projekt, auftrag, ZWEITER_TAG)

        kumuliert = services.kumulierter_abschlag(zweiter)
        stand = sum(services.positionssumme(menge=p.menge,
                                            einzelpreis=p.einzelpreis)
                    for p in kumuliert.positionen)

        assert stand == Decimal('2100.00')
        assert stand + sum(a.betrag for a in kumuliert.abzuege) == (
            services.belegsummen(zweiter).netto)

    def test_xml_ohne_titel_mit_zuschlagsnummer(self, projekt, auftrag):
        _fest(_abschlag(projekt, auftrag, ERSTER_TAG))
        zweiter = _fest(_abschlag(projekt, auftrag, ZWEITER_TAG))

        xml = facturx.xml_erzeugen(zweiter).decode()

        assert 'Erkundung' not in xml
        assert re.findall(r'<ram:LineID>([^<]+)</ram:LineID>', xml)[:2] == [
            '1.1', '1.2']


@pytest.mark.django_db
class TestRechenweg:

    def test_rundung_behaelt_die_basis(self, projekt, auftrag):
        """Je Abschlag 1,67 ergibt 3,34; 5 % der Basis wären 3,33."""
        _fest(_abschlag(projekt, auftrag, ERSTER_TAG, preis='3.33'))
        zweiter = _abschlag(projekt, auftrag, ZWEITER_TAG, preis='3.33')

        zeilen = [z for _, z in _zeilen(pdf.beleg_als_html(zweiter))]

        assert any('5 % auf 66,60 (Titel 1)' in z and z.endswith('3,34')
                   for z in zeilen)

    def test_verschiedene_saetze_ohne_falsche_basis(self, projekt, auftrag):
        """Jeder Satz bleibt eine Zeile; die gemeinsame Basis passte zu
        keiner."""
        _fest(_abschlag(projekt, auftrag, ERSTER_TAG, prozent='5'))
        zweiter = _abschlag(projekt, auftrag, ZWEITER_TAG, prozent='8')

        html = pdf.beleg_als_html(zweiter)

        assert '5 % auf Titel 1' in html
        assert '8 % auf Titel 1' in html
        assert 'auf 2.000,00' not in html


def test_maske_zeigt_titel_und_summe(buero, projekt, auftrag):
    _fest(_abschlag(projekt, auftrag, ERSTER_TAG))
    zweiter = _abschlag(projekt, auftrag, ZWEITER_TAG)

    inhalt = buero.get(reverse('admin:faktura_abschlagsrechnung_change',
                               args=[zweiter.pk])).content.decode()

    assert 'Summe Titel 1 Erkundung' in inhalt
