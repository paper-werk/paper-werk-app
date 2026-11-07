"""Statische Prüfung der Workflow-Dateien in workflows/.

Prüft je Datei: gültiges JSON, eindeutige Knotennamen und -IDs, Verbindungen
nur zwischen vorhandenen Knoten, Credentials nur aus CREDENTIALS (feste IDs,
passend zu credentials.json.example), Fehler-Workflow gesetzt, Workflow-ID
eindeutig und in workflows.list eingetragen. Mit Node.js im Pfad wird der Code
jedes Code-Knotens kompiliert (Syntaxfehler, nicht Laufzeitfehler).

Aufruf aus der Wurzel des Repos::

    python werkzeuge/pruefen.py
"""

import json
import pathlib
import shutil
import subprocess
import sys

WURZEL = pathlib.Path(__file__).resolve().parent.parent

#: Credential-IDs, auf die Workflows verweisen dürfen.
CREDENTIALS = {
    'pwEreignisToken1': 'httpHeaderAuth',
    'pwApiBelege00001': 'httpHeaderAuth',
    'Xg7X6xVdrbSzUQ4o': 'smtp',
}

#: Kompiliert eine Liste von Code-Knoten wie n8n: als Rumpf einer async-Funktion.
NODE_PRUEFUNG = r"""
const vm = require('vm');
const eingabe = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const fehler = [];
for (const { datei, knoten, code } of eingabe) {
  try { new vm.Script('(async function () {\n' + code + '\n})'); }
  catch (e) { fehler.push(datei + ' / ' + knoten + ': ' + e.message); }
}
process.stdout.write(JSON.stringify(fehler));
"""


def main() -> int:
    fehler: list[str] = []
    liste = (WURZEL / 'workflows.list').read_text(encoding='utf-8')
    eingetragen = {zeile.split(';')[0].strip() for zeile in liste.splitlines()
                   if zeile.strip() and not zeile.lstrip().startswith('#')}
    ids: dict[str, str] = {}
    code_knoten = []

    for pfad in sorted((WURZEL / 'workflows').glob('*.json')):
        name = f'workflows/{pfad.name}'
        try:
            wf = json.loads(pfad.read_text(encoding='utf-8'))
        except json.JSONDecodeError as e:
            fehler.append(f'{name}: kein gültiges JSON ({e})')
            continue

        if wf.get('id') in ids:
            fehler.append(f'{name}: ID {wf.get("id")} auch in {ids[wf["id"]]}')
        ids[wf.get('id')] = name
        if name not in eingetragen:
            fehler.append(f'{name}: fehlt in workflows.list')
        if wf.get('settings', {}).get('errorWorkflow') != 'pwFehlerMelden01':
            fehler.append(f'{name}: settings.errorWorkflow ist nicht pwFehlerMelden01')

        namen = [k['name'] for k in wf['nodes']]
        knoten_ids = [k['id'] for k in wf['nodes']]
        for liste_, art in ((namen, 'Knotenname'), (knoten_ids, 'Knoten-ID')):
            doppelt = {x for x in liste_ if liste_.count(x) > 1}
            if doppelt:
                fehler.append(f'{name}: {art} doppelt: {", ".join(sorted(doppelt))}')

        for quelle, ausgaenge in wf['connections'].items():
            if quelle not in namen:
                fehler.append(f'{name}: Verbindung von unbekanntem Knoten "{quelle}"')
            for ausgang in ausgaenge.get('main', []):
                for ziel in ausgang:
                    if ziel['node'] not in namen:
                        fehler.append(f'{name}: Verbindung zu unbekanntem Knoten "{ziel["node"]}"')

        for k in wf['nodes']:
            for typ, cred in (k.get('credentials') or {}).items():
                if CREDENTIALS.get(cred.get('id')) != typ:
                    fehler.append(f'{name} / {k["name"]}: Credential {cred} unbekannt')
            if k['type'] == 'n8n-nodes-base.code':
                code_knoten.append({'datei': name, 'knoten': k['name'],
                                    'code': k['parameters']['jsCode']})

    for eintrag in sorted(eingetragen):
        if not (WURZEL / eintrag).exists():
            fehler.append(f'workflows.list: {eintrag} existiert nicht')

    node = shutil.which('node')
    if node:
        ergebnis = subprocess.run([node, '-e', NODE_PRUEFUNG], input=json.dumps(code_knoten),
                                  capture_output=True, text=True, encoding='utf-8', check=True)
        fehler += json.loads(ergebnis.stdout)
    else:
        print('Hinweis: node nicht gefunden, Code-Knoten nicht kompiliert.')

    for f in fehler:
        print(f)
    print(f'{len(ids)} Workflows, {len(code_knoten)} Code-Knoten, {len(fehler)} Fehler.')
    return 1 if fehler else 0


if __name__ == '__main__':
    sys.exit(main())
