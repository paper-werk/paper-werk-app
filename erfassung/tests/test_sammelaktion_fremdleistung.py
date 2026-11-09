"""Recht der Sammelaktion „In Rechnung übernehmen“ an Fremdleistungen.

Die Aktion legt Belege an und verlangt deshalb ``faktura.add_beleg``.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory
from django.urls import reverse

from erfassung.models import Eingangsrechnung, Fremdleistung
from faktura.models import Beleg, Kontakt

User = get_user_model()


def _konto(*rechte):
    konto = User.objects.create_user(
        username='einzelrechte', email='e@example.invalid',
        password='geheim12345', is_staff=True)
    konto.user_permissions.add(*Permission.objects.filter(
        codename__in=rechte))
    return konto


@pytest.fixture
def posten(db, projekt):
    labor = Kontakt.anlegen(name='Labor', nummer='L-1')
    rechnung = Eingangsrechnung.objects.create(
        lieferant=labor, nummer='AL-1', datum=date(2026, 8, 1),
        betrag_netto=Decimal('200.00'))
    return Fremdleistung.objects.create(
        rechnung=rechnung, projekt=projekt, bezeichnung='Paket 4711',
        menge=Decimal('2'), einkaufspreis=Decimal('96.00'))


def _uebernehmen(client, posten):
    return client.post(
        reverse('admin:erfassung_fremdleistung_changelist'),
        {'action': 'in_rechnung', 'index': '0', 'bestaetigt': 'ja',
         'ziel': '', '_selected_action': [str(posten.pk)]},
        follow=True)


def test_mit_ansehen_entsteht_keine_rechnung(client, posten):
    client.force_login(_konto('view_fremdleistung'))

    _uebernehmen(client, posten)

    assert not Beleg.objects.exists()


def test_mit_belegrecht_entsteht_die_rechnung(client, posten):
    client.force_login(_konto('view_fremdleistung', 'add_beleg'))

    _uebernehmen(client, posten)

    assert Beleg.objects.count() == 1


def test_angeboten_wird_sie_nur_mit_belegrecht(db):
    modeladmin = admin.site.get_model_admin(Fremdleistung)
    anfrage = RequestFactory().get('/')

    anfrage.user = _konto('view_fremdleistung')
    assert 'in_rechnung' not in modeladmin.get_actions(anfrage)

    anfrage.user = User.objects.get(pk=anfrage.user.pk)
    anfrage.user.user_permissions.add(Permission.objects.get(
        content_type__app_label='faktura', codename='add_beleg'))
    assert 'in_rechnung' in modeladmin.get_actions(anfrage)
