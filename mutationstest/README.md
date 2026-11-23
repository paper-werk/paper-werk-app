# Mutationstest

`mutationstest.py` prüft, ob die Testsuite Rechenfehler in den Rechenmodulen
erkennt. Das Werkzeug wird von Hand gestartet und gehört weder zum
gewöhnlichen Testlauf noch zur CI.

## Grundsatz

Die Abdeckung zeigt, welche Zeilen ein Test ausführt, aber nicht, ob er ein
falsches Ergebnis bemerkt. Der Mutationstest baut deshalb je Lauf genau einen
Fehler in ein Modul ein, die Mutation, und führt die Tests aus, die die
geänderte Zeile ausführen. Schlägt einer fehl, ist die Mutation getötet.
Bleiben alle grün, hat sie überlebt: An dieser Stelle bliebe ein Rechenfehler
unbemerkt.

## Aufruf

```
.venv/Scripts/python mutationstest/mutationstest.py [--neu] [--nur N] [--ziel DIR] MODUL ...
```

| Option | Wirkung |
| --- | --- |
| `MODUL` | Pfad relativ zum Repo, etwa `faktura/services/summen.py` |
| `--neu` | Abdeckungslauf wiederholen; nötig nach Änderungen an Tests oder Code außerhalb der Module |
| `--nur N` | höchstens N Mutationen ausführen |
| `--ziel DIR` | Arbeitskopie, Vorgabe `%TEMP%/paper-werk-mutation` |

Voraussetzungen sind die `.venv` des Repos und die Datenbank des Teststacks
wie beim gewöhnlichen Testlauf. Der Abdeckungslauf über alle Tests dauert so
lange wie ein voller Testlauf. Danach braucht eine Mutation zwischen wenigen
Sekunden und einigen Minuten, abhängig von der Zahl der Tests, die die Zeile
ausführen. Für `core/rechnen.py` und die fünf Rechenmodule in
`faktura/services/` (`summen`, `abschlaege`, `kumuliert`, `abzuege`,
`korrektur`) sind es zusammen etwa drei Stunden.

## Abgrenzung zum Testlauf

- pytest sammelt die Datei nicht, weil sie nicht `test_*.py` heißt und der
  Ordner nicht in `testpaths` steht (`pyproject.toml`).
- `pruefen.sh` und die CI rufen das Werkzeug nicht auf.
- `.dockerignore` schließt den Ordner vom Image aus.

## Ablauf

1. **Arbeitskopie.** Kopiert werden die versionierten Dateien (`git ls-files`)
   und `.env` in das Zielverzeichnis. Gearbeitet wird mit der Datenbank
   `test_paperwerk_mutation`, damit Arbeitsordner und gewöhnliche Testläufe
   unberührt bleiben.
2. **Abdeckungslauf.** Ein voller Testlauf mit `--cov-context=test` liefert je
   Zeile die Tests, die sie ausführen, und je Test die Laufzeit
   (`zeiten.json`). Ohne grünen Lauf bricht das Werkzeug ab.
3. **Mutationen.** Je Mutation wird das Modul in der Kopie geändert und
   `__pycache__` gelöscht. Danach laufen die zugehörigen Tests nach Laufzeit
   aufsteigend mit `-x`. Die Frist beträgt 60 s plus das Dreifache der
   gemessenen Laufzeit. Zeilen auf Modulebene (Konstanten, SQL-Ausdrücke)
   laufen beim Import ohne Testkontext; für sie laufen alle Tests des Moduls.
4. **Ergebnis.** Jede Mutation wird sofort als Zeile in `ergebnis.jsonl`
   geschrieben. Ein abgebrochener Lauf setzt dort fort. Der Schlüssel enthält
   einen Hash des Modulquelltexts, damit nach einer Änderung am Modul alle
   seine Mutationen neu laufen. `bericht.md` listet je Modul die Zählung und
   die überlebenden Mutationen.

## Mutationen

| Art | Änderung |
| --- | --- |
| Arithmetik | `+` und `-`, `*` und `/` gegeneinander |
| Vergleich | `<` und `<=`, `>` und `>=`, `==` und `!=`, `in` und `not in`, `is` und `is not` |
| Logik | `and` und `or`; `not` entfällt |
| Vorzeichen | unäres `-` entfällt |
| Konstante | `True` und `False`; Ganzzahl plus 1; `Decimal('x')` zehnfach mit anderem Exponenten |
| Rundung | `ROUND_HALF_UP` und `ROUND_HALF_EVEN`, `ROUND_UP` und `ROUND_DOWN`, `ROUND_CEILING` und `ROUND_FLOOR` |
| Funktion | `min` und `max`; `abs()` entfällt |
| Bedingung | Bedingung ohne Vergleich oder Logik wird verneint |

Ausgenommen sind Docstrings, Annotationen, f-Strings und Decorators, weil
eine Änderung dort keinen Rechenfehler darstellt.

`Decimal('0.01')` wird zu `Decimal('0.1')`. Mit `Decimal('0.10')` bliebe der
Exponent gleich, und `quantize` rundete unverändert.

## Status

| Status | Bedeutung |
| --- | --- |
| getötet | ein Test schlägt fehl |
| getötet (Frist) | Frist überschritten |
| überlebt | alle Tests grün |
| nicht abgedeckt | kein Test führt die Zeile aus |
| keine Tests | pytest hat keinen der ausgewählten Tests gefunden |
| Fehler (Exit n) | pytest mit anderem Exit-Code, Ausgabe in `ergebnis.jsonl` |

## Auswertung

Eine überlebende Mutation gehört in eine von drei Gruppen:

- **Äquivalent.** Die Mutation ändert kein Ergebnis, etwa ein Vorgabewert, der
  nie greift, ein Wert, den späterer Code neu setzt, oder `output_field` eines
  `DecimalField`, das PostgreSQL nicht auswertet. Kein Test, der sie erzwingt.
  Ist der Code tot, wird er entfernt.
- **Grenzwert.** Es fehlt der Test genau auf der Grenze, etwa `<= 0` gegen
  `< 0` oder die Fälligkeit am selben Tag.
- **Kombination.** Kein Test trennt die Bedingungen einer `and`- oder
  `or`-Verknüpfung.

Für Grenzwerte und Kombinationen, die fachlich vorkommen, kommt ein Test
dazu. Jeder neue Test wird gegengeprüft: Mutation von Hand einspielen, Test
muss rot werden, Mutation zurücknehmen.

Das Ergebnis ist eine Liste zur Durchsicht und hat keinen Schwellenwert, weil
äquivalente Mutationen nur von Hand zu erkennen sind.

## Verworfene Alternativen

- **mutmut.** Version 3 braucht `fork`, das unter Windows fehlt. Die
  parallelen Worker teilten außerdem eine Test-Datenbank.
- **Alle Tests je Mutation.** Bei mehreren hundert Mutationen dauerte jeder
  Lauf so lange wie ein voller Testlauf.
- **Lauf in der CI.** Ein Lauf über die Rechenmodule dauert Stunden und
  verlangt eine Auswertung von Hand.

## Grenzen

- Nur die Mutationen der Tabelle. Geänderte Aufrufe, Feldnamen oder
  Querysets werden nicht erzeugt.
- Gemessen wird gegen die Tests, die laut Abdeckung die Zeile ausführen.
  Nach Änderungen an Tests ist `--neu` nötig.
- Das Werkzeug hat keine eigenen Tests.
