"""Kennzahl „Einbehalten“ in Projekt- und Kundenakte (R-192).

Die Rechenregel prüft ``faktura/tests/test_einbehalten.py``; hier nur die
Anzeige, weil die Akten zur App ``auswertung`` gehören und der Kern ohne
sie läuft.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from faktura import services
from faktura.models import (
    Abzugsgrundlage,
    BelegTyp,
    Kontakt,
    Projekt,
    Rechnungsart,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(nummer='K-5200', name='Gemeinde Unterfeld',
                           strasse='Rathausplatz 2', plz='84028',
                           ort='Landshut')


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(
        nummer='2026-520', bezeichnung='Bauhof', kunde=kunde,
        einbehalt_prozent=Decimal('5'),
        einbehalt_grundlage=Abzugsgrundlage.BRUTTO)


@pytest.fixture
def abschlag(projekt):
    """4.000,00 netto, 4.760,00 brutto, Einbehalt 238,00."""
    beleg = services.beleg_anlegen(
        projekt=projekt, typ=BelegTyp.RECHNUNG,
        rechnungsart=Rechnungsart.ABSCHLAG, betreff='Abschlag',
        leistungsdatum=date(2026, 1, 1), leistungsdatum_bis=date(2026, 1, 31))
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Bauüberwachung', menge=Decimal('1'),
        einheit='LS', einzelpreis=Decimal('4000.00'), steuersatz='19.00')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


def test_projektakte_zeigt_die_karte(buero, projekt, abschlag):
    antwort = buero.get(reverse('projektakte', args=[projekt.pk]))

    titel = [k['titel'] for k in antwort.context['kennzahlen']]
    assert 'Einbehalten' in titel


def test_kundenakte_nennt_den_betrag(buero, kunde, abschlag):
    antwort = buero.get(reverse('kundenakte', args=[kunde.pk]))

    assert antwort.context['einbehalten'] == Decimal('238.00')


def test_ohne_einbehalt_keine_karte(buero, kunde):
    antwort = buero.get(reverse('kundenakte', args=[kunde.pk]))

    assert antwort.context['einbehalten'] == Decimal('0.00')
