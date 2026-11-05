"""Absenderzeile als eigenes Feld der Firma.

Bestehende Datensätze erhalten den bisher zusammengesetzten Text, damit
neue PDFs die Zeile weiter drucken.
"""

from django.db import migrations, models


def befuellen(apps, schema_editor):
    Firma = apps.get_model('faktura', 'Firma')
    for firma in Firma.objects.filter(absenderzeile=''):
        firma.absenderzeile = (
            f'{firma.name} - {firma.strasse} - {firma.plz} {firma.ort}'
        )[:120]
        firma.save(update_fields=['absenderzeile'])


class Migration(migrations.Migration):

    dependencies = [
        ('faktura', '0056_fremdschluessel_an_der_position'),
    ]

    operations = [
        migrations.AddField(
            model_name='firma',
            name='absenderzeile',
            field=models.CharField(
                default='',
                help_text='Steht klein über der Empfängeranschrift, '
                          'vollständig mit Name, Straße, PLZ und Ort, etwa '
                          '„Muster GmbH · Musterweg 1 · 84028 Landshut“. '
                          'Höchstens eine Zeile.',
                max_length=120,
                verbose_name='Absenderzeile',
            ),
        ),
        migrations.RunPython(befuellen, migrations.RunPython.noop),
    ]
