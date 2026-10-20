# Leistung

Unter „Leistung“ steht, was für ein Projekt aufgelaufen ist: eigene
Stunden und Mengen in der Erfassung, zugekaufte Leistungen in den
Eingangsrechnungen. Beides landet am Ende in derselben Rechnung an den
Kunden.

## Erfassung {#erfassungszeile}

In der Erfassung trägt jede Person ein, was sie wann für welches Projekt
geleistet hat. Jede Zeile ist eine Leistung an einem Tag.

### Was Sie sehen

Ohne besonderes Recht sehen Sie nur Ihre eigenen Zeilen. Wer für andere
erfassen darf (etwa die Büroleitung, die Stundenzettel nachträgt), sieht
alle und hat zusätzlich das Feld **Person** und den Filter nach Person.

Über der Liste steht die **Zeitsumme** der gefilterten Zeilen, etwa für
„Diese Woche“. Die Spalten:

| Spalte | Inhalt |
|---|---|
| Datum, Von, Bis | wann gearbeitet wurde |
| Dauer | aus Von und Bis gerechnet |
| Umfang | Dauer oder Menge mit Einheit |
| Projekt | |
| Worauf | Auftragsposition mit Auftragsnummer, sonst die Katalogleistung |
| Person | nur mit dem Recht für andere |
| Beschreibung | |
| Zustand | offen, abgerechnet oder nicht abrechenbar |

Die Filter: **Sortierung** (Neueste zuerst; Nachweis: Projekt, Art,
Datum; Tagebuch: Projekt, Datum, Art; Person, dann Datum; Leistung, dann
Datum), **Zeitraum** (Heute, Diese Woche, Letzte Woche, Dieser Monat,
Letzter Monat, Dieses und Letztes Quartal, Dieses und Letztes Jahr,
Letzte 7 und 30 Tage), **Zustand**, Kunde, Projekt, **Art der Erfassung**
(Zeit, Menge, Pauschale), Leistung und Person. Die Zeitraumfilter sind
relativ: Ein Lesezeichen auf „Letzter Monat“ zeigt immer den Vormonat.

Die Suche findet Projektnummer und -bezeichnung, Personen und Wörter aus
der Beschreibung. Mehrere Wörter müssen alle vorkommen; in
Anführungszeichen gilt eine Wortgruppe als ein Wort.

### Eine Zeile erfassen

In der Liste „+“. Die Felder erscheinen der Reihe nach, je nachdem, was
Sie wählen:

1. **Datum**: steht auf heute. Erfasst wird für vergangene Tage und
   heute, nicht im Voraus.
2. **Projekt**: nur laufende Projekte.
3. **Auftragsposition**: die beauftragte Leistung, auf die Sie arbeiten.
   Zur Wahl stehen die Positionen festgeschriebener Aufträge dieses
   Projekts. Das ist der Regelfall: Preis und Einheit kommen dann aus dem
   Auftrag.
4. **Leistung aus dem Katalog**: nur, wenn Sie keine Auftragsposition
   wählen, für Arbeit ohne Auftrag. Zur Wahl stehen die kontierbaren
   Katalogpositionen.
5. Je nach Art der Leistung:
   - **Zeit**: **Von** und **Bis**. Getippt wird etwa „0830“; die Dauer
     rechnet Paper-Werk. Bis muss nach Von liegen, am selben Tag; eine
     Schicht über Mitternacht teilen Sie auf zwei Zeilen auf.
   - **Menge**: die **Menge** in der Einheit der Leistung, etwa Kilometer
     einer Anfahrt.
   - **Pauschale**: keine Menge, sie ist immer 1. Tragen Sie Von und Bis
     ein, gilt die Zeile als Aufwand fürs Controlling und wird **nicht
     abrechenbar**. Die Pauschale zum Abrechnen erfassen Sie einmal ohne
     Uhrzeiten. Ein Hinweis unter den Feldern sagt das.
6. **Beschreibung**: was getan wurde; erscheint im Leistungsnachweis.
7. **Abrechenbar** (nur mit dem Recht für andere): ausschalten für
   Gewährleistung oder Kulanz. Die Zeile zählt dann in der
   Nachkalkulation, kommt aber nie auf eine Rechnung.

**Sichern und neu hinzufügen** öffnet die nächste leere Zeile mit
demselben Projekt (und derselben Person); so erfassen Sie einen ganzen
Stapel, ohne das Projekt jedes Mal neu zu wählen.

Stundenzettel aus Excel lassen sich über **Importieren** oben in der
Liste einlesen. Die Spalten heißen datum, person, projekt, auftrag,
position, leistung, von, bis, menge, beschreibung und abrechenbar; Projekt
und Auftrag stehen als Nummer, die Person als Anmeldename. Der Import legt
nur neue Zeilen an und überspringt Zeilen, die es genauso schon gibt.
**Exportieren** gibt die Zeilen als Tabelle aus.

### Zustände

| Zustand | Bedeutung |
|---|---|
| Offen | abrechenbar und auf keiner Rechnung |
| Abgerechnet | steht auf einer Rechnung, auch auf einem Rechnungsentwurf |
| Nicht abrechenbar | „Abrechenbar“ ausgeschaltet oder Pauschale mit Uhrzeiten |

Eine Zeile, die auf einer Rechnung steht, auch auf einem Entwurf, lässt
sich nicht mehr ändern. Soll sie geändert werden, nehmen Sie die Position
aus dem Rechnungsentwurf; danach ist die Zeile wieder frei.

Jede Änderung einer Zeile steht im **Verlauf** („Weitere …“): wer, wann,
alter und neuer Stand. Einen früheren Stand zurückholen lässt sich dort
nicht.

### Leistungsnachweis

Markieren Sie die Zeilen (etwa gefiltert auf ein Projekt und den letzten
Monat, alle Zeilen der Seite mit dem Häkchen oben) und wählen Sie unter
„Aktion wählen“:

- **Leistungsnachweis als PDF (mit Uhrzeit)**: je Zeile Datum, Von, Bis,
  Leistung, Umfang, Person und Beschreibung, darunter die Summe der
  Stunden und was davon ohne Berechnung ist.
- **Leistungsnachweis als PDF (kompakt)**: ohne Von und Bis, für Kunden,
  die nur die Stunden je Tag sehen wollen.

Das PDF öffnet sich in einem neuen Reiter, in der Reihenfolge der Liste.
Wählen Sie dafür vorher die passende Sortierung, etwa „Nachweis“. Der
Nachweis bekommt keine Nummer und wird nicht gespeichert; wer ihn morgen
neu zieht, bekommt den Stand von morgen. An den Zeilen ändert er nichts.

### In Rechnung übernehmen

Markieren Sie die Zeilen eines Projekts und wählen Sie **In Rechnung
übernehmen**. Eine Vorschau zeigt, welche Positionen daraus werden: eine je
Leistung, nicht eine je Zeile. Die Zeit wird je Leistung auf die Summe
aufgerundet, auf die Viertelstunde. Der Preis kommt aus der
Auftragsposition, bei Katalogleistungen aus dem Katalog, Stand heute.

Unter der Vorschau wählen Sie das Ziel:

- **Neuen Rechnungsentwurf anlegen**,
- **Neue Abschlagsrechnung anlegen (Entwurf)**,
- **Neue Schlussrechnung anlegen (Entwurf, Abschläge werden abgesetzt)**,
- oder **An … anhängen**: ein vorhandener Rechnungsentwurf dieses
  Projekts oder eine Sammelrechnung des Kunden ohne Projekt.

Nach der Bestätigung meldet Paper-Werk, wie viele Zeilen als wie viele
Positionen übernommen wurden, mit Verweis auf die Rechnung. Zeilen, die
nicht abrechenbar oder schon abgerechnet sind, werden übergangen; die
Meldung nennt sie.

Die Auswahl muss zu genau einem Projekt gehören. Für das Übernehmen
braucht es das Recht, Belege anzulegen.

Derselbe Vorgang geht auch von der Rechnung aus: am Rechnungsentwurf
„Weitere …“, **Erbrachte Leistungen hinzufügen**. Dort haken Sie an, was
auf dem Projekt offen ist, eigene Leistung und Zukauf.

## Nicht abgerechnet {#liegengeblieben}

Die Arbeitsliste gegen das Vergessen. Oben drei Zahlen:

- **Eigene Leistung**: erfasste Stunden und Mengen ohne Beleg.
- **Zugekaufte Leistung**: weiterberechenbar, noch nicht weiterberechnet.
- **Nicht zugeordnet**: Beträge aus Eingangsrechnungen, die auf keinem
  Projekt liegen.

**Erbracht und nicht berechnet** listet die Projekte nach Betrag: Kunde,
eigene Leistung, Zugekauftes, Gesamt und seit wann etwas liegt. Der
Projektname führt in die Projektakte, **abrechnen** in die Erfassung,
gefiltert auf das Projekt; dort markieren und „In Rechnung übernehmen“.
Zeilen auf einem Rechnungsentwurf gelten hier noch als nicht abgerechnet,
denn ein Entwurf fordert noch nichts.

**Eingangsrechnungen ohne vollständige Zuordnung** listet fremde
Rechnungen, deren Positionen nicht ganz auf Projekte verteilt sind, mit
dem Rest. Ein Klick öffnet die Eingangsrechnung.

## Eingangsrechnungen {#eingangsrechnung}

Eingangsrechnungen sind Rechnungen von Lieferanten und Subunternehmern,
etwa eines Labors. Erfasst werden sie hier, damit ihre Positionen dem
Projekt zugeordnet und an den Kunden weiterberechnet werden können.

**Die Liste** zeigt Datum, Lieferant, Nummer, Betrag netto, Zugeordnet,
Rest, die Projekte und ein Symbol, wenn das Dokument in Paperless liegt.
Ein Rest bedeutet: Nicht alle Positionen sind verteilt. Filter nach
Lieferant und Datum als Zeitraum.

**Von Hand erfassen:** „+“, dann **Lieferant** (ein Kontakt mit der Rolle
Lieferant), **Rechnungsnummer** wie auf seinem Beleg, **Rechnungsdatum**
und **Betrag netto**, unter „Weiteres“ eine Notiz. Darunter die Positionen,
je Zeile:

- **Projekt**, für das die Position angefallen ist,
- **Auftragsposition**, freiwillig: die beauftragte Leistung, zu der der
  Einkauf gehört,
- **Bezeichnung** wie auf der Lieferantenrechnung,
- **Einheit**, **Menge**, **Einkaufspreis netto** je Einheit,
- **Betrag netto**: leer lassen, dann gilt Menge mal Einkaufspreis;
  abweichend eintragen bei Rabatt auf der Zeile,
- **Weiterberechenbar**: ausschalten, wenn Sie die Kosten selbst tragen.
  Sie bleiben dann im Projektergebnis, kommen aber auf keine Rechnung.

Ergeben die Positionen nicht den Rechnungsbetrag (Skonto, Rabatt), weist
Paper-Werk darauf hin; der Rest bleibt offen, bis er verteilt ist. Eine
Gutschrift des Lieferanten erfassen Sie als eigene Eingangsrechnung mit
negativem Betrag.

**E-Rechnung einlesen:** Der Knopf über der Liste nimmt das PDF
(ZUGFeRD/Factur-X) oder das XML einer E-Rechnung und legt daraus die
Eingangsrechnung mit allen Positionen an. Wählen Sie dabei ein
**Projekt**, kommen alle Positionen darauf; leer gelassen, gilt das
Projekt, das der Lieferant als Referenz angegeben hat, wenn es dazu
passt. Die Meldung sagt, was übernommen wurde. Prüfen Sie danach die
Zuordnung in den Positionen.

Eingangsrechnungen, die über Paperless hereinkommen, stehen mit Verweis
auf das Dokument im Archiv da; das PDF liegt dort, nicht in Paper-Werk.

**Weiterberechnen:** Weiterberechenbare Positionen kommen über „In Rechnung
übernehmen“ oder „Erbrachte Leistungen hinzufügen“ auf die Rechnung an den
Kunden. Mit Auftragsposition und passender Einheit gilt deren Preis;
sonst steht genau der Einkaufsbetrag auf der Rechnung. Einen Aufschlag
tragen Sie danach in der Rechnung ein. Eine weiterberechnete Position
lässt sich nicht mehr ändern; die Spalte „Abgerechnet“ nennt die Rechnung.

### Fremdleistungen {#fremdleistung}

Die Liste aller zugekauften Positionen quer über die Eingangsrechnungen
erreichen Sie aus der Projektakte („Zugekaufte Leistung“); in der
Seitenleiste steht sie nicht. Sie zeigt Datum, Projekt,
Auftragsposition, Bezeichnung, Menge, Einkauf, Zustand und die
Eingangsrechnung. Filter nach Zustand (offen, abgerechnet, nicht
abrechenbar), Lieferant, Projekt und Datum. Die Aktion **In Rechnung
übernehmen** funktioniert wie in der Erfassung, mit Vorschau und Wahl des
Rechnungsentwurfs. Bearbeitet werden die Positionen in ihrer
Eingangsrechnung oder hier; alle Änderungen stehen im Verlauf.
