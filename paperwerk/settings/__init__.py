"""Leer.

Kein ``from .dev import *`` als Fallback: ``DJANGO_SETTINGS_MODULE=
paperwerk.settings`` ergäbe sonst auch im Betrieb die Entwicklungssettings
mit DEBUG=True und Stacktraces samt Datenbankzugang. Ohne Fallback schlägt
der Start mit einer Fehlermeldung fehl.
"""
