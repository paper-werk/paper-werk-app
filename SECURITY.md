# Sicherheit

## Lücken melden

Sicherheitslücken bitte nicht als öffentliches Issue melden, sondern über
„Report a vulnerability“ im Reiter **Security** dieses Repos. Die Meldung ist
nur für die Maintainer sichtbar. Nach der Behebung wird sie als Security
Advisory veröffentlicht, auf Wunsch mit Nennung des Melders.

## Unterstützte Versionen

Sicherheitskorrekturen gibt es für die neueste Version auf `main`. Betrifft
eine Lücke den Betrieb, erscheint die Korrektur als Patch-Release, ohne auf
das nächste reguläre Release zu warten.

## Prüfung der Abhängigkeiten

`./sicherheit.sh` prüft die Sperrdateien auf bekannte Lücken: `uv.lock` mit
pip-audit gegen die PyPI-Advisory-Datenbank, `package-lock.json` mit
`npm audit`.

- **Betrieb:** Python-Pakete ohne Dev-Gruppe, also der Inhalt des Images, und
  npm-Pakete ohne `devDependencies`. Ein Treffer lässt die Prüfung
  fehlschlagen.
- **Entwicklung:** pytest, Playwright, ruff, Tailwind. Treffer stehen im
  Bericht, blockieren aber nicht, weil diese Pakete nicht ausgeliefert
  werden.

Die Prüfung läuft wöchentlich in der CI gegen `main`
(`.github/workflows/sicherheit.yml`) und bei jeder Änderung an den
Sperrdateien. Zusätzlich sind Dependabot-Alerts aktiv.

Ein Release ist nur mit bestandener Prüfung möglich. Jedes Release ab v0.1.10
trägt den Bericht `sicherheit-<version>.md` als Anhang: ein datierter
Nachweis, welche Lücken beim Erscheinen bekannt waren.

Bewusst hingenommene Lücken stehen mit Begründung und Datum in
`sicherheit-ausnahmen.txt` und erscheinen im Bericht.

## Nicht abgedeckt

Das Docker-Image selbst, also die Debian-Pakete der Basis sowie Pango, Cairo
und HarfBuzz für WeasyPrint, wird derzeit nicht auf Lücken geprüft.
