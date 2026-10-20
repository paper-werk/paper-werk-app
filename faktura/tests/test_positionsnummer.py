"""Positionsnummern als Text (faktura/positionsnummer.py).

Ohne Datenbank, weil Sortierschlüssel und Weiterzählen reine Funktionen
sind. Dieselbe Regel steht in positionsnummer.js, im Browser geprüft von
tests/test_browser_formular.py (TestPositionenImFormular).
"""

import pytest

from faktura.positionsnummer import naechste, naechste_nummern, sortierschluessel


@pytest.mark.parametrize('reihe', [
    ['9', '10', '100'],
    ['10', '15', '20'],
    ['01.01.0010', '01.01.0020', '01.02.0010', '02.01.0010'],
    ['1.9', '1.10', '2'],
    ['3', '3a', '3b', '4'],
])
def test_sortiert_wie_gezaehlt(reihe):
    durcheinander = reihe[2:] + reihe[:2]

    assert sorted(durcheinander, key=sortierschluessel) == reihe


def test_gross_und_klein_stehen_beieinander():
    assert sortierschluessel('3A') == sortierschluessel('3a')


@pytest.mark.parametrize('vorige,erwartet', [
    ('30', '40'),
    ('15', '16'),
    ('01.01.0010', '01.01.0020'),
    ('01.09', '01.10'),
    ('1.99', '1.100'),          # die Breite wächst bei Bedarf
    ('3a', '4a'),
    ('Zulage', ''),             # nichts zum Weiterzählen
])
def test_naechste(vorige, erwartet):
    assert naechste(vorige) == erwartet


class TestNaechsteNummern:

    def test_ohne_vorgaenger_10_20_30(self):
        assert naechste_nummern([], 3) == ['10', '20', '30']

    def test_zehner_bleiben_zehner(self):
        assert naechste_nummern(['10', '20'], 2) == ['30', '40']

    def test_einer_bleiben_einer(self):
        """Bei ganzen Zahlen: nach 10 und 15 Einerschritte."""
        assert naechste_nummern(['10', '15'], 1) == ['16']

    def test_lv_nummern_hinter_der_hoechsten(self):
        assert naechste_nummern(['01.02.0010', '01.01.0030'], 2) \
            == ['01.02.0020', '01.02.0030']

    def test_nie_eine_vergebene(self):
        assert naechste_nummern(['01.0010', '01.0020', '01.0010x'], 1) \
            == ['01.0030']
        assert naechste_nummern(['1.1', '1.2', '1.3', 'a'], 1) == ['1.4']

    def test_ohne_zaehlbare_nummer_wie_ohne_vorgaenger(self):
        assert naechste_nummern(['Zulage'], 2) == ['10', '20']

    def test_leere_werden_uebergangen(self):
        assert naechste_nummern(['', '  ', '20'], 1) == ['30']
