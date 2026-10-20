"""Rechte der Gruppen im Admin."""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from core import gruppen
from faktura import services
from faktura.models import (
    Beleg,
    BelegTyp,
    Katalogposition,
    Projekt,
    Textbaustein,
    TextbausteinVerwendung,
)
from faktura.tests.admin.hilfen import User


@pytest.mark.django_db
class TestArbeitsgruppeKannArbeiten:
    """Die Arbeitsgruppe darf alle eigenen Endpunkte verwenden.

    Regression: Die Gruppe war manuell mit Rechten auf zehn Modelle
    angelegt und wuchs bei neuen Modellen (Leistungskatalog, Textbausteine)
    nicht mit. Der Katalog-Endpunkt antwortete mit **403**, das Formular
    blieb leer, das Skript verschluckte den Fehler. Tests als Superuser
    (``buero``) erfassten das nicht.

    Der Test legt die Gruppe wie ``faktura_rechte`` an, fügt einen Benutzer
    ohne Superuser-Status hinzu und ruft jeden eigenen Endpunkt auf. Ein
    neues Modell mit Endpunkt, das in der Rechteliste fehlt, lässt ihn
    fehlschlagen.
    """

    @pytest.fixture
    def mitarbeiterin(self, client, db):
        """Benutzer der Arbeitsgruppe ohne Superuser-Status."""
        from django.contrib.auth.models import Group
        from django.core.management import call_command

        call_command('faktura_rechte', verbosity=0)

        benutzer = User.objects.create_user(
            username='buerokraft', email='b@example.com',
            password='geheim12345', is_staff=True,
        )
        benutzer.groups.add(Group.objects.get(name=gruppen.BUERO))
        client.login(username='buerokraft', password='geheim12345')
        return client

    def test_alle_eigenen_dienste_antworten(self, mitarbeiterin, kunde):
        """Alle Endpunkte, die das Belegformular aufruft, antworten der Gruppe;
        jeder prüft ein Recht, das die Gruppe haben muss."""
        katalog = Katalogposition.objects.create(
            bezeichnung='Montagestunde', einzelpreis=Decimal('95.00')
        )

        projekt = Projekt.objects.create(
            nummer='P-1', bezeichnung='Probe', kunde=kunde
        )

        # Ohne Textvorlagen, weil sie mit dem Formular geliefert werden.
        dienste = [
            (reverse('admin:faktura_katalogposition_daten'),
             {'katalog': katalog.pk}),
            (reverse('admin:faktura_angebot_kundendaten'),
             {'kunde': kunde.pk}),
            # Derselbe Endpunkt mit Projekt-Parameter und zusätzlicher
            # Prüfung des Rechts am Projekt.
            (reverse('admin:faktura_angebot_kundendaten'),
             {'projekt': projekt.pk}),
        ]

        verweigert = []
        for adresse, parameter in dienste:
            antwort = mitarbeiterin.get(adresse, parameter)
            if antwort.status_code != 200:
                verweigert.append(f'{adresse} -> {antwort.status_code}')

        assert not verweigert, 'verweigert: ' + '; '.join(verweigert)

    def test_das_belegformular_zeigt_ihr_alle_hilfen(self, mitarbeiterin,
                                                    bausteine):
        """Das Belegformular zeigt der Gruppe alle Buttons, für die sie Rechte
        hat."""
        inhalt = mitarbeiterin.get(
            reverse('admin:faktura_angebot_add')
        ).content.decode()

        assert 'data-ziel="id_kopftext"' in inhalt, 'keine Textvorlagen'
        assert 'data-katalog-url' in inhalt, 'kein Katalogfeld'
        assert 'data-stammdaten-url' in inhalt, 'kein Kundendienst'
        assert 'id="id_projekt"' in inhalt, 'kein Projektfeld'

    def test_sie_darf_einen_beleg_anlegen(self, mitarbeiterin, kunde):
        """Die Gruppe legt einen Beleg vollständig an."""
        mitarbeiterin.post(reverse('admin:faktura_angebot_add'), {
            'kunde': kunde.pk, 'betreff': 'Von der Bürokraft',
            'empfaenger': 'Muster GmbH', 'empfaenger_ust_id': '',
            'empfaenger_land': 'DE', 'zahlungsziel_tage': '14',
            'belegdatum': '', 'leistungsdatum': '', 'leistungsdatum_bis': '',
            'kopftext': '', 'fusstext': '',
            'positionen-TOTAL_FORMS': '0', 'positionen-INITIAL_FORMS': '0',
            'positionen-MIN_NUM_FORMS': '0', 'positionen-MAX_NUM_FORMS': '1000',
        }, follow=True)

        assert Beleg.objects.filter(betreff='Von der Bürokraft').exists()

    # --- Command ---

    def test_der_befehl_ist_wiederholbar(self, db):
        """``faktura_rechte`` ist idempotent."""
        from django.contrib.auth.models import Group
        from django.core.management import call_command

        call_command('faktura_rechte', verbosity=0)
        erster = set(Group.objects.get(name=gruppen.BUERO).permissions.all())

        call_command('faktura_rechte', verbosity=0)
        zweiter = set(Group.objects.get(name=gruppen.BUERO).permissions.all())

        assert erster == zweiter
        assert erster, 'die Gruppe blieb leer'

    def test_die_firma_bleibt_geschuetzt(self, db):
        """Die Firma: view und change, ohne add und delete, weil eine
        gelöschte Firma allen Belegen den Briefkopf nähme."""
        from django.contrib.auth.models import Group
        from django.core.management import call_command

        call_command('faktura_rechte', verbosity=0)
        rechte = {
            p.codename
            for p in Group.objects.get(name=gruppen.BUERO).permissions.all()
            if p.content_type.model == 'firma'
        }

        assert rechte == {'view_firma', 'change_firma'}

    def test_der_trockenlauf_aendert_nichts(self, db):
        from io import StringIO

        from django.contrib.auth.models import Group
        from django.core.management import call_command

        call_command('faktura_rechte', '--trocken', stdout=StringIO())

        # Die Gruppe existiert durch die Migration; ``--trocken`` setzt keine
        # Rechte.
        assert not Group.objects.get(name=gruppen.BUERO).permissions.exists()


class TestOhneRechteKeinBeleg:
    """Ohne Rechte in faktura kein Zugriff auf eigene URLs.

    Gegenstück zu ``TestArbeitsgruppeKannArbeiten``. Regression:
    ``ansicht_pdf`` und ``ansicht_html`` prüften kein Recht;
    ``admin_view()`` prüft nur ``is_active and is_staff``, sodass jeder
    Benutzer mit Admin-Zugang den vollständigen Beleg mit Kalkulation sah.
    Geprüft werden alle eigenen URLs.
    """

    @pytest.fixture
    def fremder(self, client, db):
        """Benutzer mit Admin-Zugang ohne Rechte in faktura.

        ``is_staff`` erlaubt nur die Anmeldung.
        """
        User.objects.create_user(
            username='ohne-faktura', email='o@example.com',
            password='geheim12345', is_staff=True,
        )
        client.login(username='ohne-faktura', password='geheim12345')
        return client

    @pytest.fixture
    def rechnung(self, firma, kunde):
        beleg = services.beleg_anlegen(
            typ=BelegTyp.RECHNUNG, kunde=kunde, leistungsdatum=date(2026, 8, 1))
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Kalkulation', menge=Decimal('1.000'),
            einheit='Stk', einzelpreis=Decimal('9999.00'),
            steuersatz='19.00')
        return services.beleg_festschreiben(beleg_id=beleg.pk)

    def test_kein_pdf(self, fremder, rechnung):
        """Kein Zugriff auf das PDF."""
        antwort = fremder.get(
            reverse('admin:faktura_rechnung_pdf', args=[rechnung.pk]))

        assert antwort.status_code == 403

    def test_keine_vorschau(self, fremder, rechnung):
        """Kein Zugriff auf die HTML-Vorschau mit demselben Inhalt."""
        antwort = fremder.get(
            reverse('admin:faktura_rechnung_vorschau', args=[rechnung.pk]))

        assert antwort.status_code == 403

    def test_keine_stammdaten(self, fremder, kunde):
        """Kein Zugriff auf den Stammdaten-Endpunkt."""
        antwort = fremder.get(
            reverse('admin:faktura_angebot_kundendaten'), {'kunde': kunde.pk})

        assert antwort.status_code != 200

    def test_keine_textbausteine(self, fremder, db):
        """Keine Textbausteine, weil sie nur mit dem Belegformular geliefert
        werden, auf das kein Zugriff besteht."""
        Textbaustein.objects.create(
            name='Grußformel',
            verwendung=TextbausteinVerwendung.BELEGTEXT,
            text='Über Ihren Auftrag würden wir uns freuen.',
        )

        antwort = fremder.get(reverse('admin:faktura_angebot_add'))

        assert antwort.status_code != 200

    def test_kein_leistungskatalog(self, fremder, db):
        katalog = Katalogposition.objects.create(
            bezeichnung='Montagestunde', einzelpreis=Decimal('95.00'))

        antwort = fremder.get(
            reverse('admin:faktura_katalogposition_daten'),
            {'katalog': katalog.pk})

        assert antwort.status_code != 200

    def test_wer_rechnungen_sehen_darf_bekommt_sie(self, client, db, firma, kunde):
        """Gegenprobe: Mit View-Recht an Rechnungen ist der Zugriff möglich."""
        from django.contrib.auth.models import Permission

        benutzer = User.objects.create_user(
            username='darf-lesen', email='d@example.com',
            password='geheim12345', is_staff=True)
        benutzer.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='faktura',
            codename__in=['view_rechnung', 'view_beleg']))
        client.login(username='darf-lesen', password='geheim12345')

        beleg = services.beleg_anlegen(
            typ=BelegTyp.RECHNUNG, kunde=kunde, leistungsdatum=date(2026, 8, 1))
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='P', menge=Decimal('1.000'),
            einheit='Stk', einzelpreis=Decimal('10.00'),
            steuersatz='19.00')
        services.beleg_festschreiben(beleg_id=beleg.pk)

        antwort = client.get(
            reverse('admin:faktura_rechnung_vorschau', args=[beleg.pk]))

        assert antwort.status_code == 200


# --------------------------------------------------------------------------
# Cookies und Dokumentspalte
# --------------------------------------------------------------------------


@pytest.mark.django_db
class TestEigeneCookienamen:
    """Eigene Cookie-Namen, verschieden von Paperless.

    Cookies unterscheiden nicht nach Port (RFC 6265, Abschnitt 8.5). Im
    Stack laufen paper-werk und Paperless-ngx auf demselben Host. Mit den
    Default-Namen antwortet Paperless mit ``sessionid=""; Max-Age=0`` und
    beendet die Session hier, auch ohne Anmeldung dort.

    Geprüft wird das Cookie der Response, nicht der Wert der Setting.
    """

    #: Default-Namen von Django, die auch Paperless verwendet.
    VORGABEN = {'sessionid', 'csrftoken'}

    def test_die_anmeldung_setzt_ein_eigenes_sitzungscookie(self, buero):
        antwort = buero.get(reverse('admin:index'))

        gesetzt = set(antwort.client.cookies.keys())
        assert 'paperwerk_sessionid' in gesetzt or 'paperwerk_sessionid' in buero.cookies
        assert not (self.VORGABEN & set(buero.cookies.keys())), (
            f'Vorgabenamen in Benutzung: {set(buero.cookies.keys())}')

    def test_das_csrf_cookie_traegt_einen_eigenen_namen(self, settings):
        assert settings.CSRF_COOKIE_NAME == 'paperwerk_csrftoken'
        assert settings.CSRF_COOKIE_NAME not in self.VORGABEN

    def test_die_namen_stehen_gemeinsam_fest(self, settings):
        """Session- und CSRF-Cookie sind beide umbenannt.

        Mit nur umbenanntem Session-Cookie bliebe die Anmeldung erhalten,
        das Speichern im Admin schlüge aber nach einem Besuch im Archiv
        sporadisch mit "CSRF verification failed" fehl.
        """
        assert settings.SESSION_COOKIE_NAME not in self.VORGABEN
        assert settings.CSRF_COOKIE_NAME not in self.VORGABEN
