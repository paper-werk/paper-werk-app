"""Zusagen der Archiv-Anbindung.

Der n8n-Workflow ``sub-duo-versand-paperwerk`` sucht zu einem Dokument im
Archiv den Beleg (``?paperless_id=``), liest ``erechnungsprofil`` und ruft
bei einer XRechnung das gespeicherte XML ab. Das gilt im Kern und bleibt
erhalten, wenn ein Zusatz den Endpunkt unter derselben URL ersetzt
(``core.erweiterungen.api_endpoint(ersetzt=True)``). Geprüft wird daher die
URL, nicht eine bestimmte Klasse.
"""

import hashlib
from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.apps import apps
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


def _mit_schluessel(benutzer) -> APIClient:
    zugang = APIClient()
    zugang.credentials(
        HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=benutzer).key}')
    return zugang


@pytest.fixture
def dienst(django_user_model):
    """Dienstzugang ohne Rechte."""
    benutzer = django_user_model.objects.create(username='n8n', is_staff=False)
    benutzer.set_unusable_password()
    benutzer.save(update_fields=['password'])
    return benutzer


@pytest.fixture
def n8n(dienst):
    """Derselbe Zugang in der Gruppe von ``api_schluessel``, mit den Rechten
    aus ``faktura_rechte``."""
    call_command('faktura_rechte', stdout=StringIO())
    dienst.groups.add(Group.objects.get(name=gruppen.DIENST))
    return _mit_schluessel(dienst)


@pytest.fixture
def rechnung(db):
    kunde = Kontakt.anlegen(nummer='K-1024', name='Bauherr Nord GmbH',
                            strasse='Hafenstraße 3', plz='20095', ort='Hamburg')
    beleg = services.beleg_anlegen(
        typ=BelegTyp.RECHNUNG, kunde=kunde, leistungsdatum=date(2026, 8, 1))
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Ausführung', menge=Decimal('1.000'),
        einheit='Pausch', einzelpreis=Decimal('2500.00'),
        steuersatz='19.00')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


@pytest.fixture
def xrechnung(rechnung):
    """Rechnung als XRechnung mit gespeichertem XML, archiviert.

    Der Inhalt weicht bewusst von der Ausgabe von ``facturx`` ab, damit der
    Test nachweist, dass die **gespeicherte** Datei ausgeliefert wird.
    """
    rechnung.xml.save('probe.xml', ContentFile(XML), save=False)
    Beleg.objects.filter(pk=rechnung.pk).update(
        xml=rechnung.xml.name, xml_sha256=hashlib.sha256(XML).hexdigest(),
        erechnungsprofil='XRECHNUNG', paperless_id=4711)
    rechnung.refresh_from_db()
    return rechnung


class TestZugang:

    def test_ohne_schluessel_nichts(self, xrechnung):
        assert APIClient().get('/api/v1/belege/').status_code == 401

    def test_ohne_leserecht_nichts(self, dienst, xrechnung):
        assert _mit_schluessel(dienst).get('/api/v1/belege/').status_code == 403

    def test_die_dienstgruppe_liest(self, n8n, xrechnung):
        assert n8n.get('/api/v1/belege/').status_code == 200

    def test_anlegen_bleibt_verschlossen(self, n8n):
        antwort = n8n.post('/api/v1/belege/', {'typ': 'rechnung'}, format='json')

        assert antwort.status_code in (403, 405)
        assert not Beleg.objects.exists()


class TestVomArchivdokumentZumXml:
    """Die Schritte des n8n-Workflows."""

    def test_die_dokument_id_findet_den_beleg(self, n8n, xrechnung):
        treffer = n8n.get('/api/v1/belege/', {'paperless_id': 4711}).json()['results']
        daneben = n8n.get('/api/v1/belege/', {'paperless_id': 4712}).json()['results']

        assert [b['id'] for b in treffer] == [xrechnung.pk]
        assert daneben == []

    def test_die_liste_traegt_was_die_strecke_liest(self, n8n, xrechnung):
        """Die Liste enthält die Felder, die jede Implementierung des Endpunkts
        liefern muss."""
        eintrag = n8n.get('/api/v1/belege/', {'paperless_id': 4711}).json()['results'][0]

        assert eintrag['erechnungsprofil'] == 'XRECHNUNG'
        assert eintrag['xml_sha256'] == hashlib.sha256(XML).hexdigest()
        assert eintrag['nummer'] == xrechnung.nummer
        assert eintrag['typ_kennung'] == 'rechnung'
        assert eintrag['archiviert'] is True

    def test_das_xml_ist_die_abgelegte_datei(self, n8n, xrechnung):
        antwort = n8n.get(f'/api/v1/belege/{xrechnung.pk}/xml/')

        assert antwort.status_code == 200
        assert antwort['Content-Type'] == 'application/xml'
        assert b''.join(antwort.streaming_content) == XML

    def test_nach_profil_und_xml_filtern(self, n8n, xrechnung):
        assert n8n.get('/api/v1/belege/', {'erechnungsprofil': 'xrechnung'}).json()['count'] == 1
        assert n8n.get('/api/v1/belege/', {'erechnungsprofil': 'EN 16931'}).json()['count'] == 0
        assert n8n.get('/api/v1/belege/', {'mit_xml': 'true'}).json()['count'] == 1
        assert n8n.get('/api/v1/belege/', {'mit_xml': 'false'}).json()['count'] == 0

    def test_ohne_abgelegtes_xml_kein_neues(self, n8n, rechnung):
        """Ohne gespeichertes XML keine Neuerzeugung, weil sie die aktuellen
        Stammdaten enthielte."""
        assert n8n.get(f'/api/v1/belege/{rechnung.pk}/xml/').status_code == 404

    def test_zum_angebot_gibt_es_keines(self, n8n, rechnung):
        angebot = services.beleg_anlegen(typ=BelegTyp.ANGEBOT, kunde=rechnung.kunde)

        assert n8n.get(f'/api/v1/belege/{angebot.pk}/xml/').status_code == 404


class TestInhaltsverzeichnis:

    def test_nennt_die_anbindung(self, n8n):
        daten = n8n.get('/api/v1/').json()

        assert daten['belege'].endswith('/api/v1/belege/')
        assert daten['eingangsrechnungen'].endswith('/api/v1/eingangsrechnungen/')


@pytest.mark.skipif(apps.is_installed('api'),
                    reason='Der Zusatz api ersetzt die Belegauskunft.')
class TestNurKern:
    """Funktionen, die der Kern bewusst nicht bietet."""

    def test_kein_pdf(self, n8n, xrechnung):
        assert n8n.get(f'/api/v1/belege/{xrechnung.pk}/pdf/').status_code == 404

    def test_kein_festschreiben_und_kein_archivvermerk(self, n8n, xrechnung):
        assert n8n.post(f'/api/v1/belege/{xrechnung.pk}/festschreiben/').status_code == 404
        assert n8n.post(f'/api/v1/belege/{xrechnung.pk}/archiviert/',
                        {'paperless_document_id': 1}, format='json').status_code == 404

    def test_keine_projekte_kunden_kontakte(self, n8n):
        daten = n8n.get('/api/v1/').json()

        assert not {'projekte', 'kunden', 'kontakte', 'projekt_aufloesen'} & set(daten)
        assert n8n.get('/api/v1/projekte/').status_code == 404
