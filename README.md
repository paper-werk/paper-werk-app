# paper-werk-app

Projektabrechnung von Paper-Werk: Angebote, Aufträge, Lieferscheine,
Rechnungen und Mahnungen, dazu Projekte, Leistungserfassung und Controlling.
Geschrieben für Betriebe in Deutschland, deshalb mit deutscher Fachsprache in
Oberfläche und Code.

- Belege als PDF/A-3b mit eingebettetem Factur-X (EN 16931), für öffentliche
  Auftraggeber als XRechnung.
- Lückenlose Nummernkreise, festgeschriebene Belege unveränderlich, mit
  Prüfsumme abgelegt.
- Eingehende E-Rechnungen (ZUGFeRD/Factur-X und XRechnung in CII) werden zu
  Eingangsrechnungen mit Positionen.
- Abschlags-, Teilschluss- und Schlussrechnungen, Rechnungskorrekturen,
  Steuerfälle nach § 13b UStG, EU und Drittland.

Django 6.1, PostgreSQL 18, Python 3.13. Die Oberfläche ist der Django-Admin
mit [Unfold](https://unfoldadmin.com/); die Gründe stehen in
[docs/entscheidungen.md](docs/entscheidungen.md#grundsätze).

> [!NOTE]
> **Domänensprache & Ubiquitous Language (German Domain Language)**  
> Paper-Werk bildet deutsches Rechnungs-, Steuer- und Handelsrecht ab (GoBD, UStG, Factur-X/ZUGFeRD, XRechnung). Fachbegriffe, Modellbezeichner, Datenbankfelder und Tests folgen deshalb konsequent dem Domain-Driven-Design-Prinzip einer einheitlichen *Ubiquitous Language* auf Deutsch, um semantische Brüche zwischen Rechtsnorm und Implementierung auszuschließen. Infrastruktur-Begriffe bleiben englisch. Näheres steht in [CONTRIBUTING.md](CONTRIBUTING.md#sprache).  
> *(Note for international visitors: This application is specifically tailored to German statutory accounting and tax standards. By design, domain logic, data models, and documentation are written in German.)*

## Einstieg

Voraussetzungen: [uv](https://docs.astral.sh/uv/), Docker (nur für die
Datenbank) und die Bibliotheken für WeasyPrint:

- Debian/Ubuntu: `sudo apt install libpango-1.0-0 libpangoft2-1.0-0
  libharfbuzz-subset0 fonts-crosextra-carlito`
- macOS: `brew install pango`
- Windows: [GTK3-Runtime](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer),
  dann `GTK_BIN_DIR` in der `.env` setzen.

```bash
docker run -d --name paperwerk-db -e POSTGRES_USER=paperwerk \
  -e POSTGRES_PASSWORD=paperwerk -e POSTGRES_DB=paperwerk \
  -p 127.0.0.1:5432:5432 postgres:18

cp .env.example .env
uv sync
uv run playwright install chromium        # für die Browsertests

uv run python manage.py migrate
uv run python manage.py faktura_rechte    # Rechtegruppen
uv run python manage.py erfassung_rechte
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Danach: Oberfläche unter <http://127.0.0.1:8000/admin/>, Schnittstelle
unter `/api/v1/`, ihre Dokumentation unter `/api/v1/doku/`. Vor dem ersten
Beleg die Firmenstammdaten unter „Eigene Firma“ anlegen.

Tests und Lint, wie in der CI:

```bash
uv run pytest
uv run ruff check .
./pruefen.sh                              # beides, mit Protokoll in pruefen.log
```

Die Tests brauchen nur die Datenbank; Paperless und n8n sind dafür nicht
nötig. Wie Beiträge ablaufen, steht in [CONTRIBUTING.md](CONTRIBUTING.md).

### Einstellungen

`paperwerk.settings.dev` und `paperwerk.settings.prod` mit gemeinsamer
Grundlage in `base.py`. `manage.py` und pytest verwenden `dev`, das
Dockerfile `prod`. Alle Umgebungsvariablen stehen mit Erläuterung in
[.env.example](.env.example).

### Entwicklung im vollständigen Stack

Für Arbeit an der Archivanbindung, den n8n-Workflows oder der Installation
läuft die Anwendung im Stack aus
[paper-werk](https://github.com/paper-werk/paper-werk)
zusammen mit Paperless-ngx, n8n und Kopia. Dort steht auch, wie
`runserver` gegen die Datenbank des Stacks arbeitet und wie Demodaten
eingespielt werden.

## Betrieb

```bash
docker build -t paper-werk-app .
```

Das Image enthält Pango, Cairo und die Schrift Carlito, damit WeasyPrint im
Betrieb dieselben Belege erzeugt wie in den Tests. Statische Dateien liefert
WhiteNoise aus. Nötige Umgebungsvariablen: `.env.example`, Abschnitt „Nur für
den Betrieb“.

Persistent zu halten sind zwei Volumes:

| Pfad | Inhalt |
| --- | --- |
| `/app/media` | Festgeschriebene Beleg-PDFs und XML-Dateien, aufbewahrungspflichtig. Die Datenbank verweist nur auf sie. |
| Datenbank | Eigene PostgreSQL-Instanz. |

Fertige Images liegen unter `ghcr.io/paper-werk/paper-werk-app`; eine
vollständige Installation beschreibt paper-werk.

## Name und Logo

Ein Betrieb kann die Anwendung ohne Eingriff in den Quelltext umbenennen:

```bash
PAPER_WERK_MARKE_NAME=Belegwerk
PAPER_WERK_MARKE_UNTERTITEL=Verwaltung und Abrechnung
PAPER_WERK_MARKE_LOGO=marke/logo.svg      # Pfad innerhalb von /app/media
```

Das betrifft Browsertab, Seitenleiste, Anmeldeseite und die Seiten der
Anmeldung über einen Identitätsanbieter. Variablen-, Container- und
Gruppennamen bleiben; die Gruppen `paper-werk-buero`,
`paper-werk-projektleitung` und `paper-werk-superuser` heißen im
Identitätsanbieter, in Paperless und hier gleich. Belege tragen ohnehin die
Firma aus den Stammdaten. Fehlt eine eingestellte Bilddatei, meldet
`manage.py check` das (`paperwerk.W002`). Alle Werte: `.env.example`,
Abschnitt „Name und Logo der Anwendung“.

## Schnittstelle

Anmeldung per Schlüssel im Header, dasselbe Verfahren wie bei Paperless-ngx,
damit n8n für beide denselben Credential-Typ verwendet:

```bash
uv run python manage.py api_schluessel n8n --anlegen
curl -H "Authorization: Token <schluessel>" http://localhost:8000/api/v1/ich/
```

`/api/v1/ich/` liefert die Rechte des Schlüssels.

## Anbindung an Paperless-ngx (optional)

Ist sie eingeschaltet, legt das Festschreiben das PDF zusätzlich in
Paperless-ngx ab, in einem Aufruf mit allen Eigenschaften:

| In Paperless | Quelle |
| --- | --- |
| Titel | Belegart, Nummer, Kunde |
| Dokumentdatum | Belegdatum |
| Dokumenttyp | Belegart |
| Speicherpfad | `PAPERLESS_SPEICHERPFAD`, Vorgabe „Buchführung“ |
| Korrespondent | Kunde, wird bei Bedarf angelegt |
| Rechnungsnummer, Projektnummer, Fällig am, Gesamtbetrag | Custom Fields |

Den Gesamtbetrag erhalten nur Belege mit Preisen, ein Lieferschein nicht.
Die Ablage in `media/` bleibt maßgeblich, weil in Paperless Dokumente
gelöscht werden können; `manage.py pruefe_belegarchiv` prüft sie gegen die
SHA-256-Summen.

```bash
PAPERLESS_URL=http://paperless:8000          # Adresse aus Sicht des Servers
PAPERLESS_ANSICHT_URL=http://localhost:8005  # Adresse aus Sicht des Browsers
PAPERLESS_TOKEN=<schluessel>
PAPERLESS_ARCHIVIERUNG=True
```

Paperless verarbeitet den Upload asynchron und liefert zunächst eine
Task-ID. Steht die Dokument-ID beim Festschreiben noch aus, holt
`manage.py belege_archivieren` sie nach (`--trocken` zeigt, was offen ist).
Der Lauf lädt nichts doppelt hoch; Paperless selbst weist Duplikate nicht
ab. Ist Paperless nicht erreichbar, gilt das Festschreiben trotzdem, und die
Ablage wird nachgeholt.

## Dokumentation

In [docs/](docs/): Rechenregister, Entscheidungen,
Belegansicht, E-Rechnung, Prüfprotokoll Lasttest und eine Vorlage für die
Verfahrensdokumentation nach GoBD. Die Bedienungsanleitung für Anwender liegt
in `hilfe/texte/` und ist in der Anwendung unter `/hilfe/` erreichbar.

## Versionen und Sicherheit

`main` ist die ausgelieferte Version, `dev` die kommende; Pull Requests
gehen gegen `dev`. Versionen folgen dem Schema `0.x.y` und stehen nur in
`pyproject.toml`. Wie Sicherheitslücken gemeldet und behandelt werden, steht
in [SECURITY.md](SECURITY.md).

## Lizenz

Paper-Werk ist freie Software und steht unter der
[GNU Affero General Public License v3 (AGPL-3.0)](LICENSE).
Copyright (C) 2026 Horst Amper / KI-Werkstatt.

Für Betriebe, Systemhäuser und Integratoren, die Paper-Werk ohne die Bedingungen
der AGPL einsetzen möchten (z. B. ohne Offenlegungspflicht bei Anpassungen, zur
Einbindung in geschlossene Systeme oder mit vertraglicher Gewährleistung),
bieten wir separate kommerzielle Lizenzen an. Anfragen an Horst Amper / KI-Werkstatt.
