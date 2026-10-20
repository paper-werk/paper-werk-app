"""Registry, über die Fachapps und Zusätze Menüeinträge, URLs, Endpunkte und
weitere Erweiterungen bereitstellen.

Jede App ruft in ``AppConfig.ready()`` Funktionen dieses Moduls auf.
``paperwerk/settings/unfold.py`` und ``paperwerk/urls.py`` lesen nur die
Registrierungen und importieren keine Fachapp.

**Reihenfolge.** Registriert wird in der Reihenfolge von ``INSTALLED_APPS``
(core, faktura, erfassung, auswertung, Zusätze). Für die Abschnitte der
Seitenleiste reicht das nicht: ``core`` registriert "Übersicht" und
"Verwaltung" in derselben ``ready()``, "Verwaltung" gehört aber ans Ende.
Abschnitte und Einträge haben deshalb einen ``rang`` (Vorgabe 0,
aufsteigend, stabil bei Gleichstand). Ein Abschnitt, den mehrere Apps
befüllen (etwa "Leistung" aus ``erfassung`` und ``auswertung``), entsteht
bei der ersten Registrierung und behält deren ``rang``. Ohne solche
Überschneidungen ist kein ``rang`` nötig.

**Keine Modell-Importe.** ``paperwerk/settings/unfold.py`` importiert das
Modul, während die Settings geladen werden, wie ``core/marke.py``. Es darf
deshalb nichts voraussetzen, was geladene Apps oder Modelle braucht.
"""

from collections.abc import Callable
from dataclasses import dataclass

#: Abschnitte der Seitenleiste, nach Titel; siehe ``menue()``.
_ABSCHNITTE: dict[str, dict] = {}

#: URL-Muster der Fachapps; siehe ``urls()``.
_URL_MUSTER: list = []

#: Tabs über Listen, nach Modell ("faktura.rechnung"); siehe ``reiter()``.
_REITER: dict[str, list[dict]] = {}

#: Lieferanten für die Schnellsuche (Strg+K); siehe ``suche()``.
_SUCHE: list[Callable] = []

#: Registrierte Startseiten-Funktion, falls eine App eine mitbringt.
_startseite: Callable | None = None

#: Detailaktionen an Belegen, nach Belegtyp; siehe ``belegaktion()``.
_BELEGAKTIONEN: dict[str, dict[str, tuple[Callable, Callable | None]]] = {}

#: Anlagen zum Versand mit dem Beleg, nach Belegtyp und Art; siehe
#: ``beleganlage()``.
_BELEGANLAGEN: dict[str, dict[str, 'Anlagenquelle']] = {}

#: Prüfungen, ob eine Position eine besondere Herkunft hat; siehe
#: ``positionsbezug()``.
_POSITIONSBEZUEGE: list[Callable] = []

#: URL-Funktionen der Akten (Projekt, Auftrag, Rechnung, Kunde), nach
#: Schlüssel; siehe ``akte_verweis()``.
_AKTEN: dict[str, Callable] = {}

#: App-Labels, deren Rechte die API-Selbstauskunft zeigt; siehe
#: ``fachliche_app()``.
_FACHLICHE_APPS: list[str] = []

#: DRF-Endpunkte unter ``/api/v1/``, nach Präfix; siehe ``api_endpoint()``.
#: Je Eintrag ``(viewset, basename, ersetzt, weitere)``.
_API_ENDPUNKTE: dict[str, tuple[type, str, bool, dict[str, str]]] = {}


def menue(titel: str, eintraege: list[dict], *, separator: bool = True,
          collapsible: bool = True, rang: int = 0) -> None:
    """Registriert Einträge für einen Abschnitt der Seitenleiste.

    ``eintraege`` sind Unfold-Einträge (``title``, ``icon``, ``link``,
    optional ``permission``) mit optionalem ``rang`` für die Sortierung im
    Abschnitt. Existiert der Abschnitt schon, werden nur Einträge ergänzt;
    ``separator``, ``collapsible`` und ``rang`` des Abschnitts bleiben wie
    bei der ersten Registrierung.
    """
    abschnitt = _ABSCHNITTE.setdefault(titel, {
        'title': titel,
        'separator': separator,
        'collapsible': collapsible,
        'rang': rang,
        'items': [],
    })
    abschnitt['items'].extend(eintraege)


def urls(muster: list) -> None:
    """Registriert URL-Muster für ``paperwerk/urls.py``."""
    _URL_MUSTER.extend(muster)


def startseite(ansicht: Callable) -> None:
    """Registriert die Funktion, die den Kontext der Admin-Startseite füllt.

    Signatur wie ``auswertung.dashboard.startseite``: ``(request, context)
    -> context``.
    """
    global _startseite
    _startseite = ansicht


def belegaktion(belegtyp: str, name: str, aktion: Callable,
                 hat_recht: Callable | None = None) -> None:
    """Registriert eine Detailaktion an einem Beleg, etwa "Erbrachte
    Leistungen hinzufügen" an der Rechnung.

    ``aktion`` ist eine mit ``@unfold_action`` dekorierte Funktion
    ``(self, request, object_id)`` mit der Signatur jeder Unfold-Detailaktion;
    ``self`` ist zur Laufzeit der ModelAdmin der Belegart. ``hat_recht``
    entspricht ``has_<name>_permission(self, request, object_id=None)``; ohne
    sie ist die Aktion immer erlaubt, vorbehaltlich ``permissions=[...]`` in
    ``aktion``.

    Die Admins der Belegarten (etwa ``faktura.admin.rechnung.RechnungAdmin``)
    holen Name und Funktionen über ``belegaktionen(self.typ)`` und setzen sie
    als Methoden. ``faktura`` braucht dadurch keinen Import der Apps, die auf
    ihr aufbauen.
    """
    _BELEGAKTIONEN.setdefault(belegtyp, {})[name] = (aktion, hat_recht)


def belegaktionen(belegtyp: str) -> dict[str, tuple[Callable, Callable | None]]:
    """Registrierte Detailaktionen eines Belegtyps, nach Name."""
    return dict(_BELEGAKTIONEN.get(belegtyp, {}))


@dataclass(frozen=True)
class Anlagenquelle:
    """Dokument, das eine Fachapp zu einem Beleg liefert, etwa den
    Leistungsnachweis zur Rechnung.

    ``hat_inhalt(beleg) -> bool``: ob es für den Beleg Inhalt gibt.
    ``pdf(beleg) -> bytes`` erzeugt das PDF bei jedem Aufruf neu; gespeichert
    wird nichts.
    """

    art: str
    titel: str
    hat_inhalt: Callable
    pdf: Callable


def beleganlage(belegtyp: str, quelle: Anlagenquelle) -> None:
    """Registriert eine Anlage.

    ``faktura`` bietet sie in der Versandmaske zum Anhängen an, ohne die
    Fachapp zu importieren.
    """
    _BELEGANLAGEN.setdefault(belegtyp, {})[quelle.art] = quelle


def beleganlagen(belegtyp: str) -> dict[str, Anlagenquelle]:
    """Registrierte Anlagen eines Belegtyps, nach Art."""
    return dict(_BELEGANLAGEN.get(belegtyp, {}))


def positionsbezug(pruefung: Callable) -> None:
    """Registriert eine Prüfung ``pruefung(position) -> bool``, ob eine
    Belegposition eine besondere Herkunft hat und etwa beim Duplizieren
    nicht kopiert werden darf.

    Ersetzt den Zugriff von ``faktura`` auf ``position.fremdleistungen``,
    einen Reverse-Accessor, den erst ``erfassung`` an ``Belegposition``
    anlegt. Ohne ``erfassung`` fehlte das Attribut, ohne dass ein
    Import-Test es bemerkt.
    """
    _POSITIONSBEZUEGE.append(pruefung)


def hat_besonderen_bezug(position) -> bool:
    """True, wenn eine registrierte Prüfung auf die Position zutrifft."""
    return any(pruefung(position) for pruefung in _POSITIONSBEZUEGE)


def akte_verweis(schluessel: str, verweis: Callable) -> None:
    """Registriert die URL-Funktion für die Akte eines Typs, etwa::

        akte_verweis('rechnung', lambda pk: reverse('rechnungsakte', args=[pk]))

    Für Anzeigespalten in ``faktura`` und ``erfassung``. Die URLs der Akten
    registriert ``auswertung`` (``auswertung/apps.py``); ein direkter Aufruf
    von ``reverse('rechnungsakte', ...)`` würfe ohne ``auswertung``
    ``NoReverseMatch``. Der CI-Lauf "nur Kern" prüft diesen Fall.
    """
    _AKTEN[schluessel] = verweis


def akte_url(schluessel: str, pk) -> str | None:
    """URL der Akte oder ``None``, wenn für den Typ keine registriert ist.

    Bei ``None`` zeigt die Anzeigespalte den Text ohne Link.
    """
    verweis = _AKTEN.get(schluessel)
    if verweis is None:
        return None
    return verweis(pk)


def fachliche_app(app_label: str) -> None:
    """Registriert ein App-Label als fachlich.

    Seine Rechte erscheinen in der API-Selbstauskunft
    (``core.schnittstelle.views.IchAnsicht``). Djangos eigene Rechte
    (admin, sessions, contenttypes) gehören nicht dazu; ``core`` registriert
    sich deshalb nicht.
    """
    if app_label not in _FACHLICHE_APPS:
        _FACHLICHE_APPS.append(app_label)


def fachliche_apps() -> list[str]:
    """Registrierte fachliche App-Labels."""
    return list(_FACHLICHE_APPS)


def api_endpoint(prefix: str, viewset: type, basename: str, *,
                 ersetzt: bool = False,
                 weitere: dict[str, str] | None = None) -> None:
    """Registriert einen DRF-Endpunkt für den Router unter ``/api/v1/``
    (``core/schnittstelle/urls.py``).

    So registriert etwa ``erfassung`` "eingangsrechnungen", ohne dass
    ``core`` Modell oder ViewSet importiert.

    **Ersetzen.** ``faktura`` liefert eine schmale Belegauskunft
    (``faktura/api.py``). Ein Zusatz kann mit ``ersetzt=True`` eine
    ausführlichere unter derselben URL registrieren; sie gilt unabhängig von
    der Reihenfolge der Apps. Ohne ``ersetzt`` ist ein doppelter Präfix ein
    Konfigurationsfehler, weil sonst eine App die andere ohne Meldung
    verdrängt.

    ``weitere`` ergänzt das Verzeichnis um Einträge
    ``{'schluessel': 'url-name'}`` ohne Namespace, etwa für eine Suche als
    ``@action`` am ViewSet.
    """
    from django.core.exceptions import ImproperlyConfigured

    vorhanden = _API_ENDPUNKTE.get(prefix)
    if vorhanden is not None:
        if vorhanden[2] and not ersetzt:
            # Der Ersatz ist schon registriert; die schmale Fassung entfällt.
            return
        if not vorhanden[2] and not ersetzt:
            raise ImproperlyConfigured(
                f'Der API-Endpunkt "{prefix}" ist doppelt angemeldet '
                f'({vorhanden[0].__name__} und {viewset.__name__}). Wer '
                f'eine Fassung bewusst ablöst, meldet sich mit ersetzt=True an.')
    _API_ENDPUNKTE[prefix] = (viewset, basename, ersetzt, dict(weitere or {}))


def api_endpunkte() -> list[tuple[str, type, str]]:
    """Registrierte DRF-Endpunkte als ``(prefix, viewset, basename)``.

    In Reihenfolge der Registrierung; ein Ersatz steht an der Stelle der
    ersten Registrierung.
    """
    return [(prefix, viewset, basename)
            for prefix, (viewset, basename, _, _) in _API_ENDPUNKTE.items()]


def api_verweise() -> dict[str, str]:
    """Zusätzliche Einträge des Verzeichnisses aus
    ``api_endpoint(weitere=...)``."""
    verweise: dict[str, str] = {}
    for _, _, _, weitere in _API_ENDPUNKTE.values():
        verweise.update(weitere)
    return verweise


def menue_abschnitte(request=None) -> list[dict]:
    """Abschnitte für ``UNFOLD['SIDEBAR']['navigation']``.

    Unfold ruft die Funktion je Request auf (``request`` bleibt ungenutzt).
    Abschnitte und Einträge werden nach ``rang`` sortiert; das Feld ``rang``
    selbst wird vor der Übergabe an Unfold entfernt.
    """
    abschnitte = sorted(_ABSCHNITTE.values(), key=lambda a: a['rang'])
    ergebnis = []
    for abschnitt in abschnitte:
        kopie = {k: v for k, v in abschnitt.items() if k != 'rang'}
        kopie['items'] = [
            {k: v for k, v in eintrag.items() if k != 'rang'}
            for eintrag in sorted(abschnitt['items'],
                                   key=lambda e: e.get('rang', 0))
        ]
        ergebnis.append(kopie)
    return ergebnis


def reiter(modell: str, eintraege: list[dict]) -> None:
    """Registriert Tabs über der Liste eines Modells, etwa "Offen" und
    "Über Frist" über den Rechnungen.

    ``modell`` wie ``str(Model._meta)`` ("faktura.rechnung"); die Einträge
    sind Unfold-Tabs (``title``, ``link``, optional ``active`` und
    ``permission``). ``paperwerk/settings/unfold.py`` liest nur
    ``reiter_liste``.
    """
    _REITER.setdefault(modell, []).extend(eintraege)


def reiter_liste(request=None) -> list[dict]:
    """Wert für ``UNFOLD['TABS']``, je Request aufgerufen."""
    return [{'models': [modell], 'items': list(eintraege)}
            for modell, eintraege in _REITER.items()]


def suche(lieferant: Callable) -> None:
    """Registriert einen Lieferanten für die Schnellsuche (Strg+K).

    ``lieferant(request, begriff) -> list[dict]`` mit ``titel``,
    ``beschreibung``, ``link`` und ``icon``. Der Lieferant prüft die Rechte
    selbst und liefert wenige Treffer je Art.
    """
    _SUCHE.append(lieferant)


def suchergebnisse(request, begriff: str) -> list:
    """Wert für ``UNFOLD['COMMAND']['search_callback']``: Treffer aller
    Lieferanten als Unfolds ``SearchResult``.

    Unfold durchsucht zusätzlich die Namen der Listen ("Rechnungen"). Die
    Suche über alle Modelle (``search_models``) ist abgeschaltet, weil sie
    jeden Treffer lud und auf das Änderungsformular verlinkte; die
    registrierten Lieferanten verlinken auf die Akte.
    """
    from unfold.dataclasses import SearchResult

    return [SearchResult(title=t['titel'], description=t['beschreibung'],
                         link=t['link'], icon=t.get('icon'))
            for lieferant in _SUCHE for t in lieferant(request, begriff)]


def registrierte_urls() -> list:
    """Registrierte URL-Muster für ``paperwerk/urls.py``."""
    return list(_URL_MUSTER)


def startseite_ansicht(request, context: dict) -> dict:
    """Wert für ``UNFOLD['DASHBOARD_CALLBACK']``.

    Setzt für Superuser den Hinweis auf ein ablaufendes HTTPS-Zertifikat und
    ruft dann die registrierte Startseite auf. Der Hinweis liegt in ``core``,
    damit er auch ohne ``auswertung`` erscheint; der CI-Lauf "nur Kern"
    prüft das.

    Ohne registrierte Startseite fehlt ``zeige_auswertung`` im Kontext, und
    ``templates/admin/index.html`` zeigt die Liste der Anwendungen wie der
    Django-Admin.
    """
    from core import zertifikat

    if request.user.is_superuser:
        ablauf = zertifikat.ablauf()
        context['zertifikat'] = ablauf if ablauf and ablauf.bald else None

    if _startseite is not None:
        return _startseite(request, context)
    return context
