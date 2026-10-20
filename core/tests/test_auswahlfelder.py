"""Höhe der Rechteauswahl in Gruppen- und Benutzermaske.

Djangos ``filter_horizontal`` nimmt die Höhe aus dem ``size``-Attribut; ohne
Angabe zeigt der Browser vier Zeilen von rund zweihundert Rechten.
``core/static/core/css/auswahlfelder.css`` setzt die Höhe. Die Tests prüfen,
dass das Stylesheet in der Maske eingebunden ist.
"""

import pytest
from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse

User = get_user_model()
STILBLATT = 'core/css/auswahlfelder.css'


@pytest.mark.parametrize('modell', [Group, User])
def test_die_maske_laedt_das_stilblatt(modell):
    dateien = [str(d) for d in site.get_model_admin(modell).media._css['all']]

    assert any(STILBLATT in d for d in dateien), dateien


def test_es_steht_auch_im_ausgelieferten_html(verwaltung, db):
    gruppe = Group.objects.create(name='Leistungserfassung')

    inhalt = verwaltung.get(
        reverse('admin:auth_group_change', args=[gruppe.pk])).content.decode()

    assert STILBLATT in inhalt
    # Das Feld selbst ist vorhanden. Geprüft wird die Klasse ``selectfilter``
    # am gerenderten ``<select>``; das zweispaltige ``selector``-Markup, auf
    # das die CSS-Regel zielt, erzeugt SelectFilter2.js erst im Browser.
    assert 'selectfilter' in inhalt
