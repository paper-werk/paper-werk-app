"""Fixtures der Tests von faktura.

Jeder Test mit Datenbank erhält die eigene Firma, weil das Festschreiben das
PDF erzeugt und ohne Absenderdaten fehlschlägt; eine Rechnung ohne
Steuernummer berechtigt den Empfänger nicht zum Vorsteuerabzug.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from faktura import services
from faktura.models import (
    BelegTyp,
    Kontakt,
)


@pytest.fixture(autouse=True)
def firma(request):
    """Legt die eigene Firma an, für jeden Test mit Datenbank.

    Mit Prüfung auf den Marker, weil ``autouse`` sonst auch Tests ohne
    Datenbank eine Datenbank zuwiese (etwa die Tests der Lokalisierung).
    """
    if request.node.get_closest_marker('django_db') is None:
        return None

    request.getfixturevalue('db')

    from faktura.models import Firma
    return Firma.objects.create(
        name='Werkstatt Amper GmbH',
        strasse='Musterweg 12',
        plz='80331',
        ort='München',
        telefon='089 1234567',
        email='post@example.de',
        steuernummer='143/815/47110',
        ust_id='DE123456789',
        bank='Stadtsparkasse',
        iban='DE02120300000000202051',
        bic='BYLADEM1001',
        geschaeftsfuehrung='H. Amper',
        registergericht='AG München',
        handelsregister='HRB 12345',
    )


@pytest.fixture
def ueberfaellig():
    """Schreibt eine Rechnung fest und datiert ihre Fälligkeit zurück.

    Für Tests, die mahnen, weil ``mahnung_erstellen`` Verzug verlangt, der
    nach § 286 BGB erst nach Fälligkeit eintritt. Eine Fixture für
    test_services und test_admin, damit die Frist an einer Stelle steht.

    Zurückdatiert über ``update()``, weil ``save()`` am festgeschriebenen
    Beleg keine Änderung zulässt.
    """
    from datetime import timedelta

    from django.utils import timezone

    from faktura import services
    from faktura.models import Beleg

    def herstellen(rechnung, tage=10):
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)
        Beleg.objects.filter(pk=original.pk).update(
            faellig_am=timezone.localdate() - timedelta(days=tage))
        return Beleg.objects.get(pk=original.pk)

    return herstellen


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-1000',
        name='Muster GmbH',
        strasse='Hauptstraße 1',
        plz='10115',
        ort='Berlin',
        zahlungsziel_tage=14,
    )


@pytest.fixture
def rechnung(kunde):
    beleg = services.beleg_anlegen(
        kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Leistungen Januar'
    )
    beleg.leistungsdatum = timezone.localdate()
    beleg.save()
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Beratung', menge=Decimal('10'),
        einzelpreis=Decimal('100.00'), steuersatz='19.00', einheit='Std',
    )
    return beleg


@pytest.fixture
def angebot(kunde):
    beleg = services.beleg_anlegen(
        kunde=kunde, typ=BelegTyp.ANGEBOT, betreff='Umbau Dachgeschoss'
    )
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Planung', menge=Decimal('8'),
        einzelpreis=Decimal('95.00'), steuersatz='19.00', einheit='Std',
    )
    return beleg


@pytest.fixture
def bearbeiterin(db):
    return get_user_model().objects.create_user(
        username='huber', password='geheim12345'
    )
