# Entscheidungen

Entwurfsentscheidungen mit Begründung, nach Bereich geordnet. Kommentare im
Code verweisen hierher, wenn das Warum nicht in einen Satz passt. Die
Rechenregeln selbst stehen im [Rechenregister](rechenregister.md) (`R-xxx`).

## Grundsätze

- **Die Oberfläche ist der Django-Admin mit Unfold.** Die Anwender sind die
  Beschäftigten eines Betriebs, also der Personenkreis, für den der Admin
  gedacht ist. Rechte je Modell, Listen mit Filter und Suche, Formulare,
  Inlines und das Änderungsprotokoll kommen damit ohne eigenen Code; eigene
  Seiten (Akten, Controlling, Versand) hängen als Admin-Views darin. Der
  Preis: Wo der Admin an Grenzen stößt, überschreiben Templates Teile von
  Unfold (`templates/unfold/`), und ein Unfold-Update kann sie brechen. Die
  Browsertests in `tests/test_browser_*.py` decken die betroffenen Masken
  ab.
- **Stammdaten werden in den Beleg kopiert**, nicht verknüpft: Anschrift,
  Preis, Steuersatz, Texte. Fremdschlüssel dienen nur der Navigation, damit
  ein festgeschriebener Beleg sich nicht mit den Stammdaten ändert
  (`faktura/models/beleg.py`).
- **Die Belegnummer entsteht beim Festschreiben**, ein Entwurf hat keine. Sie
  kommt aus einem lückenlosen Nummernkreis (`django-sequences`, in der
  Transaktion des Festschreibens) (`services.naechste_belegnummer`).
- **Kernfunktionen hängen an keiner Einstellung.** Versenden, Festschreiben
  und das Erzeugen des Belegdokuments lassen sich nicht abschalten, damit sich
  Test- und Betriebskonfiguration darin nicht unterscheiden. Tests ersetzen
  `_dokument_ablegen`, außer mit dem Marker `mit_pdf` (`conftest.py`,
  `services.festschreiben`).
- **Kaufmännische Rundung an einer Stelle** (`ROUND_HALF_UP`): je Position
  gerundet, Steuer je Satz (`core/rechnen.py`, `services.belegsummen`).
- **Keine gespeicherten Summen am Beleg.** Abfragen über viele Belege rechnen
  in der Datenbank mit derselben Regel (R-173) und werden in Tests gegen den
  Einzelweg geprüft. Parallele Abfragen in PostgreSQL sind abgeschaltet
  (`max_parallel_workers_per_gather=0`); Messungen im
  [Prüfprotokoll Lasttest](pruefprotokoll-lasttest-2026-10.md)
  (`services.bruttosummen`, `DATABASES` in `paperwerk/settings/base.py`).

## Belegarten und Nummernkreise

- Rechnung, Stornorechnung und Rechnungskorrektur teilen einen Nummernkreis
  (`services.NUMMERNKREIS`).
- Die Mahnung hat ein Zahlungsziel, obwohl sie kein Steuerbeleg ist
  (`mit_zahlungsziel`). Mengen von Belegarten werden in `BelegTyp` aufgezählt,
  nicht auseinander abgeleitet.
- Die Texte der Mahnstufen stehen nur in `MAHNTEXT`, nicht zusätzlich in der
  Vorlage.
- Die Belegart heißt „Auftrag“, nicht „Auftragsbestätigung“: benannt ist der
  Vorgang, nicht das Schreiben (`BelegTyp.AUFTRAG`).
- Abschlags- und Schlussrechnung sind eine Rechnungsart (Feld `Rechnungsart`),
  kein eigener Belegtyp. Eigene Menüeinträge entstehen über Proxy-Modelle.
- Abschläge werden je Projekt gezählt, nicht je Auftrag
  (`Beleg.abschlagsnummer`).
- Festschreiben behält ein im Entwurf gesetztes Belegdatum
  (`services.beleg_festschreiben`).
- **Wiedereröffnen** führt Angebot und Auftrag zurück in den Entwurf; die
  Nummer bleibt, einen dritten Zustand gibt es nicht. Lieferscheine lassen
  sich nicht wiedereröffnen. Die Änderung steht in `geaendert_am` und
  `geaendert_von` (`BelegTyp.entsperrbar`, `services.beleg_wiedereroeffnen`).
- Der Auftrag bekommt beim Festschreiben kein Dokument und wird nicht
  archiviert (`BelegTyp.mit_dokument`).

## Versand und E-Rechnung

- **Eine Datei je Beleg:** XRechnung als XML, alles andere als PDF, bei
  Rechnungen mit ZUGFeRD. Es gibt keine Auswahl von Anhängen; Mail und
  Download liefern dieselbe Datei. Einzelheiten in
  [e-rechnung.md](e-rechnung.md) (`services.versandformat`).
- Der Zustellweg „XRechnung“ des Kunden bestimmt beim Festschreiben das
  XML-Profil (`Zustellweg`, `facturx.ist_xrechnung`).
- Eine E-Rechnung lässt sich mit derselben Nummer neu ausstellen; die alte
  Fassung bleibt als `Belegfassung` erhalten
  (`services.erechnung_neu_ausstellen`).
- Der Dokumenttyp (BT-3) ist je Rechnungsart einstellbar, Vorgabe 380;
  Stornorechnung und Rechnungskorrektur haben 381, das Storno einer
  Rechnungskorrektur 384 (`ERECHNUNG_TYPCODE`, `facturx.typcode`).
- Storno und Rechnungskorrektur verweisen im XML auf ihren Vorgänger (BG-3:
  BT-25 Nummer, BT-26 Datum), weil die Berichtigung spezifisch und eindeutig
  auf den berichtigten Beleg verweisen muss (§ 31 Abs. 5 UStDV) und bei
  XRechnung das XML das Original ist. Die Neufassung nach einem Storno hat
  kein BG-3; sie ist eine neue Rechnung.
- Der erste Versand wird in `versendet_am` und `versendet_an` gespeichert und
  nie überschrieben. Weitere Versendungen stehen im Verlauf (`LogEntry`),
  ohne eigene Tabelle (`Beleg.versendet_am`).
- Spalte und Schritt heißen „E-Mail“: Datum der ersten Mail, sonst leer. Einen
  Zustand „nicht versendet“ gibt es nicht, weil per Post oder Portal
  verschickte Belege im System nicht erfasst werden; die E-Mail erscheint
  deshalb nie als nächster Schritt (`RechnungAdmin.versandstand`,
  `rechnungsakte.belegweg`).

## Steuer

- **Steuersätze** sind eine Tabelle (`faktura/models/steuersatz.py`), damit
  ein Betrieb einen geänderten Satz zum Stichtag selbst einträgt, statt auf ein
  Update zu warten. Das Risiko eines falsch eingetragenen Satzes liegt damit
  beim Betrieb.
  - Einen Gültigkeitszeitraum gibt es nicht; der Anwender wählt den Satz.
    Gesenkte Sätze wie 16 % und 5 % bleiben wählbar.
  - Positionen speichern den Wert (`'19.00'`), keinen Fremdschlüssel.
  - Ein Satz ist nach dem Anlegen unveränderlich und lässt sich nicht löschen;
    abgelöst wird er über „Wählbar“. 0 % ist die Konstante `STEUERFREI` und
    nicht abwählbar.
  - Die Grundausstattung legt ein `post_migrate`-Handler an, damit auch
    `flush` sie wiederherstellt.
  - Das Modellfeld hat keine `choices`, weil die Systemprüfung aufrufbare
    `choices` vor der Migration auswertet (`forms.steuersatz_auswahl_eingrenzen`).
- Der **Steuerfall** (§ 13b UStG, innergemeinschaftlich, Drittland) ersetzt
  das frühere Häkchen „§ 13b“, das keine Wirkung hatte (`faktura/steuerfall.py`).
- Das **steuerliche Leistungsdatum** (BT-72) ist ein eigenes Feld am Beleg,
  vorbelegt und nie ohne Rückfrage überschrieben. Abschlagsrechnungen haben
  keines (`Beleg.steuerliches_leistungsdatum`).

## Abschläge, Teilleistungen, Schlussrechnung

- Der Leistungsfall ist der Auftrag. Eine Teilleistung ist eine Teilabnahme
  aus ganzen Auftragspositionen (`faktura/models/abnahme.py`).
- Eine Teilschlussrechnung entsteht nur aus einer Teilabnahme, nie von Hand.
- Schluss- und Teilschlussrechnung setzen die gestellten Abschläge selbst ab,
  jede Abschlagsposition genau einmal, im XML als BT-113. Einen Schalter für
  „vereinnahmt“ gibt es nicht (`faktura/services/abschlaege.py`).
- Mehr abzurechnen als beauftragt ist erlaubt, beim Festschreiben aber erst
  nach Hinweis und Bestätigung (`services.mengenueberschreitungen`).
- Abschlagsrechnungen ab der zweiten sind kumuliert: Leistungsstand abzüglich
  der gestellten Abschläge. Kumuliert wird nur bei der Ausgabe, gespeichert
  bleibt der Zuwachs, damit Schlussrechnung und offene Posten unverändert
  rechnen. PDF und XML enthalten dieselben Zeilen, weil der Bildteil keine
  abweichende Leistungsbeschreibung enthalten darf (Abschn. 14.4 Abs. 4a
  UStAE). Abgezogen wird das Gestellte, nicht das Bezahlte, weil sonst ein
  offener Abschlag in zwei Rechnungen gefordert würde. In Projekten mit
  Teilabnahme bleibt der Abschlag einfach (`faktura/services/kumuliert.py`).
  Verworfen: der kumulierte Stand als gespeicherte Positionen mit Abzügen der
  Vorgänger, weil eine Abzugszeile den Vorgänger abrechnen würde.

## Rechnungskorrektur und Nachlass

Eine festgeschriebene Rechnungskorrektur (Nachlass, § 17 UStG) mindert den
offenen Betrag ihrer Rechnung (R-182). Die Rechnung selbst bleibt
unverändert, der offene Betrag ist abgeleitet. Der Bezug läuft über
`vorgaenger`, das nur die Aktion „Nachlass gewähren“ setzt. Ein Entwurf
mindert nichts.

- Alle Nachlässe einer Rechnung zusammen sind höchstens ihr Bruttobetrag,
  geprüft beim Anlegen und beim Festschreiben. Mehr als den offenen Betrag
  nachzulassen ist erlaubt, mit Hinweis auf das entstehende Guthaben; die
  Erstattung bildet die Anwendung nicht ab.
- Eine Rechnung lässt sich erst stornieren, wenn ihre festgeschriebenen
  Nachlässe storniert sind, weil sonst doppelt gutgeschrieben würde.
- „Nachlass stornieren“ an der Korrektur erzeugt ein eigenes Storno ohne
  Neufassung, mit positiven Beträgen, als E-Rechnung mit Typcode 384
  (korrigierte Rechnung), weil es die Korrektur berichtigt; BG-3 nennt die
  Korrektur, wie BR-DE-26 es bei 384 verlangt. Mit 381 kehrte das XML die
  Beträge um.
- Jeder Beleg bekommt seinen eigenen Gegenbeleg, kein Sammelstorno über
  Rechnung und Nachlass. Ob ein Storno zwei Belege aufheben darf, ist nicht
  belegt (UStAE 14.11 verlangt nur einen „spezifischen und eindeutigen“
  Bezug), und in der Buchhaltung gleicht ein Storno genau einen offenen
  Posten aus.
- Beide Stornos gehen an den Kunden, weil sonst Umsatzsteuer des Verkäufers
  und Vorsteuer des Kunden um die Steuer des Nachlasses auseinanderlaufen
  (§ 31 Abs. 5 UStDV: Die Berichtigung wirkt mit Zugang beim Empfänger).
- Ein Nachlassentwurf auf einer stornierten Rechnung lässt sich nicht
  festschreiben.
- Abschlagsrechnungen bekommen keinen Nachlass; dort gilt die Kürzung bei der
  Zahlung.

Die Begründung für Anwender steht in der Hilfe, Kapitel 06
„Rechnungskorrekturen“. Code: `services.nachlaesse`,
`festschreiben.pruefe_rechnungskorrektur`, `rechnung_korrigieren`,
`nachlass_stornieren`, `facturx.typcode`; Tests in `faktura/tests/test_nachlass.py`.

## Positionen

- Die Positionsnummer ist Text. Sortiert wird über einen Schlüssel mit
  aufgefüllten Ziffernfolgen, damit `9` vor `10` und `01.01.0010` vor
  `01.02.0010` steht, in Python wie in SQL (`faktura/positionsnummer.py`,
  `Belegposition.sortierung`).
- Optionale Positionen („optional“, im Bauwesen auch Eventualposition) gibt es
  nur an Angebot und Auftrag. Aus den Summen genommen werden sie an genau zwei
  Stellen, `_summen` und `POSITIONSNETTO` (R-178). Sie zählen nie als „mehr
  als beauftragt“ (`Belegposition.optional`, `services/summen.py`).
- Die Gestaltung der Belegmaske und des PDFs ist in
  [belegansicht.md](belegansicht.md) festgelegt.

## Stammdaten und Zahlungen

- Ein **Kontakt** hat Rollen: Kunde, Lieferant, Partner, Interessent, auch
  mehrere zugleich. Das frühere Modell `Lieferant` ist darin aufgegangen. Die
  Felder `kunde` an Beleg, Projekt und Zahlung bleiben, weil sie die Rolle
  benennen. Dazu das Feld „Eigene Kundennummer“: die Nummer, unter der der
  Kontakt den eigenen Betrieb führt (`faktura/models/stammdaten.py`).
- Adressen, Ansprechpartner und Kontaktwege sind eigene Tabellen.
  `kontakt.strasse` und die übrigen Adressfelder lesen aus der
  Standardadresse.
- Der Vorschlag für Kunden- und Projektnummer im Formular liest nur den
  Bestand und verbraucht keine Nummer (`stammdaten.*_vorschlag`).
- Kopf- und Fußtext sind eine gemeinsame Verwendung „Belegtext“ der
  Textbausteine (`TextbausteinVerwendung`).
- Zahlungseingänge sind `Zahlung` und `Zahlungszuordnung` (n:m). Skonto trägt
  der Anwender ein, automatisch ausgebucht wird nichts
  (`faktura/models/zahlung.py`).

## Erfassung

- Eine Fremdleistung ist ein Einkauf: centgenauer Zeilenbetrag
  `einkauf_netto` (BT-131), kein Verkaufspreis, kein Katalogbezug. Zugeordnet
  wird in der Eingangsrechnung (`erfassung/models.py`).
- Erfasste Zeiten und Fremdleistungen haben eine Änderungsgeschichte
  (`simple_history`), nur lesend; einen früheren Stand zurückzuholen ist
  gesperrt (`core/adminhilfen.py`).
- Gespeicherte Filter der Erfassungsliste gibt es nicht. Zeitraum,
  Sortierung und Art sind Filter der Liste und stehen in der URL.

## Rechte

- Die Auswertungen haben ein eigenes Recht `controlling_ansehen`, getrennt von
  `view_rechnung` (`Beleg.Meta.permissions`).
- Tests melden sich mit Rollen-Fixtures an, nicht als Superuser, damit sie die
  Rechte prüfen, die im Betrieb gelten (`conftest.py`, `core/tests/test_rechte.py`).
- Erfassen ohne Auftragsposition darf jeder, der erfassen darf; ein eigenes
  Recht dafür gibt es nicht.

## Architektur

- **Richtung der Abhängigkeiten:** `core` ← `faktura` ← `erfassung` ←
  `auswertung`. Eine App importiert nur Apps unter sich; obere Apps melden
  sich über Andockstellen in `core/erweiterungen.py` an (Menü, URLs,
  Startseite, Belegaktionen, Schnittstelle, Suche, Reiter). `erfassung` ist
  immer installiert, die Stammdaten liegen in `faktura`
  (`tests/test_richtung.py`).
- **Kern** heißen die Apps, die sich nicht abschalten lassen: `core`,
  `faktura`, `erfassung` und `hilfe`. `auswertung` lässt sich mit
  `PAPERWERK_OHNE_APPS` weglassen; der CI-Lauf „nur Kern“ prüft das
  (`paperwerk/settings/base.py`, `paperwerk/settings/kern.py`).
- **Zusätze** sind Django-Apps außerhalb dieses Repos. Eine Installation
  mountet sie in den Container und trägt sie in `PAPERWERK_ZUSATZAPPS` ein;
  sie registrieren sich über `core/erweiterungen.py`.
- **Die Schnittstelle `/api/v1/`** gehört dem Kern und umfasst die
  Archiv-Anbindung (Eingangsrechnungen, Belegauskunft). Ein Zusatz kann
  Endpunkte ergänzen oder einen vorhandenen mit `ersetzt=True` ersetzen
  (`core/schnittstelle/`, `faktura/api.py`).
- Auswertungen liegen in der App `auswertung`, nicht im Projektpaket. Tests
  liegen in Paketen, keine Testdatei im Wurzelverzeichnis.
- Die Version steht nur in `pyproject.toml`, Schema `0.x.y`
  (`core/version.py`).
- Für Tailwind-Klassen, die im vorkompilierten CSS von Unfold fehlen, gibt es
  einen eigenen Build. Das Ergebnis ist eingecheckt, Node braucht nur, wer eine
  neue Klasse einführt. Die Datei nennt alle fünf Layer in der Reihenfolge von
  Unfold (`stile/eingang.css`, `core/static/core/css/paperwerk.css`,
  `tests/test_stilklassen.py`).

## Oberfläche

- Die Rechnungsliste zeigt den Zahlungsstand als Marke (offen, über Frist,
  bezahlt, abgerechnet). Eine Statusspalte gibt es nicht; festgeschriebene
  Belege zeigt das Schloss (`services.zahlungsstand`, R-176,
  `faktura/admin/spalten.py`).
- Datumsangaben in Listen sind kurz (28.07.2026), über ein Formatmodul, das
  nur `DATE_FORMAT` und `DATETIME_FORMAT` setzt (`paperwerk/datumsformate/`).
- Monatsverläufe auf Startseite und Projektakte sind HTML-Säulen. Die
  Controlling-Seite verwendet Chart.js; ein Skript formatiert dort die Zahlen
  deutsch (`darstellung.saeulen`, `core/static/core/js/diagramme.js`).
- Alle Kennzahlen verwenden eine eigene Kartenkomponente statt Unfolds Karte
  mit `icon` (`templates/admin/_kennzahl.html`).
- Die Zähler in der Seitenleiste beschränken sich auf billige Abfragen
  (Entwürfe, `COUNT`). Ein Zähler „über Frist“ kostete bei zehn Jahren
  Bestand 0,1 s je Seite (`faktura/zaehler.py`).
- Die Startseite beginnt mit „Zu erledigen“. Der Abschnitt wählt aus
  vorhandenen Ergebnissen aus und rechnet nichts selbst
  (`auswertung/aufgaben.py`).
- Unfolds Zeilenaktionen (`actions_row`) werden nicht verwendet, weil ihre
  Rechte für die ganze Liste gelten. Stattdessen entscheidet eine Spalte je
  Zeile (`RechnungAdmin.zahlung_vermerken`).
- Die Schnellsuche nutzt `search_callback` statt `search_models`: höchstens
  acht Treffer je Art, Ziel ist die Akte, angezeigt wird nur, was der Benutzer
  sehen darf. Reiter und Suche melden sich wie das Menü über Andockstellen an
  (`faktura/suche.py`, `core.erweiterungen.suche`, `core.erweiterungen.reiter`).
- Die Kopfleiste der Änderungsseite zeigt vorn nur Akte, den Schritt, den der
  Status verlangt (Festschreiben, Versenden), und PDF. Alles andere steht im
  Dropdown „Weitere …“, der Verlauf als letzter Eintrag, an jedem Admin. An der
  Rechnung ist die Zahlung der erste Eintrag. `SHOW_HISTORY` ist aus
  (`core.adminhilfen.VerlaufInWeitere`, `weitere()`).
