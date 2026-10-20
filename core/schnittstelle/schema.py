"""Filter für das OpenAPI-Schema.

Ohne Filter nähme drf-spectacular jede Route auf, auch die JSON-Endpunkte
der Admin-Masken (``kundendaten/``, ``bausteine/``).
"""

#: Nur Routen unter diesem Pfad erscheinen im Schema.
EIGENER_PFAD = '/api/'


def nur_eigene_endpunkte(endpoints, **kwargs):
    """Preprocessing-Hook für drf-spectacular.

    Konfiguriert in ``SPECTACULAR_SETTINGS['PREPROCESSING_HOOKS']``. Erhält
    alle Routen als ``(pfad, pfad_regex, methode, callback)`` und gibt die zu
    beschreibenden zurück.
    """
    return [
        eintrag for eintrag in endpoints
        if eintrag[0].startswith(EIGENER_PFAD)
    ]
