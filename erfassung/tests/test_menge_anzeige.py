"""Menge der Erfassung ohne nachlaufende Nullen."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from erfassung import services


@pytest.fixture
def zeile(projekt, mengenleistung, mitarbeiter):
    return services.zeile_erfassen(
        projekt=projekt, leistung=mengenleistung, benutzer=mitarbeiter,
        datum=date(2026, 10, 6), menge=Decimal('1.5'), beschreibung='Proben')


def _adresse(zeile):
    return reverse('admin:erfassung_erfassungszeile_change', args=[zeile.pk])


@pytest.mark.django_db
def test_eingabefeld(admin_client, zeile):
    inhalt = admin_client.get(_adresse(zeile)).content.decode()

    assert 'value="1.5"' in inhalt
    assert '1.500000' not in inhalt


@pytest.mark.django_db
def test_nur_ansehen(client, zeile, mitarbeiter):
    mitarbeiter.is_staff = True
    mitarbeiter.save()
    mitarbeiter.user_permissions.set(Permission.objects.filter(
        codename='view_erfassungszeile'))
    client.force_login(mitarbeiter)

    antwort = client.get(_adresse(zeile))
    inhalt = antwort.content.decode()

    assert '1,5' in inhalt
    assert '1,500000' not in inhalt
