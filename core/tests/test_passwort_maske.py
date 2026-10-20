"""Passwortfeld der Benutzerverwaltung: Link zur Passwortmaske, deutsche
Beschriftung, Button "Abbrechen".

Djangos Feld zeigt Algorithmus, Iterationen, Salt und Hash und in Django 6.1
einen nicht übersetzten Hilfetext.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


@pytest.fixture
def bea(db):
    return get_user_model().objects.create_user(username='bea',
                                                password='geheim12345x')


def _seite(client, name, benutzer):
    return client.get(reverse(name, args=[benutzer.pk])).content.decode()


def test_das_passwortfeld_zeigt_nur_den_knopf(verwaltung, bea):
    inhalt = _seite(verwaltung, 'admin:core_user_change', bea)

    assert 'Passwort zurücksetzen' in inhalt
    assert reverse('admin:auth_user_password_change', args=[bea.pk]) in inhalt \
        or '../password/' in inhalt
    for rauschen in ('pbkdf2', 'Salt', 'Hash:', 'Raw passwords', 'Reset password'):
        assert rauschen not in inhalt, f'{rauschen!r} steht noch da'


def test_ohne_passwort_heisst_der_knopf_setzen(verwaltung, db):
    """Konten aus der Microsoft-Anmeldung haben kein nutzbares Passwort."""
    ohne = get_user_model().objects.create_user(username='sso')
    ohne.set_unusable_password()
    ohne.save()

    inhalt = _seite(verwaltung, 'admin:core_user_change', ohne)

    assert 'Passwort setzen' in inhalt
    assert 'Set password' not in inhalt


def test_die_passwortmaske_hat_einen_abbrechen_knopf(verwaltung, bea):
    inhalt = _seite(verwaltung, 'admin:auth_user_password_change', bea)

    zurueck = reverse('admin:core_user_change', args=[bea.pk])
    assert f'href="{zurueck}"' in inhalt
    assert 'Abbrechen' in inhalt


def test_das_passwort_setzen_wirkt_weiterhin(verwaltung, bea):
    """Das eigene Template lässt das Formular funktionsfähig."""
    antwort = verwaltung.post(
        reverse('admin:auth_user_password_change', args=[bea.pk]),
        {'password1': 'NeuesGeheimnis-2026', 'password2': 'NeuesGeheimnis-2026'})

    bea.refresh_from_db()
    assert antwort.status_code == 302
    assert bea.check_password('NeuesGeheimnis-2026')
