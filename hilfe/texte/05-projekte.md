# Projekte

Die Gruppe „Projekte“ in der Seitenleiste folgt dem Weg eines Vorhabens:
erst das Projekt, dann das Angebot, daraus der Auftrag, die Abnahme und
gegebenenfalls Lieferscheine.

## Projekte {#projekt}

Ein Projekt fasst alles zusammen, was zu einem Vorhaben gehört: Belege,
erfasste Stunden, zugekaufte Leistungen. Stunden lassen sich nur auf ein
Projekt erfassen.

**Die Liste** zeigt je Projekt die Spalte „Akte“ mit dem Verweis
„ansehen“, Nummer, Bezeichnung, Kunde, die Zahl der Belege und ob es
abgeschlossen ist. Ein Klick auf Nummer oder Bezeichnung öffnet die Maske.
Der Filter „Bearbeitungsstand“ zeigt nur laufende oder nur abgeschlossene
Projekte, der Filter „Kunde“ die Projekte eines Kunden. Über die Knöpfe
oben lassen sich Projekte aus einer Tabelle importieren und als Tabelle
exportieren.

**Die Maske:**

- **Nummer**: vorgeschlagen ist die nächste freie des Jahres, etwa
  „2026-014“. Sie ist frei überschreibbar, auch mit eigenen Nummern wie
  „BV-Halle-Nord“.
- **Bezeichnung** und **Kunde**.
- Unter „Weiteres“: **Beschreibung** und **Notiz** für interne Zwecke und
  der Haken **Abgeschlossen**.

Ein abgeschlossenes Projekt steht in neuen Belegen nicht mehr zur Wahl,
bleibt aber in der Liste (Filter „Nur abgeschlossene“) und in allen
Auswertungen auffindbar.

Oben in der Maske führt **Projektakte** in die Akte.

## Projektakte {#projektakte}

Die Projektakte zeigt alles zu einem Projekt auf einer Seite. Sie öffnen
sie über „ansehen“ in der Projektliste, über „Projektakte“ in der Maske,
über die Schnellsuche oder aus der Startseite. Oben rechts führt
**Projekt bearbeiten** in die Maske; ‹ › blättert zum nächsten Projekt der
Liste.

Im Kopf stehen Nummer, Bezeichnung und der Kunde mit Verweis auf seine
Akte. Darunter, für wer die Zahlen sehen darf, die Kennzahlen:

- **Beauftragt**: Summe der Aufträge und Nachträge, netto.
- **Fakturiert**: gestellte Rechnungen, Stornos abgezogen.
- **Noch abzurechnen**: erfasste Stunden und zugekaufte Leistung ohne
  Rechnung.
- **Kosten**: eigene Arbeit (Stunden mal Kostensatz) und Zukauf.
- **Ergebnis**: Leistungswert minus Kosten.
- **Effektiver Stundensatz**: Erlös je geleisteter Stunde, mit dem Faktor
  auf den Kostensatz; nur, wenn Stunden erfasst sind.

Ist mehr geleistet als beauftragt, steht ein Warnhinweis „über dem
Auftrag“. Ob das bezahlt wird, entscheidet der Vertrag: nach Aufwand ja,
pauschal nicht. Ein Nachtrag gehört geprüft.

Darunter die Abschnitte:

- **Auftrag und Nachträge**: erst ab dem ersten Nachtrag; woraus sich die
  Auftragssumme zusammensetzt, mit Verweis auf jede Auftragsakte.
- **Erfasste Stunden je Monat**.
- **Wohin der Leistungswert fließt** und **Vom Leistungswert zum
  Ergebnis**: die Rechnung hinter dem Ergebnis.
- **Belege**: alle Belege des Projekts mit Datum, Art, Nummer, Betreff,
  Status und Betrag; ein Klick öffnet den Beleg.
- **Erfasste Leistung**: je Person und je Leistung, mit „Alle Zeilen
  ansehen“ in die Erfassungsliste.
- **Zugekaufte Leistung**: Positionen aus Eingangsrechnungen und ob sie
  schon weiterberechnet sind.

## Angebote {#angebot}

Ein Angebot ist der erste Beleg an den Kunden.

**Anlegen:** In der Liste „+“, Projekt (oder Kunde) wählen, Betreff,
Positionen und Texte eintragen, mit „Sichern und weiter bearbeiten“
sichern. „Ausführung ab / bis“ ist der geplante Zeitraum, ohne
steuerliche Bedeutung. Wie die Positionen funktionieren, steht unter
[Positionen](#positionen).

**Die Knöpfe** der Angebotsmaske:

| Knopf | Wo | Wann | Wirkung |
|---|---|---|---|
| Versenden | vorn | am Entwurf | Versandseite, schreibt fest, siehe [Versenden](#versenden) |
| PDF anzeigen | vorn | immer | PDF im neuen Reiter |
| Erneut versenden | Weitere … | nach dem Versand | Noch einmal schicken oder herunterladen |
| Auftrag erzeugen | Weitere … | festgeschrieben | Auftrag als Entwurf mit allen Positionen |
| Rechnung erzeugen | Weitere … | festgeschrieben | Rechnung direkt aus dem Angebot, ohne Auftrag |
| Wieder öffnen | Weitere … | festgeschrieben | Zurück in den Entwurf, Nummer bleibt; eigenes Recht |
| Angebot duplizieren | Weitere … | immer | Neues Angebot mit denselben Positionen |
| Verlauf | Weitere … | immer | Wer hat wann was getan |

**Die Liste** zeigt Beleg, Projekt, Empfänger, Datum, Brutto, Dokument und
das Schloss. Als Aktionen für mehrere Angebote gibt es „Ausgewählte Belege
festschreiben“, „Auftrag daraus erzeugen“ und „Rechnung daraus erzeugen“.

Angebote dürfen optionale Positionen enthalten, siehe [Optionale
Positionen](#optionale-positionen).

## Aufträge {#auftrag}

Der Auftrag ist die Vereinbarung mit dem Kunden und die Vorgabe im
Projekt: Gegen seine Positionen wird abgerechnet, auf sie werden Stunden
kontiert. Er geht nicht an den Kunden und wird deshalb nicht versendet,
sondern festgeschrieben.

**Entstehen** sollte er aus dem Angebot („Auftrag erzeugen“). Ohne
Angebot legen Sie ihn in der Liste mit „+“ an.

**Die Knöpfe:**

| Knopf | Wo | Wann | Wirkung |
|---|---|---|---|
| Auftragsakte | vorn | immer | Abrechnungsstand des Auftrags |
| Festschreiben | vorn | am Entwurf | Nummer vergeben, Auftrag sperren |
| PDF anzeigen | vorn | immer | die Auftragsbestätigung, aus dem aktuellen Stand |
| Nachtrag anlegen | Weitere … | festgeschriebener Hauptauftrag | Leerer Auftrag, der auf diesen verweist |
| Lieferschein erzeugen | Weitere … | festgeschrieben | Lieferschein mit den Positionen ohne Preise |
| Rechnung erzeugen | Weitere … | festgeschrieben | Rechnung mit den Positionen des Auftrags |
| Wieder öffnen | Weitere … | festgeschrieben | Zurück in den Entwurf; eigenes Recht |
| Verlauf | Weitere … | immer | Änderungen und Vorgänge |

„Festschreiben“ führt auf eine kurze Seite, die Beleg und Betrag nennt und
nachfragt. Anders als bei anderen Belegen wird beim Auftrag kein PDF
eingefroren: Die Auftragsbestätigung entsteht bei jedem „PDF anzeigen“ aus
dem gültigen Stand.

**Die Spalte „Abgerechnet“** in den Positionen zeigt je Position, wie viel
davon schon auf festgeschriebenen Rechnungen steht, etwa „12 von 40 Std
abgerechnet“, und ob mehr abgerechnet als beauftragt ist. So sehen Sie vor
der nächsten Rechnung, was noch offen ist.

**Nachträge.** Kommt Leistung hinzu, legen Sie am festgeschriebenen
Hauptauftrag über „Weitere …“ einen **Nachtrag** an. Es entsteht ein
leerer Auftrag mit Empfänger und Konditionen des Hauptauftrags; das Feld
„Nachtrag zu“ verweist auf ihn. Tragen Sie die Positionen ein und
schreiben Sie fest. Der Nachtrag zählt in der Projektakte unter „Auftrag
und Nachträge“ zur Auftragssumme, und seine Positionen stehen in den
Abnahmen des Hauptauftrags zur Wahl. Einen
Nachtrag zu einem Nachtrag gibt es nicht.

**Die Liste** zeigt vorn die Spalte „Akte“ mit „ansehen“. Der Filter
„Nachtrag zu“ zeigt die Nachträge eines Auftrags.

## Auftragsakte {#auftragsakte}

Die Auftragsakte beantwortet: Wie weit ist dieser Auftrag? Sie öffnen sie
mit „Auftragsakte“ am Auftrag oder „ansehen“ in der Auftragsliste. Oben
rechts führt **Auftrag bearbeiten** in die Maske.

Kennzahlen:

- **Beauftragt**: Auftragswert netto mit Zahl der Positionen.
- **Abgerechnet**: festgeschriebene Rechnungen auf diesen Auftrag.
- **Offen**: was vom Auftrag noch abzurechnen ist.
- **Erfasst, nicht berechnet**: geleistet und auf diesen Auftrag
  kontiert, aber auf keiner Rechnung.

Ist mehr abgerechnet als beauftragt, steht ein Hinweis mit dem Prozentsatz.

Die Abschnitte:

- **Abrechnungsstand**: das Herzstück. Je Position beauftragte,
  abgerechnete und offene Menge, ein Balken für den Stand und der
  Nettobetrag. Optionale Positionen sind gekennzeichnet; sie zählen nicht
  zum Auftragswert.
- **Abnahmen**: die Abnahmen zu diesem Auftrag mit Datum, Leistungsdatum,
  Stand und Rechnung. Hier steht der Knopf **Abnahme erfassen**.
- **Fortschritt**, **Auftrag und Nachträge** und **Rechnungen auf diesen
  Auftrag** mit ihrem Anteil.
- **Wer daran gearbeitet hat** und **Zuletzt erfasst**: die erfassten
  Stunden, mit „Alle Zeilen dieses Auftrags ansehen“.

## Abnahmen {#abnahme}

Die Abnahme hält fest, dass unsere Leistung ganz oder teilweise vollendet
und abgenommen ist. Aus ihr entsteht die Schlussrechnung oder eine
Teilschlussrechnung; einen anderen Weg zur Teilschlussrechnung gibt es
nicht.

**Anlegen:** am einfachsten in der Auftragsakte mit **Abnahme erfassen**.
Dann ist der Auftrag gewählt, und Leistungsbeginn und -ende sind mit dem
ersten und letzten Tag vorbelegt, an dem auf den Auftrag erfasst wurde.

Die Felder:

- **Auftrag**: nur festgeschriebene Hauptaufträge; Nachträge gehören dazu.
- **Art**: **Gesamtabnahme** für den ganzen Auftrag (je Auftrag nur eine)
  oder **Teilabnahme** für einen Teil.
- **Bezeichnung**: bei der Teilabnahme, welche Teilleistung, etwa
  „Bauabschnitt 1“.
- **Auftragspositionen**: nur bei der Teilabnahme; die Positionen der
  Teilleistung als Häkchen, aus dem Auftrag und seinen Nachträgen. Eine
  Position kann nur zu einer Teilabnahme gehören und darf noch nicht ganz
  abgerechnet sein.
- **Leistungsbeginn** und **Leistungsende**: der Zeitraum für die
  Rechnung.
- **Abgenommen am**: der Tag der Abnahme oder Vollendung unserer Leistung,
  nicht die Abnahme der Bauleistung eines anderen. Leer heißt: noch offen.
- **Leistungsdatum**: geht als Leistungsdatum in die Rechnung.
- **Notiz**.

Darunter stehen Stand (offen, abgenommen, abgerechnet), das vereinbarte
Entgelt und die Rechnung, die aus der Abnahme entstanden ist.

**Rechnung erzeugen** (vorn) legt aus einer Gesamtabnahme die
Schlussrechnung, aus einer Teilabnahme die Teilschlussrechnung an, jeweils
als Entwurf. Voraussetzung ist ein Datum unter „Abgenommen am“. Gibt es zu
der Abnahme schon einen Entwurf, öffnen Sie diesen statt eines neuen.

Ist die Rechnung festgeschrieben, lässt sich die Abnahme nicht mehr
ändern. Löschen lässt sie sich nur, solange keine Rechnung an ihr hängt.
Alle Änderungen an einer Abnahme stehen im Verlauf.

## Lieferscheine {#lieferschein}

Der Lieferschein weist nach, was geliefert wurde, ohne Preise. Wer ihn beim
Kunden vorlegt, sieht keine Kalkulation.

Er entsteht aus einem festgeschriebenen Auftrag („Weitere …“,
„Lieferschein erzeugen“) oder in der Liste mit „+“. Die Positionen haben
nur Pos., Bezeichnung, Menge und Einheit. Das **Lieferdatum** belegt später
das Leistungsdatum der Rechnung.

Versendet wird wie jeder Beleg mit **Versenden**; danach ist er gesperrt
und lässt sich nicht wieder öffnen. Aus ihm erzeugt „Weitere …“,
**Rechnung erzeugen** die Rechnung.
