"""Schreibt die Bedienungsanleitung als PDF, siehe ``hilfe/pdf.py``.

Aufruf, wenn sich die Texte in ``hilfe/texte/`` geändert haben; das
Ergebnis wird committet::

    uv run manage.py hilfe_pdf
    uv run manage.py hilfe_pdf --ziel C:/tmp/anleitung.pdf
"""

from pathlib import Path

from django.core.management.base import BaseCommand

from hilfe.pdf import bedienungsanleitung

ZIEL = Path(__file__).resolve().parents[2] / 'bedienungsanleitung.pdf'


class Command(BaseCommand):
    help = 'Schreibt die Bedienungsanleitung als PDF (Vorgabe: hilfe/bedienungsanleitung.pdf).'

    def add_arguments(self, parser):
        parser.add_argument('--ziel', type=Path, default=ZIEL)

    def handle(self, *args, ziel: Path, **optionen):
        ziel.write_bytes(bedienungsanleitung())
        self.stdout.write(f'Geschrieben: {ziel}')
