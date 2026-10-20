"""Eigener Name und eigenes Logo einer Installation (``core/marke.py``).

Geprüft wird das gerenderte HTML, weil ein Test auf ``UNFOLD['SITE_TITLE']``
auch grün bliebe, wenn Unfold den Wert nie anzeigt.

Die vier Seiten der Anmeldung über Microsoft haben keine eigene URL; sie
entstehen im Login-Flow (``core/anmeldung.py``). Sie werden mit
``render_to_string`` und einem echten Request gerendert, damit die
Kontextprozessoren laufen, um die es hier geht.
"""

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.checks import run_checks
from django.template.loader import render_to_string
from django.test import RequestFactory
from django.utils import timezone

from core import zertifikat

User = get_user_model()

#: Ein Name ohne Bestandteil von „Paper-Werk“, damit sich prüfen lässt, ob
#: der alte Name verschwunden ist.
EIGENER = 'Belegwerk'

#: Minimales gültiges SVG. Geprüft wird nur, ob die Anwendung die Datei
#: findet und ihre URL ausgibt.
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"></svg>'


@pytest.fixture
def medienordner(settings, tmp_path):
    """Leerer Medienordner für Testbilder."""
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


@pytest.fixture
def bild(medienordner):
    """Legt eine Bilddatei im Medienordner ab und gibt den relativen Pfad zurück."""
    def anlegen(pfad='marke/logo.svg', inhalt=SVG):
        datei = medienordner / pfad
        datei.parent.mkdir(parents=True, exist_ok=True)
        datei.write_bytes(inhalt)
        return pfad
    return anlegen


def seite(client):
    """Admin-Seite mit Seitenleiste: die leere Kundenliste.

    Geprüft wird der Rahmen (Kopf, Seitenleiste, Titel), der auf jeder Seite
    gleich ist. Nicht die Benutzerliste, weil ihr Filter die Gruppen
    ``paper-werk-*`` als Daten enthält, die absichtlich ihren Namen behalten
    (:func:`test_die_gruppennamen_bleiben_absichtlich_stehen`). Nicht die
    Startseite, weil die Auswertungen Stammdaten bräuchten.
    """
    antwort = client.get('/admin/faktura/kontakt/')
    assert antwort.status_code == 200
    return antwort.content.decode()


# --- Name --------------------------------------------------------------------

def test_ohne_einstellung_heisst_es_paper_werk(verwaltung, client):
    """Ohne Einstellung gilt der Name des Projekts."""
    html = seite(client)

    assert 'Paper-Werk' in html
    assert '<title>' in html


def test_eigener_name_steht_im_kopf_und_im_browsertab(verwaltung, client, settings):
    settings.MARKE_NAME = EIGENER

    html = seite(client)

    assert EIGENER in html
    # Titel im Browsertab.
    titel = html.split('<title>')[1].split('</title>')[0]
    assert EIGENER in titel


def test_der_alte_name_verschwindet_vollstaendig(verwaltung, client, settings):
    """Nach dem Umbenennen enthält die Seite „Paper-Werk“ nicht mehr.

    Findet übersehene Vorkommen in Kopf, Titel oder Hinweistexten.
    """
    settings.MARKE_NAME = EIGENER

    html = seite(client)

    assert 'paper-werk' not in html.lower()


def test_untertitel_laesst_sich_leeren(verwaltung, client, settings):
    settings.MARKE_NAME = EIGENER
    settings.MARKE_UNTERTITEL = ''

    html = seite(client)

    assert 'Faktura, Projekte, Controlling' not in html
    assert EIGENER in html


def test_eigener_untertitel_erscheint(verwaltung, client, settings):
    settings.MARKE_UNTERTITEL = 'Verwaltung und Abrechnung'

    assert 'Verwaltung und Abrechnung' in seite(client)


# --- Symbol und Logo ---------------------------------------------------------

def test_ohne_logo_steht_das_symbol_da(verwaltung, client, settings):
    settings.MARKE_LOGO = ''
    settings.MARKE_SYMBOL = 'receipt_long'

    html = seite(client)

    assert 'receipt_long' in html
    assert '<img src="/media/' not in html


def test_eigenes_symbol_wird_verwendet(verwaltung, client, settings):
    settings.MARKE_SYMBOL = 'engineering'

    assert 'engineering' in seite(client)


def test_logo_erscheint_als_bild_aus_dem_medienordner(verwaltung, client, settings, bild):
    settings.MARKE_LOGO = bild('marke/logo.svg')

    html = seite(client)

    assert '/media/marke/logo.svg' in html


def test_logo_fuer_hell_und_dunkel_getrennt(verwaltung, client, settings, bild):
    settings.MARKE_LOGO = bild('marke/hell.svg')
    settings.MARKE_LOGO_DUNKEL = bild('marke/dunkel.svg')

    html = seite(client)

    assert '/media/marke/hell.svg' in html
    assert '/media/marke/dunkel.svg' in html


def test_ohne_dunkle_fassung_gilt_dieselbe_datei(verwaltung, client, settings, bild):
    """Ohne Logo für den Dark Mode gilt das eine Logo in beiden Modi."""
    settings.MARKE_LOGO = bild('marke/logo.svg')
    settings.MARKE_LOGO_DUNKEL = ''

    html = seite(client)

    assert html.count('/media/marke/logo.svg') == 1


def test_eingestelltes_logo_ohne_datei_faellt_auf_das_symbol_zurueck(
        verwaltung, client, settings, medienordner):
    """Fehlt die Datei, erscheint kein defektes Bild im Kopf.

    Den Fehler meldet ``manage.py check``, siehe die Systemprüfung unten.
    """
    settings.MARKE_LOGO = 'marke/gibtsnicht.svg'
    settings.MARKE_SYMBOL = 'receipt_long'

    html = seite(client)

    assert 'gibtsnicht' not in html
    assert 'receipt_long' in html


def test_logo_ausserhalb_des_medienordners_wird_abgewiesen(
        verwaltung, client, settings, medienordner):
    """Ein ``..`` im Pfad wird abgelehnt (Path Traversal).

    Die URL zeigte sonst auf eine Datei außerhalb von ``/media/``, die nicht
    ausgeliefert wird.
    """
    draussen = medienordner.parent / 'fremd.svg'
    draussen.write_bytes(SVG)

    settings.MARKE_LOGO = '../fremd.svg'

    assert 'fremd.svg' not in seite(client)


# --- Favicon -----------------------------------------------------------------

def test_favicon_ohne_einstellung_ist_das_mitgelieferte(verwaltung, client, settings):
    settings.MARKE_FAVICON = ''

    html = seite(client)

    assert 'favicon.svg' in html
    assert 'image/svg+xml' in html


def test_eigenes_favicon_mit_passendem_medientyp(verwaltung, client, settings, bild):
    """Ein PNG-Favicon erhält den Typ ``image/png``."""
    settings.MARKE_FAVICON = bild('marke/tab.png', inhalt=b'\x89PNG\r\n\x1a\n')

    html = seite(client)

    assert '/media/marke/tab.png' in html
    assert 'image/png' in html


# --- Anmeldeseiten -----------------------------------------------------------

@pytest.mark.parametrize('vorlage', [
    'admin/sso_kein_zugang.html',
    'admin/sso_nicht_erreichbar.html',
    'socialaccount/authentication_error.html',
    'socialaccount/login_cancelled.html',
])
def test_anmeldeseiten_tragen_den_eigenen_namen(db, settings, vorlage):
    """Die vier Seiten des SSO-Flows zeigen den eingestellten Namen.

    Sie liegen außerhalb des Admin, wo Unfold den Namen nicht setzt, und
    hatten ihn im Fließtext und als Fallback im Titel.
    """
    settings.MARKE_NAME = EIGENER
    anfrage = RequestFactory().get('/')

    html = render_to_string(vorlage, {'anbieter': 'Microsoft'}, request=anfrage)

    assert EIGENER in html
    assert 'paper-werk' not in html.lower()


def test_anmeldeseite_des_admin_traegt_den_eigenen_namen(db, client, settings):
    settings.MARKE_NAME = EIGENER

    html = client.get('/admin/login/').content.decode()

    assert EIGENER in html
    assert 'Paper-Werk' not in html


def test_zertifikatshinweis_nennt_den_eigenen_namen(verwaltung, client, settings):
    """Der Zertifikatshinweis auf der Startseite verwendet den eingestellten
    Namen.

    Abgerufen wird die Startseite, weil die Box an einer Bedingung im
    Kontext hängt, die ein Rendern des Templates mit vorgegebenem Kontext
    umginge. Gemockt ist nur die Abfrage des Zertifikats über das Netz.
    """
    settings.MARKE_NAME = EIGENER
    laeuft_ab = zertifikat.Ablauf(
        gueltig_bis=timezone.now() + timedelta(days=5), tage=5)

    with mock.patch.object(zertifikat, 'ablauf', return_value=laeuft_ab):
        html = client.get('/admin/').content.decode()

    assert f'Danach öffnen die Browser {EIGENER} und das Archiv' in html
    assert 'paper-werk' not in html.lower()


# --- Systemprüfung -----------------------------------------------------------

def _warnungen():
    return [f for f in run_checks() if f.id == 'paperwerk.W002']


def test_pruefung_meldet_ein_logo_ohne_datei(settings, medienordner):
    settings.MARKE_LOGO = 'marke/gibtsnicht.svg'

    gemeldet = _warnungen()

    assert len(gemeldet) == 1
    assert 'PAPER_WERK_MARKE_LOGO' in gemeldet[0].msg


def test_pruefung_schweigt_wenn_die_datei_da_ist(settings, bild):
    settings.MARKE_LOGO = bild('marke/logo.svg')

    assert _warnungen() == []


def test_pruefung_schweigt_ohne_eingestelltes_logo(settings, medienordner):
    settings.MARKE_LOGO = ''
    settings.MARKE_LOGO_DUNKEL = ''
    settings.MARKE_FAVICON = ''

    assert _warnungen() == []


def test_pruefung_erfasst_auch_dunkle_fassung_und_favicon(settings, medienordner):
    """Je eine Warnung für Logo, Logo im Dark Mode und Favicon."""
    settings.MARKE_LOGO = 'a.svg'
    settings.MARKE_LOGO_DUNKEL = 'b.svg'
    settings.MARKE_FAVICON = 'c.svg'

    assert len(_warnungen()) == 3


def test_die_gruppennamen_bleiben_absichtlich_stehen(verwaltung, client, settings):
    """Die Gruppen heißen nach dem Umbenennen weiter ``paper-werk-*``.

    Die Gruppennamen sind zugleich Rollennamen in Entra ID und Gruppennamen
    in Paperless; eine Änderung nur hier bräche das SSO
    (``core/gruppen.py``). Sichtbar sind sie im Gruppenfilter der
    Benutzerliste. Umbenennen lassen sie sich nur in allen drei Systemen
    zugleich.

    Ändert sich diese Festlegung, schlägt der Test fehl; dann ist auch der
    Docstring von ``core/marke.py`` anzupassen.
    """
    settings.MARKE_NAME = EIGENER

    antwort = client.get('/admin/core/user/')

    assert 'paper-werk-buero' in antwort.content.decode()


# --- Umgebungsvariablen ------------------------------------------------------

def test_die_umgebungsvariablen_kommen_wirklich_an():
    """Die Umgebungsvariablen ``PAPER_WERK_MARKE_*`` erreichen die Settings.

    Die übrigen Tests setzen ``settings.MARKE_NAME`` direkt; ein Tippfehler
    im Variablennamen in ``base.py`` fänden sie nicht.

    Läuft in einem eigenen Prozess, weil die Settings einmal beim Start
    gelesen werden. Der Kindprozess erhält über ``env=`` eine eigene
    Umgebung mit genau diesen Werten, damit die lokale ``.env`` nicht
    mitwirkt.
    """
    umgebung = {
        **os.environ,
        'DJANGO_SETTINGS_MODULE': 'paperwerk.settings.dev',
        'PAPER_WERK_MARKE_NAME': EIGENER,
        'PAPER_WERK_MARKE_UNTERTITEL': 'Verwaltung und Abrechnung',
        'PAPER_WERK_MARKE_SYMBOL': 'engineering',
        'PAPER_WERK_MARKE_WEBSEITE': 'https://www.beispielbuero.de',
    }

    ergebnis = subprocess.run(
        [sys.executable, '-c',
         'import django; django.setup();'
         'from django.conf import settings;'
         'print(settings.MARKE_NAME, settings.MARKE_UNTERTITEL,'
         ' settings.MARKE_SYMBOL, settings.MARKE_WEBSEITE, sep="|")'],
        cwd=Path(__file__).resolve().parents[2],
        env=umgebung, capture_output=True, text=True, encoding='utf-8',
    )

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert ergebnis.stdout.strip() == (
        f'{EIGENER}|Verwaltung und Abrechnung|engineering'
        f'|https://www.beispielbuero.de')
