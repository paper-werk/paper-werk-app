"""Lieferant wird Kontakt, Teil 1: das neue Feld neben dem alten.

In drei Migrationen, weil PostgreSQL eine Tabelle nicht ändert, solange in
derselben Transaktion Zeilen daran geschrieben wurden ("pending trigger
events"): anlegen, Daten übernehmen, Altes entfernen.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('erfassung', '0013_ansichten_entfernen'),
        ('faktura', '0034_kontakt_rollen'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='eingangsrechnung',
            name='eingangsrechnung_je_lieferant_eindeutig',
        ),
        migrations.AddField(
            model_name='eingangsrechnung',
            name='lieferant_kontakt',
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='+', to='faktura.kontakt'),
        ),
    ]
