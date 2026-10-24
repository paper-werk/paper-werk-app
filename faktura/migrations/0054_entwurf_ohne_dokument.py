"""Löst PDF und XML von Entwürfen, die vor dem Fix in
``beleg_wiedereroeffnen`` wieder geöffnet wurden. ``ansicht_pdf`` lieferte
dort die gespeicherte Datei statt der Vorschau. Die Dateien bleiben im
Ablageverzeichnis."""

from django.db import migrations


def dokument_loesen(apps, schema_editor):
    Beleg = apps.get_model('faktura', 'Beleg')
    Beleg.objects.filter(status='entwurf').exclude(pdf='').exclude(
        pdf=None).update(
        pdf=None, pdf_sha256='', xml=None, xml_sha256='',
        erechnungsprofil='', vorlagenversion='',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('faktura', '0053_texte_ohne_gedankenstrich'),
    ]

    operations = [
        migrations.RunPython(dokument_loesen, migrations.RunPython.noop),
    ]
