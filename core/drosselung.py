"""Drosselung der API.

Zwei Grenzen je Minute, beide im Cache ``drosselung`` (settings.CACHES), den
alle gunicorn-Worker eines Containers teilen; im Standard-Cache stünden die
Zähler je Worker und begrenzten auf das Dreifache.

* ``AngemeldetDrosseln``: Requests je Benutzer (Rate ``user``).
* ``TokenMitDrosselung``: fehlgeschlagene Token-Anmeldungen je IP-Adresse
  (Rate ``fehlversuch``). DRFs ``AnonRateThrottle`` greift hier nicht, weil
  DRF die Rechte vor der Drosselung prüft und ein Request ohne Anmeldung
  vorher mit 401 endet.
"""

import time

from django.core.cache import caches
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed, Throttled
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle


class AngemeldetDrosseln(UserRateThrottle):
    """Requests mit Anmeldung, je Benutzer."""

    cache = caches['drosselung']


class Fehlversuche(SimpleRateThrottle):
    """Zähler fehlgeschlagener Token-Anmeldungen je IP-Adresse.

    Gezählt wird nur über ``vermerken``; ``allow_request`` von DRF zählte
    jeden Request.
    """

    cache = caches['drosselung']
    scope = 'fehlversuch'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope,
                                    'ident': self.get_ident(request)}

    def gesperrt(self, request) -> float | None:
        """Wartezeit in Sekunden, wenn die Rate erreicht ist, sonst None."""
        self.key = self.get_cache_key(request, None)
        self.now = time.time()
        self.history = [t for t in self.cache.get(self.key, [])
                        if t > self.now - self.duration]
        if len(self.history) < self.num_requests:
            return None
        return self.wait()

    def vermerken(self):
        """Fehlversuch zu den in ``gesperrt`` geladenen hinzufügen."""
        self.history.insert(0, self.now)
        self.cache.set(self.key, self.history, self.duration)


class TokenMitDrosselung(TokenAuthentication):
    """TokenAuthentication, die nach zu vielen ungültigen Tokens derselben
    IP-Adresse mit 429 antwortet, auch für ein gültiges Token."""

    def authenticate(self, request):
        if 'HTTP_AUTHORIZATION' not in request.META:
            return None
        zaehler = Fehlversuche()
        warten = zaehler.gesperrt(request)
        if warten is not None:
            raise Throttled(wait=warten)
        try:
            return super().authenticate(request)
        except AuthenticationFailed:
            zaehler.vermerken()
            raise
