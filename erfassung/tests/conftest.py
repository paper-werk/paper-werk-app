"""Fixtures der Tests von erfassung.

Anders als in ``faktura`` ist keine Firma nötig, weil eine Erfassungszeile
kein Dokument erzeugt. Nötig ist ein Projekt und dafür ein Kunde.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from faktura.models import (
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Katalogposition,
    Kontakt,
    Leistungsart,
    Projekt,
)


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-2000',
        name='Bauunternehmung Vogt GmbH',
        strasse='Werkstraße 8',
        plz='31226',
        ort='Peine',
    )


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(
        nummer='2026-042', bezeichnung='Halle Nord', kunde=kunde
    )


@pytest.fixture
def abgeschlossenes_projekt(kunde):
    return Projekt.objects.create(
        nummer='2025-001', bezeichnung='Anbau Süd', kunde=kunde,
        abgeschlossen=True,
    )


@pytest.fixture
def zeitleistung(db):
    """Leistung, die über Uhrzeiten erfasst wird."""
    return Katalogposition.objects.create(
        bezeichnung='Montage', einheit='Std', einzelpreis=Decimal('68.00'),
        kontierbar=True, art=Leistungsart.ZEIT,
    )


@pytest.fixture
def mengenleistung(db):
    """Leistung mit Menge: Anfahrt in Kilometern."""
    return Katalogposition.objects.create(
        bezeichnung='Anfahrt', einheit='km', einzelpreis=Decimal('0.90'),
        kontierbar=True, art=Leistungsart.MENGE,
    )


@pytest.fixture
def pauschalleistung(db):
    """Pauschale, Menge immer eins."""
    return Katalogposition.objects.create(
        bezeichnung='Kleinmaterial', einheit='pausch',
        einzelpreis=Decimal('35.00'), kontierbar=True,
        art=Leistungsart.PAUSCHALE,
    )


@pytest.fixture
def nur_fuer_angebote(db):
    """Katalogposition, die nicht kontierbar ist, etwa
    "Baustelleneinrichtung pauschal" aus Angeboten."""
    return Katalogposition.objects.create(
        bezeichnung='Baustelleneinrichtung', einheit='pausch',
        einzelpreis=Decimal('450.00'), kontierbar=False,
    )


@pytest.fixture
def mitarbeiter(db):
    """Konto ohne Superuser-Status, damit die Tests mit den Rechten der
    Anwender laufen."""
    return get_user_model().objects.create_user(
        username='anna', password='geheim12345', is_staff=True,
    )


@pytest.fixture
def kollege(db):
    return get_user_model().objects.create_user(
        username='bernd', password='geheim12345', is_staff=True,
    )


# ── Belege für die Erfassung ─────────────────────────────────────────────────
#
# Ohne Positionen und Empfänger, weil nur der Zustand des Belegs zählt (ob er
# eine Zeile sperrt). Ein vollständiger Aufbau über faktura.services (Firma,
# Anschrift, Position, Leistungsdatum, Nummernkreis) machte die Tests von
# der Rechnungsschreibung abhängig.

@pytest.fixture
def rechnungsentwurf(db):
    """Rechnungsentwurf: reserviert die Zeile, sperrt sie nicht."""
    return Beleg.objects.create(
        typ=BelegTyp.RECHNUNG, status=BelegStatus.ENTWURF,
    )


@pytest.fixture
def festgeschriebene_rechnung(db):
    """Festgeschriebene Rechnung: sperrt die Zeile."""
    return Beleg.objects.create(
        typ=BelegTyp.RECHNUNG, status=BelegStatus.FESTGESCHRIEBEN,
        nummer='2026-0117',
    )


@pytest.fixture
def auftragsposition(projekt, zeitleistung):
    """Position eines festgeschriebenen Auftrags zum Vorhaben.

    Mit Leistungsart Zeit, damit die Erfassung Uhrzeiten erwartet. Angelegt
    über ``bulk_create``, weil ``Belegposition.save()`` Änderungen an
    festgeschriebenen Belegen ablehnt (wie ``festgeschriebene_position``).
    """
    auftrag = Beleg.objects.create(
        typ=BelegTyp.AUFTRAG, status=BelegStatus.FESTGESCHRIEBEN,
        nummer='AU-2026-0005', projekt=projekt,
    )
    return Belegposition.objects.bulk_create([
        Belegposition(
            beleg=auftrag, position=10, bezeichnung='Planung Lph 1-4',
            menge=Decimal('100'), einheit='Std',
            einzelpreis=Decimal('95.00'), art=zeitleistung.art,
        )
    ])[0]


@pytest.fixture
def entwurfsposition(rechnungsentwurf):
    """Position auf dem Rechnungsentwurf als Ziel von ``abgerechnet_in``.

    ``abgerechnet_in`` zeigt auf eine Position. Der zugehörige Beleg ist
    ``rechnungsentwurf``; beide Fixtures zusammen liefern denselben Beleg.
    """
    return Belegposition.objects.create(
        beleg=rechnungsentwurf, position=10, bezeichnung='Leistung',
        menge=Decimal('1'), einzelpreis=Decimal('100.00'),
    )


@pytest.fixture
def festgeschriebene_position(festgeschriebene_rechnung):
    """Position auf der festgeschriebenen Rechnung, über ``bulk_create``.

    ``objects.create()`` schlägt fehl, weil ``Belegposition.save()``
    Änderungen an festgeschriebenen Belegen ablehnt. Im Betrieb entsteht die
    Position am Entwurf; die Fixture erzeugt direkt den Endzustand.
    ``bulk_create`` ruft kein ``save()`` (wie ``zeile_ohne_umfang``).
    """
    return Belegposition.objects.bulk_create([
        Belegposition(
            beleg=festgeschriebene_rechnung, position=10,
            bezeichnung='Leistung', menge=Decimal('1'),
            einzelpreis=Decimal('100.00'),
        )
    ])[0]


@pytest.fixture
def zeile_ohne_umfang():
    """Zeile ohne Zeit und Menge, ohne ``clean()`` angelegt.

    ``Erfassungszeile.clean()`` lehnt solche Zeilen ab, Services und Admin
    erzeugen sie nicht. Vorkommen können sie trotzdem, in Altdaten und über
    ``bulk_create`` oder ``queryset.update()``, die kein ``clean()``
    aufrufen. Liste und Abrechnungsvorschau müssen sie verarbeiten; die
    Vorschau meldet sie.

    ``objects.create()`` ruft ``save()``, aber nicht ``full_clean()``.
    """
    from erfassung.models import Erfassungszeile

    def anlegen(projekt, leistung, benutzer, **rest):
        return Erfassungszeile.objects.create(
            datum=rest.pop('datum', timezone.localdate()),
            projekt=projekt, leistung=leistung, benutzer=benutzer,
            beschreibung=rest.pop('beschreibung', 'Aus dem Altbestand'),
            **rest,
        )

    return anlegen


@pytest.fixture
def dienst(db):
    """Dienstzugang für n8n mit den Rechten der Gruppe "Belegübernahme" aus
    den Rechtebefehlen, für die Tests der Schnittstelle."""
    from io import StringIO

    from django.contrib.auth.models import Group
    from django.core.management import call_command
    from rest_framework.test import APIClient

    from core import gruppen

    call_command('faktura_rechte', stdout=StringIO())
    call_command('erfassung_rechte', stdout=StringIO())
    person = get_user_model().objects.create_user(
        username='n8n', password='geheim12345')
    person.groups.add(Group.objects.get(name=gruppen.BELEGUEBERNAHME))
    client = APIClient()
    client.force_authenticate(person)
    return client
