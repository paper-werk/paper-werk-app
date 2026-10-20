"""Hilfsfunktionen zum Auslesen der Änderungsliste in Tests.

Eine Suche im ganzen HTML trifft auch Summenzeile und Filterleiste:
``'0:00' not in inhalt`` schlägt fehl, weil die Summenzeile ``0:00``
enthält, und ``'Pauschale' not in inhalt``, weil "Pauschale" im Filter
"Art der Leistung" steht. Die Funktionen lesen deshalb Tabellenzellen.

Einfache Funktionen ohne Fixtures, damit jede App sie importieren kann.

Gesucht wird der Klassenname mit Wortgrenze, weil Unfold weitere Klassen
anhängt (``class="field-beschreibung align-middle border-t ..."``); eine
Prüfung auf das schließende Anführungszeichen fände keine Zelle.
"""

import json
import re


def json_daten(html: str, kennung: str):
    """Inhalt eines ``{{ ... |json_script:"kennung" }}``-Blocks.

    Eine Suche nach ``"in_rechnung"`` im ganzen HTML träfe auch die
    Aktionsauswahl (``<option value="in_rechnung">``).
    """
    treffer = re.search(
        rf'<script id="{kennung}" type="application/json">(.*?)</script>',
        html, re.S)
    return json.loads(treffer.group(1)) if treffer else None


def zelle(html: str, feld: str) -> str:
    """Inhalt der ersten Zelle einer Spalte."""
    treffer = re.search(rf'<t[dh] class="field-{feld}[\s"][^>]*>(.*?)</t[dh]>',
                        html, re.S)
    return treffer.group(1).strip() if treffer else ''


def spalte(html: str, feld: str) -> list[str]:
    """Alle Zellen einer Spalte in der Reihenfolge der Zeilen, also nach
    Sortierung, Pagination und Template."""
    return [t.strip() for t in re.findall(
        rf'<td class="field-{feld}[\s"][^>]*>(.*?)</td>', html, re.S)]
