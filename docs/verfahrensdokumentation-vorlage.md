# Verfahrensdokumentation Faktura: Vorlage

Gerüst einer Verfahrensdokumentation nach GoBD für einen Betrieb, der mit
Paper-Werk fakturiert. Ein Betrieb füllt sie einmal aus, am besten gemeinsam
mit seinem Steuerberater, und schreibt sie bei Änderungen am Verfahren fort.
Zielumfang 5 bis 10 Seiten.

Die _kursiven Hinweise_ und die **Leitfragen** sind Arbeitsanweisungen und
werden beim Ausfüllen gelöscht. Die Leitfragen lassen sich je Abschnitt an
der laufenden Anwendung beantworten; der Verweis dahinter nennt die Stelle im
Code, an der das Verhalten festgelegt ist.

---

## 0 Dokumentverwaltung

_Die Verfahrensdokumentation unterliegt selbst der GoBD: Änderungen an ihr
müssen nachvollziehbar sein (Rz. 154). Deshalb Versionsstand und Historie im
Dokument führen und die Datei versionieren, etwa in Git._

|                 |                          |
| --------------- | ------------------------ |
| Version         | 0.1 (Gerüst)             |
| Stand           | [DATUM]                  |
| Verantwortlich  | [NAME, ROLLE]            |
| Geltungsbereich | Fakturierung der [FIRMA] |

**Änderungshistorie**

| Version | Datum   | Änderung        | Wer   |
| ------- | ------- | --------------- | ----- |
| 0.1     | [DATUM] | Gerüst angelegt | [WER] |

---

## 1 Allgemeine Beschreibung

_Für Leser, die das System nicht kennen: Prüfer, Steuerberater, Nachfolger.
Ohne Technik: was das System tut und auf welcher Grundlage._

- **Unternehmen**: [FIRMA, Rechtsform, Sitz]
- **Zweck des Systems**: Erstellen von Angeboten, Aufträgen, Lieferscheinen,
  Rechnungen, Stornorechnungen, Rechnungskorrekturen und Mahnungen.
  [Anpassen, falls Belegarten hinzukommen oder entfallen.]
- **Einordnung**: Das System ist ein Vorsystem der Buchführung. Die
  Buchführung erfolgt durch [STEUERBERATER] in DATEV; übergeben wird [WAS,
  WIE OFT, AUF WELCHEM WEG].
- **Rechtlicher Rahmen**: § 146 AO (Ordnungsvorschriften), § 14 UStG
  (Pflichtangaben der Rechnung), GoBD in der Fassung vom [STAND].
- **Betroffene Daten**: Kundenstammdaten, Belege mit Positionen, erzeugte
  PDF- und XML-Dateien. [Verweis auf das Verzeichnis nach DSGVO, falls
  vorhanden.]

**Leitfragen:**

- Welche Belegarten gibt es, und welche sind steuerlich relevant?
  (`faktura/models/beleg.py`, `BelegTyp.steuerbelege()`)
- Wer arbeitet mit dem System (Rollen, keine Namen)?

---

## 2 Anwenderdokumentation: die Abläufe

_Aus Sicht der Person am Bildschirm, ein Abschnitt je Vorgang. Jeder
Abschnitt beantwortet: Wie wird der Vorgang ausgelöst, was entsteht dabei,
was ist danach nicht mehr möglich?_

### 2.1 Beleg anlegen und bearbeiten (Entwurf)

**Leitfragen:** Wie entsteht ein Angebot? Was übernimmt das System aus den
Stammdaten, und was hat Vorrang, wenn der Anwender selbst etwas einträgt?
Warum hat ein Entwurf keine Nummer?
(`services.beleg_anlegen()`, `services.stammdaten_uebernehmen()`)

### 2.2 Festschreiben

**Leitfragen:** Was geschieht beim Festschreiben, in welcher Reihenfolge, und
warum in einer Transaktion? Was wird geprüft und abgelehnt? Was steht danach
am Beleg (Nummer, Datum, Benutzer, PDF, Prüfsumme, Vorlagenversion)?
(`services.beleg_festschreiben()`, `_dokument_einfrieren()`)

### 2.3 Rechnung korrigieren (Storno und Neufassung)

**Leitfragen:** Was der Anwender als „Rechnung ändern“ erlebt, ist im System
eine Stornorechnung mit eigener Nummer und ein neuer Entwurf. Wie ist das
festgehalten? Warum heißt der Gegenbeleg nie „Gutschrift“?
(`services.rechnung_korrigieren()`)

### 2.3a E-Rechnung neu ausstellen (vom Empfänger abgewiesen)

_Ob eine abgewiesene E-Rechnung unter derselben Nummer neu ausgestellt
werden darf, entscheidet der Betrieb, nicht das Programm. Die Entscheidung
gehört hierher und wird mit dem Steuerberater abgestimmt, bevor die Funktion
genutzt wird._

**Leitfragen:** Wann wird neu ausgestellt statt storniert (Portal weist ab
wegen falscher Leitweg-ID, fehlender Bestellnummer, falschem Profil)? Was
darf sich ändern (Kopfangaben und Stammdaten wie Telefon, E-Mail,
Zustellweg), was nie (Nummer, Datum, Positionen, Beträge)? Wo bleibt die
alte Fassung, und wie wird sie nachgewiesen? Wer darf die Neuausstellung
auslösen?
(`services.erechnung_neu_ausstellen()`, Modell `Belegfassung`, Aktion
„E-Rechnung neu ausstellen“ an der Rechnung)

**Formulierungsvorschlag** _(mit dem Steuerberater prüfen, dann übernehmen)_:

> Weist ein Rechnungsempfänger eine elektronische Rechnung aus formalen
> Gründen zurück (insbesondere das Rechnungseingangsportal eines
> öffentlichen Auftraggebers bei der Eingangsprüfung), gilt die Rechnung als
> nicht zugegangen. Sie wird unter **derselben Rechnungsnummer** mit
> berichtigten Kopfangaben neu ausgestellt. Rechnungsdatum, Positionen und
> Beträge bleiben unverändert; das System lässt deren Änderung nicht zu.
> Die zurückgewiesene Fassung (PDF und XML) wird mit ihren
> SHA-256-Prüfsummen, dem Grund der Neuausstellung, Zeitpunkt und
> auslösender Person unverändert aufbewahrt und in die laufende
> Integritätsprüfung einbezogen. Inhaltliche Änderungen der Rechnung
> erfolgen ausschließlich über Stornorechnung und Neufassung (2.3).

### 2.4 Nachlass gewähren (Rechnungskorrektur)

**Leitfragen:** Worin unterscheidet sich der Nachlass vom Storno, fachlich
(§ 17 UStG) und im System? Wie mindert er den offenen Betrag der Rechnung,
und wie wird er storniert?
(`RechnungAdmin.action_nachlass` in `faktura/admin/rechnung.py`,
`services.nachlass_stornieren()`)

### 2.5 Mahnen

**Leitfragen:** Woher kennt das System die Mahnstufe? Warum weist die Mahnung
keine Umsatzsteuer aus?
(`services.mahnung_erstellen()`)

### 2.6 Belege ansehen und versenden

**Leitfragen:** Woher kommt das PDF eines festgeschriebenen Belegs, und warum
wird es nie neu erzeugt? Woran ist ein Entwurf auf dem Ausdruck zu erkennen?
[Versandweg des Betriebs: E-Mail, Post, durch wen?]
(`DokumentMixin.ansicht_pdf()` in `faktura/admin/dokumente.py`)

**E-Rechnung:** Jede Rechnung trägt eine E-Rechnung (XML nach EN 16931, für
öffentliche Auftraggeber XRechnung). Versendet wird eine Datei je Beleg: an
Kunden mit Zustellweg „XRechnung“ das XML, an alle anderen das PDF mit
eingebettetem ZUGFeRD.

**Leitfragen:** Welche Kunden erhalten welches Format, und wo ist das
festgelegt (Zustellweg am Kunden)? Was ist das Original? Das, was der Kunde
erhält: beim PDF das PDF, beim reinen XML-Versand das XML. Wie wird das XML
dann aufbewahrt (in Paper-Werk mit Prüfsumme, im Archiv eingebettet im PDF,
beim Steuerberater über den n8n-Workflow)? _Der ausschließliche XML-Versand
ist nur zulässig, wenn das XML revisionssicher aufbewahrt wird (GoBD). Hier
festhalten, wie der Betrieb das sicherstellt._
(`services.beleg_versenden()`, `services.versandformat()`,
[e-rechnung.md](e-rechnung.md))

### 2.7 Steuerfälle (§ 13b, EU, Drittland)

**Leitfragen:** Wer legt fest, ob ein Kunde unter § 13b, Reverse Charge in
der EU, innergemeinschaftliche Lieferung, Ausfuhr oder „nicht steuerbar“
fällt (Steuerfall am Kunden, am Beleg änderbar)? Wer prüft die USt-IdNr. des
Kunden (qualifizierte Bestätigung beim BZSt)? Was verhindert das System
(Festschreiben nur mit 0 % an allen Positionen, Pflichtvermerk und Kategorie
automatisch)? Wie wird die Zusammenfassende Meldung erstellt (außerhalb des
Systems)?
(`faktura/steuerfall.py`, `services.beleg_festschreiben()`)

---

## 3 Technische Systemdokumentation

_Für alle, die das System betreiben oder prüfen. Technik steht hier als
Begründung, ohne Quelltextauszüge._

### 3.1 Systemumgebung

[Hosting, Docker, PostgreSQL-Version, Python- und Django-Version, Ablage der
Konfiguration (`.env`), Zugriff auf den Server.]

### 3.2 Unveränderbarkeit

**Leitfragen:** Welche Schichten verhindern die Änderung eines
festgeschriebenen Belegs (Constraints in der Datenbank, Prüfung im Modell,
Berechtigung im Admin)? Welche Wege führen daran vorbei (direkter Zugriff auf
die Datenbank, `queryset.update()`), und wie sind sie organisatorisch
geregelt? _Diesen letzten Punkt verlangt die GoBD ausdrücklich._
(`Beleg.save()`, Constraints `nummer_ab_der_festschreibung` und
`entwurf_mit_nummer_nur_wiedereroeffnet`, `BelegAdmin.has_change_permission()`)

### 3.3 Nummernvergabe

**Leitfragen:** Warum bleibt der Nummernkreis lückenlos, auch bei Abbrüchen
und parallelen Zugriffen? Warum teilen sich Rechnung, Stornorechnung und
Rechnungskorrektur einen Kreis?
(`services.naechste_belegnummer()`, `django-sequences`)

### 3.4 Dokumentablage und Integrität

**Leitfragen:** Was wird beim Festschreiben eingefroren (Datei, SHA-256,
Vorlagenversion), wo liegt es, und wie wird die Unversehrtheit laufend
nachgewiesen? Wo liegen die Dateien physisch, und wie sind sie gesichert?
(`_dokument_einfrieren()`, Befehl `pruefe_belegarchiv`)

Je Rechnung gibt es zwei Dateien, PDF und XML, jede mit eigener Prüfsumme;
das XML ist byte-gleich im PDF eingebettet und wird einmal erzeugt.
Abgelöste Fassungen (2.3a) bleiben als `Belegfassung` mit Prüfsummen
erhalten und werden von `pruefe_belegarchiv` mitgeprüft.

### 3.5 Protokollierung

**Leitfragen:** Was steht am Beleg (wann und von wem festgeschrieben), was im
Änderungsprotokoll des Admin, und was bewusst nicht (Änderungen an Entwürfen
müssen nicht nachvollziehbar sein)?
(`festgeschrieben_von`, `LogEntry`)

### 3.6 Benutzer und Berechtigungen

**Leitfragen:** Welche Gruppen gibt es, wer darf festschreiben, wer
stornieren? Warum werden Konten deaktiviert statt gelöscht?
(Proxy-Modelle je Belegart mit eigenen Rechten; `festgeschrieben_von` mit
`on_delete=PROTECT`)

---

## 4 Betriebsdokumentation

_Was regelmäßig getan wird, von wem, und was bei Störungen geschieht. Hier
stehen die organisatorischen Antworten, die der Code nicht geben kann._

- **Datensicherung**: [Werkzeug, z. B. Kopia wie in paper-werk
  eingerichtet; Zyklus, Ablageort, wer prüft, dass sie lief]. Gesichert
  werden die Datenbank und die Belegdateien; das PDF ist der Beleg.
- **Archivprüfung**: `manage.py pruefe_belegarchiv` läuft [WANN, z. B.
  täglich nach der Sicherung]. Ein Exit-Code ungleich 0 alarmiert [WEN, WIE].
- **Aufbewahrung**: Rechnungen und Buchungsbelege [8 Jahre, Stand 2025;
  FRIST BEIM STEUERBERATER BESTÄTIGEN], Geschäftsbriefe 6 Jahre. Gelöscht
  wird [NIE / WANN, DURCH WEN].
- **Wiederherstellung**: [Wie wird aus der Sicherung ein lauffähiges System?
  Zuletzt geprobt am DATUM.]
- **Mitarbeiterwechsel**: Konto deaktivieren (`is_active`), nicht löschen.
  [Wer, binnen welcher Frist?]
- **Änderungen am System**: Updates und Vorlagenänderungen werden [WIE]
  eingespielt; eine Vorlagenänderung erhöht `VORLAGENVERSION`.

---

## 5 Internes Kontrollsystem (IKS)

_Bei wenigen Beteiligten kurz, aber nicht leer. Der Prüfer fragt: Wer
kontrolliert wen, und woran würde ein Fehler auffallen?_

- Zugriff nur mit persönlichem Konto, keine Sammelkonten. [PRÜFEN: Gilt das?]
- Funktionstrennung: [Wer schreibt Rechnungen, wer sieht die Auswertungen?
  Im Ein-Personen-Betrieb ausdrücklich so benennen.]
- Regelmäßige Kontrollen: Archivprüfung (4), Sichtung des
  Änderungsprotokolls [WER, WIE OFT], Abgleich mit DATEV [WIE OFT].

---

_Anhang: Screenshots der Masken, Musterbelege je Belegart, Übergabeformat an
den Steuerberater._
