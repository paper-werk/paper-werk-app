"""Lieferant wird Kontakt, Teil 3: das alte Feld und das Modell gehen."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('erfassung', '0015_lieferant_wird_kontakt'),
    ]

    operations = [
        migrations.RemoveField(model_name='eingangsrechnung', name='lieferant'),
        migrations.RenameField(
            model_name='eingangsrechnung',
            old_name='lieferant_kontakt',
            new_name='lieferant',
        ),
        migrations.AlterField(
            model_name='eingangsrechnung',
            name='lieferant',
            field=models.ForeignKey(
                limit_choices_to={'ist_lieferant': True},
                on_delete=django.db.models.deletion.PROTECT,
                related_name='eingangsrechnungen', to='faktura.kontakt',
                verbose_name='Lieferant'),
        ),
        migrations.AddConstraint(
            model_name='eingangsrechnung',
            constraint=models.UniqueConstraint(
                fields=('lieferant', 'nummer'),
                name='eingangsrechnung_je_lieferant_eindeutig'),
        ),
        migrations.DeleteModel(name='Lieferant'),
    ]
