"""Aus der Auftragsbestätigung wird der Auftrag.

Der Beleg ist der **Vorgang** und nicht das Schreiben darüber: An seinen
Positionen hängt, was noch abzurechnen ist. Die Auftragsbestätigung ist nur
eine seiner Ausgaben: das PDF, das der Kunde bekommt, und das behält seinen
Namen (siehe ``archiv.DOKUMENTTYPEN``).

**Was hier alles zusammenhängt.** Ein Belegtyp umzubenennen ist nicht ein
Feld, sondern fünf Dinge, und vier davon fallen erst im Betrieb auf:

1. der gespeicherte Wert in ``faktura_beleg.typ`` ('ab' -> 'auftrag'),
2. der ContentType des Stellvertretermodells; den benennt Django bei
   ``RenameModel`` selbst um,
3. die **Rechte**, die an diesem ContentType hängen: ``view_auftrag`` statt
   ``view_auftragsbestaetigung``. Ohne diesen Schritt legt ``migrate`` die
   neuen Rechte einfach zusätzlich an, die alten bleiben liegen, und jede
   Gruppe, die auf ihnen steht, verliert lautlos den Zugriff,
4. der **Nummernkreis** in der Tabelle von django-sequences. Er heißt
   ``auftragsbestaetigung-2026``; bliebe er stehen, begänne die Zählung unter
   dem neuen Namen wieder bei 1 und liefe in die vergebenen Nummern hinein,
5. das Präfix der Belegnummer: ``AU`` statt ``AB``. Der Zähler läuft weiter,
   bestehende Nummern bleiben unverändert; auf AB-2026-0004 folgt
   AU-2026-0005. Ein einmaliger, erklärbarer Sprung in einer durchgehenden
   Reihe; sie umzunummerieren wäre der schwerere Eingriff.
"""

from django.db import migrations, models
import django.db.models.deletion


#: Die vier Rechte, die Django je Modell anlegt.
VERBEN = ['add', 'change', 'delete', 'view']


def typ_umbenennen(apps, schema_editor):
    apps.get_model('faktura', 'Beleg').objects.filter(typ='ab').update(typ='auftrag')


def typ_zurueck(apps, schema_editor):
    apps.get_model('faktura', 'Beleg').objects.filter(typ='auftrag').update(typ='ab')


def _rechte_umbenennen(apps, alt, neu, bezeichnung):
    Permission = apps.get_model('auth', 'Permission')
    for verb in VERBEN:
        Permission.objects.filter(codename=f'{verb}_{alt}').update(
            codename=f'{verb}_{neu}', name=f'Can {verb} {bezeichnung}')


def rechte_umbenennen(apps, schema_editor):
    _rechte_umbenennen(apps, 'auftragsbestaetigung', 'auftrag', 'Auftrag')


def rechte_zurueck(apps, schema_editor):
    _rechte_umbenennen(apps, 'auftrag', 'auftragsbestaetigung', 'Auftragsbestätigung')


def _kreise_umbenennen(apps, alt, neu):
    """Der Nummernkreis heißt ``<kreis>-<jahr>``, je Jahr eine Zeile.

    ``sequences`` ist eine fremde App und muss nicht installiert sein; ist
    sie es nicht, gibt es auch keine Zeilen umzubenennen.
    """
    try:
        Sequence = apps.get_model('sequences', 'Sequence')
    except LookupError:
        return
    for kreis in Sequence.objects.filter(name__startswith=f'{alt}-'):
        Sequence.objects.filter(pk=kreis.pk).update(
            name=neu + kreis.name[len(alt):])


def kreise_umbenennen(apps, schema_editor):
    _kreise_umbenennen(apps, 'auftragsbestaetigung', 'auftrag')


def kreise_zurueck(apps, schema_editor):
    _kreise_umbenennen(apps, 'auftrag', 'auftragsbestaetigung')


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('faktura', '0009_alter_beleg_options'),
    ]

    operations = [
        migrations.RunPython(typ_umbenennen, typ_zurueck),
        migrations.AlterField(
            model_name='beleg',
            name='typ',
            field=models.CharField(
                choices=[('angebot', 'Angebot'), ('auftrag', 'Auftrag'),
                         ('lieferschein', 'Lieferschein'), ('rechnung', 'Rechnung'),
                         ('storno', 'Stornorechnung'), ('gutschrift', 'Rechnungskorrektur'),
                         ('mahnung', 'Mahnung')],
                max_length=20, verbose_name='Belegart'),
        ),
        migrations.AlterField(
            model_name='beleg',
            name='nachtrag_zu',
            field=models.ForeignKey(
                blank=True,
                db_comment='Die Klammer um einen Auftrag samt seiner Nachtraege. '
                           'Flach: zeigt immer auf den Hauptauftrag, nie auf einen '
                           'anderen Nachtrag. Nicht zu verwechseln mit vorgaenger '
                           '(woraus ein Beleg entstanden ist).',
                help_text='Nur bei Aufträgen: der Hauptauftrag, zu dem dieser '
                          'Nachtrag gehört. Leer lassen beim Hauptauftrag selbst.',
                limit_choices_to={'typ': 'auftrag'}, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='nachtraege', to='faktura.beleg',
                verbose_name='Nachtrag zu'),
        ),
        # Der ContentType wird mit umbenannt; darum kuemmert sich contenttypes
        # selbst, angehaengt an RenameModel. Die Rechte tun das nicht.
        migrations.RenameModel(
            old_name='Auftragsbestaetigung',
            new_name='Auftrag',
        ),
        migrations.AlterModelOptions(
            name='auftrag',
            options={'proxy': True, 'verbose_name': 'Auftrag',
                     'verbose_name_plural': 'Aufträge'},
        ),
        migrations.RunPython(rechte_umbenennen, rechte_zurueck),
        migrations.RunPython(kreise_umbenennen, kreise_zurueck),
    ]
