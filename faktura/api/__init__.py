"""REST-Schnittstelle der Faktura unter ``/api/v1/``.

``anbindung.py`` enthält die Archiv-Anbindung (XML zum Steuerberater) und den
Rückweg für Workflows, die auf Ereignisse reagieren. ``belege.py`` erweitert
sie zur vollen Belegauskunft mit Filtern, ``festschreiben`` und
``archiviert``; ``projekte.py`` und ``kunden.py`` liefern Projekte, Kunden
und Kontakte. ``faktura/apps.py`` registriert die ViewSets über
``core.erweiterungen.api_endpoint()``.
"""
