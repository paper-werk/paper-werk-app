# n8n-Beispiele für Ereignisse an Belegen

Drei n8n-Workflows, die auf Ereignisse von Paper-Werk reagieren. Paper-Werk
meldet Aktionen an Belegen (angelegt, geändert, festgeschrieben, versendet,
wiedereröffnet) per HTTP-POST an die Regeln unter „Verwaltung > Ereignisse“;
Ereignismodell, Nutzlast und API beschreibt
[`docs/webhooks.md`](../../docs/webhooks.md). Die Workflows dienen als
Vorlage für eigene: Jeder zeigt eine andere Bauweise.

## Workflows

| Datei | Regel in Paper-Werk | Ergebnis |
| --- | --- | --- |
| `beleg-belegbuch` | angelegt, festgeschrieben, versendet, wiedereröffnet | Zeile in der Data Table `pw_belegbuch` |
| `beleg-angebot-nachfassen` | Angebot, versendet | Nach 14 Tagen ohne Auftrag eine Mail an den Betrieb |
| `beleg-team-nachricht` | Auftrag und Rechnung, angelegt, festgeschrieben, versendet | Nachricht in Slack, Mattermost, Rocket.Chat, Google Chat oder Teams |

`beleg-belegbuch` braucht weder Mail noch ein fremdes System und eignet sich
als erster Test. `beleg-angebot-nachfassen` wartet mit einem Wait-Knoten und
fragt danach über die API, ob zum Angebot ein Auftrag angelegt wurde.
`beleg-team-nachricht` setzt die Nachricht je nach `chat_format` als Text
oder als Adaptive Card für Teams zusammen.

Jeder Workflow beschreibt sich in seiner Notiz „Doku“ im Editor: Zweck,
Regel, Schlüssel in `pw_config`, Credentials, Grenzen. Fachliche
Einstellungen (Wartezeiten, Belegarten) stehen als Konstanten im Knoten
„Konfiguration“.

## Aufbau

Die Workflows folgen den Konventionen der Workflows der Installation
([paper-werk](https://github.com/paper-werk/paper-werk), Ordner `n8n/`):

- Instanzwerte (Adressen, URLs) kommen aus der Data Table `pw_config` über
  `sub-einstellungen`; im Workflow steht keine Adresse.
- Abbrüche meldet `fehler-melden` (`settings.errorWorkflow`).
- Credentials haben feste IDs (`credentials.json.example`), damit sie nach dem
  Import vorausgewählt sind.

Ein Webhook-Workflow beginnt mit dem Knoten „Webhook“ (Header Auth,
Antwort sofort), holt die Einstellungen und prüft im Knoten „Konfiguration“
Aktion und Belegtyp. Passt das Ereignis nicht, etwa beim Aufruf „Test
senden“ (Aktion `test`) oder bei einer zu weit gefassten Regel, liefert der
Knoten keine Items, und der Lauf endet ohne Wirkung.

Paper-Werk wartet nicht auf die Antwort und wiederholt nichts. Ein Ereignis,
das n8n nicht erreicht (Neustart, Ausfall), ist verloren. Workflows, bei denen
das zählt, gleichen zusätzlich über die API ab.

## Einrichtung

Voraussetzung ist eine Installation aus paper-werk mit n8n, den Workflows
`sub-einstellungen` und `fehler-melden` (veröffentlicht) und der Data Table
`pw_config`.

1. **Credentials** in n8n anlegen oder aus `credentials.json.example`
   importieren:
   - „Header Auth Paper-Werk-Ereignis“: Name `X-PaperWerk-Token`, Wert ein
     beliebiges langes Token. Dasselbe Token steht in jeder Regel in
     Paper-Werk.
   - „Header Auth paper-werk Belege“ (nur `beleg-angebot-nachfassen`): Name
     `Authorization`, Wert `Token <Schlüssel>` eines API-Schlüssels in
     Paper-Werk (Verwaltung > API-Schlüssel) für einen Benutzer in der Gruppe
     „Faktura Dienst“. Die Gruppe darf Belege lesen und Kopffelder ändern,
     aber nicht festschreiben.
   - „SMTP account“ (nur `beleg-angebot-nachfassen`) aus der Installation.
2. **pw_config** um die Schlüssel aus `config.json.example` ergänzen, soweit
   die gewählten Workflows sie brauchen (`chat_webhook_url`, `chat_format`
   für `beleg-team-nachricht`).
3. **Workflows importieren**, aus diesem Ordner in den Container der
   Installation:

   ```sh
   docker exec -i -u node <n8n-container> sh -c 'cat > /tmp/wf.json && n8n import:workflow --input=/tmp/wf.json' < workflows/beleg-belegbuch.json
   docker exec -u node <n8n-container> n8n publish:workflow --id=pwBlgBelegbuch1
   docker restart <n8n-container>
   ```

   `workflows.list` nennt im Format von paper-werk, welche Workflows aktiv
   ausgeliefert werden.
4. **Regel in Paper-Werk** anlegen (Verwaltung > Ereignisse): Aktionen und
   Typen wie in der Tabelle oben, Ziel-URL `http://n8n:5678/webhook/<pfad>`
   (Pfad im Knoten „Webhook“), Token wie in der Credential. „Test senden“
   muss Status 200 melden; 404 heißt, der Workflow ist nicht veröffentlicht,
   403, das Token stimmt nicht.

## Prüfung

Aus diesem Ordner:

```sh
python werkzeuge/pruefen.py      # Aufbau: Verbindungen, IDs, Credentials, Syntax
node werkzeuge/probelauf.mjs     # Ablauf: Szenarien aus werkzeuge/szenarien.mjs
```

`probelauf.mjs` führt die Code-Knoten und n8n-Ausdrücke aus, weil beide in
n8n JavaScript sind, und ersetzt HTTP, Mail und Data Tables durch die
Antworten im Szenario. Geprüft wird, was hinausgeht: Mails, HTTP-Aufrufe und
geschriebene Zeilen. Der Lauf ersetzt keinen Test in n8n, findet aber Fehler
in Logik und Ausdrücken, bevor ein Workflow importiert wird. Node braucht
nur, wer die Workflows prüft; für den Import genügt n8n.

## Änderungen

Workflows im n8n-Editor ändern, exportieren (Download) und die Datei hier
ersetzen; die ID bleibt dieselbe. Danach beide Prüfungen laufen lassen. Ein
neuer Workflow braucht eine eindeutige ID mit Präfix `pw`, einen Eintrag in
`workflows.list` und mindestens ein Szenario in `werkzeuge/szenarien.mjs`.
