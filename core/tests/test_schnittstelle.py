"""Zugangsregeln der Schnittstelle: Authentifizierung, Selbstauskunft,
Rechte, Schema.

Alles davon liegt in ``core/schnittstelle/`` und läuft deshalb auch im
CI-Lauf "nur Kern". Fachliche Endpunkte testen die jeweiligen Apps.
"""

import pytest
from django.contrib.auth.models import Permission
from rest_framework.authtoken.models import Token
from rest_framework.generics import ListAPIView
from rest_framework.serializers import ModelSerializer
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from faktura.models import Kontakt

# Die Fixture heißt "angemeldet", weil diese Tests die Authentifizierung
# selbst prüfen.


@pytest.fixture
def dienst(django_user_model):
    """Dienstzugang ohne Rechte, wie ``api_schluessel`` ihn vor der
    Gruppenzuordnung anlegt."""
    benutzer = django_user_model.objects.create(username='n8n', is_staff=False)
    benutzer.set_unusable_password()
    benutzer.save(update_fields=['password'])
    return benutzer


@pytest.fixture
def angemeldet(dienst):
    """Client mit gültigem Token im Authorization-Header."""
    schluessel = Token.objects.create(user=dienst)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Token {schluessel.key}')
    return client


# ---------------------------------------------------------------------------
# Authentifizierung
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAnmeldung:

    def test_das_lebenszeichen_braucht_keine_anmeldung(self):
        """Healthchecks laufen beim Start des Containers, bevor ein Token
        existiert."""
        antwort = APIClient().get('/api/v1/status/')

        assert antwort.status_code == 200
        assert antwort.json()['stand'] == 'bereit'

    def test_das_lebenszeichen_verraet_keine_endpunkte(self):
        """Der einzige Endpunkt ohne Authentifizierung gibt keine Auskunft über
        andere Endpunkte."""
        daten = APIClient().get('/api/v1/status/').json()

        assert set(daten) == {'dienst', 'stand'}

    def test_ohne_schluessel_kein_zugang(self):
        assert APIClient().get('/api/v1/').status_code == 401
        assert APIClient().get('/api/v1/ich/').status_code == 401

    def test_mit_falschem_schluessel_kein_zugang(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Token nichtsdergleichen')

        assert client.get('/api/v1/ich/').status_code == 401

    def test_mit_schluessel_geht_es(self, angemeldet):
        assert angemeldet.get('/api/v1/').status_code == 200

    def test_der_schluessel_kommt_im_kopf_wie_bei_paperless(self, dienst):
        """Gleiches Verfahren wie bei Paperless-ngx (Header und Präfix), damit
        n8n beide Zugänge gleich einrichtet."""
        schluessel = Token.objects.create(user=dienst)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {schluessel.key}')

        assert client.get('/api/v1/ich/').status_code == 200


# ---------------------------------------------------------------------------
# Selbstauskunft
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSelbstauskunft:

    def test_nennt_den_angemeldeten_benutzer(self, angemeldet):
        daten = angemeldet.get('/api/v1/ich/').json()

        assert daten['benutzer'] == 'n8n'
        assert daten['ist_mitarbeiter'] is False
        assert daten['ist_verwalter'] is False

    def test_ohne_rechte_ist_die_liste_leer(self, angemeldet):
        """Häufigster Fall beim Einrichten: Zugang ohne Gruppe."""
        assert angemeldet.get('/api/v1/ich/').json()['rechte'] == {}

    def test_zeigt_die_rechte_nach_modell_gruppiert(self, angemeldet, dienst):
        """Gruppiert nach Modell, etwa ``faktura.beleg: ['view']``."""
        dienst.user_permissions.add(
            Permission.objects.get(codename='view_beleg', content_type__app_label='faktura'),
            Permission.objects.get(codename='add_beleg', content_type__app_label='faktura'),
        )

        rechte = angemeldet.get('/api/v1/ich/').json()['rechte']

        assert rechte == {'faktura.beleg': ['add', 'view']}

    def test_fremde_rechte_bleiben_draussen(self, angemeldet, dienst):
        """Rechte von admin, sessions und contenttypes erscheinen nicht."""
        dienst.user_permissions.add(
            Permission.objects.get(codename='view_logentry', content_type__app_label='admin'),
        )

        assert angemeldet.get('/api/v1/ich/').json()['rechte'] == {}

    def test_rechte_an_der_erfassung_stehen_dabei(self, angemeldet, dienst):
        """Die Übernahme von Eingangsrechnungen braucht Rechte an
        ``erfassung``; die Selbstauskunft zeigt sie."""
        dienst.user_permissions.add(Permission.objects.get(
            codename='add_eingangsrechnung', content_type__app_label='erfassung'))

        rechte = angemeldet.get('/api/v1/ich/').json()['rechte']

        assert rechte == {'erfassung.eingangsrechnung': ['add']}


# ---------------------------------------------------------------------------
# Modellrechte
# ---------------------------------------------------------------------------

class KundenProbe(ListAPIView):
    """Endpunkt nur für den Test, ohne eigene ``permission_classes``.

    Geprüft wird die Vorgabe aus den Settings für eine gewöhnliche View.
    """

    queryset = Kontakt.objects.all()

    class serializer_class(ModelSerializer):
        class Meta:
            model = Kontakt
            fields = ['id', 'nummer', 'name']


@pytest.mark.django_db
class TestModellrechte:
    """Lesen verlangt das ``view``-Recht (``core.permissions.Modellrechte``).

    ``DjangoModelPermissions`` prüft nur schreibende Zugriffe; ein
    Dienstzugang mit irgendeinem Recht könnte sonst alle Modelle lesen.
    """

    def _antwort(self, benutzer):
        anfrage = APIRequestFactory().get('/beliebig/')
        force_authenticate(anfrage, user=benutzer)
        return KundenProbe.as_view()(anfrage)

    def test_ohne_leserecht_kein_lesen(self, dienst):
        assert self._antwort(dienst).status_code == 403

    def test_mit_leserecht_geht_es(self, dienst):
        dienst.user_permissions.add(
            Permission.objects.get(codename='view_kontakt', content_type__app_label='faktura'),
        )

        assert self._antwort(dienst).status_code == 200

    def test_ein_fremdes_recht_oeffnet_nichts(self, dienst):
        """Ein Recht an einem anderen Modell erlaubt kein Lesen; Djangos
        Vorgabe ließe es zu."""
        dienst.user_permissions.add(
            Permission.objects.get(codename='view_projekt', content_type__app_label='faktura'),
        )

        assert self._antwort(dienst).status_code == 403

    def test_schreiben_verlangt_weiterhin_sein_eigenes_recht(self, dienst):
        """Die Prüfung der schreibenden Rechte bleibt erhalten."""
        dienst.user_permissions.add(
            Permission.objects.get(codename='view_kontakt', content_type__app_label='faktura'),
        )
        anfrage = APIRequestFactory().post('/beliebig/', {})
        force_authenticate(anfrage, user=dienst)

        assert KundenProbe.as_view()(anfrage).status_code == 403


# ---------------------------------------------------------------------------
# Schema und Dokumentation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSchema:

    def test_das_schema_entsteht_ohne_fehler(self, angemeldet):
        """Ein Fehler beim Erzeugen des Schemas fiele sonst erst beim Aufruf
        der Doku auf."""
        antwort = angemeldet.get('/api/v1/schema/')

        assert antwort.status_code == 200

    def test_die_doku_wird_ausgeliefert(self, angemeldet):
        assert angemeldet.get('/api/v1/doku/').status_code == 200

    def test_das_inhaltsverzeichnis_verweist_auf_die_selbstauskunft(self, angemeldet):
        """Die URLs entstehen über reverse(); eine umbenannte Route lässt den
        Test fehlschlagen."""
        daten = angemeldet.get('/api/v1/').json()

        assert daten['ich'].endswith('/api/v1/ich/')

    def test_das_inhaltsverzeichnis_nennt_jeden_endpunkt_des_routers(
            self, angemeldet):
        """Jede Ressource des Routers erscheint im Verzeichnis."""
        from core.schnittstelle.urls import router

        daten = angemeldet.get('/api/v1/').json()

        for praefix, _viewset, _name in router.registry:
            assert praefix in daten, f'{praefix} fehlt im Inhaltsverzeichnis'


# ---------------------------------------------------------------------------
# Registrierung von Endpunkten und Ersatz
# ---------------------------------------------------------------------------

class TestEndpunktAnmeldung:
    """``core.erweiterungen.api_endpoint()``: Ersatz der Belegauskunft aus
    ``faktura`` durch einen Zusatz."""

    @pytest.fixture(autouse=True)
    def leere_liste(self, monkeypatch):
        from core import erweiterungen

        monkeypatch.setattr(erweiterungen, '_API_ENDPUNKTE', {})
        return erweiterungen

    class Schmal:
        pass

    class Voll:
        pass

    def test_der_ersatz_gewinnt_nach_dem_original(self, leere_liste):
        leere_liste.api_endpoint('belege', self.Schmal, 'beleg')
        leere_liste.api_endpoint('belege', self.Voll, 'beleg', ersetzt=True)

        assert leere_liste.api_endpunkte() == [('belege', self.Voll, 'beleg')]

    def test_der_ersatz_gewinnt_auch_vor_dem_original(self, leere_liste):
        """Das Ergebnis ist unabhängig von der Reihenfolge der Apps."""
        leere_liste.api_endpoint('belege', self.Voll, 'beleg', ersetzt=True)
        leere_liste.api_endpoint('belege', self.Schmal, 'beleg')

        assert leere_liste.api_endpunkte() == [('belege', self.Voll, 'beleg')]

    def test_doppelt_ohne_ersetzen_ist_ein_fehler(self, leere_liste):
        from django.core.exceptions import ImproperlyConfigured

        leere_liste.api_endpoint('belege', self.Schmal, 'beleg')

        with pytest.raises(ImproperlyConfigured, match='doppelt'):
            leere_liste.api_endpoint('belege', self.Voll, 'beleg')

    def test_weitere_verweise_fuers_verzeichnis(self, leere_liste):
        leere_liste.api_endpoint('projekte', self.Voll, 'projekt',
                                 weitere={'projekt_aufloesen': 'projekt-aufloesen'})

        assert leere_liste.api_verweise() == {'projekt_aufloesen': 'projekt-aufloesen'}
