"""Browsertests des Belegformulars: Stammdaten und Positionen."""

import re
from decimal import Decimal

import pytest
from playwright.sync_api import expect

from faktura import services
from faktura.models import (
    Beleg,
    Katalogposition,
    Kontakt,
    Projekt,
    Textbaustein,
    TextbausteinVerwendung,
)
from tests.browserhilfen import _anmelden, _katalog_waehlen, _kunde_waehlen


@pytest.mark.django_db(transaction=True)
class TestStammdatenImFormular:
    """Übernahme der Stammdaten im Belegformular, im Browser geprüft."""

    def test_kundenwahl_fuellt_empfaenger_und_zahlungsziel(
            self, live_server, page, chefin, kunde):
        """Auch das Zahlungsziel: Beim Anlegen gilt der Default 14 als leer,
        sonst zeigte das Formular 14, während der Server 30 speichert."""
        Kontakt.objects.filter(pk=kunde.pk).update(zahlungsziel_tage=30)
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/faktura/angebot/add/')

        _kunde_waehlen(page, 'Wohnbau')

        expect(page.locator('#id_empfaenger')).to_have_value(
            re.compile('Wohnbau Isartal'))
        expect(page.locator('#id_zahlungsziel_tage')).to_have_value('30')

    def test_projektwahl_leert_den_kunden(self, live_server, page, chefin,
                                         kunde):
        """Die Wahl eines Projekts leert den Kunden, wie die Validierung des
        Servers verlangt."""
        projekt = Projekt.objects.create(
            nummer='2026-001', bezeichnung='Ludwigsplatz 9', kunde=kunde)
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/faktura/angebot/add/')
        _kunde_waehlen(page, 'Wohnbau')

        page.select_option('#id_projekt', value=str(projekt.pk))

        expect(page.locator('#id_kunde')).to_have_value('')

    def test_textvorlage_landet_im_feld(self, live_server, page, chefin):
        Textbaustein.objects.create(
            name='Dank für Anfrage', verwendung=TextbausteinVerwendung.BELEGTEXT,
            text='Wir bedanken uns für Ihre Anfrage.')
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/faktura/angebot/add/')

        page.locator('.textvorlagen-feld:has(#id_kopftext) button',
                     has_text='Textvorlagen').click()
        page.locator('[data-vorlage][data-ziel="id_kopftext"]',
                     has_text='Dank für Anfrage').click()

        expect(page.locator('#id_kopftext')).to_have_value(
            'Wir bedanken uns für Ihre Anfrage.')


@pytest.mark.django_db(transaction=True)
class TestPositionenImFormular:
    """Katalogsuche über der Positionszeile und vorbelegte Nummern, im
    Browser, weil beides JavaScript ist."""

    @pytest.fixture
    def katalog(self, db):
        Katalogposition.objects.create(
            nummer='E-100', bezeichnung='Gesellenstunde', einheit='Std',
            einzelpreis=Decimal('62.00'))
        return Katalogposition.objects.create(
            nummer='E-210', bezeichnung='Unterverteilung setzen',
            langtext='Aufputz, bis 24 Module, inkl. Hutschiene',
            einheit='Stk', einzelpreis=Decimal('340.00'))

    def test_die_suche_findet_ueber_den_langtext_und_fuellt_die_zeile(
            self, live_server, page, chefin, kunde, katalog):
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/faktura/angebot/add/')

        _katalog_waehlen(page, 0, 'Hutschiene', 'Unterverteilung')

        expect(page.locator('#id_positionen-0-bezeichnung')).to_have_value(
            'Unterverteilung setzen')
        expect(page.locator('#id_positionen-0-einzelpreis')).to_have_value(
            '340.00')
        expect(page.locator('#id_positionen-0-langtext')).to_have_value(
            re.compile('Hutschiene'))

    def test_eine_angefuegte_zeile_hat_nummer_und_suche(
            self, live_server, page, chefin, kunde, katalog):
        """Eine angefügte Zeile hat Nummer und Suche, obwohl sie aus der
        Vorlage im Browser entsteht, ohne Vorbelegung des Servers und ohne
        automatisches Select2."""
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/faktura/angebot/add/')
        expect(page.locator('#id_positionen-2-position')).to_have_value('30')

        page.locator('a.add-row').first.click()

        expect(page.locator('#id_positionen-3-position')).to_have_value('40')
        _katalog_waehlen(page, 3, 'Gesellen', 'Gesellenstunde')
        expect(page.locator('#id_positionen-3-einheit')).to_have_value('Std')

    def test_angefuegt_hinter_lv_nummern_geht_es_in_ihrer_form_weiter(
            self, live_server, page, chefin, kunde):
        """positionsnummer.js zählt wie faktura/positionsnummer.py die letzte
        Ziffernfolge der höchsten Nummer weiter."""
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/faktura/angebot/add/')
        page.locator('#id_positionen-0-position').fill('01.01.0010')
        page.locator('#id_positionen-1-position').fill('01.02.0010')
        page.locator('#id_positionen-2-position').fill('01.01.0020')

        page.locator('a.add-row').first.click()

        expect(page.locator('#id_positionen-3-position')).to_have_value(
            '01.02.0020')

    @pytest.mark.parametrize(('menge', 'preis', 'erwartet'), [
        # Die Hälfte aufgerundet; in Gleitkomma ergäbe sich 67,12.
        ('0.75', '89.50', '67,13 EUR'),
        ('12', '1234.56', '14.814,72 EUR'),
        # Ein Nachlass: die Hälfte von der Null weg, wie beim Server.
        ('0.75', '-89.50', '-67,13 EUR'),
        ('0.001', '0.01', '0,00 EUR'),
    ])
    def test_die_summe_netto_rechnet_beim_tippen_mit(
            self, live_server, page, chefin, menge, preis, erwartet):
        """Die Nettosumme bei Eingabe rechnet wie services.positionssumme(),
        damit die Anzeige auf den Cent dem Beleg entspricht."""
        from faktura import formate
        # Zuerst die Referenz des Servers.
        assert formate.geld_mit_waehrung(services.positionssumme(
            menge=Decimal(menge), einzelpreis=Decimal(preis))) == erwartet
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/faktura/angebot/add/')
        summe = page.locator('tr.form-row:has(#id_positionen-0-menge) '
                             'td.field-zeilensumme')
        expect(summe).to_have_text('-')

        page.fill('#id_positionen-0-menge', menge)
        page.fill('#id_positionen-0-einzelpreis', preis)

        expect(summe).to_have_text(erwartet)

    def test_zuschlag_auf_schlaegt_die_zeilen_der_maske_vor(
            self, live_server, page, chefin):
        """Das Feld "auf" schlägt die Zeilen der Maske vor, auch nicht
        gespeicherte, ohne den Zuschlag selbst und ohne die Vorlage für
        angefügte Zeilen (zuschlag_auf.js)."""
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/faktura/angebot/add/')
        page.fill('#id_positionen-0-position', '3.1')
        page.fill('#id_positionen-0-bezeichnung', 'Raumluftmessung')
        page.select_option('#id_positionen-1-zeilenart', 'titel')
        page.fill('#id_positionen-1-position', '01')
        page.fill('#id_positionen-1-bezeichnung', 'Analytik')
        page.select_option('#id_positionen-2-zeilenart', 'zuschlag')

        page.focus('#id_positionen-2-zuschlag_auf')

        optionen = page.locator('#pw-zuschlag-ziele option')
        expect(optionen).to_have_count(2)
        werte = [optionen.nth(i).get_attribute('value') for i in range(2)]
        assert werte == ['3.1', '01']
        assert optionen.nth(1).get_attribute('label') == 'Titel Analytik'
        expect(page.locator('#id_positionen-2-zuschlag_auf')).to_have_attribute(
            'list', 'pw-zuschlag-ziele')

    def test_die_katalogwahl_fuellt_auch_die_summe(
            self, live_server, page, chefin, katalog):
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/faktura/angebot/add/')
        page.fill('#id_positionen-0-menge', '2')

        _katalog_waehlen(page, 0, 'E-210', 'Unterverteilung')

        expect(page.locator('tr.form-row:has(#id_positionen-0-menge) '
                            'td.field-zeilensumme')).to_have_text('680,00 EUR')

    def test_die_bezeichnung_fuellt_ihre_spalte(self, live_server, page,
                                                 chefin):
        """Die Bezeichnung füllt ihre Spalte, gemessen im Browser.

        Regression: Ein max-width am Wrapper des Felds begrenzte es auf
        672 px; eine Regel am Feld allein wirkte nicht."""
        page.set_viewport_size({'width': 2400, 'height': 1200})
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/faktura/angebot/add/')

        feld, spalte = page.evaluate('''() => {
            const td = document.querySelector('td.field-bezeichnung');
            return [td.querySelector('input').offsetWidth, td.clientWidth];
        }''')

        assert feld > 672
        # Abzüglich Padding der Zelle.
        assert spalte - feld < 40

    def test_gesichert_wird_nur_die_genutzte_zeile(
            self, live_server, page, chefin, kunde, katalog):
        """Gespeichert wird nur die genutzte Zeile; Zeilen nur mit Nummer
        gelten nicht als Eingabe."""
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/faktura/angebot/add/')
        _kunde_waehlen(page, 'Wohnbau')
        page.fill('#id_betreff', 'Verteilung Ludwigsplatz')
        page.locator('a.add-row').first.click()
        _katalog_waehlen(page, 0, 'E-210', 'Unterverteilung')

        page.locator('button[name="_continue"]').click()
        page.wait_for_load_state('networkidle')

        beleg = Beleg.objects.get(betreff='Verteilung Ludwigsplatz')
        assert [(p.position, p.bezeichnung, p.einzelpreis)
                for p in beleg.positionen.all()] \
            == [('10', 'Unterverteilung setzen', Decimal('340.00'))]
