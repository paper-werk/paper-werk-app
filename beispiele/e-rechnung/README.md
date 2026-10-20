# Beispiel-E-Rechnungen

Zum Ausprobieren von *Eingangsrechnungen → E-Rechnung einlesen*. Die Dateien
sind erfunden, aber vollständig: Sie tragen alles, was der Parser liest, und
decken die Fälle ab, an denen sich das Verhalten unterscheidet.

Sie werden **auch von den Tests eingelesen**
([`erfassung/tests/test_erechnung.py`](../../erfassung/tests/test_erechnung.py),
`TestBeispieldateien`). Das ist der Grund, warum sie hier und nicht in einem
Downloads-Ordner liegen: Eine Beispieldatei, die stillschweigend nicht mehr
funktioniert, ist schlimmer als keine; sie lässt einen den Fehler in der
Anwendung suchen.

## Was eingelesen wird

| Datei | Was daran zu sehen ist |
| --- | --- |
| `isartal-4713-als-pdf.pdf` | **Der Alltagsfall**: eine E-Rechnung als PDF, wie sie im Postfach liegt. Sichtbare Rechnungsseite, das `factur-x.xml` steckt als Anhang darin; genau daraus wird gelesen. |
| `isartal-4711-regelfall.xml` | Dasselbe als nacktes XML: zwei Positionen, Summen gehen auf, Rest steht auf null. Verschiedene Einheiten (C62 → Stk, HUR → Std). |
| `isartal-4712-mit-abschlag.xml` | 25 € Rabatt auf Belegebene. Der Kopf lautet auf **647,50 €** (BT-109), die Positionen ergeben 672,50; die Maske meldet die Abweichung als Warnung. |
| `ingsoft-4801-ohne-positionen.xml` | Profil BASIC WL, also gar keine Zeilen. Mit Vorhaben entsteht eine Summenzeile über den vollen Betrag. Zweiter Lieferant, zeigt, dass ein unbekannter Name angelegt und vermerkt wird. |

### Für den Elektrobetrieb

Diese beiden gehören zum Demobestand Elektro Hofmeister (paper-werk,
`demodaten/elektro-hofmeister`). Sie stehen neben den Laborrechnungen, weil
beide Demobestände, Ingenieurbüro und Handwerksbetrieb, Belege brauchen, die
zu ihren Vorhaben passen.

Die Lieferanten heißen wie im Seed, die **Rechnungsnummern sind andere**; so
lassen sich die Dateien hochladen, ohne auf *"bereits erfasst"* zu laufen.

| Datei | Was daran zu sehen ist |
| --- | --- |
| `wittmann-880366-material.xml` | **Der Alltagsfall eines Handwerksbetriebs**: vier Positionen, viele Kleinteile, und der Betrag steckt im Material statt in Arbeitszeit. Zeigt als einzige Datei die Einheit `MTR` → `m`. Kopf 1.524,00 €, Summen gehen auf. |
| `ladetechnik-3402-wallbox.xml` | **Wenige Zeilen, hoher Betrag**, der Gegenfall. Zwei Wallboxen mit Montagesäulen, 2.212,00 €. Solche Positionen werden mit Aufschlag weiterberechnet, während Kleinmaterial in der Pauschale untergeht. Die **Seriennummern** stehen nur im Freitext und landen über `sonstiges` in der Notiz: Sie gehen in die Anmeldung beim Netzbetreiber, und wer sie nach zwei Jahren für einen Garantiefall sucht, sucht sie in der Rechnung. |

Das PDF wurde mit derselben Kette gebaut, mit der paper-werk seine eigenen
Rechnungen erzeugt: WeasyPrint für die Seite, `drafthorse` für das
eingebettete XML.

## Was abgewiesen wird

Jede dieser Dateien muss eine **rote Meldung** ergeben und darf nichts anlegen.

| Datei | Erwartete Absage |
| --- | --- |
| `abgewiesen-gutschrift.xml` | Typcode 381: eine Eingangsrechnung kennt nur den Rechnungsfall. |
| `abgewiesen-ubl-syntax.xml` | UBL statt CII. Gelesen wird nur CII, dieselbe Syntax, die paper-werk auch schreibt. |
| `abgewiesen-fremdwaehrung.xml` | CHF statt EUR. Der gefährlichste Fall: Das Modell hat kein Währungsfeld, aus 672,50 Franken würden sonst still 672,50 Euro. |

Ein **gewöhnliches PDF** (ein Scan, eine gedruckte Rechnung) wird ebenfalls
abgewiesen: Es trägt nur das Bild, keine Daten. Dafür braucht es keine
Beispieldatei, jedes beliebige PDF tut es.

## Reihenfolge beim Durchprobieren

1. `isartal-4713-als-pdf.pdf` **mit** einem Vorhaben → Rest auf null, zwei Positionen, Meldung „XML aus dem PDF geholt". Der Weg, den im Betrieb fast jede Rechnung nimmt.
2. `isartal-4711-regelfall.xml` → dasselbe Ergebnis aus dem nackten XML.
3. Dieselbe Datei noch einmal → „bereits erfasst", nichts entsteht.
4. `isartal-4712-mit-abschlag.xml` → Warnung über die Abweichung, derselbe Lieferant wird wiederverwendet.
5. `ingsoft-4801-ohne-positionen.xml` **ohne** Vorhaben → nur der Kopf, Rest offen sichtbar.
6. Die drei `abgewiesen-*.xml`, dazu ein beliebiges eigenes PDF → vier verschiedene rote Meldungen.

Nach Schritt 5 lohnt ein Blick in *Lieferanten*: „Ingsoft Tragwerksplanung
GbR" trägt den Vermerk, dass sie automatisch angelegt wurde. Und ein Blick in
die Notiz der ersten Rechnung; dort steht, dass ihre Zahlen aus dem PDF
kommen.
