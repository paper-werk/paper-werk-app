"""Schema von ``faktura`` auf dem Stand von 0.1.15, ersetzt 0001 bis 0052.

Datenbanken, die alle ersetzten Migrationen angewendet haben, führen diese
Migration nicht aus (``replaces``). Datenmigrationen, die nur Bestandsdaten
umgestellt haben, entfallen. Erhalten bleibt das Anlegen der Textbausteine
für die Einleitungen der Mahnstufen; der Wortlaut ist eingefroren, damit die
Migration unabhängig von ``standardtexte`` dasselbe tut.
"""

import django.core.validators
import django.db.models.deletion
import faktura.models.steuersatz
import simple_history.models
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


MAHNUNG_BAUSTEINE = [
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


def mahnung_bausteine_anlegen(apps, schema_editor):
    Textbaustein = apps.get_model('faktura', 'Textbaustein')
    for name, text in MAHNUNG_BAUSTEINE:
        Textbaustein.objects.get_or_create(
            name=name,
            defaults={'verwendung': 'belegtext', 'belegart': 'mahnung',
                      'text': text},
        )


class Migration(migrations.Migration):

    initial = True

    replaces = [
        ('faktura', '0001_initial'),
        ('faktura', '0002_katalogposition_art_katalogposition_kontierbar'),
        ('faktura', '0003_alter_katalogposition_kontierbar'),
        ('faktura', '0004_beleg_paperless_task_id'),
        ('faktura', '0005_kunde_kaeuferreferenz_alter_beleg_leitweg_id'),
        ('faktura', '0006_alter_kunde_nummer'),
        ('faktura', '0007_beleg_nachtrag_zu'),
        ('faktura', '0008_belegposition_langtext_katalogposition_langtext_and_more'),
        ('faktura', '0009_alter_beleg_options'),
        ('faktura', '0010_auftrag_statt_auftragsbestaetigung'),
        ('faktura', '0011_abrechnungsbezug_an_der_position'),
        ('faktura', '0012_rechnungsarten'),
        ('faktura', '0013_projektnummer_wird_vorgeschlagen'),
        ('faktura', '0014_versand_vorbereiten'),
        ('faktura', '0015_anschreiben_als_baustein'),
        ('faktura', '0016_belegtext_und_belegart'),
        ('faktura', '0017_schreibschutz_aufhebbar'),
        ('faktura', '0018_beleg_wiedereroeffnen'),
        ('faktura', '0019_versandprotokoll'),
        ('faktura', '0020_versandprotokoll_zurueck'),
        ('faktura', '0021_alter_beleg_empfaenger_email'),
        ('faktura', '0022_alter_belegposition_steuersatz_and_more'),
        ('faktura', '0023_stammdaten_und_zahlungen'),
        ('faktura', '0024_kontaktdaten_beschriftung'),
        ('faktura', '0025_zahlung_beschriftung'),
        ('faktura', '0026_beleg_xml'),
        ('faktura', '0027_xml_aus_pdf_nachziehen'),
        ('faktura', '0028_steuerfall'),
        ('faktura', '0029_belegfassung'),
        ('faktura', '0030_umlaute_in_feldtexten'),
        ('faktura', '0031_kunde_wird_kontakt'),
        ('faktura', '0032_teiltabellen_zeigen_auf_kontakt'),
        ('faktura', '0033_constraints_auf_kontakt'),
        ('faktura', '0034_kontakt_rollen'),
        ('faktura', '0035_steuerliches_leistungsdatum'),
        ('faktura', '0036_steuerliches_leistungsdatum_fuellen'),
        ('faktura', '0037_abnahme'),
        ('faktura', '0038_positionszeitraum'),
        ('faktura', '0039_abgesetzte_position'),
        ('faktura', '0040_leistungsdatum_hilfetext'),
        ('faktura', '0041_bestellnummer_kurz'),
        ('faktura', '0042_abschlagskuerzung'),
        ('faktura', '0043_positionsnummer_als_text'),
        ('faktura', '0044_optionale_position'),
        ('faktura', '0045_mahnstufe_auswahl'),
        ('faktura', '0046_zahlung_hilfetexte'),
        ('faktura', '0047_mahnung_textbausteine'),
        ('faktura', '0048_mahngebuehr_an_firma'),
        ('faktura', '0049_zeilenarten'),
        ('faktura', '0050_version'),
        ('faktura', '0051_version'),
        ('faktura', '0052_steuersatz_tabelle'),
    ]

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Abnahme',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version', models.PositiveIntegerField(db_comment='Optimistic Locking: wird bei jedem Update inkrementiert und beim Speichern im Admin mit der Version beim Laden verglichen.', default=0, editable=False, verbose_name='Version')),
                ('art', models.CharField(choices=[('gesamt', 'Gesamtabnahme'), ('teil', 'Teilabnahme')], default='gesamt', max_length=10, verbose_name='Art')),
                ('bezeichnung', models.CharField(blank=True, default='', help_text='Bei der Teilabnahme: welche Teilleistung, z. B. "Leistungsphasen 1-4".', max_length=200, verbose_name='Bezeichnung')),
                ('leistungsbeginn', models.DateField(blank=True, null=True, verbose_name='Leistungsbeginn')),
                ('leistungsende', models.DateField(blank=True, null=True, verbose_name='Leistungsende')),
                ('abgenommen_am', models.DateField(blank=True, help_text='Abnahme bzw. Vollendung unserer Leistung, nicht die Abnahme der Bauleistung eines anderen. Leer: noch offen.', null=True, verbose_name='Abgenommen am')),
                ('steuerliches_leistungsdatum', models.DateField(blank=True, help_text='Geht als Leistungsdatum in die Rechnung. Vorbelegt mit dem Abnahmedatum; nur ändern, wenn der Steuerberater es anders sieht.', null=True, verbose_name='Leistungsdatum')),
                ('notiz', models.TextField(blank=True, default='', verbose_name='Notiz')),
                ('erfasst_am', models.DateTimeField(auto_now_add=True, verbose_name='Erfasst am')),
            ],
            options={
                'verbose_name': 'Abnahme',
                'verbose_name_plural': 'Abnahmen',
                'ordering': ['auftrag', 'art', 'pk'],
            },
        ),
        migrations.CreateModel(
            name='Adresse',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('verwendung', models.CharField(choices=[('rechnung', 'Rechnungsanschrift'), ('post', 'Postanschrift'), ('lieferung', 'Lieferanschrift'), ('sonstige', 'Sonstige')], default='rechnung', help_text='Wofür diese Anschrift vorgeschlagen wird.', max_length=20, verbose_name='Verwendung')),
                ('bezeichnung', models.CharField(blank=True, default='', help_text='Zur Unterscheidung in der Liste: "Zentrale", "Niederlassung Landshut". Steht auf keinem Beleg.', max_length=100, verbose_name='Bezeichnung')),
                ('zusatz', models.CharField(blank=True, default='', help_text='Erscheint im Anschriftfeld über der Straße.', max_length=200, verbose_name='Adresszusatz')),
                ('strasse', models.CharField(blank=True, default='', max_length=200, verbose_name='Straße')),
                ('plz', models.CharField(blank=True, default='', max_length=10, verbose_name='PLZ')),
                ('ort', models.CharField(blank=True, default='', max_length=100, verbose_name='Ort')),
                ('land', models.CharField(default='DE', help_text='Zwei Buchstaben nach ISO 3166. Pflichtangabe der E-Rechnung.', max_length=2, verbose_name='Ländercode')),
                ('ist_standard', models.BooleanField(default=False, help_text='Die Anschrift, die gilt, wenn keine andere genannt ist. Genau eine je Kunde.', verbose_name='Standardanschrift')),
            ],
            options={
                'verbose_name': 'Adresse',
                'verbose_name_plural': 'Adressen',
                'ordering': ['-ist_standard', 'verwendung', 'ort'],
            },
        ),
        migrations.CreateModel(
            name='Firma',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='Firmenname')),
                ('zusatz', models.CharField(blank=True, default='', max_length=200, verbose_name='Namenszusatz')),
                ('strasse', models.CharField(max_length=200, verbose_name='Straße')),
                ('plz', models.CharField(max_length=10, verbose_name='PLZ')),
                ('ort', models.CharField(max_length=100, verbose_name='Ort')),
                ('land', models.CharField(default='DE', help_text='Zwei Buchstaben nach ISO 3166, wird für die E-Rechnung gebraucht.', max_length=2, verbose_name='Ländercode')),
                ('telefon', models.CharField(blank=True, default='', max_length=50, verbose_name='Telefon')),
                ('email', models.EmailField(blank=True, default='', max_length=254, verbose_name='E-Mail')),
                ('web', models.CharField(blank=True, default='', max_length=100, verbose_name='Web')),
                ('steuernummer', models.CharField(blank=True, default='', max_length=30, verbose_name='Steuernummer')),
                ('ust_id', models.CharField(blank=True, default='', max_length=20, verbose_name='USt-IdNr.')),
                ('kleinunternehmer', models.BooleanField(default=False, help_text='Wenn gesetzt, wird keine Umsatzsteuer ausgewiesen und der vorgeschriebene Hinweis auf den Beleg gedruckt.', verbose_name='Kleinunternehmer nach § 19 UStG')),
                ('bank', models.CharField(blank=True, default='', max_length=100, verbose_name='Kreditinstitut')),
                ('iban', models.CharField(blank=True, default='', max_length=34, verbose_name='IBAN')),
                ('bic', models.CharField(blank=True, default='', max_length=11, verbose_name='BIC')),
                ('geschaeftsfuehrung', models.CharField(blank=True, default='', max_length=200, verbose_name='Geschäftsführung')),
                ('registergericht', models.CharField(blank=True, default='', max_length=100, verbose_name='Registergericht')),
                ('handelsregister', models.CharField(blank=True, default='', max_length=50, verbose_name='Handelsregisternummer')),
                ('logo', models.ImageField(blank=True, null=True, upload_to='firma/', verbose_name='Logo')),
                ('standard_fusstext', models.TextField(blank=True, default='', help_text='Wird verwendet, wenn am Beleg selbst kein Fußtext steht.', verbose_name='Standardtext unter den Positionen')),
                ('mahngebuehr_erinnerung', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=8, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='Gebühr Zahlungserinnerung')),
                ('mahngebuehr_mahnung', models.DecimalField(decimal_places=2, default=Decimal('2.50'), max_digits=8, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='Gebühr Mahnung')),
                ('mahngebuehr_letzte', models.DecimalField(decimal_places=2, default=Decimal('2.50'), max_digits=8, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='Gebühr Letzte Mahnung')),
            ],
            options={
                'verbose_name': 'Firma',
                'verbose_name_plural': 'Firma',
            },
        ),
        migrations.CreateModel(
            name='Katalogposition',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nummer', models.CharField(blank=True, db_comment='Freiwillig und eindeutig. NULL statt Leerstring, damit mehrere Positionen ohne Nummer nebeneinander bestehen.', help_text='Freiwillig. Wenn vergeben, dann eindeutig; sie dient dem Wiederfinden und dem Verweis im Angebot.', max_length=30, null=True, unique=True, verbose_name='Artikelnummer')),
                ('bezeichnung', models.CharField(max_length=300, verbose_name='Bezeichnung')),
                ('langtext', models.TextField(blank=True, default='', help_text='Ausführliche Leistungsbeschreibung. Erscheint im Beleg unter der Bezeichnung und lässt sich dort noch ändern.', verbose_name='Langtext')),
                ('einheit', models.CharField(blank=True, default='Stk', max_length=20, verbose_name='Einheit')),
                ('einzelpreis', models.DecimalField(decimal_places=2, max_digits=12, verbose_name='Einzelpreis netto')),
                ('steuersatz', models.CharField(default=faktura.models.steuersatz.vorgabe, max_length=5, verbose_name='Steuersatz')),
                ('kontierbar', models.BooleanField(db_comment='Erscheint diese Leistung in der Leistungserfassung? Vorgabe an; abgewählt wird bei reinen Angebotszeilen.', default=True, help_text='Diese Leistung erscheint in der Leistungserfassung. Abwählen bei Positionen, die nur auf Angebote gehören; eine "Baustelleneinrichtung pauschal" bucht niemand im Feld.', verbose_name='In der Erfassung')),
                ('art', models.CharField(choices=[('zeit', 'Zeit (von/bis)'), ('menge', 'Menge'), ('pauschale', 'Pauschale')], default='menge', help_text='Bestimmt, WIE erfasst wird: Zeit über von/bis, Menge über eine Zahl, Pauschale gar nicht (Menge 1).', max_length=10, verbose_name='Art der Erfassung')),
            ],
            options={
                'verbose_name': 'Katalogposition',
                'verbose_name_plural': 'Leistungskatalog',
                'ordering': ['bezeichnung'],
            },
        ),
        migrations.CreateModel(
            name='Textbaustein',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Der Name in der Auswahlliste, kurz und wiedererkennbar.', max_length=100, unique=True, verbose_name='Name')),
                ('verwendung', models.CharField(choices=[('belegtext', 'Text auf dem Beleg'), ('mail', 'Anschreiben beim Versand')], help_text='Bestimmt, in welcher Auswahlliste der Baustein erscheint. Beim Anschreiben sind Platzhalter erlaubt: {nummer}, {beleg}, {empfaenger}, {betrag}, {firma}.', max_length=20, verbose_name='Verwendung')),
                ('belegart', models.CharField(blank=True, choices=[('angebot', 'Angebot'), ('auftrag', 'Auftrag'), ('lieferschein', 'Lieferschein'), ('rechnung', 'Rechnung'), ('storno', 'Stornorechnung'), ('gutschrift', 'Rechnungskorrektur'), ('mahnung', 'Mahnung')], default='', help_text='Leer lassen, wenn der Baustein für jede Belegart taugt. Sonst erscheint er nur dort.', max_length=20, verbose_name='Belegart')),
                ('text', models.TextField(verbose_name='Text')),
            ],
            options={
                'verbose_name': 'Textbaustein',
                'verbose_name_plural': 'Textbausteine',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Ansprechpartner',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version', models.PositiveIntegerField(db_comment='Optimistic Locking: wird bei jedem Update inkrementiert und beim Speichern im Admin mit der Version beim Laden verglichen.', default=0, editable=False, verbose_name='Version')),
                ('anrede', models.CharField(blank=True, choices=[('', 'ohne (neutral anschreiben)'), ('frau', 'Frau'), ('herr', 'Herr')], default='', max_length=10, verbose_name='Anrede')),
                ('titel', models.CharField(blank=True, default='', help_text='"Dr.", "Prof."; steht vor dem Namen.', max_length=30, verbose_name='Titel')),
                ('vorname', models.CharField(blank=True, default='', max_length=100, verbose_name='Vorname')),
                ('nachname', models.CharField(max_length=100, verbose_name='Nachname')),
                ('funktion', models.CharField(blank=True, default='', help_text='"Bauleitung", "Buchhaltung", "Projektsteuerung": wofür diese Person zuständig ist.', max_length=100, verbose_name='Funktion')),
                ('ist_standard', models.BooleanField(default=False, help_text='Wer gemeint ist, wenn kein anderer genannt wird. Höchstens einer je Kunde.', verbose_name='Hauptansprechpartner')),
                ('aktiv', models.BooleanField(default=True, verbose_name='Aktiv')),
                ('notiz', models.TextField(blank=True, default='', verbose_name='Notiz')),
                ('erfasst_am', models.DateTimeField(auto_now_add=True, verbose_name='Erfasst am')),
                ('adresse', models.ForeignKey(blank=True, help_text='Nur bei mehreren Standorten nötig.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ansprechpartner', to='faktura.adresse', verbose_name='Anschrift')),
            ],
            options={
                'verbose_name': 'Ansprechpartner',
                'verbose_name_plural': 'Ansprechpartner',
                'ordering': ['-ist_standard', 'nachname', 'vorname'],
            },
        ),
        migrations.CreateModel(
            name='Beleg',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version', models.PositiveIntegerField(db_comment='Optimistic Locking: wird bei jedem Update inkrementiert und beim Speichern im Admin mit der Version beim Laden verglichen.', default=0, editable=False, verbose_name='Version')),
                ('typ', models.CharField(choices=[('angebot', 'Angebot'), ('auftrag', 'Auftrag'), ('lieferschein', 'Lieferschein'), ('rechnung', 'Rechnung'), ('storno', 'Stornorechnung'), ('gutschrift', 'Rechnungskorrektur'), ('mahnung', 'Mahnung')], max_length=20, verbose_name='Belegart')),
                ('rechnungsart', models.CharField(blank=True, choices=[('normal', 'Rechnung'), ('abschlag', 'Abschlagsrechnung'), ('schluss', 'Schlussrechnung'), ('teilschluss', 'Teilschlussrechnung')], db_comment='Nur bei typ=rechnung gefüllt. Kein eigener Belegtyp: gleiche Felder, gleicher Nummernkreis, gleiche Pflichtangaben, und umwidmen bleibt möglich.', default='', help_text='Abschlag, Schlussrechnung oder gewöhnliche Rechnung. Solange die Rechnung Entwurf ist, änderbar.', max_length=20, verbose_name='Art der Rechnung')),
                ('status', models.CharField(choices=[('entwurf', 'Entwurf'), ('festgeschrieben', 'Festgeschrieben'), ('storniert', 'Storniert')], default='entwurf', max_length=20, verbose_name='Status')),
                ('nummer', models.CharField(blank=True, max_length=30, null=True, unique=True, verbose_name='Belegnummer')),
                ('empfaenger', models.TextField(blank=True, default='', help_text='Erscheint zeilengetreu im Anschriftfeld des Belegs. Wird beim Auswählen des Kunden gefüllt, wenn es leer ist.', verbose_name='Empfänger')),
                ('empfaenger_name', models.CharField(blank=True, default='', max_length=200, verbose_name='Name (E-Rechnung)')),
                ('empfaenger_strasse', models.CharField(blank=True, default='', max_length=200, verbose_name='Straße (E-Rechnung)')),
                ('empfaenger_plz', models.CharField(blank=True, default='', max_length=10, verbose_name='PLZ (E-Rechnung)')),
                ('empfaenger_ort', models.CharField(blank=True, default='', max_length=100, verbose_name='Ort (E-Rechnung)')),
                ('empfaenger_land', models.CharField(default='DE', max_length=2, verbose_name='Land')),
                ('empfaenger_email', models.EmailField(blank=True, default='', max_length=254, verbose_name='E-Mail des Empfängers')),
                ('empfaenger_ust_id', models.CharField(blank=True, default='', max_length=20, verbose_name='USt-IdNr.')),
                ('zahlungsziel_tage', models.PositiveSmallIntegerField(default=14, verbose_name='Zahlungsziel (Tage)')),
                ('belegdatum', models.DateField(blank=True, null=True, verbose_name='Belegdatum')),
                ('leistungsdatum', models.DateField(blank=True, help_text='Zeitpunkt oder Beginn des Zeitraums, in dem geleistet wird. Was er im einzelnen Beleg bedeutet, steht an der jeweiligen Belegart.', null=True, verbose_name='Leistung von')),
                ('leistungsdatum_bis', models.DateField(blank=True, null=True, verbose_name='Leistung bis')),
                ('steuerliches_leistungsdatum', models.DateField(blank=True, db_comment='BT-72. Bei Abschlägen immer leer (Anzahlung).', help_text='Der Tag, an dem die Leistung vollendet bzw. abgenommen ist, die Pflichtangabe nach § 14 Abs. 4 Nr. 6 UStG. Leer gelassen, gilt das Ende des Zeitraums. Ein Abschlag hat keines.', null=True, verbose_name='Leistungsdatum')),
                ('betreff', models.CharField(blank=True, default='', max_length=200, verbose_name='Betreff')),
                ('kopftext', models.TextField(blank=True, default='', verbose_name='Text über den Positionen')),
                ('fusstext', models.TextField(blank=True, default='', verbose_name='Text unter den Positionen')),
                ('mahnstufe', models.PositiveSmallIntegerField(blank=True, choices=[(1, 'Zahlungserinnerung'), (2, 'Mahnung'), (3, 'Letzte Mahnung')], null=True, verbose_name='Mahnstufe')),
                ('faellig_am', models.DateField(blank=True, help_text='Wird bei der Festschreibung aus dem Zahlungsziel berechnet.', null=True, verbose_name='Zahlbar bis')),
                ('steuerfall', models.CharField(blank=True, choices=[('', 'Inland (Regelbesteuerung)'), ('inland_13b', '§ 13b UStG: Kunde schuldet die Steuer (Inland)'), ('eu_dienstleistung', 'Dienstleistung an Unternehmen in der EU (Reverse Charge)'), ('eu_lieferung', 'Warenlieferung an Unternehmen in der EU (innergemeinschaftlich)'), ('drittland_dienstleistung', 'Dienstleistung an Unternehmen außerhalb der EU (nicht steuerbar)'), ('ausfuhr', 'Warenlieferung außerhalb der EU (Ausfuhr)')], default='', help_text='Außer beim Regelfall: alle Positionen mit 0 %, dazu der gesetzliche Vermerk auf dem Beleg und in der E-Rechnung.', max_length=30, verbose_name='Steuerfall')),
                ('leitweg_id', models.CharField(blank=True, default='', help_text='BT-10 der E-Rechnung. Bei öffentlichen Auftraggebern die Leitweg-ID, sonst die Referenz des Kunden. Wird aus den Kundenstammdaten vorbelegt.', max_length=50, verbose_name='Käuferreferenz')),
                ('bestellnummer', models.CharField(blank=True, default='', max_length=50, verbose_name='Bestellnr. des Kunden')),
                ('pdf', models.FileField(blank=True, null=True, upload_to='belege/%Y/%m/', verbose_name='PDF')),
                ('pdf_sha256', models.CharField(blank=True, default='', help_text='SHA-256 des PDF. Weist nach, dass die Datei seit der Festschreibung unverändert ist.', max_length=64, verbose_name='Prüfsumme')),
                ('xml', models.FileField(blank=True, null=True, upload_to='belege/%Y/%m/', verbose_name='XML')),
                ('xml_sha256', models.CharField(blank=True, default='', help_text='SHA-256 des XML. Weist nach, dass die E-Rechnung seit der Festschreibung unverändert ist.', max_length=64, verbose_name='Prüfsumme XML')),
                ('erechnungsprofil', models.CharField(blank=True, default='', help_text='"EN 16931" oder "XRECHNUNG": wie das XML beim Festschreiben entstanden ist.', max_length=20, verbose_name='E-Rechnungsprofil')),
                ('vorlagenversion', models.CharField(blank=True, default='', help_text='Mit welcher Fassung der Druckvorlage der Beleg erzeugt wurde. Ohne diese Angabe lässt sich später nicht mehr nachvollziehen, warum ein Beleg anders aussieht.', max_length=20, verbose_name='Vorlagenversion')),
                ('paperless_id', models.PositiveIntegerField(blank=True, help_text='Nummer des Dokuments in Paperless. Wird vom Archivierungslauf gesetzt, nicht von Hand.', null=True, unique=True, verbose_name='Dokument-ID im Archiv')),
                ('archiviert_am', models.DateTimeField(blank=True, null=True, verbose_name='Archiviert am')),
                ('paperless_task_id', models.CharField(blank=True, default='', help_text='Quittung für einen laufenden Upload. Wird geleert, sobald die Dokument-ID feststeht.', max_length=64, verbose_name='Aufgabennummer im Archiv')),
                ('erstellt_am', models.DateTimeField(auto_now_add=True, verbose_name='Angelegt am')),
                ('versendet_am', models.DateTimeField(blank=True, null=True, verbose_name='Erstmals versendet am')),
                ('versendet_an', models.EmailField(blank=True, default='', max_length=254, verbose_name='Erstmals versendet an')),
                ('festgeschrieben_am', models.DateTimeField(blank=True, null=True, verbose_name='Festgeschrieben am')),
                ('geaendert_am', models.DateTimeField(blank=True, help_text='Gesetzt, sobald ein festgeschriebener Beleg wieder zum Entwurf gemacht wurde. Leer heißt: seit der Festschreibung unverändert.', null=True, verbose_name='Wiedereröffnet am')),
                ('abnahme', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='rechnungen', to='faktura.abnahme', verbose_name='Abnahme')),
                ('ansprechpartner', models.ForeignKey(blank=True, help_text='Wer beim Kunden gemeint ist. Wird beim Anlegen vorbelegt; auf dem Beleg erscheint die Zeile "z. Hd." im Empfängerfeld.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='belege', to='faktura.ansprechpartner', verbose_name='Ansprechpartner')),
                ('festgeschrieben_von', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Festgeschrieben von')),
                ('geaendert_von', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Wiedereröffnet von')),
                ('nachtrag_zu', models.ForeignKey(blank=True, db_comment='Die Klammer um einen Auftrag samt seiner Nachträge. Flach: zeigt immer auf den Hauptauftrag, nie auf einen anderen Nachtrag. Nicht zu verwechseln mit vorgaenger (woraus ein Beleg entstanden ist).', help_text='Nur bei Aufträgen: der Hauptauftrag, zu dem dieser Nachtrag gehört. Leer lassen beim Hauptauftrag selbst.', limit_choices_to={'typ': 'auftrag'}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='nachtraege', to='faktura.beleg', verbose_name='Nachtrag zu')),
                ('vorgaenger', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='nachfolger', to='faktura.beleg', verbose_name='Vorgängerbeleg')),
            ],
            options={
                'verbose_name': 'Beleg',
                'verbose_name_plural': 'Belege',
                'ordering': ['-erstellt_am'],
                'permissions': [('archivieren_beleg', 'Kann den Archivvermerk setzen'), ('controlling_ansehen', 'Kann die Auswertungen sehen'), ('beleg_wiedereroeffnen', 'Kann Belege wieder öffnen')],
            },
        ),
        migrations.AddField(
            model_name='abnahme',
            name='auftrag',
            field=models.ForeignKey(limit_choices_to={'nachtrag_zu__isnull': True, 'status': 'festgeschrieben', 'typ': 'auftrag'}, on_delete=django.db.models.deletion.PROTECT, related_name='abnahmen', to='faktura.beleg', verbose_name='Auftrag'),
        ),
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
            name='Angebot',
            fields=[
            ],
            options={
                'verbose_name': 'Angebot',
                'verbose_name_plural': 'Angebote',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('faktura.beleg',),
        ),
        migrations.CreateModel(
            name='Auftrag',
            fields=[
            ],
            options={
                'verbose_name': 'Auftrag',
                'verbose_name_plural': 'Aufträge',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('faktura.beleg',),
        ),
        migrations.CreateModel(
            name='Lieferschein',
            fields=[
            ],
            options={
                'verbose_name': 'Lieferschein',
                'verbose_name_plural': 'Lieferscheine',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('faktura.beleg',),
        ),
        migrations.CreateModel(
            name='Mahnung',
            fields=[
            ],
            options={
                'verbose_name': 'Mahnung',
                'verbose_name_plural': 'Mahnungen',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('faktura.beleg',),
        ),
        migrations.CreateModel(
            name='Rechnung',
            fields=[
            ],
            options={
                'verbose_name': 'Rechnung',
                'verbose_name_plural': 'Rechnungen',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('faktura.beleg',),
        ),
        migrations.CreateModel(
            name='Rechnungskorrektur',
            fields=[
            ],
            options={
                'verbose_name': 'Rechnungskorrektur',
                'verbose_name_plural': 'Rechnungskorrekturen',
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
        migrations.CreateModel(
            name='Stornorechnung',
            fields=[
            ],
            options={
                'verbose_name': 'Stornorechnung',
                'verbose_name_plural': 'Stornorechnungen',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('faktura.beleg',),
        ),
        migrations.CreateModel(
            name='Teilschlussrechnung',
            fields=[
            ],
            options={
                'verbose_name': 'Teilschlussrechnung',
                'verbose_name_plural': 'Teilschlussrechnungen',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('faktura.beleg',),
        ),
        migrations.CreateModel(
            name='Belegfassung',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pdf', models.FileField(blank=True, null=True, upload_to='belege/%Y/%m/', verbose_name='PDF')),
                ('pdf_sha256', models.CharField(blank=True, default='', max_length=64, verbose_name='Prüfsumme PDF')),
                ('xml', models.FileField(blank=True, null=True, upload_to='belege/%Y/%m/', verbose_name='XML')),
                ('xml_sha256', models.CharField(blank=True, default='', max_length=64, verbose_name='Prüfsumme XML')),
                ('erechnungsprofil', models.CharField(blank=True, default='', max_length=20, verbose_name='E-Rechnungsprofil')),
                ('vorlagenversion', models.CharField(blank=True, default='', max_length=20, verbose_name='Vorlagenversion')),
                ('leitweg_id', models.CharField(blank=True, default='', max_length=50, verbose_name='Käuferreferenz')),
                ('bestellnummer', models.CharField(blank=True, default='', max_length=50, verbose_name='Bestellnummer des Kunden')),
                ('paperless_id', models.PositiveIntegerField(blank=True, null=True, verbose_name='Dokument-ID im Archiv')),
                ('abgeloest_am', models.DateTimeField(auto_now_add=True, verbose_name='Abgelöst am')),
                ('grund', models.TextField(verbose_name='Grund der Neuausstellung')),
                ('abgeloest_von', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Abgelöst von')),
                ('beleg', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='fassungen', to='faktura.beleg', verbose_name='Beleg')),
            ],
            options={
                'verbose_name': 'Frühere Fassung',
                'verbose_name_plural': 'Frühere Fassungen',
                'ordering': ['beleg', 'abgeloest_am'],
            },
        ),
        migrations.CreateModel(
            name='Belegposition',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.CharField(default='10', max_length=30, verbose_name='Pos.')),
                ('sortierung', models.CharField(db_index=True, default='', editable=False, max_length=120)),
                ('bezeichnung', models.CharField(max_length=300, verbose_name='Bezeichnung')),
                ('langtext', models.TextField(blank=True, default='', help_text='Ausführliche Beschreibung unter der Bezeichnung. Kommt aus dem Katalog und ist hier frei änderbar.', verbose_name='Langtext')),
                ('menge', models.DecimalField(decimal_places=3, default=Decimal('1.000'), max_digits=10, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='Menge')),
                ('einheit', models.CharField(blank=True, default='Stk', max_length=20, verbose_name='Einheit')),
                ('einzelpreis', models.DecimalField(decimal_places=2, max_digits=12, verbose_name='Einzelpreis netto')),
                ('steuersatz', models.CharField(default=faktura.models.steuersatz.vorgabe, max_length=5, verbose_name='Steuersatz')),
                ('leistung_von', models.DateField(blank=True, null=True, verbose_name='Leistung von')),
                ('leistung_bis', models.DateField(blank=True, null=True, verbose_name='Leistung bis')),
                ('optional', models.BooleanField(default=False, help_text='Zählt nicht in die Summe. Im PDF steht der Betrag in Klammern, bei Menge 0 gar nicht.', verbose_name='Optional')),
                ('zeilenart', models.CharField(choices=[('leistung', 'Leistung'), ('titel', 'Titel'), ('text', 'Text'), ('zuschlag', 'Zuschlag')], default='leistung', help_text='Titel: Überschrift mit Summe über alle Positionen, deren Nummer mit der Titelnummer und einem Punkt beginnt. Text: freier Absatz ohne Preis. Zuschlag: Prozent auf die Positionen darüber.', max_length=10, verbose_name='Zeilenart')),
                ('zuschlag_prozent', models.DecimalField(blank=True, decimal_places=2, help_text='Nur bei einem Zuschlag: der Satz in Prozent, z. B. 3 für Nebenkosten 3 %.', max_digits=6, null=True, verbose_name='Zuschlag %')),
                ('zuschlag_auf', models.CharField(blank=True, default='', help_text='Leer: auf alle Leistungen. Eine Titelnummer (01): auf diesen Titel. Eine Positionsnummer (01.0020): auf genau diese Position.', max_length=30, verbose_name='Zuschlag auf')),
                ('art', models.CharField(blank=True, choices=[('zeit', 'Zeit (von/bis)'), ('menge', 'Menge'), ('pauschale', 'Pauschale')], default='', help_text='Kommt aus dem Katalog. Leer bei frei eingetragenen Positionen.', max_length=20, verbose_name='Art')),
                ('ist_abzug', models.BooleanField(default=False, help_text='Absetzung eines geleisteten Abschlags. Steht im PDF unter den Leistungen, nicht zwischen ihnen.', verbose_name='Abzugszeile')),
                ('ist_abschlagsrest', models.BooleanField(default=False, help_text='Der nicht bezahlte Teil eines Abschlags, der deshalb nicht abgesetzt wird. Wird beim Absetzen errechnet.', verbose_name='Nicht bezahlter Abschlag')),
                ('abgesetzte_position', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='absetzungen', to='faktura.belegposition', verbose_name='Abgesetzte Abschlagsposition')),
                ('auftragsposition', models.ForeignKey(blank=True, db_comment='Zeigt von der Rechnungs- auf die Auftragsposition. Der Auftrag ergibt sich über auftragsposition.beleg; kein zweites Feld dafür.', help_text='Die beauftragte Leistung, die hier abgerechnet wird. Leer lassen, wenn die Position zu keinem Auftrag gehört.', limit_choices_to={'beleg__status': 'festgeschrieben', 'beleg__typ': 'auftrag', 'zeilenart__in': ('leistung', 'zuschlag')}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='abrechnungen', to='faktura.belegposition', verbose_name='Auftragsposition')),
                ('beleg', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='positionen', to='faktura.beleg', verbose_name='Beleg')),
            ],
            options={
                'verbose_name': 'Position',
                'verbose_name_plural': 'Positionen',
                'ordering': ['sortierung', 'pk'],
            },
        ),
        migrations.AddField(
            model_name='abnahme',
            name='positionen',
            field=models.ManyToManyField(blank=True, help_text='Nur bei der Teilabnahme: die Positionen der Teilleistung: ganze Positionen, aus diesem Auftrag oder seinen Nachträgen.', related_name='teilabnahmen', to='faktura.belegposition', verbose_name='Auftragspositionen'),
        ),
        migrations.CreateModel(
            name='HistoricalAbnahme',
            fields=[
                ('id', models.BigIntegerField(auto_created=True, blank=True, db_index=True, verbose_name='ID')),
                ('art', models.CharField(choices=[('gesamt', 'Gesamtabnahme'), ('teil', 'Teilabnahme')], default='gesamt', max_length=10, verbose_name='Art')),
                ('bezeichnung', models.CharField(blank=True, default='', help_text='Bei der Teilabnahme: welche Teilleistung, z. B. "Leistungsphasen 1-4".', max_length=200, verbose_name='Bezeichnung')),
                ('leistungsbeginn', models.DateField(blank=True, null=True, verbose_name='Leistungsbeginn')),
                ('leistungsende', models.DateField(blank=True, null=True, verbose_name='Leistungsende')),
                ('abgenommen_am', models.DateField(blank=True, help_text='Abnahme bzw. Vollendung unserer Leistung, nicht die Abnahme der Bauleistung eines anderen. Leer: noch offen.', null=True, verbose_name='Abgenommen am')),
                ('steuerliches_leistungsdatum', models.DateField(blank=True, help_text='Geht als Leistungsdatum in die Rechnung. Vorbelegt mit dem Abnahmedatum; nur ändern, wenn der Steuerberater es anders sieht.', null=True, verbose_name='Leistungsdatum')),
                ('notiz', models.TextField(blank=True, default='', verbose_name='Notiz')),
                ('erfasst_am', models.DateTimeField(blank=True, editable=False, verbose_name='Erfasst am')),
                ('history_id', models.AutoField(primary_key=True, serialize=False)),
                ('history_date', models.DateTimeField(db_index=True)),
                ('history_change_reason', models.CharField(max_length=100, null=True)),
                ('history_type', models.CharField(choices=[('+', 'Created'), ('~', 'Changed'), ('-', 'Deleted')], max_length=1)),
                ('auftrag', models.ForeignKey(blank=True, db_constraint=False, limit_choices_to={'nachtrag_zu__isnull': True, 'status': 'festgeschrieben', 'typ': 'auftrag'}, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='faktura.beleg', verbose_name='Auftrag')),
                ('history_user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Änderung der Abnahme',
                'verbose_name_plural': 'historical Abnahmen',
                'ordering': ('-history_date', '-history_id'),
                'get_latest_by': ('history_date', 'history_id'),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name='Kontakt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version', models.PositiveIntegerField(db_comment='Optimistic Locking: wird bei jedem Update inkrementiert und beim Speichern im Admin mit der Version beim Laden verglichen.', default=0, editable=False, verbose_name='Version')),
                ('nummer', models.CharField(blank=True, help_text='Leer lassen, wird dann vergeben (K-1000 aufwärts). Eine eigene Nummer aus einem bestehenden System wird übernommen, wenn sie eingetragen wird.', max_length=20, unique=True, verbose_name='Kundennummer')),
                ('name', models.CharField(max_length=200, verbose_name='Name')),
                ('ust_id', models.CharField(blank=True, default='', max_length=20, verbose_name='USt-IdNr.')),
                ('ist_kunde', models.BooleanField(default=True, verbose_name='Kunde')),
                ('ist_lieferant', models.BooleanField(default=False, verbose_name='Lieferant')),
                ('ist_partner', models.BooleanField(default=False, verbose_name='Partner')),
                ('ist_interessent', models.BooleanField(default=False, verbose_name='Interessent')),
                ('eigene_kundennummer', models.CharField(blank=True, default='', help_text='Unter dieser Nummer führt uns der Kontakt, für Rückfragen und Bestellungen.', max_length=50, verbose_name='Eigene Kundennummer')),
                ('zahlungsziel_tage', models.PositiveSmallIntegerField(default=14, verbose_name='Zahlungsziel (Tage)')),
                ('skonto_prozent', models.DecimalField(decimal_places=2, default=Decimal('0.00'), help_text='0 heißt: kein Skonto vereinbart.', max_digits=4, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Skonto (%)')),
                ('skonto_tage', models.PositiveSmallIntegerField(default=0, help_text='Innerhalb wie vieler Tage der Abzug gilt.', verbose_name='Skontofrist (Tage)')),
                ('steuerfall', models.CharField(blank=True, choices=[('', 'Inland (Regelbesteuerung)'), ('inland_13b', '§ 13b UStG: Kunde schuldet die Steuer (Inland)'), ('eu_dienstleistung', 'Dienstleistung an Unternehmen in der EU (Reverse Charge)'), ('eu_lieferung', 'Warenlieferung an Unternehmen in der EU (innergemeinschaftlich)'), ('drittland_dienstleistung', 'Dienstleistung an Unternehmen außerhalb der EU (nicht steuerbar)'), ('ausfuhr', 'Warenlieferung außerhalb der EU (Ausfuhr)')], default='', help_text='Vorbelegung für neue Belege. Bei allem außer dem Regelfall gehen die Positionen mit 0 % hinaus, und der Beleg trägt den gesetzlichen Vermerk.', max_length=30, verbose_name='Steuerfall')),
                ('zustellweg', models.CharField(choices=[('pdf_mail', 'PDF per E-Mail'), ('erechnung', 'E-Rechnung als PDF (ZUGFeRD)'), ('xrechnung', 'XRechnung (XML, z. B. für ein Rechnungsportal)'), ('post', 'Papier per Post')], default='pdf_mail', help_text='Wie dieser Kunde Rechnungen bekommen will. Bei "XRechnung" entsteht das XML seiner Rechnungen im Profil XRechnung; dafür braucht es die Leitweg-ID.', max_length=20, verbose_name='Zustellweg')),
                ('kaeuferreferenz', models.CharField(blank=True, default='', help_text='Vorbelegung für neue Belege (BT-10 der E-Rechnung). Bei öffentlichen Auftraggebern die Leitweg-ID, sonst die Referenz, unter der dieser Kunde die Rechnung zuordnet.', max_length=50, verbose_name='Käuferreferenz')),
                ('aktiv', models.BooleanField(default=True, help_text='Inaktive Kunden stehen in den Auswahllisten nicht mehr zur Wahl. Ihre Belege und Projekte bleiben unberührt.', verbose_name='Aktiv')),
                ('notiz', models.TextField(blank=True, default='', verbose_name='Notiz')),
                ('rechnungsempfaenger', models.ForeignKey(blank=True, help_text='Nur setzen, wenn die Rechnung an einen anderen Kunden geht, etwa Hausverwaltung, Konzernmutter, Versicherung. Für Ansprechpartner ist dieses Feld nicht gedacht.', limit_choices_to={'ist_kunde': True}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='zahlt_fuer', to='faktura.kontakt', verbose_name='Abweichender Rechnungsempfänger')),
            ],
            options={
                'verbose_name': 'Kontakt',
                'verbose_name_plural': 'Kontakte',
                'ordering': ['name'],
            },
        ),
        migrations.AddField(
            model_name='beleg',
            name='kunde',
            field=models.ForeignKey(blank=True, help_text='Verknüpfung zu Projekt/Kunde.', limit_choices_to={'ist_kunde': True}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='belege', to='faktura.kontakt', verbose_name='Kunde'),
        ),
        migrations.AddField(
            model_name='ansprechpartner',
            name='kontakt',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ansprechpartner', to='faktura.kontakt', verbose_name='Kontakt'),
        ),
        migrations.AddField(
            model_name='adresse',
            name='kontakt',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='adressen', to='faktura.kontakt', verbose_name='Kontakt'),
        ),
        migrations.CreateModel(
            name='Kontaktweg',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('art', models.CharField(choices=[('email', 'E-Mail'), ('telefon', 'Telefon'), ('mobil', 'Mobil'), ('fax', 'Fax'), ('web', 'Web'), ('weitere', 'Weitere')], max_length=20, verbose_name='Art')),
                ('wert', models.CharField(help_text='Die Telefonnummer, die E-Mail-Adresse, der Link.', max_length=200, verbose_name='Nummer oder Adresse')),
                ('bezeichnung', models.CharField(blank=True, default='', help_text='"Zentrale", "Buchhaltung", "Durchwahl", und bei der Art "Weitere" der Dienst selbst: "Slack", "LinkedIn".', max_length=100, verbose_name='Wofür')),
                ('ist_standard', models.BooleanField(default=False, help_text='Der Weg, der genommen wird, wenn keiner genannt ist. Höchstens einer je Art.', verbose_name='Standard')),
                ('ansprechpartner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='kontaktwege', to='faktura.ansprechpartner', verbose_name='Ansprechpartner')),
                ('kontakt', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='kontaktwege', to='faktura.kontakt', verbose_name='Kontakt')),
            ],
            options={
                'verbose_name': 'Kontaktweg',
                'verbose_name_plural': 'Kontaktwege',
                'ordering': ['art', '-ist_standard', 'bezeichnung'],
            },
        ),
        migrations.CreateModel(
            name='Projekt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version', models.PositiveIntegerField(db_comment='Optimistic Locking: wird bei jedem Update inkrementiert und beim Speichern im Admin mit der Version beim Laden verglichen.', default=0, editable=False, verbose_name='Version')),
                ('nummer', models.CharField(blank=True, help_text='Vorgeschlagen wird die nächste freie Nummer des Jahres. Frei überschreibbar, muss aber eindeutig sein; z. B. "2026-042" oder "BV-Halle-Nord".', max_length=30, unique=True, verbose_name='Projektnummer')),
                ('bezeichnung', models.CharField(help_text='Kurz und wiedererkennbar; erscheint in jeder Auswahlliste.', max_length=200, verbose_name='Bezeichnung')),
                ('beschreibung', models.TextField(blank=True, default='', help_text='Nur zur internen Erläuterung; steht auf keinem Beleg.', verbose_name='Beschreibung')),
                ('abgeschlossen', models.BooleanField(default=False, help_text='Abgeschlossene Projekte stehen in den Auswahllisten nicht mehr zur Wahl. Ihre Belege bleiben unberührt.', verbose_name='Abgeschlossen')),
                ('notiz', models.TextField(blank=True, default='', verbose_name='Notiz')),
                ('kunde', models.ForeignKey(help_text='Der Auftraggeber. Belege dieses Projekts übernehmen seine Anschrift, solange am Beleg selbst kein anderer Kunde steht.', limit_choices_to={'ist_kunde': True}, on_delete=django.db.models.deletion.PROTECT, related_name='projekte', to='faktura.kontakt', verbose_name='Kunde')),
            ],
            options={
                'verbose_name': 'Projekt',
                'verbose_name_plural': 'Projekte',
                'ordering': ['-nummer'],
            },
        ),
        migrations.AddField(
            model_name='beleg',
            name='projekt',
            field=models.ForeignKey(blank=True, help_text='Verknüpfung zu Projekt/Kunde.', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='belege', to='faktura.projekt', verbose_name='Projekt'),
        ),
        migrations.CreateModel(
            name='Steuersatz',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('satz', models.DecimalField(decimal_places=2, help_text='Nach dem Anlegen nicht mehr änderbar. Positionen speichern den Satz als Wert, nicht als Verweis.', max_digits=4, unique=True, validators=[django.core.validators.MinValueValidator(Decimal('0')), django.core.validators.MaxValueValidator(Decimal('99.99'))], verbose_name='Satz in %')),
                ('bezeichnung', models.CharField(blank=True, help_text='Steht in der Auswahl hinter dem Satz, z. B. „19 % (Regelsteuersatz)“.', max_length=60, verbose_name='Bezeichnung')),
                ('aktiv', models.BooleanField(default=True, help_text='Abgewählt fehlt der Satz in der Auswahl neuer Positionen. Bestehende Positionen behalten ihn.', verbose_name='Wählbar')),
                ('vorgabe', models.BooleanField(default=False, help_text='Vorbelegt an neuen Positionen und Katalogeinträgen. Genau ein Satz ist Vorgabe.', verbose_name='Vorgabe')),
                ('reihenfolge', models.PositiveSmallIntegerField(default=0, help_text='Position in der Auswahl, kleinere Zahl zuerst.', verbose_name='Reihenfolge')),
            ],
            options={
                'verbose_name': 'Steuersatz',
                'verbose_name_plural': 'Steuersätze',
                'ordering': ['reihenfolge', '-satz'],
                'constraints': [models.UniqueConstraint(condition=models.Q(('vorgabe', True)), fields=('vorgabe',), name='steuersatz_eine_vorgabe'), models.CheckConstraint(condition=models.Q(('vorgabe', False), ('aktiv', True), _connector='OR'), name='steuersatz_vorgabe_ist_aktiv'), models.CheckConstraint(condition=models.Q(models.Q(('satz', 0), _negated=True), ('aktiv', True), _connector='OR'), name='steuersatz_null_bleibt_aktiv')],
            },
        ),
        migrations.CreateModel(
            name='Zahlung',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version', models.PositiveIntegerField(db_comment='Optimistic Locking: wird bei jedem Update inkrementiert und beim Speichern im Admin mit der Version beim Laden verglichen.', default=0, editable=False, verbose_name='Version')),
                ('datum', models.DateField(help_text='Wertstellung laut Auszug', verbose_name='Zahlungsdatum')),
                ('betrag', models.DecimalField(db_comment='Der Betrag laut Auszug, die Sollgröße. Die Summe der Zuordnungen darf ihn nicht überschreiten; was fehlt, steht als Rest am Kopf.', decimal_places=2, help_text='Betrag laut Auszug', max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0.01'))], verbose_name='Betrag')),
                ('zahlungsart', models.CharField(choices=[('ueberweisung', 'Überweisung'), ('lastschrift', 'Lastschrift'), ('bar', 'Bar'), ('karte', 'Karte'), ('verrechnung', 'Verrechnung')], default='ueberweisung', max_length=20, verbose_name='Zahlungsart')),
                ('zahlername', models.CharField(blank=True, default='', help_text='Name laut Kontoauszug. Kann abweichen', max_length=200, verbose_name='Name laut Auszug')),
                ('verwendungszweck', models.TextField(blank=True, default='', verbose_name='Verwendungszweck')),
                ('referenz', models.CharField(blank=True, help_text='Eindeutige Kennung aus dem Kontoauszug. Wird beim Import gesetzt und bleibt sonst leer.', max_length=100, null=True, unique=True, verbose_name='Referenz')),
                ('notiz', models.TextField(blank=True, default='', verbose_name='Notiz')),
                ('erfasst_am', models.DateTimeField(auto_now_add=True, verbose_name='Erfasst am')),
                ('kunde', models.ForeignKey(blank=True, help_text='Zuordnung Kunde zu diesem Zahlungseingang (optional)', limit_choices_to={'ist_kunde': True}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='zahlungen', to='faktura.kontakt', verbose_name='Kunde')),
            ],
            options={
                'verbose_name': 'Zahlung',
                'verbose_name_plural': 'Zahlungen',
                'ordering': ['-datum', '-pk'],
            },
        ),
        migrations.CreateModel(
            name='Zahlungszuordnung',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('betrag', models.DecimalField(decimal_places=2, help_text='Was von dieser Zahlung auf diese Rechnung entfällt.', max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Betrag')),
                ('skonto', models.DecimalField(db_comment='Kein Geld: der vereinbarte Abzug. Zusammen mit betrag ergibt er, was die Rechnung ausgleicht.', decimal_places=2, default=Decimal('0.00'), help_text='Was zusätzlich als Abzug gilt und deshalb nicht überwiesen wurde. Mindert die Forderung, nicht die Zahlung.', max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Skonto')),
                ('kuerzung', models.DecimalField(db_comment='Kein Geld und nicht erlassen; verschoben in einen späteren Abschlag oder die Schlussrechnung. Zählt zum Ausgleich, nicht zum Vereinnahmten.', decimal_places=2, default=Decimal('0.00'), help_text='Nur bei Abschlagsrechnungen: was der Kunde noch nicht anerkennt und später gefordert wird. Schließt den offenen Posten, die Schlussrechnung fordert den Betrag erneut.', max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Gekürzt')),
                ('notiz', models.TextField(blank=True, default='', verbose_name='Notiz')),
                ('beleg', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='zahlungszuordnungen', to='faktura.beleg', verbose_name='Rechnung')),
                ('zahlung', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='zuordnungen', to='faktura.zahlung', verbose_name='Zahlung')),
            ],
            options={
                'verbose_name': 'Zahlungszuordnung',
                'verbose_name_plural': 'Zahlungszuordnungen',
                'ordering': ['beleg__nummer', 'pk'],
            },
        ),
        migrations.AddConstraint(
            model_name='belegposition',
            constraint=models.UniqueConstraint(fields=('beleg', 'position'), name='eindeutige_position_je_beleg'),
        ),
        migrations.AddConstraint(
            model_name='abnahme',
            constraint=models.UniqueConstraint(condition=models.Q(('art', 'gesamt')), fields=('auftrag',), name='abnahme_eine_gesamtabnahme_je_auftrag'),
        ),
        migrations.AddConstraint(
            model_name='kontakt',
            constraint=models.CheckConstraint(condition=models.Q(('ist_kunde', True), ('ist_lieferant', True), ('ist_partner', True), ('ist_interessent', True), _connector='OR'), name='kontakt_hat_eine_rolle', violation_error_message='Ein Kontakt braucht mindestens eine Rolle: Kunde, Lieferant, Partner oder Interessent.'),
        ),
        migrations.AddConstraint(
            model_name='ansprechpartner',
            constraint=models.UniqueConstraint(condition=models.Q(('ist_standard', True)), fields=('kontakt',), name='ein_hauptansprechpartner_je_kunde', violation_error_message='Es kann nur einen Hauptansprechpartner je Kunde geben. Bitte bei genau einer Person das Häkchen setzen.'),
        ),
        migrations.AddConstraint(
            model_name='adresse',
            constraint=models.UniqueConstraint(condition=models.Q(('ist_standard', True)), fields=('kontakt',), name='eine_standardadresse_je_kunde', violation_error_message='Es kann nur eine Standardanschrift je Kunde geben. Bitte bei genau einer Anschrift das Häkchen setzen.'),
        ),
        migrations.AddConstraint(
            model_name='kontaktweg',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('ansprechpartner__isnull', True), ('kontakt__isnull', False)), models.Q(('ansprechpartner__isnull', False), ('kontakt__isnull', True)), _connector='OR'), name='kontaktweg_hat_genau_einen_traeger', violation_error_message='Ein Kontaktdatensatz gehört entweder einem Kunden oder einem Ansprechpartner; nicht beiden und nicht keinem.'),
        ),
        migrations.AddConstraint(
            model_name='kontaktweg',
            constraint=models.UniqueConstraint(condition=models.Q(('ist_standard', True)), fields=('kontakt', 'art'), name='ein_standardkontakt_je_kunde_und_art', violation_error_message='Je Art kann nur ein Eintrag der Standard sein. Bitte das Häkchen bei den übrigen Zeilen derselben Art entfernen.'),
        ),
        migrations.AddConstraint(
            model_name='kontaktweg',
            constraint=models.UniqueConstraint(condition=models.Q(('ist_standard', True)), fields=('ansprechpartner', 'art'), name='ein_standardkontakt_je_person_und_art', violation_error_message='Je Art kann nur ein Eintrag der Standard sein. Bitte das Häkchen bei den übrigen Zeilen derselben Art entfernen.'),
        ),
        migrations.AddConstraint(
            model_name='beleg',
            constraint=models.CheckConstraint(condition=models.Q(('status', 'entwurf'), ('nummer__isnull', False), _connector='OR'), name='nummer_ab_der_festschreibung'),
        ),
        migrations.AddConstraint(
            model_name='beleg',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('status', 'entwurf'), _negated=True), ('nummer__isnull', True), ('geaendert_am__isnull', False), _connector='OR'), name='entwurf_mit_nummer_nur_wiedereroeffnet'),
        ),
        migrations.AddConstraint(
            model_name='beleg',
            constraint=models.CheckConstraint(condition=models.Q(('kunde__isnull', True), ('projekt__isnull', True), _connector='OR'), name='kunde_oder_projekt_nicht_beides'),
        ),
        migrations.AddConstraint(
            model_name='zahlungszuordnung',
            constraint=models.UniqueConstraint(fields=('zahlung', 'beleg'), name='eine_zuordnung_je_zahlung_und_beleg', violation_error_message='Diese Rechnung steht bei dieser Zahlung schon einmal. Bitte den vorhandenen Betrag ändern statt eine zweite Zeile anzulegen.'),
        ),
        migrations.AddConstraint(
            model_name='zahlungszuordnung',
            constraint=models.CheckConstraint(condition=models.Q(('betrag__gt', 0), ('skonto__gt', 0), ('kuerzung__gt', 0), _connector='OR'), name='zuordnung_traegt_einen_betrag', violation_error_message='Eine Zuordnung über null Euro sagt nichts. Bitte einen Betrag, einen Skontoabzug oder eine Kürzung eintragen.'),
        ),
        migrations.RunPython(mahnung_bausteine_anlegen, migrations.RunPython.noop),
    ]
