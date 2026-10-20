"""Versionsnummer unten in der Seitenleiste.

Geprüft wird das gerenderte HTML, weil ein Test auf ``VERSION`` auch grün
bliebe, wenn die Nummer nie angezeigt würde (wie in ``test_marke.py``).
"""

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / 'pyproject.toml'


def test_die_seitenleiste_zeigt_die_version_aus_pyproject(buero, client):
    """Die Version aus pyproject.toml erscheint in der Seitenleiste.

    Der erwartete Wert wird direkt aus der Datei gelesen, damit der Test
    ``core.version`` nicht gegen sich selbst prüft.
    """
    with PYPROJECT.open('rb') as datei:
        erwartet = tomllib.load(datei)['project']['version']

    antwort = client.get('/admin/faktura/kontakt/')
    assert antwort.status_code == 200
    html = antwort.content.decode()

    # Nach Beginn der Seitenleiste und nach dem Benutzerblock, also unten in
    # der Leiste.
    beginn = html.index('id="nav-sidebar-inner"')
    benutzer = html.index('unfold_more', beginn)
    assert html.find(f'Version {erwartet}', benutzer) > benutzer
