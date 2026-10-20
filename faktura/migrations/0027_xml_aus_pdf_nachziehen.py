"""Legt das XML bestehender E-Rechnungen daneben ab, aus dem PDF gelöst.

Seit 0026 friert das Festschreiben das XML als eigene Datei ein. Rechnungen,
die davor festgeschrieben wurden, haben es nur eingebettet im PDF. Ohne
diesen Nachlauf meldete die Archivprüfung jede davon als "kein XML
hinterlegt", und die Schnittstelle hätte zu ihnen keines.

**Herausgelöst und nicht neu erzeugt**, und das ist der Punkt: Das XML im
PDF ist das, was der Kunde bekommen hat. Ein neu erzeugtes hinge an den
Stammdaten von heute. Die Prüfsumme wird über genau diese Bytes gebildet.

Was sich nicht lesen lässt (Datei fehlt, kein Anhang darin), bleibt ohne
XML; das meldet dann die Archivprüfung, und dort gehört es auch hin. Eine
Migration, die an einem kaputten Einzelfall scheitert, hielte die ganze
Installation an.
"""

import hashlib
import io
import logging

from django.core.files.base import ContentFile
from django.db import migrations

logger = logging.getLogger(__name__)

#: Wie in faktura/facturx.py, dort nicht importiert, weil eine Migration
#: nicht vom heutigen Stand des Codes abhängen darf.
XML_DATEINAME = 'factur-x.xml'
ERECHNUNG_TYPEN = ('rechnung', 'storno', 'gutschrift')


def _xml_aus_pdf(datei) -> bytes | None:
    from pypdf import PdfReader

    with datei.open('rb') as offen:
        anhaenge = PdfReader(io.BytesIO(offen.read())).attachments
    for inhalt in anhaenge.get(XML_DATEINAME, []):
        if inhalt:
            return inhalt
    return None


def nachziehen(apps, schema_editor):
    Beleg = apps.get_model('faktura', 'Beleg')
    offen = (Beleg.objects
             .exclude(status='entwurf')
             .filter(typ__in=ERECHNUNG_TYPEN)
             .exclude(nummer__isnull=True).exclude(nummer='')
             .exclude(pdf='').exclude(pdf__isnull=True)
             .filter(xml_sha256=''))
    for beleg in offen:
        try:
            xml = _xml_aus_pdf(beleg.pdf)
        except Exception as fehler:
            logger.warning('XML zu Beleg %s nicht lesbar: %s', beleg.pk, fehler)
            continue
        if xml is None:
            logger.warning('Im PDF zu Beleg %s steckt kein XML.', beleg.pk)
            continue
        # Neben das PDF, nicht in den Ordner des heutigen Monats; über
        # den Storage direkt, weil FieldFile.save() upload_to anwendet.
        name = beleg.pdf.storage.save(
            beleg.pdf.name.rsplit('.', 1)[0] + '.xml', ContentFile(xml))
        Beleg.objects.filter(pk=beleg.pk).update(
            xml=name,
            xml_sha256=hashlib.sha256(xml).hexdigest(),
            # Vor 0026 gab es nur dieses Profil.
            erechnungsprofil='EN 16931',
        )


class Migration(migrations.Migration):

    dependencies = [
        ('faktura', '0026_beleg_xml'),
    ]

    operations = [
        migrations.RunPython(nachziehen, migrations.RunPython.noop),
    ]
