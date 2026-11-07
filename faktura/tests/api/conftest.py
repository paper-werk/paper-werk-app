"""Vorbedingungen der Schnittstellentests.

Gleichnamige Fixtures aus ``faktura/tests/conftest.py`` werden hier
überschrieben, weil diese Tests die Schnittstelle prüfen und mit knapperen
Daten auskommen.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from faktura import services
from faktura.models import Beleg, BelegTyp, Firma, Kontakt, Projekt


@pytest.fixture
def firma(db):
    return Firma.objects.create(
        name='Werkstatt Amper GmbH', strasse='Musterweg 12',
        plz='80331', ort='München',
        steuernummer='143/815/47110', ust_id='DE123456789',
        bank='Stadtsparkasse', iban='DE02120300000000202051',
    )


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-1024', name='Bauherr Nord GmbH',
        strasse='Hafenstraße 3', plz='20095', ort='Hamburg',
    )


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(
        nummer='2026-042', bezeichnung='Halle Nord', kunde=kunde,
    )


@pytest.fixture
def dienst(django_user_model):
    """Ein Dienstzugang **ohne** Rechte, so wie ``api_schluessel`` ihn
    anlegt, bevor eine Gruppe dazukommt."""
    benutzer = django_user_model.objects.create(username='n8n', is_staff=False)
    benutzer.set_unusable_password()
    benutzer.save(update_fields=['password'])
    return benutzer


@pytest.fixture
def leser(dienst):
    """Derselbe Zugang mit den Leserechten der Gruppe "Faktura Dienst"."""
    dienst.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='faktura', codename__startswith='view_',
    ))
    return dienst


def _mit_schluessel(benutzer) -> APIClient:
    zugang = APIClient()
    zugang.credentials(
        HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=benutzer).key}')
    return zugang


@pytest.fixture
def client(leser):
    """Der Regelfall: angemeldet, mit Leserechten."""
    return _mit_schluessel(leser)


@pytest.fixture
def client_ohne_rechte(dienst):
    """Angemeldet, aber ohne jedes Recht: der häufigste Einrichtungsfehler."""
    return _mit_schluessel(dienst)


@pytest.fixture
def darf_aendern(leser):
    """Ergänzt das Recht, Belege zu ändern: das Recht zum Festschreiben.

    Bewusst nicht Teil der Dienstgruppe: Festschreiben vergibt eine Nummer aus
    dem lückenlosen Kreis und friert ein Dokument ein.
    """
    leser.user_permissions.add(Permission.objects.get(
        content_type__app_label='faktura', codename='change_beleg',
    ))
    return leser


@pytest.fixture
def darf_archivieren(leser):
    """Ergänzt das eigene Recht für den Archivvermerk."""
    leser.user_permissions.add(Permission.objects.get(
        content_type__app_label='faktura', codename='archivieren_beleg',
    ))
    return leser


@pytest.fixture
def entwurf(firma, kunde):
    """Ein Angebot im Entwurf, mit zwei Positionen."""
    beleg = services.beleg_anlegen(typ=BelegTyp.ANGEBOT, kunde=kunde)
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Planung', menge=Decimal('10.000'),
        einheit='Std', einzelpreis=Decimal('95.00'), steuersatz='19.00',
    )
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Fahrtkosten', menge=Decimal('1.000'),
        einheit='Pausch', einzelpreis=Decimal('120.50'), steuersatz='19.00',
    )
    return beleg


@pytest.fixture
def rechnung(firma, kunde):
    """Eine festgeschriebene Rechnung, der Regelfall für das Archiv."""
    beleg = services.beleg_anlegen(
        typ=BelegTyp.RECHNUNG, kunde=kunde, leistungsdatum=date(2026, 8, 1),
    )
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Ausführung', menge=Decimal('1.000'),
        einheit='Pausch', einzelpreis=Decimal('2500.00'), steuersatz='19.00',
    )
    return services.beleg_festschreiben(beleg_id=beleg.pk)


@pytest.fixture
def rechnung_mit_pdf(rechnung):
    """Dieselbe Rechnung, mit angehängter Datei.

    Der Inhalt ist eine Attrappe: Ob WeasyPrint ein brauchbares PDF erzeugt,
    prüft ``faktura/tests/test_pdf.py``. Hier geht es darum, dass die
    **gespeicherte** Datei ausgeliefert wird und nicht eine neu gerenderte.
    """
    rechnung.pdf.save('probe.pdf', ContentFile(b'%PDF-1.4 Attrappe'), save=False)
    Beleg.objects.filter(pk=rechnung.pk).update(pdf=rechnung.pdf.name)
    rechnung.refresh_from_db()
    return rechnung


@pytest.fixture
def rechnung_mit_xml(rechnung):
    """Dieselbe Rechnung mit abgelegtem XML, wie nach dem Festschreiben.

    Der Inhalt ist absichtlich keines, das ``facturx`` so erzeugen würde:
    Nur so zeigt der Test, dass die **abgelegte** Datei ausgeliefert wird
    und nicht eine frisch erzeugte.
    """
    import hashlib

    inhalt = b'<rsm:CrossIndustryInvoice>abgelegt</rsm:CrossIndustryInvoice>'
    rechnung.xml.save('probe.xml', ContentFile(inhalt), save=False)
    Beleg.objects.filter(pk=rechnung.pk).update(
        xml=rechnung.xml.name,
        xml_sha256=hashlib.sha256(inhalt).hexdigest(),
        erechnungsprofil='EN 16931',
    )
    rechnung.refresh_from_db()
    return rechnung
