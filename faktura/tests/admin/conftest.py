"""Fixtures der Admin-Tests von faktura."""

from decimal import Decimal

import pytest
from django.utils import timezone

from faktura import services
from faktura.models import (
    BelegTyp,
    Kontakt,
    Textbaustein,
    TextbausteinVerwendung,
)


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-1000', name='Muster GmbH', strasse='Hauptstraße 1',
        plz='10115', ort='Berlin',
    )


@pytest.fixture
def rechnungsentwurf(kunde):
    beleg = services.beleg_anlegen(
        kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Leistungen',
        leistungsdatum=timezone.localdate(),
    )
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Beratung', menge=Decimal('10'),
        einzelpreis=Decimal('100.00'), steuersatz='19.00',
    )
    return beleg


@pytest.fixture
def bausteine(db):
    """Je ein Baustein für Kopf- und Fußtext.

    Auf Modulebene, weil vier Testklassen sie brauchen; das Vorlagenmenü im
    Formular erscheint nur, wenn Bausteine existieren.
    """
    return (
        Textbaustein.objects.create(
            name='Dank für Anfrage',
            verwendung=TextbausteinVerwendung.BELEGTEXT,
            text='Wir bedanken uns für Ihre Anfrage\nund bieten an:',
        ),
        Textbaustein.objects.create(
            name='Grußformel',
            verwendung=TextbausteinVerwendung.BELEGTEXT,
            text='Über Ihren Auftrag würden wir uns freuen.',
        ),
    )


@pytest.fixture
def angebot(kunde):
    beleg = services.beleg_anlegen(
        kunde=kunde, typ=BelegTyp.ANGEBOT, betreff='Halle Nord',
        leistungsdatum=timezone.localdate(),
    )
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Montage', menge=Decimal('10'),
        einzelpreis=Decimal('100.00'), steuersatz='19.00',
    )
    return beleg
