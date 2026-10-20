"""Importrichtung zwischen den Apps, als Test.

::

    core  <--  faktura  <--  erfassung  <--  auswertung

Eine App importiert nur Apps links von ihr. ``paperwerk`` (Settings,
URLs) ist ausgenommen, weil das Projektpaket alle Apps einbindet.

Geprüft über ``ast``, damit lokale Imports in Methoden ebenso zählen wie
Imports am Dateianfang.
"""

import ast
from pathlib import Path

import pytest
from django.conf import settings

WURZEL = Path(settings.BASE_DIR)

#: Zulässige Imports je App.
ERLAUBT_FUER = {
    'core': set(),
    'faktura': {'core'},
    'erfassung': {'core', 'faktura'},
    'auswertung': {'core', 'faktura', 'erfassung'},
}

APPS = set(ERLAUBT_FUER)

#: Ausnahmen, einzeln aufgeführt; derzeit keine.
AUSNAHMEN: set[tuple[str, str]] = set()

#: Dateien, die nicht zur Produktionslogik der App gehören.
AUSGENOMMENE_NAMEN = {'conftest.py'}


def _importierte_apps(pfad: Path) -> set[str]:
    """Oberste Paketnamen, die diese Datei importiert, auch lokal."""
    baum = ast.parse(pfad.read_text(encoding='utf-8'))
    gefunden = set()
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Import):
            for alias in knoten.names:
                gefunden.add(alias.name.split('.')[0])
        elif isinstance(knoten, ast.ImportFrom):
            if knoten.module and knoten.level == 0:
                gefunden.add(knoten.module.split('.')[0])
    return gefunden & APPS


def _dateien(app: str):
    for pfad in (WURZEL / app).glob('**/*.py'):
        teile = pfad.relative_to(WURZEL).parts
        if {'migrations', 'tests'} & set(teile) or pfad.name.startswith('test_'):
            continue
        if pfad.name in AUSGENOMMENE_NAMEN:
            continue
        yield pfad


@pytest.mark.parametrize('app', sorted(APPS))
def test_eine_app_importiert_nur_was_unter_ihr_steht(app):
    """Jede App importiert nur zulässige Apps (Diagramm oben)."""
    erlaubt = ERLAUBT_FUER[app]
    verstoesse = []
    for pfad in _dateien(app):
        rel = pfad.relative_to(WURZEL).as_posix()
        for fremd in _importierte_apps(pfad) - {app} - erlaubt:
            if (rel, fremd) in AUSNAHMEN:
                continue
            verstoesse.append(f'{rel} importiert {fremd}')

    assert not verstoesse, (
        f'`{app}` importiert eine App, die nach dem Zielbild nicht unter '
        f'ihr steht:\n  ' + '\n  '.join(verstoesse)
        + '\n\nEntweder gehört der Import in die Ausnahmeliste (mit Namen '
          'und Begründung), oder er wird über eine Andockstelle in '
          '`core/erweiterungen.py` aufgelöst.'
    )
