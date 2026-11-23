# Fachszenarien

Testtreiber für Abrechnungsfälle, deren Sollwerte unabhängig vom Code
gerechnet sind. Ein Fall liegt als TOML-Datei vor: Stammdaten, Schritte mit
Datum und fachlicher Aktion, Sollwerte je Schritt, Prüfpunkte am Ende. Wo
die Praxis uneinheitlich ist, führt der Fall je Regelfrage mehrere
zulässige Varianten; der Treiber akzeptiert jede, verlangt aber dieselbe
über alle Schritte eines Falls.

## Ausführung

Die Fälle liegen außerhalb dieses Repos.

```bash
export PAPERWERK_FACHSZENARIEN=/pfad/zu/fachszenarien
export PAPERWERK_FACHSZENARIEN_AUSGABE=/tmp/befunde   # optional
pytest tests/fachszenarien -s
```

Ohne `PAPERWERK_FACHSZENARIEN` werden die Tests übersprungen. Mit `-s`
steht die Befundliste je Fall in der Ausgabe, mit
`PAPERWERK_FACHSZENARIEN_AUSGABE` zusätzlich als Markdown-Datei je Fall.

## Aufbau

| Modul | Inhalt |
|---|---|
| `fall.py` | Einlesen, Schemaprüfung, Varianten (`Bindung`, `vergleichen`) |
| `maske.py` | Formulare aus dem HTML der Admin-Masken lesen und absenden |
| `aktionen.py` | fachliche Aktionen der Fälle auf Masken abgebildet |
| `istwerte.py` | Istwert je Sollwertname |
| `pruefpunkte.py` | Prüfpunkte je Regeltext |
| `test_fachszenarien.py` | Ablauf je Fall und Befundliste |

Geschrieben wird nur über Masken und Formular-POSTs, gelesen über die
Datenbank mit denselben Rechenfunktionen, die Maske und PDF verwenden. Die
POST-Daten entstehen aus dem HTML der Maske, damit Management Form,
Inlines und Vorgaben so ankommen wie aus dem Browser; ein Feld, das die
Maske nicht anbietet, lässt sich nicht setzen. Kunde, Projekt, Einheit und
Katalogpositionen legt `einrichten` direkt an, weil sie Stammdaten sind und
kein Schritt eines Falls.

Die Uhr steht je Schritt auf dessen Datum (Patch von
`django.utils.timezone.now`), weil die Fälle über Monate laufen und die
Erfassung keine künftigen Tage annimmt. Vor jedem Schritt meldet sich der
Client neu an, weil die Sitzung sonst nach zwei Wochen abläuft.

## Abbildung

- Pauschale Leistungen mit Leistungsstand stehen im Auftrag mit Menge 100
  in Prozent (UN/ECE `P1`). Ein Abschlag erfasst den Zuwachs in Prozent auf
  die Auftragsposition und übernimmt ihn mit „Erbrachte Leistungen
  hinzufügen“. So bleibt jede Rechnungsposition mit ihrer Auftragsposition
  verbunden. Eine Pauschale in psch scheidet aus, weil sie in der
  Erfassung immer Menge 1 hat.
- Stundensätze stehen als Auftragsposition in Stunden, wenn der Fall sie
  im Angebot führt, sonst als Katalogposition.
- Zahlungen gehen über „Zahlung vermerken“. Übersteigt der Betrag den
  offenen Betrag oder zahlt ein anderer Kunde, über „Zahlungseingänge“;
  der nicht zuordenbare Rest bleibt unverteilt.
- Eine zweite Schlussrechnung entsteht über „Stornieren und neu schreiben“
  der ersten, weil je Auftrag eine Gesamtabnahme zulässig ist.

## Befunde

| Klasse | Bedeutung | Test |
|---|---|---|
| Fehler | Istwert entspricht keiner noch möglichen Variante, oder ein Prüfpunkt gilt nicht | rot |
| Lücke | Schritt nicht abbildbar; der Fall endet dort oder läuft mit Abweichung weiter | grün |
| Abweichung nach Lücke | Sollwertabweichung nach einer Lücke im selben Fall | grün |
| nicht geprüft | Sollwert oder Prüfpunkt ohne Auswertung im Treiber | grün |

Ein neuer Sollwertname braucht eine Funktion in `ISTWERTE`, ein neuer
Prüfpunkt einen Eintrag in `AM_ENDE` oder `JE_SCHRITT` mit dem Regeltext
aus der Falldatei als Schlüssel. Sollwerte kommen ausschließlich aus den
Fällen; ein Istwert aus einem Lauf wird nie als Sollwert übernommen.
