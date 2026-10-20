"""Ablaufdatum des HTTPS-Zertifikats der Installation.

Im Modus ``PAPER_WERK_TLS_MODE=datei`` stellt der Kunde das Zertifikat,
etwa aus einer Windows-Domäne, und erneuert es selbst, typischerweise nach
ein oder zwei Jahren. Ist es abgelaufen, öffnet kein Browser mehr App oder
Archiv, und die Anmeldung über Microsoft schlägt fehl. Die Startseite zeigt
Verwaltern einen Hinweis, sobald weniger als ``WARNUNG_TAGE`` bleiben
(``auswertung/dashboard.py``).

Nur im Modus "datei". Im Modus "intern" erneuert Caddy seine Zertifikate
alle paar Stunden; eine Prüfung meldete dort ständig einen nahen Ablauf.

Abgefragt wird Caddy im Compose-Netz mit dem Namen der Installation als SNI,
also dasselbe Zertifikat, das die Browser erhalten. Die Zertifikatsdatei
liest die App nicht, damit sie keinen Zugriff auf den privaten Schlüssel
daneben braucht. Die Kette wird nicht validiert: Gelesen wird nur das
Datum, und die CA des Kunden ist im Container nicht installiert.
"""

import logging
import socket
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography import x509
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

#: Vorlauf der Warnung. Ein Monat, weil die Erneuerung beim Kunden jemand
#: anderes übernimmt und Urlaub oder Vertretung einzuplanen sind.
WARNUNG_TAGE = 30

_SCHLUESSEL = 'paperwerk:zertifikat:gueltig_bis'

#: Cache-Dauer. Die Startseite fragt bei jedem Aufruf; nach sechs Stunden
#: verschwindet der Hinweis für ein erneuertes Zertifikat noch am selben Tag.
_MERKDAUER = 6 * 3600

#: Cache-Dauer bei nicht erreichbarem Caddy. Ohne Cache liefe jeder Aufruf der
#: Startseite in den Timeout.
_MERKDAUER_FEHLER = 10 * 60


@dataclass(frozen=True)
class Ablauf:
    gueltig_bis: datetime
    tage: int

    @property
    def abgelaufen(self) -> bool:
        return self.tage < 0

    @property
    def bald(self) -> bool:
        return self.tage < WARNUNG_TAGE


def _zertifikat_holen(adresse: str, name: str, port: int = 443) -> bytes:
    """Zertifikat, das Caddy für ``name`` ausliefert, als DER."""
    kontext = ssl.create_default_context()
    kontext.check_hostname = False
    kontext.verify_mode = ssl.CERT_NONE
    with socket.create_connection((adresse, port), timeout=5) as roh:
        with kontext.wrap_socket(roh, server_hostname=name) as tls:
            return tls.getpeercert(binary_form=True)


def ablauf(jetzt: datetime | None = None) -> Ablauf | None:
    """Ablaufdatum des Zertifikats oder None.

    None bei fehlendem HTTPS, im Modus "intern" oder wenn Caddy nicht
    erreichbar war. Im letzten Fall wird nur geloggt, damit nicht jeder
    Neustart von Caddy einen Hinweis auf der Startseite erzeugt.
    """
    if settings.PAPER_WERK_TLS_MODE != 'datei' or not settings.PAPER_WERK_HOSTNAME:
        return None
    jetzt = jetzt or datetime.now(UTC)

    gueltig_bis = cache.get(_SCHLUESSEL)
    if gueltig_bis is None:
        try:
            roh = _zertifikat_holen(settings.ZERTIFIKAT_PRUEFADRESSE,
                                    settings.PAPER_WERK_HOSTNAME)
            gueltig_bis = x509.load_der_x509_certificate(roh).not_valid_after_utc
        except (OSError, ValueError):
            logger.warning('Zertifikat von %s nicht lesbar; Ablauf ungeprüft.',
                           settings.PAPER_WERK_HOSTNAME, exc_info=True)
            cache.set(_SCHLUESSEL, False, _MERKDAUER_FEHLER)
            return None
        cache.set(_SCHLUESSEL, gueltig_bis, _MERKDAUER)
    elif gueltig_bis is False:
        return None

    return Ablauf(gueltig_bis=gueltig_bis, tage=(gueltig_bis - jetzt).days)
