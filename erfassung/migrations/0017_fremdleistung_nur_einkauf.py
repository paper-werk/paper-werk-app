"""Fremdleistung = Einkauf, Teil 1 von 3: das Schema.

Verkaufspreis und Katalogbezug ("Als eigene Leistung") gehen; wie es beim
Kunden erscheint, entscheidet sich beim Übernehmen in die Rechnung. Dazu
kommen die freiwillige Auftragsposition und der Zeilenbetrag
``einkauf_netto``, erst nullbar.

**Warum drei Migrationen:** PostgreSQL verweigert ALTER TABLE und CREATE
INDEX auf einer Tabelle, deren Zeilen in derselben Transaktion gerade
geändert wurden ("pending trigger events"). Schema, Daten (0018) und
Pflichtfeld (0019) laufen deshalb je in einer eigenen Transaktion. In der
Testdatenbank fällt das nicht auf, weil sie keine Zeilen hat.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('erfassung', '0016_lieferant_entfernen'),
        ('faktura', '0034_kontakt_rollen'),
    ]

    operations = [
        migrations.RemoveField(model_name='fremdleistung', name='leistung'),
        migrations.RemoveField(model_name='fremdleistung', name='verkaufspreis'),
        migrations.AddField(
            model_name='fremdleistung',
            name='auftragsposition',
            field=models.ForeignKey(
                blank=True, null=True,
                limit_choices_to={'beleg__status': 'festgeschrieben',
                                  'beleg__typ': 'auftrag'},
                on_delete=django.db.models.deletion.PROTECT,
                related_name='fremdkontierungen',
                to='faktura.belegposition',
                verbose_name='Auftragsposition',
                help_text='Freiwillig: die beauftragte Leistung, zu der dieser '
                          'Einkauf gehört. Beim Übernehmen in die Rechnung gilt '
                          'dann ihr Preis, wenn die Einheit passt.',
            ),
        ),
        migrations.AlterField(
            model_name='fremdleistung',
            name='einkaufspreis',
            field=models.DecimalField(
                decimal_places=4, max_digits=14,
                verbose_name='Einkaufspreis netto',
                help_text='Je Einheit, so wie der Lieferant ihn berechnet.',
                db_comment='Einzelpreis laut Lieferant. Maßgeblich für die '
                           'Kosten ist einkauf_netto, nicht Menge mal Preis.',
            ),
        ),
        migrations.AddField(
            model_name='fremdleistung',
            name='einkauf_netto',
            field=models.DecimalField(
                decimal_places=2, max_digits=12, null=True,
                verbose_name='Betrag netto'),
        ),
    ]
