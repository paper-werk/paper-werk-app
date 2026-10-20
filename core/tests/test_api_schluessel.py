"""Gruppen und Rechte, die ``api_schluessel`` einem Dienstzugang gibt.

Geprüft über Requests an die API, weil ein Zugang in der richtigen Gruppe
trotzdem 403 erhalten kann.
"""

from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core import gruppen

pytestmark = pytest.mark.django_db


@pytest.fixture
def rechte():
    """Gruppen, wie das Setup sie vor dem Dienstzugang anlegt."""
    call_command('faktura_rechte', stdout=StringIO())
    call_command('erfassung_rechte', stdout=StringIO())


def _anlegen(*argumente):
    call_command('api_schluessel', 'n8n', '--anlegen', *argumente, stdout=StringIO())
    benutzer = get_user_model().objects.get(username='n8n')
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Token {Token.objects.get(user=benutzer).key}')
    return benutzer, client


def test_vorgabe_reicht_fuer_abholung_und_uebernahme(rechte):
    _, client = _anlegen()

    assert client.get('/api/v1/belege/').status_code == 200
    assert client.get('/api/v1/eingangsrechnungen/').status_code == 200


def test_vorgabe_nennt_beide_gruppen(rechte):
    benutzer, _ = _anlegen()

    assert set(benutzer.groups.values_list('name', flat=True)) == {
        gruppen.DIENST, gruppen.BELEGUEBERNAHME}


def test_eigene_gruppe_ersetzt_die_vorgabe(rechte):
    benutzer, client = _anlegen('--gruppe', gruppen.DIENST)

    assert list(benutzer.groups.values_list('name', flat=True)) == [gruppen.DIENST]
    assert client.get('/api/v1/eingangsrechnungen/').status_code == 403


def test_leere_gruppe_heisst_ohne_rechte(rechte):
    benutzer, client = _anlegen('--gruppe', '')

    assert not benutzer.groups.exists()
    assert client.get('/api/v1/belege/').status_code == 403


def test_zweiter_lauf_ergaenzt_fehlende_gruppe(rechte):
    """Ein erneuter Lauf ergänzt fehlende Gruppen und behält den Schlüssel,
    weil n8n nur den bestehenden kennt."""
    benutzer, _ = _anlegen('--gruppe', gruppen.DIENST)
    alt = Token.objects.get(user=benutzer).key

    _anlegen()

    assert benutzer.groups.filter(name=gruppen.BELEGUEBERNAHME).exists()
    assert Token.objects.get(user=benutzer).key == alt
