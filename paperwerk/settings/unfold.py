"""Konfiguration von django-unfold: Farben, Seitenleiste, Startseite.

Wegen des Umfangs aus base.py ausgelagert.

Die Einträge der Seitenleiste registrieren die Fachapps in
``AppConfig.ready()`` über ``core.erweiterungen.menue()``; dieses Modul
liest nur ``erweiterungen.menue_abschnitte``.

Unfold liefert eigene Templates für den Django-Admin und lässt seine Logik
unverändert. Jede ModelAdmin-Klasse erbt von ``unfold.admin.ModelAdmin``,
damit die Formularfelder Unfolds Widgets erhalten.
Fehlt die Basisklasse, gibt es keine Fehlermeldung, nur Eingabefelder im
Stil des Django-Admin. ``manage.py check`` erkennt das nicht;
``auswertung/tests/test_dashboard.py`` prüft es über die Registry des Admin. Das
schließt die in core/admin.py neu registrierten Modelle ein: Djangos
Gruppen, die Nummernkreise von django-sequences und die API-Schlüssel von
DRF.
"""

from django.templatetags.static import static

from core import erweiterungen, marke

UNFOLD = {
    # Name, Untertitel, Symbol, Logo und Favicon kommen aus ``core/marke.py``
    # und damit aus der ``.env``. Was umbenannt wird und was nicht, steht im
    # Docstring von core/marke.py.
    #
    # Callables, weil base.py dieses Modul importiert, während
    # die Settings noch geladen werden; ``settings.MARKE_NAME`` existiert zu
    # diesem Zeitpunkt nicht. Unfold ruft die Funktionen beim Seitenaufbau
    # auf.
    'SITE_URL': marke.webseite,
    'SITE_TITLE': marke.name,
    'SITE_HEADER': marke.name,
    'SITE_SUBHEADER': marke.untertitel,

    # Hintergrundbild des Logins aus ``core/static/core/images/``.
    'LOGIN': {
        'image': lambda request: static('core/images/login-bg.png'),
    },

    # Material-Symbol, angezeigt ohne Logo.
    'SITE_SYMBOL': marke.symbol,

    # Logo des Betriebs neben dem Namen. SITE_ICON, weil SITE_LOGO den ganzen
    # Kopf mit Name und Untertitel ersetzt. Ohne Logo liefert die Funktion
    # ``None``, und Unfold zeigt SITE_SYMBOL.
    'SITE_ICON': marke.logo,

    # Favicon. Ohne eigene Datei dasselbe Material-Symbol als SVG. Safari
    # unterstützt keine SVG-Favicons; dafür bräuchte es einen zweiten Eintrag
    # mit PNG.
    #
    # Die ganze Liste ist ein Callable, weil Unfold zwar ``href`` zur Laufzeit
    # auflöst, ``type`` aber nicht, und der Medientyp von der Endung der
    # konfigurierten Datei abhängt.
    'SITE_FAVICONS': marke.favicons,

    # Kein Button "Verlauf" in der Kopfleiste; der Verlauf ist letzter
    # Eintrag in "Weitere …" (core.adminhilfen.VerlaufInWeitere).
    'SHOW_HISTORY': False,

    # "Auf der Seite anzeigen" ausblenden, weil die Anwendung keine
    # öffentlichen Seiten hat. Django zeigt den Button für jedes Modell mit
    # get_absolute_url.
    'SHOW_VIEW_ON_SITE': False,

    # Schnellsuche (Strg+K). Findet die Listen ("Rechnung" führt in die
    # Rechnungsliste) und über ``search_callback`` Kunden, Projekte, Belege
    # und Beträge, je Art wenige Treffer mit Link auf die Akte
    # (core.erweiterungen.suche, faktura/suche.py).
    #
    # ``search_models`` ist aus, weil Unfold damit die Daten jedes Modells
    # mit search_fields durchsucht, alle Treffer ohne Limit lädt und auf das
    # Änderungsformular verlinkt.
    'COMMAND': {
        'search_models': False,
        'search_callback': erweiterungen.suchergebnisse,
        'show_history': True,
    },

    # paperwerk.css enthält die Tailwind-Klassen, die Unfolds vorkompiliertes
    # CSS nicht mitbringt, gebaut aus stile/eingang.css (``npm run css``).
    # unfold-overrides.css enthält Anpassungen für den Light Mode.
    'STYLES': [
        lambda request: static('core/css/paperwerk.css'),
        lambda request: static('core/css/unfold-overrides.css'),
    ],

    # Deutsche Zahlenformate an Achse und Tooltip der Chart.js-Diagramme
    # (Controlling), siehe Kopf der Datei.
    'SCRIPTS': [
        lambda request: static('core/js/diagramme.js'),
    ],

    "BORDER_RADIUS": "2px",

    'COLORS': {
        # Primärfarbe Blau (Unfolds Vorgabe ist Violett), ohne fachliche
        # Bedeutung.
        # oklch wie in Unfolds eigenen Vorgaben. Beim Austausch alle elf
        # Stufen setzen, weil Unfold daraus auch Rahmen, Hintergründe und
        # den Dark Mode ableitet.
        'primary': {
            '50': 'oklch(97.3% .006 223.456)',
            '100': 'oklch(93.1% .016 221.084)',
            '200': 'oklch(86.7% .030 223.810)',
            '300': 'oklch(77.1% .050 225.181)',
            '400': 'oklch(64.8% .071 229.158)',
            '500': 'oklch(54.0% .070 231.303)',
            '600': 'oklch(48.7% .063 237.181)',
            '700': 'oklch(43.1% .051 239.139)',
            '800': 'oklch(39.0% .039 240.547)',
            '900': 'oklch(35.5% .033 243.719)',
            '950': 'oklch(26.6% .027 244.613)',
        },
        'base': {
            '50':  'oklch(98.5% .00023 286.04)',
            '100': 'oklch(96.7% .00034 286.04)',
            '200': 'oklch(87.2% .00115 286.04)',
            '300': 'oklch(78.9% .00184 286.04)',
            '400': 'oklch(70.7% .00252 286.04)',
            '500': 'oklch(55.1% .0031  286.04)',
            '600': 'oklch(44.6% .00344 286.04)',
            '700': 'oklch(40.95% .00367 286.04)',
            '800': 'oklch(37.3% .0039  286.04)',
            '900': 'oklch(20.105% .0039 286.04)',  # = #161618, exakt
            '950': 'oklch(13% .00321 286.04)',
        },
    },

    # Startseite mit Auswertungen, wenn eine App sie registriert; sonst die
    # Liste der Apps.
    #
    # Als Pfad, weil dieses Modul vor dem Laden der Apps gelesen wird.
    # ``core.erweiterungen.startseite_ansicht`` liest zur Laufzeit, was in
    # ``AppConfig.ready()`` registriert wurde.
    'DASHBOARD_CALLBACK': 'core.erweiterungen.startseite_ansicht',

    # Tabs über Listen ("Offen", "Über Frist" über den Rechnungen), wie die
    # Seitenleiste von den Fachapps registriert (core/erweiterungen.py).
    'TABS': erweiterungen.reiter_liste,

    'SIDEBAR': {
        'show_search': False,

        # Aus, weil Unfold sonst unter der eigenen Gliederung alle Modelle
        # ein zweites Mal nach Apps sortiert anzeigt.
        'show_all_applications': False,

        # Die Fachapps registrieren ihre Einträge selbst
        # (core/erweiterungen.py). Die Gliederung folgt dem Arbeitsablauf. Wo
        # Einträge verschiedener Apps ineinander greifen (etwa "Nicht
        # abgerechnet" zwischen zwei Einträgen von ``erfassung``), bestimmt
        # ``rang`` die Reihenfolge, siehe die ``ready()``-Methoden von core,
        # faktura, erfassung und auswertung.
        #
        # Unfold ruft das Callable je Request auf; dann sind alle ``ready()``
        # gelaufen und die Registry vollständig.
        'navigation': erweiterungen.menue_abschnitte,
    },
}
