"""Single Sign-on über einen OIDC-Anbieter (``core/anmeldung.py``).

Die Tests durchlaufen den Flow wie ein Browser: Login-Button absenden, zum
Anbieter weitergeleitet werden, mit Code und ``state`` zurückkehren, im
Admin ankommen. Gemockt sind nur die drei Aufrufe von allauth bei
Microsoft: Discovery, Token-Tausch und Prüfung der Token-Signatur. Session,
``state``-Prüfung, Anlegen des Kontos, Adapter, Login und Redirect laufen
echt, weil ein Test, der nur den Button im HTML findet, nichts über den
Login aussagt.

Die Fixture ``anbieter`` setzt die SSO-Settings, damit die Tests nicht von
der lokalen ``.env`` abhängen.
"""

from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from allauth.socialaccount.providers.openid_connect.views import (
    OpenIDConnectOAuth2Adapter,
)
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command

from core import gruppen
from faktura.management.commands.faktura_rechte import GRUPPE_DIENST

User = get_user_model()

TENANT = 'https://login.example.invalid/tenant/v2.0'
DISCOVERY = {
    'issuer': TENANT,
    'authorization_endpoint': f'{TENANT}/authorize',
    'token_endpoint': f'{TENANT}/token',
    'userinfo_endpoint': f'{TENANT}/userinfo',
    'jwks_uri': f'{TENANT}/keys',
}


@pytest.fixture
def anbieter(settings):
    """Settings eines konfigurierten Anbieters wie im Teststack."""
    settings.SSO_PROVIDER_ID = 'entra'
    settings.SSO_NAME = 'Microsoft'
    settings.SSO_CLIENT_ID = 'test-client'
    settings.ACCOUNT_DEFAULT_HTTP_PROTOCOL = 'http'
    settings.SOCIALACCOUNT_PROVIDERS = {'openid_connect': {'APPS': [{
        'provider_id': 'entra',
        'name': 'Microsoft',
        'client_id': 'test-client',
        'secret': 'test-geheim',
        'settings': {
            'server_url': f'{TENANT}/.well-known/openid-configuration',
            'fetch_userinfo': False,
        },
    }]}}
    with mock.patch.object(OpenIDConnectOAuth2Adapter, 'openid_config',
                           new_callable=mock.PropertyMock,
                           return_value=DISCOVERY):
        yield


@pytest.fixture
def rechte(db):
    """Gruppenrechte über dieselben Befehle wie ``setup.sh ... app``."""
    call_command('faktura_rechte', verbosity=0)
    call_command('erfassung_rechte', verbosity=0)


def token(**ansprueche):
    """Claims eines ID-Tokens von Microsoft nach dem Dekodieren."""
    return {
        'sub': 'sub-' + ansprueche.get('preferred_username', 'x'),
        'oid': 'oid-' + ansprueche.get('preferred_username', 'x'),
        'name': 'Erika Muster',
        **ansprueche,
    }


def anmelden(client, id_token):
    """Durchläuft den Login vom Button bis zum Callback und gibt die letzte
    Response zurück.

    Das Ziel des Buttons wird aus der gerenderten Anmeldeseite gelesen, damit
    ein falsches Ziel den Test fehlschlagen lässt.
    """
    seite = client.get('/admin/login/?next=/admin/')
    assert seite.status_code == 200
    formular = seite.content.decode().split('id="sso-form"')[0].rsplit('<form', 1)[1]
    ziel = formular.split('action="', 1)[1].split('"', 1)[0]

    start = client.post(ziel, {'next': '/admin/'})
    assert start.status_code == 302, start.content[:500]
    beim_anbieter = urlparse(start['Location'])
    assert beim_anbieter.geturl().startswith(DISCOVERY['authorization_endpoint'])
    abfrage = parse_qs(beim_anbieter.query)
    assert abfrage['redirect_uri'] == [
        'http://testserver/accounts/oidc/entra/login/callback/']

    with mock.patch.object(OAuth2Client, 'get_access_token', return_value={
            'access_token': 'zugang', 'token_type': 'Bearer',
            'expires_in': 3600, 'id_token': 'signiert'}), \
         mock.patch.object(OpenIDConnectOAuth2Adapter, '_decode_id_token',
                           return_value=id_token):
        return client.get('/accounts/oidc/entra/login/callback/',
                          {'code': 'einmalcode', 'state': abfrage['state'][0]})


# ── Zugang ────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_buero_kommt_in_den_admin(client, anbieter, rechte):
    antwort = anmelden(client, token(
        preferred_username='erika@betrieb.example',
        email='erika@betrieb.example',
        roles=['paper-werk-buero']))

    assert antwort.status_code == 302
    assert antwort['Location'] == '/admin/'
    # Geprüft wird, dass der Admin lädt, nicht nur der Redirect.
    assert client.get('/admin/').status_code == 200

    konto = User.objects.get(username='erika@betrieb.example')
    assert konto.email == 'erika@betrieb.example'
    assert konto.is_staff and not konto.is_superuser
    assert list(konto.groups.values_list('name', flat=True)) == [gruppen.BUERO]


@pytest.mark.django_db
def test_superuser_rolle_macht_zum_superuser(client, anbieter, rechte):
    anmelden(client, token(preferred_username='chef@betrieb.example',
                           roles=['paper-werk-superuser']))

    konto = User.objects.get(username='chef@betrieb.example')
    assert konto.is_superuser and konto.is_staff
    assert list(konto.groups.values_list('name', flat=True)) == [gruppen.SUPERUSER]
    assert client.get('/admin/core/user/').status_code == 200


@pytest.mark.django_db
def test_projektleitung_steht_fuer_sich(client, anbieter, rechte):
    """Die Rolle Projektleitung allein gibt Zugriff, den das Büro nicht hat."""
    anmelden(client, token(preferred_username='pl@betrieb.example',
                           roles=['paper-werk-projektleitung']))

    konto = User.objects.get(username='pl@betrieb.example')
    assert list(konto.groups.values_list('name', flat=True)) == [
        gruppen.PROJEKTLEITUNG]
    # Eingangsrechnungen enthalten Einkaufspreise und sind der Projektleitung
    # vorbehalten; für das Büro lädt die Seite nicht.
    liste = '/admin/erfassung/eingangsrechnung/'
    assert client.get(liste).status_code == 200
    client.logout()
    anmelden(client, token(preferred_username='erika@betrieb.example',
                           roles=['paper-werk-buero']))
    assert client.get(liste).status_code == 403


@pytest.mark.django_db
def test_ohne_rolle_abgewiesen_und_kein_konto(client, anbieter, rechte):
    """Ablehnung ohne Rolle, falls im Portal "Zuweisung erforderlich" aus
    ist."""
    antwort = anmelden(client, token(preferred_username='fremd@betrieb.example',
                                     roles=[]))

    assert antwort.status_code == 403
    assert 'noch nicht freigeschaltet' in antwort.content.decode()
    assert not User.objects.filter(username='fremd@betrieb.example').exists()
    assert not SocialAccount.objects.exists()
    assert client.get('/admin/').status_code == 302  # nicht angemeldet


@pytest.mark.django_db
def test_unbekannte_rolle_zaehlt_nicht(client, anbieter, rechte):
    """Rollen anderer Anwendungen im Verzeichnis zählen nicht."""
    antwort = anmelden(client, token(preferred_username='x@betrieb.example',
                                     roles=['andere-anwendung-admin']))
    assert antwort.status_code == 403


# ── Rollenabgleich bei jeder Anmeldung ────────────────────────────────────────

@pytest.mark.django_db
def test_entzogene_superuser_rolle_wirkt_bei_der_naechsten_anmeldung(
        client, anbieter, rechte):
    anmelden(client, token(preferred_username='chef@betrieb.example',
                           roles=['paper-werk-superuser']))
    client.logout()
    anmelden(client, token(preferred_username='chef@betrieb.example',
                           roles=['paper-werk-buero']))

    konto = User.objects.get(username='chef@betrieb.example')
    assert not konto.is_superuser
    assert konto.is_staff
    assert list(konto.groups.values_list('name', flat=True)) == [gruppen.BUERO]
    assert User.objects.filter(username='chef@betrieb.example').count() == 1


@pytest.mark.django_db
def test_von_hand_vergebene_gruppe_bleibt(client, anbieter, rechte):
    """Abgeglichen werden nur Gruppen mit Präfix ``paper-werk-``."""
    anmelden(client, token(preferred_username='erika@betrieb.example',
                           roles=['paper-werk-buero']))
    konto = User.objects.get(username='erika@betrieb.example')
    konto.groups.add(Group.objects.get(name=GRUPPE_DIENST))
    client.logout()

    anmelden(client, token(preferred_username='erika@betrieb.example',
                           roles=['paper-werk-buero']))

    assert GRUPPE_DIENST in konto.groups.values_list('name', flat=True)


@pytest.mark.django_db
def test_deaktiviertes_konto_bekommt_keine_rechte(client, anbieter, rechte):
    """Ein im Admin deaktiviertes Konto erhält keine Rechte aus dem Verzeichnis."""
    anmelden(client, token(preferred_username='erika@betrieb.example',
                           roles=['paper-werk-buero']))
    client.logout()
    konto = User.objects.get(username='erika@betrieb.example')
    konto.is_active = False
    konto.save()

    antwort = anmelden(client, token(preferred_username='erika@betrieb.example',
                                     roles=['paper-werk-superuser']))

    konto.refresh_from_db()
    assert not konto.is_superuser
    assert antwort['Location'] == '/accounts/inactive/'
    assert client.get('/admin/').status_code == 302


# ── Lokaler Login und Fehlerfälle ─────────────────────────────────────────────

@pytest.mark.django_db
def test_lokaler_login_bleibt_und_wird_nicht_angefasst(client, anbieter, rechte):
    """Der lokale Login bleibt nutzbar, auch mit konfiguriertem Anbieter."""
    User.objects.create_superuser('admin', 'admin@example.invalid', 'geheim')

    antwort = client.post('/admin/login/?next=/admin/',
                          {'username': 'admin', 'password': 'geheim'})

    assert antwort.status_code == 302
    assert client.get('/admin/').status_code == 200
    konto = User.objects.get(username='admin')
    assert konto.is_superuser  # der Rollenabgleich hat ihn nicht erfasst
    assert not konto.groups.exists()


@pytest.mark.django_db
def test_toter_anbieter_erklaert_statt_abzustuerzen(client, anbieter, rechte):
    """Nicht erreichbarer Anbieter beim Login: 503 mit Hinweisseite und Link
    auf den lokalen Login."""
    User.objects.create_superuser('admin', 'admin@example.invalid', 'geheim')
    seite = client.get('/admin/login/').content.decode()
    ziel = seite.split('id="sso-form"')[0].rsplit('<form', 1)[1]
    ziel = ziel.split('action="', 1)[1].split('"', 1)[0]

    with mock.patch.object(OpenIDConnectOAuth2Adapter, 'openid_config',
                           new_callable=mock.PropertyMock,
                           side_effect=requests.ConnectionError('Name or service not known')):
        antwort = client.post(ziel)

    assert antwort.status_code == 503
    inhalt = antwort.content.decode()
    assert 'Microsoft ist im Moment nicht erreichbar' in ' '.join(inhalt.split())
    assert 'href="/admin/login/"' in inhalt
    # Der verlinkte lokale Login funktioniert.
    client.post('/admin/login/', {'username': 'admin', 'password': 'geheim'})
    assert client.get('/admin/').status_code == 200


@pytest.mark.django_db
def test_toter_anbieter_auf_dem_rueckweg(client, anbieter, rechte):
    """Ausfall des Anbieters beim Callback: Der Token-Tausch schlägt fehl."""
    seite = client.get('/admin/login/').content.decode()
    ziel = seite.split('id="sso-form"')[0].rsplit('<form', 1)[1]
    ziel = ziel.split('action="', 1)[1].split('"', 1)[0]
    start = client.post(ziel)
    state = parse_qs(urlparse(start['Location']).query)['state'][0]

    with mock.patch.object(OAuth2Client, 'get_access_token',
                           side_effect=requests.Timeout('zu langsam')):
        antwort = client.get('/accounts/oidc/entra/login/callback/',
                             {'code': 'einmalcode', 'state': state})

    # allauth fängt diesen Fall selbst ab (Status 401). Seine Seite ist
    # englisch und ohne Link zurück und wird durch eine eigene ersetzt.
    assert antwort.status_code == 401
    inhalt = antwort.content.decode()
    assert 'Anmeldung hat nicht geklappt' in inhalt
    assert 'href="/admin/login/"' in inhalt
    assert not User.objects.exists()


@pytest.mark.django_db
def test_beim_anbieter_abgebrochen(client, anbieter, rechte):
    """Abbruch beim Anbieter (error=access_denied) führt auf eine deutsche
    Seite mit Link zurück."""
    seite = client.get('/admin/login/').content.decode()
    ziel = seite.split('id="sso-form"')[0].rsplit('<form', 1)[1]
    ziel = ziel.split('action="', 1)[1].split('"', 1)[0]
    start = client.post(ziel)
    state = parse_qs(urlparse(start['Location']).query)['state'][0]

    antwort = client.get('/accounts/oidc/entra/login/callback/',
                         {'error': 'access_denied', 'state': state}, follow=True)

    inhalt = antwort.content.decode()
    assert 'Anmeldung abgebrochen' in inhalt
    assert 'href="/admin/login/"' in inhalt


@pytest.mark.django_db
def test_ohne_client_id_kein_knopf(client, settings):
    """Ohne SSO_CLIENT_ID zeigt die Anmeldeseite keinen SSO-Button."""
    settings.SSO_CLIENT_ID = ''
    settings.SOCIALACCOUNT_PROVIDERS = {'openid_connect': {'APPS': []}}

    seite = client.get('/admin/login/').content.decode()

    assert 'id="sso-form"' not in seite
    assert 'id="login-form"' in seite
    assert client.post('/accounts/oidc/entra/login/').status_code == 404


@pytest.mark.django_db
def test_keine_selbstregistrierung_und_keine_zweite_anmeldeseite(client, anbieter):
    """Die URL-Namen, die allauth während des Logins auflöst, leiten auf den
    Admin um."""
    for adresse in ('/accounts/login/', '/accounts/signup/'):
        antwort = client.get(adresse)
        assert antwort.status_code == 302
        assert antwort['Location'].startswith('/admin/login/')


# ── Rolle und Gruppe heißen gleich ────────────────────────────────────────────

@pytest.mark.django_db
def test_die_gruppen_gibt_es_ohne_setup():
    """Die Migration legt die Gruppen an, damit die Anmeldung Rollen auch vor
    dem ersten ``setup.sh ... app`` erkennt."""
    vorhanden = set(Group.objects.values_list('name', flat=True))
    assert set(gruppen.ALLE) <= vorhanden


@pytest.mark.django_db
def test_eine_neue_paper_werk_gruppe_zaehlt_ohne_code(client, anbieter, rechte):
    """Eine neue Gruppe mit Präfix wird ohne Codeänderung als Rolle erkannt."""
    Group.objects.create(name='paper-werk-lager')

    anmelden(client, token(preferred_username='lager@betrieb.example',
                           roles=['paper-werk-lager']))

    konto = User.objects.get(username='lager@betrieb.example')
    assert list(konto.groups.values_list('name', flat=True)) == ['paper-werk-lager']
    assert konto.is_staff and not konto.is_superuser


@pytest.mark.django_db
def test_paper_werk_rolle_ohne_gruppe_zaehlt_nicht(client, anbieter, rechte):
    """Eine Rolle mit Präfix, aber ohne Gruppe (etwa durch einen Tippfehler
    im Portal), führt zur Ablehnung; es entsteht kein Konto."""
    antwort = anmelden(client, token(preferred_username='x@betrieb.example',
                                     roles=['paper-werk-bureo']))
    assert antwort.status_code == 403
