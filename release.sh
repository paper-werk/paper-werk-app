#!/usr/bin/env sh
# Gibt den Stand von dev als Release aus, alle Schritte in einem Durchlauf.
#
#     ./release.sh <notes.md>            Release mit diesen Release-Notes
#     ./release.sh --probe               nur die Prüfungen, ändert nichts
#
# Die Version ist die aus pyproject.toml auf dev; sie wurde nach dem
# letzten Release schon hochgezählt. Die Notes werden vorher geschrieben;
# das Skript hängt die Zeile zur Sicherheitsprüfung an.
#
# Bricht ab, bevor es etwas ändert, wenn
#   - nicht auf dev, Arbeitsverzeichnis nicht sauber, dev nicht gleich
#     origin/dev oder main kein Vorfahr von dev,
#   - der Tag schon existiert,
#   - der CI-Lauf "Prüfen" für genau diesen Commit nicht grün ist,
#   - ./sicherheit.sh im Betrieb eine Lücke findet.
#   - Docker nicht läuft oder gh kein write:packages hat (Image-Push).
# Danach: main auf dev vorspulen, Tag, pushen, GitHub-Release mit dem
# Sicherheitsbericht als Anhang, Image aus dem Tag bauen und nach GHCR
# pushen, Vorgabe der Version in paper-werk anheben, dev auf die
# nächste Version, lokales App-Image der Installation dev neu bauen.

cd "$(dirname "$0")" || exit 1

halt() {
    echo
    echo "ABBRUCH: $*"
    exit 1
}

PROBE=0
NOTES=""
case "${1:-}" in
    --probe) PROBE=1 ;;
    "") halt "Aufruf: ./release.sh <notes.md>  oder  ./release.sh --probe" ;;
    *) NOTES=$1; [ -f "$NOTES" ] || halt "Notes-Datei $NOTES fehlt." ;;
esac

VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -n 1)
TAG="v$VERSION"
BERICHT="sicherheit-$VERSION.md"
IMAGE=ghcr.io/paper-werk/paper-werk-app
INSTALL=../paper-werk
VORLAGE=compose/docker-compose.yml

echo "== Release $VERSION: Vorbedingungen"
[ "$(git rev-parse --abbrev-ref HEAD)" = dev ] || halt "nicht auf dev."
[ -z "$(git status --porcelain)" ] || halt "Arbeitsverzeichnis nicht sauber."
git fetch -q --tags origin || halt "git fetch fehlgeschlagen."
[ "$(git rev-parse dev)" = "$(git rev-parse origin/dev)" ] \
    || halt "dev und origin/dev sind verschieden, erst pullen oder pushen."
git merge-base --is-ancestor origin/main dev \
    || halt "main hat Commits, die nicht in dev sind."
if git rev-parse -q --verify "refs/tags/$TAG" > /dev/null; then
    halt "Tag $TAG gibt es schon. Ist dev nach dem letzten Release hochgezählt?"
fi
COMMIT=$(git rev-parse HEAD)
echo "dev = $(git rev-parse --short HEAD), Tag $TAG ist frei."
docker info > /dev/null 2>&1 || halt "Docker läuft nicht; das Image wird beim Release gebaut."
gh auth status 2>&1 | grep -q "write:packages" \
    || halt "gh hat kein write:packages: gh auth refresh -s write:packages,read:packages"

echo "== CI-Lauf \"Prüfen\" für diesen Commit"
CI=$(gh run list --workflow pruefen.yml --branch dev --commit "$COMMIT" \
    --limit 1 --json status,conclusion -q '.[0] | "\(.status) \(.conclusion)"')
echo "${CI:-kein Lauf gefunden}"
[ "$CI" = "completed success" ] \
    || halt "CI für $COMMIT ist nicht grün (oder läuft noch)."

echo "== Sicherheitsprüfung"
PRUEFEN_WARTEN=0 ./sicherheit.sh \
    || halt "Sicherheitsprüfung nicht bestanden, Bericht: $BERICHT. Abhängigkeit aktualisieren oder begründet in sicherheit-ausnahmen.txt eintragen."

if [ "$PROBE" = 1 ]; then
    echo
    echo "Probe bestanden: $VERSION könnte ausgegeben werden."
    exit 0
fi

# Nächste Version: nur die letzte Stelle zählt hoch.
NAECHSTE=$(echo "$VERSION" | awk -F. '{ $NF = $NF + 1; print }' OFS=.)

echo
echo "Jetzt wird ausgegeben:"
echo "  main auf $(git rev-parse --short HEAD) vorspulen, Tag $TAG, pushen"
echo "  GitHub-Release $VERSION mit $NOTES und $BERICHT"
echo "  Image $IMAGE:$VERSION bauen und pushen, Vorgabe in paper-werk anheben"
echo "  dev auf $NAECHSTE hochzählen, pushen"
printf 'Zum Bestätigen die Version eintippen (%s): ' "$VERSION"
read -r antwort
[ "$antwort" = "$VERSION" ] || halt "nicht bestätigt, nichts geändert."

echo "== main und Tag"
git switch -q main && git merge -q --ff-only dev || halt "main ließ sich nicht vorspulen."
git tag "$TAG"
git push -q origin main "$TAG" || halt "Push von main/$TAG fehlgeschlagen; lokal stehen main und $TAG schon."

echo "== GitHub-Release"
NOTES_GANZ=$(mktemp)
trap 'rm -f "$NOTES_GANZ"' EXIT
{
    cat "$NOTES"
    echo
    echo "Sicherheitsprüfung der Abhängigkeiten: bestanden, Bericht im Anhang."
} > "$NOTES_GANZ"
gh release create "$TAG" --title "$VERSION" --notes-file "$NOTES_GANZ" --latest \
    || halt "GitHub-Release nicht angelegt. Tag ist gepusht; von Hand nachholen."
gh release upload "$TAG" "$BERICHT" \
    || halt "Bericht nicht angehängt: gh release upload $TAG $BERICHT"

# Das Image entsteht aus dem Tag, nicht aus dem Arbeitsverzeichnis: Dort
# liegen ignorierte Dateien (Sicherheitsbericht, lokale .env), die nicht alle
# in .dockerignore stehen. Ab hier bricht nichts mehr ab; das Release steht,
# es gibt nur Warnungen mit dem Befehl zum Nachholen.
echo "== Image $IMAGE:$VERSION"
QUELLE=$(mktemp -d)
trap 'rm -f "$NOTES_GANZ"; rm -rf "$QUELLE"' EXIT
IMAGE_DA=0
if git archive "$TAG" | tar -x -C "$QUELLE" \
    && docker build -q -t "$IMAGE:$VERSION" \
        --label "org.opencontainers.image.source=https://github.com/paper-werk/paper-werk-app" \
        --label "org.opencontainers.image.version=$VERSION" "$QUELLE" \
    && docker push -q "$IMAGE:$VERSION"; then
    IMAGE_DA=1
else
    echo "WARNUNG: Image nicht gebaut oder gepusht. Von Hand: git archive $TAG | tar -x -C <ordner>,"
    echo "  docker build -t $IMAGE:$VERSION <ordner> && docker push $IMAGE:$VERSION"
fi

# Neue Installationen laden das Image in der Version, die die Vorlage in
# paper-werk vorgibt. Angehoben wird nur, wenn das Image in der
# Registry liegt, und nur auf einem sauberen dev.
echo "== paper-werk: Vorgabe auf $VERSION"
if [ "$IMAGE_DA" = 1 ] && [ -f "$INSTALL/$VORLAGE" ]; then
    if [ "$(git -C "$INSTALL" rev-parse --abbrev-ref HEAD)" = dev ] \
        && [ -z "$(git -C "$INSTALL" status --porcelain)" ] \
        && git -C "$INSTALL" pull -q --ff-only \
        && sed -i "s/PAPER_WERK_APP_VERSION:-[0-9.]*}/PAPER_WERK_APP_VERSION:-$VERSION}/" "$INSTALL/$VORLAGE" \
        && git -C "$INSTALL" commit -q -m "App-Image $VERSION als Vorgabe (paper-werk-app $TAG)" -- "$VORLAGE" \
        && git -C "$INSTALL" push -q origin dev; then
        echo "dev von paper-werk gibt jetzt $VERSION vor."
    else
        echo "WARNUNG: Vorgabe nicht angehoben (paper-werk nicht auf sauberem dev?)."
        echo "  Von Hand in $INSTALL/$VORLAGE: PAPER_WERK_APP_VERSION:-$VERSION, committen, pushen."
    fi
else
    echo "WARNUNG: übersprungen, kein Image in der Registry oder $INSTALL fehlt."
fi

echo "== dev auf $NAECHSTE"
git switch -q dev
sed -i "s/^version = \"$VERSION\"/version = \"$NAECHSTE\"/" pyproject.toml
uv lock -q || halt "uv lock fehlgeschlagen."
git add pyproject.toml uv.lock
git commit -q -m "Version $NAECHSTE: dev zählt gleich nach dem Release hoch" \
    || halt "Commit des Hochzählens fehlgeschlagen."
git push -q origin dev || halt "Push von dev fehlgeschlagen."

# Ohne --build läuft das alte Image weiter und zeigt die alte Version.
echo "== App-Image der Installation dev neu bauen"
if [ -x "$INSTALL/paper-werk" ]; then
    (cd "$INSTALL" && ./paper-werk up dev --build paper-werk-app)         || echo "WARNUNG: Neubau fehlgeschlagen. Von Hand: cd $INSTALL && ./paper-werk up dev --build paper-werk-app"
else
    echo "WARNUNG: $INSTALL/paper-werk fehlt, Container nicht neu gebaut."
fi

echo
echo "Fertig: $VERSION ist ausgegeben, dev steht auf $NAECHSTE."
OFFEN=$(git branch --no-merged dev --format='%(refname:short)' | grep -v '^main$')
if [ -n "$OFFEN" ]; then
    echo "Laufende Branches, die das Hochzählen per cherry-pick bekommen:"
    echo "$OFFEN" | sed 's/^/  /'
    echo "  git cherry-pick $(git rev-parse --short dev)"
fi
