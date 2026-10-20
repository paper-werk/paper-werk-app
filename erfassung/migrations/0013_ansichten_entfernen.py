"""Die App ``ansichten`` (gespeicherte Filter der Erfassungsliste) ist
gestrichen; räumt ihre Reste aus bestehenden Datenbanken.

Hier und nicht in ``ansichten``: Die App gibt es nicht mehr, ihre
Migrationen auch nicht. Alles mit ``IF EXISTS``, weil es sie auf einer frischen
Datenbank nie gab.
"""

from django.db import migrations


def inhaltstypen_entfernen(apps, schema_editor):
    """Inhaltstyp weg; die Rechte daran und ihre Gruppenzuordnungen gehen
    per CASCADE mit."""
    ContentType = apps.get_model('contenttypes', 'ContentType')
    ContentType.objects.filter(app_label='ansichten').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('erfassung', '0012_umlaute_in_feldtexten'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunSQL(
            'DROP TABLE IF EXISTS ansichten_ansicht CASCADE;',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            "DELETE FROM django_migrations WHERE app = 'ansichten';",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunPython(inhaltstypen_entfernen, migrations.RunPython.noop),
    ]
