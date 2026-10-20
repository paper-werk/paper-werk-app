# Abbild der Anwendung für den Betrieb im paper-werk-Stack.
#
# Grundlage ist das uv-Image: Es bringt uv mit und hält sich an dieselbe
# uv.lock, aus der auch die Entwicklung installiert. Damit läuft im Container
# nachweislich derselbe Satz Abhängigkeiten wie auf dem Entwicklungsrechner -
# das ist der Grund für diese Basis und nicht python:3.13-slim.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    DJANGO_SETTINGS_MODULE=paperwerk.settings.prod

# WeasyPrint ist ein Python-Paket, aber die eigentliche Arbeit machen
# C-Bibliotheken: Pango setzt den Text, Cairo zeichnet, HarfBuzz formt die
# Glyphen. Die kommen nicht über pip, sondern nur über die Paketverwaltung
# des Systems. Fehlt eine davon, fällt das erst beim ersten PDF auf: Der
# Import gelingt, das Rendern nicht.
#
# fonts-dejavu-core ist nicht optional: Ein Container ohne Schriften rendert
# leere Rechtecke statt Buchstaben. PDF/A verlangt zudem eingebettete
# Schriften, WeasyPrint bettet also ein, was es findet, und findet ohne
# dieses Paket nichts.
#
# fonts-crosextra-carlito steht dabei nicht aus Geschmacksgründen hier.
# beleg.css verlangt "Carlito", "Calibri", "DejaVu Sans", sans-serif; unter
# Windows greift Carlito, im Container gab es weder Carlito noch Calibri.
# Nachgemessen wurde daraufhin nicht etwa DejaVu *Sans* gesetzt, sondern
# DejaVu *Serif*: dieselbe Rechnung, einmal serifenlos und einmal mit
# Serifen, je nachdem wo sie gerendert wurde.
#
# Ohne Carlito sähe der Beleg beim Kunden anders aus als jeder,
# der je geprüft wurde, und die vorlagenversion, die genau solche
# Unterschiede später erklären soll, bliebe dabei gleich. Sie beschreibt
# die Vorlage, nicht die Schriftenlage des Systems.
#
# Carlito ist die metrisch mit Calibri kompatible freie Schrift; mit ihr
# greift auf beiden Systemen derselbe erste Eintrag der Liste.
#
# libharfbuzz-subset0 bettet nur die benutzten Zeichen einer Schrift ein.
# WeasyPrint 70 warnt ohne sie und will sie in einer kommenden Fassung
# verlangen.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libharfbuzz-subset0 \
        libffi8 \
        shared-mime-info \
        fonts-dejavu-core         fonts-crosextra-carlito \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Erst nur die beiden Dateien, aus denen die Abhängigkeiten hervorgehen,
# dann der Quelltext. Ändert sich nur Code, bleibt die teure Schicht mit den
# Paketen im Cache.
#
# --no-dev lässt die Entwicklungsgruppe weg: pytest, ruff und vor allem die
# Debug Toolbar. prod.py hängt sie nicht ein, und
# installiert ist sie hier gar nicht.
#
# UV_NO_DEV=1 weiter oben ist dabei kein Gürtel zum Hosenträger, sondern
# notwendig: "uv run" synchronisiert vor jedem Aufruf selbst nach, und zwar
# per Default MIT der dev-Gruppe. Der collectstatic-Schritt weiter unten hat
# damit alles wieder hereingeholt, was diese Zeile ausschliesst; dann liegen
# pytest, ruff, model_bakery und debug_toolbar im fertigen Image. Im Build-Log
# steht dann "Downloaded ruff" mitten im collectstatic-Schritt.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .

# collectstatic braucht die Settings, und die verlangen SECRET_KEY und
# DATABASE_URL; beides gibt es zur Bauzeit nicht und soll es auch nicht
# geben: Ein Geheimnis, das in einer Image-Schicht landet, ist keines mehr.
#
# Deshalb Wegwerfwerte nur für diesen einen Befehl. Er baut statische
# Dateien, er verbindet sich mit nichts.
RUN DJANGO_SECRET_KEY=nur-fuer-den-build \
    DATABASE_URL=postgres://build:build@localhost/build \
    uv run --no-dev python manage.py collectstatic --noinput --clear

# Nicht als root. Der Container schreibt nur nach media/; alles andere darf
# ihm gehören, ohne dass er es ändern könnte.
RUN useradd --create-home --uid 10001 paperwerk \
    && mkdir -p /app/media \
    && chown -R paperwerk:paperwerk /app/media
USER paperwerk

EXPOSE 8000

# migrate vor dem Start: Der Stack wird per "compose up" aktualisiert, und
# ein Schema, das der Code nicht mehr kennt, ist der häufigste Grund für
# einen Container, der hochkommt und sofort Fehler wirft. --noinput, weil
# hier niemand antworten kann.
CMD ["sh", "-c", "uv run --no-dev python manage.py migrate --noinput && exec uv run --no-dev gunicorn paperwerk.wsgi:application --bind 0.0.0.0:8000 --workers 3 --access-logfile - --error-logfile -"]
