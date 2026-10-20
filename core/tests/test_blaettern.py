"""Blättern auf Detailseiten (``core/blaettern.py``), am Benutzer-Admin."""

from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from core import blaettern

User = get_user_model()
LISTE = reverse('admin:core_user_changelist')
FILTER = 'is_staff__exact=1'


def _aendern(user):
    return reverse('admin:core_user_change', args=[user.pk])


@pytest.fixture
def benutzer(db):
    """b, c, d sind Mitarbeiter. Nach Name: admin, b, c, d."""
    return {name: User.objects.create_user(username=name, password='x',
                                           is_staff=True)
            for name in ('b', 'c', 'd')}


def _pfeile(client, user, filter_=FILTER):
    adresse = _aendern(user)
    if filter_ is not None:
        adresse += '?' + urlencode({'_changelist_filters': filter_})
    return client.get(adresse).context['blaettern']


def _ziel(url):
    return urlparse(url).path


@pytest.mark.django_db
class TestNachbarn:

    def test_mitte(self, admin_client, benutzer):
        admin_client.get(f'{LISTE}?{FILTER}&o=1')
        pfeile = _pfeile(admin_client, benutzer['c'], f'{FILTER}&o=1')

        assert (pfeile['stelle'], pfeile['anzahl']) == (3, 4)
        assert _ziel(pfeile['zurueck']) == _aendern(benutzer['b'])
        assert _ziel(pfeile['weiter']) == _aendern(benutzer['d'])
        assert parse_qs(urlparse(pfeile['weiter']).query) == {
            '_changelist_filters': [f'{FILTER}&o=1']}

    def test_raender(self, admin_client, admin_user, benutzer):
        admin_client.get(f'{LISTE}?{FILTER}&o=1')

        assert _pfeile(admin_client, admin_user, f'{FILTER}&o=1')['zurueck'] \
            is None
        assert _pfeile(admin_client, benutzer['d'], f'{FILTER}&o=1')['weiter'] \
            is None

    def test_geloeschte_werden_uebersprungen(self, admin_client, benutzer):
        admin_client.get(f'{LISTE}?{FILTER}&o=1')
        benutzer['c'].delete()

        pfeile = _pfeile(admin_client, benutzer['b'], f'{FILTER}&o=1')

        assert _ziel(pfeile['weiter']) == _aendern(benutzer['d'])

    def test_wer_aus_dem_filter_faellt_bleibt_in_der_reihenfolge(
            self, admin_client, benutzer):
        """Hauptanwendung: Entwürfe nacheinander versenden. Ein versendeter
        Beleg ist kein Entwurf mehr, "Weiter" führt trotzdem zum nächsten."""
        admin_client.get(f'{LISTE}?{FILTER}&o=1')
        User.objects.filter(pk=benutzer['c'].pk).update(is_staff=False)

        pfeile = _pfeile(admin_client, benutzer['c'], f'{FILTER}&o=1')

        assert pfeile['stelle'] == 3
        assert _ziel(pfeile['weiter']) == _aendern(benutzer['d'])

    def test_ohne_schnappschuss_keine_pfeile(self, admin_client, benutzer):
        seite = admin_client.get(_aendern(benutzer['c']))

        assert seite.context['blaettern'] is None
        assert 'data-blaettern' not in seite.content.decode()

    def test_ohne_filter_in_der_adresse_gilt_die_letzte_liste(
            self, admin_client, benutzer):
        """Akten und andere Seiten verlinken ohne ``_changelist_filters``."""
        admin_client.get(f'{LISTE}?o=1')
        admin_client.get(f'{LISTE}?{FILTER}&o=-1')

        pfeile = _pfeile(admin_client, benutzer['c'], None)

        assert _ziel(pfeile['weiter']) == _aendern(benutzer['b'])

    def test_die_seitenzahl_gehoert_nicht_zum_filter(self):
        assert blaettern.filterschluessel(f'p=2&{FILTER}') == FILTER

    def test_pfeile_im_html(self, admin_client, benutzer):
        admin_client.get(f'{LISTE}?{FILTER}&o=1')

        seite = admin_client.get(
            _aendern(benutzer['c']) + '?'
            + urlencode({'_changelist_filters': f'{FILTER}&o=1'})
        ).content.decode()

        assert 'data-blaettern' in seite
        assert '3 von 4' in seite


@pytest.mark.django_db
class TestSchnappschuss:

    def test_hoechstens_zehn_listen(self, admin_client, benutzer):
        for i in range(blaettern.MAX_LISTEN + 2):
            admin_client.get(f'{LISTE}?q=x{i}')

        listen = admin_client.session[blaettern.SITZUNG]
        assert len(listen) == blaettern.MAX_LISTEN
        assert listen[-1]['filter'] == f'q=x{blaettern.MAX_LISTEN + 1}'

    def test_dieselbe_liste_ersetzt_ihren_schnappschuss(self, admin_client,
                                                         benutzer):
        admin_client.get(f'{LISTE}?{FILTER}')
        admin_client.get(f'{LISTE}?{FILTER}&p=1')

        assert len(admin_client.session[blaettern.SITZUNG]) == 1

    def test_nicht_sichtbare_werden_uebersprungen(self, rf, benutzer):
        anfrage = rf.get('/')
        anfrage.session = {blaettern.SITZUNG: [{
            'modell': 'core.user', 'filter': '',
            'pks': [str(benutzer[n].pk) for n in 'bcd']}]}

        pfeile = blaettern.nachbarn(
            anfrage, User, benutzer['b'].pk,
            User.objects.exclude(pk=benutzer['c'].pk),
            lambda pk: f'/{pk}/')

        assert pfeile['weiter'] == f'/{benutzer["d"].pk}/'
