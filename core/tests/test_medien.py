"""Auslieferung unter ``/media/`` (``core/medien.py``).

Alle Tests laufen mit ``DEBUG=False`` wie im Container, weil
``static()`` in der Entwicklung sonst jede Datei ausliefert und ein Fehler
nur im Betrieb auffiele.
"""

import re

import pytest
from django.contrib.auth import get_user_model

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"></svg>'
PDF = b'%PDF-1.7 festgeschrieben'


@pytest.fixture
def medienordner(settings, tmp_path, db):
    """Medienordner mit Marke, Firmenlogo und einem festgeschriebenen Beleg."""
    settings.DEBUG = False
    settings.MEDIA_ROOT = str(tmp_path)
    for pfad, inhalt in (('marke/logo.svg', SVG), ('marke/tab.svg', SVG),
                         ('marke/nicht-konfiguriert.svg', SVG),
                         ('firma/logo.svg', SVG),
                         ('belege/2026/10/RE-2026-0001.pdf', PDF)):
        datei = tmp_path / pfad
        datei.parent.mkdir(parents=True, exist_ok=True)
        datei.write_bytes(inhalt)
    settings.MARKE_LOGO = 'marke/logo.svg'
    settings.MARKE_FAVICON = 'marke/tab.svg'
    return tmp_path


def inhalt(antwort):
    return b''.join(antwort.streaming_content)


def test_logo_der_marke_ohne_anmeldung(client, medienordner):
    """Die Anmeldeseite zeigt Logo und Favicon, also ohne Anmeldung."""
    for pfad in ('logo.svg', 'tab.svg'):
        antwort = client.get(f'/media/marke/{pfad}')
        assert antwort.status_code == 200
        assert inhalt(antwort) == SVG


def test_logo_auf_der_anmeldeseite_ist_abrufbar(client, medienordner):
    """Die URL im HTML der Anmeldeseite liefert die Datei aus."""
    html = client.get('/admin/login/').content.decode()
    adressen = set(re.findall(r'/media/[^"\']+', html))

    assert adressen
    for adresse in adressen:
        assert client.get(adresse).status_code == 200


def test_nicht_konfigurierte_datei_der_marke_bleibt_verborgen(client, medienordner):
    """Freigegeben sind die konfigurierten Dateien, nicht der Ordner."""
    assert client.get('/media/marke/nicht-konfiguriert.svg').status_code == 404


def test_firmenlogo_nur_fuer_mitarbeiter(client, medienordner):
    adresse = '/media/firma/logo.svg'
    assert client.get(adresse).status_code == 404

    benutzer = get_user_model().objects.create_user('ohne-staff')
    client.force_login(benutzer)
    assert client.get(adresse).status_code == 404

    benutzer.is_staff = True
    benutzer.save()
    antwort = client.get(adresse)
    assert antwort.status_code == 200
    assert inhalt(antwort) == SVG


def test_belege_auch_fuer_superuser_nicht_ueber_media(verwaltung, medienordner):
    """Belege gibt nur faktura.admin.dokumente mit Rechteprüfung aus."""
    assert verwaltung.get(
        '/media/belege/2026/10/RE-2026-0001.pdf').status_code == 404


@pytest.mark.parametrize('adresse', [
    '/media/firma/../belege/2026/10/RE-2026-0001.pdf',
    '/media/marke/../belege/2026/10/RE-2026-0001.pdf',
    '/media/firma/%2e%2e/belege/2026/10/RE-2026-0001.pdf',
    '/media//belege/2026/10/RE-2026-0001.pdf',
])
def test_path_traversal_wird_abgewiesen(verwaltung, medienordner, adresse):
    assert verwaltung.get(adresse).status_code == 404
