"""Sichert ab, wie Zahleneingaben im deutschen Locale gelesen werden.

Nur Eingaben, die Beträge und Mengen verändern können, weil ein
Parsing-Fehler dort falsche Rechnungen erzeugt. Übersetzung und
Datumsformat des Admins sind Sache von Django.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.forms import DecimalField
from django.test import override_settings


class TestZahleneingabe:
    """Begründung für USE_THOUSAND_SEPARATOR = False in den Settings."""

    @pytest.mark.parametrize(
        'eingabe,erwartet',
        [
            ('1234,56', '1234.56'),   # deutsche Schreibweise
            ('1234.56', '1234.56'),   # englische Schreibweise, ebenfalls erkannt
            ('0,05', '0.05'),
        ],
    )
    def test_beide_schreibweisen_werden_verstanden(self, eingabe, erwartet):
        feld = DecimalField(max_digits=12, decimal_places=2, localize=True)

        assert feld.clean(eingabe) == Decimal(erwartet)

    def test_drei_nachkommastellen_bleiben_eindeutig(self):
        """"1.500" ergibt 1,5 für Belegposition.menge (drei Nachkommastellen).

        Ohne Tausendertrennzeichen ist die Eingabe eindeutig; eine Änderung
        der Setting lässt diesen Test fehlschlagen.
        """
        feld = DecimalField(max_digits=10, decimal_places=3, localize=True)

        assert feld.clean('1.500') == Decimal('1.5')
        assert feld.clean('12.500') == Decimal('12.5')

    def test_mit_tausendertrennzeichen_waere_es_das_tausendfache(self):
        """Verworfene Alternative: Mit Tausendertrennzeichen ergäbe "1.500"
        ohne Warnung 1500."""
        with override_settings(USE_THOUSAND_SEPARATOR=True):
            feld = DecimalField(max_digits=10, decimal_places=3, localize=True)

            assert feld.clean('1.500') == Decimal('1500')

    def test_zu_viele_nachkommastellen_bei_geld_werden_abgewiesen(self):
        """Geldfelder lehnen mehr als zwei Nachkommastellen ab, damit ein
        Tippfehler auffällt."""
        feld = DecimalField(max_digits=12, decimal_places=2, localize=True)

        with pytest.raises(ValidationError):
            feld.clean('1.500')


@pytest.mark.django_db
class TestBelegformatierung:
    """Formatierung der Ausgabe auf dem Beleg.

    USE_THOUSAND_SEPARATOR bleibt False, weil der Punkt bei der Eingabe
    mehrdeutig wäre; im PDF setzen die Filter ihn explizit.
    """

    def test_betraege_bekommen_den_tausenderpunkt(self):
        from faktura.formate import geld

        assert geld(Decimal('1234.5')) == '1.234,50'
        assert geld(Decimal('999')) == '999,00'
        assert geld(Decimal('-5219.34')) == '-5.219,34'

    def test_euro_rundet_kaufmaennisch_und_kennt_leer(self):
        """``euro`` für Masken und Auswertungen rundet wie die Rechnung
        (Hälfte von der Null weg) und behandelt leere Werte."""
        from faktura.formate import euro

        assert euro(Decimal('12345.675')) == '12.345,68 €'
        assert euro(Decimal('-0.005')) == '-0,01 €'
        assert euro(Decimal('0')) == '0,00 €'
        assert euro(None) == ''

    def test_mengen_ohne_ueberfluessige_nullen(self):
        from faktura.formate import menge

        assert menge(Decimal('10.000')) == '10'
        assert menge(Decimal('1.500')) == '1,5'
        assert menge(Decimal('1200')) == '1.200'

    def test_der_faktor_mit_komma(self):
        """R-177: Der Faktor erscheint mit Komma. Regression: "Faktor 1.90"
        auf der Controlling-Seite."""
        from faktura.formate import faktor

        assert faktor(Decimal('1.9')) == '1,90'
        assert faktor(Decimal('12.345')) == '12,35'
        assert faktor(None) == ''

    def test_steuersatz_bleibt_ohne_trennzeichen(self):
        from faktura.formate import prozent

        assert prozent(Decimal('19.00')) == '19 %'
        assert prozent(Decimal('7.00')) == '7 %'


class TestMengeImEingabefeld:
    """Menge im Eingabefeld ohne nachlaufende Nullen.

    "6.000 Std" würde im Deutschen als sechstausend gelesen. Das Feld ist
    ein ``<input type="number">`` mit Wert im technischen Format (``1.5``);
    das Komma zeigt der Browser. Ein Tausenderpunkt wäre dort ein
    Dezimalpunkt."""

    @pytest.mark.parametrize(('gespeichert', 'im_feld'), [
        ('6.000', '6'),
        ('1.500', '1.5'),
        ('1200.000', '1200'),
        ('0.125', '0.125'),
        ('0.001', '0.001'),
        ('10.000', '10'),      # nicht "1E+1"
    ])
    def test_ohne_ueberfluessige_nullen(self, gespeichert, im_feld):
        from faktura.forms import MengeWidget

        assert MengeWidget().format_value(Decimal(gespeichert)) == im_feld

    def test_getippter_text_bleibt_wie_getippt(self):
        """Nach einem Validierungsfehler bleibt die Eingabe unverändert, auch
        "6,000"."""
        from faktura.forms import MengeWidget

        assert MengeWidget().format_value('6,000') == '6,000'
        assert MengeWidget().format_value(None) is None

    def test_der_gekuerzte_wert_wird_wieder_derselbe(self):
        """Gegenprobe: Der gekürzte Wert im Feld parst zum gespeicherten Wert,
        ohne Faktor 1000."""
        from faktura.forms import MengeWidget

        feld = DecimalField(max_digits=10, decimal_places=3, localize=True)
        for gespeichert in ('6.000', '1.500', '1200.000', '0.125'):
            im_feld = MengeWidget().format_value(Decimal(gespeichert))
            assert feld.clean(im_feld) == Decimal(gespeichert)
