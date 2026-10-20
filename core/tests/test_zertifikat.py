"""Hinweis auf ein ablaufendes HTTPS-Zertifikat (``core/zertifikat.py``).

Geprüft wird auf der Startseite, wo Verwalter den Hinweis sehen. Die
Zertifikate werden in jedem Test erzeugt und geparst; gemockt ist nur die
Verbindung zu Caddy. ``test_liest_ein_echtes_zertifikat`` holt das
Zertifikat über TLS von einem Testserver.
"""

import socket
import ssl
import threading
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from django.contrib.auth import get_user_model
from django.core.cache import cache

from core import zertifikat

User = get_user_model()
NAME = 'paper-werk.betrieb.example'


def zertifikat_bis(gueltig_bis: datetime):
    """Selbstsigniertes Zertifikat für NAME und sein privater Schlüssel."""
    schluessel = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, NAME)])
    zert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(schluessel.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(gueltig_bis - timedelta(days=365))
            .not_valid_after(gueltig_bis)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(NAME)]),
                           critical=False)
            .sign(schluessel, hashes.SHA256()))
    return zert, schluessel


def der_bis(tage: int) -> bytes:
    zert, _ = zertifikat_bis(datetime.now(UTC) + timedelta(days=tage, hours=1))
    return zert.public_bytes(serialization.Encoding.DER)


@pytest.fixture
def https_datei(settings):
    settings.PAPER_WERK_HOSTNAME = NAME
    settings.PAPER_WERK_TLS_MODE = 'datei'
    cache.clear()
    yield
    cache.clear()


def startseite(client) -> str:
    antwort = client.get('/admin/')
    assert antwort.status_code == 200
    return antwort.content.decode()


# ── Anzeige ───────────────────────────────────────────────────────────────────

def test_verwaltung_sieht_den_hinweis(verwaltung, https_datei):
    with mock.patch.object(zertifikat, '_zertifikat_holen', return_value=der_bis(10)):
        seite = startseite(verwaltung)

    assert 'id="zertifikat-hinweis"' in seite
    assert 'läuft in 10 Tagen ab' in seite


def test_abgelaufen_heisst_abgelaufen(verwaltung, https_datei):
    with mock.patch.object(zertifikat, '_zertifikat_holen', return_value=der_bis(-3)):
        seite = startseite(verwaltung)

    assert 'Das Sicherheitszertifikat ist abgelaufen' in seite


def test_mit_zeit_kein_hinweis(verwaltung, https_datei):
    with mock.patch.object(zertifikat, '_zertifikat_holen', return_value=der_bis(45)):
        seite = startseite(verwaltung)

    assert 'zertifikat-hinweis' not in seite


def test_das_buero_sieht_ihn_nicht(client, db, https_datei):
    """Nur Verwalter sehen den Hinweis, weil nur sie handeln können."""
    client.force_login(User.objects.create_user('erika', password='x', is_staff=True))
    with mock.patch.object(zertifikat, '_zertifikat_holen', return_value=der_bis(10)) as holen:
        seite = startseite(client)

    assert 'zertifikat-hinweis' not in seite
    holen.assert_not_called()


def test_modus_intern_prueft_nicht(verwaltung, settings, https_datei):
    """Im Modus "intern" erneuert Caddy alle paar Stunden selbst."""
    settings.PAPER_WERK_TLS_MODE = 'intern'
    with mock.patch.object(zertifikat, '_zertifikat_holen', return_value=der_bis(0)) as holen:
        seite = startseite(verwaltung)

    assert 'zertifikat-hinweis' not in seite
    holen.assert_not_called()


def test_ohne_https_prueft_nicht(verwaltung, settings):
    settings.PAPER_WERK_HOSTNAME = ''
    settings.PAPER_WERK_TLS_MODE = ''
    with mock.patch.object(zertifikat, '_zertifikat_holen') as holen:
        startseite(verwaltung)

    holen.assert_not_called()


def test_caddy_nicht_erreichbar_bremst_die_startseite_nicht(verwaltung, https_datei):
    """Kein Hinweis, kein Fehler und kein neuer Versuch je Aufruf, weil sonst
    jede Startseite in den Timeout liefe."""
    with mock.patch.object(zertifikat, '_zertifikat_holen',
                           side_effect=ConnectionRefusedError) as holen:
        erste = startseite(verwaltung)
        startseite(verwaltung)

    assert 'zertifikat-hinweis' not in erste
    assert holen.call_count == 1


def test_gemerkt_wird_das_datum_nicht_die_tage(https_datei):
    """Gecacht wird das Datum; die Tage werden bei jedem Aufruf neu
    berechnet."""
    with mock.patch.object(zertifikat, '_zertifikat_holen', return_value=der_bis(10)):
        heute = zertifikat.ablauf()
    spaeter = zertifikat.ablauf(jetzt=datetime.now(UTC) + timedelta(days=4))

    assert heute.tage == 10
    assert spaeter.tage == 6


# ── Abfrage über TLS ──────────────────────────────────────────────────────────

def test_liest_ein_echtes_zertifikat(tmp_path):
    """Ohne Mock: Ein TLS-Server im Test liefert ein Zertifikat für NAME,
    ``_zertifikat_holen`` liest es über SNI. Prüft die Abfrage selbst, etwa
    einen fehlenden Hostnamen, bei dem Caddy ein anderes oder kein
    Zertifikat sendet."""
    bis = datetime(2031, 3, 1, 12, 0, tzinfo=UTC)
    zert, schluessel = zertifikat_bis(bis)
    (tmp_path / 'z.pem').write_bytes(zert.public_bytes(serialization.Encoding.PEM))
    (tmp_path / 's.pem').write_bytes(schluessel.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))

    server_kontext = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_kontext.load_cert_chain(tmp_path / 'z.pem', tmp_path / 's.pem')
    gesehener_name = []
    server_kontext.sni_callback = lambda sock, name, ctx: gesehener_name.append(name)

    lauscher = socket.create_server(('127.0.0.1', 0))
    port = lauscher.getsockname()[1]

    def bedienen():
        # Der Client schließt die Verbindung, sobald er das Zertifikat hat,
        # während der Server noch den Handshake abschließt. Unter Windows
        # endet das je nach Timing mit ConnectionAbortedError (WinError
        # 10053). Geprüft wird nur, was der Client gelesen hat; Fehler auf
        # der Serverseite werden deshalb ignoriert.
        verbindung, _ = lauscher.accept()
        try:
            with server_kontext.wrap_socket(verbindung, server_side=True) as tls:
                tls.recv(1)
        except OSError:  # ssl.SSLError ist eine Unterklasse davon
            pass

    faden = threading.Thread(target=bedienen, daemon=True)
    faden.start()
    try:
        roh = zertifikat._zertifikat_holen('127.0.0.1', NAME, port=port)
    finally:
        faden.join(timeout=5)
        lauscher.close()

    assert gesehener_name == [NAME]
    assert x509.load_der_x509_certificate(roh).not_valid_after_utc == bis
