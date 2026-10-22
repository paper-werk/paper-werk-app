# Rechnungen

Alle Rechnungsarten werden gleich bedient: Entwurf anlegen, Positionen
eintragen, versenden. Was für alle Belege gilt, steht im Kapitel
[Belege](#belegstatus); hier steht, was Rechnungen darüber hinaus können.

## Rechnungen {#rechnung}

„Rechnungen“ in der Seitenleiste sind die gewöhnlichen Rechnungen, ohne
Abschläge und Schlussrechnungen.

### Die Liste

Ein Klick auf die Nummer öffnet die **Rechnungsakte**, nicht die Maske;
dort führt „Rechnung bearbeiten“ weiter. Die Spalten:

| Spalte | Inhalt |
|---|---|
| Beleg | Nummer, beim Entwurf „Entwurf 54“ |
| Empfänger | erste Zeile der Anschrift |
| Belegdatum | |
| Fällig | Datum „Zahlbar bis“; dahinter rot „+12 T“ für zwölf Tage über der Frist oder grau „in 7 T“ |
| Brutto | Rechnungsbetrag |
| Offen | was noch zu zahlen ist; ein Strich, wenn nichts offen ist |
| Zahlung | offen, über Frist, bezahlt oder abgerechnet |
| (Symbol) | „Zahlung vermerken“, nur wo etwas offen ist |
| E-Mail | Tag der ersten Mail an den Kunden |
| Dokument | PDF und Archiv |

„Abgerechnet“ in der Spalte Zahlung heißt: Die Rechnung ist in einer
Schlussrechnung aufgegangen, die den Betrag fordert. Die Spalte „E-Mail“
weiß nur von Mails; eine heruntergeladene und per Post verschickte
Rechnung hat dort kein Datum.

Die **Reiter** über der Liste: Alle, Entwürfe, Offen, Über Frist (älteste
Fälligkeit zuerst) und Bezahlt. Die **Filter**: Status, Belegdatum als
Zeitraum, Projekt, Kunde, E-Mail (versendet oder nicht) und Zahlungsstand.

Aktionen für mehrere Rechnungen: Ausgewählte Belege festschreiben,
Rechnung stornieren und neu schreiben, Nachlass gewähren, Mahnung erzeugen
(nächste Stufe), Zahlungseingang vermerken. Nachlass und Zahlung gehen nur
für genau eine Rechnung.

### Anlegen

Eine Rechnung entsteht meist aus einem Auftrag, Angebot oder Lieferschein
(„Rechnung erzeugen“) oder aus erfassten Leistungen. Von Hand: in der
Liste „+“, Projekt wählen, Positionen eintragen. Pflicht beim
Festschreiben sind Leistungsdatum und Empfängeranschrift.

### Die Knöpfe

| Knopf | Wo | Wann | Wirkung |
|---|---|---|---|
| Rechnungsakte | vorn | immer | Woraus die Rechnung besteht |
| Versenden | vorn | am Entwurf | Versandseite, schreibt fest, siehe [Versenden](#versenden) |
| PDF anzeigen | vorn | immer | PDF mit E-Rechnung im neuen Reiter |
| Zahlung vermerken | Weitere … | festgeschrieben, etwas offen | Zahlungseingang erfassen |
| Erbrachte Leistungen hinzufügen | Weitere … | Entwurf mit Projekt | Erfasste Stunden und Zukauf übernehmen |
| Erneut versenden | Weitere … | nach dem Versand | Noch einmal schicken oder herunterladen |
| Mahnung erzeugen | Weitere … | festgeschrieben, etwas offen | Mahnung der nächsten Stufe als Entwurf |
| Nachlass gewähren | Weitere … | festgeschrieben, nicht am Abschlag | Rechnungskorrektur über einen Betrag |
| E-Rechnung neu ausstellen | Weitere … | festgeschrieben | Neue Dateien bei gleicher Nummer, etwa nach Ablehnung durch ein Portal |
| Stornieren und neu schreiben | Weitere … | festgeschrieben, Nachlass vorher storniert | Stornorechnung und neuer Entwurf |
| Rechnung duplizieren | Weitere … | immer | Neuer Entwurf mit denselben Positionen |
| Verlauf | Weitere … | immer | Änderungen und Vorgänge |

### Erbrachte Leistungen hinzufügen

Am Rechnungsentwurf eines Projekts öffnet dieser Knopf eine Seite mit
allem, was auf dem Projekt geleistet und noch nicht berechnet ist:
erfasste Stunden und Mengen, nach Leistung gruppiert, und zugekaufte
Leistungen aus Eingangsrechnungen. Haken Sie an, was auf diese Rechnung
soll; die Positionen werden angefügt und die Zeilen gelten danach als
abgerechnet. Mehr dazu im Kapitel Leistung.

### E-Rechnung neu ausstellen

Lehnt ein Rechnungsportal eine E-Rechnung ab, etwa wegen einer falschen
Leitweg-ID, stellt dieser Knopf sie neu aus: gleiche Nummer, neue Dateien.
Auf der Seite tragen Sie den **Grund** ein (Pflicht) und können
**Käuferreferenz / Leitweg-ID** und **Bestellnummer des Kunden**
berichtigen. Die vorige Fassung bleibt im Reiter „Status“ unter „Frühere
Fassung“ erhalten.

## Rechnungsakte {#rechnungsakte}

Die Rechnungsakte beantwortet: Woraus besteht diese Rechnung, und wo steht
sie? Oben rechts führt **Rechnung bearbeiten** in die Maske.

Im Kopf stehen Nummer, Betreff, der Zustand und der Zahlungsstand als
Marke, dazu Projekt und Kunde mit Verweis auf ihre Akten.

Darunter **der Weg des Belegs**: Angelegt, Festgeschrieben, E-Mail, Im
Archiv, Bezahlt, jeweils mit Datum. Der erste offene Schritt ist
hervorgehoben, dort liegt die Rechnung gerade. Eine stornierte Rechnung
endet bei „Storniert“, eine in der Schlussrechnung aufgegangene bei
„Abgerechnet“.

Die Kennzahlen teilen den Nettobetrag nach Herkunft:

- **Netto**: der Rechnungsbetrag ohne Umsatzsteuer.
- **Aus Erfassungen**: Positionen, an denen erfasste Leistung hängt.
- **Aus Fremdleistungen**: weiterberechneter Zukauf, mit dem Einkaufswert.
- **Ohne Nachweis**: von Hand geschrieben, aus dem Katalog oder Abzüge.

Die Tabelle darunter zeigt je Auftragsposition, was erfasst, was schon
abgerechnet, was auf dieser Rechnung und was noch offen ist.
**Fakturierte Erfassungen** zeigt, wessen Stunden auf der Rechnung stehen.

## Abschlagsrechnungen {#abschlagsrechnung}

Ein Abschlag ist eine Anzahlung auf eine noch nicht vollendete Leistung.

**Anlegen:** unter Abschlagsrechnungen „+“, Projekt wählen. Die Position
ist meist ein Betrag, etwa „Abschlagszahlung“, 1 pausch, 3.000,00.
Abschläge auf bestimmte Leistungen entstehen mit „Erbrachte Leistungen
hinzufügen“. Statt Leistungsdatum und Zeitraum hat der Abschlag die Felder
**Leistungsstand ab** und **Stichtag**: den Zeitraum, auf den er sich
bezieht, etwa Projektbeginn bis heute. Beide sind Pflicht. Ein
Leistungsdatum hat ein Abschlag nicht.

Im PDF steht „1. Abschlagsrechnung“, „2. Abschlagsrechnung“ und so
weiter, gezählt je Projekt nach Belegdatum; die Liste zeigt die Zählung in
der Spalte „Abschlag“. Knöpfe und Versand wie bei jeder Rechnung.

**Gekürzte Zahlung.** Zahlt der Kunde weniger, weil er einen Teil (noch)
nicht anerkennt, tragen Sie beim Vermerken der Zahlung den Betrag unter
**Gekürzt** ein. Dieser Teil wird nicht gemahnt; die Schlussrechnung
fordert ihn.

**Was mit dem Abschlag geschieht:** Die Schlussrechnung setzt ihn ab.
Danach hat der Abschlag nichts mehr offen, und die Zahlung steht auf
„abgerechnet“; was vom Abschlag nicht bezahlt war, fordert die
Schlussrechnung.

## Schlussrechnungen {#schlussrechnung}

Die Schlussrechnung führt die volle Leistung auf und setzt die gestellten
Abschläge ab.

**Entstehen** sollte sie aus einer Gesamtabnahme („Rechnung erzeugen“ an
der Abnahme). Dann übernimmt sie Leistungsdatum und Zeitraum aus der
Abnahme, die Leistung aus den Abschlägen und setzt die Abschläge gleich
ab. Was in keinem Abschlag stand, holen Sie mit „Erbrachte Leistungen
hinzufügen“ dazu. Von Hand angelegt (Liste, „+“) fehlen die Abzüge, bis
Sie **Abschläge absetzen** klicken.

**Die Abzüge** stehen unter den Positionen in einem eigenen Block, je
Abschlag eine Zeile, wie im PDF, und lassen sich dort nicht bearbeiten.
Abgesetzt wird jeder festgeschriebene, nicht stornierte Abschlag des
Projekts, genau einmal. Abgesetzt wird aber nur, was bezahlt ist: Ein
Abschlag über 50.000 €, auf den 40.000 € gezahlt sind, mindert die
Schlussrechnung um 40.000 €; die fehlenden 10.000 € fordert die
Schlussrechnung.

**Abschläge absetzen** (vorn, nur am Entwurf) fügt hinzu, was noch fehlt,
und gleicht ab, was sich bei den Zahlungen geändert hat. Sie können den
Knopf beliebig oft klicken. Geht nach dem Absetzen noch eine Zahlung auf
einen Abschlag ein, verlangt das Festschreiben, den Knopf erneut zu
klicken.

Beim **Versenden** weist die Seite unter „Abschläge nicht vollständig
bezahlt“ auf Abschläge mit offenem Rest hin. Ist inzwischen Geld
eingegangen, vermerken Sie erst die Zahlung, dann „Abschläge absetzen“,
dann versenden.

Schlussrechnungen lassen sich nicht duplizieren.

## Teilschlussrechnungen {#teilschlussrechnung}

Eine Teilschlussrechnung rechnet eine abgenommene Teilleistung ab. Sie
entsteht nur aus einer Teilabnahme („Rechnung erzeugen“ an der Abnahme);
die Liste hat deshalb kein „+“.

Sie übernimmt die Positionen der Teilabnahme mit ihrer offenen Menge und
dem Preis aus dem Auftrag, Zeitraum und Leistungsdatum aus der Abnahme und
setzt die Abschläge ab, die zu diesen Positionen gehören. Abschläge ohne
Bezug zu einer Position bleiben für die Schlussrechnung. Sonst wird sie
bedient wie eine Schlussrechnung.

## Zahlungseingänge {#zahlung}

### Zahlung an einer Rechnung vermerken

Der übliche Weg: an der Rechnung „Weitere …“, **Zahlung vermerken**, oder
in der Rechnungsliste das Symbol in der Zeile. Die Seite nennt Brutto,
bisher Gezahltes und den offenen Betrag. Die Felder:

- **Eingegangen am**: das Datum vom Kontoauszug, nicht das der Erfassung.
  Es entscheidet, ob die Rechnung als überfällig galt.
- **Betrag**: was tatsächlich geflossen ist; vorbelegt mit dem offenen
  Betrag.
- **Skonto**: nur, wenn der Kunde Skonto abgezogen hat; der Betrag in
  Euro, nicht der Prozentsatz.
- **Gekürzt**: nur an Abschlagsrechnungen, siehe dort.
- **Art**: Überweisung, Lastschrift, Bar, Karte oder Verrechnung.
- **Verwendungszweck**: wie auf dem Auszug; leer bedeutet die
  Rechnungsnummer.

Danach meldet Paper-Werk, ob die Rechnung ausgeglichen ist oder was offen
bleibt. Alle Zahlungen auf eine Rechnung stehen in ihrem Reiter
„Zahlungen“.

### Die Liste Zahlungseingänge

Hier stehen alle Geldeingänge, auch solche, die mehrere Rechnungen
bezahlen. Die Spalten: Datum, Zahler, Betrag, Verteilt, Rest und Art. Der
Filter „Verteilung“ zeigt Zahlungen, die noch nicht ganz oder gar nicht
zugeordnet sind, also Geld auf dem Konto, das zu keiner Rechnung gehört.

**Eine Sammelüberweisung** über mehrere Rechnungen erfassen Sie hier mit
„+“:

- oben **Zahlungsdatum** (Wertstellung laut Auszug), **Betrag** und
  **Zahlungsart**,
- unter „Zuordnung Kunde“ den **Kunden**, den **Namen laut Auszug**,
  **Verwendungszweck**, **Referenz** (eindeutige Kennung aus dem
  Kontoauszug) und eine **Notiz**,
- unter „Zuordnung Rechnungen“ je Rechnung eine Zeile mit **Beleg**,
  **Betrag**, **Skonto**, **Gekürzt** und **Notiz**. Zur Wahl stehen nur
  Rechnungen, auf denen etwas offen ist.

Was nach dem Verteilen übrig bleibt, zeigt die Spalte „Rest“.

## Mahnungen {#mahnung}

Eine Mahnung ist ein Brief zu einer überfälligen Rechnung, kein
Steuerbeleg.

**Entstehen** kann sie nur aus der Rechnung: „Weitere …“, **Mahnung
erzeugen**, oder in der Rechnungsliste die Aktion „Mahnung erzeugen
(nächste Stufe)“; die Liste der Mahnungen hat kein „+“. Gemahnt wird
erst nach der Fälligkeit und nur, solange etwas offen ist.

Die Stufe ergibt sich aus den bisherigen Mahnungen zur Rechnung:

| Stufe | Überschrift |
|---|---|
| 1 | Zahlungserinnerung |
| 2 | Mahnung |
| 3 | Letzte Mahnung |

Die Mahnung entsteht als Entwurf mit dem offenen Betrag als Forderung,
der Mahngebühr der Stufe (aus Stammdaten, Eigene Firma), dem Text der
Stufe und einer Frist von sieben Tagen.

**Die Maske:** oben die gemahnte Rechnung und die **Mahnstufe**. Ändern
Sie die Stufe, kommen beim Sichern Text und Gebühr der neuen Stufe mit,
solange Sie beide nicht von Hand geändert haben. Darunter Empfänger,
**Frist (Tage)** mit dem Datum „Zahlbar bis“ und dem offenen
Gesamtbetrag, die Texte über und unter der Aufstellung und die
Aufstellung selbst mit „Offene Forderung“ und „Betrag“.

Versendet wird wie jeder Beleg. Beim Festschreiben prüft Paper-Werk, ob
die Rechnung inzwischen bezahlt ist oder sich der offene Betrag geändert
hat; dann ist die Mahnung zu löschen und neu zu erzeugen.

Der Filter „Mahnstufe“ in der Liste zeigt etwa alle letzten Mahnungen.

## Stornorechnungen {#stornorechnung}

Eine festgeschriebene Rechnung lässt sich nicht mehr ändern. Nicht jeder
Fehler braucht ein Storno: Ist nur der Betrag zu hoch, genügt ein
[Nachlass](#rechnungskorrektur); ist er zu niedrig, stellen Sie den Rest
mit einer weiteren Rechnung. Ein Storno ist nötig bei formalen Fehlern,
etwa falschem Empfänger, falschem Steuersatz oder falschem
Leistungsdatum.

Ist die Rechnung falsch, klicken Sie an ihr „Weitere …“, **Stornieren und neu schreiben**
(rot). Nach der Rückfrage geschieht dreierlei:

1. Eine **Stornorechnung** mit denselben Positionen und negativen
   Beträgen entsteht und wird sofort festgeschrieben, mit eigener
   RE-Nummer.
2. Die ursprüngliche Rechnung wird **storniert**; sie bleibt im Bestand.
3. Eine **Neufassung** derselben Art (auch Abschlag oder Schlussrechnung)
   liegt als Entwurf bereit.

Die Meldung verweist auf beide neuen Belege. Versenden Sie die
Stornorechnung an den Kunden, dann die berichtigte Neufassung.

Stornorechnungen entstehen nur so; ihre Liste hat kein „+“. Wird eine
Schlussrechnung storniert, sind ihre Abschläge wieder frei und werden von
der Neufassung abgesetzt.

Hat die Rechnung schon einen festgeschriebenen Nachlass, stornieren Sie
zuerst den Nachlass, dann die Rechnung, siehe
[Nachlass stornieren](#nachlass-stornieren).

## Rechnungskorrekturen {#rechnungskorrektur}

Für einen nachträglichen Nachlass, bei dem die Rechnung bestehen bleibt,
etwa wegen einer Mängelrüge: an der Rechnung „Weitere …“, **Nachlass
gewähren**. Die Seite nennt den Rechnungsbetrag und was davon noch offen
ist, und sie fragt:

- **Nachlass netto**: als positiver Betrag; das Vorzeichen setzt
  Paper-Werk.
- **Grund**: erscheint als Positionstext auf dem Beleg.
- **Steuersatz**: der Satz der ursprünglichen Leistung.

Es entsteht eine **Rechnungskorrektur** als Entwurf mit Bezug auf die
Rechnung und dem Text „Zu unserer Rechnung … schreiben wir Ihnen gut“.
Prüfen und versenden Sie sie wie eine Rechnung.

### Was der Nachlass bewirkt

Die ursprüngliche Rechnung bleibt, wie sie ist: Sie ist festgeschrieben
und beim Kunden. Was der Kunde noch schuldet, rechnet Paper-Werk aus
Rechnungsbetrag, Zahlungen und Nachlässen. Sobald die Korrektur
festgeschrieben ist, gilt:

- Der **offene Betrag** der Rechnung sinkt um den Nachlass (brutto). Das
  sehen Sie in der Liste, auf der Startseite, im Controlling und im
  Reiter „Zahlungen“ der Rechnung, der den Nachlass eigens nennt.
- Eine **Zahlung** lässt sich nur noch über den geminderten Betrag
  vermerken.
- **Gemahnt** wird nur der geminderte Rest. Die Mahnung führt den
  Nachlass in ihrer Forderungszeile auf, damit der Kunde den Betrag
  nachvollziehen kann. Ist nach dem Nachlass nichts mehr offen, gibt es
  keine Mahnung. Liegt schon ein Mahnentwurf über den alten Betrag vor,
  lässt er sich nicht mehr versenden; löschen Sie ihn und erzeugen Sie
  ihn neu.

Solange die Korrektur ein Entwurf ist, ändert sich nichts: Den Entwurf
hat der Kunde noch nicht.

### Grenzen

- **Nicht über den Rechnungsbetrag hinaus.** Alle Nachlässe zusammen
  dürfen den Bruttobetrag der Rechnung nicht übersteigen. Paper-Werk
  prüft das beim Anlegen und noch einmal beim Festschreiben, falls der
  Entwurf geändert wurde.
- **Mehr als offen ist.** Hat der Kunde schon (fast) alles bezahlt, ist
  der überschießende Teil ein Guthaben des Kunden. Paper-Werk weist
  darauf hin; die Erstattung erledigen Sie außerhalb von Paper-Werk.
- **Kein Nachlass auf einen Abschlag.** Den Abschlag rechnet die
  Schlussrechnung ab. Erkennt der Kunde einen Teil des Abschlags nicht
  an, tragen Sie beim Zahlungseingang den Betrag unter **Gekürzt** ein
  (siehe [Abschlagsrechnungen](#abschlagsrechnung)); die Schlussrechnung
  fordert ihn dann neu.
- **Erst den Nachlass stornieren, dann die Rechnung.** Ein Storno hebt
  die ganze Rechnung auf; bliebe der Nachlass stehen, bekäme der Kunde
  ihn doppelt gutgeschrieben. Deshalb lässt sich eine Rechnung mit
  festgeschriebenem Nachlass erst stornieren, wenn der Nachlass storniert
  ist, siehe unten. Ein Nachlass, der noch Entwurf ist, sperrt nicht;
  nach dem Storno der Rechnung lässt er sich aber nicht mehr
  festschreiben und ist zu löschen.

### Nachlass stornieren {#nachlass-stornieren}

Der seltene Fall: Eine Rechnung mit Nachlass ist falsch und muss
storniert werden. Dann:

1. Öffnen Sie die Rechnungskorrektur und klicken „Weitere …“, **Nachlass
   stornieren**. Es entsteht eine festgeschriebene Stornorechnung, die
   den Nachlass aufhebt; die Rechnungskorrektur steht danach auf
   „Storniert“, und die Rechnung fordert wieder den vollen Betrag.
2. Stornieren Sie dann die Rechnung wie gewohnt mit **Stornieren und
   neu schreiben**.
3. Schicken Sie dem Kunden **beide** Stornos, das des Nachlasses und das
   der Rechnung, dann die Neufassung.

Warum beide: Der Kunde hat den Nachlass bekommen und gebucht. Ein Storno,
das er nicht erhält, ändert nur Ihre Bücher, nicht seine; am Ende passten
Ihre Umsatzsteuer und seine Vorsteuer nicht mehr zusammen. Je Beleg ein
eigenes Storno sorgt außerdem dafür, dass der Steuerberater jeden Beleg
genau einem Gegenbeleg zuordnen kann. Nur wenn der Nachlass nie
hinausgegangen ist, bleibt sein Storno bei Ihnen.

Das Storno eines Nachlasses erhöht die Forderung wieder. Als E-Rechnung
geht es deshalb als korrigierte Rechnung hinaus, nicht als Gutschrift.

Rechnungskorrekturen entstehen nur so; ihre Liste hat kein „+“.
