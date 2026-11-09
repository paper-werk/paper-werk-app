"""Rechte der Sammelaktionen in den Beleglisten.

Django führt eine Aktion ohne ``allowed_permissions`` für jeden aus, der die
Liste sehen darf. Die Tests laufen deshalb mit einzeln vergebenen Rechten;
die Gruppen ``buero`` und ``leitung`` haben stets alle Rechte an Belegen.
"""

import pytest
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.test import RequestFactory
from django.urls import reverse

from faktura import services
from faktura.admin.beleg import BelegAdmin
from faktura.models import (
    Angebot,
    Auftrag,
    Beleg,
    BelegStatus,
    BelegTyp,
    Rechnung,
)
from faktura.tests.admin.hilfen import User


def _konto(*rechte):
    konto = User.objects.create_user(
        username='einzelrechte', email='e@example.invalid',
        password='geheim12345', is_staff=True)
    konto.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='faktura', codename__in=rechte))
    return konto


def _ausfuehren(client, liste, aktion, beleg):
    return client.post(
        reverse(f'admin:faktura_{liste}_changelist'),
        {'action': aktion, '_selected_action': [str(beleg.pk)]},
        follow=True,
    )


def _belegadmins():
    return [modeladmin for modeladmin in admin.site._registry.values()
            if isinstance(modeladmin, BelegAdmin)]


def test_jede_aktion_einer_belegliste_nennt_ihr_recht():
    """Schließt auch künftige Aktionen und Belegarten ein."""
    ohne_recht = [
        f'{type(modeladmin).__name__}.{name}'
        for modeladmin in _belegadmins()
        for name in modeladmin.actions
        if not getattr(getattr(modeladmin, name), 'allowed_permissions', None)
    ]

    assert not ohne_recht


@pytest.mark.django_db
@pytest.mark.parametrize(('modell', 'aktion', 'recht'), [
    (Rechnung, 'action_festschreiben', 'change_rechnung'),
    (Rechnung, 'action_korrigieren', 'change_rechnung'),
    (Rechnung, 'action_nachlass', 'change_rechnung'),
    (Rechnung, 'action_mahnen', 'change_rechnung'),
    (Rechnung, 'action_zahlung', 'add_zahlung'),
    (Angebot, 'action_festschreiben', 'change_angebot'),
    (Angebot, 'action_in_auftrag', 'change_angebot'),
    (Angebot, 'action_in_rechnung', 'change_angebot'),
    (Auftrag, 'action_in_lieferschein', 'change_auftrag'),
])
def test_angeboten_wird_die_aktion_nur_mit_ihrem_recht(modell, aktion, recht):
    ansehen = f'view_{modell._meta.model_name}'
    anfrage = RequestFactory().get('/')
    modeladmin = admin.site.get_model_admin(modell)

    anfrage.user = _konto(ansehen)
    assert aktion not in modeladmin.get_actions(anfrage)

    anfrage.user = User.objects.get(pk=anfrage.user.pk)
    anfrage.user.user_permissions.add(
        Permission.objects.get(content_type__app_label='faktura',
                               codename=recht))
    assert aktion in modeladmin.get_actions(anfrage)


@pytest.mark.django_db
class TestNurAnsehenAendertNichts:
    """Ein direkter POST bewirkt nichts, auch wenn die Aktion nicht angeboten
    wird."""

    @pytest.fixture
    def ansehen_rechnung(self, client):
        client.force_login(_konto('view_rechnung'))
        return client

    @pytest.fixture
    def ansehen_angebot(self, client):
        client.force_login(_konto('view_angebot'))
        return client

    def test_kein_festschreiben(self, ansehen_rechnung, rechnung):
        _ausfuehren(ansehen_rechnung, 'rechnung', 'action_festschreiben',
                    rechnung)

        rechnung.refresh_from_db()
        assert rechnung.status == BelegStatus.ENTWURF
        assert rechnung.nummer is None

    @pytest.mark.parametrize('aktion',
                             ['action_in_auftrag', 'action_in_rechnung'])
    def test_kein_folgebeleg(self, ansehen_angebot, angebot, aktion):
        services.beleg_festschreiben(beleg_id=angebot.pk)
        vorher = Beleg.objects.count()

        _ausfuehren(ansehen_angebot, 'angebot', aktion, angebot)

        assert Beleg.objects.count() == vorher

    def test_kein_storno(self, ansehen_rechnung, rechnung):
        services.beleg_festschreiben(beleg_id=rechnung.pk)
        vorher = Beleg.objects.count()

        _ausfuehren(ansehen_rechnung, 'rechnung', 'action_korrigieren',
                    rechnung)

        assert Beleg.objects.count() == vorher

    def test_keine_mahnung(self, ansehen_rechnung, rechnung, ueberfaellig):
        ueberfaellig(rechnung)
        vorher = Beleg.objects.count()

        _ausfuehren(ansehen_rechnung, 'rechnung', 'action_mahnen', rechnung)

        assert Beleg.objects.count() == vorher

    @pytest.mark.parametrize(('aktion', 'zwischenseite'), [
        ('action_nachlass', 'admin/faktura/nachlass.html'),
        ('action_zahlung', 'admin/faktura/zahlung.html'),
    ])
    def test_keine_zwischenseite(self, ansehen_rechnung, rechnung, aktion,
                                 zwischenseite):
        services.beleg_festschreiben(beleg_id=rechnung.pk)

        antwort = _ausfuehren(ansehen_rechnung, 'rechnung', aktion, rechnung)

        assert zwischenseite not in [t.name for t in antwort.templates]


@pytest.mark.django_db
class TestMitAenderungsrecht:
    """Gegenprobe mit den einzeln vergebenen Rechten."""

    def test_festschreiben(self, client, rechnung):
        client.force_login(_konto('view_rechnung', 'change_rechnung'))

        _ausfuehren(client, 'rechnung', 'action_festschreiben', rechnung)

        rechnung.refresh_from_db()
        assert rechnung.status == BelegStatus.FESTGESCHRIEBEN

    def test_folgebeleg(self, client, angebot):
        services.beleg_festschreiben(beleg_id=angebot.pk)
        client.force_login(_konto('view_angebot', 'change_angebot'))

        _ausfuehren(client, 'angebot', 'action_in_rechnung', angebot)

        assert Beleg.objects.filter(typ=BelegTyp.RECHNUNG).count() == 1
