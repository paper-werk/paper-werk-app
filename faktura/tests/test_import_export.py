"""Import und Export des Leistungskatalogs als Tabelle.

Für vorhandene Kataloge (Excel, Altsystem). Geprüft wird eine Datei aus
einer **deutschen** Tabellenkalkulation: Dezimalkomma, "19 %" als
Steuersatz, leere Artikelnummern.
"""

import io
from decimal import Decimal

import pytest
import tablib
from django.urls import reverse

from faktura.models import (
    Katalogposition,
    Kontakt,
    Leistungsart,
    Projekt,
)
from faktura.ressourcen import (
    KatalogpositionResource,
    KontaktResource,
    ProjektResource,
)

pytestmark = pytest.mark.django_db

SPALTEN = ['nummer', 'bezeichnung', 'langtext', 'einheit', 'einzelpreis',
           'steuersatz', 'art', 'kontierbar']


def _tabelle(*zeilen) -> tablib.Dataset:
    daten = tablib.Dataset(headers=SPALTEN)
    for zeile in zeilen:
        daten.append(zeile)
    return daten


class TestWasAusEinerDateiHereinkommt:

    def test_eine_zeile_wird_zur_katalogposition(self):
        daten = _tabelle(['2.10', 'Probenahme vor Ort', 'Nach DIN ISO 10381-1',
                          'Std', '85,00', '19 %', 'Zeit', 'ja'])

        ergebnis = KatalogpositionResource().import_data(daten, dry_run=False)

        assert not ergebnis.has_errors()
        position = Katalogposition.objects.get()
        assert position.nummer == '2.10'
        assert position.einzelpreis == Decimal('85.00')
        assert position.steuersatz == '19.00'
        assert position.art == Leistungsart.ZEIT
        assert position.kontierbar is True

    def test_das_dezimalkomma_kommt_aus_excel(self):
        """Das Dezimalkomma wird geparst; ohne eigenes Widget schlüge jede
        Zeile mit "ungültige Dezimalzahl" fehl."""
        daten = _tabelle(['1', 'Mit Komma', '', 'Std', '1.250,50', '19', 'zeit', 'ja'])

        ergebnis = KatalogpositionResource().import_data(daten, dry_run=False)

        assert not ergebnis.has_errors()
        assert Katalogposition.objects.get().einzelpreis == Decimal('1250.50')

    def test_ein_punkt_geht_genauso(self):
        daten = _tabelle(['1', 'Mit Punkt', '', 'Std', '85.00', '19', 'zeit', 'ja'])

        KatalogpositionResource().import_data(daten, dry_run=False)

        assert Katalogposition.objects.get().einzelpreis == Decimal('85.00')

    @pytest.mark.parametrize('geschrieben, erwartet', [
        ('19 %', '19.00'),
        ('19', '19.00'),
        ('voll', '19.00'),
        ('7 %', '7.00'),
        ('ermäßigt', '7.00'),
        ('0', '0.00'),
        # Die gesenkten Sätze aus dem zweiten Halbjahr 2020, wie sie in
        # Katalogen aus dieser Zeit vorkommen.
        ('16 %', '16.00'),
        ('16,00', '16.00'),
        ('5 %', '5.00'),
        ('5.00', '5.00'),
    ])
    def test_der_steuersatz_darf_ausgeschrieben_dastehen(self, geschrieben,
                                                         erwartet):
        """Der Steuersatz darf als "19 %" angegeben sein."""
        daten = _tabelle(['1', 'Etwas', '', 'Std', '10,00', geschrieben,
                          'menge', 'ja'])

        KatalogpositionResource().import_data(daten, dry_run=False)

        assert Katalogposition.objects.get().steuersatz == erwartet

    @pytest.mark.parametrize('geschrieben, erwartet', [
        ('Stunde', Leistungsart.ZEIT),
        ('zeit', Leistungsart.ZEIT),
        ('Stück', Leistungsart.MENGE),
        ('Pauschale', Leistungsart.PAUSCHALE),
    ])
    def test_und_die_art_auch(self, geschrieben, erwartet):
        daten = _tabelle(['1', 'Etwas', '', 'Std', '10,00', '19', geschrieben,
                          'ja'])

        KatalogpositionResource().import_data(daten, dry_run=False)

        assert Katalogposition.objects.get().art == erwartet

    def test_ja_und_nein_statt_true_und_false(self):
        daten = _tabelle(
            ['1', 'Im Feld', '', 'Std', '10,00', '19', 'zeit', 'ja'],
            ['2', 'Nur im Angebot', '', 'pausch', '99,00', '19', 'pauschal',
             'nein'],
        )

        KatalogpositionResource().import_data(daten, dry_run=False)

        assert Katalogposition.objects.get(nummer='1').kontierbar is True
        assert Katalogposition.objects.get(nummer='2').kontierbar is False

    def test_mehrere_zeilen_ohne_nummer_gehen_nebeneinander(self):
        """Mehrere Zeilen ohne Nummer: Eine leere Zelle liefert einen
        Leerstring, das Feld ist unique; zwei Leerstrings kollidieren, zwei
        NULL nicht."""
        daten = _tabelle(
            ['', 'Ohne Nummer', '', 'Std', '10,00', '19', 'zeit', 'ja'],
            ['', 'Auch ohne', '', 'Std', '20,00', '19', 'zeit', 'ja'],
        )

        ergebnis = KatalogpositionResource().import_data(daten, dry_run=False)

        assert not ergebnis.has_errors()
        assert Katalogposition.objects.count() == 2
        assert Katalogposition.objects.filter(nummer__isnull=True).count() == 2


class TestDerZweiteLauf:
    """Ein zweiter Import erkennt vorhandene Zeilen und verdoppelt den
    Katalog nicht."""

    def test_dieselbe_datei_zweimal_verdoppelt_nichts(self):
        daten = _tabelle(['2.10', 'Probenahme', '', 'Std', '85,00', '19',
                          'zeit', 'ja'])

        KatalogpositionResource().import_data(daten, dry_run=False)
        KatalogpositionResource().import_data(_tabelle(*daten), dry_run=False)

        assert Katalogposition.objects.count() == 1

    def test_ein_neuer_preis_wird_uebernommen(self):
        """Preisänderung: Export, Änderung in der Tabelle, Import."""
        KatalogpositionResource().import_data(
            _tabelle(['2.10', 'Probenahme', '', 'Std', '85,00', '19', 'zeit',
                      'ja']), dry_run=False)

        ergebnis = KatalogpositionResource().import_data(
            _tabelle(['2.10', 'Probenahme', '', 'Std', '92,50', '19', 'zeit',
                      'ja']), dry_run=False)

        assert Katalogposition.objects.get().einzelpreis == Decimal('92.50')
        assert ergebnis.totals['update'] == 1

    def test_unveraenderte_zeilen_werden_gezaehlt_nicht_geschrieben(self):
        """Unveränderte Zeilen werden gezählt und nicht geschrieben."""
        zeile = ['2.10', 'Probenahme', '', 'Std', '85,00', '19', 'zeit', 'ja']
        KatalogpositionResource().import_data(_tabelle(zeile), dry_run=False)

        ergebnis = KatalogpositionResource().import_data(
            _tabelle(zeile), dry_run=False)

        assert ergebnis.totals['skip'] == 1
        assert ergebnis.totals['update'] == 0

    def test_ohne_nummer_erkennt_die_bezeichnung_wieder(self):
        zeile = ['', 'Ohne Nummer', '', 'Std', '10,00', '19', 'zeit', 'ja']
        KatalogpositionResource().import_data(_tabelle(zeile), dry_run=False)

        KatalogpositionResource().import_data(_tabelle(zeile), dry_run=False)

        assert Katalogposition.objects.count() == 1


class TestWasHinausgeht:

    def test_der_export_traegt_die_spalten_des_katalogs(self, db):
        Katalogposition.objects.create(
            nummer='2.10', bezeichnung='Probenahme vor Ort',
            langtext='Nach DIN ISO 10381-1', einheit='Std',
            einzelpreis=Decimal('85.00'), art=Leistungsart.ZEIT)

        daten = KatalogpositionResource().export()

        assert daten.headers == SPALTEN
        assert daten[0][0] == '2.10'
        assert 'DIN ISO 10381-1' in daten[0][2]

    def test_und_er_laesst_sich_wieder_einlesen(self, db):
        """Ein Export lässt sich nach Änderung wieder importieren."""
        Katalogposition.objects.create(
            nummer='2.10', bezeichnung='Probenahme', einheit='Std',
            einzelpreis=Decimal('85.00'), art=Leistungsart.ZEIT)
        hinaus = KatalogpositionResource().export()
        Katalogposition.objects.all().delete()

        ergebnis = KatalogpositionResource().import_data(hinaus, dry_run=False)

        assert not ergebnis.has_errors()
        wieder = Katalogposition.objects.get()
        assert wieder.nummer == '2.10'
        assert wieder.einzelpreis == Decimal('85.00')


class TestDieMaskeImAdmin:

    def test_die_drei_seiten_laufen(self, admin_client):
        for name in ['changelist', 'import', 'export']:
            adresse = reverse(f'admin:faktura_katalogposition_{name}')

            assert admin_client.get(adresse).status_code == 200

    def test_eine_hochgeladene_datei_wird_erst_gezeigt_nicht_geschrieben(
            self, admin_client):
        """Der Upload zeigt zuerst die Vorschau (Dry Run); geschrieben wird
        erst nach Bestätigung."""
        datei = io.BytesIO(
            b'nummer,bezeichnung,langtext,einheit,einzelpreis,steuersatz,'
            b'art,kontierbar\n'
            b'2.10,Probenahme,,Std,"85,00",19,zeit,ja\n')
        datei.name = 'katalog.csv'

        antwort = admin_client.post(
            reverse('admin:faktura_katalogposition_import'),
            {'import_file': datei, 'input_format': '1', 'format': '1'},
            follow=True)

        assert antwort.status_code == 200
        assert Katalogposition.objects.count() == 0


# ══════════════════════════════════════════════════════════════════════════
# Kunden und Projekte
# ══════════════════════════════════════════════════════════════════════════

#: Flache Tabelle des Kundenstamms, obwohl ein Kunde aus vier Tabellen
#: besteht, weil Adresslisten aus Excel eine Zeile je Kunde haben
#: (Begründung an ``KundeResource``).
KUNDENSPALTEN = ['nummer', 'name', 'strasse', 'plz', 'ort', 'land',
                 'email', 'telefon', 'ust_id', 'zahlungsziel_tage',
                 'kaeuferreferenz']
PROJEKTSPALTEN = ['nummer', 'bezeichnung', 'kunde', 'beschreibung',
                  'abgeschlossen', 'notiz']


def _kundentabelle(*zeilen) -> tablib.Dataset:
    daten = tablib.Dataset(headers=KUNDENSPALTEN)
    for zeile in zeilen:
        daten.append(zeile)
    return daten


def _projekttabelle(*zeilen) -> tablib.Dataset:
    daten = tablib.Dataset(headers=PROJEKTSPALTEN)
    for zeile in zeilen:
        daten.append(zeile)
    return daten


class TestDerKundenstamm:

    def test_der_export_traegt_nur_den_datensatz(self, db):
        """Der Export enthält nur den Datensatz, ohne IDs, Belege und
        Projekte."""
        Kontakt.anlegen(nummer='K-1000', name='Stadt Musterstadt',
                             strasse='Rathausplatz 1', plz='84032',
                             ort='Musterstadt')

        daten = KontaktResource().export()

        assert daten.headers == KUNDENSPALTEN
        assert 'id' not in daten.headers
        assert 'belege' not in daten.headers

    def test_eine_adressliste_ohne_nummern_bekommt_welche(self, db):
        """Zeilen ohne Nummer erhalten beim Speichern eine (ab K-1000), weil
        die Vergabe in save() liegt."""
        daten = _kundentabelle(
            ['', 'Erster Kunde', 'Weg 1', '12345', 'Ort', '', '', '', '', '14', ''],
            ['', 'Zweiter Kunde', 'Weg 2', '12345', 'Ort', '', '', '', '', '14', ''],
        )

        ergebnis = KontaktResource().import_data(daten, dry_run=False)

        assert not ergebnis.has_errors()
        assert Kontakt.objects.count() == 2
        assert all(k.nummer.startswith('K-') for k in Kontakt.objects.all())

    def test_ein_leeres_land_ist_deutschland(self, db):
        """Leeres Land wird 'DE', weil BT-55 Pflicht ist und Adresslisten das
        Land oft nicht enthalten."""
        daten = _kundentabelle(
            ['K-1', 'Kunde', 'Weg 1', '12345', 'Ort', '', '', '', '', '14', ''])

        KontaktResource().import_data(daten, dry_run=False)

        assert Kontakt.objects.get().land == 'DE'

    def test_der_zweite_lauf_erkennt_an_der_nummer_wieder(self, db):
        zeile = ['K-1000', 'Stadt Musterstadt', 'Rathausplatz 1', '84032',
                 'Musterstadt', 'DE', '', '', '', '30', '']
        KontaktResource().import_data(_kundentabelle(zeile), dry_run=False)

        KontaktResource().import_data(_kundentabelle(zeile), dry_run=False)

        assert Kontakt.objects.count() == 1


class TestDieVorhaben:
    """Import laufender Projekte aus einem Altsystem (Nummer, Bezeichnung,
    Auftraggeber)."""

    @pytest.fixture
    def kunde(self, db):
        return Kontakt.objects.create(nummer='K-2001',
                                    name='Stadt Musterstadt')

    def test_der_kunde_steht_als_nummer_da_nicht_als_kennung(self, kunde):
        """Der Kunde erscheint als Kundennummer ("K-2001"), nicht als ID
        ("42")."""
        Projekt.objects.create(nummer='2026-042', bezeichnung='Turnhalle',
                               kunde=kunde)

        daten = ProjektResource().export()

        assert daten.headers == PROJEKTSPALTEN
        assert daten[0][2] == 'K-2001'
        assert str(kunde.pk) not in daten[0]

    def test_der_import_findet_den_kunden_ueber_seine_nummer(self, kunde):
        daten = _projekttabelle(
            ['2026-042', 'Schadstofferkundung Turnhalle', 'K-2001',
             'Erkundung vor Abbruch', 'nein', ''])

        ergebnis = ProjektResource().import_data(daten, dry_run=False)

        assert not ergebnis.has_errors()
        projekt = Projekt.objects.get()
        assert projekt.kunde == kunde
        assert projekt.abgeschlossen is False

    def test_ja_und_nein_beim_abschluss(self, kunde):
        daten = _projekttabelle(
            ['2026-001', 'Altes Vorhaben', 'K-2001', '', 'ja', ''],
            ['2026-002', 'Laufendes', 'K-2001', '', 'nein', ''],
        )

        ProjektResource().import_data(daten, dry_run=False)

        assert Projekt.objects.get(nummer='2026-001').abgeschlossen is True
        assert Projekt.objects.get(nummer='2026-002').abgeschlossen is False

    def test_eine_unbekannte_kundennummer_wird_beim_namen_genannt(self, kunde):
        """Die Fehlermeldung enthält die unbekannte Kundennummer; Django
        meldete nur "Kunde matching query does not exist"."""
        daten = _projekttabelle(
            ['2026-042', 'Turnhalle', 'K-9999', '', 'nein', ''])

        ergebnis = ProjektResource().import_data(daten, dry_run=True)

        # Validierungsfehler am Feld, keine Exception: django-import-export
        # bricht bei Exceptions ab, Feldfehler erscheinen in der Vorschau an
        # ihrer Zeile.
        assert ergebnis.has_validation_errors()
        assert not ergebnis.has_errors()
        meldungen = ' '.join(
            str(text)
            for zeile in ergebnis.invalid_rows
            for texte in zeile.error_dict.values()
            for text in texte
        )
        assert 'K-9999' in meldungen
        assert 'Erst die Kunden einlesen' in meldungen
        assert Projekt.objects.count() == 0

    def test_belege_und_stunden_bleiben_draussen(self, kunde):
        """Belege und Stunden sind nicht importierbar, weil sie an
        Nummernkreisen und Festschreibung hängen."""
        daten = ProjektResource().export()

        for verboten in ('belege', 'erfassung', 'fremdleistungen', 'id'):
            assert verboten not in daten.headers

    def test_der_kreis_geht_auf(self, kunde):
        """Export, Löschen, Import ergibt denselben Bestand."""
        Projekt.objects.create(nummer='2026-042', bezeichnung='Turnhalle',
                               kunde=kunde, beschreibung='Vor Abbruch')
        hinaus = ProjektResource().export()
        Projekt.objects.all().delete()

        ergebnis = ProjektResource().import_data(hinaus, dry_run=False)

        assert not ergebnis.has_errors()
        wieder = Projekt.objects.get()
        assert wieder.kunde == kunde
        assert wieder.beschreibung == 'Vor Abbruch'


class TestDieMaskenDerStammdaten:

    @pytest.mark.parametrize('modell', ['kontakt', 'projekt',
                                        'katalogposition'])
    @pytest.mark.parametrize('seite', ['import', 'export'])
    def test_sie_laufen(self, admin_client, modell, seite):
        adresse = reverse(f'admin:faktura_{modell}_{seite}')

        assert admin_client.get(adresse).status_code == 200

    @pytest.mark.parametrize('modell', ['rechnung', 'angebot',
                                        'auftrag'])
    def test_belege_haben_keine(self, admin_client, modell):
        """Belege haben keine Resource, weil sie lückenlose Nummern haben und
        festgeschrieben werden."""
        from django.urls import NoReverseMatch

        with pytest.raises(NoReverseMatch):
            reverse(f'admin:faktura_{modell}_import')
