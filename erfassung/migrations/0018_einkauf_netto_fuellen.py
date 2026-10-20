"""Fremdleistung = Einkauf, Teil 2 von 3: die Beträge des Bestands.

Menge mal Einkaufspreis, auf Cent gerundet wie ``positionssumme``. Eine
eigene Migration, siehe 0017.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db import migrations


def betraege_fuellen(apps, schema_editor):
    Fremdleistung = apps.get_model('erfassung', 'Fremdleistung')
    for zeile in Fremdleistung.objects.all():
        zeile.einkauf_netto = (zeile.menge * zeile.einkaufspreis).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP)
        zeile.save(update_fields=['einkauf_netto'])


class Migration(migrations.Migration):

    dependencies = [
        ('erfassung', '0017_fremdleistung_nur_einkauf'),
    ]

    operations = [
        migrations.RunPython(betraege_fuellen, migrations.RunPython.noop),
    ]
