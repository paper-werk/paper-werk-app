"""Schutz des letzten Verwalters (``core/admin.py``).

Django erlaubt dem einzigen Superuser ohne Warnung, sich ``is_superuser``
oder ``is_staff`` zu entziehen oder sich zu deaktivieren. Danach erreicht
niemand mehr die Benutzerverwaltung; helfen kann nur ``manage.py
createsuperuser`` auf dem Server.

Die Tests senden Requests an den Admin, weil der Schutz in der Oberfläche
greifen muss.
"""

import pytest
from django.forms import MultiWidget
from django.urls import reverse

from core.admin import VERWALTER


def _abschicken(client, konto, **aenderung):
    """Sendet das Änderungsformular eines Kontos mit den angezeigten Werten.

    Die Werte kommen aus dem gerenderten Formular, weil das Benutzerformular
    zweiteilige Datumsfelder, Gruppen und Rechte hat und eine kopierte
    Feldliste bei einem Django-Update veraltete.
    """
    adresse = reverse('admin:core_user_change', args=[konto.pk])
    formular = client.get(adresse).context['adminform'].form
    daten = {}
    for name, feld in formular.fields.items():
        if feld.disabled:
            continue
        wert = aenderung.get(name, formular[name].value())
        if isinstance(feld.widget, MultiWidget):
            for i, teil in enumerate(feld.widget.decompress(wert)):
                daten[f'{name}_{i}'] = '' if teil is None else str(teil)
        elif isinstance(wert, bool):
            if wert:
                daten[name] = 'on'
        elif isinstance(wert, (list, tuple)):
            daten[name] = [str(getattr(v, 'pk', v)) for v in wert]
        else:
            daten[name] = '' if wert is None else wert
    return client.post(adresse, {**daten, '_save': 'Sichern'})


def _fehlercodes(antwort):
    if antwort.status_code != 200 or 'adminform' not in (antwort.context or {}):
        return []
    fehler = antwort.context['adminform'].form.errors.as_data()
    return [f.code for f in fehler.get('__all__', [])]


@pytest.mark.django_db
class TestLetzterVerwalterImFormular:
    @pytest.mark.parametrize('haken', list(VERWALTER))
    def test_kann_sich_nicht_selbst_herabstufen(self, admin_client, admin_user, haken):
        antwort = _abschicken(admin_client, admin_user, **{haken: False})

        admin_user.refresh_from_db()
        assert _fehlercodes(antwort) == ['letzter_verwalter']
        assert getattr(admin_user, haken) is True

    def test_meldung_nennt_den_ausweg(self, admin_client, admin_user):
        antwort = _abschicken(admin_client, admin_user, is_superuser=False)

        assert 'Zuerst einem anderen Konto' in antwort.content.decode()

    def test_harmlose_aenderung_am_eigenen_konto_geht(self, admin_client, admin_user):
        """Abgelehnt wird nur der Übergang, andere Änderungen am Konto gehen."""
        antwort = _abschicken(admin_client, admin_user, first_name='Maria')

        admin_user.refresh_from_db()
        assert antwort.status_code == 302
        assert admin_user.first_name == 'Maria'

    def test_mit_zweitem_verwalter_geht_es(self, admin_client, admin_user,
                                           django_user_model):
        django_user_model.objects.create_superuser('zweiter', 'z@example.invalid', 'x')

        antwort = _abschicken(admin_client, admin_user, is_superuser=False)

        admin_user.refresh_from_db()
        assert antwort.status_code == 302
        assert admin_user.is_superuser is False

    def test_ein_deaktivierter_superuser_zaehlt_nicht(self, admin_client, admin_user,
                                                      django_user_model):
        """Ein inaktiver zweiter Superuser zählt nicht als Verwalter."""
        django_user_model.objects.create_superuser(
            'ausgeschieden', 'a@example.invalid', 'x', is_active=False)

        antwort = _abschicken(admin_client, admin_user, is_superuser=False)

        assert _fehlercodes(antwort) == ['letzter_verwalter']

    def test_wer_kein_verwalter_ist_bleibt_bearbeitbar(self, client, django_user_model):
        """Auch wenn es keinen Verwalter gibt.

        Abgelehnt wird nur der Übergang. Eine Prüfung des Zustands sperrte
        eine Installation ohne Verwalter (etwa nach Änderungen über die
        Kommandozeile) für jede Bearbeitung in der Oberfläche.
        """
        from django.contrib.auth.models import Permission

        buero = django_user_model.objects.create_user('buero', password='x', is_staff=True)
        buero.user_permissions.set(Permission.objects.filter(
            codename__in=['view_user', 'change_user']))
        kollege = django_user_model.objects.create_user('kollege', password='x')
        client.force_login(buero)

        antwort = _abschicken(client, kollege, first_name='Kurt')

        kollege.refresh_from_db()
        assert antwort.status_code == 302
        assert kollege.first_name == 'Kurt'


@pytest.mark.django_db
class TestLetzterVerwalterBeimLoeschen:
    def test_loeschseite_loescht_ihn_nicht(self, admin_client, admin_user,
                                           django_user_model):
        antwort = admin_client.post(
            reverse('admin:core_user_delete', args=[admin_user.pk]), {'post': 'yes'})

        assert antwort.status_code == 200
        assert django_user_model.objects.filter(pk=admin_user.pk).exists()
        assert 'Zuerst einem anderen Konto' in antwort.content.decode()

    def test_sammelaktion_loescht_ihn_nicht(self, admin_client, admin_user,
                                            django_user_model):
        """Auch nicht zusammen mit anderen Konten in der Sammelaktion."""
        kollege = django_user_model.objects.create_user('kollege', password='x')

        admin_client.post(reverse('admin:core_user_changelist'), {
            'action': 'delete_selected',
            '_selected_action': [str(admin_user.pk), str(kollege.pk)],
            'post': 'yes',
        })

        assert django_user_model.objects.filter(pk=admin_user.pk).exists()
        assert django_user_model.objects.filter(pk=kollege.pk).exists()

    def test_mit_zweitem_verwalter_geht_es(self, admin_client, admin_user,
                                           django_user_model):
        zweiter = django_user_model.objects.create_superuser(
            'zweiter', 'z@example.invalid', 'x')

        admin_client.post(
            reverse('admin:core_user_delete', args=[zweiter.pk]), {'post': 'yes'})

        assert not django_user_model.objects.filter(pk=zweiter.pk).exists()

    def test_beide_verwalter_auf_einmal_geht_nicht(self, admin_client, admin_user,
                                                   django_user_model):
        """Zwei Verwalter in derselben Auswahl: Danach gäbe es keinen mehr."""
        zweiter = django_user_model.objects.create_superuser(
            'zweiter', 'z@example.invalid', 'x')

        admin_client.post(reverse('admin:core_user_changelist'), {
            'action': 'delete_selected',
            '_selected_action': [str(admin_user.pk), str(zweiter.pk)],
            'post': 'yes',
        })

        assert django_user_model.objects.filter(pk__in=[admin_user.pk, zweiter.pk]).count() == 2
