"""Dropdown "Weitere …" mit Verlauf an jedem Admin (``core.adminhilfen``)."""

import pytest
from django.contrib import admin
from django.urls import reverse

from core.adminhilfen import WEITERE, Kopfleiste

ADMINS = sorted(admin.site._registry.items(),
                key=lambda eintrag: eintrag[0]._meta.label)


@pytest.mark.parametrize(
    'modell_admin', [a for _, a in ADMINS],
    ids=[m._meta.label for m, _ in ADMINS])
def test_jeder_admin_endet_mit_weitere_und_verlauf(modell_admin):
    """Ohne ``Kopfleiste`` fehlten Verlauf (``SHOW_HISTORY`` ist aus) und
    Navigation."""
    assert isinstance(modell_admin, Kopfleiste)
    letzter = modell_admin.actions_detail[-1]
    assert isinstance(letzter, dict)
    assert letzter['title'] == WEITERE
    assert letzter['items'][-1] == 'detail_verlauf'


@pytest.mark.django_db
def test_verlauf_leitet_auf_die_history_view(admin_client, admin_user):
    adresse = reverse('admin:core_user_detail_verlauf', args=[admin_user.pk])

    antwort = admin_client.get(adresse)

    assert antwort.status_code == 302
    assert antwort['Location'] == reverse('admin:core_user_history',
                                          args=[admin_user.pk])
    assert admin_client.get(antwort['Location']).status_code == 200


@pytest.mark.django_db
def test_kein_verlauf_mehr_in_der_kopfleiste(admin_client, admin_user):
    seite = admin_client.get(reverse('admin:core_user_change',
                                     args=[admin_user.pk])).content.decode()

    assert reverse('admin:core_user_history', args=[admin_user.pk]) \
        not in seite
    assert reverse('admin:core_user_detail_verlauf',
                   args=[admin_user.pk]) in seite
