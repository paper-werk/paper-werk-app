"""Meldungen der Anmeldemaske (core.admin.Anmeldeformular und
templates/unfold/helpers/messages/errornote.html)."""

import pytest
from django.contrib.auth import get_user_model

pytestmark = pytest.mark.django_db

LOGIN = '/admin/login/'
MELDUNG = ('Benutzername oder Passwort falsch. Beim Passwort zählt die '
           'Groß- und Kleinschreibung.')
SAMMELHINWEIS = 'Fehler korrigieren'


@pytest.fixture
def konto(db):
    return get_user_model().objects.create_user(
        username='bea', password='richtig-12345', is_staff=True)


def _seite(client, benutzer, passwort):
    antwort = client.post(LOGIN, {'username': benutzer, 'password': passwort})
    return antwort.content.decode()


class TestFalscheZugangsdaten:

    def test_eine_meldung_ohne_sammelhinweis(self, client, konto):
        seite = _seite(client, 'bea', 'falsch')

        assert MELDUNG in seite
        assert 'Staff-Account' not in seite
        assert SAMMELHINWEIS not in seite

    def test_das_passwort_unterscheidet_gross_und_klein(self, client, konto):
        assert MELDUNG in _seite(client, 'bea', 'Richtig-12345')

    def test_der_benutzername_nicht(self, client, konto):
        antwort = client.post(LOGIN, {'username': 'Bea',
                                      'password': 'richtig-12345'})

        assert antwort.status_code == 302

    def test_ohne_mitarbeiter_status_dieselbe_meldung(self, client, konto):
        konto.is_staff = False
        konto.save()

        assert MELDUNG in _seite(client, 'bea', 'richtig-12345')


class TestLeereFelder:

    def test_der_sammelhinweis_bleibt_bei_feldfehlern(self, client):
        seite = _seite(client, '', '')

        assert SAMMELHINWEIS in seite

    def test_die_aenderungsmaske_zeigt_ihn_weiter(self, admin_client):
        """In der Änderungsmaske ist ``errors`` eine Liste; die Ausnahme für
        allgemeine Fehler greift dort nicht."""
        seite = admin_client.post('/admin/core/user/add/', {}).content.decode()

        assert SAMMELHINWEIS in seite
