"""Ein Anfangsstand für jede vorhandene Zeile.

Die Änderungsgeschichte schreibt erst ab jetzt mit. Ohne diesen Stand
fehlte bei der ersten Änderung einer alten Zeile das "vorher"; man sähe
nur den neuen Wert. Dasselbe, was ``manage.py populate_history`` tut, hier
aber bei jeder Installation von selbst.

Eigene Migration, getrennt vom Anlegen der Tabellen: Daten und Schema in
einem Schritt scheitern bei PostgreSQL an "pending trigger events" (siehe
0017 bis 0019).
"""

from django.db import migrations
from django.utils import timezone

MODELLE = ('Erfassungszeile', 'Fremdleistung')


def anfangsstand(apps, schema_editor):
    jetzt = timezone.now()
    for name in MODELLE:
        modell = apps.get_model('erfassung', name)
        historie = apps.get_model('erfassung', f'Historical{name}')
        felder = [f.attname for f in modell._meta.concrete_fields]
        historie.objects.bulk_create(
            (historie(**{f: getattr(zeile, f) for f in felder},
                      history_date=jetzt, history_type='+',
                      history_change_reason='Anfangsstand')
             for zeile in modell.objects.iterator()),
            batch_size=500,
        )


def entfernen(apps, schema_editor):
    for name in MODELLE:
        apps.get_model('erfassung', f'Historical{name}').objects.filter(
            history_change_reason='Anfangsstand').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('erfassung', '0020_aenderungsgeschichte'),
    ]

    operations = [
        migrations.RunPython(anfangsstand, entfernen),
    ]
