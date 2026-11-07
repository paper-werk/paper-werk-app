"""Volle Belegauskunft und Kontakte über die Archiv-Anbindung hinaus.

Ergänzt ``faktura/tests/test_anbindung.py``, das die Zusagen der
Archiv-Anbindung prüft.
"""

import hashlib
from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.core.management import call_command
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core import gruppen
from faktura import services
from faktura.models import Beleg, BelegTyp, Kontakt

pytestmark = pytest.mark.django_db

XML = b'<rsm:CrossIndustryInvoice>abgelegt</rsm:CrossIndustryInvoice>'


@pytest.fixture
def n8n(django_user_model):
    """Dienstzugang in der Gruppe, die ``api_schluessel`` vergibt."""
    benutzer = django_user_model.objects.create(username='n8n', is_staff=False)
    benutzer.set_unusable_password()
    benutzer.save(update_fields=['password'])
    call_command('faktura_rechte', stdout=StringIO())
    benutzer.groups.add(Group.objects.get(name=gruppen.DIENST))
    zugang = APIClient()
    zugang.credentials(
        HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=benutzer).key}')
    return zugang


@pytest.fixture
def xrechnung(db):
    kunde = Kontakt.anlegen(nummer='K-1024', name='Bauherr Nord GmbH',
                            strasse='Hafenstraße 3', plz='20095', ort='Hamburg')
    beleg = services.beleg_anlegen(
        typ=BelegTyp.RECHNUNG, kunde=kunde, leistungsdatum=date(2026, 8, 1))
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Ausführung', menge=Decimal('1.000'),
        einheit='Pausch', einzelpreis=Decimal('2500.00'),
        steuersatz='19.00')
    rechnung = services.beleg_festschreiben(beleg_id=beleg.pk)
    rechnung.xml.save('probe.xml', ContentFile(XML), save=False)
    Beleg.objects.filter(pk=rechnung.pk).update(
        xml=rechnung.xml.name, xml_sha256=hashlib.sha256(XML).hexdigest(),
        erechnungsprofil='XRECHNUNG', paperless_id=4711)
    rechnung.refresh_from_db()
    return rechnung


@pytest.fixture
def verwaltung_api(verwaltung):
    client = APIClient()
    client.force_authenticate(get_user_model().objects.get(username='verwaltung'))
    return client


def _lieferant(name, **felder):
    return Kontakt.objects.create(name=name, ist_kunde=False,
                                  ist_lieferant=True, **felder)


def _namen(antwort) -> set[str]:
    daten = antwort.json()
    eintraege = daten['results'] if 'results' in daten else daten
    return {e['name'] for e in eintraege}


class TestVolleAuskunft:

    def test_die_belegauskunft_traegt_summen(self, n8n, xrechnung):
        """Summen stehen nur in der vollen Auskunft, nicht in der
        Archiv-Anbindung."""
        eintrag = n8n.get('/api/v1/belege/').json()['results'][0]

        assert eintrag['summen']['netto'] == '2500.00'

    def test_die_felder_der_anbindung_bleiben(self, n8n, xrechnung):
        """Was ``sub-duo-versand-paperwerk`` liest, trägt auch die volle."""
        eintrag = n8n.get('/api/v1/belege/', {'paperless_id': 4711}).json()['results'][0]

        assert eintrag['erechnungsprofil'] == 'XRECHNUNG'
        assert eintrag['xml_sha256'] == hashlib.sha256(XML).hexdigest()

    def test_das_verzeichnis_nennt_die_endpunkte(self, n8n):
        daten = n8n.get('/api/v1/').json()

        assert {'projekte', 'kunden', 'kontakte', 'projekt_aufloesen'} <= set(daten)


class TestKontakte:

    def test_kunden_bleibt_bei_den_kunden(self, verwaltung_api):
        """Bestehende n8n-Workflows bekommen keine Lieferanten untergeschoben."""
        Kontakt.objects.create(name='Wohnbau')
        _lieferant('Labor Nord')

        assert _namen(verwaltung_api.get('/api/v1/kunden/')) == {'Wohnbau'}

    def test_kontakte_liefert_alle_mit_rollen(self, verwaltung_api):
        Kontakt.objects.create(name='Wohnbau')
        _lieferant('Labor Nord', eigene_kundennummer='88-4711')

        alle = verwaltung_api.get('/api/v1/kontakte/')
        lieferanten = verwaltung_api.get('/api/v1/kontakte/', {'ist_lieferant': 'true'})

        assert _namen(alle) == {'Wohnbau', 'Labor Nord'}
        assert _namen(lieferanten) == {'Labor Nord'}
        eintrag = lieferanten.json()['results'][0]
        assert eintrag['rollen'] == ['Lieferant']
        assert eintrag['eigene_kundennummer'] == '88-4711'
