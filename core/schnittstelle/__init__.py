"""Schnittstelle unter ``/api/v1/``.

``core`` stellt Authentifizierung per API-Schlüssel (``api_schluessel``),
Status, Selbstauskunft, Schema und Doku. Fachliche Endpunkte registrieren
die Apps über ``core.erweiterungen.api_endpoint()``. Die Apps des Kerns
liefern die Endpunkte, die Paperless und n8n brauchen:

* ``eingangsrechnungen/`` (``erfassung/api.py``): eine geprüfte Rechnung
  aus dem Archiv übernehmen
* ``belege/?paperless_id=`` und ``belege/{id}/xml/`` (``faktura/api.py``):
  das XML einer XRechnung zum Steuerberater

Ein Zusatz (``PAPERWERK_ZUSATZAPPS``) kann über dieselbe Funktion weitere
Endpunkte registrieren oder einen vorhandenen unter derselben URL ersetzen
(``ersetzt=True``). n8n-Workflows, die nur die Archiv-Endpunkte nutzen,
bleiben davon unberührt.
"""
