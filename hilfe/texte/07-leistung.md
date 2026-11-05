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
| Position / Leistung | Auftragsnummer und Auftragsposition mit Positionsnummer, sonst die Katalogleistung |
| Person | nur mit dem Recht für andere |
| Beschreibung | |
| Zustand | offen, abgerechnet oder nicht abrechenbar |

Die Filter: **Sortierung** (Neueste zuerst; Nachweis: Projekt, Art,
Datum; Tagebuch: Projekt, Datum, Art; Auftrag: Projekt, Position, Datum;
Person, dann Datum; Leistung, dann Datum), **Zeitraum** (Heute, Diese
Woche, Letzte Woche, Dieser Monat, Letzter Monat, Dieses und Letztes
Quartal, Dieses und Letztes Jahr, Letzte 7 und 30 Tage), **Zustand**, Kunde, Projekt, **Art der Erfassung**
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

### In Rechnung übernehmen {#in-rechnung-uebernehmen}

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

**Titel und Positionsnummern.** Eine Leistung auf eine Auftragsposition
behält deren Nummer, etwa 2.20. Steht die Position im Auftrag unter einem
Titel, kommt der Titel mit auf die Rechnung („2 Erkundung“, bei
Unterteilung auch „01“ und „01.02“), samt Zwischensumme. Hat die Rechnung
schon eine Zeile mit dieser Nummer, etwa einen eigenen Titel, bleibt sie
und es kommt kein zweiter dazu. Texte aus dem Auftrag, etwa
Vorbemerkungen, werden nicht übernommen; fügen Sie sie bei Bedarf von Hand
ein.

**Nebenkosten und andere Zuschläge.** Zuschläge des Auftrags, etwa
„Nebenkosten 3 %“, kommen mit auf die Rechnung; die Einzelheiten stehen
unter [Zuschläge beim Übernehmen](#zuschlag-uebernehmen).

**Mehrfach übernehmen.** Übernehmen Sie zu einer Auftragsposition, die auf
der Rechnung schon steht, ein zweites Mal, wächst die vorhandene Position:
Die Menge wird addiert, der Leistungszeitraum erweitert. Es entsteht keine
zweite Position mit neuer Nummer. Das gilt auch, wenn eigene Stunden und
Zukauf auf dieselbe Auftragsposition in einem Durchgang kommen. Ausnahme:
Haben Sie an der vorhandenen Position Preis oder Einheit von Hand
geändert, entsteht eine neue Position, damit nichts zu einem fremden
Preis addiert wird. Zeit wird je Übernahme auf die Viertelstunde
aufgerundet; zweimal übernommen kann das eine Viertelstunde mehr ergeben
als in einem Durchgang.

Nach der Bestätigung meldet Paper-Werk, wie viele Zeilen als wie viele
Positionen übernommen wurden, mit Verweis auf die Rechnung. Zeilen, die
nicht abrechenbar oder schon abgerechnet sind, werden übergangen; die
Meldung nennt sie.

Die Auswahl muss zu genau einem Projekt gehören. Für das Übernehmen
braucht es das Recht, Belege anzulegen.

Derselbe Vorgang geht auch von der Rechnung aus: am Rechnungsentwurf
„Weitere …“, **Erbrachte Leistungen hinzufügen**. Dort haken Sie an, was
auf dem Projekt offen ist, eigene Leistung und Zukauf. Zukauf ohne
passende Auftragsposition nehmen Abschlags- und Schlussrechnung nicht
auf, siehe
[Fremdleistungen in Abschlag und Schlussrechnung](#fremdleistung-zuordnen).

### Zuschläge beim Übernehmen {#zuschlag-uebernehmen}

Steht im Auftrag ein Zuschlag, etwa „Nebenkosten 3 %“ oder „Erschwernis
10 % auf 2.20“, legt Paper-Werk ihn beim Übernehmen auf der Rechnung an.
Das gilt für jede Rechnungsart: gewöhnliche Rechnung, Abschlags-,
Teilschluss- und Schlussrechnung.

**Wann ein Zuschlag mitkommt.** Alle vier Bedingungen müssen erfüllt sein:

1. Er steht in dem Auftrag (oder Nachtrag), zu dem eine übernommene
   Position gehört. Leistung ohne Auftragsposition, etwa nur aus dem
   Katalog, bringt keinen Zuschlag mit.
2. Er ist nicht optional. Optionale Zuschläge, etwa „Samstag 50 %“,
   brauchen Ihre Entscheidung; die Rechnung zeigt sie als Hinweis,
   und Sie fügen sie bei Bedarf von Hand ein.
3. Er bezieht sich auf eine übernommene Position. Ist „Zuschlag auf“
   leer, gilt er für alle Positionen, kommt also mit jeder Position des
   Auftrags. Steht dort eine Nummer, etwa 2.20 oder der Titel 2, kommt er
   nur mit, wenn diese Position oder eine Position unter diesem Titel
   übernommen wird.
4. Die Rechnung hat noch keinen Zuschlag mit derselben Bezeichnung.
   Groß- und Kleinschreibung zählen dabei nicht.

**Betrag.** Der Betrag rechnet sich immer aus den Positionen der
Rechnung, nicht aus der Auftragssumme. Im Auftrag stehen 2.10 Probenahme
zu 95,00 €/Std, 2.20 Bodenprobe zu 145,00 €/Stk, „Erschwernis 10 % auf
2.20“ und „Nebenkosten 3 %“. Übernommen werden 2 Std und 3 Stk:

| Pos. | Bezeichnung | Betrag |
|---|---|---|
| 2.10 | Probenahme, 2 Std | 190,00 € |
| 2.20 | Bodenprobe, 3 Stk | 435,00 € |
| 2.90 | Erschwernis 10 % auf 435,00 | 43,50 € |
| 90 | Nebenkosten 3 % auf 625,00 | 18,75 € |

Ein Zuschlag rechnet nie auf einen anderen Zuschlag: Die Nebenkosten
nehmen die Erschwernis nicht mit. Ändern Sie danach Mengen oder Preise im
Entwurf, rechnet Paper-Werk die Zuschläge neu.

**Zweimal übernehmen.** Übernehmen Sie später weitere Leistung in
dieselbe Rechnung, kommt kein zweiter Zuschlag dazu. Der vorhandene wird
auf alle Positionen der Rechnung neu berechnet. Das gilt auch für einen
Zuschlag, den Sie selbst mit derselben Bezeichnung angelegt haben: Er
bleibt mit Ihrem Satz und Ihrer Nummer. Heißt Ihr Zuschlag anders, etwa
„Nebenkosten pauschal“ statt „Nebenkosten“, kommt der aus dem Auftrag
zusätzlich; löschen Sie dann einen der beiden. Haben Sie einen
übernommenen Zuschlag auf der Rechnung gelöscht, legt die nächste
Übernahme in diese Rechnung ihn wieder an.

**Positionsnummer.** Der Zuschlag behält die Nummer aus dem Auftrag, im
Beispiel 2.90 und 90. Ist diese Nummer auf der Rechnung schon besetzt,
etwa durch eine eigene Position 90 „Fahrtkosten“ oder eine Position
eines Nachtrags mit derselben Nummer, bekommt er die nächste freie
Nummer nach der höchsten auf der Rechnung. Ist 90 die höchste, wird es
100. Ist die höchste eine Unterposition, etwa 2.10, wird es 2.20; dann
steht der Zuschlag unter Titel 2 und zählt in dessen Zwischensumme, weil
die Nummer Reihenfolge und Titel bestimmt. In beiden Fällen stimmt seine
Nummer nicht mehr mit dem Auftrag überein. Prüfen Sie in diesem Fall die
Nummer und ändern Sie sie von Hand, etwa auf 91. Der Betrag ändert sich
dadurch nicht, denn worauf der Zuschlag rechnet, legt allein „Zuschlag
auf“ fest.

**Schlussrechnung.** Die Schlussrechnung nimmt jeden Zuschlag einmal,
berechnet auf die volle Leistung, und nicht die Summe der Zuschläge aus
den Abschlägen. Er kommt aus den Abschlägen und, falls er dort fehlt,
etwa bei älteren Abschlägen, aus dem Auftrag. Seine Nummer folgt
derselben Regel wie oben.

**Nebenkosten als gewöhnliche Position.** Stehen die Nebenkosten im
Auftrag nicht als Zuschlag, sondern als Position, etwa „Nebenkosten
pauschal, 1 psch“, kommen sie nicht von selbst. Ob und wann Sie sie
abrechnen, entscheiden Sie; fügen Sie die Position dann von Hand ein.

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
tragen Sie danach in der Rechnung ein. Abschlags-, Teilschluss- und
Schlussrechnung nehmen nur Fremdleistungen mit Auftragsposition und
passender Einheit auf, siehe
[Fremdleistungen in Abschlag und Schlussrechnung](#fremdleistung-zuordnen).

Eine weiterberechnete Position lässt sich nicht mehr ändern; die Spalte
„Abgerechnet“ nennt die Rechnung.

### Fremdleistungen {#fremdleistung}

Die Liste aller zugekauften Positionen quer über die Eingangsrechnungen
steht unter **Leistung › Fremdleistungen** und ist aus der Projektakte
verlinkt („Zugekaufte Leistung“). Sie zeigt Datum, Projekt,
Eingangsrechnung, Fremdschlüssel, Auftragsposition, Bezeichnung, Menge,
Einkauf, Zustand und die Rechnung an den Kunden. Filter nach Zustand (offen, abgerechnet, nicht
abrechenbar), Zuordnung (ohne Auftragsposition, Einheit passt nicht,
zugeordnet), Lieferant, Projekt und Datum. Die Aktion **In Rechnung
übernehmen** funktioniert wie in der Erfassung, mit Vorschau und Wahl des
Rechnungsentwurfs. Bearbeitet werden die Positionen in ihrer
Eingangsrechnung oder hier; alle Änderungen stehen im Verlauf.

Zwei Aktionen ordnen mehrere Fremdleistungen auf einmal einer
Auftragsposition zu:

- **Auftragsposition setzen**: Filtern Sie nach Projekt, markieren Sie die
  Zeilen und wählen Sie auf der folgenden Seite eine Position aus den
  festgeschriebenen Aufträgen des Projekts. „Keine“ entfernt die
  Zuordnung. Aus der Projektakte führt die Zeile „noch nicht zugeordnet“
  direkt zu den passenden Fremdleistungen.
- **Über Fremdschlüssel zuordnen**: Trägt eine Fremdleistung im Feld
  **Fremdschlüssel** die Artikelnummer des Lieferanten, und hat genau
  eine Auftragsposition des Projekts denselben Fremdschlüssel, wird diese
  gesetzt. Gibt es mehrere passende
  Positionen, etwa dieselbe Leistung je Geschoss, bleibt die Zeile offen.

Beide ändern nur Fremdleistungen, die noch auf keiner Rechnung stehen,
auch auf keinem Entwurf. Die Auftragsposition bestimmt beim Übernehmen
den Preis, wenn die Einheit passt.

### Fremdleistungen in Abschlag und Schlussrechnung {#fremdleistung-zuordnen}

Abschlags-, Teilschluss- und Schlussrechnung rechnen gegen den Auftrag ab.
Eine Fremdleistung kommt dort nur zum Preis ihrer Auftragsposition auf die
Rechnung, nie zum Einkaufspreis. Das gelingt nur, wenn beides stimmt:

- Die Fremdleistung hat eine **Auftragsposition**.
- Die **Einheit** der Fremdleistung passt zu der der Auftragsposition.
  Groß- und Kleinschreibung zählen nicht: „Stk“ und „stk“ passen, „Stk“
  und „Std“ oder „pausch“ nicht.

Die gewöhnliche Rechnung nimmt weiter alles auf, Fremdleistungen ohne
passende Position zum Einkaufspreis. Sie ist für Abrechnungen ohne
Auftrag gedacht.

**Woran Sie es merken.** An einer Abschlags- oder Schlussrechnung zeigt
„Erbrachte Leistungen hinzufügen“ nur die passenden Fremdleistungen zum
Anhaken. Darüber steht der Kasten **Fremdleistungen, die nicht
übernommen werden können**, getrennt nach „Ohne Auftragsposition“ und
„Einheit passt nicht zur Auftragsposition“, gleiche Leistungen
zusammengefasst, etwa „3 × Aufbereitung Asbest (Stk, Pos. 50 hat Std)“.
Über die Aktion „In Rechnung übernehmen“ in der Liste nennt die Vorschau
die Zahl dieser Fremdleistungen; wählen Sie dort eine Abschlags- oder
Schlussrechnung als Ziel, werden sie übergangen und in der Meldung
genannt.

**So ordnen Sie zu:**

1. Lassen Sie die Rechnung als Entwurf liegen.
2. Klicken Sie im Kasten auf **Fremdleistungen**. Die Liste öffnet sich mit
   den offenen Fremdleistungen des Projekts. Ohne den Kasten erreichen Sie
   sie über **Leistung › Fremdleistungen** und die Filter Projekt und
   Zustand „offen“.
3. Wählen Sie rechts den Filter **Zuordnung**:
   - **Ohne Auftragsposition**: Probieren Sie zuerst **Über
     Fremdschlüssel zuordnen** für alle Zeilen; das setzt die Position,
     wo der Fremdschlüssel eindeutig ist. Für den Rest markieren Sie die
     Zeilen und wählen **Auftragsposition setzen**. Dieselbe Leistung je
     Geschoss verteilen Sie so in mehreren Durchgängen, je Geschoss die
     passenden Zeilen.
   - **Einheit passt nicht**: Die Position ist gewählt, aber ihre Einheit
     weicht ab. Meist ist die Position falsch, dann wählen Sie mit
     „Auftragsposition setzen“ eine mit passender Einheit. Ist die Einheit
     falsch, ändern Sie sie an der Fremdleistung.
4. Fehlt im Auftrag eine passende Position, öffnen Sie den Auftrag wieder,
   ergänzen die Position (mit dem Fremdschlüssel des Lieferanten, dann
   ordnet „Über Fremdschlüssel zuordnen“ künftig von selbst zu) und
   schreiben ihn erneut fest.
5. Öffnen Sie die Rechnung wieder und wählen Sie **Erbrachte Leistungen
   hinzufügen**. Die zugeordneten Fremdleistungen stehen jetzt zur Auswahl.

Was nicht übernommen wird, bleibt offen und zählt in der Projektakte und
unter „Nicht abgerechnet“ weiter mit.
