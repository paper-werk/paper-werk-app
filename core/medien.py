"""Auslieferung ausgewählter Dateien unter ``MEDIA_ROOT``.

``django.conf.urls.static.static()`` liefert nur bei ``DEBUG=True`` aus, und
der Reverse Proxy der Installation hat keine Regel für ``/media/``. Diese View
liefert in jeder Umgebung zwei Arten von Dateien aus:

- die in ``PAPER_WERK_MARKE_*`` konfigurierten Dateien ohne Anmeldung, weil
  Logo und Favicon auch auf der Anmeldeseite erscheinen;
- Dateien unter ``firma/`` (``Firma.logo``) für Mitarbeiter
  (``is_staff``), gebraucht für die HTML-Vorschau der Belege und die
  Firmenmaske.

Alle anderen Pfade ergeben 404, auch für angemeldete Benutzer, weil unter
``belege/`` die festgeschriebenen Belege liegen; diese liefert
``faktura.admin.dokumente`` mit Rechteprüfung aus.

Verworfen: eine Regel für ``/media/`` im Reverse Proxy, weil sie das Volume
im Proxy-Container und eine zweite Liste freigegebener Pfade in der
Installation bräuchte. WhiteNoise liefert nur Dateien aus, die beim Start
vorhanden sind. ``django.views.static.serve`` ist für große Mengen nicht
gedacht; hier geht es um wenige kleine Bilder.
"""

import posixpath

from django.conf import settings
from django.http import Http404
from django.views.static import serve

#: Unterordner von ``MEDIA_ROOT`` mit ``Firma.logo`` (``upload_to``).
FIRMA = 'firma'


def _normalisiert(pfad: str) -> str:
    """Pfad ohne führenden Schrägstrich und ohne ``.``-Segmente."""
    return posixpath.normpath(pfad).lstrip('/')


def _marke() -> set[str]:
    """Die in ``PAPER_WERK_MARKE_*`` konfigurierten Pfade."""
    pfade = (settings.MARKE_LOGO, settings.MARKE_LOGO_DUNKEL,
             settings.MARKE_FAVICON)
    return {_normalisiert(p) for p in pfade if p}


def freigegeben(request, pfad: str) -> bool:
    """Ob ``pfad`` (relativ zu ``MEDIA_ROOT``) ausgeliefert werden darf."""
    pfad = _normalisiert(pfad)
    if '..' in pfad.split('/'):
        return False
    if pfad in _marke():
        return True
    return pfad.startswith(f'{FIRMA}/') and request.user.is_staff


def medien(request, pfad):
    """Liefert eine freigegebene Datei aus, sonst 404."""
    if not freigegeben(request, pfad):
        raise Http404
    return serve(request, pfad, document_root=settings.MEDIA_ROOT)
