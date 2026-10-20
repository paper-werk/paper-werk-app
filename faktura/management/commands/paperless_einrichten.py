"""Legt in Paperless die Objekte an, die der Belegweg voraussetzt.

    uv run python manage.py paperless_einrichten [--trocken]

Beide Richtungen setzen Objekte im Archiv voraus: Beim Festschreiben
schreibt die App Custom Fields an das Dokument (``faktura/archiv.py``), der
Eingangsweg liest sie. Eine neue Installation braucht sechs Felder, drei
Tags und einen Dokumenttyp; der Befehl ersetzt die manuelle Einrichtung in
der Oberfläche von Paperless.

Idempotent: Angelegt wird nur, was fehlt; Vorhandenes wird weder geändert
noch umbenannt.
"""

import requests
from django.core.management.base import BaseCommand, CommandError

from faktura import archiv

#: Anzulegende Objekte: Endpunkt, Name, weitere Angaben.
#
# Die Feldnamen sind die Konstanten aus ``archiv.py``, damit es nur eine
# Liste gibt.
FELDER = [
    (archiv.FELD_PROJEKTNUMMER, 'string'),
    (archiv.FELD_RECHNUNGSNUMMER, 'string'),
    (archiv.FELD_GESAMTBETRAG, 'monetary'),
    (archiv.FELD_FAELLIG_AM, 'date'),
    # Felder des Eingangswegs: Der Workflow erkennt beide Beträge, der
    # Benutzer prüft sie, paper-werk erhält den Nettowert.
    (archiv.FELD_NETTOBETRAG, 'monetary'),
    (archiv.FELD_RECHNUNGSDATUM, 'date'),
]

#: Die ersten beiden Tags lösen den Workflow aus und zeigen das Ergebnis;
#: ein Dokument, das nach einem Lauf noch den ersten trägt, ist
#: fehlgeschlagen. Der dritte kennzeichnet eine E-Rechnung; ihn setzt die
#: Erkennung, und die Übernahme liest dann das XML.
SCHLAGWOERTER = [archiv.TAG_SENDEN, archiv.TAG_GESENDET,
                 archiv.TAG_ERECHNUNG]

DOKUMENTTYPEN = ['Eingangsrechnung']


class Command(BaseCommand):
    help = 'Legt in Paperless die Zusatzfelder, Tags und Typen an.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--trocken', action='store_true',
            help='Nur zeigen, was fehlt; nichts anlegen.')

    def handle(self, *args, **options):
        if not archiv.ist_eingerichtet():
            raise CommandError(
                'Paperless ist nicht eingerichtet. Es fehlen PAPERLESS_URL, '
                'PAPERLESS_TOKEN oder PAPERLESS_ARCHIVIERUNG=True; siehe '
                '.env.example.')

        trocken = options['trocken']
        self.stdout.write(f'Archiv: {archiv.settings.PAPERLESS_URL}')

        fehlend = 0
        for name, art in FELDER:
            fehlend += self._sorgen('custom_fields', name, trocken,
                                    data_type=art)
        for name in SCHLAGWOERTER:
            # Kein automatisches Matching, weil die drei Tags den Ablauf
            # steuern; ein automatisch vergebenes "E-Rechnung" leitete ein
            # gewöhnliches PDF auf den XML-Weg.
            fehlend += self._sorgen('tags', name, trocken,
                                    matching_algorithm=0)
        for name in DOKUMENTTYPEN:
            fehlend += self._sorgen('document_types', name, trocken)

        if trocken and fehlend:
            self.stdout.write(self.style.WARNING(
                f'\n{fehlend} Einträge fehlen. Ohne --trocken werden sie '
                f'angelegt.'))
        elif fehlend:
            self.stdout.write(self.style.SUCCESS(
                f'\n{fehlend} Einträge angelegt.'))
        else:
            self.stdout.write(self.style.SUCCESS(
                '\nAlles vorhanden; nichts zu tun.'))

    def _sorgen(self, bereich: str, name: str, trocken: bool, **zusatz) -> int:
        """Legt einen Eintrag an, wenn er fehlt. Gibt 1 zurück, wenn er fehlte.

        ``nummer_fuer`` sucht ohne anzulegen; angelegt wird hier, weil nur
        hier die weiteren Angaben vorliegen (ein Custom Field braucht seinen
        Datentyp, ein Tag nicht).
        """
        vorhanden = archiv.nummer_fuer(bereich, name)
        if vorhanden is not None:
            self.stdout.write(f'  {bereich:<15} {name:<28} da (#{vorhanden})')
            return 0

        if trocken:
            self.stdout.write(self.style.WARNING(
                f'  {bereich:<15} {name:<28} FEHLT'))
            return 1

        antwort = requests.post(
            f'{archiv.settings.PAPERLESS_URL}/api/{bereich}/',
            headers={'Authorization':
                     f'Token {archiv.settings.PAPERLESS_TOKEN}'},
            json={'name': name, **zusatz},
            timeout=archiv.settings.PAPERLESS_TIMEOUT,
        )
        if antwort.status_code >= 400:
            raise CommandError(
                f'{bereich}/{name} ließ sich nicht anlegen: '
                f'{antwort.status_code} {antwort.text[:200]}')

        self.stdout.write(self.style.SUCCESS(
            f'  {bereich:<15} {name:<28} angelegt (#{antwort.json()["id"]})'))
        return 1
