"""Markup des Tabs „Zahlungen".

Die fachliche Prüfung steht in ``test_zahlung_vermerken.py``. Regression:
„Betrag Skonto Art" erschien als ein Wort, weil das Padding nur an den
Datenzellen hing und Unfolds Stylesheet Tabellen zurücksetzt. Geprüft
werden daher die Zellen im Markup, ohne Browser.
"""

import re
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from faktura import services
from faktura.models import BelegTyp, Kontakt

HEUTE = timezone.localdate()
User = get_user_model()


@pytest.fixture
def rechnung(db):
    kunde = Kontakt.anlegen(nummer='K-3200', name='Netzbetrieb Beispiel',
                          strasse='Am Werk 2', plz='84028', ort='Landshut')
    beleg = services.beleg_anlegen(
        kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Gutachten')
    beleg.leistungsdatum = HEUTE
    beleg.save()
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Gutachten', menge=Decimal('1'),
        einzelpreis=Decimal('1000.00'), steuersatz='19.00',
        einheit='psch')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


def _tabelle(seite: str) -> str:
    """Tabelle der Zahlungen aus der gerenderten Seite."""
    treffer = re.search(r'<table class="text-sm w-full">.*?</table>',
                        seite, re.S)
    assert treffer, 'keine Zahlungstabelle im HTML'
    return treffer.group(0)


@pytest.mark.django_db
class TestDieTabelleImFormular:

    def test_jede_kopfzelle_ist_eine_eigene_zelle_mit_abstand(
            self, buero, rechnung):
        """Jede Kopfzelle ist ein eigenes ``th`` mit Padding-Klasse; ohne sie
        laufen die Überschriften zusammen."""
        services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=HEUTE, betrag=Decimal('1190.00'))

        tabelle = _tabelle(buero.get(
            reverse('admin:faktura_rechnung_change', args=[rechnung.pk])
        ).content.decode())

        # Nicht ``<th[^>]*>``, weil das auch ``<thead>`` trifft.
        kopfzellen = re.findall(r'<th\s[^>]*>(.*?)</th>', tabelle)
        assert kopfzellen == ['Datum', 'Betrag', 'Skonto', 'Gekürzt', 'Art',
                              'Verwendungszweck']
        # Alle außer der letzten haben das Padding.
        abstaende = re.findall(r'<th class="([^"]*)"', tabelle)
        assert all('pr-6' in klasse for klasse in abstaende[:-1])

    def test_betrag_und_skonto_stehen_rechtsbuendig(self, buero, rechnung):
        """Betrag und Skonto rechtsbündig, damit die Kommas untereinander
        stehen."""
        services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=HEUTE, betrag=Decimal('1154.30'),
            skonto=Decimal('35.70'))

        tabelle = _tabelle(buero.get(
            reverse('admin:faktura_rechnung_change', args=[rechnung.pk])
        ).content.decode())

        datenzellen = re.findall(r'<td class="([^"]*)"', tabelle)
        assert 'text-right' in datenzellen[1]
        assert 'text-right' in datenzellen[2]

    def test_die_zeile_traegt_ihre_werte_in_der_richtigen_ordnung(
            self, buero, rechnung):
        """Die Werte der Zeile stehen in der Reihenfolge der Kopfzellen."""
        services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=HEUTE, betrag=Decimal('1154.30'),
            skonto=Decimal('35.70'), verwendungszweck='RE-0001')

        tabelle = _tabelle(buero.get(
            reverse('admin:faktura_rechnung_change', args=[rechnung.pk])
        ).content.decode())

        werte = [w.strip() for w in re.findall(r'<td[^>]*>(.*?)</td>', tabelle)]
        assert werte[0] == HEUTE.strftime('%d.%m.%Y')
        assert '1.154,30' in werte[1]
        assert '35,70' in werte[2]
        # Gekürzt (R-175) nur beim Abschlag, hier ein Strich.
        assert werte[3] == '–'
        assert werte[4] == 'Überweisung'
        assert werte[5] == 'RE-0001'

    def test_ohne_skonto_steht_ein_strich_und_keine_null(
            self, buero, rechnung):
        """Ohne Skonto ein Strich, nicht 0,00."""
        services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=HEUTE, betrag=Decimal('1190.00'))

        tabelle = _tabelle(buero.get(
            reverse('admin:faktura_rechnung_change', args=[rechnung.pk])
        ).content.decode())

        werte = [w.strip() for w in re.findall(r'<td[^>]*>(.*?)</td>', tabelle)]
        assert werte[2] == '–'
