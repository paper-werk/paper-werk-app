#!/usr/bin/env sh
# Der Prüflauf vor einem Merge, mit denselben Schritten wie in der CI
# (.github/workflows/pruefen.yml).
#
#     ./pruefen.sh                  alles
#     ./pruefen.sh faktura/         pytest nur über ein Verzeichnis
#
# Braucht die Datenbank des Teststacks (siehe README, Entwicklung).
#
# Am Ende steht eine Zeile "Ergebnis: ...", die ganze Ausgabe zusätzlich in
# pruefen.log. Per Doppelklick gestartet, wartet das Fenster auf Enter -
# sonst schließt es sich, bevor man das Ergebnis lesen kann. Aus einem
# offenen Terminal läuft es ohne Pause durch; PRUEFEN_WARTEN=1 erzwingt die
# Pause, PRUEFEN_WARTEN=0 verhindert sie.

cd "$(dirname "$0")" || exit 1

PROTOKOLL=pruefen.log
STAND=$(mktemp)
# Farbe nur auf dem Bildschirm: Durch tee hielte pytest sich sonst für
# umgeleitet. Im Protokoll werden die Farbcodes wieder entfernt.
if [ -t 1 ]; then FARBE=yes; else FARBE=no; fi
ESC=$(printf '\033')

schritt() {
    echo "$1" > "$STAND"
    shift
    echo
    echo "== $*"
    "$@"
}

ablauf() {
    set -e
    schritt "Ruff" uv run ruff check .
    schritt "Django-Prüfung" uv run python manage.py check
    schritt "Migrationen" uv run python manage.py makemigrations --check --dry-run
    schritt "Tests" uv run pytest -q --color="$FARBE" "$@"
    echo "fertig" > "$STAND"
}

# Der Rückgabewert des Ablaufs, nicht der von tee.
{ ( ablauf "$@" ); echo $? > "$STAND.rc"; } 2>&1 | tee "$PROTOKOLL.roh"
sed "s/${ESC}\[[0-9;]*m//g" "$PROTOKOLL.roh" > "$PROTOKOLL"
rm -f "$PROTOKOLL.roh"
rc=$(cat "$STAND.rc" 2>/dev/null || echo 1)
zuletzt=$(cat "$STAND" 2>/dev/null)
rm -f "$STAND" "$STAND.rc"

if [ "$rc" -eq 0 ]; then
    ergebnis="Ergebnis: alles grün. Protokoll: $PROTOKOLL"
else
    ergebnis="Ergebnis: FEHLER in Schritt \"$zuletzt\" (Rückgabe $rc). Protokoll: $PROTOKOLL"
fi
echo
echo "$ergebnis"
printf '\n%s\n' "$ergebnis" >> "$PROTOKOLL"

# Doppelklick erkennt man daran, dass keine Shell darüber liegt.
warten=${PRUEFEN_WARTEN:-}
if [ -z "$warten" ]; then
    if [ -t 0 ] && [ "${SHLVL:-1}" -le 1 ]; then warten=1; else warten=0; fi
fi
if [ "$warten" = 1 ]; then
    printf 'Enter zum Schließen ... '
    read -r _
fi

exit "$rc"
