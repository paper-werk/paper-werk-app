# Webhooks

Paper-Werk meldet Aktionen an Belegen per HTTP-POST an konfigurierte Ziele,
typischerweise einen Webhook-Knoten in n8n. Der Empfänger liest bei Bedarf
weitere Daten über die API und kann unkritische Kopffelder eines Entwurfs
ändern. Beschrieben sind Ereignismodell, Nutzlast, Auslösung, Versand und
die zugehörige API. Neue Aktionen oder Nutzlastfelder bitte vorher in einem
Issue abstimmen, weil Workflows sich auf Namen und Felder verlassen.

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
| `angelegt` | neuer Entwurf, auch durch Umwandeln und Duplizieren | `faktura/services/anlegen.py` |
| `geaendert` | Speichern eines Entwurfs in der Maske | `save_related` des Beleg-Admins |
| `festgeschrieben` | Festschreiben, der Beleg erhält seine Nummer | `beleg_festschreiben` |
| `versendet` | jeder Versand per E-Mail | `beleg_versenden` |
| `wiedereroeffnet` | zurück in den Entwurf | `beleg_wiedereroeffnen` |

- Ein angenommenes Angebot ist `angelegt` beim Typ Auftrag; der Vorgänger
  steht in der Nutzlast.
- `geaendert` entsteht einmal je Speichervorgang in der Maske, nicht je
  geänderter Position. Die Meldestelle liegt im Admin statt im Modell, damit
  `PATCH` über die API nicht meldet.
- `versendet` folgt bei einem Entwurf auf `festgeschrieben`, weil
  `beleg_versenden` vorher festschreibt.
- Die Services melden unabhängig vom Aufrufer. Die API ruft keinen von
  ihnen auf. Ruft eine Erweiterung später etwa `beleg_festschreiben` auf,
  ist die Meldung gewollt; eine Schleife entsteht nicht, weil der Beleg
  danach gesperrt ist.

Folge der Auslösung nur aus der Oberfläche: Ändert ein Workflow einen Beleg,
erfahren andere Workflows davon nichts.

## Auslösung und Empfänger

- Meldestellen rufen `erweiterungen.ereignis(aktion, beleg)` auf. Die
  Funktion registriert per `transaction.on_commit` den Aufruf aller
  Empfänger und kehrt sofort zurück.
- Empfänger melden sich mit `erweiterungen.ereignisempfaenger(funktion)` an
  (Signatur `funktion(aktion, beleg)`). Der Versand an Webhooks ist ein
  solcher Empfänger; weitere Apps können auf dieselben Ereignisse hören,
  ohne dass sich die Meldestellen ändern.
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
    "status": "festgeschrieben",
    "belegdatum": "2026-11-02",
    "faellig_am": "2026-11-16",
    "netto": "1250.00",
    "brutto": "1487.50",
    "version": 7,
    "kunde": {"id": 12, "name": "Muster GmbH"},
    "projekt": {"id": 3, "nummer": "P-2026-003"},
    "vorgaenger": {"id": 4690, "typ": "auftrag"},
    "admin_url": "https://paper-werk.example/admin/faktura/rechnung/4711/change/",
    "api_url": "https://paper-werk.example/api/v1/belege/4711/"
  }
}
```

- `nummer` ist im Entwurf `null`, ebenso `projekt` und `vorgaenger`, wenn
  nicht gesetzt.
- Beträge als Zeichenkette mit zwei Nachkommastellen, wie in der API.
- `version` ist die Version für Optimistic Locking; ein `PATCH` übergibt
  sie unverändert.

## API

Die Belegauskunft (`faktura/api.py`, `/api/v1/belege/`) wird erweitert:

- Lesen: dieselben Felder wie `beleg` in der Nutzlast, zusätzlich die
  vorhandenen Felder der Archiv-Anbindung.
- `GET /api/v1/belege/{id}/pdf/`: das PDF des Belegs.
- `PATCH /api/v1/belege/{id}/`: unkritische Kopffelder eines Entwurfs, mit
  `version`. Weicht sie ab, antwortet die API mit 409. Ein festgeschriebener
  Beleg antwortet mit 409. Validiert wird wie in der Maske.

Änderbar sind `betreff`, `kopftext`, `fusstext`, `bestellnummer`,
`leitweg_id` und `empfaenger_email`, weil sie weder Steuer, Summen und
Fristen noch die Zuordnung zu Kunde und Projekt berühren. Nicht angeboten
werden Anschrift, Daten, Zahlungsziel, Steuerfall, Positionen,
Zustandswechsel (Festschreiben, Versenden) und das Anlegen von Belegen,
weil dabei Summen, Abschläge und erfasste Leistungen konsistent bleiben
müssen.

Eine Erweiterung kann den Endpunkt unter derselben URL ersetzen
(`api_endpoint(ersetzt=True)`); sie liefert die hier beschriebenen Felder
und Aktionen weiter.

## Versand

- Der Webhook-Empfänger ermittelt die zutreffenden Regeln und sendet je
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
- Absicherung: Header `X-PaperWerk-Token` mit dem Token der Regel. Der
  Webhook-Knoten in n8n prüft ihn als „Header Auth“ ohne eigenen Code.
  Ziele verwenden `https` oder liegen im internen Netz der Installation.
- `X-PaperWerk-Ereignis` enthält die Aktion, damit ein Ziel ohne Lesen des
  Rumpfs verzweigen kann.

## Oberfläche

Regeln stehen im Abschnitt „Verwaltung“ der Seitenleiste.

- Arbeitstitel in der Seitenleiste: „Ereignisse“. Eine Regel liest sich
  „Wenn Rechnung festgeschrieben, dann senden an …“.
- Eine Regel hat Name, „aktiv“, Filter nach Aktion und Belegtyp
  (Mehrfachauswahl, leer bedeutet alle), Ziel-URL und Token.
- Der Rumpf ist die feste Nutzlast. Platzhalter wie in Paperless gibt es
  nicht, damit die Felder an einer Stelle definiert sind.

- „Test senden“ an der Regel schickt die Aktion `test` mit einem
  Beispielbeleg und zeigt Status und Antwort des Ziels als Meldung an. Nur
  dieser Aufruf läuft im Request, weil der Anwender auf das Ergebnis
  wartet.

## Abgrenzung

- Zahlungen (`zahlung.eingegangen`, Rechnung bezahlt) folgen in einem
  zweiten Schritt.
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

## Implementierung

| Bereich | Datei |
| --- | --- |
| `ereignis()`, `ereignisempfaenger()` | `core/erweiterungen.py` |
| Modell `Ereignisregel`, Admin | `core/models.py`, `core/admin.py` |
| Versand | `core/webhooks.py` |
| Meldestellen | `faktura/services/anlegen.py`, `festschreiben.py`, `versand.py`, `faktura/admin/belegarten.py` |
| API | `faktura/api.py` |
| n8n-Vorlage | `paper-werk-install`: `n8n/paper-werk-beleg.json` |

## Tests

- Jede Aktion erzeugt genau ein Ereignis; Speichern mit mehreren
  geänderten Positionen ergibt ein `geaendert`.
- `PATCH` über die API erzeugt kein Ereignis.
- Rollback nach der Meldung ruft keinen Empfänger auf.
- Filter nach Aktion und Belegtyp.
- Ausnahme in einem Empfänger: die Meldestelle läuft durch, Warnung im Log.
- `PATCH` mit veralteter `version`, auf festgeschriebenen Beleg und auf
  ausgeschlossene Felder wird abgewiesen.
- Header `X-PaperWerk-Token` und `X-PaperWerk-Ereignis` werden gesetzt.
- Ziel antwortet 500 oder gar nicht: Festschreiben ist davon nicht
  betroffen, Warnung im Log.
