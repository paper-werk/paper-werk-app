"""Aus ``Kunde`` wird ``Kontakt``, mit denselben Daten.

``RenameModel`` benennt Tabelle und Inhaltstyp um. Die Rechte heißen danach
anders (``view_kontakt``); sie werden hier umbenannt statt neu angelegt,
damit die Gruppen sie behalten.
"""

from django.db import migrations

TAETIGKEITEN = ('add', 'change', 'delete', 'view')


def rechte_umbenennen(apps, schema_editor, alt='kunde', neu='kontakt',
                      anzeige='Kontakt'):
    Permission = apps.get_model('auth', 'Permission')
    for taetigkeit in TAETIGKEITEN:
        Permission.objects.filter(
            content_type__app_label='faktura',
            codename=f'{taetigkeit}_{alt}',
        ).update(codename=f'{taetigkeit}_{neu}',
                 name=f'Can {taetigkeit} {anzeige}')


def rechte_zurueck(apps, schema_editor):
    rechte_umbenennen(apps, schema_editor, alt='kontakt', neu='kunde',
                      anzeige='Kunde')


class Migration(migrations.Migration):

    dependencies = [
        ('faktura', '0030_umlaute_in_feldtexten'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RenameModel('Kunde', 'Kontakt'),
        migrations.AlterModelOptions(
            name='kontakt',
            options={'ordering': ['name'], 'verbose_name': 'Kontakt',
                     'verbose_name_plural': 'Kontakte'},
        ),
        migrations.RunPython(rechte_umbenennen, rechte_zurueck),
    ]
