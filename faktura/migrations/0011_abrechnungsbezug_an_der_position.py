"""Die Belegposition bekommt ihre Leistungsart und ihren Abrechnungsbezug.

``auftragsposition`` zeigt von der Rechnungs- auf die Auftragsposition, die
sie abrechnet - **an der Position und nicht am Beleg**, weil eine Rechnung
Positionen mehrerer Auftraege tragen darf. ``art`` ist die Kopie der
Leistungsart aus dem Katalog; ohne sie waere eine Auftragsposition fuer die
Leistungserfassung unbrauchbar, denn zum Katalog zurueck fuehrt kein Weg.

**Drei Hilfetexte gehen mit**, die schon vorher vom Migrationsstand
abwichen: ``Beleg.kunde``, ``Beleg.projekt`` und ``Firma.kleinunternehmer``.
Sie waren nie Teil dieser Arbeit; sie hier mitzunehmen ist billiger, als den
Drift weiterzuschleppen, bis ihn jemand fuer eine echte Aenderung haelt.
"""

# Erzeugt von Django 6.1 on 2026-08-31 08:41

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('faktura', '0010_auftrag_statt_auftragsbestaetigung'),
    ]

    operations = [
        migrations.AddField(
            model_name='belegposition',
            name='art',
            field=models.CharField(blank=True, choices=[('zeit', 'Zeit (von/bis)'), ('menge', 'Menge'), ('pauschale', 'Pauschale')], default='', help_text='Kommt aus dem Katalog. Leer bei frei eingetragenen Positionen.', max_length=20, verbose_name='Art'),
        ),
        migrations.AddField(
            model_name='belegposition',
            name='auftragsposition',
            field=models.ForeignKey(blank=True, db_comment='Zeigt von der Rechnungs- auf die Auftragsposition. Der Auftrag ergibt sich ueber auftragsposition.beleg - kein zweites Feld dafuer.', help_text='Die beauftragte Leistung, die hier abgerechnet wird. Leer lassen, wenn die Position zu keinem Auftrag gehört.', limit_choices_to={'beleg__status': 'festgeschrieben', 'beleg__typ': 'auftrag'}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='abrechnungen', to='faktura.belegposition', verbose_name='Auftragsposition'),
        ),
        migrations.AlterField(
            model_name='beleg',
            name='kunde',
            field=models.ForeignKey(blank=True, help_text='Verknüpfung zu Projekt/Kunde.', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='belege', to='faktura.kunde', verbose_name='Kunde'),
        ),
        migrations.AlterField(
            model_name='beleg',
            name='projekt',
            field=models.ForeignKey(blank=True, help_text='Verknüpfung zu Projekt/Kunde.', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='belege', to='faktura.projekt', verbose_name='Projekt'),
        ),
        migrations.AlterField(
            model_name='firma',
            name='kleinunternehmer',
            field=models.BooleanField(default=False, help_text='Wenn gesetzt, wird keine Umsatzsteuer ausgewiesen und der vorgeschriebene Hinweis auf den Beleg gedruckt.', verbose_name='Kleinunternehmer nach § 19 UStG'),
        ),
    ]
