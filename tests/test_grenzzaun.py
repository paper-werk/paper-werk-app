"""Trennung von Berechnung und Anzeige, als Test.

Die Seiten in ``auswertung/`` wählen aus, beschriften, formatieren und
bestimmen Balkenbreiten. Berechnet wird in den Services
(``faktura/services/``, ``erfassung/services/``), in
``auswertung/ergebnisse.py`` und ``controlling.py``. Eine Seite mit eigenem
``Sum(F('menge') * F('einzelpreis'))`` rundete nicht je Position und zeigte
einen anderen Betrag als die Rechnung.

Zulässig sind ``min`` und ``max`` für Balkenbreiten, ``len`` für Anzahlen
und das Summieren fertiger Beträge aus einem Service.
"""

import ast
from pathlib import Path

import pytest
from django.conf import settings

WURZEL = Path(settings.BASE_DIR)

#: Dateien, die nur anzeigen und nicht berechnen.
ANSICHTEN = [
    'auswertung/darstellung.py',
    'auswertung/dashboard.py',
    'auswertung/aufgaben.py',
    'auswertung/projektakte.py',
    'auswertung/auftragsakte.py',
    'auswertung/kundenakte.py',
    'auswertung/controllingseite.py',
    'auswertung/liegengeblieben.py',
]

#: Aufrufe, die in einer View eine eigene Berechnung beginnen.
#
# ``Sum``, ``Avg`` und ``Count`` bilden eine summierende Abfrage und damit
# eine zweite Stelle mit Rundungsregel. ``F`` kennzeichnet einen
# Datenbankausdruck über Spalten. ``quantize`` rundet und gehört nach
# ``core/rechnen.py``.
VERBOTENE_AUFRUFE = {'Sum', 'Avg', 'Count', 'F', 'quantize', 'Round'}

#: Ausnahmen, einzeln aufgeführt.
#
# ``_rechnungen`` in der Auftragsakte summiert je Beleg den Anteil dieses
# Auftrags über ``services.POSITIONSNETTO`` (die Rundungsregel der
# Anwendung). Die Kundenakte zählt Belege je Projekt, eine Anzahl.
ERLAUBT = {
    ('auswertung/auftragsakte.py', 'Sum'),
    ('auswertung/auftragsakte.py', 'DecimalField'),
    ('auswertung/kundenakte.py', 'Count'),
}


def _aufrufe(pfad: Path) -> list[tuple[str, int]]:
    """Alle aufgerufenen Namen einer Datei mit Zeile.

    Über den AST, weil ``Sum`` auch in "Summe" und in Kommentaren vorkommt;
    geprüft werden Aufrufe wie ``Sum(...)`` und ``x.quantize(...)``.
    """
    baum = ast.parse(pfad.read_text(encoding='utf-8'))
    gefunden = []
    for knoten in ast.walk(baum):
        if not isinstance(knoten, ast.Call):
            continue
        ziel = knoten.func
        name = (ziel.id if isinstance(ziel, ast.Name)
                else ziel.attr if isinstance(ziel, ast.Attribute)
                else None)
        if name:
            gefunden.append((name, knoten.lineno))
    return gefunden


@pytest.mark.parametrize('datei', ANSICHTEN)
def test_eine_ansicht_rechnet_nicht_selbst(datei):
    """Eine View enthält keine eigene Summe und keine eigene Rundung."""
    pfad = WURZEL / datei
    verstoesse = [
        f'{datei}:{zeile} ruft {name}()'
        for name, zeile in _aufrufe(pfad)
        if name in VERBOTENE_AUFRUFE and (datei, name) not in ERLAUBT
    ]

    assert not verstoesse, (
        'Hier wird in einer Ansicht gerechnet:\n  '
        + '\n  '.join(verstoesse)
        + '\n\nDie Rechnung gehört in einen Dienst oder in eine Auswertung '
          '(ergebnisse.py, controlling.py). Die Begründung steht im Kopf '
          'dieser Datei und bei ergebnisse.Auftragsstand.'
    )


def test_die_rundungsregel_steht_an_einer_stelle():
    """``quantize`` kommt im ganzen Produktivcode nur in ``core/rechnen.py`` vor.

    Python rundet ohne Modus zum geraden Nachbarn, auf einer Rechnung wird
    die Hälfte von der Null weg gerundet. Ein direkter Aufruf von
    ``quantize`` trifft diese Entscheidung erneut. Regression: neunzehn
    Stellen rundeten falsch.
    """
    wurzel = WURZEL
    treffer = []
    for pfad in wurzel.glob('*/**/*.py'):
        teile = pfad.relative_to(wurzel).parts
        if teile[0] not in {'faktura', 'erfassung', 'auswertung', 'paperwerk',
                            'core'}:
            continue
        if {'migrations', 'tests'} & set(teile) or pfad.name.startswith('test_'):
            continue
        if pfad.name in {'conftest.py',
                         'rechnen.py'}:
            continue
        for name, zeile in _aufrufe(pfad):
            if name == 'quantize':
                treffer.append(f'{pfad.relative_to(wurzel).as_posix()}:{zeile}')

    assert not treffer, (
        'quantize() wird außerhalb von core/rechnen.py aufgerufen:\n  '
        + '\n  '.join(treffer)
        + '\n\nStattdessen rechnen.auf_cent() oder rechnen.auf_stufe() '
          'benutzen; sonst steht die Rundungsregel wieder an zwei Stellen.'
    )


def _versionsfeld_genannt(pfad: Path) -> list[int]:
    """Zeilen mit direktem Zugriff auf die Spalte ``version``: Attribut
    (``beleg.version``), Keyword (``update(version=…)``) oder Feldname als
    String (``F('version')``, ``version__gt``). Modulpfade in Imports
    zählen nicht."""
    baum = ast.parse(pfad.read_text(encoding='utf-8'))
    zeilen = []
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Attribute) and knoten.attr == 'version':
            zeilen.append(knoten.lineno)
        elif isinstance(knoten, ast.keyword) and knoten.arg == 'version':
            zeilen.append(knoten.value.lineno)
        elif (isinstance(knoten, ast.Constant) and isinstance(knoten.value, str)
              and knoten.value.split('__')[0] == 'version'):
            zeilen.append(knoten.lineno)
    return zeilen


#: Dateien, die ``version`` in anderer Bedeutung verwenden.
#: ``core/version.py`` liest die App-Version aus ``pyproject.toml``.
VERSION_ANDERE_BEDEUTUNG = {'core/version.py'}


def test_die_versionsspalte_steht_an_einer_stelle():
    """Nur ``core/optimistic_locking.py`` greift auf ``version`` zu.

    Damit betrifft ein Wechsel zu ``django-concurrency`` eine Datei.
    Schreibzugriffe ohne ``save()`` rufen ``version_erhoehen`` auf.
    """
    treffer = []
    for pfad in WURZEL.glob('*/**/*.py'):
        relativ = pfad.relative_to(WURZEL).as_posix()
        teile = pfad.relative_to(WURZEL).parts
        if teile[0] not in {'faktura', 'erfassung', 'auswertung', 'paperwerk',
                            'core'}:
            continue
        if {'migrations', 'tests'} & set(teile) or pfad.name.startswith('test_'):
            continue
        if pfad.name in {'tests.py', 'conftest.py', 'optimistic_locking.py'}:
            continue
        if relativ in VERSION_ANDERE_BEDEUTUNG:
            continue
        treffer += [f'{relativ}:{zeile}'
                    for zeile in _versionsfeld_genannt(pfad)]

    assert not treffer, (
        'Zugriff auf die Spalte version außerhalb von '
        'core/optimistic_locking.py:\n  ' + '\n  '.join(treffer)
        + '\n\nStattdessen version_erhoehen() oder VersionAdminMixin.'
    )
