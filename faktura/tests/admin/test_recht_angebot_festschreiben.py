"""Recht ``angebot_festschreiben``.

Festschreiben, Versenden, erneutes Versenden und Wiedereröffnen eines
Angebots verlangen es zusätzlich zum Änderungsrecht. ``faktura_rechte``
vergibt es nicht und entzieht es nicht; die Gruppe Büro hat es deshalb nach
der Einrichtung nicht.
"""

from decimal import Decimal
from io import StringIO

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.urls import reverse

from core import gruppen
from faktura import services
from faktura.models import BelegStatus, BelegTyp

LEERE_MASKE = {'an': '', 'betreff': '', 'nachricht': ''}


def _recht():
    return Permission.objects.get(content_type__app_label='faktura',
                                  codename='angebot_festschreiben')


@pytest.fixture
def bea(konto):
    """Büro ohne ``angebot_festschreiben``."""
    return konto(gruppen.BUERO, 'bea')


@pytest.fixture
def ohne_recht(client, bea):
    client.force_login(bea)
    return client


@pytest.fixture
def mit_recht(client, bea):
    bea.user_permissions.add(_recht())
    client.force_login(bea)
    return client


@pytest.fixture
def angebot(kunde):
    beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Planung', menge=Decimal('8'),
        einzelpreis=Decimal('95.00'), steuersatz='19.00')
    return beleg


def _url(beleg, aktion, art='angebot'):
    return reverse(f'admin:faktura_{art}_detail_{aktion}', args=[beleg.pk])


@pytest.mark.django_db
class TestOhneRecht:

    @pytest.mark.parametrize('knopf', ['nur_festschreiben', 'herunterladen',
                                       'senden'])
    def test_die_versandmaske_schreibt_nicht_fest(self, ohne_recht, angebot,
                                                  knopf):
        daten = {**LEERE_MASKE, knopf: '1', 'an': 'kunde@muster.example'}

        antwort = ohne_recht.post(_url(angebot, 'versenden'), daten)

        angebot.refresh_from_db()
        assert antwort.status_code == 403
        assert angebot.status == BelegStatus.ENTWURF

    def test_die_versandmaske_oeffnet_nicht(self, ohne_recht, angebot):
        assert ohne_recht.get(_url(angebot, 'versenden')).status_code == 403

    def test_die_sammelaktion_schreibt_nicht_fest(self, ohne_recht, angebot):
        ohne_recht.post(reverse('admin:faktura_angebot_changelist'),
                        {'action': 'action_festschreiben',
                         '_selected_action': [str(angebot.pk)]})

        angebot.refresh_from_db()
        assert angebot.status == BelegStatus.ENTWURF

    def test_kein_erneuter_versand(self, ohne_recht, angebot):
        services.beleg_versenden(beleg_id=angebot.pk,
                                 an='kunde@muster.example')

        antwort = ohne_recht.post(_url(angebot, 'erneut_versenden'),
                                  {**LEERE_MASKE, 'senden': '1',
                                   'an': 'kunde@muster.example'})

        assert antwort.status_code == 403

    def test_kein_wiedereroeffnen(self, ohne_recht, angebot, bea):
        """Auch nicht mit ``beleg_wiedereroeffnen``, das am Angebot nicht
        gilt."""
        assert bea.has_perm('faktura.beleg_wiedereroeffnen')
        services.beleg_festschreiben(beleg_id=angebot.pk)

        ohne_recht.post(_url(angebot, 'wiedereroeffnen'),
                        {'_form_submitted': 'on'})

        angebot.refresh_from_db()
        assert angebot.status == BelegStatus.FESTGESCHRIEBEN

    def test_die_rechnung_ist_nicht_betroffen(self, ohne_recht, rechnung):
        ohne_recht.post(_url(rechnung, 'versenden', 'rechnung'),
                        {**LEERE_MASKE, 'nur_festschreiben': '1'})

        rechnung.refresh_from_db()
        assert rechnung.status == BelegStatus.FESTGESCHRIEBEN

    def test_der_auftrag_oeffnet_mit_beleg_wiedereroeffnen(self, ohne_recht,
                                                           kunde):
        auftrag = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.AUFTRAG)
        services.position_hinzufuegen(
            beleg=auftrag, bezeichnung='Montage', menge=Decimal('1'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00')
        services.beleg_festschreiben(beleg_id=auftrag.pk)

        ohne_recht.post(_url(auftrag, 'wiedereroeffnen', 'auftrag'),
                        {'_form_submitted': 'on'})

        auftrag.refresh_from_db()
        assert auftrag.status == BelegStatus.ENTWURF


@pytest.mark.django_db
class TestMitRecht:

    @pytest.mark.parametrize('knopf', ['nur_festschreiben', 'herunterladen'])
    def test_die_versandmaske_schreibt_fest(self, mit_recht, angebot, knopf):
        mit_recht.post(_url(angebot, 'versenden'), {**LEERE_MASKE, knopf: '1'})

        angebot.refresh_from_db()
        assert angebot.status == BelegStatus.FESTGESCHRIEBEN

    def test_der_versand_geht_hinaus(self, mit_recht, angebot):
        mit_recht.post(_url(angebot, 'versenden'),
                       {**LEERE_MASKE, 'senden': '1',
                        'an': 'kunde@muster.example'})

        angebot.refresh_from_db()
        assert angebot.versendet_an == 'kunde@muster.example'

    def test_die_sammelaktion_schreibt_fest(self, mit_recht, angebot):
        mit_recht.post(reverse('admin:faktura_angebot_changelist'),
                       {'action': 'action_festschreiben',
                        '_selected_action': [str(angebot.pk)]})

        angebot.refresh_from_db()
        assert angebot.status == BelegStatus.FESTGESCHRIEBEN

    def test_das_wiedereroeffnen_geht(self, mit_recht, angebot):
        services.beleg_festschreiben(beleg_id=angebot.pk)

        mit_recht.post(_url(angebot, 'wiedereroeffnen'),
                       {'_form_submitted': 'on'})

        angebot.refresh_from_db()
        assert angebot.status == BelegStatus.ENTWURF


@pytest.mark.django_db
class TestDieEinrichtung:

    def test_vergibt_das_recht_nicht(self, rollenrechte):
        for name in (gruppen.BUERO, gruppen.PROJEKTLEITUNG, gruppen.DIENST):
            assert _recht() not in Group.objects.get(name=name).permissions.all()

    def test_entzieht_das_recht_nicht(self, rollenrechte):
        """Auch nicht in einer Gruppe, deren übrige Rechte der Befehl
        setzt."""
        buero = Group.objects.get(name=gruppen.BUERO)
        buero.permissions.add(_recht())

        call_command('faktura_rechte', stdout=StringIO())

        assert _recht() in buero.permissions.all()
