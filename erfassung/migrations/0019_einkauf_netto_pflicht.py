"""Der Zeilenbetrag wird Pflicht, Teil 3 von 3, siehe 0017."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('erfassung', '0018_einkauf_netto_fuellen'),
    ]

    operations = [
        migrations.AlterField(
            model_name='fremdleistung',
            name='einkauf_netto',
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=12,
                verbose_name='Betrag netto',
                help_text='Was der Lieferant für diese Zeile berechnet. Leer '
                          'lassen - dann Menge mal Einkaufspreis. Abweichend '
                          'eintragen bei Rabatt oder Zuschlag auf der Zeile.',
                db_comment='Der Zeilenbetrag laut Lieferant (E-Rechnung: '
                           'BT-131). Belastet das Projektergebnis, auch wenn '
                           'nichts weiterberechnet wird. Die Summe über die '
                           'Eingangsrechnung muss deren Nettobetrag treffen.',
            ),
        ),
    ]
