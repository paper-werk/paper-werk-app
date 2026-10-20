"""Die drei Gruppen von paper-werk anlegen, die Demogruppen entfernen.

Die Gruppen entstehen hier und nicht erst in den Rechtebefehlen, weil die
Anmeldung sie am Namen erkennt: Eine Rolle, zu der es keine Gruppe gibt,
weist sie ab. Gäbe es die Gruppen erst nach ``setup.sh ... app``, käme vorher
niemand über das Verzeichnis herein, auch nicht die Verwaltung, die das
Setup nachholen könnte. Die RECHTE setzen weiterhin ``faktura_rechte`` und
``erfassung_rechte``; die Liste steht neben den Modellen.

Entfernt werden die älteren Gruppen Faktura, Leistungserfassung und
Leistungserfassung Leitung. Wer darin war, verliert diese
Mitgliedschaft; bei SSO-Konten stellt die nächste Anmeldung sie in den neuen
Gruppen wieder her.

``Faktura Dienst`` bleibt: der Dienstzugang für n8n, kein Demomaterial.

Rückwärts wird nichts wiederhergestellt. Die alten Gruppen trugen nur Rechte,
die die Befehle jederzeit neu setzen; eine leere Gruppe "Faktura"
zurückzuzaubern wäre eine Attrappe.
"""

from django.db import migrations

NEU = ['paper-werk-buero', 'paper-werk-projektleitung', 'paper-werk-superuser']
ALT = ['Faktura', 'Leistungserfassung', 'Leistungserfassung Leitung']


def gruppen_umstellen(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    for name in NEU:
        Group.objects.get_or_create(name=name)
    Group.objects.filter(name__in=ALT).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(gruppen_umstellen, migrations.RunPython.noop),
    ]
