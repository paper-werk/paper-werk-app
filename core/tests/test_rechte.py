"""Jedes fachliche Modell im Admin ist einer Rolle zugeordnet.

Ein Modell, das im Admin registriert, aber in ``faktura_rechte`` nicht
aufgeführt ist, sieht nur der Superuser. Geprüft werden die Rechte, die ein
Konto der Gruppe nach den Rechtebefehlen tatsächlich hat.
"""

import pytest
from django.contrib import admin

from core import gruppen
from erfassung.management.commands.erfassung_rechte import NUR_LEITUNG

#: Apps, deren Modelle die Arbeitsgruppen nutzen. Ohne ``core``, weil
#: Benutzer, Gruppen und Schlüssel nur Verwaltern zustehen.
FACHLICHE_APPS = {'faktura', 'erfassung'}


def _modelle_im_menue():
    return [modell for modell in admin.site._registry
            if modell._meta.app_label in FACHLICHE_APPS]


def _darf_sehen(person, modell) -> bool:
    opts = modell._meta
    return person.has_perm(f'{opts.app_label}.view_{opts.model_name}')


@pytest.mark.django_db
@pytest.mark.parametrize('gruppe', [gruppen.BUERO, gruppen.PROJEKTLEITUNG])
def test_jedes_fachliche_modell_hat_eine_rolle(konto, gruppe):
    person = konto(gruppe, 'person')
    nur_leitung = gruppe == gruppen.BUERO and set(NUR_LEITUNG)

    fehlt = [modell._meta.label for modell in _modelle_im_menue()
             if not (nur_leitung and modell._meta.model_name in nur_leitung)
             and not _darf_sehen(person, modell)]

    assert fehlt == [], f'{gruppe} sieht nicht: {fehlt}'


@pytest.mark.django_db
def test_das_buero_sieht_keine_einkaufspreise(konto):
    person = konto(gruppen.BUERO, 'person')

    sichtbar = [modell._meta.label for modell in _modelle_im_menue()
                if modell._meta.model_name in NUR_LEITUNG
                and _darf_sehen(person, modell)]

    assert sichtbar == []


@pytest.mark.django_db
def test_die_beleguebernahme_darf_genau_das_noetige(rollenrechte):
    """Der n8n-Zugang für Eingangsrechnungen darf anlegen, ansehen und
    Projekte lesen, aber keine Fremdleistungen und keine Belege."""
    from django.contrib.auth.models import Group

    gruppe = Group.objects.get(name=gruppen.BELEGUEBERNAHME)
    rechte = {f'{r.content_type.app_label}.{r.codename}'
              for r in gruppe.permissions.select_related('content_type')}

    assert rechte == {'erfassung.add_eingangsrechnung',
                      'erfassung.view_eingangsrechnung',
                      'faktura.view_projekt'}
