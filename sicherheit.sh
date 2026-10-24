#!/usr/bin/env sh
# Prüft die Abhängigkeiten auf bekannte Sicherheitslücken und schreibt einen
# Bericht sicherheit-<version>.md. Dieselben Schritte laufen wöchentlich in
# der CI (.github/workflows/sicherheit.yml); beim Release hängt der Bericht
# am GitHub-Release (SECURITY.md).
#
#     ./sicherheit.sh
#
# Geprüft wird der Stand der Sperrdateien, nicht das, was gerade in .venv
# oder node_modules liegt:
#
#   Betrieb      uv.lock ohne Dev-Gruppe, also genau das, was ins
#                Docker-Image kommt, dazu die npm-Pakete ohne devDependencies.
#                Ein Treffer hier lässt das Skript fehlschlagen.
#   Entwicklung  pytest, playwright, ruff und Tailwind. Sie kommen nie zum
#                Kunden; Treffer stehen im Bericht, blockieren aber nicht.
#
# Bewusst hingenommene Lücken stehen in sicherheit-ausnahmen.txt, mit
# Begründung und Datum. Sie erscheinen im Bericht, nicht als Treffer.
#
# Braucht Netz (pip-audit fragt die PyPI-Advisory-Datenbank, npm audit die
# von GitHub), aber keine Datenbank und keinen Teststack.

cd "$(dirname "$0")" || exit 1

AUSNAHMEN=sicherheit-ausnahmen.txt
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -n 1)
BERICHT="sicherheit-$VERSION.md"
ARBEIT=$(mktemp -d)
trap 'rm -rf "$ARBEIT"' EXIT

# Erste Spalte jeder Zeile ohne # ist die ID der Lücke.
IGNORIEREN=""
if [ -f "$AUSNAHMEN" ]; then
    for id in $(sed -e 's/#.*//' "$AUSNAHMEN" | awk 'NF { print $1 }'); do
        IGNORIEREN="$IGNORIEREN --ignore-vuln $id"
    done
fi

# pip-audit über uvx: kein zusätzliches Paket im Projekt. Rückgabe 1 heißt
# Treffer oder Fehler, beides soll im Bericht sichtbar werden. UTF-8, weil
# die Beschreibungen Zeichen außerhalb von cp1252 enthalten (Windows).
pip_pruefen() {
    # $1: Ausgabedatei, Rest: Optionen für uv export
    ziel=$1
    shift
    uv export --frozen --no-emit-project --format requirements-txt "$@" \
        > "$ARBEIT/anforderungen.txt" || return 2
    # shellcheck disable=SC2086
    PYTHONIOENCODING=utf-8 uvx pip-audit --progress-spinner off --disable-pip --require-hashes \
        -r "$ARBEIT/anforderungen.txt" -f markdown --desc on $IGNORIEREN \
        > "$ziel" 2>&1
}

npm_pruefen() {
    # $1: Ausgabedatei, Rest: Optionen für npm audit
    ziel=$1
    shift
    npm audit "$@" > "$ziel" 2>&1
}

echo "== Python, Betrieb"
pip_pruefen "$ARBEIT/pip-betrieb.md" --no-dev
rc_pip_betrieb=$?
echo "== Python, Entwicklung"
pip_pruefen "$ARBEIT/pip-entwicklung.md" --only-dev
rc_pip_entwicklung=$?
echo "== npm, Betrieb"
npm_pruefen "$ARBEIT/npm-betrieb.txt" --omit=dev
rc_npm_betrieb=$?
echo "== npm, Entwicklung"
npm_pruefen "$ARBEIT/npm-entwicklung.txt"
rc_npm_entwicklung=$?

# $1: Rückgabe der Prüfung, $2: betrieb oder entwicklung. Nur im Betrieb ist
# ein Treffer ein Alarm; in der Entwicklung steht er als Hinweis da.
zustand() {
    if [ "$1" -eq 0 ]; then
        echo "keine bekannten Lücken"
    elif [ "$2" = betrieb ]; then
        echo "**Treffer oder Fehler** (Rückgabe $1)"
    else
        echo "Treffer oder Fehler (Rückgabe $1), Details unten"
    fi
}

if [ "$rc_pip_betrieb" -eq 0 ] && [ "$rc_npm_betrieb" -eq 0 ]; then
    ergebnis="bestanden: im Betrieb keine bekannten Lücken"
    rc=0
else
    ergebnis="NICHT bestanden: Treffer oder Fehler im Betrieb"
    rc=1
fi

{
    echo "# Sicherheitsprüfung paper-werk $VERSION"
    echo
    echo "- Geprüft am: $(date -u '+%Y-%m-%d %H:%M') UTC"
    echo "- Commit: $(git rev-parse --short HEAD 2>/dev/null)$(git diff --quiet HEAD -- uv.lock package-lock.json 2>/dev/null || echo ', Sperrdateien mit lokalen Änderungen')"
    echo "- Werkzeuge: $(uvx pip-audit --version 2>/dev/null), npm $(npm --version 2>/dev/null)"
    echo "- Ergebnis: **$ergebnis**"
    echo
    echo "| Bereich | Quelle | Ergebnis | Wirkung |"
    echo "|---|---|---|---|"
    echo "| Betrieb | uv.lock ohne Dev-Gruppe | $(zustand $rc_pip_betrieb betrieb) | entscheidet |"
    echo "| Betrieb | package-lock.json ohne devDependencies | $(zustand $rc_npm_betrieb betrieb) | entscheidet |"
    echo "| Entwicklung | uv.lock, Dev-Gruppe | $(zustand $rc_pip_entwicklung entwicklung) | nur Hinweis |"
    echo "| Entwicklung | package-lock.json, Bauwerkzeug Tailwind | $(zustand $rc_npm_entwicklung entwicklung) | nur Hinweis |"
    echo
    echo "Nur der Bereich Betrieb entscheidet über das Ergebnis. Die"
    echo "Entwicklungswerkzeuge laufen auf dem Entwicklungsrechner und in der"
    echo "CI, nie in einer Installation beim Kunden. Treffer dort werden mit"
    echo "dem nächsten Update der Werkzeuge behoben."
    echo
    echo "## Hingenommene Lücken"
    echo
    if [ -n "$IGNORIEREN" ]; then
        echo '```'
        sed -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d' "$AUSNAHMEN"
        echo '```'
    else
        echo "Keine."
    fi
    echo
    echo "## Python, Betrieb"
    echo
    cat "$ARBEIT/pip-betrieb.md"
    echo
    echo "## npm, Betrieb"
    echo
    echo '```'
    cat "$ARBEIT/npm-betrieb.txt"
    echo '```'
    echo
    echo "## Python, Entwicklung"
    echo
    cat "$ARBEIT/pip-entwicklung.md"
    echo
    echo "## npm, Entwicklung"
    echo
    echo '```'
    cat "$ARBEIT/npm-entwicklung.txt"
    echo '```'
} > "$BERICHT"

echo
echo "Ergebnis: $ergebnis. Bericht: $BERICHT"

# Doppelklick wie bei pruefen.sh: Fenster offen halten.
warten=${PRUEFEN_WARTEN:-}
if [ -z "$warten" ]; then
    if [ -t 0 ] && [ "${SHLVL:-1}" -le 1 ]; then warten=1; else warten=0; fi
fi
if [ "$warten" = 1 ]; then
    printf 'Enter zum Schließen ... '
    read -r _
fi

exit "$rc"
