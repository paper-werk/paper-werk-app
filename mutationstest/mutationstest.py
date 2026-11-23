"""Mutationstest der Rechenmodule.

Baut je Lauf genau einen Fehler in ein Modul ein (Operator, Vergleich,
Konstante, Rundungsmodus, Bedingung) und führt die Tests aus, die die
geänderte Zeile laut Coverage ausführen. Schlägt kein Test fehl, hat die
Mutation überlebt: An dieser Stelle bliebe ein Rechenfehler unbemerkt.

    .venv/Scripts/python mutationstest/mutationstest.py core/rechnen.py faktura/services/summen.py

Konzept, Auswertung und Grenzen in ``mutationstest/README.md``.

Gearbeitet wird in einer Kopie des Repos (``--ziel``, Vorgabe im Temp-Ordner)
mit eigener Datenbank ``test_paperwerk_mutation``, damit Arbeitsordner und
gewöhnliche Testläufe unberührt bleiben. Die Läufe sind seriell.

Erster Schritt ist ein voller Testlauf mit ``--cov-context=test``; er liefert
je Zeile die ausführenden Tests und je Test die Laufzeit. Er wird nur
wiederholt, wenn ``--neu`` gesetzt ist. Ergebnisse stehen zeilenweise in
``ergebnis.jsonl`` in der Kopie; ein abgebrochener Lauf setzt dort fort.
Der Bericht ``bericht.md`` listet die überlebenden Mutationen.

Zeilen auf Modulebene (Konstanten, SQL-Ausdrücke) werden beim Import
ausgeführt, also ohne Testkontext. Für sie laufen alle Tests, die irgendeine
Zeile des Moduls ausführen.

Tests laufen je Mutation nach Laufzeit aufsteigend mit ``-x``: Getötete
Mutationen kosten meist Sekunden, überlebende die volle Laufzeit der
zugehörigen Tests.
"""

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

QUELLE = Path(__file__).resolve().parent.parent
PYTHON = QUELLE / '.venv' / 'Scripts' / 'python.exe'
if not PYTHON.exists():
    PYTHON = QUELLE / '.venv' / 'bin' / 'python'

DB_NAME = 'paperwerk_mutation'
ZEITEN_PLUGIN = '_mutation_zeiten'

# Pytest-Plugin für den Abdeckungslauf: Laufzeit je Test-ID.
ZEITEN_PLUGIN_CODE = '''
import json

_zeiten = {}

def pytest_runtest_logreport(report):
    _zeiten[report.nodeid] = _zeiten.get(report.nodeid, 0.0) + report.duration

def pytest_sessionfinish(session):
    with open('zeiten.json', 'w', encoding='utf-8') as f:
        json.dump(_zeiten, f)
'''


# ---------------------------------------------------------------------------
# Mutationen


BINOP = {
    ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult,
    ast.FloorDiv: ast.Div, ast.Mod: ast.FloorDiv, ast.Pow: ast.Mult,
}
VERGLEICH = {
    ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.In: ast.NotIn,
    ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is,
}
ZEICHEN = {
    ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.Div: '/', ast.FloorDiv: '//',
    ast.Mod: '%', ast.Pow: '**', ast.Lt: '<', ast.LtE: '<=', ast.Gt: '>',
    ast.GtE: '>=', ast.Eq: '==', ast.NotEq: '!=', ast.In: 'in',
    ast.NotIn: 'not in', ast.Is: 'is', ast.IsNot: 'is not',
    ast.And: 'and', ast.Or: 'or',
}
RUNDUNG = {
    'ROUND_HALF_UP': 'ROUND_HALF_EVEN', 'ROUND_HALF_EVEN': 'ROUND_HALF_UP',
    'ROUND_DOWN': 'ROUND_UP', 'ROUND_UP': 'ROUND_DOWN',
    'ROUND_FLOOR': 'ROUND_CEILING', 'ROUND_CEILING': 'ROUND_FLOOR',
}
FUNKTION = {'min': 'max', 'max': 'min'}


def _ausgenommen(baum):
    """IDs der Knoten, die nicht mutiert werden: Docstrings, Annotationen,
    f-Strings."""
    aus = set()

    def alles(knoten):
        for k in ast.walk(knoten):
            aus.add(id(k))

    for k in ast.walk(baum):
        if isinstance(k, (ast.Module, ast.ClassDef, ast.FunctionDef,
                          ast.AsyncFunctionDef)):
            if (k.body and isinstance(k.body[0], ast.Expr)
                    and isinstance(k.body[0].value, ast.Constant)
                    and isinstance(k.body[0].value.value, str)):
                alles(k.body[0])
        if isinstance(k, ast.ClassDef):
            for d in k.decorator_list:
                alles(d)
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if k.returns:
                alles(k.returns)
            for a in k.args.args + k.args.kwonlyargs + k.args.posonlyargs:
                if a.annotation:
                    alles(a.annotation)
            for d in k.decorator_list:
                alles(d)
        if isinstance(k, ast.AnnAssign):
            alles(k.annotation)
        if isinstance(k, ast.JoinedStr):
            alles(k)
    return aus


def _zahl_text(knoten, eltern):
    """Zahl als String im Aufruf ``Decimal('…')``, sonst None."""
    e = eltern.get(id(knoten))
    if not (isinstance(e, ast.Call) and isinstance(e.func, ast.Name)
            and e.func.id == 'Decimal' and knoten in e.args):
        return None
    try:
        return Decimal(knoten.value)
    except (InvalidOperation, TypeError):
        return None


def kandidaten(baum):
    """Liefert (Knotenindex, Variante, Zeile, Beschreibung) in fester
    Reihenfolge von ``ast.walk``. Die Variante wird in ``anwenden`` auf
    denselben Index eines frisch geparsten Baums angewandt."""
    aus = _ausgenommen(baum)
    eltern = {}
    for k in ast.walk(baum):
        for kind in ast.iter_child_nodes(k):
            eltern[id(kind)] = k

    for i, k in enumerate(ast.walk(baum)):
        if id(k) in aus:
            continue
        z = getattr(k, 'lineno', None)
        if isinstance(k, (ast.BinOp, ast.AugAssign)) and type(k.op) in BINOP:
            neu = BINOP[type(k.op)]
            yield i, 'op', z, f'{ZEICHEN[type(k.op)]} wird {ZEICHEN[neu]}'
        elif isinstance(k, ast.Compare):
            for j, op in enumerate(k.ops):
                if type(op) in VERGLEICH:
                    neu = VERGLEICH[type(op)]
                    yield i, ('vergleich', j), z, \
                        f'{ZEICHEN[type(op)]} wird {ZEICHEN[neu]}'
        elif isinstance(k, ast.BoolOp):
            neu = ast.Or if isinstance(k.op, ast.And) else ast.And
            yield i, 'bool', z, f'{ZEICHEN[type(k.op)]} wird {ZEICHEN[neu]}'
        elif isinstance(k, ast.UnaryOp) and isinstance(k.op, (ast.Not, ast.USub)):
            yield i, 'unaer', z, ('not entfällt' if isinstance(k.op, ast.Not)
                                  else 'Vorzeichen entfällt')
        elif isinstance(k, ast.Constant):
            v = k.value
            if isinstance(v, bool):
                yield i, 'bool_konst', z, f'{v} wird {not v}'
            elif isinstance(v, (int, float)):
                yield i, 'zahl', z, f'{v} wird {v + 1}'
            elif isinstance(v, str) and _zahl_text(k, eltern) is not None:
                yield i, 'dezimal', z, f"Decimal('{v}') wird Decimal('{_dezimal_neu(v)}')"
        elif isinstance(k, ast.Name) and k.id in RUNDUNG:
            yield i, 'rundung', z, f'{k.id} wird {RUNDUNG[k.id]}'
        elif isinstance(k, ast.Attribute) and k.attr in RUNDUNG:
            yield i, 'rundung', z, f'{k.attr} wird {RUNDUNG[k.attr]}'
        elif (isinstance(k, ast.Call) and isinstance(k.func, ast.Name)
              and k.func.id in FUNKTION):
            yield i, 'funktion', z, f'{k.func.id} wird {FUNKTION[k.func.id]}'
        elif (isinstance(k, ast.Call) and isinstance(k.func, ast.Name)
              and k.func.id == 'abs' and len(k.args) == 1):
            yield i, 'abs', z, 'abs() entfällt'
        elif (isinstance(k, (ast.If, ast.IfExp, ast.While))
              and not isinstance(k.test, (ast.Compare, ast.BoolOp, ast.UnaryOp))):
            yield i, 'bedingung', z, 'Bedingung verneint'


def _dezimal_neu(text):
    """Zehnfacher Wert mit anderem Exponenten. ``Decimal('0.10')`` statt
    ``Decimal('0.01')`` hätte denselben Exponenten und quantisierte gleich."""
    d = Decimal(text)
    return '1' if d == 0 else str((d * 10).normalize())


class _Ersetzen(ast.NodeTransformer):
    def __init__(self, ziel, neu):
        self.ziel, self.neu = ziel, neu

    def visit(self, knoten):
        if knoten is self.ziel:
            return self.neu
        return super().visit(knoten)


def anwenden(quelltext, index, variante):
    """Quelltext mit der Mutation ``variante`` am Knoten ``index``."""
    baum = ast.parse(quelltext)
    knoten = list(ast.walk(baum))[index]
    neu = None

    if variante == 'op':
        knoten.op = BINOP[type(knoten.op)]()
    elif isinstance(variante, tuple) and variante[0] == 'vergleich':
        knoten.ops[variante[1]] = VERGLEICH[type(knoten.ops[variante[1]])]()
    elif variante == 'bool':
        knoten.op = ast.Or() if isinstance(knoten.op, ast.And) else ast.And()
    elif variante == 'unaer':
        neu = knoten.operand
    elif variante == 'bool_konst':
        knoten.value = not knoten.value
    elif variante == 'zahl':
        knoten.value = knoten.value + 1
    elif variante == 'dezimal':
        knoten.value = _dezimal_neu(knoten.value)
    elif variante == 'rundung':
        if isinstance(knoten, ast.Name):
            knoten.id = RUNDUNG[knoten.id]
        else:
            knoten.attr = RUNDUNG[knoten.attr]
    elif variante == 'funktion':
        knoten.func.id = FUNKTION[knoten.func.id]
    elif variante == 'abs':
        neu = knoten.args[0]
    elif variante == 'bedingung':
        knoten.test = ast.UnaryOp(op=ast.Not(), operand=knoten.test)
    else:
        raise ValueError(variante)

    if neu is not None:
        baum = _Ersetzen(knoten, neu).visit(baum)
    ast.fix_missing_locations(baum)
    # Der Import für einen getauschten Rundungsmodus fehlt sonst.
    text = ast.unparse(baum)
    if variante == 'rundung' and isinstance(knoten, ast.Name):
        text = f'from decimal import {knoten.id}\n' + text
    return text


# ---------------------------------------------------------------------------
# Umgebung


def umgebung():
    env = dict(os.environ)
    url = None
    for zeile in (QUELLE / '.env').read_text(encoding='utf-8').splitlines():
        if zeile.startswith('DATABASE_URL='):
            url = zeile.split('=', 1)[1].strip()
    url = os.environ.get('DATABASE_URL', url)
    env['DATABASE_URL'] = re.sub(r'/[^/?]+(\?|$)', f'/{DB_NAME}\\1', url, count=1)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env.pop('COVERAGE_PROCESS_START', None)
    return env


def kopieren(ziel: Path):
    """Arbeitskopie aus den versionierten Dateien des Arbeitsstands und
    ``.env``. Ergebnisse und Abdeckung im Ziel bleiben erhalten."""
    dateien = subprocess.run(
        ['git', 'ls-files', '-z'], cwd=QUELLE, capture_output=True, check=True,
    ).stdout.decode().split('\0')
    for name in [d for d in dateien if d] + ['.env']:
        q = QUELLE / name
        if q.is_file():
            z = ziel / name
            z.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(q, z)
    (ziel / f'{ZEITEN_PLUGIN}.py').write_text(ZEITEN_PLUGIN_CODE, encoding='utf-8')


def abdecken(ziel: Path, env):
    """Voller Testlauf mit Testkontexten; erzeugt ``.coverage`` und
    ``zeiten.json``."""
    print('Abdeckungslauf über alle Tests ...', flush=True)
    start = time.monotonic()
    r = subprocess.run(
        [str(PYTHON), '-m', 'pytest', '-q', '-p', ZEITEN_PLUGIN, '-p',
         'no:cacheprovider', '--create-db', '--reuse-db', '--cov', '--cov-context=test',
         '--cov-report=', '-o', 'addopts='],
        cwd=ziel, env=env,
    )
    print(f'Abdeckungslauf: Exit {r.returncode}, '
          f'{(time.monotonic() - start) / 60:.1f} min', flush=True)
    if r.returncode != 0:
        sys.exit('Abdeckungslauf nicht grün; ohne grüne Basis kein Mutationstest.')


def tests_je_zeile(ziel: Path, modul: str):
    """{Zeile: {Test-ID}} und die Menge aller Tests des Moduls."""
    from coverage import CoverageData

    daten = CoverageData(basename=str(ziel / '.coverage'))
    daten.read()
    pfad = str((ziel / modul).resolve())
    datei = next((f for f in daten.measured_files()
                  if os.path.normcase(f) == os.path.normcase(pfad)), None)
    if datei is None:
        print(f'{modul}: nicht in der Abdeckung, fehlt in [tool.coverage.run]?')
        return {}, set()
    je_zeile, alle = {}, set()
    for zeile, kontexte in daten.contexts_by_lineno(datei).items():
        ids = {k.rsplit('|', 1)[0] for k in kontexte if k}
        je_zeile[zeile] = ids
        alle |= ids
    return je_zeile, alle


# ---------------------------------------------------------------------------
# Lauf


def schluessel(modul, quelltext, index, variante, beschreibung):
    h = hashlib.sha1(quelltext.encode()).hexdigest()[:10]
    return f'{modul}:{h}:{index}:{variante}:{beschreibung}'


def lauf(ziel: Path, env, modul, quelltext, mutiert, tests, zeiten):
    datei = ziel / modul
    pyc = datei.parent / '__pycache__'
    reihenfolge = sorted(tests, key=lambda t: zeiten.get(t, 60.0))
    (ziel / 'auswahl.txt').write_text('\n'.join(reihenfolge), encoding='utf-8')
    frist = 60 + 3 * sum(zeiten.get(t, 5.0) for t in reihenfolge)

    datei.write_text(mutiert, encoding='utf-8')
    # Eine alte .pyc mit gleicher Größe und Sekunde würde sonst geladen.
    shutil.rmtree(pyc, ignore_errors=True)
    start = time.monotonic()
    try:
        r = subprocess.run(
            [str(PYTHON), '-m', 'pytest', '-x', '-q', '-p', 'no:cacheprovider',
             '--reuse-db', '-o', 'addopts=', '@auswahl.txt'],
            cwd=ziel, env=env, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=frist,
        )
        code = r.returncode
        ausgabe = (r.stdout or '')[-1500:]
    except subprocess.TimeoutExpired:
        code, ausgabe = 'frist', ''
    finally:
        datei.write_text(quelltext, encoding='utf-8')
        shutil.rmtree(pyc, ignore_errors=True)

    status = {0: 'überlebt', 1: 'getötet', 5: 'keine Tests',
              'frist': 'getötet (Frist)'}.get(code, f'Fehler (Exit {code})')
    return status, time.monotonic() - start, ausgabe


def bericht(ziel: Path, ergebnisse):
    zeilen = ['# Mutationstest', '']
    je_modul = {}
    for e in ergebnisse:
        je_modul.setdefault(e['modul'], []).append(e)
    for modul, liste in je_modul.items():
        zaehlung = {}
        for e in liste:
            zaehlung[e['status']] = zaehlung.get(e['status'], 0) + 1
        zeilen.append(f'## {modul}')
        zeilen.append('')
        zeilen.append(', '.join(f'{v} {k}' for k, v in sorted(zaehlung.items())))
        zeilen.append('')
        rest = [e for e in liste if e['status'] in ('überlebt', 'nicht abgedeckt')]
        if rest:
            zeilen += ['| Zeile | Mutation | Status | Code |', '| --- | --- | --- | --- |']
            for e in sorted(rest, key=lambda e: e['zeile'] or 0):
                code = e['code'].replace('|', '\\|')
                zeilen.append(f"| {e['zeile']} | {e['beschreibung']} | "
                              f"{e['status']} | `{code}` |")
            zeilen.append('')
    (ziel / 'bericht.md').write_text('\n'.join(zeilen), encoding='utf-8')
    return ziel / 'bericht.md'


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('module', nargs='+', help='Pfade relativ zum Repo')
    p.add_argument('--ziel', type=Path,
                   default=Path(tempfile.gettempdir()) / 'paper-werk-mutation')
    p.add_argument('--neu', action='store_true',
                   help='Abdeckungslauf wiederholen')
    p.add_argument('--nur', type=int, help='höchstens so viele Mutationen')
    args = p.parse_args()

    ziel = args.ziel.resolve()
    ziel.mkdir(parents=True, exist_ok=True)
    env = umgebung()
    kopieren(ziel)
    if args.neu or not (ziel / '.coverage').exists():
        abdecken(ziel, env)
    zeiten = json.loads((ziel / 'zeiten.json').read_text(encoding='utf-8'))

    ergebnisdatei = ziel / 'ergebnis.jsonl'
    erledigt = {}
    if ergebnisdatei.exists():
        for z in ergebnisdatei.read_text(encoding='utf-8').splitlines():
            e = json.loads(z)
            erledigt[e['schluessel']] = e

    ergebnisse, anzahl = [], 0
    for modul in args.module:
        modul = modul.replace('\\', '/')
        quelltext = (ziel / modul).read_text(encoding='utf-8')
        zeilen = quelltext.splitlines()
        je_zeile, alle = tests_je_zeile(ziel, modul)
        liste = list(kandidaten(ast.parse(quelltext)))
        print(f'{modul}: {len(liste)} Mutationen, {len(alle)} Tests', flush=True)

        for n, (index, variante, zeile, beschreibung) in enumerate(liste, 1):
            s = schluessel(modul, quelltext, index, variante, beschreibung)
            if s in erledigt:
                ergebnisse.append(erledigt[s])
                continue
            if args.nur is not None and anzahl >= args.nur:
                break
            anzahl += 1
            code = zeilen[zeile - 1].strip() if zeile else ''
            tests = je_zeile.get(zeile)
            if tests is None:
                status, dauer, ausgabe = 'nicht abgedeckt', 0.0, ''
            else:
                status, dauer, ausgabe = lauf(
                    ziel, env, modul, quelltext,
                    anwenden(quelltext, index, variante),
                    tests or alle, zeiten)
            e = {'schluessel': s, 'modul': modul, 'zeile': zeile,
                 'beschreibung': beschreibung, 'code': code, 'status': status,
                 'tests': len(tests or alle) if tests is not None else 0,
                 'dauer': round(dauer, 1)}
            if status.startswith('Fehler'):
                e['ausgabe'] = ausgabe
            ergebnisse.append(e)
            with ergebnisdatei.open('a', encoding='utf-8') as f:
                f.write(json.dumps(e, ensure_ascii=False) + '\n')
            print(f'  [{n}/{len(liste)}] Z. {zeile} {beschreibung}: {status} '
                  f'({e["tests"]} Tests, {dauer:.0f} s)', flush=True)

    print(f'Bericht: {bericht(ziel, ergebnisse)}')


if __name__ == '__main__':
    main()
