"""Versionsnummer der Anwendung, angezeigt unten in der Seitenleiste.

Einzige Quelle ist ``version`` in ``pyproject.toml``.

Gelesen wird ``pyproject.toml`` direkt, weil ``importlib.metadata`` hier
nichts findet: Das Projekt hat kein ``[build-system]`` (Begründung am Ende
von ``pyproject.toml``) und wird nie als Paket installiert. Im Image kopiert
das ``Dockerfile`` die Datei vor dem ``uv sync``.

Gelesen wird einmal beim Import. Fehlt die Datei, schlägt der Start fehl,
damit das schon beim Bauen des Images auffällt.
"""

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parent.parent / 'pyproject.toml'

with _PYPROJECT.open('rb') as _datei:
    VERSION: str = tomllib.load(_datei)['project']['version']


def version(request):
    """Kontextprozessor: die Versionsnummer für jede Vorlage."""
    return {'app_version': VERSION}
