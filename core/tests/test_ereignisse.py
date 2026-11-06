"""Ereignisse und ihr Versand an Ereignisregeln (``docs/webhooks.md``).

``requests.post`` wird ersetzt; die Hintergrund-Threads laufen über einen
Ersatz für ``threading.Thread`` synchron, damit die Tests das Ergebnis
sehen.
"""

import json
import logging
from decimal import Decimal

import pytest
import requests
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from core import erweiterungen, webhooks
from core.models import Ereignisregel
from faktura import services
from faktura.models import BelegTyp, Kontakt


class _SofortThread:
    """Ersatz für ``threading.Thread``: ``start`` ruft das Ziel direkt auf."""

    def __init__(self, target, args=(), **kwargs):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


class _Antwort:
    def __init__(self, status_code):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300


@pytest.fixture
def aufrufe(monkeypatch):
    """Aufrufe von ``requests.post`` als ``(url, kwargs)``; Antwort 204."""
    liste = []

    def post(url, **kwargs):
        liste.append((url, kwargs))
        return _Antwort(204)

    monkeypatch.setattr(webhooks.requests, 'post', post)
    monkeypatch.setattr(webhooks.threading, 'Thread', _SofortThread)
    return liste


@pytest.fixture
def rechnung(db):
    kunde = Kontakt.anlegen(nummer='K-1', name='Muster GmbH', strasse='Weg 1',
                            plz='10115', ort='Berlin')
    beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG,
                                   leistungsdatum=timezone.localdate())
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Beratung', menge=Decimal('1'),
        einzelpreis=Decimal('100.00'), steuersatz='19.00')
    return beleg


def _regel(**felder) -> Ereignisregel:
    werte = {'name': 'n8n', 'url': 'http://n8n:5678/webhook/beleg'} | felder
    return Ereignisregel.objects.create(**werte)


class TestRegel:

    @pytest.mark.parametrize(('aktionen', 'typen', 'erwartet'), [
        ([], [], True),
        (['festgeschrieben'], [], True),
        (['versendet'], [], False),
        ([], ['rechnung'], True),
        ([], ['angebot'], False),
        (['festgeschrieben'], ['angebot', 'rechnung'], True),
    ])
    def test_filter(self, aktionen, typen, erwartet):
        regel = Ereignisregel(aktionen=aktionen, typen=typen)

        assert regel.trifft_zu('festgeschrieben', 'rechnung') is erwartet

    @pytest.mark.parametrize(('url', 'erlaubt'), [
        ('https://n8n.example/webhook/x', True),
        ('http://n8n:5678/webhook/x', True),
        ('http://localhost:5678/webhook/x', True),
        ('http://n8n.example/webhook/x', False),
    ])
    def test_http_nur_im_internen_netz(self, url, erlaubt, settings):
        settings.DEBUG = False
        regel = Ereignisregel(name='x', url=url)

        if erlaubt:
            regel.full_clean()
        else:
            with pytest.raises(ValidationError):
                regel.full_clean()

    def test_token_wird_erzeugt(self, db):
        assert len(_regel().token) >= 40


@pytest.mark.django_db
class TestVersand:

    def test_post_an_die_zutreffende_regel(self, rechnung, aufrufe):
        regel = _regel(aktionen=['festgeschrieben'], typen=['rechnung'])
        _regel(name='andere', aktionen=['versendet'])
        _regel(name='aus', aktiv=False)

        webhooks.versenden('beleg', 'festgeschrieben', rechnung)

        assert len(aufrufe) == 1
        url, kwargs = aufrufe[0]
        assert url == regel.url
        assert kwargs['headers']['X-PaperWerk-Token'] == regel.token
        assert kwargs['headers']['X-PaperWerk-Ereignis'] == 'beleg.festgeschrieben'
        assert kwargs['timeout'] == webhooks.ZEITLIMIT
        rumpf = json.loads(kwargs['data'])
        assert rumpf['ereignis'] == 'beleg'
        assert rumpf['aktion'] == 'festgeschrieben'
        assert rumpf['beleg']['id'] == rechnung.pk

    def test_ohne_regel_kein_aufruf(self, rechnung, aufrufe):
        webhooks.versenden('beleg', 'festgeschrieben', rechnung)

        assert aufrufe == []

    def test_fehler_landet_im_log(self, rechnung, monkeypatch, caplog):
        def post(url, **kwargs):
            raise requests.ConnectionError('verweigert')

        monkeypatch.setattr(webhooks.requests, 'post', post)
        monkeypatch.setattr(webhooks.threading, 'Thread', _SofortThread)
        _regel()

        with caplog.at_level(logging.WARNING, logger='core.webhooks'):
            webhooks.versenden('beleg', 'festgeschrieben', rechnung)

        assert 'nicht erreicht' in caplog.text

    def test_fehlerstatus_landet_im_log(self, rechnung, monkeypatch, caplog):
        monkeypatch.setattr(webhooks.requests, 'post',
                            lambda url, **kwargs: _Antwort(500))
        monkeypatch.setattr(webhooks.threading, 'Thread', _SofortThread)
        _regel()

        with caplog.at_level(logging.WARNING, logger='core.webhooks'):
            webhooks.versenden('beleg', 'festgeschrieben', rechnung)

        assert 'Status 500' in caplog.text

    def test_festschreiben_trotz_unerreichbarem_ziel(
            self, rechnung, monkeypatch, django_capture_on_commit_callbacks):
        def post(url, **kwargs):
            raise requests.Timeout

        monkeypatch.setattr(webhooks.requests, 'post', post)
        monkeypatch.setattr(webhooks.threading, 'Thread', _SofortThread)
        _regel()

        with django_capture_on_commit_callbacks(execute=True):
            beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)

        assert beleg.nummer


class TestVerteilen:

    def test_ohne_empfaenger_wird_nichts_registriert(
            self, monkeypatch, django_capture_on_commit_callbacks, db):
        monkeypatch.setattr(erweiterungen, '_EREIGNISEMPFAENGER', [])

        with django_capture_on_commit_callbacks() as callbacks:
            erweiterungen.ereignis('beleg', 'angelegt', object())

        assert callbacks == []

    def test_ausnahme_eines_empfaengers_bleibt_dort(
            self, monkeypatch, django_capture_on_commit_callbacks, db, caplog):
        erhalten = []

        def kaputt(quelle, aktion, objekt):
            raise RuntimeError('kaputt')

        monkeypatch.setattr(erweiterungen, '_EREIGNISEMPFAENGER',
                            [kaputt, lambda *a: erhalten.append(a)])

        with django_capture_on_commit_callbacks(execute=True):
            erweiterungen.ereignis('beleg', 'angelegt', 'objekt')

        assert erhalten == [('beleg', 'angelegt', 'objekt')]
        assert 'fehlgeschlagen' in caplog.text


@pytest.mark.django_db
class TestMaske:

    def test_liste_und_formular(self, verwaltung):
        regel = _regel(aktionen=['festgeschrieben'], typen=['rechnung'])

        liste = verwaltung.get(reverse('admin:core_ereignisregel_changelist'))
        formular = verwaltung.get(
            reverse('admin:core_ereignisregel_change', args=[regel.pk]))

        assert liste.status_code == 200
        assert 'Rechnung: Festgeschrieben' in liste.content.decode()
        assert formular.status_code == 200

    def test_anlegen(self, verwaltung):
        antwort = verwaltung.post(reverse('admin:core_ereignisregel_add'), {
            'name': 'Kalender', 'aktiv': 'on', 'quelle': 'beleg',
            'aktionen': ['festgeschrieben', 'wiedereroeffnet'],
            'typen': ['rechnung'], 'url': 'https://n8n.example/webhook/kalender',
            'token': 'geheim',
        })

        assert antwort.status_code == 302
        regel = Ereignisregel.objects.get(name='Kalender')
        assert regel.aktionen == ['festgeschrieben', 'wiedereroeffnet']
        assert regel.typen == ['rechnung']

    def test_unbekannte_aktion_wird_abgewiesen(self, verwaltung):
        antwort = verwaltung.post(reverse('admin:core_ereignisregel_add'), {
            'name': 'x', 'quelle': 'beleg', 'aktionen': ['gibtsnicht'],
            'url': 'https://n8n.example/x', 'token': 't',
        })

        assert antwort.status_code == 200
        assert not Ereignisregel.objects.exists()

    def test_test_senden_zeigt_den_status(self, verwaltung, rechnung, aufrufe):
        regel = _regel()

        antwort = verwaltung.get(
            reverse('admin:core_ereignisregel_detail_test_senden', args=[regel.pk]),
            follow=True)

        assert 'antwortet mit Status 204' in antwort.content.decode()
        rumpf = json.loads(aufrufe[0][1]['data'])
        assert rumpf['aktion'] == webhooks.TESTAKTION
        assert rumpf['test'] is True
        # Erfundener Beleg, nie der jüngste echte.
        assert rumpf['beleg']['id'] == 0
        assert rumpf['beleg']['nummer'] == 'TEST-0001'

    def test_test_senden_nimmt_den_typ_der_regel(self, verwaltung, aufrufe):
        regel = _regel(typen=['angebot', 'auftrag'])

        verwaltung.get(
            reverse('admin:core_ereignisregel_detail_test_senden', args=[regel.pk]))

        assert json.loads(aufrufe[0][1]['data'])['beleg']['typ'] == 'angebot'

    def test_test_senden_ohne_testnutzlast(self, verwaltung, aufrufe, monkeypatch):
        quellen = dict(erweiterungen._EREIGNISQUELLEN)
        quellen['lager'] = erweiterungen.Ereignisquelle(
            name='lager', titel='Lager', aktionen=[], typen=[],
            typ=lambda o: '', nutzlast=lambda o: {})
        monkeypatch.setattr(erweiterungen, '_EREIGNISQUELLEN', quellen)
        regel = _regel(quelle='lager')

        antwort = verwaltung.get(
            reverse('admin:core_ereignisregel_detail_test_senden', args=[regel.pk]),
            follow=True)

        assert 'nicht umgesetzt' in antwort.content.decode()
        assert aufrufe == []

    def test_test_senden_zeigt_den_fehler(self, verwaltung, monkeypatch):
        def post(url, **kwargs):
            raise requests.ConnectionError('verweigert')

        monkeypatch.setattr(webhooks.requests, 'post', post)
        regel = _regel()

        antwort = verwaltung.get(
            reverse('admin:core_ereignisregel_detail_test_senden', args=[regel.pk]),
            follow=True)

        assert 'nicht erreicht' in antwort.content.decode()
