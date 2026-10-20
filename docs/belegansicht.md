# Belegansicht

Gestaltung der Belegmaske im Admin für alle Belegarten (Angebot, Auftrag,
Lieferschein, Rechnung, Stornorechnung, Rechnungskorrektur, Mahnung) und die
zugehörigen Regeln im PDF. Änderungen am Layout bitte vorher in einem Issue
abstimmen; die unter [Tests](#tests) genannten Browsertests messen die hier
beschriebenen Eigenschaften.

## Gestaltungsprinzip

Die Aufteilung der Maske folgt dem Aufbau des erzeugten PDFs: links die
Positionsnummer in eigener Spalte, daneben die Bezeichnung, darunter
linksbündig der Langtext, Beträge rechts. Gegliedert wird über Abstände und
Ausrichtung, um mit wenigen Farben auszukommen.

## Positionen

- Die Positionsnummer steht halbfett in einer eigenen Spalte. Sie ist ein
  Textfeld, damit Ordnungszahlen aus Leistungsverzeichnissen wie
  `01.01.0010` möglich sind. Sortiert wird nach einem Schlüssel mit
  aufgefüllten Ziffernfolgen (`9` vor `10`), weitergezählt in der letzten
  Stufe (auf `01.01.0010` folgt `01.01.0020`), siehe
  `faktura/positionsnummer.py`. Spaltenbreite in der Maske 6,5 rem.
- Unter der Nummer haben Katalogsuche und Langtext eine eigene leere Zelle
  (CSS-Klasse `pw-rueckgrat`). Ihr Inhalt beginnt dadurch in Bearbeitungs-
  und Leseansicht exakt unter der Bezeichnung.
- Suche, Bezeichnung, Langtext, Trennlinie und nächste Position haben
  denselben vertikalen Abstand. Zwischen zwei Positionen liegt genau eine
  helle Linie.
- Hervorgehoben wird nur die Position, in der ein Feld den Fokus hat
  (`:focus-within`): leichte Hintergrundfarbe in der Primärfarbe und ein
  schmaler Balken am linken Rand.
- Die Katalogsuche erscheint nur über neuen Zeilen, auch beim Lieferschein.
  Um eine gespeicherte Position zu ersetzen, wird sie gelöscht und neu
  gewählt.
- Der Langtext hat keine Beschriftung, einen Platzhalter und wächst mit dem
  Inhalt (`field-sizing: content`). Daneben „Leistung von“ und „Leistung
  bis“, Beschriftung links vom Feld. In der Leseansicht werden leerer
  Langtext und leere Datumsfelder ausgeblendet.
- Spaltenköpfe: „Pos.“, „Bezeichnung“, „Menge“, „Einheit“, „Preis (Netto)“,
  „USt.“, „Betrag“, darunter klein die BT-Nummer der EN 16931,
  Pflichtsternchen direkt hinter der Beschriftung. Pos. und Bezeichnung
  linksbündig, alle übrigen Spalten rechtsbündig mit Ziffern fester Breite
  (`font-variant-numeric: tabular-nums`), der Betrag halbfett.
- Zahlen erscheinen im Format des PDFs: Menge im Eingabefeld ohne
  überflüssige Nachkommanullen (`6`, `1.5`), in der Leseansicht `40`,
  `1.450,00`, `19 %`. Menge und Preis haben keine Spin-Buttons.
- Zeilenarten: Ein Titel steht fett über die ganze Breite, nach seiner
  letzten Unterposition folgt „Summe Titel 01 …“ fett mit Linie darüber. Ein
  Text steht ohne Nummer über die ganze Breite. Ein Zuschlag hat keine
  Menge, Einheit und Einzelpreis; darunter steht klein der Rechenweg („3 %
  auf 9.500,00“). Zeilenart, Prozentsatz und Bezugsbereich („auf“) stehen in
  der zweiten Zeile der Position, die beiden letzten nur beim Zuschlag
  (`zeilenart.js`).
- Das Löschsymbol ist grau und wird beim Überfahren rot. Eine Position hat
  keine eigene Titelzeile. Leere Zusatzzeilen: eine, wenn der Beleg bereits
  Positionen hat, sonst drei.
- Bei 1366 und 1280 px Breite passt die Tabelle ohne horizontales Scrollen,
  auch beim Auftrag mit der zusätzlichen Spalte „Abgerechnet“.

## Belegkopf

- Zusammengehörige Felder stehen paarweise in einer Zeile: Projekt und
  Kunde, Betreff und „Bestellnr. des Kunden“, Empfänger und E-Mail,
  Belegdatum und Leistungsdatum (BT-72). Das gilt auch beim Anlegen, beim
  Lieferschein und bei der Mahnung. Die Felder einer Zeile sind oben
  ausgerichtet.
- Alle Datumsfelder haben dieselbe Breite. Zwei Datumsfelder in einer Zeile
  teilen sich den Platz ohne Überlappung.
- Der Reiter „E-Rechnung“ ist zweispaltig. Ein einzelnes Feld in einer Zeile
  belegt die linke Hälfte; alle Felder enden an derselben Kante.

## Versand

Versendet wird genau eine Datei je Beleg, ohne Auswahl von Anhängen. Die
Versandmaske nennt die Datei und den Zustellweg des Kunden. Begründung in
[e-rechnung.md](e-rechnung.md).

## PDF

Der Langtext steht in einer eigenen Zeile, die von der Bezeichnung bis zum
Gesamtpreis reicht, ohne Trennlinie zur Position. Die Spalte „Pos.“ ist bei
bis zu vier Zeichen 8 mm breit und wächst mit längeren Nummern. Zeilenarten
wie in der Maske; die Schlussrechnung zeigt je Abschlag eine Zeile.

## Verworfene Alternativen

- **Tausendertrennzeichen im Preisfeld.** Ein `<input type="number">`
  unterstützt keine, und ein Punkt als Trennzeichen macht `1.500`
  mehrdeutig (1,5 oder 1500). `USE_THOUSAND_SEPARATOR` bleibt `False`;
  formatiert wird nur die Anzeige.
- **Katalogsuche abhängig vom Inhalt der Zeile.** Sie würde beim ersten
  eingegebenen Zeichen verschwinden und das aktive Eingabefeld nach oben
  verschieben. Maßgeblich ist deshalb, ob die Zeile gespeichert ist.
- **Schaltfläche „Aus dem Katalog ersetzen“** an gespeicherten Positionen.
  Wurde gebaut und nach dem Ausprobieren am selben Tag wieder entfernt.
- **Innenabstand statt eigener Zelle unter der Nummer.** In der Leseansicht
  ist die Nummernspalte ohne Eingabefelder schmaler, der Langtext stand
  dann 18 px versetzt zur Bezeichnung. Nur eine eigene Zelle hält beide
  Ansichten bündig.
- **Karten, Schatten, Zebrastreifen, Farbe je Steuersatz.** Bei 20
  Positionen entstehen 20 Kästen; Zebrastreifen flackern bei Langtexten
  unterschiedlicher Länge.
- **Fixierter Spaltenkopf.** Der Container von Unfold hat
  `overflow-x: auto`, darin greift `position: sticky` nicht. Wieder prüfen,
  wenn Leistungsverzeichnisse mit 50 und mehr Positionen üblich werden.
- **Layout unter 1024 px.** Unfold blendet dort den Tabellenkopf aus; die
  Zelle unter der Nummer ist unterhalb des Breakpoints `lg` ausgeblendet.
- **Polyfill für `field-sizing: content`.** Browser ohne Unterstützung
  zeigen den Langtext mit der Mindesthöhe von 2,5 rem.
- **Schaltfläche zum Einblenden des Leistungszeitraums.** Die Datumsfelder
  sind immer sichtbar.

## Implementierung

| Bereich | Datei |
| --- | --- |
| Layout, Abstände, Breiten | `faktura/static/faktura/css/faktura_admin.css` |
| Zusatzzeilen mit Zelle unter der Nummer | `templates/unfold/helpers/edit_inline/paperwerk_zusatzzeile.html` |
| Spaltenköpfe mit BT-Nummer | `templates/unfold/helpers/edit_inline/tabular_heading.html` |
| Leseansicht (Filter `lesewert`, `hat_lesewert`) | `templates/unfold/helpers/edit_inline/tabular_group.html` |
| Inline: `show_title`, `SPALTENKOEPFE`, `get_extra` | `faktura/admin/gemeinsam.py` |
| Mengenfeld (`MengeWidget`), Langtextfeld | `faktura/forms.py` |
| Feldpaare im Belegkopf | `faktura/admin/belegarten.py`, `faktura/admin/formular.py` |
| Zeilenarten in der Maske | `faktura/static/faktura/js/zeilenart.js` |
| Positionsnummern | `faktura/positionsnummer.py`, `faktura/static/faktura/js/positionsnummer.js` |

## Tests

Die Browsertests (Playwright) messen Positionen und Abstände im
gerenderten DOM:

- `tests/test_browser_positionen.py`
  - `TestPositionenDarstellung`: Langtext unter der Bezeichnung (±1 px),
    gleiche Abstände, Platz der Datumsfelder, E-Rechnung zweispaltig,
    Leseansicht, 1280 px, Zahl der leeren Zeilen, Hervorhebung,
    Spaltenköpfe, Pflichtsternchen, keine Spin-Buttons.
  - `TestKatalogsucheNurAnNeuenZeilen`, auch beim Lieferschein.
  - `TestWerteInDerMaske`: Menge, Preis, Steuersatz und Summe ändern sich
    beim Speichern ohne Eingabe nicht.
- `tests/test_stilklassen.py`: Jede `pw-`-Klasse ist im eigenen CSS
  definiert.
- `faktura/tests/test_lokalisierung.py`: Eingabe `1.500`.
- `faktura/tests/test_langtext.py`, `TestDerLangtextUeberDieGanzeBreite`: Langtext
  im PDF.
- `faktura/tests/test_zeilenarten.py`, `faktura/tests/test_schluss_leistung.py`:
  Zeilenarten und Schlussrechnung.
