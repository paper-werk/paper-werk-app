"""Härtung für öffentlich erreichbare Installationen (#88).

Anmeldesperre (django-axes), Drosselung der API, Größengrenze für Requests
ohne Anmeldung, Content-Security-Policy und der Schalter
``DJANGO_HINTER_PROXY``.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from core import drosselung

pytestmark = pytest.mark.django_db

LOGIN = '/admin/login/'
API = '/api/v1/'


@pytest.fixture
def konto(db):
    return get_user_model().objects.create_user(
        username='bea', password='richtig-12345', is_staff=True)


def _anmelden(client, passwort):
    return client.post(LOGIN, {'username': 'bea', 'password': passwort})


class TestDieAnmeldesperre:

    def test_nach_fuenf_fehlversuchen_ist_gesperrt(self, client, konto):
        for _ in range(4):
            assert _anmelden(client, 'falsch').status_code == 200

        antwort = _anmelden(client, 'falsch')

        assert antwort.status_code == 429

    def test_gesperrt_hilft_auch_das_richtige_passwort_nicht(
            self, client, konto):
        for _ in range(5):
            _anmelden(client, 'falsch')

        assert _anmelden(client, 'richtig-12345').status_code == 429

    def test_eine_erfolgreiche_anmeldung_setzt_den_zaehler_zurueck(
            self, client, konto):
        for _ in range(4):
            _anmelden(client, 'falsch')
        assert _anmelden(client, 'richtig-12345').status_code == 302
        client.logout()

        for _ in range(4):
            assert _anmelden(client, 'falsch').status_code == 200

    def test_loeschen_im_admin_hebt_die_sperre_auf(
            self, client, konto, admin_user):
        from axes.models import AccessAttempt
        for _ in range(5):
            _anmelden(client, 'falsch')
        verwalter = Client()
        verwalter.force_login(admin_user)
        eintrag = AccessAttempt.objects.get(username='bea')

        verwalter.post(
            f'/admin/axes/accessattempt/{eintrag.pk}/delete/', {'post': 'yes'})

        assert _anmelden(client, 'richtig-12345').status_code == 302

    def test_das_menue_fuehrt_zur_liste(self, admin_client):
        seite = admin_client.get('/admin/').content.decode()

        assert 'Anmeldesperren' in seite
        assert '/admin/axes/accessattempt/' in seite


class TestDieListeDerSperren:

    def test_die_liste_laedt_mit_gesperrtem_eintrag(
            self, client, konto, admin_client):
        for _ in range(5):
            _anmelden(client, 'falsch')

        assert admin_client.get(
            '/admin/axes/accessattempt/').status_code == 200

    def test_die_aktion_entfernt_nur_abgelaufene(self, admin_client):
        from datetime import timedelta

        from axes.models import AccessAttempt
        from django.utils import timezone
        jetzt = timezone.now()
        for name, alter in (('alt', timedelta(hours=1)),
                            ('neu', timedelta(minutes=1))):
            eintrag = AccessAttempt.objects.create(
                username=name, ip_address='10.0.0.1', user_agent='',
                path_info=LOGIN, get_data='', post_data='',
                http_accept='', failures_since_start=5)
            AccessAttempt.objects.filter(pk=eintrag.pk).update(
                attempt_time=jetzt - alter)

        admin_client.post('/admin/axes/accessattempt/', {
            'action': 'abgelaufene_entfernen',
            '_selected_action': list(
                AccessAttempt.objects.values_list('pk', flat=True)),
        })

        assert list(AccessAttempt.objects.values_list(
            'username', flat=True)) == ['neu']


class TestDieDrosselung:

    @pytest.fixture
    def zwei_je_minute(self, monkeypatch):
        """DRF liest die Raten beim Import; gesetzt wird an der Klasse."""
        for klasse in (drosselung.AngemeldetDrosseln, drosselung.Fehlversuche):
            monkeypatch.setattr(klasse, 'THROTTLE_RATES',
                                {'user': '2/min', 'fehlversuch': '2/min'})

    def test_mit_anmeldung_ist_nach_der_rate_schluss(
            self, client, konto, zwei_je_minute):
        client.force_login(konto)

        antworten = [client.get(API).status_code for _ in range(3)]

        assert antworten == [200, 200, 429]

    def test_ungueltige_tokens_sperren_die_adresse(
            self, client, konto, zwei_je_minute):
        """Nach zwei ungültigen Tokens antwortet die API mit 429, auch auf
        ein gültiges Token derselben Adresse."""
        from rest_framework.authtoken.models import Token
        gueltig = Token.objects.create(user=konto).key

        antworten = [
            client.get(API, HTTP_AUTHORIZATION='Token falsch').status_code,
            client.get(API, HTTP_AUTHORIZATION='Token falsch').status_code,
            client.get(API, HTTP_AUTHORIZATION=f'Token {gueltig}').status_code,
        ]

        assert antworten == [401, 401, 429]

    def test_gueltige_tokens_zaehlen_nicht_als_fehlversuch(
            self, client, konto, zwei_je_minute, monkeypatch):
        from rest_framework.authtoken.models import Token
        gueltig = Token.objects.create(user=konto).key
        monkeypatch.setattr(drosselung.AngemeldetDrosseln, 'THROTTLE_RATES',
                            {'user': '100/min'})

        antworten = [client.get(API, HTTP_AUTHORIZATION=f'Token {gueltig}')
                     .status_code for _ in range(3)]

        assert antworten == [200, 200, 200]


class TestDieGroessengrenze:

    def test_ein_grosser_rumpf_ohne_anmeldung_wird_abgelehnt(self, client):
        antwort = client.post(LOGIN, {'feld': 'x' * 70_000})

        assert antwort.status_code == 413

    def test_mit_anmeldung_gilt_die_grenze_nicht(self, client, konto):
        client.force_login(konto)

        antwort = client.post(LOGIN, {'feld': 'x' * 70_000})

        assert antwort.status_code != 413

    def test_mit_token_entscheidet_die_schnittstelle(self, client):
        """Der Token wird erst in der View geprüft; die Middleware lässt
        den Request durch, DRF lehnt den ungültigen Token ab."""
        antwort = client.post(API, {'feld': 'x' * 70_000},
                              HTTP_AUTHORIZATION='Token ungueltig')

        assert antwort.status_code == 401

    def test_eine_normale_anmeldung_passt(self, client, konto):
        assert _anmelden(client, 'richtig-12345').status_code == 302


class TestDieSicherheitsrichtlinie:

    def test_die_anmeldeseite_traegt_sie(self, client):
        richtlinie = client.get(LOGIN)['Content-Security-Policy']

        assert "default-src 'self'" in richtlinie
        assert "frame-ancestors 'none'" in richtlinie
        assert "object-src 'none'" in richtlinie


def _prod_einstellung(hinter_proxy: str | None) -> str:
    """SECURE_PROXY_SSL_HEADER der prod-Settings in einem eigenen Prozess,
    weil Settings einmal beim Start gelesen werden."""
    umgebung = {**os.environ,
                'DJANGO_SETTINGS_MODULE': 'paperwerk.settings.prod'}
    umgebung.pop('DJANGO_HINTER_PROXY', None)
    if hinter_proxy is not None:
        umgebung['DJANGO_HINTER_PROXY'] = hinter_proxy

    ergebnis = subprocess.run(
        [sys.executable, '-c',
         'import django; django.setup();'
         'from django.conf import settings;'
         'print(settings.SECURE_PROXY_SSL_HEADER)'],
        cwd=Path(__file__).resolve().parents[2],
        env=umgebung, capture_output=True, text=True, encoding='utf-8',
    )
    assert ergebnis.returncode == 0, ergebnis.stderr
    return ergebnis.stdout.strip()


class TestDerProxySchalter:

    def test_ohne_schalter_kein_proxy_header(self):
        assert _prod_einstellung(None) == 'None'

    def test_mit_schalter_gilt_x_forwarded_proto(self):
        assert _prod_einstellung('true') == (
            "('HTTP_X_FORWARDED_PROTO', 'https')")
