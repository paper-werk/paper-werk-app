"""Die Bedienungsanleitung als PDF: dieselben Texte wie ``/hilfe/``, mit
Titelblatt (Version, Datum), Inhaltsverzeichnis und Seitenzahlen.

Erzeugt wird nur auf Aufruf (``manage.py hilfe_pdf``), nicht je Release.
Die Datei liegt im Repository; eine ältere Fassung kommt aus der Git-History,
die Version auf dem Titelblatt ordnet sie zu.
"""

from datetime import date

from django.template.loader import render_to_string
from django.utils import timezone

from core.version import VERSION
from faktura.pdf import weasyprint  # registriert unter Windows die Pango-DLLs

from .texte import anleitung


def bedienungsanleitung(stand: date | None = None) -> bytes:
    html = render_to_string('hilfe/pdf.html', {
        'anleitung': anleitung(),
        'version': VERSION,
        'stand': stand or timezone.localdate(),
    })
    return weasyprint.HTML(string=html).write_pdf()
