"""Formatierung von Dauer (``erfassung/formate.py``), ohne Datenbank.

Wie in ``faktura/tests/test_lokalisierung.py`` wird auch die verworfene Lesart
geprüft, damit eine spätere Änderung sie nicht unbemerkt einführt.
"""

import pytest

from erfassung.formate import dauer_dezimal, dauer_zeigen


class TestDauerZeigen:

    @pytest.mark.parametrize('minuten, text', [
        (90, '1:30'),
        (45, '0:45'),
        (480, '8:00'),
        (5, '0:05'),
        (1440, '24:00'),
    ])
    def test_immer_zweistellige_minuten(self, minuten, text):
        assert dauer_zeigen(minuten) == text



class TestDauerDezimal:

    @pytest.mark.parametrize('minuten, text', [
        (90, '1,50'),
        (15, '0,25'),
        (60, '1,00'),
        (465, '7,75'),
    ])
    def test_stunden_mit_komma(self, minuten, text):
        """Dezimalstunden mit Komma für Auswertungen und Rechnungen."""
        assert dauer_dezimal(minuten) == text

    def test_zwanzig_minuten_sind_nicht_exakt_darstellbar(self):
        """20 Minuten sind als Dezimalstunde nicht exakt; deshalb wird in
        Minuten gespeichert."""
        assert dauer_dezimal(20) == '0,33'
        assert dauer_dezimal(40) == '0,67'
