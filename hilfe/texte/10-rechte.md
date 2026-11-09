# Rechte

Dieses Kapitel richtet sich an Administratoren. Es beschreibt, wie sich
Rechte auswirken und welche Rechte für eine Aufgabe mindestens nötig sind.

## Grundlagen der Rechte

Der Zugriff eines Benutzers ergibt sich aus Kontostatus, Rechten und Zustand
des Datensatzes. Rechte werden über Gruppen oder direkt am Benutzer
vergeben. Wirksam ist die Summe.

| Stufe | Einstellung | Wirkung |
|---|---|---|
| Kein Zugang | „Aktiv“ oder „Mitarbeiter-Status“ fehlt | Keine Anmeldung an der Oberfläche möglich |
| Normaler Benutzer | „Aktiv“ und „Mitarbeiter-Status“ | Sieht und darf nur, was seine Rechte hergeben |
| Administrator | zusätzlich „Administrator-Status“ | Hat alle Rechte, unabhängig von seinen Gruppen |

Je Datenart gibt es vier Standardrechte. Die Gruppenmaske zeigt sie in der
Form „Faktura | Rechnung | Can add Rechnung“, also Bereich, Datenart und
Recht.

| Recht | Anzeige in der Maske | Wirkung |
|---|---|---|
| Ansehen | Can view … | Menüeintrag, Liste und schreibgeschützte Maske |
| Anlegen | Can add … | Schaltfläche „Hinzufügen“ und neue Datensätze |
| Ändern | Can change … | Vorhandene Datensätze speichern; öffnet auch Liste und Maske, der Menüeintrag erscheint aber nur mit „Ansehen“ |
| Löschen | Can delete … | Datensätze löschen, soweit der Zustand es zulässt |

Dabei gilt:

- Festgeschriebene Belege sind für alle Benutzer schreibgeschützt, auch für
  Administratoren. Löschbar ist nur ein Entwurf, der nie eine Nummer hatte.
- Jede Belegart hat eigene Rechte. Rechte an „Rechnung“ gelten nicht für
  Abschlags- oder Schlussrechnungen.
- Teilbereiche einer Maske haben eigene Rechte: Positionen im Beleg
  „Position“, Anschriften im Kontakt „Adresse“. Fehlt das Recht, fehlt der
  Teilbereich.
- Die Schaltflächen für Versenden, Festschreiben, Mahnen und Stornieren
  erscheinen mit dem Änderungsrecht an der Belegart.

Einige Vorgänge haben ein eigenes Recht:

| Recht | Wirkung |
|---|---|
| Kann für andere Personen erfassen | Sieht die Stunden aller, erfasst für andere, entscheidet über „abrechenbar“ |
| Kann die Auswertungen sehen | Kennzahlen der Startseite und Controlling |
| Kann Belege wieder öffnen | Festgeschriebene Angebote und Aufträge zurück in den Entwurf |
| Kann den Archivvermerk setzen | Nur für die Anbindung an das Archiv |
| Kann Kopffelder über die API ändern | Nur für automatisierte Abläufe über die Schnittstelle |

## Mindestrechte je Aufgabe

Angegeben sind die Mindestrechte zusätzlich zum Mitarbeiter-Status.
„Ansehen“ ist aufgeführt, wenn der Eintrag in der Seitenleiste es erfordert.

### Zeiterfassung

| Aufgabe | Mindestrechte |
|---|---|
| Eigene Zeiten erfassen | Erfassungszeile: ansehen, anlegen |
| Eigene Zeiten korrigieren | zusätzlich Erfassungszeile: ändern |
| Eigene Zeiten löschen | zusätzlich Erfassungszeile: löschen |
| Liste nach Projekt oder Kunde filtern | zusätzlich Projekt: ansehen, Kontakt: ansehen |
| Zeiten für andere erfassen, Stunden aller sehen | Erfassungszeile: ansehen, anlegen; „Kann für andere Personen erfassen“ |

Ohne „Kann für andere Personen erfassen“ zeigt die Liste nur eigene Zeilen.
Projekte und Auftragspositionen sind in der Erfassungsmaske ohne weitere
Rechte auswählbar.

### Rechnung

| Aufgabe | Mindestrechte |
|---|---|
| Rechnung erstellen | Rechnung: ansehen, anlegen; Position: anlegen; Kontakt: ansehen |
| Entwurf bearbeiten | Rechnung: ansehen, ändern; Position: anlegen, ändern, löschen |
| Fertige Rechnung lesen, PDF öffnen | Rechnung: ansehen; Position: ansehen (sonst fehlen die Positionen in der Maske) |
| Versenden und damit festschreiben | Rechnung: ändern |
| Leistungen aus dem Katalog suchen | zusätzlich Leistungskatalog: ansehen |
| Textvorlagen im Beleg verwenden | zusätzlich Textbaustein: ansehen |
| Anschrift aus Kunde oder Projekt vorbelegen | zusätzlich Kontakt: ansehen, Projekt: ansehen |
| Erbrachte Leistungen in einen Entwurf übernehmen | Rechnung: ändern (Entwurf mit Projekt) |
| Aus der Erfassungsliste abrechnen | Erfassungszeile: ansehen; Beleg: anlegen |
| Rechnung duplizieren | Rechnung: anlegen |
| Mahnen, stornieren und neu schreiben, Nachlass | Rechnung: ändern. Für die Bearbeitung des neuen Belegs zusätzlich Rechte an Mahnung, Stornorechnung oder Rechnungskorrektur |
| Zahlung an der Rechnung vermerken | Zahlung: anlegen |
| Zahlungseingang erfassen und zuordnen | Zahlung: ansehen, anlegen; Zahlungszuordnung: anlegen; Kontakt: ansehen |

### Weitere Belege

| Aufgabe | Mindestrechte |
|---|---|
| Angebot, Auftrag, Lieferschein, Abschlags- oder Schlussrechnung erstellen | Die jeweilige Belegart: ansehen, anlegen; Position: anlegen; Kontakt: ansehen |
| Beleg versenden, Auftrag festschreiben | Die jeweilige Belegart: ändern |
| Angebot oder Auftrag wieder öffnen | „Kann Belege wieder öffnen“ |
| Aus Angebot Auftrag oder Rechnung, aus Auftrag Rechnung, Lieferschein oder Nachtrag erzeugen | Quellbeleg: ändern. Für die Bearbeitung des neuen Belegs zusätzlich Rechte an dessen Belegart |
| Rechnung aus einer Abnahme erzeugen | Abnahme: ansehen; Rechnung: anlegen |

### Stammdaten und Einkauf

| Aufgabe | Mindestrechte |
|---|---|
| Kontakt mit Anschrift anlegen | Kontakt: ansehen, anlegen; Adresse: anlegen; Kontaktweg: anlegen; Ansprechpartner: ansehen |
| Projekt anlegen | Projekt: ansehen, anlegen; Kontakt: ansehen |
| Eingangsrechnung mit Fremdleistungen anlegen | Eingangsrechnung: ansehen, anlegen; Fremdleistung: anlegen; Kontakt: ansehen; Projekt: ansehen |
| Eigene Firma ändern | Firma: ansehen, ändern |

### Auswertungen

| Aufgabe | Mindestrechte |
|---|---|
| Startseite ohne Kennzahlen | keine |
| Kennzahlen auf der Startseite, Seite Controlling | „Kann die Auswertungen sehen“ |
| Controlling: Auslastung je Person | zusätzlich Kostensatz: ansehen |
| Nicht abgerechnete Leistung | Rechnung: ansehen |
| Projektakte, Kundenakte, Auftragsakte | Projekt, Kontakt oder Auftrag: ansehen. Beträge erscheinen nur zusätzlich mit Rechnung: ansehen |
| Rechnungsakte | Rechnung: ansehen |
| Hilfe | keine |

## Gruppen und Hinweise

| Gruppe | Zweck | Vergabe |
|---|---|---|
| paper-werk-buero | Belege, Stammdaten, Controlling, eigene Zeiten | Rolle oder von Hand |
| paper-werk-projektleitung | Wie Büro, dazu Einkauf, Kostensätze, Zeiten aller | Rolle oder von Hand |
| paper-werk-superuser | Kennzeichnet die Administratorrolle; ohne eigene Rechte | Rolle |
| Faktura Dienst | Technischer Zugang, liest Belege und Stammdaten | Nicht an Personen vergeben |
| Belegübernahme | Technischer Zugang für Eingangsrechnungen aus dem Archiv | Nicht an Personen vergeben |

Für reine Zeiterfassung legen Sie eine eigene Gruppe an mit diesen Rechten:
Erfassungszeile alle, Projekt ansehen, Kontakt ansehen.

Mit dem Änderungsrecht an Benutzern oder Gruppen lassen sich die eigenen
Rechte erweitern. Vergeben Sie es nur an Administratoren.

### Hinweise zur Pflege

- Die Einrichtung setzt die Rechte von „Büro“, „Projektleitung“, „Faktura
  Dienst“ und „Belegübernahme“ an Belegen, Stammdaten und Erfassung auf den
  Standard zurück. Pflegen Sie Abweichungen in einer eigenen Gruppe.
- Bei Anmeldung über Microsoft Entra werden Gruppen mit dem Präfix
  „paper-werk-“ und der Mitarbeiter-Status bei jeder Anmeldung aus den
  Rollen gesetzt. Gruppen ohne dieses Präfix bleiben unverändert.
- Rechte zu entfallenen Datenarten bleiben ohne Wirkung in der Gruppe
  stehen.

### Rechte ohne Wirkung

Die folgenden Rechte haben keine Wirkung und werden nicht vergeben:

- Frühere Fassung; die Dateien früherer Fassungen folgen dem Leserecht der
  Belegart
- Änderung der Erfassungszeile, Änderung der Fremdleistung, Änderung der
  Abnahme; der Verlauf folgt den Rechten am Datensatz
- Anlage (die Datenart gibt es nicht mehr, nur auf älteren Installationen
  sichtbar)
- Inhaltstyp, Berechtigung, Logeintrag, Sitzung
- Token (der Eintrag ohne Maske; maßgeblich ist der API-Schlüssel unter
  Verwaltung)
- E-Mail-Adresse, E-Mail-Bestätigung, soziale Anwendung, Token für soziale
  Anwendung
