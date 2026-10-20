"""Gruppennamen und Rollen.

Der Name einer Gruppe ist zugleich der Wert der App-Rolle in Microsoft Entra
ID (Feld "Value") und der Name der Gruppe in Paperless. Eine Zuordnungstabelle
gibt es nicht: Die Rolle ``paper-werk-buero`` im Portal ergibt in beiden
Anwendungen die Gruppe ``paper-werk-buero``.

Eine neue Rolle braucht eine Gruppe mit dem Präfix ``paper-werk-`` (hier und
in der Migration) und ihre Rechte in ``faktura_rechte`` und
``erfassung_rechte``. Die Anmeldung erkennt sie am Präfix.

Die Gruppen der Dienstzugänge für n8n (``api_schluessel``) haben kein
Präfix, damit die Anmeldung sie weder vergibt noch entzieht.
"""

#: Präfix der Gruppen, die die Anmeldung aus den Rollen des Verzeichnisses setzt.
PRAEFIX = 'paper-werk-'

#: Belege schreiben, eigene Stunden buchen.
BUERO = 'paper-werk-buero'

#: Wie ``BUERO``, dazu die Stunden aller, Einkaufspreise, Eingangsrechnungen.
PROJEKTLEITUNG = 'paper-werk-projektleitung'

#: Die Anmeldung setzt ``is_superuser``. Die Gruppe selbst hat keine Rechte;
#: sie macht die Rolle im Admin sichtbar.
SUPERUSER = 'paper-werk-superuser'

ALLE = [BUERO, PROJEKTLEITUNG, SUPERUSER]

# Gruppen der Dienstzugänge (n8n), ohne Präfix. Ihre Rechte setzen
# faktura_rechte und erfassung_rechte, jeweils für die eigene App.

#: Liest Belege, Kunden, Projekte; darf den Archivvermerk setzen.
DIENST = 'Faktura Dienst'

#: Überträgt Eingangsrechnungen aus dem Archiv: anlegen und ansehen, dazu
#: Projekte lesen (die Projektnummer steht am Dokument).
BELEGUEBERNAHME = 'Belegübernahme'
