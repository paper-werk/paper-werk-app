"""Steuersätze als Tabelle (``models/steuersatz.py``).

Geprüft wird ein neuer Satz zum Stichtag, der den bisherigen ersetzt: Er
ist im Formular wählbar, wird wie jeder Satz berechnet und im Import
erkannt. Der ersetzte bleibt an bestehenden Positionen.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse

from faktura import services
from faktura.forms import BelegpositionForm, KatalogpositionForm, NachlassForm
from faktura.models import (
    STEUERFREI,
    Belegposition,
    BelegTyp,
    Katalogposition,
    Kontakt,
    Steuersatz,
)
from faktura.models import steuersatz as steuersatz_tabelle
from faktura.ressourcen import KatalogpositionResource
from faktura.tests.test_gleichzeitig import formulardaten, gesichert

pytestmark = pytest.mark.django_db


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(nummer='K-7100', name='Stadtwerke Probedorf',
                           strasse='Am Wehr 2', plz='84028', ort='Landshut')


@pytest.fixture
def zwanzig(db):
    """Stichtag: 20 % wird Vorgabe, 19 % inaktiv."""
    neu = Steuersatz(satz=Decimal('20.00'), bezeichnung='Regelsteuersatz',
                     vorgabe=True, reihenfolge=5)
    neu.full_clean()
    neu.save()
    Steuersatz.objects.filter(satz=Decimal('19.00')).update(aktiv=False)
    return neu


def _werte(choices) -> list[str]:
    return [wert for wert, _ in choices]


class TestGrundausstattung:

    def test_fuenf_saetze_und_19_als_vorgabe(self):
        assert _werte(steuersatz_tabelle.angeboten()) == [
            '19.00', '7.00', '0.00', '16.00', '5.00']
        assert steuersatz_tabelle.vorgabe() == '19.00'

    def test_eine_gepflegte_tabelle_bleibt_unberuehrt(self, zwanzig):
        """``post_migrate`` legt nur in einer leeren Tabelle an, damit nach
        einem Update nicht wieder 19 % Vorgabe ist."""
        call_command('migrate', verbosity=0, stdout=StringIO())

        assert steuersatz_tabelle.vorgabe() == '20.00'
        assert Steuersatz.objects.count() == 6

    def test_neue_position_bekommt_die_vorgabe(self, kunde, zwanzig):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT,
                                       betreff='Pumpwerk')
        position = Belegposition.objects.create(
            beleg=beleg, bezeichnung='Prüfung', einzelpreis=Decimal('100.00'))
        katalog = Katalogposition.objects.create(
            bezeichnung='Prüfung', einzelpreis=Decimal('100.00'))

        assert position.steuersatz == '20.00'
        assert katalog.steuersatz == '20.00'


class TestRegeln:

    def test_eine_neue_vorgabe_loest_die_alte_ab(self):
        sieben = Steuersatz.objects.get(satz=Decimal('7.00'))
        sieben.vorgabe = True
        sieben.save()

        assert list(Steuersatz.objects.filter(vorgabe=True)) == [sieben]

    def test_der_satz_ist_nach_dem_anlegen_fest(self):
        satz = Steuersatz.objects.get(satz=Decimal('16.00'))
        satz.satz = Decimal('17.00')

        with pytest.raises(ValidationError, match='nach dem Anlegen fest'):
            satz.full_clean()

    def test_die_vorgabe_laesst_sich_nicht_abwaehlen(self):
        satz = Steuersatz.objects.get(vorgabe=True)
        satz.vorgabe = False

        with pytest.raises(ValidationError, match='muss Vorgabe sein'):
            satz.full_clean()

    def test_null_prozent_bleibt_waehlbar(self):
        """0 % bleibt wählbar, weil Mahnung, Lieferschein und Steuerfälle
        ``STEUERFREI`` setzen."""
        satz = Steuersatz.objects.get(satz=0)
        satz.aktiv = False

        with pytest.raises(ValidationError, match='0 % bleibt wählbar'):
            satz.full_clean()
        assert satz.wert == STEUERFREI


class TestAuswahl:

    def test_neuer_satz_ja_abgeloester_nein(self, zwanzig):
        werte = _werte(steuersatz_tabelle.angeboten())

        assert '20.00' in werte
        assert '19.00' not in werte

    def test_die_position_behaelt_ihren_abgeloesten_satz(self, kunde, zwanzig):
        """Die Position behält einen inaktiven Satz; sonst speicherte das
        Formular die Vorgabe oder lehnte die Zeile ab."""
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT,
                                       betreff='Pumpwerk')
        alt = services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Alt', menge=Decimal('1'),
            einzelpreis=Decimal('10.00'), steuersatz='19.00')

        assert '19.00' in _werte(
            BelegpositionForm(instance=alt).fields['steuersatz'].choices)
        assert '19.00' not in _werte(
            BelegpositionForm().fields['steuersatz'].choices)

    def test_die_positionszeile_zeigt_nur_den_satz(self):
        assert ('19.00', '19 %') in BelegpositionForm().fields['steuersatz'].choices

    def test_katalog_und_nachlass_bieten_dasselbe(self, zwanzig):
        katalog = KatalogpositionForm()
        nachlass = NachlassForm()

        assert '20.00' in _werte(katalog.fields['steuersatz'].choices)
        assert '20.00' in _werte(nachlass.fields['steuersatz'].choices)
        assert nachlass.fields['steuersatz'].initial() == '20.00'


class TestInDerMaske:
    """Speichern über das Formular mit Prüfung des gespeicherten Werts."""

    def _daten(self, kunde, satz):
        return {
            'kunde': kunde.pk, 'betreff': 'Neuer Satz',
            'belegdatum': '', 'leistungsdatum': '', 'leistungsdatum_bis': '',
            'zahlungsziel_tage': '14', 'empfaenger': '', 'empfaenger_ust_id': '',
            'kopftext': '', 'fusstext': '',
            'positionen-TOTAL_FORMS': '1', 'positionen-INITIAL_FORMS': '0',
            'positionen-MIN_NUM_FORMS': '0', 'positionen-MAX_NUM_FORMS': '1000',
            'positionen-0-katalog': '', 'positionen-0-position': '',
            'positionen-0-bezeichnung': 'Messung',
            'positionen-0-menge': '2', 'positionen-0-einheit': 'Std',
            'positionen-0-einzelpreis': '85.00',
            'positionen-0-steuersatz': satz,
        }

    def test_der_neue_satz_wird_gesichert(self, buero, kunde, zwanzig):
        buero.post(reverse('admin:faktura_angebot_add'),
                   self._daten(kunde, '20.00'), follow=True)

        assert Belegposition.objects.get(bezeichnung='Messung').steuersatz == '20.00'

    def test_ein_abgeloester_satz_wird_abgelehnt(self, buero, kunde, zwanzig):
        buero.post(reverse('admin:faktura_angebot_add'),
                   self._daten(kunde, '19.00'))

        assert not Belegposition.objects.filter(bezeichnung='Messung').exists()

    def test_unveraendert_gesichert_bleibt_die_leere_zeile_leer(self, buero, kunde):
        """Die leere Zeile hat die Vorgabe als Initialwert. Fehlte er im
        ersetzten Feld, gälte sie als geändert, und jedes Speichern schlüge
        mit "Bezeichnung angeben" fehl, auch vor dem Festschreiben."""
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT,
                                       betreff='Pumpwerk')
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Prüfung', menge=Decimal('1'),
            einzelpreis=Decimal('10.00'), steuersatz='19.00')
        url = reverse('admin:faktura_angebot_change', args=[beleg.pk])

        assert gesichert(buero.post(url, formulardaten(buero.get(url), 'angebot')))
        assert beleg.positionen.count() == 1

    def test_der_katalog_bietet_den_neuen_satz_vorgewaehlt(self, buero, zwanzig):
        inhalt = buero.get(reverse('admin:faktura_katalogposition_add')) \
            .content.decode()
        auswahl = inhalt.split('name="steuersatz"')[1].split('</select>')[0]

        assert '<option value="20.00" selected>20 % (Regelsteuersatz)' in auswahl
        assert 'value="19.00"' not in auswahl


class TestRechnen:
    """R-002/R-003 mit einem neu angelegten Satz."""

    def test_steuer_je_satz_mit_dem_neuen(self, kunde, zwanzig):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG,
                                       betreff='Pumpwerk',
                                       leistungsdatum=date(2027, 1, 15))
        for preis, satz in (('333.33', '20.00'), ('100.05', '7.00')):
            services.position_hinzufuegen(
                beleg=beleg, bezeichnung='Leistung', menge=Decimal('1'),
                einzelpreis=Decimal(preis), steuersatz=satz)

        summen = services.belegsummen(beleg)

        # 333,33 × 20 % = 66,666 → 66,67; 100,05 × 7 % = 7,0035 → 7,00
        assert summen.netto == Decimal('433.38')
        assert summen.steuer == Decimal('73.67')
        assert summen.brutto == Decimal('507.05')
        assert services.bruttosummen(
            type(beleg).objects.filter(pk=beleg.pk)) == {beleg.pk: Decimal('507.05')}

    def test_rechnungskorrektur_nimmt_die_vorgabe(self, kunde, zwanzig):
        rechnung = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG,
                                          betreff='Pumpwerk',
                                          leistungsdatum=date(2027, 1, 15))
        services.position_hinzufuegen(
            beleg=rechnung, bezeichnung='Leistung', menge=Decimal('1'),
            einzelpreis=Decimal('500.00'), steuersatz='20.00')
        services.beleg_festschreiben(beleg_id=rechnung.pk)

        korrektur = services.rechnungskorrektur_erstellen(
            beleg_id=rechnung.pk, betrag_netto=Decimal('50.00'), grund='Nachlass')

        assert korrektur.positionen.get().steuersatz == '20.00'


class TestImport:

    @pytest.mark.parametrize('geschrieben, erwartet', [
        ('20 %', '20.00'),
        ('20,00', '20.00'),
        ('voll', '20.00'),
        ('Ermäßigt', '7.00'),
        ('frei', '0.00'),
        ('', '20.00'),
    ])
    def test_der_satz_aus_der_tabelle(self, zwanzig, geschrieben, erwartet):
        assert KatalogpositionResource._steuersatz(geschrieben) == erwartet


class TestAdmin:

    def test_das_buero_legt_einen_satz_an(self, buero):
        buero.post(reverse('admin:faktura_steuersatz_add'), {
            'satz': '17.50', 'bezeichnung': 'Sondersatz', 'aktiv': 'on',
            'reihenfolge': '60'}, follow=True)

        assert Steuersatz.objects.filter(satz=Decimal('17.50')).exists()
        assert '17.50' in _werte(steuersatz_tabelle.angeboten())

    def test_niemand_loescht(self, admin_client):
        satz = Steuersatz.objects.get(satz=Decimal('16.00'))

        antwort = admin_client.get(
            reverse('admin:faktura_steuersatz_delete', args=[satz.pk]))

        assert antwort.status_code == 403

    def test_der_satz_ist_in_der_maske_schreibgeschuetzt(self, admin_client):
        satz = Steuersatz.objects.get(satz=Decimal('16.00'))

        inhalt = admin_client.get(reverse(
            'admin:faktura_steuersatz_change', args=[satz.pk])).content.decode()

        assert 'name="satz"' not in inhalt
        assert 'name="aktiv"' in inhalt
