"""Datumsformate für die Anzeige, siehe ``FORMAT_MODULE_PATH`` in
``paperwerk/settings/base.py``.

Enthält nur die Abweichungen von Djangos deutschem Locale; Eingabeformate
und Monatsnamen kommen von dort.
"""

DATE_FORMAT = 'd.m.Y'
DATETIME_FORMAT = 'd.m.Y H:i'
