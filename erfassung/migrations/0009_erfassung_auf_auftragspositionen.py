"""Erfasst wird auf eine Auftragsposition; der Katalog wird zur Ausnahme.

Kontiert wird kuenftig auf das, was beauftragt ist. Damit kommt der Preis aus
dem **Vertrag** statt aus dem Katalog, und die Rechnung
weiss spaeter, wogegen sie abrechnet.

``leistung`` wird dafuer nullbar. Bestehende Zeilen behalten sie und bleiben
gueltig: Genau eines der beiden Felder muss gefuellt sein, und das ist bei
ihnen der Katalog. Es ist also keine Datenmigration noetig; eine
Aufloesungspflicht entsteht erst dort, wo jemand neu erfasst.

Dazu das Recht ``katalog_frei_waehlen``. Es wird vorerst niemandem vergeben
und schaltet noch nichts ab; es steht da, bevor es gebraucht wird, weil das
Nachruesten eines Rechts jede bestehende Gruppe anfasst.
"""

# Erzeugt von Django 6.1 on 2026-08-31 09:08

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('erfassung', '0008_zuordnung_auf_die_belegposition'),
        ('faktura', '0011_abrechnungsbezug_an_der_position'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='erfassungszeile',
            options={'ordering': ['-datum', '-pk'], 'permissions': [('fuer_andere_erfassen', 'Kann für andere Personen erfassen'), ('katalog_frei_waehlen', 'Darf ohne Auftragsposition erfassen')], 'verbose_name': 'Erfassungszeile', 'verbose_name_plural': 'Erfassung'},
        ),
        migrations.AddField(
            model_name='erfassungszeile',
            name='auftragsposition',
            field=models.ForeignKey(blank=True, db_comment='Der Regelfall. Preis und Einheit kommen von hier - also aus dem Vertrag und nicht aus dem Katalog.', help_text='Die beauftragte Leistung, auf die gearbeitet wurde. Zur Wahl stehen die Positionen der Aufträge dieses Vorhabens.', limit_choices_to={'beleg__status': 'festgeschrieben', 'beleg__typ': 'auftrag'}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='kontierungen', to='faktura.belegposition', verbose_name='Auftragsposition'),
        ),
        migrations.AlterField(
            model_name='erfassungszeile',
            name='leistung',
            field=models.ForeignKey(blank=True, help_text='Nur für Arbeit, die zu keinem Auftrag gehört. Zur Wahl steht, was im Katalog als "in der Erfassung" gekennzeichnet ist.', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='erfassung', to='faktura.katalogposition', verbose_name='Leistung aus dem Katalog'),
        ),
    ]
