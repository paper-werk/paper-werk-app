# Stammdaten

Stammdaten sind die Angaben, aus denen Belege vorbelegt werden: Kunden und
Lieferanten, der Leistungskatalog, Textbausteine, Steuersätze und die
eigene Firma, dazu die Kostensätze für die Nachkalkulation. Was ein Beleg
daraus übernimmt, gehört danach dem Beleg: Eine spätere Änderung der
Stammdaten ändert keinen bestehenden Beleg.

## Kontakte {#kontakt}

Ein Kontakt ist ein Betrieb oder eine Person außerhalb der eigenen Firma:
Kunde, Lieferant, Partner oder Interessent.

**Die Liste** zeigt Kundennummer, Name, Rolle, Ort, Zahlungsziel, die Zahl
der Belege und ob der Kontakt aktiv ist. Ein Klick auf Nummer oder Name
öffnet die **Kundenakte**, nicht die Maske; dort führt „Stammdaten
bearbeiten“ weiter. Die Filter: **Rolle** und **Sichtbarkeit** (nur aktive
oder nur inaktive). Die Suche findet Nummer, Name, Ort, PLZ, Telefon und
E-Mail sowie Namen von Ansprechpartnern. Über die Knöpfe oben lassen sich
Kontakte aus einer Tabelle importieren und exportieren.

**Die Maske:**

- **Nummer**: vorgeschlagen ist die nächste freie (K-1000 aufwärts).
- **Name** und **Aktiv**: Inaktive Kontakte stehen in den Auswahllisten
  nicht mehr zur Wahl; ihre Belege und Projekte bleiben unberührt.
- **Rollen**: Kunde, Lieferant, Partner, Interessent, auch mehrere
  zugleich. Belege und Projekte bieten nur Kunden an, Eingangsrechnungen
  nur Lieferanten.
- **Kaufmännisch**: **USt-IdNr.**, **Eigene Kundennummer** (unter der uns
  der Kontakt führt, für Bestellungen), **Zahlungsziel (Tage)**,
  **Skonto** in Prozent und Tagen, **Steuerfall** als Vorbelegung für neue
  Belege. Skonto wirkt nirgends automatisch; es steht hier zum Nachsehen,
  wenn eine Zahlung mit Abzug eingeht.
- **E-Rechnung und Versand**: der **Zustellweg** (PDF per E-Mail,
  E-Rechnung als PDF mit ZUGFeRD, XRechnung als XML etwa für ein
  Rechnungsportal, Papier per Post) und die **Käuferreferenz**, bei
  Behörden die Leitweg-ID. Für XRechnung ist die Leitweg-ID nötig.
- **Besonderheiten** (eingeklappt): **Rechnungsempfänger**, nur wenn ein
  anderer Kunde die Rechnungen bekommt, etwa eine Hausverwaltung,
  Konzernmutter oder Versicherung; dazu eine **Notiz**.

Darunter drei Tabellen:

- **Anschriften**: je Zeile Verwendung (Rechnungs-, Post-, Lieferanschrift
  oder sonstige), Bezeichnung (etwa „Zentrale“), Zusatz, Straße, PLZ, Ort,
  Land und der Haken **Standard**: die Anschrift, die gilt, wenn keine
  andere genannt ist. Genau eine je Kontakt ist Standard.
- **Kontaktdaten des Betriebs**: Art (E-Mail, Telefon, Mobil, Fax, Web,
  Weitere), Wert, Bezeichnung und Standard; höchstens einer je Art ist
  Standard.
- **Ansprechpartner**: nur zur Übersicht. Ein Klick auf den Namen öffnet
  die Seite der Person, **Ansprechpartner hinzufügen** legt eine neue an.

Oben führt **Akte** in die Kundenakte.

### Ansprechpartner {#ansprechpartner}

Jede Person beim Kunden hat eine eigene Seite: **Kontakt**, **Anrede**
(Frau, Herr oder neutral), **Titel**, **Vorname**, **Nachname**, unter
„Zuordnung“ die **Funktion** (etwa „Bauleitung“), die **Anschrift** bei
mehreren Standorten, **Standard** (wer gemeint ist, wenn kein anderer
genannt wird; höchstens einer je Kunde) und **Aktiv**, dazu eine Notiz.
Darunter die Kontaktdaten dieser Person: Durchwahl, Mobil, persönliche
E-Mail.

Der Standard-Ansprechpartner kommt beim Anlegen eines Belegs als
„z. Hd.“-Zeile ins Anschriftfeld, und seine E-Mail-Adresse hat Vorrang
als Versandadresse. Als Anschrift nimmt der Beleg die Rechnungsanschrift
des Kunden. „Sichern“
und **Zum Kontakt** führen zurück zum Kontakt.

## Kundenakte {#kundenakte}

Die Kundenakte zeigt alles zu einem Kontakt auf einer Seite. Im Kopf
Nummer, Name, Ort und, falls gesetzt, der abweichende Rechnungsempfänger;
oben rechts **Stammdaten bearbeiten**.

Die Abschnitte: **Anschriften**, **Kontaktdaten**, **Konditionen**,
**Ansprechpartner**, **Projekte** (mit „Alle Projekte dieses Kunden“),
**Letzte Belege** mit Brutto und Offen (mit „Alle Rechnungen dieses
Kunden“) und **Zahlungseingänge** (mit „Alle Zahlungen dieses Kunden“).
Bei Lieferanten kommen die **Eingangsrechnungen** dazu. Beträge sieht nur,
wer das Recht für das Controlling hat.

## Leistungskatalog {#katalogposition}

Der Leistungskatalog enthält die Leistungen und Artikel, die in Belegen
immer wieder vorkommen. Aus ihm füllt die Katalogsuche die Positionen, und
die Erfassung bietet seine Leistungen für Arbeit ohne Auftrag an.

**Die Liste** zeigt Artikelnummer, Bezeichnung, ob ein Langtext da ist,
Einheit, Einzelpreis netto und Steuersatz. Filter nach Steuersatz, Art der
Erfassung und „In der Erfassung“. Kataloge kommen oft als Tabelle von
außen: Über **Importieren** und **Exportieren** lassen sie sich einlesen,
etwa für eine Preisrunde, und als Preisliste ausgeben.

**Die Maske:**

- **Artikelnummer**: freiwillig, aber eindeutig.
- **Bezeichnung** und **Langtext**: der Langtext erscheint im Beleg unter
  der Bezeichnung und lässt sich dort noch ändern.
- **Einheit**, **Einzelpreis netto**, **Steuersatz**.
- **In der Erfassung**: Die Leistung erscheint in der Leistungserfassung.
  Abwählen bei Positionen, die nur auf Angebote gehören, etwa
  „Baustelleneinrichtung pauschal“.
- **Art der Erfassung**: Zeit (über Von und Bis), Menge (über eine Zahl)
  oder Pauschale (Menge 1).

Eine Preisänderung im Katalog wirkt nur auf neue Positionen. Bestehende
Belege und Aufträge behalten ihren Preis.

## Textbausteine {#textbaustein}

Textbausteine sind wiederkehrende Texte, die Sie über den Knopf
„Textvorlagen“ in ein Textfeld einfügen.

- **Name**: so steht er in der Auswahl, kurz und wiedererkennbar.
- **Verwendung**: **Text auf dem Beleg** (für die Texte über und unter den
  Positionen) oder **Anschreiben beim Versand** (für die Nachricht in der
  Versandseite).
- **Belegart**: leer, wenn der Baustein für jede Belegart taugt, etwa eine
  Grußformel; sonst erscheint er nur dort. „Anbei unsere Rechnung“ gehört
  zur Rechnung.
- **Text**.

Im Anschreiben dürfen Platzhalter stehen, die beim Versand ersetzt werden:

| Platzhalter | wird zu |
|---|---|
| {nummer} | Belegnummer, etwa RE-2026-0098 |
| {beleg} | Bezeichnung mit Nummer, etwa „Rechnung RE-2026-0098“ |
| {empfaenger} | Name des Empfängers |
| {betrag} | Bruttobetrag mit Währung |
| {firma} | Name der eigenen Firma |

Gibt es für eine Belegart einen Baustein „Anschreiben beim Versand“, steht
er beim Versenden schon in der Nachricht.

## Kostensätze {#kostensatz}

Der Kostensatz sagt, was eine Stunde einer Person den Betrieb kostet:
Lohn samt Nebenkosten und Umlage, netto, nicht was der Kunde zahlt. Aus
ihm rechnen Projektakte, Startseite und Controlling das Ergebnis. Fehlt
er für jemanden, der Stunden erfasst hat, meldet die Startseite
„Kostensatz fehlt“, und das Ergebnis ist unvollständig.

Je Eintrag: **Person**, **Gültig ab** und **Kostensatz je Stunde**, dazu
eine Notiz. Ein neuer Satz gilt ab seinem Datum bis zum nächsten dieser
Person; frühere Stunden bleiben mit dem alten Satz gerechnet. Ändern Sie
deshalb nicht den alten Eintrag, sondern legen Sie einen neuen an.

Die Liste zeigt je Person den neuesten Satz oben. Kostensätze sieht nur,
wer das Recht dafür hat; sie sind eine Leistungsbewertung.

## Steuersätze {#steuersatz}

Die Steuersätze, die in Positionen und im Katalog zur Wahl stehen. Je
Satz: **Satz in %**, **Bezeichnung** (steht in der Auswahl hinter dem
Satz, etwa „19 % (Regelsteuersatz)“), **Wählbar**, **Vorgabe** und
**Reihenfolge**. Die Reihenfolge ändern Sie direkt in der Liste.

- Der Satz selbst lässt sich nach dem Anlegen nicht mehr ändern, und ein
  Steuersatz lässt sich nicht löschen: Positionen speichern den Satz als
  Wert.
- Ändert der Gesetzgeber die Sätze, legen Sie den neuen Satz an und nehmen
  bei dem alten den Haken **Wählbar** heraus. Bestehende Positionen
  behalten ihn.
- **Vorgabe**: der Satz, mit dem neue Positionen und Katalogeinträge
  vorbelegt sind. Genau einer ist Vorgabe.

## Eigene Firma {#firma}

Die Angaben der eigenen Firma stehen auf jedem Beleg. Es gibt genau einen
Eintrag; „Hinzufügen“ verschwindet, sobald er angelegt ist.

- **Firmenname**, **Namenszusatz** und **Logo** für den Briefkopf.
- **Anschrift** mit Land (zwei Buchstaben, etwa DE, für die E-Rechnung).
- **Kontakt**: Telefon, E-Mail, Web.
- **Steuerlich**: **Steuernummer** oder **USt-IdNr.**; eine Rechnung
  braucht eines von beiden. **Kleinunternehmer**: Dann weist kein Beleg
  Umsatzsteuer aus, und der vorgeschriebene Hinweis steht darauf.
- **Bankverbindung**: Kreditinstitut, IBAN, BIC.
- **Pflichtangaben im Geschäftsbrief** (eingeklappt): Geschäftsführung,
  Registergericht und Handelsregister, bei Kapitalgesellschaften
  vorgeschrieben.
- **Mahngebühren**: je Stufe ein Betrag in Euro ohne Umsatzsteuer. Er kommt
  in jede neue Mahnung dieser Stufe.
- **Texte** (eingeklappt): der **Standard-Fußtext**, der gilt, wenn am
  Beleg selbst kein Fußtext steht.

Änderungen hier, etwa nach einem Umzug, wirken auf neue PDFs. Ein
festgeschriebener Beleg behält sein eingefrorenes PDF mit den alten
Angaben.
