"""Name, Logo und Favicon der Installation.

Vorgabe ist „Paper-Werk“. Ein Betrieb kann Name und Logo im Browsertab und
im Kopf der Seitenleiste durch die eigenen ersetzen.

Geändert wird nur, was der Anwender sieht. Gruppen (``paper-werk-buero``
usw.), Umgebungsvariablen, Container und Schnittstelle behalten ihre Namen,
weil Entra ID und Paperless dieselben Gruppennamen verwenden.

Konfiguriert wird die Marke über Settings, weil der Name schon vor der
Anmeldung erscheint und einmal bei der Installation festgelegt wird.

Alle Werte sind Funktionen: ``paperwerk/settings/unfold.py`` trägt sie als
Callables ein, Unfold ruft sie bei jedem Seitenaufbau auf. Ein später
abgelegtes Logo erscheint dadurch ohne Neustart.
"""

from pathlib import Path

from django.conf import settings
from django.templatetags.static import static

#: Dateiendung und Medientyp für das Favicon. Unfold schreibt den Typ in das
#: ``<link>``-Element; er muss deshalb zur Datei passen.
_FAVICON_TYPEN = {
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.ico': 'image/x-icon',
    '.gif': 'image/gif',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
}


def name(request=None) -> str:
    """Name im Browsertab und im Kopf der Seitenleiste."""
    return settings.MARKE_NAME


def untertitel(request=None) -> str:
    """Zeile unter dem Namen; leer blendet sie aus."""
    return settings.MARKE_UNTERTITEL


def symbol(request=None) -> str:
    """Material-Symbol im farbigen Quadrat, angezeigt ohne Logo."""
    return settings.MARKE_SYMBOL


def webseite(request=None) -> str:
    """Ziel von „Webseite anzeigen“ im Benutzermenü; leer blendet es aus.

    Unfolds Vorgabe ``/`` führt in dieser Anwendung auf keine Seite.
    """
    return settings.MARKE_WEBSEITE


def logo(request=None):
    """Logo im Kopf der Seitenleiste.

    Rückgabe nach Unfolds Format: ``None`` (Unfold zeigt dann
    :func:`symbol`), eine URL oder ein Dict mit ``light`` und ``dark``.

    Eingetragen als ``SITE_ICON``, weil ``SITE_LOGO`` den ganzen Kopf
    einschließlich Name ersetzt.
    """
    hell = medien_adresse(settings.MARKE_LOGO)
    if not hell:
        return None

    dunkel = medien_adresse(settings.MARKE_LOGO_DUNKEL)
    if not dunkel:
        # Keine eigene Fassung für den Dunkelmodus.
        return hell

    return {'light': hell, 'dark': dunkel}


def favicons(request=None) -> list[dict]:
    """Favicon im Format von Unfolds ``SITE_FAVICONS``.

    Ohne eigene Datei das mitgelieferte SVG (Material-Symbol
    „receipt_long“). Die Liste wird berechnet, weil ``type`` von der Endung
    der konfigurierten Datei abhängt.
    """
    eigenes = medien_adresse(settings.MARKE_FAVICON)
    adresse = eigenes or static('core/images/favicon.svg')
    endung = Path(settings.MARKE_FAVICON if eigenes else 'favicon.svg').suffix.lower()

    return [{
        'rel': 'icon',
        'type': _FAVICON_TYPEN.get(endung, 'image/svg+xml'),
        'href': adresse,
    }]


def medien_adresse(pfad: str) -> str:
    """URL einer Datei unter ``MEDIA_ROOT``, leer, wenn sie fehlt.

    Die Marke liegt im Medienordner, weil ``collectstatic`` die statischen
    Dateien beim Bauen des Images einsammelt und eine später abgelegte Datei
    dort nicht ankäme. Fehlt die Datei, ist die Rückgabe leer, damit kein
    defektes Bild erscheint; ``manage.py check`` meldet den Fall
    (``paperwerk.W002``).
    """
    if not pfad:
        return ''

    wurzel = Path(settings.MEDIA_ROOT).resolve()
    datei = (wurzel / pfad).resolve()

    # Verhindert Path Traversal über ``..``.
    if not datei.is_relative_to(wurzel) or not datei.is_file():
        return ''

    return f"{settings.MEDIA_URL}{pfad.lstrip('/')}"


def marke(request):
    """Kontextprozessor: Name und Untertitel für jedes Template.

    Unfold setzt ``site_title`` nur im Admin; die Anmeldeseiten liegen zum
    Teil außerhalb.
    """
    return {'marke': settings.MARKE_NAME, 'marke_untertitel': settings.MARKE_UNTERTITEL}
