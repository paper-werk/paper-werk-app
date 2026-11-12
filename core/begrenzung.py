"""Größenbegrenzung für Requests ohne Anmeldung.

``DATA_UPLOAD_MAX_NUMBER_FIELDS`` ist für die Belegmaske auf 20000 erhöht und
gilt für jeden Request. Ohne Anmeldung gibt es nur Anmeldeformulare mit
wenigen hundert Byte; ein größerer Rumpf wird abgelehnt, bevor Django ihn
parst.

Requests mit ``Authorization``-Header bleiben unberührt, weil DRF den Token
erst in der View prüft und der Benutzer hier noch anonym erscheint.
"""

from django.conf import settings
from django.http import HttpResponse

#: Methoden mit Rumpf.
MIT_RUMPF = {'POST', 'PUT', 'PATCH'}


class AnonymeAnfragenBegrenzen:
    """Lehnt Requests ohne Anmeldung mit mehr als ``ANONYM_MAX_BYTES`` Rumpf
    mit 413 ab. Steht nach der AuthenticationMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (request.method in MIT_RUMPF
                and not request.user.is_authenticated
                and 'HTTP_AUTHORIZATION' not in request.META
                and _laenge(request) > settings.ANONYM_MAX_BYTES):
            return HttpResponse('Anfrage zu groß.', status=413,
                                content_type='text/plain; charset=utf-8')
        return self.get_response(request)


def _laenge(request) -> int:
    """Content-Length; ohne Angabe oder bei ungültiger 0."""
    try:
        return int(request.META.get('CONTENT_LENGTH') or 0)
    except ValueError:
        return 0
