"""Fixtures der Browsertests."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from faktura.models import (
    Firma,
    Kontakt,
)
from tests.browserhilfen import PASSWORT


@pytest.fixture
def kunde(db):
    Firma.objects.create(
        name='Elektro Hofmeister e.K.', strasse='Schirmbeckstraße 14',
        plz='84034', ort='Landshut', steuernummer='132/218/40391')
    return Kontakt.anlegen(
        nummer='K-1001', name='Wohnbau Isartal eG', strasse='Ludwigsplatz 9',
        plz='84034', ort='Landshut')


@pytest.fixture
def chefin(db):
    """Benutzer mit allen Rechten, weil hier Buttons geprüft werden.

    Die Rechte prüft ``faktura/tests/admin/test_rechte.py``.
    """
    person = get_user_model().objects.create_superuser(
        username='chefin', password=PASSWORT, email='c@example.invalid')
    person.user_permissions.add(*Permission.objects.all())
    return person
