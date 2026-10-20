"""Legt die Standard-Textbausteine an.

    python manage.py faktura_textbausteine

Eine neue Installation hat leere Auswahllisten (Anrede, Grußformel,
Einleitung). Der Befehl legt neun Bausteine an; Wortlaut und Begründung
stehen in ``faktura/standardtexte.py``.

Idempotent: Bausteine mit vorhandenem Namen bleiben unverändert, deshalb
kann der Befehl bei jedem Deployment laufen.

Er legt keine Belege an und vergibt keine Nummern aus dem lückenlosen
Nummernkreis; eine Sperre für produktive Installationen ist daher nicht
nötig, weil Textbausteine Stammdaten sind. Demodaten liegen in
``paper-werk/demodaten/``.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from faktura import standardtexte
from faktura.models import Firma


class Command(BaseCommand):
    help = 'Legt die Standard-Textbausteine an, die noch fehlen.'

    @transaction.atomic
    def handle(self, *args, **options):
        firma = Firma.objects.first()
        neu = standardtexte.anlegen(firma)

        if neu:
            self.stdout.write(self.style.SUCCESS(
                f'{neu} Textbaustein(e) angelegt.'))
        else:
            self.stdout.write('Alle Standardbausteine waren schon da.')

        if firma is None:
            self.stdout.write(self.style.WARNING(
                'Ohne eigene Firma steht die Grußformel ohne Namenszeile. '
                'Firma anlegen, den Baustein "Grußformel" löschen und '
                'diesen Befehl erneut laufen lassen.'))
