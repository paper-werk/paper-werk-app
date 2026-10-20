"""Die Bedienungsanleitung: Seite, „?“ in der Kopfleiste, PDF.

Das „?“ wird nicht im HTML gesucht, sondern verfolgt: Link aus der echten
Maske lesen, aufrufen, Sprungziel auf der Hilfeseite finden.
"""

import re
from collections import Counter

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from pypdf import PdfReader

from hilfe.texte import anleitung

User = get_user_model()

HILFE = reverse('hilfe')


@pytest.fixture
def anwender(client, db):
    person = User.objects.create_superuser(
        'anwenderin', 'anwenderin@example.invalid', 'geheim12345')
    client.force_login(person)
    return person


def _hilfe_link(html: str) -> str | None:
    treffer = re.search(r'<a href="([^"]+)"[^>]*\bdata-hilfe\b', html)
    return treffer.group(1) if treffer else None


def test_ohne_anmeldung_geht_es_zur_anmeldung(client, db):
    antwort = client.get(HILFE)

    assert antwort.status_code == 302
    assert antwort.url.startswith(reverse('admin:login'))


def test_die_seite_zeigt_die_anleitung(client, anwender):
    antwort = client.get(HILFE)

    assert antwort.status_code == 200
    html = antwort.content.decode()
    assert '<h1 id="vom-angebot-zur-rechnung">' in html
    assert 'href="#angebot"' in html, 'Inhaltsverzeichnis fehlt'


def test_jeder_anker_kommt_nur_einmal_vor():
    """Jeder Anker ist eindeutig, weil Python-Markdown nur erzeugte ``id``
    eindeutig macht, nicht die mit ``{#…}`` gesetzten; das „?“ spränge
    sonst zur ersten Stelle."""
    ids = re.findall(r'\bid="([^"]+)"', anleitung().html)

    doppelt = [anker for anker, zahl in Counter(ids).items() if zahl > 1]
    assert not doppelt


def test_jeder_verweis_hat_ein_ziel():
    """Jeder interne Link (``[Angebote](#angebot)``) hat ein Ziel, damit ein
    umbenannter Anker auffällt."""
    html = anleitung().html
    ziele = set(re.findall(r'\bid="([^"]+)"', html))

    tot = set(re.findall(r'href="#([^"]+)"', html)) - ziele
    assert not tot


@pytest.mark.parametrize('adresse', [
    reverse('admin:faktura_angebot_changelist'),
    reverse('admin:faktura_angebot_add'),
    reverse('admin:faktura_abschlagsrechnung_changelist'),
    # Seiten ohne Modell, über ``hilfe_anker`` im Kontext.
    reverse('admin:index'),
    reverse('controlling'),
])
def test_das_fragezeichen_fuehrt_zum_abschnitt(client, anwender, adresse):
    link = _hilfe_link(client.get(adresse).content.decode())
    assert link is not None, f'kein „?“ auf {adresse}'

    pfad, anker = link.split('#')
    hilfeseite = client.get(pfad)

    assert hilfeseite.status_code == 200
    assert f'id="{anker}"' in hilfeseite.content.decode()


def test_ohne_abschnitt_kein_fragezeichen(client, anwender):
    """Ohne Abschnitt kein „?“, etwa bei den Zahlungszuordnungen."""
    html = client.get(
        reverse('admin:faktura_zahlungszuordnung_changelist')).content.decode()

    assert _hilfe_link(html) is None


def test_der_befehl_schreibt_das_pdf(tmp_path, db):
    ziel = tmp_path / 'anleitung.pdf'

    call_command('hilfe_pdf', ziel=ziel)

    text = '\n'.join(seite.extract_text() for seite in PdfReader(ziel).pages)
    assert 'Bedienungsanleitung' in text
    assert 'Vom Angebot zur Rechnung' in text
    assert 'Verwaltung' in text
