"""Abschlags- und Schlussrechnung als Feld, nicht als Belegtyp.

Der Belegtyp bleibt ``rechnung``; die Art steht daneben. Damit bleiben der
Nummernkreis und alles, was mit einer Rechnung etwas TUT, unberuehrt: Storno,
Korrektur, Mahnung, E-Rechnung. Die Begruendung samt Messung steht an
``models.Rechnungsart``.

**Die Datenmigration ist Pflicht, nicht Kosmetik.** ``_pruefe_rechnungsart``
verlangt an jeder Rechnung eine Art; ohne diesen Schritt waere jeder
bestehende Beleg beim naechsten Speichern unspeicherbar, und zwar mit einer
Fehlermeldung an einem Feld, das niemand ausgefuellt hat.

Die Stellvertretermodelle legen ihre Rechte selbst an (post_migrate); hier
steht nur der Vermerk, dass es sie gibt.
"""

# Erzeugt von Django 6.1 on 2026-08-31 09:44

from django.db import migrations, models


def bestandsrechnungen_sind_gewoehnlich(apps, schema_editor):
    """Jede vorhandene Rechnung war eine gewoehnliche.

    Abschlag und Schluss gibt es erst ab heute; was vorher geschrieben wurde,
    kann nichts anderes gewesen sein.
    """
    apps.get_model('faktura', 'Beleg').objects.filter(
        typ='rechnung', rechnungsart='').update(rechnungsart='normal')


def art_zuruecknehmen(apps, schema_editor):
    """Rueckwaerts faellt die Unterscheidung weg; das Feld verschwindet ja.

    Abschlaege und Schlussrechnungen werden dabei wieder zu gewoehnlichen
    Rechnungen. Ein Weg zurueck, der Daten verliert, ist besser als keiner:
    Ohne ihn liesse sich die Migration gar nicht zuruecknehmen.
    """
    apps.get_model('faktura', 'Beleg').objects.exclude(
        rechnungsart='').update(rechnungsart='')


class Migration(migrations.Migration):

    dependencies = [
        ('faktura', '0011_abrechnungsbezug_an_der_position'),
    ]

    operations = [
        migrations.CreateModel(
            name='Abschlagsrechnung',
            fields=[
            ],
            options={
                'verbose_name': 'Abschlagsrechnung',
                'verbose_name_plural': 'Abschlagsrechnungen',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('faktura.beleg',),
        ),
        migrations.CreateModel(
            name='Schlussrechnung',
            fields=[
            ],
            options={
                'verbose_name': 'Schlussrechnung',
                'verbose_name_plural': 'Schlussrechnungen',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('faktura.beleg',),
        ),
        migrations.AddField(
            model_name='beleg',
            name='rechnungsart',
            field=models.CharField(blank=True, choices=[('normal', 'Rechnung'), ('abschlag', 'Abschlagsrechnung'), ('schluss', 'Schlussrechnung')], db_comment='Nur bei typ=rechnung gefuellt. Kein eigener Belegtyp: gleiche Felder, gleicher Nummernkreis, gleiche Pflichtangaben - und umwidmen bleibt moeglich.', default='', help_text='Abschlag, Schlussrechnung oder gewöhnliche Rechnung. Solange die Rechnung Entwurf ist, änderbar.', max_length=20, verbose_name='Art der Rechnung'),
        ),
        migrations.AddField(
            model_name='belegposition',
            name='ist_abzug',
            field=models.BooleanField(default=False, help_text='Absetzung eines geleisteten Abschlags. Steht im PDF unter den Leistungen, nicht zwischen ihnen.', verbose_name='Abzugszeile'),
        ),
        # **Nach dem Feld und nicht davor**, weil es vorher die Spalte
        # nicht gibt und die Migration in einen ProgrammingError liefe.
        migrations.RunPython(bestandsrechnungen_sind_gewoehnlich,
                             art_zuruecknehmen),
    ]
