"""Der Abrechnungsvermerk zeigt auf die Belegposition, nicht mehr auf den Beleg.

**Warum.** Eine Position entsteht aus vielen Erfassungszeilen ("Montage
40 Std" aus zwoelf Erfassungen). Solange der Vermerk am Beleg hing, gab eine
geloeschte Position ihre Zeilen nicht frei: Sie blieben als "abgerechnet"
zurueck, auf keiner Rechnung, in keiner Auswahl je wieder zu sehen. Eine
Ebene tiefer erledigt ``SET_NULL`` das von selbst.

**Warum die Werte verlorengehen.** Aus einem Beleg laesst sich nicht
zurueckrechnen, welche seiner Positionen eine bestimmte Zeile getragen hat -
die Buendelung ist nicht umkehrbar. Die bestehenden Zuordnungen werden
deshalb geloescht, nicht umgerechnet; die betroffenen Zeilen sind danach
wieder offen und lassen sich neu uebernehmen.

**Und warum das hier erlaubt ist:** Zum Zeitpunkt dieser Migration gab es
nur Testdaten, die sich neu aufbauen lassen.

Das Loeschen muss **vor** dem AlterField stehen. Danach waere es zu spaet:
Die Spalte enthaelt dann Beleg-Schluessel, die als Positions-Schluessel
gelesen wuerden: vorhandene Zahlen, die auf voellig fremde Zeilen zeigen.
Ein Fremdschluessel, der auf das Falsche zeigt, ist schlimmer als keiner.
"""

import django.db.models.deletion
from django.db import migrations, models


def zuordnung_loeschen(apps, schema_editor):
    for modell in ('Erfassungszeile', 'Fremdleistung'):
        (apps.get_model('erfassung', modell).objects
         .filter(abgerechnet_in__isnull=False)
         .update(abgerechnet_in=None))


class Migration(migrations.Migration):

    dependencies = [
        ('erfassung', '0007_kostensatz'),
        ('faktura', '0011_abrechnungsbezug_an_der_position'),
    ]

    operations = [
        # Vorwaerts wie rueckwaerts dasselbe: In beide Richtungen zeigen die
        # alten Schluessel auf die falsche Tabelle.
        migrations.RunPython(zuordnung_loeschen, zuordnung_loeschen),
        migrations.AlterField(
            model_name='erfassungszeile',
            name='abgerechnet_in',
            field=models.ForeignKey(blank=True, db_comment='Die Rechnungsposition, auf der diese Zeile steht. SET_NULL: Wird die Position entfernt oder der Entwurf verworfen, ist die Zeile wieder abrechenbar. Der Beleg ergibt sich ueber abgerechnet_in.beleg.', help_text='Wird beim Übernehmen in eine Rechnung gesetzt. Kein Eingabefeld.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='erfassung', to='faktura.belegposition', verbose_name='Abgerechnet in'),
        ),
        migrations.AlterField(
            model_name='fremdleistung',
            name='abgerechnet_in',
            field=models.ForeignKey(blank=True, help_text='Wird beim Übernehmen in eine Rechnung gesetzt. Kein Eingabefeld.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='fremdleistungen', to='faktura.belegposition', verbose_name='Abgerechnet in'),
        ),
    ]
