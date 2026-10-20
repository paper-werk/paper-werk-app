"""Gemeinsame Darstellung der Auswertungsseiten, ohne Datenbank.

Spitzenmonat (R-120, R-121), Säulen und Wasserfallanteile (R-118)
an von Hand gebauten Werten.
"""

from decimal import Decimal

from auswertung import darstellung
from erfassung.services import Monatsstunden
from faktura.formate import euro
from faktura.services import Monatssumme


def test_der_spitzenmonat_nennt_den_monat_mit_betrag():
    """R-121: Der stärkste Monat wird gefunden, auch wenn er nicht der letzte
    ist."""
    verlauf = [Monatssumme(2026, 1, Decimal('110290.00')),
               Monatssumme(2026, 2, Decimal('98000.50')),
               Monatssumme(2026, 3, Decimal('0.00'))]

    text = darstellung.spitzenmonat(verlauf, lambda m: m.netto, euro)

    assert text == 'Januar 2026 mit 110.290,00 €'


def test_ohne_umsatz_gibt_es_keinen_spitzenmonat():
    """Ohne Umsatz gibt es keinen Spitzenmonat."""
    verlauf = [Monatssumme(2026, 1, Decimal('0.00')),
               Monatssumme(2026, 2, Decimal('0.00'))]

    assert darstellung.spitzenmonat(verlauf, lambda m: m.netto, euro) == ''
    assert darstellung.spitzenmonat([], lambda m: m.netto, euro) == ''


def test_der_staerkste_monat_zaehlt_stunden():
    """R-120: dieselbe Funktion mit Stunden als Wert."""
    verlauf = [Monatsstunden(2026, 4, 600), Monatsstunden(2026, 5, 7230)]

    text = darstellung.spitzenmonat(verlauf, lambda m: m.stunden,
                                    lambda s: f'{s} Std.')

    assert text == 'Mai 2026 mit 120.5 Std.'


def test_die_saeulen_tragen_monat_hoehe_und_betrag():
    """Die Achse endet am nächsten runden Wert über der höchsten Säule
    (30.000 über 29.898,60)."""
    verlauf = [Monatssumme(2025, 11, Decimal('8866.20')),
               Monatssumme(2026, 8, Decimal('29898.60')),
               Monatssumme(2026, 9, Decimal('0.00'))]

    saeulen = darstellung.saeulen(verlauf, lambda m: m.netto, euro,
                                  darstellung.euro_glatt)

    assert [a['text'] for a in saeulen['achse']] == [
        '0 €', '10.000 €', '20.000 €', '30.000 €']
    assert [(s['kurz'], s['hoehe'], s['spitze']) for s in saeulen['saeulen']] == [
        ('11/25', '29.6', False), ('08/26', '99.7', True), ('09/26', '0.0', False)]
    assert saeulen['saeulen'][1]['text'] == '29.898,60 €'


def test_die_achse_rundet_auf_und_nicht_zur_null_hin():
    """Regression: ``-(-a // b)`` rundet bei Decimal zur Null hin und ergab
    für 29.898,60 eine Achse bis 20.000."""
    for hoechster, oben in (('29898.60', '30.000,00 €'),
                            ('30000.00', '30.000,00 €'),
                            ('30000.01', '40.000,00 €'),
                            ('7.50', '7,50 €')):
        verlauf = [Monatssumme(2026, 1, Decimal(hoechster))]

        achse = darstellung.saeulen(
            verlauf, lambda m: m.netto, euro, euro)['achse']

        assert achse[-1]['text'] == oben, hoechster
        assert achse[-1]['hoehe'] == '100.0'


def test_ohne_werte_bleibt_die_flaeche_leer():
    """Ohne Werte: kein Höchstwert, kein Spitzenmonat, keine Division durch
    null."""
    verlauf = [Monatssumme(2026, 1, Decimal('0.00'))]

    saeulen = darstellung.saeulen(verlauf, lambda m: m.netto, euro, euro)

    assert saeulen['saeulen'][0]['hoehe'] == '0.0'
    assert saeulen['saeulen'][0]['spitze'] is False


def test_stunden_gehen_auch():
    """Mit Stunden als Wert, wie in der Projektakte."""
    verlauf = [Monatsstunden(2026, 1, 900), Monatsstunden(2026, 2, 2400)]

    saeulen = darstellung.saeulen(verlauf, lambda m: m.stunden, str, str)

    # 15 und 40 Stunden; die Achse endet bei 40 (Schritt 20).
    assert [s['hoehe'] for s in saeulen['saeulen']] == ['37.5', '100.0']


class _Staffel:
    """Nachgebaute Staffel mit den Feldern, die ``wasserfall`` liest."""

    def __init__(self, leistungswert, fremdkosten, personalkosten, stufen):
        self.leistungswert = Decimal(leistungswert)
        self.fremdkosten = Decimal(fremdkosten)
        self.personalkosten = Decimal(personalkosten)
        self.stufen = stufen


def test_die_wasserfallanteile_beziehen_sich_auf_den_groesseren_wert():
    """R-118: Bei Kosten 1500 über Leistung 1000 sind die Kosten der
    Bezugswert; Anteile mit Dezimalpunkt für gültiges CSS."""
    staffel = _Staffel('1000', '500', '1000', [
        {'titel': 'Leistungswert', 'betrag': Decimal('1000'),
         'sockel': Decimal('0'), 'art': 'summe'},
        {'titel': 'Zugekauft', 'betrag': Decimal('-187.50'),
         'sockel': Decimal('812.50'), 'art': 'abzug'},
    ])

    stufen = darstellung.wasserfall(staffel)

    assert stufen[0]['breite'] == '66.7'
    assert stufen[1]['start'] == '54.2'
    assert stufen[1]['breite'] == '12.5'


def test_ueber_hundert_prozent_bleibt_der_balken_in_der_spur():
    staffel = _Staffel('100', '0', '0', [
        {'titel': 'Leistungswert', 'betrag': Decimal('250'),
         'sockel': Decimal('0'), 'art': 'summe'}])

    assert darstellung.wasserfall(staffel)[0]['breite'] == '100.0'


def test_ohne_bezug_kein_wasserfall():
    assert darstellung.wasserfall(_Staffel('0', '0', '0', [])) == []
