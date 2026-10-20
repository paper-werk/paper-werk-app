"""Jede CSS-Klasse der eigenen Templates ist definiert.

django-unfold liefert ein kompiliertes Tailwind mit nur den Klassen, die
Unfold selbst verwendet. Eine eigene Klasse wie ``h-2.5`` ist dort nicht
definiert und hat ohne Fehlermeldung keine Wirkung; das Element bleibt
0 × 0 Pixel groß.

Geprüft wird, dass jede Klasse in den eigenen Templates im Unfold-CSS oder
in den eigenen Stylesheets steht, vor allem im eigenen Tailwind-Build
(``paperwerk.css``).
"""

import re
from pathlib import Path

import pytest
import unfold
from django.conf import settings

#: Eigene Templates; die von Unfold sind ausgenommen.
VORLAGEN = [
    'auswertung/templates/admin/controlling.html',
    'templates/admin/index.html',
    'auswertung/templates/admin/liegengeblieben.html',
    'auswertung/templates/admin/faktura/projektakte.html',
    'auswertung/templates/admin/faktura/auftragsakte.html',
    'auswertung/templates/admin/faktura/kundenakte.html',
    'faktura/templates/admin/faktura/belegsumme.html',
    'templates/admin/auth/user/change_password.html',
    'templates/admin/login.html',
    'templates/admin/sso_kein_zugang.html',
    'templates/admin/sso_nicht_erreichbar.html',
    'templates/socialaccount/authentication_error.html',
    'templates/socialaccount/login_cancelled.html',
    'templates/admin/faktura/ansprechpartner_hinzufuegen.html',
    'templates/admin/_kennzahl.html',
    'auswertung/templates/admin/_saeulen.html',
    'auswertung/templates/admin/faktura/rechnungsakte.html',
    'hilfe/templates/hilfe/seite.html',
    'hilfe/templates/hilfe/_verweis.html',
    'templates/unfold/helpers/userlinks.html',
    # Ohne die Templates der Belegpositionen (templates/unfold/helpers/
    # edit_inline/), weil ihre übrigen Klassen von Unfold stammen oder
    # Selektoren für JavaScript mit Template-Variablen sind
    # ("field-{{ name }}"). Ihre pw-Klassen prüft der letzte Test.
]

#: Quellen von CSS-Regeln.
STILQUELLEN = [
    Path(unfold.__file__).parent / 'static/unfold/css/styles.css',
    # Eigener Tailwind-Build (stile/eingang.css, ``npm run css``), der jede
    # verwendete Tailwind-Klasse erzeugt. Schlägt der Test fehl, fehlt der
    # Build oder die Klasse existiert in Tailwind nicht (Tippfehler).
    'core/static/core/css/paperwerk.css',
    'faktura/static/faktura/css/faktura_admin.css',
    'templates/admin/_eigene_stile.html',
]

#: Klassen ohne CSS-Regel: Selektoren für JavaScript und Symbolschrift.
KEINE_STILKLASSEN = (
    'chart',              # findet Unfolds app.js
    'material-symbols-outlined',   # die Symbolschrift
    'pw-',                # eigene, in _eigene_stile.html
)


def _stiltexte() -> str:
    wurzel = Path(settings.BASE_DIR)
    texte = []
    for pfad in STILQUELLEN:
        datei = wurzel / pfad
        # Fehlschlagen bei fehlender Quelle, weil sonst jede Klasse
        # "undefiniert" wäre oder der Test wirkungslos.
        texte.append(datei.read_text(encoding='utf-8'))
    return '\n'.join(texte)


def _klassen_der_vorlage(pfad: Path) -> set[str]:
    """Alle Klassennamen aus den ``class="..."``-Angaben.

    Template-Tags werden zuvor entfernt, weil sonst ``{% if x %}`` als
    Klassenname erschiene.
    """
    text = pfad.read_text(encoding='utf-8')
    klassen = set()
    for treffer in re.findall(r'class="([^"]*)"', text):
        ohne_logik = re.sub(r'\{[%{].*?[%}]\}', ' ', treffer, flags=re.S)
        for klasse in ohne_logik.split():
            if klasse and not klasse.startswith(KEINE_STILKLASSEN):
                klassen.add(klasse)
    return klassen


def _ist_definiert(klasse: str, stil: str) -> bool:
    """Ob die Klasse als Selektor in einer der CSS-Quellen steht.

    Tailwind escaped Sonderzeichen im Selektor: ``h-2.5`` wird
    ``.h-2\\.5``, ``dark:bg-x`` wird ``.dark\\:bg-x``, ``lg:w-2/5`` wird
    ``.lg\\:w-2\\/5``. Geprüft wird die volle Klasse mit Präfix, weil
    ``dark:text-x`` im CSS nicht als ``.text-x`` steht.
    """
    maskiert = (klasse.replace('.', r'\.')
                .replace(':', r'\:')
                .replace('/', r'\/')
                .replace('[', r'\[')
                .replace(']', r'\]')
                .replace('&', r'\&'))
    return bool(re.search(
        r'(?<![\w\\-])\.' + re.escape(maskiert) + r'(?![\w-])', stil))


@pytest.mark.parametrize('vorlage', VORLAGEN)
def test_jede_klasse_ist_definiert(vorlage):
    """Jede Klasse ist definiert, je Template einzeln, damit die Meldung
    das Template nennt."""
    datei = Path(settings.BASE_DIR) / vorlage
    assert datei.exists(), f'{vorlage} gibt es nicht; Liste nachziehen'

    stil = _stiltexte()
    fehlend = sorted(k for k in _klassen_der_vorlage(datei)
                     if not _ist_definiert(k, stil))

    assert not fehlend, (
        f'{vorlage} benutzt Klassen, die weder Unfold noch unsere eigenen '
        f'Ergänzungen kennen; sie wirken nicht: {fehlend}'
    )


def test_der_pruefer_findet_eine_erfundene_klasse():
    """Gegenprobe: Eine erfundene Klasse wird erkannt, weil die Prüfung auf
    einer Regex über escapte Selektoren beruht."""
    stil = _stiltexte()

    assert not _ist_definiert('gibt-es-nicht-4711', stil)
    # Gegenrichtung: eine sicher vorhandene Klasse.
    assert _ist_definiert('flex', stil)


def test_die_farbpunkte_der_legenden_haben_eine_groesse():
    """Die Farbpunkte der Legenden haben eine Größe.

    Regression: ``h-2.5`` und ``w-2.5`` fehlen im Unfold-CSS; die Punkte
    blieben 0 × 0 Pixel groß.
    """
    stil = _stiltexte()

    for klasse in ('h-2.5', 'w-2.5', 'size-2.5', 'h-0.5'):
        assert _ist_definiert(klasse, stil), (
            f'{klasse} ist nirgends definiert; Farbpunkte bleiben unsichtbar')


#: Templates der Belegpositionen mit eigenen pw-Klassen.
POSITIONSVORLAGEN = [
    'templates/unfold/helpers/edit_inline/paperwerk_zusatzzeile.html',
    'templates/unfold/helpers/edit_inline/paperwerk_zusatzfelder.html',
    'templates/unfold/helpers/edit_inline/tabular_heading.html',
]


@pytest.mark.parametrize('vorlage', POSITIONSVORLAGEN)
def test_die_pw_klassen_der_positionen_stehen_im_eigenen_css(vorlage):
    """Die pw-Klassen der Positionen stehen in faktura_admin.css.

    Oben ausgenommen, weil die pw-Klassen der Startseite in
    _eigene_stile.html stehen; eine fehlende Klasse der Positionen
    zerstörte ohne Meldung das Layout der Zeile."""
    wurzel = Path(settings.BASE_DIR)
    css = (wurzel / 'faktura/static/faktura/css/faktura_admin.css'
           ).read_text(encoding='utf-8')
    text = (wurzel / vorlage).read_text(encoding='utf-8')
    klassen = {k for treffer in re.findall(r'class="([^"]*)"', text)
               for k in treffer.split() if k.startswith('pw-')}

    assert klassen, f'{vorlage} hat keine pw-Klassen mehr; Liste nachziehen'
    # Ohne _ist_definiert(), weil es die Klasse am Anfang eines Selektors
    # verlangt und sie hier auch nach dem Element steht ("td.pw-rueckgrat").
    fehlend = sorted(k for k in klassen
                     if not re.search(r'\.' + re.escape(k) + r'(?![\w-])', css))
    assert not fehlend, f'{vorlage}: nicht in faktura_admin.css: {fehlend}'
