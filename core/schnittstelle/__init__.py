"""Schnittstelle unter ``/api/v1/``.

``core`` stellt Authentifizierung per API-Schlüssel (``api_schluessel``),
Status, Selbstauskunft, Schema und Doku. Fachliche Endpunkte registrieren
die Apps über ``core.erweiterungen.api_endpoint()``:

* ``eingangsrechnungen/`` (``erfassung/api.py``): eine geprüfte Rechnung
  aus dem Archiv übernehmen
* ``belege/`` (``faktura/api/``): Belegauskunft mit Filtern, PDF und XML,
  Kopffelder eines Entwurfs ändern, festschreiben, Ablage im Archiv
  vermerken
* ``projekte/``, ``kunden/``, ``kontakte/`` (``faktura/api/``): nur lesend

Ein Zusatz (``PAPERWERK_ZUSATZAPPS``) kann über dieselbe Funktion weitere
Endpunkte registrieren oder einen vorhandenen unter derselben URL ersetzen
(``ersetzt=True``). n8n-Workflows, die nur die Archiv-Endpunkte nutzen,
bleiben davon unberührt.
"""
