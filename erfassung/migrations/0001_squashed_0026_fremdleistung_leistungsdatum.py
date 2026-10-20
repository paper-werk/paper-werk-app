"""Schema von ``erfassung`` auf dem Stand von 0.1.15, ersetzt 0001 bis 0026.

Datenbanken, die alle ersetzten Migrationen angewendet haben, führen diese
Migration nicht aus (``replaces``). Die Datenmigrationen der ersetzten Reihe
haben nur Bestandsdaten umgestellt und entfallen.
"""

import django.db.models.deletion
import django.utils.timezone
import simple_history.models
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    replaces = [
        ('erfassung', '0001_initial'),
        ('erfassung', '0002_alter_erfassungszeile_bis_and_more'),
        ('erfassung', '0003_alter_erfassungszeile_beschreibung'),
        ('erfassung', '0004_alter_erfassungszeile_menge'),
        ('erfassung', '0005_erfassungszeile_abgerechnet_in_and_more'),
        ('erfassung', '0006_eingangsrechnung_lieferant_fremdleistung_and_more'),
        ('erfassung', '0007_kostensatz'),
        ('erfassung', '0008_zuordnung_auf_die_belegposition'),
        ('erfassung', '0009_erfassung_auf_auftragspositionen'),
        ('erfassung', '0010_beleg_aus_dem_archiv'),
        ('erfassung', '0011_wortlaut_projekt_statt_vorhaben'),
        ('erfassung', '0012_umlaute_in_feldtexten'),
        ('erfassung', '0013_ansichten_entfernen'),
        ('erfassung', '0014_lieferant_kontakt_anlegen'),
        ('erfassung', '0015_lieferant_wird_kontakt'),
        ('erfassung', '0016_lieferant_entfernen'),
        ('erfassung', '0017_fremdleistung_nur_einkauf'),
        ('erfassung', '0018_einkauf_netto_fuellen'),
        ('erfassung', '0019_einkauf_netto_pflicht'),
        ('erfassung', '0020_aenderungsgeschichte'),
        ('erfassung', '0021_aenderungsgeschichte_anfangsstand'),
        ('erfassung', '0022_zeilenarten'),
        ('erfassung', '0023_hilfetexte_gestrichen'),
        ('erfassung', '0024_version'),
        ('erfassung', '0025_recht_katalog_frei_waehlen_entfernt'),
        ('erfassung', '0026_fremdleistung_leistungsdatum'),
    ]

    dependencies = [
        ('faktura', '0001_squashed_0052_steuersatz_tabelle'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Eingangsrechnung',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version', models.PositiveIntegerField(db_comment='Optimistic Locking: wird bei jedem Update inkrementiert und beim Speichern im Admin mit der Version beim Laden verglichen.', default=0, editable=False, verbose_name='Version')),
                ('nummer', models.CharField(help_text='Die Nummer des Lieferanten, so wie sie auf seinem Beleg steht.', max_length=50, verbose_name='Rechnungsnummer')),
                ('datum', models.DateField(verbose_name='Rechnungsdatum')),
                ('betrag_netto', models.DecimalField(db_comment='Der Betrag laut fremdem Beleg, die Sollgröße. Die Summe der Positionen muss ihn treffen; die Differenz steht als Rest am Kopf.', decimal_places=2, help_text='Was der Lieferant fordert. Gegen diesen Betrag prüft das Programm, ob alle Positionen zugeordnet sind.', max_digits=12, verbose_name='Rechnungsbetrag netto')),
                ('notiz', models.TextField(blank=True, default='', verbose_name='Notiz')),
                ('paperless_id', models.PositiveIntegerField(blank=True, help_text='Die Nummer des Dokuments in Paperless. Wird beim Übertrag aus dem Archiv gesetzt und bleibt sonst leer.', null=True, unique=True, verbose_name='Dokument im Archiv')),
                ('erfasst_am', models.DateTimeField(auto_now_add=True, verbose_name='Erfasst am')),
                ('lieferant', models.ForeignKey(limit_choices_to={'ist_lieferant': True}, on_delete=django.db.models.deletion.PROTECT, related_name='eingangsrechnungen', to='faktura.kontakt', verbose_name='Lieferant')),
            ],
            options={
                'verbose_name': 'Eingangsrechnung',
                'verbose_name_plural': 'Eingangsrechnungen',
                'ordering': ['-datum', '-pk'],
            },
        ),
        migrations.CreateModel(
            name='Erfassungszeile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('datum', models.DateField(default=django.utils.timezone.localdate, verbose_name='Datum')),
                ('von', models.TimeField(blank=True, db_comment='Wanduhrzeit, kein Zeitpunkt, deshalb time und nicht timestamp. Am Tag der Zeitumstellung sind 8:00 bis 12:00 vier Stunden, und bezahlt werden vier. Freiwillig: fehlt von oder bis, ist die Dauer 0.', null=True, verbose_name='Von')),
                ('bis', models.TimeField(blank=True, db_comment='Siehe von. Muss am selben Tag liegen; eine Schicht über Mitternacht wird auf zwei Zeilen aufgeteilt.', null=True, verbose_name='Bis')),
                ('dauer_minuten', models.PositiveIntegerField(db_comment='BERECHNET aus von/bis, nie eingegeben. Ganze Minuten, weil eine Drittelstunde als Dezimalzahl nur gerundet zu haben ist (0,333 h weichen je Zeile um 1,2 Sekunden ab). Gilt nur bei Leistungen der Art "zeit"; bei Mengen- und Pauschalleistungen steht hier 0.', default=0, editable=False, verbose_name='Dauer in Minuten')),
                ('menge', models.DecimalField(blank=True, db_comment='EINGEGEBEN, freiwillig. NULL heißt "keine Menge"; bei Zeitleistungen gibt es keine, bei Mengenleistungen ohne Angabe fehlt sie noch. Zusammen mit dauer_minuten die zweite Mengenspalte: die eine wird getippt, die andere gerechnet. In einer Spalte vereint wäre die Dauer wieder eingebbar, neben von/bis, und die beiden liefen auseinander.', decimal_places=3, max_digits=10, null=True, verbose_name='Menge')),
                ('beschreibung', models.CharField(blank=True, db_comment='Freiwillig. Bei Mengenleistungen wie einer Anfahrt sagt die Leistung selbst schon, was geschehen ist.', default='', max_length=300, verbose_name='Beschreibung')),
                ('abrechenbar', models.BooleanField(db_comment='Kaufmännische Entscheidung, keine Erfassungsangabe, deshalb im Formular nur für die Leitung sichtbar. Vorgabe true: Der Normalfall ist abrechenbar, und die Ausnahme soll die Ausnahme bleiben.', default=True, verbose_name='Abrechenbar')),
                ('abgerechnet_in', models.ForeignKey(blank=True, db_comment='Die Rechnungsposition, auf der diese Zeile steht. SET_NULL: Wird die Position entfernt oder der Entwurf verworfen, ist die Zeile wieder abrechenbar. Der Beleg ergibt sich über abgerechnet_in.beleg.', help_text='Wird beim Übernehmen in eine Rechnung gesetzt. Kein Eingabefeld.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='erfassung', to='faktura.belegposition', verbose_name='Abgerechnet in')),
                ('auftragsposition', models.ForeignKey(blank=True, db_comment='Der Regelfall. Preis und Einheit kommen von hier, also aus dem Vertrag und nicht aus dem Katalog.', limit_choices_to={'beleg__status': 'festgeschrieben', 'beleg__typ': 'auftrag', 'zeilenart': 'leistung'}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='kontierungen', to='faktura.belegposition', verbose_name='Auftragsposition')),
                ('benutzer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='erfassung', to=settings.AUTH_USER_MODEL, verbose_name='Person')),
                ('leistung', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='erfassung', to='faktura.katalogposition', verbose_name='Leistung aus dem Katalog')),
                ('projekt', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='erfassung', to='faktura.projekt', verbose_name='Projekt')),
            ],
            options={
                'verbose_name': 'Erfassungszeile',
                'verbose_name_plural': 'Erfassung',
                'ordering': ['-datum', '-pk'],
                'permissions': [('fuer_andere_erfassen', 'Kann für andere Personen erfassen')],
            },
        ),
        migrations.CreateModel(
            name='Fremdleistung',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('bezeichnung', models.CharField(help_text='Wie es auf der Rechnung des Lieferanten heißt; Paketnummer, Analysenbezeichnung, Leistung.', max_length=300, verbose_name='Bezeichnung')),
                ('einheit', models.CharField(blank=True, default='Stk', max_length=20, verbose_name='Einheit')),
                ('menge', models.DecimalField(db_comment='Dieselben drei Nachkommastellen wie Belegposition.menge; die Position wird eines Tages zu einer.', decimal_places=3, default=Decimal('1'), max_digits=10, verbose_name='Menge')),
                ('leistungsdatum', models.DateField(blank=True, db_comment='Geht als leistung_von/leistung_bis (BT-134/135) in die Belegposition: kleinstes bis größtes Datum der Gruppe.', help_text='Wann der Lieferant geleistet hat, z. B. die Probenahme. Ergibt beim Übernehmen den Leistungszeitraum der Rechnungsposition.', null=True, verbose_name='Leistungsdatum')),
                ('einkaufspreis', models.DecimalField(db_comment='Einzelpreis laut Lieferant. Maßgeblich für die Kosten ist einkauf_netto, nicht Menge mal Preis.', decimal_places=4, help_text='Je Einheit, so wie der Lieferant ihn berechnet.', max_digits=14, verbose_name='Einkaufspreis netto')),
                ('einkauf_netto', models.DecimalField(blank=True, db_comment='Der Zeilenbetrag laut Lieferant (E-Rechnung: BT-131). Belastet das Projektergebnis, auch wenn nichts weiterberechnet wird. Die Summe über die Eingangsrechnung muss deren Nettobetrag treffen.', decimal_places=2, help_text='Was der Lieferant für diese Zeile berechnet. Leer lassen - dann Menge mal Einkaufspreis. Abweichend eintragen bei Rabatt oder Zuschlag auf der Zeile.', max_digits=12, verbose_name='Betrag netto')),
                ('weiterberechenbar', models.BooleanField(default=True, help_text='Ausschalten, wenn wir die Kosten selbst tragen. Sie bleiben im Projektergebnis stehen.', verbose_name='Weiterberechenbar')),
                ('abgerechnet_in', models.ForeignKey(blank=True, help_text='Wird beim Übernehmen in eine Rechnung gesetzt. Kein Eingabefeld.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='fremdleistungen', to='faktura.belegposition', verbose_name='Abgerechnet in')),
                ('auftragsposition', models.ForeignKey(blank=True, help_text='Freiwillig: die beauftragte Leistung, zu der dieser Einkauf gehört. Beim Übernehmen in die Rechnung gilt dann ihr Preis, wenn die Einheit passt.', limit_choices_to={'beleg__status': 'festgeschrieben', 'beleg__typ': 'auftrag', 'zeilenart': 'leistung'}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='fremdkontierungen', to='faktura.belegposition', verbose_name='Auftragsposition')),
                ('projekt', models.ForeignKey(help_text='Für welches Projekt diese Position angefallen ist.', on_delete=django.db.models.deletion.PROTECT, related_name='fremdleistungen', to='faktura.projekt', verbose_name='Projekt')),
                ('rechnung', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='positionen', to='erfassung.eingangsrechnung', verbose_name='Eingangsrechnung')),
            ],
            options={
                'verbose_name': 'Fremdleistung',
                'verbose_name_plural': 'Fremdleistungen',
                'ordering': ['rechnung', 'pk'],
            },
        ),
        migrations.CreateModel(
            name='HistoricalErfassungszeile',
            fields=[
                ('id', models.BigIntegerField(auto_created=True, blank=True, db_index=True, verbose_name='ID')),
                ('datum', models.DateField(default=django.utils.timezone.localdate, verbose_name='Datum')),
                ('von', models.TimeField(blank=True, db_comment='Wanduhrzeit, kein Zeitpunkt, deshalb time und nicht timestamp. Am Tag der Zeitumstellung sind 8:00 bis 12:00 vier Stunden, und bezahlt werden vier. Freiwillig: fehlt von oder bis, ist die Dauer 0.', null=True, verbose_name='Von')),
                ('bis', models.TimeField(blank=True, db_comment='Siehe von. Muss am selben Tag liegen; eine Schicht über Mitternacht wird auf zwei Zeilen aufgeteilt.', null=True, verbose_name='Bis')),
                ('dauer_minuten', models.PositiveIntegerField(db_comment='BERECHNET aus von/bis, nie eingegeben. Ganze Minuten, weil eine Drittelstunde als Dezimalzahl nur gerundet zu haben ist (0,333 h weichen je Zeile um 1,2 Sekunden ab). Gilt nur bei Leistungen der Art "zeit"; bei Mengen- und Pauschalleistungen steht hier 0.', default=0, editable=False, verbose_name='Dauer in Minuten')),
                ('menge', models.DecimalField(blank=True, db_comment='EINGEGEBEN, freiwillig. NULL heißt "keine Menge"; bei Zeitleistungen gibt es keine, bei Mengenleistungen ohne Angabe fehlt sie noch. Zusammen mit dauer_minuten die zweite Mengenspalte: die eine wird getippt, die andere gerechnet. In einer Spalte vereint wäre die Dauer wieder eingebbar, neben von/bis, und die beiden liefen auseinander.', decimal_places=3, max_digits=10, null=True, verbose_name='Menge')),
                ('beschreibung', models.CharField(blank=True, db_comment='Freiwillig. Bei Mengenleistungen wie einer Anfahrt sagt die Leistung selbst schon, was geschehen ist.', default='', max_length=300, verbose_name='Beschreibung')),
                ('abrechenbar', models.BooleanField(db_comment='Kaufmännische Entscheidung, keine Erfassungsangabe, deshalb im Formular nur für die Leitung sichtbar. Vorgabe true: Der Normalfall ist abrechenbar, und die Ausnahme soll die Ausnahme bleiben.', default=True, verbose_name='Abrechenbar')),
                ('history_id', models.AutoField(primary_key=True, serialize=False)),
                ('history_date', models.DateTimeField(db_index=True)),
                ('history_change_reason', models.CharField(max_length=100, null=True)),
                ('history_type', models.CharField(choices=[('+', 'Created'), ('~', 'Changed'), ('-', 'Deleted')], max_length=1)),
                ('abgerechnet_in', models.ForeignKey(blank=True, db_comment='Die Rechnungsposition, auf der diese Zeile steht. SET_NULL: Wird die Position entfernt oder der Entwurf verworfen, ist die Zeile wieder abrechenbar. Der Beleg ergibt sich über abgerechnet_in.beleg.', db_constraint=False, help_text='Wird beim Übernehmen in eine Rechnung gesetzt. Kein Eingabefeld.', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='faktura.belegposition', verbose_name='Abgerechnet in')),
                ('auftragsposition', models.ForeignKey(blank=True, db_comment='Der Regelfall. Preis und Einheit kommen von hier, also aus dem Vertrag und nicht aus dem Katalog.', db_constraint=False, limit_choices_to={'beleg__status': 'festgeschrieben', 'beleg__typ': 'auftrag', 'zeilenart': 'leistung'}, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='faktura.belegposition', verbose_name='Auftragsposition')),
                ('benutzer', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Person')),
                ('history_user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('leistung', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='faktura.katalogposition', verbose_name='Leistung aus dem Katalog')),
                ('projekt', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='faktura.projekt', verbose_name='Projekt')),
            ],
            options={
                'verbose_name': 'Änderung der Erfassungszeile',
                'verbose_name_plural': 'historical Erfassung',
                'ordering': ('-history_date', '-history_id'),
                'get_latest_by': ('history_date', 'history_id'),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name='HistoricalFremdleistung',
            fields=[
                ('id', models.BigIntegerField(auto_created=True, blank=True, db_index=True, verbose_name='ID')),
                ('bezeichnung', models.CharField(help_text='Wie es auf der Rechnung des Lieferanten heißt; Paketnummer, Analysenbezeichnung, Leistung.', max_length=300, verbose_name='Bezeichnung')),
                ('einheit', models.CharField(blank=True, default='Stk', max_length=20, verbose_name='Einheit')),
                ('menge', models.DecimalField(db_comment='Dieselben drei Nachkommastellen wie Belegposition.menge; die Position wird eines Tages zu einer.', decimal_places=3, default=Decimal('1'), max_digits=10, verbose_name='Menge')),
                ('leistungsdatum', models.DateField(blank=True, db_comment='Geht als leistung_von/leistung_bis (BT-134/135) in die Belegposition: kleinstes bis größtes Datum der Gruppe.', help_text='Wann der Lieferant geleistet hat, z. B. die Probenahme. Ergibt beim Übernehmen den Leistungszeitraum der Rechnungsposition.', null=True, verbose_name='Leistungsdatum')),
                ('einkaufspreis', models.DecimalField(db_comment='Einzelpreis laut Lieferant. Maßgeblich für die Kosten ist einkauf_netto, nicht Menge mal Preis.', decimal_places=4, help_text='Je Einheit, so wie der Lieferant ihn berechnet.', max_digits=14, verbose_name='Einkaufspreis netto')),
                ('einkauf_netto', models.DecimalField(blank=True, db_comment='Der Zeilenbetrag laut Lieferant (E-Rechnung: BT-131). Belastet das Projektergebnis, auch wenn nichts weiterberechnet wird. Die Summe über die Eingangsrechnung muss deren Nettobetrag treffen.', decimal_places=2, help_text='Was der Lieferant für diese Zeile berechnet. Leer lassen - dann Menge mal Einkaufspreis. Abweichend eintragen bei Rabatt oder Zuschlag auf der Zeile.', max_digits=12, verbose_name='Betrag netto')),
                ('weiterberechenbar', models.BooleanField(default=True, help_text='Ausschalten, wenn wir die Kosten selbst tragen. Sie bleiben im Projektergebnis stehen.', verbose_name='Weiterberechenbar')),
                ('history_id', models.AutoField(primary_key=True, serialize=False)),
                ('history_date', models.DateTimeField(db_index=True)),
                ('history_change_reason', models.CharField(max_length=100, null=True)),
                ('history_type', models.CharField(choices=[('+', 'Created'), ('~', 'Changed'), ('-', 'Deleted')], max_length=1)),
                ('abgerechnet_in', models.ForeignKey(blank=True, db_constraint=False, help_text='Wird beim Übernehmen in eine Rechnung gesetzt. Kein Eingabefeld.', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='faktura.belegposition', verbose_name='Abgerechnet in')),
                ('auftragsposition', models.ForeignKey(blank=True, db_constraint=False, help_text='Freiwillig: die beauftragte Leistung, zu der dieser Einkauf gehört. Beim Übernehmen in die Rechnung gilt dann ihr Preis, wenn die Einheit passt.', limit_choices_to={'beleg__status': 'festgeschrieben', 'beleg__typ': 'auftrag', 'zeilenart': 'leistung'}, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='faktura.belegposition', verbose_name='Auftragsposition')),
                ('history_user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('projekt', models.ForeignKey(blank=True, db_constraint=False, help_text='Für welches Projekt diese Position angefallen ist.', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='faktura.projekt', verbose_name='Projekt')),
                ('rechnung', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='erfassung.eingangsrechnung', verbose_name='Eingangsrechnung')),
            ],
            options={
                'verbose_name': 'Änderung der Fremdleistung',
                'verbose_name_plural': 'historical Fremdleistungen',
                'ordering': ('-history_date', '-history_id'),
                'get_latest_by': ('history_date', 'history_id'),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name='Kostensatz',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('gueltig_ab', models.DateField(help_text='Ab diesem Tag gilt der Satz, bis zum nächsten dieser Person. Frühere Stunden bleiben mit dem alten Satz gerechnet.', verbose_name='Gültig ab')),
                ('satz', models.DecimalField(db_comment='INTERNER Satz je Stunde. Nicht mit Katalogposition.einzelpreis verwechseln; das ist der Verkaufspreis.', decimal_places=2, help_text='Netto, in Euro. Lohn samt Nebenkosten und Umlage, was die Stunde den Betrieb kostet, nicht was der Kunde zahlt.', max_digits=8, verbose_name='Kostensatz je Stunde')),
                ('notiz', models.TextField(blank=True, default='', verbose_name='Notiz')),
                ('benutzer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='kostensaetze', to=settings.AUTH_USER_MODEL, verbose_name='Person')),
            ],
            options={
                'verbose_name': 'Kostensatz',
                'verbose_name_plural': 'Kostensätze',
                'ordering': ['benutzer', '-gueltig_ab'],
            },
        ),
        migrations.AddConstraint(
            model_name='eingangsrechnung',
            constraint=models.UniqueConstraint(fields=('lieferant', 'nummer'), name='eingangsrechnung_je_lieferant_eindeutig'),
        ),
        migrations.AddConstraint(
            model_name='erfassungszeile',
            constraint=models.CheckConstraint(condition=models.Q(('dauer_minuten__lte', 1440)), name='erfassungszeile_hoechstens_ein_tag'),
        ),
        migrations.AddConstraint(
            model_name='kostensatz',
            constraint=models.UniqueConstraint(fields=('benutzer', 'gueltig_ab'), name='kostensatz_je_person_und_tag_eindeutig'),
        ),
    ]
