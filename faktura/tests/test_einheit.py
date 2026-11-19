"""Einheiten nach UN/ECE (``faktura/models/einheit.py``).

Positionen speichern den Code; Anzeigetext und Erfassungsart kommen aus der
Tabelle ``Einheit``.
"""

import importlib
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from erfassung.models import Erfassungszeile
from faktura import facturx, services
from faktura.models import (
    BelegTyp,
    Einheit,
    Katalogposition,
    Kontakt,
    Leistungsart,
    Projekt,
)
from faktura.models import einheit as einheit_tabelle

pytestmark = pytest.mark.django_db

migration = importlib.import_module('faktura.migrations.0066_einheit')


@pytest.fixture
def projekt(db):
    kunde = Kontakt.anlegen(nummer='K-7000', name='Bauherr GmbH',
                            strasse='Weg 1', plz='80331', ort='München')
    return Projekt.objects.create(nummer='2026-070', bezeichnung='Halle',
                                  kunde=kunde)


class TestGrundausstattung:

    def test_die_ganze_codeliste_steht_in_der_tabelle(self):
        assert Einheit.objects.count() == len(einheit_tabelle.codeliste())
        assert Einheit.objects.count() > 2000

    def test_zur_auswahl_stehen_die_gebraeuchlichen(self):
        auswahl = dict(Einheit.objects.filter(zur_auswahl=True)
                       .values_list('code', 'anzeige'))

        assert auswahl == {code: text for code, (text, _)
                           in einheit_tabelle.GRUNDAUSSTATTUNG.items()}

    @pytest.mark.parametrize('code, art', [
        ('HUR', Leistungsart.ZEIT),
        ('LS', Leistungsart.PAUSCHALE),
        ('C62', Leistungsart.MENGE),
        ('KMH', Leistungsart.MENGE),
    ])
    def test_die_erfassungsart(self, code, art):
        assert einheit_tabelle.erfassungsart(code) == art

    def test_ein_zweiter_lauf_aendert_nichts(self):
        """Eine gepflegte Anzeige bleibt nach dem nächsten ``migrate``."""
        Einheit.objects.filter(pk='HUR').update(anzeige='h')

        einheit_tabelle.grundausstattung_anlegen(sender=None)

        assert Einheit.objects.get(pk='HUR').anzeige == 'h'

    def test_ein_fehlender_code_wird_ergaenzt(self):
        Einheit.objects.filter(pk='KMH').delete()

        einheit_tabelle.grundausstattung_anlegen(sender=None)

        neu = Einheit.objects.get(pk='KMH')
        assert neu.zur_auswahl is False


class TestAnzeige:

    def test_der_anzeigetext(self):
        assert einheit_tabelle.anzeige('HUR') == 'Std'

    def test_ohne_anzeige_der_code(self):
        assert einheit_tabelle.anzeige('KMH') == 'KMH'

    def test_ohne_code_nichts(self):
        assert einheit_tabelle.anzeige('') == ''

    def test_eine_geaenderte_anzeige_gilt_sofort(self):
        einheit = Einheit.objects.get(pk='HUR')
        assert einheit_tabelle.anzeige('HUR') == 'Std'

        einheit.anzeige = 'h'
        einheit.save()

        assert einheit_tabelle.anzeige('HUR') == 'h'

    def test_die_auswahl_behaelt_eine_abgewaehlte_einheit(self):
        Einheit.objects.filter(pk='SET').update(zur_auswahl=False)

        ohne = dict(einheit_tabelle.angeboten())
        mit = dict(einheit_tabelle.angeboten('SET'))

        assert 'SET' not in ohne
        assert mit['SET'] == 'Satz'


class TestPflege:

    def test_die_erfassungsart_ist_fest_sobald_positionen_sie_tragen(self):
        Katalogposition.objects.create(bezeichnung='Probe', einheit='KGM',
                                       einzelpreis=Decimal('1.00'))
        einheit = Einheit.objects.get(pk='KGM')
        einheit.erfassungsart = Leistungsart.PAUSCHALE

        with pytest.raises(ValidationError) as fehler:
            einheit.full_clean()

        assert 'erfassungsart' in fehler.value.message_dict

    def test_ohne_positionen_ist_sie_aenderbar(self):
        einheit = Einheit.objects.get(pk='KGM')
        einheit.erfassungsart = Leistungsart.PAUSCHALE

        einheit.full_clean()

    def test_zeit_nur_bei_der_stunde(self):
        """Die Übernahme in die Rechnung rechnet die Dauer in Stunden um."""
        einheit = Einheit.objects.get(pk='DAY')
        einheit.erfassungsart = Leistungsart.ZEIT

        with pytest.raises(ValidationError) as fehler:
            einheit.full_clean()

        assert 'erfassungsart' in fehler.value.message_dict

    def test_zur_auswahl_nur_mit_anzeige(self):
        einheit = Einheit.objects.get(pk='KMH')
        einheit.zur_auswahl = True

        with pytest.raises(ValidationError) as fehler:
            einheit.full_clean()

        assert 'anzeige' in fehler.value.message_dict

    def test_ohne_anlegen_und_loeschen(self, admin_client):
        antwort = admin_client.get(reverse('admin:faktura_einheit_add'))

        assert antwort.status_code == 403
        assert admin_client.get(
            reverse('admin:faktura_einheit_change', args=['HUR'])
        ).status_code == 200


class TestCodeZumText:

    @pytest.mark.parametrize('text, code', [
        ('Stk', 'C62'),
        ('Stk.', 'C62'),
        ('Stück', 'C62'),
        ('Std', 'HUR'),
        ('h', 'HUR'),
        ('psch', 'LS'),
        ('Pausch.', 'LS'),
        ('m²', 'MTK'),
        ('HUR', 'HUR'),
        ('Eimer', ''),
        ('', ''),
    ])
    def test_schreibweisen(self, text, code):
        assert einheit_tabelle.code_zum_text(text) == code

    def test_eine_geaenderte_anzeige_wird_erkannt(self):
        Einheit.objects.filter(pk='HUR').update(anzeige='Stunden lang')
        einheit_tabelle.zwischenspeicher_leeren()

        assert einheit_tabelle.code_zum_text('stunden lang') == 'HUR'


class TestMigration:
    """Die Abbildung der bisherigen Einheitentexte in ``0066_einheit``."""

    @pytest.mark.parametrize('text, code', [
        ('Stk', 'C62'),
        (' stk ', 'C62'),
        ('Std', 'HUR'),
        ('psch.', 'LS'),
        ('pausch', 'LS'),
        ('m²', 'MTK'),
        ('m3', 'MTQ'),
        ('lfm', 'MTR'),
        ('KGM', 'KGM'),
        ('Eimer', ''),
        ('', ''),
    ])
    def test_texte_werden_codes(self, text, code):
        assert migration.einheit_als_code(text, migration._codes()) == code


class TestErfassungsartAusDerEinheit:
    """Eine frei eingetragene Pauschale bekommt Von und Bis, weil die
    Erfassungsart an der Einheit hängt und nicht an der Herkunft der
    Position."""

    def test_eine_freie_pauschale_ist_eine_pauschale(self, projekt):
        auftrag = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.AUFTRAG)
        services.position_hinzufuegen(
            beleg=auftrag, bezeichnung='Ausführungsplanung',
            menge=Decimal('1'), einheit='LS', einzelpreis=Decimal('8500.00'),
            steuersatz='19.00')
        auftrag = services.beleg_festschreiben(beleg_id=auftrag.pk)
        zeile = Erfassungszeile(projekt=projekt,
                                auftragsposition=auftrag.positionen.get())

        assert zeile.leistungsart == Leistungsart.PAUSCHALE


class TestERechnung:

    @pytest.mark.parametrize('code', ['LS', 'MTK', 'HUR', 'C62'])
    def test_der_code_geht_unveraendert_hinaus(self, code):
        assert facturx.einheit_code(code) == code

    def test_ohne_einheit_stueck(self):
        """Zuschlagszeilen haben keine Einheit; BT-130 ist Pflicht."""
        assert facturx.einheit_code('') == 'C62'
