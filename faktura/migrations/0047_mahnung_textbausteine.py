"""Die drei Einleitungen der Mahnstufen als Textbausteine.

Bisher stand der Text fest in der PDF-Vorlage. Jetzt kommt er aus
diesen Bausteinen in den Kopftext (``services.mahnung_erstellen``).

**Warum eine Migration und nicht nur ``faktura_textbausteine``.** Der
Befehl läuft beim Setup, nicht beim Update. Eine bestehende Anlage hätte die
Bausteine nie bekommen, und das Vorlagenmenü an der Mahnung zeigte nur die
allgemeinen.

Der Wortlaut ist hier eingefroren, nicht aus ``standardtexte`` gelesen: Eine
Migration muss auch dann noch dasselbe tun, wenn sich der Quelltext ändert.
Was es unter dem Namen schon gibt, bleibt unangetastet.
"""

from django.db import migrations

BAUSTEINE = [
    ('Zahlungserinnerung Einleitung',
     'zu der unten aufgeführten Rechnung konnten wir bisher keinen '
     'Zahlungseingang feststellen. Bitte überweisen Sie den offenen Betrag '
     'bis zum unten genannten Datum. Falls Sie inzwischen bezahlt haben, '
     'betrachten Sie dieses Schreiben bitte als gegenstandslos.'),
    ('Mahnung Einleitung',
     'trotz unserer Zahlungserinnerung konnten wir bisher keinen '
     'Zahlungseingang feststellen. Bitte gleichen Sie den offenen Betrag '
     'bis zum unten genannten Datum aus.'),
    ('Letzte Mahnung Einleitung',
     'trotz mehrfacher Aufforderung ist der unten aufgeführte Betrag '
     'weiterhin offen. Wir fordern Sie hiermit letztmalig auf, ihn bis zum '
     'unten genannten Datum zu begleichen. Nach fruchtlosem Fristablauf '
     'geben wir die Forderung ohne weitere Ankündigung an ein '
     'Inkassounternehmen ab.'),
]


def anlegen(apps, schema_editor):
    Textbaustein = apps.get_model('faktura', 'Textbaustein')
    for name, text in BAUSTEINE:
        Textbaustein.objects.get_or_create(
            name=name,
            defaults={'verwendung': 'belegtext', 'belegart': 'mahnung',
                      'text': text},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('faktura', '0046_zahlung_hilfetexte'),
    ]

    operations = [
        migrations.RunPython(anlegen, migrations.RunPython.noop),
    ]
