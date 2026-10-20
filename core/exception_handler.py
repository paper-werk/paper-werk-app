"""Übersetzt fachliche Fehler in HTTP-Antworten.

Services werfen Unterklassen von ``FachlicherFehler`` (etwa
``BelegNichtAenderbar``); der Handler macht daraus eine Antwort mit
``http_status`` und Meldung. Die Views brauchen dafür kein try/except.

Konfiguriert über ``REST_FRAMEWORK['EXCEPTION_HANDLER']``. Der Handler kennt
nur die gemeinsame Oberklasse aus ``core/exceptions.py`` und gilt damit für
jede App.
"""

from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .exceptions import FachlicherFehler


def api_exception_handler(exc, context):
    """DRF-Handler mit Zusatzbehandlung für fachliche Fehler.

    Die Prüfung steht vor dem Aufruf von DRF, weil DRF für diese Ausnahmen
    ``None`` zurückgibt und Django daraus eine 500 macht.
    """
    if isinstance(exc, FachlicherFehler):
        return Response({'detail': str(exc)}, status=exc.http_status)

    return drf_exception_handler(exc, context)
