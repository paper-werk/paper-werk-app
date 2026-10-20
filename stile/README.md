# Der eigene Tailwind-Build

`eingang.css` erzeugt `core/static/core/css/paperwerk.css`: die
Tailwind-Klassen, die unsere Vorlagen und Spalten benutzen, Unfolds
vorkompiliertes CSS aber nicht enthält.

## Wann neu bauen

Nur, wenn eine Vorlage oder eine Spalte (`format_html` in Python) eine
Tailwind-Klasse bekommt, die es vorher im Projekt nicht gab. Wer es
vergisst, erfährt es von `tests/test_stilklassen.py`.

```bash
npm install      # einmal, legt node_modules/ an (nicht im Repo)
npm run css      # baut core/static/core/css/paperwerk.css
```

Das Ergebnis wird **mit eingecheckt**. Container und CI brauchen deshalb
kein Node.

## Was man wissen muss

- Klassennamen ausschreiben, nie zusammensetzen: Tailwind findet nur, was
  als ganzer Name im Quelltext steht.
- Die erste Zeile von `eingang.css` nennt alle fünf CSS-Layer in Unfolds
  Reihenfolge. Fehlt sie, verliert die ganze Oberfläche ihre Abstände
  (Begründung im Kopf der Datei).
- Farben gehören Unfold (`UNFOLD['COLORS']`); hier stehen nur ihre Namen.

Hintergrund: `docs/entscheidungen.md`, Abschnitt „Architektur“.
