"""API-Schlüssel im Admin: anlegen, ansehen, ändern, löschen.

``TokenProxy.pk`` ist die Benutzer-ID. Jede URL muss sie in den Schlüssel
umsetzen, sonst sucht der Admin einen Schlüssel "5".
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.authtoken.models import Token

LISTE = 'admin:authtoken_tokenproxy_changelist'
ANLEGEN = 'admin:authtoken_tokenproxy_add'
AENDERN = 'admin:authtoken_tokenproxy_change'
LOESCHEN = 'admin:authtoken_tokenproxy_delete'


@pytest.fixture
def dienst(db):
    return get_user_model().objects.create_user(username='n8n')


def test_nach_dem_anlegen_steht_man_beim_neuen_schluessel(verwaltung, dienst):
    antwort = verwaltung.post(reverse(ANLEGEN),
                              {'user': dienst.pk, '_continue': '1'},
                              follow=True)

    token = Token.objects.get(user=dienst)
    assert antwort.redirect_chain[-1][0] == reverse(AENDERN, args=[dienst.pk])
    assert antwort.status_code == 200
    assert token.key in antwort.content.decode(), 'der Schlüssel steht da'


def test_das_anlegeformular_fragt_keinen_schluessel_ab(verwaltung, db):
    """Der Schlüssel entsteht beim Speichern, das Formular fragt ihn nicht ab."""
    formular = verwaltung.get(reverse(ANLEGEN)).context['adminform'].form

    assert 'key' not in formular.fields
    assert 'user' in formular.fields


def test_die_liste_verweist_auf_eine_seite_die_es_gibt(verwaltung, dienst):
    token = Token.objects.create(user=dienst)

    inhalt = verwaltung.get(reverse(LISTE)).content.decode()
    verweis = reverse(AENDERN, args=[dienst.pk])

    assert verweis in inhalt
    assert verwaltung.get(verweis).status_code == 200
    assert token.key in inhalt


def test_aendern_haengt_den_schluessel_um(verwaltung, dienst):
    """Der Schlüssel bleibt, der Benutzer wechselt."""
    token = Token.objects.create(user=dienst)
    anderer = get_user_model().objects.create_user(username='n8n-zwei')

    antwort = verwaltung.post(reverse(AENDERN, args=[dienst.pk]),
                              {'user': anderer.pk})

    assert antwort.status_code == 302
    assert Token.objects.get(key=token.key).user == anderer


def test_loeschen_trifft_den_richtigen_schluessel(verwaltung, dienst):
    Token.objects.create(user=dienst)
    bleibt = Token.objects.create(
        user=get_user_model().objects.create_user(username='bleibt'))

    verwaltung.post(reverse(LOESCHEN, args=[dienst.pk]), {'post': 'yes'})

    assert not Token.objects.filter(user=dienst).exists()
    assert Token.objects.filter(pk=bleibt.pk).exists()
