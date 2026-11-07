# Webhooks

Paper-Werk meldet Aktionen an Belegen per HTTP-POST an konfigurierte Ziele,
typischerweise einen Webhook-Knoten in n8n. Der Empfänger liest bei Bedarf
weitere Daten über die API und kann unkritische Kopffelder eines Entwurfs
ändern. Beschrieben sind Ereignismodell, Nutzlast, Auslösung, Versand,
Oberfläche und die zugehörige API. Neue Aktionen oder Nutzlastfelder bitte
vorher in einem Issue abstimmen, weil Workflows sich auf Namen und Felder
verlassen.

## Grundsatz

Das Modell folgt den Workflows in Paperless: Ein Ereignis tritt ein, Filter
entscheiden, ob eine Regel greift, die Regel ruft einen Webhook auf. Damit
lassen sich Funktionen ergänzen, ohne Paper-Werk zu ändern.

- Ein Ereignis wird ausgelöst wie ein Event im Browser: Die Meldestelle
  kennt die Empfänger nicht, und Paper-Werk übernimmt keine Verantwortung
  dafür, ob ein Aufruf ankommt oder was der Empfänger damit tut. Es gibt
  weder Wiederholung noch Protokoll, damit Paper-Werk keine
  Fehlerbehandlung für fremde Systeme braucht.
- Gemeldet wird erst nach dem Commit (`transaction.on_commit`), damit kein
  Empfänger von einer zurückgerollten Änderung erfährt.
- Die Nutzlast enthält elementare Eigenschaften des Belegs. Alles Weitere
  holt der Empfänger über die API.
- Nur Aktionen in der Oberfläche lösen aus. Änderungen über die API melden
  nichts, damit ein Workflow, der einen Beleg ändert, sich nicht selbst
  erneut auslöst.

## Ereignismodell

Es gibt ein Ereignis `beleg` mit einer Aktion. Filter einer Regel sind
Aktion und Belegtyp (`BelegTyp`: Angebot, Auftrag, Lieferschein, Rechnung,
Mahnung …).

| Aktion | Auslöser | Meldestelle |
| --- | --- | --- |
| `angelegt` | neuer Beleg, auf jedem Weg (Maske, Umwandeln, Duplizieren, Korrektur, Mahnung, Abrechnung) | `Beleg.save` beim Anlegen |
| `geaendert` | Speichern eines Entwurfs in der Maske mit Änderungen an Kopf oder Positionen | `BelegAdmin.save_related` |
| `festgeschrieben` | Festschreiben, der Beleg erhält seine Nummer | `beleg_festschreiben` |
| `versendet` | jeder Versand per E-Mail | `beleg_versenden` |
| `wiedereroeffnet` | zurück in den Entwurf | `beleg_wiedereroeffnen` |

- Ein angenommenes Angebot ist `angelegt` beim Typ Auftrag; der Vorgänger
  steht in der Nutzlast.
- `angelegt` meldet das Modell, weil Belege auf vielen Wegen entstehen.
  Die API legt keine Belege an.
- `geaendert` entsteht einmal je Speichervorgang in der Maske, nicht je
  geänderter Position. Die Meldestelle liegt im Admin statt im Modell, damit
  `PATCH` über die API nicht meldet.
- `versendet` folgt bei einem Entwurf auf `festgeschrieben`, weil
  `beleg_versenden` vorher festschreibt.
- Die Services melden unabhängig vom Aufrufer. Die API ruft keinen von
  ihnen auf. Ruft eine Erweiterung etwa `beleg_festschreiben` auf, ist die
  Meldung gewollt; eine Schleife entsteht nicht, weil der Beleg danach
  gesperrt ist.

Folge der Auslösung nur aus der Oberfläche: Ändert ein Workflow einen Beleg,
erfahren andere Workflows davon nichts.

## Auslösung und Empfänger

- Fachobjekte registrieren sich als Ereignisquelle
  (`erweiterungen.ereignisquelle()`): Name, Aktionen und Typen für die
  Filter, Funktionen für Typ, Nutzlast und Test-Nutzlast. `faktura`
  registriert die Quelle `beleg` (`faktura/ereignisse.py`); `core` kennt
  Belege nur über sie.
- Meldestellen rufen `erweiterungen.ereignis(quelle, aktion, objekt)` auf,
  für Belege über `faktura.ereignisse.melden(aktion, beleg)`. Die Funktion
  registriert per `transaction.on_commit` den Aufruf aller Empfänger und
  kehrt sofort zurück. Ohne registrierte Empfänger registriert sie nichts.
- Empfänger melden sich mit `erweiterungen.ereignisempfaenger(funktion)` an
  (Signatur `funktion(quelle, aktion, objekt)`). Der Versand an
  Ereignisregeln ist ein solcher Empfänger (`core/webhooks.py`); weitere
  Apps können auf dieselben Ereignisse hören, ohne dass sich die
  Meldestellen ändern.
- Eine Ausnahme in einem Empfänger wird geloggt und erreicht die
  Meldestelle nicht.

## Nutzlast

```json
{
  "ereignis": "beleg",
  "aktion": "festgeschrieben",
  "zeit": "2026-11-02T14:03:11+01:00",
  "beleg": {
    "id": 4711,
    "typ": "rechnung",
    "nummer": "RE-2026-0042",
    "betreff": "Planung Halle 3",
    "brutto": "1487.50",
    "faellig_am": "2026-11-16",
    "kunde": {"name": "Muster GmbH"},
    "projekt": {"id": 3, "nummer": "2026-003", "bezeichnung": "Halle 3"},
    "vorgaenger": {"id": 4690, "typ": "auftrag", "nummer": "AB-2026-0017"},
    "version": 7,
    "admin_url": "https://paper-werk.example/admin/faktura/rechnung/4711/change/",
    "api_url": "https://paper-werk.example/api/v1/belege/4711/"
  }
}
```

- `nummer` ist im Entwurf `null`, ebenso `faellig_am` vor dem
  Festschreiben und `kunde`, `projekt` und `vorgaenger`, wenn nicht gesetzt.
- `kunde` ist bei Projektbelegen der Kunde des Projekts
  (`services.anschriftgeber`), weil ein Beleg Kunde oder Projekt trägt,
  nie beides.
- `brutto` ist der Zahlbetrag als Zeichenkette mit zwei Nachkommastellen,
  wie in der API.
- `version` ist die Version für Optimistic Locking; ein `PATCH` übergibt
  sie unverändert.
- Absolute URLs entstehen aus `PAPER_WERK_URL` (Vorgabe
  `https://<PAPER_WERK_HOSTNAME>`); ohne beides enthalten `admin_url` und
  `api_url` nur den Pfad.
- Der Beleg wird nach dem Commit neu gelesen, die Werte zeigen also den
  gespeicherten Stand.

Die Felder sind aus den Szenarien unten abgeleitet. Ergänzen ist ohne
Bruch möglich, Entfernen nicht.

## API

Die Belegauskunft (`faktura/api.py`, `/api/v1/belege/`):

- Lesen: zusätzlich zu den Feldern der Archiv-Anbindung `faellig_am`,
  `kunde_name`, `vorgaenger_id`, `projekt_id`, `brutto`, `version` und die
  Felder, die `PATCH` ändert, damit ein Workflow sie vorher prüfen kann.
  Die Namen folgen der bestehenden Auskunft (`typ_kennung`, `kunde_name`)
  und weichen deshalb von der verschachtelten Nutzlast ab.
- `projektstand` in der Einzelauskunft eines Projektbelegs: `angeboten`,
  `beauftragt` (samt Nachträgen), `fakturiert` (mit Abschlägen),
  `abgerechnete_leistung` (ohne Abschläge), netto, und `fortschritt` in
  Prozent, berechnet von `services.projektstaende` wie auf der
  Projektseite. In der Liste `null`, weil er je Beleg zwei Abfragen
  kostet.
- `GET /api/v1/belege/?vorgaenger=<id>`: Nachfolger eines Belegs, etwa der
  Auftrag zu einem Angebot.
- `GET /api/v1/belege/{id}/pdf/`: das beim Festschreiben gespeicherte PDF;
  ein Entwurf antwortet mit 404.
- `PATCH /api/v1/belege/{id}/`: Kopffelder eines Entwurfs mit `version`
  als Pflichtangabe. Weicht die Version ab oder ist der Beleg
  festgeschrieben, antwortet die API mit 409; andere Felder werden mit 400
  abgewiesen statt ignoriert. `PUT` gibt es nicht.

Änderbar sind `betreff`, `kopftext`, `fusstext`, `bestellnummer`,
`leitweg_id` und `empfaenger_email`, weil sie weder Steuer, Summen und
Fristen noch die Zuordnung zu Kunde und Projekt berühren. Nicht angeboten
werden Anschrift, Daten, Zahlungsziel, Steuerfall, Positionen,
Zustandswechsel (Festschreiben, Versenden) und das Anlegen von Belegen,
weil dabei Summen, Abschläge und erfasste Leistungen konsistent bleiben
müssen.

`PATCH` verlangt das Recht `faktura.kopf_aendern_beleg`. Die Gruppe
„Faktura Dienst“ erhält es über `faktura_rechte`, ohne `change_beleg`, damit
ein Dienstzugang Kopffelder ändern, aber keine Belege festschreiben kann.

Eine Erweiterung kann den Endpunkt unter derselben URL ersetzen
(`api_endpoint(ersetzt=True)`); sie liefert die hier beschriebenen Felder
und Aktionen weiter.

## Versand

- `core.webhooks.versenden` ermittelt die aktiven Regeln, deren Filter das
  Ereignis zulassen, baut die Nutzlast im aufrufenden Thread und sendet je
  Regel einen POST in einem Hintergrund-Thread, damit die Maske nicht auf
  das Ziel wartet. Zeitlimit 5 s.
- Ergebnis und Antwort werden nicht ausgewertet. Ein Fehler (Zeitlimit,
  Verbindungsfehler, Status außerhalb 2xx) erzeugt eine Warnung im Log.
- Ereignisse können verloren gehen, etwa während eines Neustarts des
  Ziels. Ein Empfänger, der jeden Beleg verarbeiten muss, gleicht
  zusätzlich über die API ab, zum Beispiel täglich alle seit dem letzten
  Lauf festgeschriebenen Belege.
- Die Reihenfolge ist nicht garantiert. Wer einen Zustand braucht, liest
  ihn über `api_url`.
- Header `X-PaperWerk-Token` mit dem Token der Regel. Der Webhook-Knoten in
  n8n prüft ihn als „Header Auth“ ohne eigenen Code.
- Header `X-PaperWerk-Ereignis` mit Quelle und Aktion
  (`beleg.festgeschrieben`), damit ein Ziel ohne Lesen des Rumpfs
  verzweigen kann.
- Ziele verwenden `https`. `http` ist nur für Hostnamen ohne Punkt
  (Dienst im Docker-Netz wie `http://n8n:5678`, `localhost`) oder mit
  `DEBUG` erlaubt, weil das Token sonst im Klartext über fremde Netze ginge.

## Oberfläche

Regeln stehen unter „Verwaltung > Ereignisse“ (Modell `Ereignisregel`).

- Eine Regel hat Name, „aktiv“, Ereignis (Quelle), Aktionen und Typen
  (Mehrfachauswahl, leer bedeutet alle), Ziel-URL und Token. Das Token wird
  beim Anlegen erzeugt und lässt sich ändern.
- Die Liste zeigt die Filter als Satz, etwa „Rechnung: Festgeschrieben“.
- Der Rumpf ist die feste Nutzlast. Platzhalter wie in Paperless gibt es
  nicht, damit die Felder an einer Stelle definiert sind.
- „Test senden“ schickt die Aktion `test`, zusätzlich `"test": true` im
  Rumpf, und einen erfundenen Beleg (`faktura.ereignisse.testnutzlast`):
  ID 0, Nummer `TEST-0001`, Testkunde, keine URLs, Typ der erste der
  Regel. Ein echter Beleg ist ausgeschlossen, weil ein Workflow, der die
  Aktion `test` nicht abfängt, sonst echte Daten ändern oder Kunden
  anschreiben könnte; über die API findet er zu ID 0 nichts. Eine Quelle
  ohne `testnutzlast` meldet einen Fehler, statt zu senden. Der Status des
  Ziels erscheint als Meldung. Nur dieser Aufruf läuft im Request, weil der
  Anwender auf das Ergebnis wartet.
- Rechte sind die Modellrechte von `core.ereignisregel`; die Gruppen von
  `faktura_rechte` erhalten sie nicht, die Pflege bleibt Superusern
  vorbehalten, weil eine Regel Belegdaten an eine beliebige URL schickt.

## Szenarien

Die Szenarien legen fest, welche Felder Nutzlast und API brauchen.
Ausgearbeitete Workflows dazu liegen im Repository `paper-werk-n8n`.

**Angebot nachfassen.** Regel: Angebot, `versendet`. n8n wartet 14 Tage und
fragt dann `?vorgaenger=<id>` ab. Gibt es keinen Auftrag, erhält der
Bearbeiter eine E-Mail mit Nummer, Kunde, Betreff, Betrag und Link in die
Maske. Felder: `id`, `nummer`, `kunde.name`, `betreff`, `brutto`,
`admin_url`.

**Fälligkeit in den Kalender.** Regel: Rechnung, `festgeschrieben` und
`wiedereroeffnet`. Bei `festgeschrieben` legt n8n am Fälligkeitstag einen
Termin „Zahlungseingang prüfen“ an, bei `wiedereroeffnet` löscht es ihn;
wiedergefunden wird der Termin über die Beleg-ID im Termin. Felder: `id`,
`nummer`, `kunde.name`, `brutto`, `faellig_am`, `admin_url`.

**Bestellnummer des Kunden eintragen.** Regel: Auftrag, `angelegt`. n8n
sucht in Paperless die Bestellung des Kunden mit Bezug auf die
Angebotsnummer, liest die Bestellnummer und schreibt sie per `PATCH` in den
Auftrag. Felder: `id`, `kunde.name`, `vorgaenger.nummer`, `version`. Kommt
die Bestellung erst nach dem Auftrag, greift der Workflow nicht; robuster
ist dann ein Workflow in Paperless, der bei Eingang der Bestellung den
Auftrag über die API sucht.

**Projektfortschritt.** Regel: Rechnung, `festgeschrieben`. n8n liest
`projektstand` des Projekts und meldet, wenn der Fortschritt eine Schwelle
überschreitet (etwa 80 und 100 Prozent), damit ein Nachtrag rechtzeitig
angelegt wird. Rechnungen hängen über ihre Positionen am Auftrag, nicht
über `vorgaenger`; deshalb rechnet der Workflow nicht selbst, sondern
liest den Stand der App. Felder: `projekt.id`, `api_url`.

## Abgrenzung

- Zahlungen (Zahlung eingegangen, Rechnung bezahlt) folgen in einem
  zweiten Schritt als eigene Quelle.
- Ereignisse ohne Commit als Auslöser, etwa „Rechnung über Frist“, brauchen
  einen zeitgesteuerten Lauf und sind nicht Teil der ersten Version.

## Verworfene Alternativen

- **Je Aktion ein eigenes Ereignis** (`beleg.festgeschrieben`,
  `angebot.angenommen` …). Ein Ereignis mit Aktion und Belegtyp als Filter
  hält die Regeln einfacher und braucht für neue Belegarten keine neuen
  Namen.
- **Vollständiger Beleg in der Nutzlast.** Doppelt die Serialisierung der
  API; Positionen braucht kaum ein Workflow.
- **Django-Signale (`post_save`).** Am `post_save` des Belegs ist nicht
  erkennbar, ob festgeschrieben, versendet oder nur ein Feld geändert wurde,
  und er feuert auch bei Änderungen über die API.
- **Filter „nicht durch API-Schlüssel X“** gegen Schleifen. Überflüssig,
  weil die API nicht meldet.
- **Warten auf eine Antwort** (Hook, der einen Vorgang aufhält). Ein
  ausgefallenes n8n blockierte das Festschreiben.
- **Zustellung mit Outbox, Wiederholung und Protokoll.** Garantierte
  Zustellung macht Paper-Werk verantwortlich für die Erreichbarkeit fremder
  Systeme und braucht eine Tabelle, einen Befehl und eine Zeitsteuerung in
  der Installation. Empfänger, die Vollständigkeit brauchen, gleichen über
  die API ab.
- **Hintergrundwarteschlange (Celery, `django.tasks`).** Braucht einen
  weiteren Dienst für einen Aufruf, dessen Ergebnis nicht ausgewertet wird.
- **HMAC-Signatur des Rumpfs.** Die Prüfung erfordert in n8n einen
  Code-Knoten; ein Token im Header prüft der Webhook-Knoten selbst.
- **Synchroner Aufruf im Request.** Die Maske wartete bei nicht
  erreichbarem Ziel bis zum Zeitlimit, je zutreffender Regel.
- **`URLField` für das Ziel.** Djangos `URLValidator` lehnt Hostnamen ohne
  Punkt ab, also die Dienste im Docker-Netz.

## Implementierung

| Bereich | Datei |
| --- | --- |
| `ereignisquelle()`, `ereignis()`, `ereignisempfaenger()` | `core/erweiterungen.py` |
| Modell `Ereignisregel`, Prüfung der Ziel-URL | `core/models.py` |
| Maske und „Test senden“ | `core/admin.py` |
| Versand | `core/webhooks.py` |
| Quelle `beleg`, Nutzlast | `faktura/ereignisse.py` |
| Meldestellen | `faktura/models/beleg.py`, `faktura/services/festschreiben.py`, `faktura/services/versand.py`, `faktura/admin/beleg.py` |
| API | `faktura/api.py` |
| `PAPER_WERK_URL` | `paperwerk/settings/base.py` |

## Tests

- `faktura/tests/test_ereignisse.py`: jede Meldestelle erzeugt genau ein
  Ereignis; Speichern mit Kopf und zwei neuen Positionen ergibt ein
  `geaendert`, Speichern ohne Änderung keins; Rollback meldet nichts;
  Inhalt der Nutzlast; `PATCH` ändert ohne Ereignis, weist veraltete
  Version, fehlende Version, andere Felder, festgeschriebene Belege und
  fehlendes Recht ab; Filter `vorgaenger`; `pdf/`.
- `core/tests/test_ereignisse.py`: Filter der Regel; Prüfung der Ziel-URL;
  POST nur an zutreffende, aktive Regeln mit beiden Headern; Fehler und
  Fehlerstatus landen im Log; Festschreiben trotz unerreichbarem Ziel;
  Ausnahme eines Empfängers bleibt dort; Maske, Anlegen, unbekannte Aktion,
  „Test senden“ mit Status und Fehler.
