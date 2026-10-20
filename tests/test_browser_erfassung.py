"""Browsertests der Leistungserfassung und ihrer Übernahme in Belege."""

from datetime import date, time
from decimal import Decimal

import pytest
from playwright.sync_api import expect

from erfassung import services as erfassung_services
from faktura.models import (
    BelegStatus,
    BelegTyp,
    Katalogposition,
    Kontakt,
    Leistungsart,
    Projekt,
)
from tests.browserhilfen import _anmelden, _auftrag_mit_position


@pytest.mark.django_db(transaction=True)
class TestStundenInDieRechnung:
    """Erfasste Stunden über die Listenaktion und ihre Zwischenseite."""

    def test_die_ausgewaehlten_stunden_landen_auf_einem_rechnungsentwurf(
            self, live_server, page, chefin, kunde):
        projekt = Projekt.objects.create(nummer='2026-042', bezeichnung='Halle',
                                         kunde=kunde)
        leistung = Katalogposition.objects.create(
            bezeichnung='Gesellenstunde', einheit='Std',
            einzelpreis=Decimal('62.00'), kontierbar=True,
            art=Leistungsart.ZEIT)
        zeile = erfassung_services.zeile_erfassen(
            projekt=projekt, leistung=leistung, benutzer=chefin,
            von=time(7, 0), bis=time(9, 0), beschreibung='Verteiler setzen')

        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/erfassung/erfassungszeile/')
        page.check('#action-toggle')
        page.select_option('select[name="action"]', 'in_rechnung')
        page.locator('button[name="index"]').click()
        page.wait_for_load_state('networkidle')
        page.get_by_role('button', name='Übernehmen').click()
        page.wait_for_load_state('networkidle')

        zeile.refresh_from_db()
        assert zeile.abgerechnet_in is not None, 'die Zeile hängt an keiner Rechnung'
        rechnung = zeile.abgerechnet_in.beleg
        assert rechnung.typ == BelegTyp.RECHNUNG
        assert rechnung.status == BelegStatus.ENTWURF
        assert zeile.abgerechnet_in.menge == Decimal('2.000')


@pytest.mark.django_db(transaction=True)
class TestAuftragspositionDerFremdleistung:
    """Nur Auftragspositionen des gewählten Projekts, in der Einzelmaske wie
    in der Eingangsrechnung.

    Regression: Die Einzelmaske zeigte alle Aufträge, weil das Skript nur
    Feldnamen der Eingangsrechnung ("positionen-0-projekt") behandelte und
    nicht "projekt"; erst das Speichern meldete den Fehler.
    """

    @pytest.fixture
    def bestand(self, kunde):
        from erfassung.models import Eingangsrechnung, Fremdleistung

        nord = Projekt.objects.create(nummer='2026-071', bezeichnung='Nord',
                                      kunde=kunde)
        sued = Projekt.objects.create(nummer='2026-072', bezeichnung='Süd',
                                      kunde=kunde)
        labor_nord = _auftrag_mit_position(nord, 'AU-2026-0071', 'Labor Nord')
        labor_sued = _auftrag_mit_position(sued, 'AU-2026-0072', 'Labor Süd')
        lieferant = Kontakt.objects.create(name='ISARTAL', ist_kunde=False,
                                           ist_lieferant=True)
        rechnung = Eingangsrechnung.objects.create(
            lieferant=lieferant, nummer='AL-71', datum=date(2026, 9, 1),
            betrag_netto=Decimal('96.00'))
        fremd = Fremdleistung.objects.create(
            rechnung=rechnung, projekt=nord, bezeichnung='Paket 4711',
            menge=Decimal('1'), einkaufspreis=Decimal('96.00'))
        return {'nord': nord, 'sued': sued, 'labor_nord': labor_nord,
                'labor_sued': labor_sued, 'rechnung': rechnung,
                'fremd': fremd}

    @staticmethod
    def _option(page, feld, position):
        return page.locator(f'select[name="{feld}"] option[value="{position.pk}"]')

    def test_die_einzelmaske_zeigt_nur_das_eigene_projekt(
            self, live_server, page, chefin, bestand):
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/erfassung/fremdleistung/'
                  f'{bestand["fremd"].pk}/change/')
        page.wait_for_load_state('networkidle')

        expect(self._option(page, 'auftragsposition',
                            bestand['labor_nord'])).to_be_enabled()
        expect(self._option(page, 'auftragsposition',
                            bestand['labor_sued'])).to_be_disabled()

    def test_nach_dem_projektwechsel_die_positionen_des_neuen(
            self, live_server, page, chefin, bestand):
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/erfassung/fremdleistung/'
                  f'{bestand["fremd"].pk}/change/')
        page.wait_for_load_state('networkidle')

        # Das Projekt ist ein Select2-Autocomplete, gewählt über die
        # Oberfläche, weil es sonst kein Event auslöst.
        page.locator('#id_projekt + .select2 .select2-selection').click()
        page.locator('.select2-search__field').fill('Süd')
        page.locator('.select2-results__option', has_text='Süd').first.click()

        expect(self._option(page, 'auftragsposition',
                            bestand['labor_sued'])).to_be_enabled()
        expect(self._option(page, 'auftragsposition',
                            bestand['labor_nord'])).to_be_disabled()

    def test_in_der_eingangsrechnung_je_zeile(self, live_server, page,
                                               chefin, bestand):
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/erfassung/eingangsrechnung/'
                  f'{bestand["rechnung"].pk}/change/')
        page.wait_for_load_state('networkidle')

        expect(self._option(page, 'positionen-0-auftragsposition',
                            bestand['labor_nord'])).to_be_enabled()
        expect(self._option(page, 'positionen-0-auftragsposition',
                            bestand['labor_sued'])).to_be_disabled()


@pytest.mark.django_db(transaction=True)
class TestErfassungsmaske:
    """Erfassungsmaske: Von und Bis teilen die Breite eines Felds, "Bis"
    endet bündig mit den anderen, der Hinweis zur Pauschale steht klein
    darunter."""

    def test_von_bis_auf_der_breite_eines_feldes(self, live_server, page,
                                                 chefin):
        page.set_viewport_size({'width': 1600, 'height': 1000})
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/erfassung/erfassungszeile/add/')
        # Sonst erst nach Wahl einer Leistung sichtbar.
        page.evaluate("document.querySelectorAll('.field-line[x-show]')"
                      ".forEach(e => e.style.display = '')")

        def kasten(selektor):
            return page.locator(selektor).bounding_box()

        datum = kasten('#id_datum')
        von = kasten('#id_von')
        bis = kasten('#id_bis')
        hinweis = kasten('.pw-hinweis')
        rechts = datum['x'] + datum['width']
        assert abs(von['x'] - datum['x']) <= 1
        assert abs(von['y'] - bis['y']) <= 1
        assert abs(bis['x'] + bis['width'] - rechts) <= 1
        assert von['x'] + von['width'] < bis['x']
        assert hinweis['y'] > von['y'] + von['height']
        assert abs(hinweis['x'] - datum['x']) <= 1

    def test_das_uhrzeitfeld_des_browsers(self, live_server, page, chefin):
        """Eingegebene Uhrzeit wird als HH:MM gesendet."""
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/erfassung/erfassungszeile/add/')

        assert page.locator('#id_von').get_attribute('type') == 'time'
        assert page.locator('.field-von .clock-icon').count() == 0
