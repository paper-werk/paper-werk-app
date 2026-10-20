"""Adresse, Ansprechpartner und Kontaktweg gehören zum Kontakt, nicht zur
Kundenrolle; ihr Feld heißt jetzt ``kontakt``. Daten bleiben."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('faktura', '0031_kunde_wird_kontakt'),
    ]

    operations = [
        migrations.RenameField('adresse', 'kunde', 'kontakt'),
        migrations.RenameField('ansprechpartner', 'kunde', 'kontakt'),
        migrations.RenameField('kontaktweg', 'kunde', 'kontakt'),
    ]
