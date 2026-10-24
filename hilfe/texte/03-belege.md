# Belege: was für alle gilt

Angebot, Auftrag, Lieferschein, Rechnung in allen Arten, Stornorechnung,
Rechnungskorrektur und Mahnung sind Belege. Sie teilen Aufbau, Zustände
und die meisten Knöpfe. Dieses Kapitel beschreibt das Gemeinsame; was
eine Belegart anders macht, steht bei ihr.

## Zustände: Entwurf, festgeschrieben, storniert {#belegstatus}

**Entwurf.** Jeder Beleg beginnt als Entwurf. Sie können ihn beliebig oft
ändern, sichern und als PDF ansehen; das PDF trägt dann das Wasserzeichen
„Entwurf“. Ein Entwurf hat noch keine Nummer, in Listen heißt er etwa
„Entwurf 54“. Nur ein Entwurf lässt sich löschen.

**Festgeschrieben.** Mit dem Versenden (oder beim Auftrag mit
„Festschreiben“) bekommt der Beleg seine Nummer, sein PDF wird erzeugt und
eingefroren, und ab dann ist er unveränderlich. In den Listen zeigt ein
Schloss diesen Zustand. Wer festgeschrieben hat und wann, steht im Reiter
„Status“.

**Storniert.** Eine festgeschriebene Rechnung, die durch eine
Stornorechnung aufgehoben wurde. Sie bleibt im Bestand und ist in den
Listen mit einem durchgestrichenen Kreis markiert.

### Nummern

Die Nummer entsteht beim Festschreiben, lückenlos je Jahr und Kreis:

| Kreis | Beispiel | Belegarten |
|---|---|---|
| Angebot | AN-2026-0001 | Angebote |
| Auftrag | AU-2026-0001 | Aufträge und Nachträge |
| Lieferschein | LS-2026-0001 | Lieferscheine |
| Rechnung | RE-2026-0001 | Rechnungen, Abschlags-, Schluss-, Teilschluss- und Stornorechnungen, Rechnungskorrekturen |
| Mahnung | MA-2026-0001 | Mahnungen |

Alle Rechnungsarten teilen sich einen Kreis, weil sie steuerlich Rechnungen
sind. Ein gelöschter Entwurf reißt keine Lücke, er hatte noch keine Nummer.

### Wieder öffnen

Angebot und Auftrag lassen sich nach dem Festschreiben wieder öffnen:
„Weitere …“, **Wieder öffnen**. Der Beleg wird wieder Entwurf und behält
seine Nummer; mit dem nächsten Versenden oder Festschreiben entsteht das
PDF neu. Im Reiter „Status“ steht unter „Wiedereröffnet“, wer das wann
getan hat. Für diesen Knopf braucht es ein eigenes Recht; fehlt er,
fragen Sie den Administrator.

Solange ein Auftrag wieder offen ist, kann niemand Stunden auf ihn
kontieren. Schreiben Sie ihn bald wieder fest.

Rechnungen, Lieferscheine und Mahnungen lassen sich nicht wieder öffnen.
Eine falsche Rechnung korrigieren Sie über „Stornieren und neu schreiben“
oder einen Nachlass, siehe [Stornorechnungen](#stornorechnung) und
[Rechnungskorrekturen](#rechnungskorrektur).

## Der Belegkopf {#belegkopf}

Oben in der Maske stehen die Angaben zum ganzen Beleg.

**Info**

- **Projekt** und **Kunde**: Ein Beleg hängt an einem Projekt oder direkt
  an einem Kunden. Mit Projekt genügt das Projekt; die Anschrift kommt vom
  Kunden des Projekts. Abgeschlossene Projekte stehen nicht zur Wahl.
- **Betreff**: erscheint auf dem Beleg und in der E-Mail.
- **Bestellnr. des Kunden**: die Bestellnummer, auf die der Kunde sich
  bezieht; sie steht auf dem Beleg und in der E-Rechnung.

**Empfänger**

- **Empfänger**: das Anschriftfeld, genau so, wie es auf dem Blatt steht,
  Zeile für Zeile.
- **E-Mail des Empfängers**: die Adresse, an die „Versenden“ schickt.
- **USt-IdNr.** und **Steuerfall**: Der Steuerfall steht im Normalfall auf
  „Inland (Regelbesteuerung)“. Die anderen Fälle (§ 13b UStG, Leistungen
  an Unternehmen in der EU oder außerhalb, Ausfuhr) setzen den Vermerk auf
  dem Beleg und in der E-Rechnung; alle Positionen müssen dann 0 % haben.

Wählen Sie Projekt oder Kunde, füllt Paper-Werk Empfänger, E-Mail,
USt-IdNr., Steuerfall, Zahlungsziel und die Angaben im Reiter
„E-Rechnung“ aus den Stammdaten des Kunden, sofern Sie diese Felder nicht
schon selbst ausgefüllt haben. Die Felder leuchten dabei kurz auf. Danach
gehören die Werte dem Beleg: Eine spätere Adressänderung beim Kunden
ändert ihn nicht mehr.

**Termine**

- **Belegdatum**: steht beim Anlegen auf heute.
- **Leistungsdatum**: nur an Rechnungen, Pflichtangabe nach § 14 UStG; der
  Tag, an dem die Leistung vollendet oder abgenommen ist. Leer gelassen,
  gilt das Ende des Zeitraums darunter.
- **Leistung von / bis**: der Zeitraum, in dem geleistet wurde. Am Angebot
  und Auftrag heißen die Felder „Ausführung ab / bis“ und sind ein
  geplanter Termin ohne steuerliche Bedeutung; am Lieferschein steht das
  „Lieferdatum“, an der Abschlagsrechnung „Leistungsstand ab“ und
  „Stichtag“.
- **Zahlungsziel (Tage)**: daraus wird beim Festschreiben das Datum
  „Zahlbar bis“.

An Rechnungen stehen hinter manchen Beschriftungen Kürzel wie „(BT-72)“.
Sie nennen das Feld der E-Rechnung, in das der Wert geht, und sind für
Rückfragen des Steuerberaters oder eines Rechnungsportals gedacht.

### Die Reiter

- **Texte**: der Text über den Positionen (Anrede, Einleitung) und unter
  den Positionen (Schluss, Zahlungsbedingungen). Mit „Textvorlagen“
  fügen Sie gespeicherte Texte ein.
- **E-Rechnung** (nur an Rechnungen): Name, Straße, PLZ, Ort und Land des
  Empfängers einzeln, wie die E-Rechnung sie verlangt, und die
  **Käuferreferenz**, bei Behörden die Leitweg-ID. Alles kommt aus den
  Stammdaten; ändern Sie es hier nur, wenn dieser eine Beleg anders
  adressiert werden soll.
- **Status**: Zustand, Nummer, Vorgänger (aus welchem Beleg dieser
  entstand), wer wann festgeschrieben und versendet hat, „Zahlbar bis“, die
  Summen je Steuersatz, das Dokument und der Archivverweis. Unter
  „Dokument“ stehen das PDF mit Prüfsumme und Vorlagenversion, bei
  E-Rechnungen die XML-Datei und, falls die Rechnung neu ausgestellt wurde,
  die früheren Fassungen. „Im Archiv“ zeigt die Dokumentnummer in
  Paperless mit Verweis, „wird abgelegt …“ während der Übertragung oder
  „nicht archiviert“.
- **Zahlungen** (nur an festgeschriebenen Rechnungen): alle
  Zahlungseingänge auf diese Rechnung mit Datum, Betrag, Skonto, Kürzung,
  Art und Verwendungszweck, darunter, was offen bleibt.

## Positionen {#positionen}

Unter dem Kopf stehen die Positionen. Die Spalten:

| Spalte | Inhalt |
|---|---|
| Pos. | Positionsnummer, frei wählbar |
| Bezeichnung | Kurztext der Position, Pflicht |
| Menge, Einheit | z. B. 6 Std, 1 pausch |
| Preis (Netto) | Einzelpreis ohne Umsatzsteuer, Pflicht |
| USt. | Steuersatz aus der Tabelle der Steuersätze |
| Betrag | Menge mal Preis, wird beim Tippen mitgerechnet |

Unter jeder Position steht in einer zweiten Zeile der **Langtext**, die
ausführliche Beschreibung; er wächst mit dem Text. An Rechnungen stehen
daneben „Leistung von“ und „Leistung bis“ je Position, an Angebot und
Auftrag der Haken **Optional**.

### Aus dem Katalog

Über jeder neuen Zeile steht die Katalogsuche. Tippen Sie einen Teil von
Nummer, Bezeichnung oder Langtext; die Treffer kommen aus dem
Leistungskatalog. Die Auswahl füllt Bezeichnung, Langtext, Einheit, Preis
und Steuersatz. Alles bleibt danach änderbar und betrifft nur diesen
Beleg, nicht den Katalog.

Eine gespeicherte Position hat keine Katalogsuche mehr. Soll eine andere
Katalogposition an ihre Stelle, löschen Sie die Zeile und wählen neu.

### Nummern der Positionen

Neue Zeilen bekommen ihre Nummer vorgeschlagen: hinter 10, 20, 30 folgt 40;
hinter „01.01.0010“ folgt „01.01.0020“. Die Nummer ist frei änderbar, auch
für Ordnungszahlen eines Leistungsverzeichnisses. Beim Sichern werden die
Positionen nach ihrer Nummer sortiert. In Auftrag und Rechnung behält eine
Position die Nummer aus dem Beleg davor, auch wenn sie über erfasste
Leistungen abgerechnet wird. Ist die Nummer in der Rechnung schon vergeben,
bekommt die Position die nächste freie.

### Zeilenarten

Links in der zweiten Zeile wählen Sie die **Zeilenart**:

- **Leistung**: der Normalfall, mit Menge, Preis und Betrag.
- **Titel**: eine Überschrift, etwa „01 Rohbau“. Im PDF steht sie fett,
  und nach der letzten zugehörigen Position folgt „Summe Titel 01“. Zum
  Titel gehören alle Positionen, deren Nummer mit der Titelnummer und
  einem Punkt beginnt (01.0010, 01.0020 …).
- **Text**: ein freier Absatz ohne Menge und Preis, etwa ein Hinweis
  zwischen den Positionen.
- **Zuschlag**: ein Prozentsatz auf andere Positionen, etwa Nebenkosten
  3 %. Zwei zusätzliche Felder erscheinen: **Zuschlag %** und **Zuschlag
  auf**. „Zuschlag auf“ leer heißt: auf alle Leistungen; eine Titelnummer
  (01) heißt: auf diesen Titel; eine Positionsnummer (01.0020) heißt: auf
  genau diese Position. Den Betrag rechnet Paper-Werk selbst und rechnet
  ihn beim Festschreiben nach. Im PDF steht darunter der Rechenweg, etwa
  „3 % auf 9.500,00“. Andere Zuschläge zählen nie mit: Nebenkosten auf
  alle Leistungen rechnen also nicht auf einen Erschwerniszuschlag. Sonst
  rechneten zwei Zuschläge auf alle Leistungen jeweils auf den anderen.

Felder, die in einer Zeilenart keine Bedeutung haben, sind gesperrt.

### Optionale Positionen

An Angebot und Auftrag markiert der Haken **Optional** eine Position, die
der Kunde zusätzlich abrufen kann. Sie zählt nicht in die Summe; im PDF
steht ihr Betrag in Klammern. Beim Erzeugen einer Rechnung oder eines
Lieferscheins bleibt sie weg: Wird die Option abgerufen, tragen Sie sie in
der Rechnung als gewöhnliche Position ein.

Auch ein Zuschlag kann optional sein, etwa 50 % für Messungen an Samstagen.
Im PDF steht dann nur der Satz („50 % auf Pos. 3.1“), kein Betrag, denn
auf welchen Teil er anfällt, zeigt erst die Abrechnung. Solange eine
Rechnung zum Auftrag ein Entwurf ist, nennt ihre Maske oben die
optionalen Zuschläge des Auftrags, die sie noch nicht enthält. Ist einer
angefallen, legen Sie die betroffene Leistung als eigene Position an (etwa
3.1.1 „Raumluftmessung am Samstag“) und darunter einen Zuschlag mit
derselben Bezeichnung wie im Auftrag, „Zuschlag auf“ 3.1.1.

### Zeilen hinzufügen und löschen

Ein neuer Beleg bringt drei leere Zeilen mit, ein Beleg mit Positionen
eine. Weitere Zeilen fügt der Link unter den Positionen an. Eine leere
Zeile wird beim Sichern ignoriert.

Zum Löschen klicken Sie die Mülltonne am Ende der Zeile; gelöscht wird
beim Sichern. Die Position, in der der Cursor steht, ist farbig
hinterlegt.

An festgeschriebenen Belegen stehen die Positionen nur zum Lesen da,
leere Langtexte und Daten erscheinen dann gar nicht.

## PDF anzeigen {#pdf}

**PDF anzeigen** öffnet das PDF in einem neuen Reiter. Vorher sichert die
Maske, was Sie eingetragen haben, das PDF zeigt also den Stand vor Ihnen.
Am Entwurf entsteht das PDF bei jedem Klick neu und trägt das Wasserzeichen
„Entwurf“; am festgeschriebenen Beleg kommt immer die eingefrorene Datei,
die auch der Kunde bekommen hat.

Rechnungen, Stornorechnungen und Rechnungskorrekturen sind E-Rechnungen:
Das PDF enthält die maschinenlesbaren Daten (ZUGFeRD). Kunden mit dem
Zustellweg XRechnung, meist Behörden, bekommen stattdessen eine
XML-Datei.

## Versenden {#versenden}

**Versenden** öffnet eine eigene Seite. Oben steht, welcher Beleg an wen
über welchen Betrag geht, und der Hinweis: **Der Beleg wird dabei
festgeschrieben**, gleich welchen Weg Sie wählen. Er bekommt seine Nummer,
das PDF wird eingefroren.

Darunter die Nachricht:

- **Empfänger**: vorbelegt mit der E-Mail-Adresse aus dem Belegkopf.
- **Betreff**: etwa „Rechnung RE-2026-0042“.
- **Nachricht**: das Anschreiben aus dem Textbaustein für E-Mails dieser
  Belegart; mit „Textvorlagen“ wählen Sie einen anderen.

Die Seite nennt die Datei, die angehängt wird (PDF, PDF mit E-Rechnung
oder XRechnung), und den Zustellweg des Kunden. Eine Kopie geht als
Blindkopie an die Absenderadresse der Firma; die Seite nennt sie. Ist auf
dem Server kein Postausgang eingerichtet, steht dort ein Hinweis: Dann
geht keine Mail hinaus, der Beleg wird trotzdem festgeschrieben.

Die Knöpfe unten:

| Knopf | Wirkung |
|---|---|
| Abbrechen | Zurück zum Beleg, nichts geschieht |
| Nur festschreiben | Nummer und PDF, keine Mail; nur am Entwurf |
| Festschreiben und herunterladen | Wie oben, dazu lädt der Browser die Datei herunter, etwa für Post oder ein Rechnungsportal |
| Festschreiben und senden | Festschreiben und per E-Mail schicken |

Ist der Beleg schon festgeschrieben, aber noch nicht versendet, heißen die
Knöpfe „Herunterladen“ und „Per E-Mail senden“.

Auch das Herunterladen steht danach im Verlauf des Belegs, denn auch
damit geht der Beleg aus dem Haus.

Je nach Beleg erscheinen über den Knöpfen Hinweise, die vor dem Klick
gelesen werden wollen:

- **Passt das Format zum Kunden?** Der Zustellweg passt nicht zur
  Käuferreferenz, etwa eine Leitweg-ID ohne XRechnung.
- **Mehr als beauftragt**: Positionen, die gegen einen Auftrag abrechnen,
  überschreiten die beauftragte Menge. Festgeschrieben wird dann nur mit
  dem Haken „Ja, trotzdem festschreiben“. Sonst passen Sie die Menge an
  oder legen einen Nachtrag an.
- **Abschläge nicht vollständig bezahlt**: an Schluss- und
  Teilschlussrechnungen, siehe [Schlussrechnungen](#schlussrechnung).

### Erneut versenden

Am schon versendeten Beleg steht unter „Weitere …“ **Erneut versenden**,
etwa wenn der Kunde die Rechnung nicht gefunden hat. Dieselbe Seite,
nur mit „Herunterladen“ und „Erneut senden“. Das Datum des ersten
Versands bleibt stehen; der neue Versand kommt im Reiter „Status“ als
weitere Zeile dazu.

### Was beim Festschreiben geprüft wird

Paper-Werk schreibt nicht fest, wenn etwas fehlt, und sagt in einer roten
Meldung, was:

- Der Beleg hat keine Positionen.
- An einer Rechnung fehlt das Leistungsdatum (§ 14 Abs. 4 Nr. 6 UStG) oder
  die Empfängeranschrift.
- An einer Abschlagsrechnung fehlen „Leistungsstand ab“ oder „Stichtag“.
- Der Steuerfall verlangt 0 %, aber eine Position hat einen anderen
  Steuersatz.
- Ihre Firma ist als Kleinunternehmer eingetragen, aber eine Position hat
  Umsatzsteuer.
- An einer Schlussrechnung hat sich seit dem Absetzen geändert, was auf
  einen Abschlag bezahlt ist. Dann „Abschläge absetzen“ noch einmal
  ausführen.

## Aus einem Beleg den nächsten erzeugen {#umwandeln}

Aus einem festgeschriebenen Beleg entsteht der nächste:

| Aus | Knopf unter „Weitere …“ | Es entsteht |
|---|---|---|
| Angebot | Auftrag erzeugen | Auftrag |
| Angebot | Rechnung erzeugen | Rechnung, ohne Auftrag dazwischen |
| Auftrag | Lieferschein erzeugen | Lieferschein, Positionen ohne Preise |
| Auftrag | Rechnung erzeugen | Rechnung |
| Lieferschein | Rechnung erzeugen | Rechnung |
| Abnahme | Rechnung erzeugen (vorn) | Schluss- oder Teilschlussrechnung |

Der neue Beleg ist ein Entwurf und öffnet sich gleich. Er übernimmt
Projekt, Kunde, Betreff, Anschrift, Texte, Termine, Steuerfall und alle
Positionen, aus dem Beleg davor, nicht neu aus den Stammdaten. Optionale
Positionen gehen nur in einen Auftrag mit. Der Vorgänger steht im Reiter
„Status“.

Ein Entwurf lässt sich nicht umwandeln; schreiben Sie ihn vorher fest.

Dieselben Vorgänge gibt es als Aktion in den Listen, für mehrere Belege
auf einmal.

## Duplizieren {#duplizieren}

Angebote, Rechnungen und Abschlagsrechnungen lassen sich duplizieren:
„Weitere …“, **Angebot duplizieren** oder **Rechnung duplizieren**. Es
entsteht ein neuer Entwurf derselben Art mit allen Angaben und
Positionen, gleich ob das Original Entwurf oder festgeschrieben ist. Das
Original bleibt unverändert. Gedacht ist das für das zweite Angebot an
einen anderen Kunden oder die nächste Rechnung gleichen Inhalts.

Bei Rechnungen gilt: Positionen aus Fremdleistungen kommen nicht mit,
denn eine Fremdleistung wird nur einmal weiterberechnet. Erfasste Stunden
bleiben auf der ursprünglichen Rechnung abgerechnet. Schlussrechnungen
lassen sich nicht duplizieren, sie würden die Abschläge ein zweites Mal
absetzen.
