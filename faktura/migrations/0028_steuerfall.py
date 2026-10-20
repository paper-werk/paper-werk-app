"""Der Steuerfall löst das Häkchen "§ 13b" am Kunden ab.

Wer das Häkchen gesetzt hatte, bekommt den Steuerfall "§ 13b Inland"; das
war die einzige Bedeutung, die es haben konnte. Erst danach wird es
entfernt; die Reihenfolge ist deshalb von Hand gesetzt, makemigrations
hätte das Feld zuerst gelöscht.

Bestehende Belege bleiben beim Regelfall: Sie wurden mit ihren Sätzen
festgeschrieben, und ein nachträglich gesetzter Steuerfall behauptete einen
Vermerk, der nie auf dem Blatt stand.
"""

from django.db import migrations, models


def haekchen_uebernehmen(apps, schema_editor):
    Kunde = apps.get_model('faktura', 'Kunde')
    Kunde.objects.filter(steuerschuldner_13b=True).update(
        steuerfall='inland_13b')


class Migration(migrations.Migration):

    dependencies = [
        ('faktura', '0027_xml_aus_pdf_nachziehen'),
    ]

    operations = [
        migrations.AddField(
            model_name='beleg',
            name='steuerfall',
            field=models.CharField(blank=True, choices=[('', 'Inland (Regelbesteuerung)'), ('inland_13b', '§ 13b UStG: Kunde schuldet die Steuer (Inland)'), ('eu_dienstleistung', 'Dienstleistung an Unternehmen in der EU (Reverse Charge)'), ('eu_lieferung', 'Warenlieferung an Unternehmen in der EU (innergemeinschaftlich)'), ('drittland_dienstleistung', 'Dienstleistung an Unternehmen außerhalb der EU (nicht steuerbar)'), ('ausfuhr', 'Warenlieferung außerhalb der EU (Ausfuhr)')], default='', help_text='Außer beim Regelfall: alle Positionen mit 0 %, dazu der gesetzliche Vermerk auf dem Beleg und in der E-Rechnung.', max_length=30, verbose_name='Steuerfall'),
        ),
        migrations.AddField(
            model_name='kunde',
            name='steuerfall',
            field=models.CharField(blank=True, choices=[('', 'Inland (Regelbesteuerung)'), ('inland_13b', '§ 13b UStG: Kunde schuldet die Steuer (Inland)'), ('eu_dienstleistung', 'Dienstleistung an Unternehmen in der EU (Reverse Charge)'), ('eu_lieferung', 'Warenlieferung an Unternehmen in der EU (innergemeinschaftlich)'), ('drittland_dienstleistung', 'Dienstleistung an Unternehmen außerhalb der EU (nicht steuerbar)'), ('ausfuhr', 'Warenlieferung außerhalb der EU (Ausfuhr)')], default='', help_text='Vorbelegung für neue Belege. Bei allem außer dem Regelfall gehen die Positionen mit 0 % hinaus, und der Beleg trägt den gesetzlichen Vermerk.', max_length=30, verbose_name='Steuerfall'),
        ),
        migrations.RunPython(haekchen_uebernehmen, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='kunde',
            name='steuerschuldner_13b',
        ),
    ]
