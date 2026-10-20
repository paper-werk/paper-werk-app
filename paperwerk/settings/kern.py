"""Settings nur mit dem Kern, ohne die optionale App ``auswertung``.

Prüft, dass ``core``, ``faktura`` und ``erfassung`` ohne die optionalen Apps
starten und rechnen. Kein Betriebsmodus, weil Startseite, Controlling und
Akten fehlen.

Setzt vor dem Laden von ``base.py`` ``PAPERWERK_OHNE_APPS``, denselben
Schalter, mit dem eine Installation die App weglässt. Getestet wird damit
der Mechanismus selbst.

Aufruf (wie im zweiten Job von ``.github/workflows/pruefen.yml``)::

    DJANGO_SETTINGS_MODULE=paperwerk.settings.kern uv run python manage.py check
    DJANGO_SETTINGS_MODULE=paperwerk.settings.kern uv run python manage.py \
        makemigrations --check --dry-run
    DJANGO_SETTINGS_MODULE=paperwerk.settings.kern uv run pytest core faktura erfassung
"""

import os

os.environ.setdefault('PAPERWERK_OHNE_APPS', 'auswertung')

from .dev import *  # noqa: E402, F403
