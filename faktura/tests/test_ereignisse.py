"""Ereignisse an Belegen und der Rückweg über die API (``docs/webhooks.md``).

Die Empfänger laufen per ``transaction.on_commit``; die Tests führen die
Callbacks mit ``django_capture_on_commit_callbacks(execute=True)`` aus.
Aufgezeichnet wird mit einem Ersatzempfänger, der Versand per HTTP steht
in ``core/tests/test_ereignisse.py``.
"""

from decimal import Decimal
from io import StringIO

import pytest
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.db import transaction
from django.test import Client
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core import erweiterungen, gruppen
from core.optimistic_locking import FELD
from faktura import ereignisse, services
from faktura.models import Beleg, BelegTyp, Kontakt, Projekt
from faktura.tests.test_gleichzeitig import formulardaten, gesichert, neue_position, setze

pytestmark = pytest.mark.django_db


@pytest.fixture
def gemeldet(monkeypatch):
    """Liste der Ereignisse als ``(aktion, beleg_id)``, statt des Versands."""
    liste = []
    monkeypatch.setattr(erweiterungen, '_EREIGNISEMPFAENGER',
                        [lambda quelle, aktion, beleg: liste.append((aktion, beleg.pk))])
    return liste


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-1000', name='Muster GmbH', strasse='Hauptstraße 1',
        plz='10115', ort='Berlin', email='buchhaltung@muster.example',
    )


def _entwurf(kunde, typ=BelegTyp.RECHNUNG):
    beleg = services.beleg_anlegen(
        kunde=kunde, typ=typ, betreff='Leistungen',
        leistungsdatum=timezone.localdate())
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Beratung', menge=Decimal('10'),
        einzelpreis=Decimal('100.00'), steuersatz='19.00')
    return beleg


@pytest.fixture
def entwurf(kunde):
    return _entwurf(kunde)


class TestMeldestellen:

    def test_anlegen(self, kunde, gemeldet, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)

        assert gemeldet == [(ereignisse.ANGELEGT, beleg.pk)]

    def test_umwandeln_meldet_den_neuen_auftrag(
            self, kunde, gemeldet, django_capture_on_commit_callbacks):
        angebot = services.beleg_festschreiben(
            beleg_id=_entwurf(kunde, BelegTyp.ANGEBOT).pk)
        gemeldet.clear()

        with django_capture_on_commit_callbacks(execute=True):
            auftrag = services.beleg_umwandeln(beleg_id=angebot.pk,
                                               neuer_typ=BelegTyp.AUFTRAG)

        assert (ereignisse.ANGELEGT, auftrag.pk) in gemeldet
        nutzlast = ereignisse.nutzlast(auftrag)
        assert nutzlast['typ'] == BelegTyp.AUFTRAG
        assert nutzlast['vorgaenger'] == {'id': angebot.pk, 'typ': 'angebot',
                                          'nummer': angebot.nummer}

    def test_festschreiben(self, entwurf, gemeldet, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            services.beleg_festschreiben(beleg_id=entwurf.pk)

        assert gemeldet == [(ereignisse.FESTGESCHRIEBEN, entwurf.pk)]

    def test_versenden_eines_entwurfs(self, entwurf, gemeldet,
                                      django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            services.beleg_versenden(beleg_id=entwurf.pk)

        assert gemeldet == [(ereignisse.FESTGESCHRIEBEN, entwurf.pk),
                            (ereignisse.VERSENDET, entwurf.pk)]

    def test_wiedereroeffnen(self, kunde, gemeldet, django_capture_on_commit_callbacks):
        angebot = services.beleg_festschreiben(
            beleg_id=_entwurf(kunde, BelegTyp.ANGEBOT).pk)
        gemeldet.clear()

        with django_capture_on_commit_callbacks(execute=True):
            services.beleg_wiedereroeffnen(beleg_id=angebot.pk)

        assert gemeldet == [(ereignisse.WIEDEREROEFFNET, angebot.pk)]

    def test_rollback_meldet_nichts(self, kunde, gemeldet,
                                    django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            with pytest.raises(RuntimeError), transaction.atomic():
                services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
                raise RuntimeError

        assert gemeldet == []


class TestMaske:
    """``geaendert`` kommt aus dem Admin, einmal je Speichervorgang."""

    @pytest.fixture
    def maske(self, konto):
        client = Client()
        client.force_login(konto(gruppen.BUERO, 'bea'))
        return client

    @staticmethod
    def _adresse(beleg):
        from django.urls import reverse
        return reverse('admin:faktura_rechnung_change', args=[beleg.pk])

    def test_ein_ereignis_fuer_kopf_und_positionen(
            self, maske, entwurf, gemeldet, django_capture_on_commit_callbacks):
        daten = formulardaten(maske.get(self._adresse(entwurf)))
        setze(daten, 'betreff', 'Neuer Betreff')
        neue_position(daten, 'Planung', '20')
        neue_position(daten, 'Bauleitung', '30')

        with django_capture_on_commit_callbacks(execute=True):
            assert gesichert(maske.post(self._adresse(entwurf), daten))

        assert gemeldet == [(ereignisse.GEAENDERT, entwurf.pk)]

    def test_ohne_aenderung_kein_ereignis(
            self, maske, entwurf, gemeldet, django_capture_on_commit_callbacks):
        daten = formulardaten(maske.get(self._adresse(entwurf)))

        with django_capture_on_commit_callbacks(execute=True):
            assert gesichert(maske.post(self._adresse(entwurf), daten))

        assert gemeldet == []


class TestNutzlast:

    def test_eigenschaften_der_festgeschriebenen_rechnung(self, entwurf, settings):
        settings.PAPER_WERK_URL = 'https://pw.example'
        rechnung = services.beleg_festschreiben(beleg_id=entwurf.pk)

        nutzlast = ereignisse.nutzlast(rechnung)

        assert nutzlast['id'] == rechnung.pk
        assert nutzlast['typ'] == 'rechnung'
        assert nutzlast['nummer'] == rechnung.nummer
        assert nutzlast['betreff'] == 'Leistungen'
        assert nutzlast['brutto'] == '1190.00'
        assert nutzlast['faellig_am'] == rechnung.faellig_am
        assert nutzlast['kunde'] == {'name': 'Muster GmbH'}
        assert nutzlast['vorgaenger'] is None
        assert nutzlast['projekt'] is None
        assert nutzlast[FELD] == Beleg.objects.values_list(FELD, flat=True).get(
            pk=rechnung.pk)
        assert nutzlast['admin_url'] == (
            f'https://pw.example/admin/faktura/rechnung/{rechnung.pk}/change/')
        assert nutzlast['api_url'] == f'https://pw.example/api/v1/belege/{rechnung.pk}/'

    def test_entwurf_ohne_nummer(self, entwurf):
        assert ereignisse.nutzlast(entwurf)['nummer'] is None


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@pytest.fixture
def n8n(django_user_model):
    """Dienstzugang mit den Rechten von "Faktura Dienst"."""
    call_command('faktura_rechte', stdout=StringIO())
    benutzer = django_user_model.objects.create(username='n8n')
    benutzer.groups.add(Group.objects.get(name=gruppen.DIENST))
    zugang = APIClient()
    zugang.credentials(
        HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=benutzer).key}')
    return zugang


def _version(beleg) -> int:
    return Beleg.objects.values_list(FELD, flat=True).get(pk=beleg.pk)


class TestKopfaendern:

    def test_aendert_den_betreff_ohne_ereignis(
            self, n8n, entwurf, gemeldet, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            antwort = n8n.patch(f'/api/v1/belege/{entwurf.pk}/',
                                {'betreff': 'Bestellung 4711', FELD: _version(entwurf)},
                                format='json')

        assert antwort.status_code == 200, antwort.content
        assert antwort.json()['betreff'] == 'Bestellung 4711'
        assert Beleg.objects.get(pk=entwurf.pk).betreff == 'Bestellung 4711'
        assert gemeldet == []

    def test_veraltete_version(self, n8n, entwurf):
        antwort = n8n.patch(f'/api/v1/belege/{entwurf.pk}/',
                            {'betreff': 'x', FELD: _version(entwurf) - 1},
                            format='json')

        assert antwort.status_code == 409
        assert Beleg.objects.get(pk=entwurf.pk).betreff == 'Leistungen'

    def test_ohne_version(self, n8n, entwurf):
        antwort = n8n.patch(f'/api/v1/belege/{entwurf.pk}/', {'betreff': 'x'},
                            format='json')

        assert antwort.status_code == 400

    def test_andere_felder_werden_abgewiesen(self, n8n, entwurf):
        antwort = n8n.patch(f'/api/v1/belege/{entwurf.pk}/',
                            {'zahlungsziel_tage': 60, FELD: _version(entwurf)},
                            format='json')

        assert antwort.status_code == 400
        assert 'zahlungsziel_tage' in antwort.json()
        assert Beleg.objects.get(pk=entwurf.pk).zahlungsziel_tage != 60

    def test_festgeschrieben(self, n8n, entwurf):
        rechnung = services.beleg_festschreiben(beleg_id=entwurf.pk)

        antwort = n8n.patch(f'/api/v1/belege/{rechnung.pk}/',
                            {'betreff': 'x', FELD: _version(rechnung)},
                            format='json')

        assert antwort.status_code == 409

    def test_ohne_recht(self, entwurf, django_user_model):
        benutzer = django_user_model.objects.create(username='leser')
        zugang = APIClient()
        zugang.force_authenticate(benutzer)

        antwort = zugang.patch(f'/api/v1/belege/{entwurf.pk}/',
                               {'betreff': 'x', FELD: _version(entwurf)},
                               format='json')

        assert antwort.status_code == 403

    def test_kein_put(self, entwurf, django_user_model):
        """Als Superuser, weil die Rechteprüfung vor der Methode greift."""
        zugang = APIClient()
        zugang.force_authenticate(django_user_model.objects.create_superuser(
            'chefin', 'chefin@example.invalid', 'x'))

        antwort = zugang.put(f'/api/v1/belege/{entwurf.pk}/', {'betreff': 'x'},
                             format='json')

        assert antwort.status_code == 405


class TestLesen:

    def test_eigenschaften(self, n8n, entwurf):
        daten = n8n.get(f'/api/v1/belege/{entwurf.pk}/').json()

        assert daten['betreff'] == 'Leistungen'
        assert daten['kunde_name'] == 'Muster GmbH'
        assert daten['brutto'] == '1190.00'
        assert daten['vorgaenger_id'] is None
        assert daten[FELD] == _version(entwurf)

    def test_kopffelder_sind_lesbar(self, n8n, entwurf):
        Beleg.objects.filter(pk=entwurf.pk).update(bestellnummer='B-77')

        daten = n8n.get(f'/api/v1/belege/{entwurf.pk}/').json()

        assert daten['bestellnummer'] == 'B-77'
        assert {'kopftext', 'fusstext', 'leitweg_id', 'empfaenger_email'} <= set(daten)

    def test_projektstand_nur_in_der_einzelauskunft(self, n8n, kunde):
        projekt = Projekt.objects.create(nummer='2026-099',
                                         bezeichnung='Halle Nord', kunde=kunde)
        auftrag = _entwurf(kunde, BelegTyp.AUFTRAG)
        Beleg.objects.filter(pk=auftrag.pk).update(projekt=projekt, kunde=None)
        services.beleg_festschreiben(beleg_id=auftrag.pk)
        rechnung = _entwurf(kunde)
        Beleg.objects.filter(pk=rechnung.pk).update(projekt=projekt, kunde=None)

        einzeln = n8n.get(f'/api/v1/belege/{rechnung.pk}/').json()
        liste = n8n.get('/api/v1/belege/').json()['results']

        assert einzeln['projekt_id'] == projekt.pk
        assert einzeln['projektstand']['beauftragt'] == '1000.00'
        assert einzeln['projektstand']['fakturiert'] == '0.00'
        assert einzeln['projektstand']['fortschritt'] == 0
        assert all(b['projektstand'] is None for b in liste)

    def test_nutzlast_nennt_projekt_und_dessen_kunden(self, kunde):
        projekt = Projekt.objects.create(nummer='2026-099',
                                         bezeichnung='Halle Nord', kunde=kunde)
        rechnung = _entwurf(kunde)
        Beleg.objects.filter(pk=rechnung.pk).update(projekt=projekt, kunde=None)

        nutzlast = ereignisse.nutzlast(rechnung)

        assert nutzlast['projekt'] == {'id': projekt.pk, 'nummer': '2026-099',
                                       'bezeichnung': 'Halle Nord'}
        assert nutzlast['kunde'] == {'name': 'Muster GmbH'}

    def test_nachfolger_ueber_den_vorgaenger(self, n8n, kunde):
        angebot = services.beleg_festschreiben(
            beleg_id=_entwurf(kunde, BelegTyp.ANGEBOT).pk)
        auftrag = services.beleg_umwandeln(beleg_id=angebot.pk,
                                           neuer_typ=BelegTyp.AUFTRAG)
        _entwurf(kunde, BelegTyp.ANGEBOT)

        daten = n8n.get(f'/api/v1/belege/?vorgaenger={angebot.pk}').json()

        assert [b['id'] for b in daten['results']] == [auftrag.pk]

    def test_pdf(self, n8n, entwurf):
        rechnung = services.beleg_festschreiben(beleg_id=entwurf.pk)
        rechnung.pdf.save('probe.pdf', ContentFile(b'%PDF-probe'), save=False)
        Beleg.objects.filter(pk=rechnung.pk).update(pdf=rechnung.pdf.name)

        antwort = n8n.get(f'/api/v1/belege/{rechnung.pk}/pdf/')

        assert antwort.status_code == 200
        assert b''.join(antwort.streaming_content) == b'%PDF-probe'

    def test_entwurf_hat_kein_pdf(self, n8n, entwurf):
        assert n8n.get(f'/api/v1/belege/{entwurf.pk}/pdf/').status_code == 404
