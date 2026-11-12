"""Schreibregeln für sichtbare Texte in Templates.

Gedankenstriche (– und —) sind im Fließtext nicht zulässig; Sätze werden
mit Punkt, Komma, Doppelpunkt oder Klammer gegliedert. Erlaubt bleibt der
Strich als Platzhalter einer leeren Zelle und zwischen zwei Werten
(„01.08.2026 – 31.08.2026“), weil dort kein Wort angrenzt.
"""

import re
from pathlib import Path

from django.conf import settings

#: Ein Strich mit Wörtern auf beiden Seiten, auch über einen Zeilenumbruch.
GEDANKENSTRICH = re.compile(
    r'[A-Za-zÄÖÜäöüß.,;:)]\s*(?:&ndash;|&mdash;|–|—)\s*[A-Za-zÄÖÜäöüß(&]')

#: Nicht sichtbarer Inhalt: Template-Kommentare, Skripte, Stile.
UNSICHTBAR = re.compile(
    r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}|\{#.*?#\}'
    r'|<script.*?</script>|<style.*?</style>',
    re.S)


def _templates():
    wurzel = Path(settings.BASE_DIR)
    for datei in sorted(wurzel.glob('**/templates/**/*.html')):
        teile = datei.relative_to(wurzel).parts
        if teile[0] in {'.venv', 'node_modules', 'staticfiles'}:
            continue
        yield datei


def test_keine_gedankenstriche_in_templates():
    funde = []
    for datei in _templates():
        inhalt = UNSICHTBAR.sub(
            lambda m: '\n' * m.group(0).count('\n'),
            datei.read_text(encoding='utf-8'))
        for treffer in GEDANKENSTRICH.finditer(inhalt):
            zeile = inhalt.count('\n', 0, treffer.start()) + 1
            funde.append(f'{datei.relative_to(settings.BASE_DIR)}:{zeile}: '
                         f'{" ".join(treffer.group(0).split())}')

    assert not funde, 'Gedankenstrich im Fließtext:\n' + '\n'.join(funde)
