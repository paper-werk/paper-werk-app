# Grundlagen der Bedienung

Paper-Werk läuft im Browser. Links steht die Seitenleiste mit allen
Bereichen, oben die Kopfleiste mit den Knöpfen der jeweiligen Seite, darunter
die Liste oder Maske, an der Sie gerade arbeiten. Welche Einträge und Knöpfe
Sie sehen, hängt von Ihren Rechten ab. Fehlt Ihnen etwas, das eine
Kollegin sieht, fragen Sie den Administrator.

## Die Seitenleiste {#seitenleiste}

Die Seitenleiste folgt dem Arbeitsablauf:

| Gruppe | Einträge |
|---|---|
| Übersicht | Startseite, Controlling |
| Projekte | Projekte, Angebote, Aufträge, Abnahmen, Lieferscheine |
| Rechnungen | Rechnungen, Abschlagsrechnungen, Schlussrechnungen, Mahnungen, Zahlungseingänge |
| Weitere Rechnungsarten | Teilschlussrechnungen, Stornorechnungen, Rechnungskorrekturen |
| Leistung | Erfassung, Nicht abgerechnet, Eingangsrechnungen |
| Stammdaten | Kontakte, Leistungskatalog, Textbausteine, Kostensätze, Steuersätze, Eigene Firma |
| Verwaltung | Benutzer, Gruppen, API-Schlüssel |
| Hilfe | Bedienungsanleitung |

Die Gruppen „Weitere Rechnungsarten“, „Stammdaten“ und „Verwaltung“ sind
eingeklappt; ein Klick auf die Überschrift öffnet sie. Eine Zahl neben
„Rechnungen“, „Abschlagsrechnungen“, „Schlussrechnungen“ und
„Teilschlussrechnungen“ nennt die Entwürfe, die dort noch liegen.

Ganz unten stehen Ihr Name und die Versionsnummer von Paper-Werk. Über
Ihren Namen melden Sie sich ab, ändern Ihr Passwort und wechseln zwischen
heller und dunkler Darstellung.

Mit der Taste <kbd>[</kbd> blenden Sie die Seitenleiste aus und wieder ein,
etwa wenn eine breite Liste mehr Platz braucht. Dasselbe tut das Symbol
links in der Kopfleiste.

## Die Schnellsuche mit Strg+K {#schnellsuche}

Die schnellste Art, etwas zu finden: <kbd>Strg</kbd>+<kbd>K</kbd> (am Mac
<kbd>⌘</kbd>+<kbd>K</kbd>) öffnet ein Suchfeld über der Seite. Ab zwei
Zeichen erscheinen Treffer aus vier Bereichen:

- **Kontakte** nach Nummer und Name. Der Treffer öffnet die Kundenakte.
- **Projekte** nach Nummer und Bezeichnung. Der Treffer öffnet die
  Projektakte.
- **Belege** nach Nummer, Empfänger und Betreff, also Angebote, Aufträge,
  Rechnungen, Mahnungen und so weiter. Eine Rechnung öffnet die
  Rechnungsakte, die übrigen Belege ihre Maske.
- **Beträge**: Tippen Sie einen Betrag wie auf dem Kontoauszug, etwa
  „1.445,14“ oder „1445,14“, finden Sie die festgeschriebenen Belege mit
  genau diesem Bruttobetrag. Das hilft, wenn eine Überweisung ohne
  brauchbaren Verwendungszweck eingeht. Ganze Zahlen wie „2026“ gelten
  nicht als Betrag, sie sind meist Teil einer Nummer.

Außerdem findet die Suche die Bereiche selbst: „mahn“ führt zur Liste der
Mahnungen.

Je Bereich erscheinen höchstens acht Treffer; wird es mehr, tippen Sie
weiter. Sie sehen nur, was Sie auch in den Listen sehen dürfen.

Bedienung im Suchfeld:

| Taste | Wirkung |
|---|---|
| <kbd>↓</kbd> <kbd>↑</kbd> | Treffer auswählen |
| <kbd>Enter</kbd> | Treffer öffnen |
| <kbd>Strg</kbd>+<kbd>Enter</kbd> | Treffer in einem neuen Reiter öffnen |
| <kbd>Esc</kbd> | Suche schließen |

Die zuletzt geöffneten Treffer stehen beim nächsten Öffnen schon da.

Zwei Einschränkungen: Strg+K wirkt nicht, solange der Cursor in einem
Eingabefeld steht; klicken Sie vorher auf eine freie Stelle der Seite. Und
die Treffer werden fünf Minuten zwischengespeichert, ein eben angelegter
Beleg erscheint also unter Umständen erst danach.

## Weitere Tastenkürzel {#tastenkuerzel}

Diese Kürzel wirken nur, wenn der Cursor in keinem Eingabefeld steht.

| Taste | Wirkung |
|---|---|
| <kbd>Strg</kbd>+<kbd>K</kbd> | Schnellsuche öffnen |
| <kbd>Umschalt</kbd>+<kbd>?</kbd> | Übersicht aller Tastenkürzel |
| <kbd>[</kbd> | Seitenleiste ein- oder ausblenden |
| <kbd>Strg</kbd>+<kbd>E</kbd> | Zwischen hell und dunkel wechseln |
| <kbd>/</kbd> | In einer Liste: Cursor ins Suchfeld |
| <kbd>F</kbd> | In einer Liste: Filter ein- oder ausblenden |
| <kbd>C</kbd> | In einer Liste: neuen Eintrag anlegen |
| <kbd>Esc</kbd> | Offenes Fenster oder Menü schließen |

Das „?“ rechts in der Kopfleiste ist etwas anderes: Es öffnet diese
Anleitung an der Stelle, die zur aktuellen Seite gehört, in einem neuen
Reiter.

## Die Kopfleiste {#kopfleiste}

Über einer geöffneten Maske stehen, von links nach rechts:

- **‹ 7 von 42 ›**: Blättern in der Liste, aus der Sie den Eintrag geöffnet
  haben, in deren Reihenfolge und mit deren Filter. So arbeiten Sie etwa
  alle offenen Rechnungen der Reihe nach ab, ohne zur Liste zurückzugehen.
  Die Liste gilt so, wie sie beim Öffnen war: Ein Beleg, der inzwischen
  aus dem Filter fällt (etwa weil Sie ihn versendet haben), bleibt in der
  Reihe; neue Einträge kommen erst nach erneutem Laden der Liste dazu.
- **Die Knöpfe der Seite**: vorn der nächste Schritt, den der Zustand des
  Eintrags verlangt (etwa „Versenden“ am Entwurf), dazu „PDF anzeigen“ und
  bei manchen Masken die Akte. Ein Knopf erscheint nur, wenn er im
  aktuellen Zustand möglich ist: An einer festgeschriebenen Rechnung gibt
  es kein „Versenden“ mehr, sondern „Erneut versenden“ unter „Weitere …“.
- **Weitere …**: ein Menü mit allem, was seltener gebraucht wird. Der
  letzte Eintrag ist immer **Verlauf**: wer wann was an diesem Eintrag
  geändert, festgeschrieben, versendet oder heruntergeladen hat.
- **+**: einen neuen Eintrag dieser Art anlegen.
- **?**: die Hilfe zu dieser Seite.

Die Knöpfe der Seite erscheinen erst, wenn der Eintrag gesichert ist. Bei
einem neuen Beleg klicken Sie deshalb zuerst „Sichern und weiter
bearbeiten“.

Ein Klick auf einen dieser Knöpfe sichert vorher, was Sie in der Maske
eingetragen haben. Sie müssen also vor „Versenden“ oder „PDF anzeigen“
nicht selbst sichern; das PDF zeigt immer den Stand, den Sie vor sich
sehen. Enthält die Maske einen Fehler, bleibt sie stehen und zeigt ihn an,
statt die Aktion auszuführen.

Manche Knöpfe fragen in einem kleinen Fenster nach, bevor sie etwas tun
(„Auftrag aus diesem Angebot erzeugen?“). Andere führen auf eine eigene
Seite, auf der Sie noch etwas eintragen, etwa beim Versenden oder beim
Vermerken einer Zahlung. Dort führt „Abbrechen“ ohne Änderung zurück.

Meldungen über das Ergebnis erscheinen oben auf der Seite: grün für
Erfolg, gelb für Hinweise, rot für Fehler. Rote Meldungen nennen den Grund,
etwa „Bei einer Rechnung ist das Leistungsdatum Pflichtangabe“.

## Listen {#listen}

Jeder Eintrag der Seitenleiste öffnet eine Liste.

- **Suchen**: Das Suchfeld über der Liste durchsucht die wichtigsten
  Spalten, bei Belegen Nummer, Empfänger und Betreff. Mit
  <kbd>/</kbd> springen Sie hinein.
- **Filtern**: Der Knopf „Filter“ (oder die Taste <kbd>F</kbd>) öffnet die
  Filter, etwa nach Status, Zeitraum, Projekt oder Kunde. Bei den Belegen
  wirken sie erst mit „Filter anwenden“, damit die Liste nicht nach jedem
  Feld neu lädt. Ein aktiver Filter färbt den Knopf ein.
- **Sortieren**: Ein Klick auf eine Spaltenüberschrift sortiert danach,
  ein zweiter Klick dreht die Reihenfolge um.
- **Zeitleiste**: Über manchen Listen stehen Jahre und Monate; ein Klick
  grenzt die Liste auf diesen Zeitraum ein.
- **Reiter**: Über der Rechnungsliste stehen die Reiter „Alle“, „Entwürfe“,
  „Offen“, „Über Frist“ und „Bezahlt“. Sie setzen nur den passenden Filter.
- **Summe**: Unter jeder Belegliste stehen Netto, Umsatzsteuer und Brutto
  über alle gefilterten Belege, nicht nur über die sichtbare Seite. So
  beantworten Sie Fragen wie „Was ging im dritten Quartal hinaus?“ ohne
  Export.
- **Mehrere Einträge auf einmal**: Setzen Sie links die Häkchen, wählen Sie
  oben unter „Aktion wählen“ den Vorgang, etwa „Ausgewählte Belege
  festschreiben“, und klicken Sie „Ausführen“. Das Häkchen in der
  Kopfzeile wählt alle Einträge der Seite.

In den Belegen steht ganz rechts ein Schloss für festgeschriebene und ein
durchgestrichener Kreis für stornierte Belege; Entwürfe haben kein
Zeichen. Die Spalte „Dokument“ verweist auf das PDF und, sobald der Beleg
im Archiv liegt, auf das Archiv.

## Masken {#masken}

Eine Maske ist das Formular eines einzelnen Eintrags.

- Pflichtfelder sind mit einem Sternchen markiert.
- Felder, die nebeneinander stehen, gehören zusammen (etwa Projekt und
  Kunde).
- Manche Bereiche liegen in **Reitern** unter dem Kopf, etwa „Texte“,
  „E-Rechnung“ und „Status“. Enthält ein Reiter einen Fehler, zeigt er die
  Zahl der Fehler an.
- Werte ohne Eingabekasten sind nur zum Lesen, etwa die Nummer oder das
  Datum der Festschreibung.

Unten rechts stehen die Knöpfe zum Sichern:

| Knopf | Wirkung |
|---|---|
| Sichern | Sichert und führt zurück zur Liste |
| Sichern und weiter bearbeiten | Sichert und bleibt in der Maske |
| Sichern und neu hinzufügen | Sichert und öffnet eine leere Maske derselben Art |
| Löschen | Löscht den Eintrag nach Rückfrage; bei Belegen nur am Entwurf |

Wollen Sie eine Seite mit ungesicherten Änderungen verlassen, fragt der
Browser nach. Ein festgeschriebener Beleg zeigt keine Sichern-Knöpfe, er
lässt sich nicht mehr ändern.

### Textvorlagen

Über langen Textfeldern, etwa dem Text über und unter den Positionen oder
der Nachricht beim Versenden, steht der Knopf **Textvorlagen**. Er öffnet
eine Liste der passenden Textbausteine. Ein Klick fügt den Text ein; steht
im Feld schon etwas, kommt er darunter, nichts wird überschrieben. Danach
ist er gewöhnlicher Text, den Sie frei ändern. Die Bausteine selbst
pflegen Sie unter Stammdaten, Textbausteine. Gibt es für ein Feld keinen
Baustein, erscheint auch kein Knopf.

### Auswahlfelder mit Suche

Felder wie Kunde oder Projekt sind Suchfelder: Klicken Sie hinein und
tippen Sie einen Teil des Namens oder der Nummer. Die drei Punkte daneben
öffnen ein Menü: den gewählten Eintrag ansehen oder ändern oder einen neuen
anlegen, jeweils in einem eigenen Fenster, ohne die Maske zu verlassen.
Ein neuer Kunde lässt sich so direkt aus dem Angebot heraus anlegen.

## Wenn zwei Personen denselben Eintrag bearbeiten {#versionskonflikt}

Haben zwei Personen denselben Eintrag offen und die andere sichert zuerst,
nimmt Paper-Werk Ihre Eingaben nicht an und meldet: „Ihre Eingaben konnten
nicht gespeichert werden. Die Daten sind nicht mehr aktuell.“ Die Meldung
nennt, wer zuletzt geändert hat und wann. So überschreibt niemand
unbemerkt die Arbeit eines anderen.

Klicken Sie **Aktuellen Stand laden**. Die Maske zeigt dann, was die
andere Person gesichert hat; tragen Sie Ihre Änderung dort erneut ein und
sichern Sie. Ihre ursprünglichen Eingaben sind nicht gespeichert; wenn Sie
viel getippt haben, kopieren Sie den Text vorher heraus.

Wird ein Beleg festgeschrieben, während Sie ihn noch offen haben, meldet
Paper-Werk beim Sichern, wer ihn wann festgeschrieben hat. Ihre Änderungen
sind dann nicht gesichert.

## Hell und dunkel

Paper-Werk folgt der Einstellung Ihres Betriebssystems. Mit
<kbd>Strg</kbd>+<kbd>E</kbd> oder über Ihren Namen unten in der
Seitenleiste wählen Sie hell oder dunkel fest.
