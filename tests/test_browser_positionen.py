"""Browsertests der Positionen: Darstellung, Spalten, Werte, Löschen, Katalogsuche."""

import re
from datetime import date, time
from decimal import Decimal

import pytest
from playwright.sync_api import expect

from erfassung import services as erfassung_services
from faktura import services
from faktura.models import (
    Beleg,
    BelegTyp,
    Katalogposition,
    Leistungsart,
    Projekt,
)
from tests.browserhilfen import _anmelden, _beleg_mit_fuenf_positionen, _entwurf, _katalog_waehlen


@pytest.mark.django_db(transaction=True)
class TestPositionLoeschen:
    """Löschen einer Position zeigt sofort das Overlay.

    Unfold legt über eine zum Löschen markierte Position ein Overlay mit
    "Abbrechen"; gelöscht wird beim Speichern. Die CSS-Regel greift nur,
    wenn die Overlay-Zeile direkt auf die Positionszeile folgt. Regression:
    Die Langtextzeile stand dazwischen, und der Klick zeigte nichts.
    """

    @pytest.fixture
    def rechnung(self, chefin, kunde):
        """Entwurf mit zwei Positionen, die erste aus erfassten Stunden, die
        zweite manuell."""
        projekt = Projekt.objects.create(nummer='2026-081', bezeichnung='Halle',
                                         kunde=kunde)
        leistung = Katalogposition.objects.create(
            bezeichnung='Gesellenstunde', einheit='Std',
            einzelpreis=Decimal('62.00'), kontierbar=True,
            art=Leistungsart.ZEIT)
        zeile = erfassung_services.zeile_erfassen(
            projekt=projekt, leistung=leistung, benutzer=chefin,
            von=time(7, 0), bis=time(9, 0), beschreibung='Verteiler setzen')
        beleg, _ = erfassung_services.in_rechnung_uebernehmen(zeilen=[zeile])
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Anfahrt', menge=Decimal('1'),
            einheit='pausch', einzelpreis=Decimal('45.00'),
            steuersatz='19.00')
        beleg.leistungsdatum = date(2026, 9, 1)
        beleg.save()
        return beleg, zeile

    def _oeffnen(self, page, live_server, beleg):
        from faktura.admin import adresse_im_admin

        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}{adresse_im_admin(beleg)}')
        page.wait_for_load_state('networkidle')

    @staticmethod
    def _schleier(page, nummer):
        """Das Overlay-Element, nicht seine Zeile, weil die Zeile keine Höhe
        hat und Playwright sie als unsichtbar wertet; das Element liegt
        absolut positioniert über der Position."""
        return page.locator(
            f'tbody.form-group:has(#id_positionen-{nummer}-DELETE) '
            f'tr.form-delete td > div')

    @staticmethod
    def _muelltonne(page, nummer):
        return page.locator(
            f'label:has(#id_positionen-{nummer}-DELETE)')

    def test_der_klick_zeigt_den_schleier_sofort(self, live_server, page,
                                                 rechnung):
        beleg, _ = rechnung
        self._oeffnen(page, live_server, beleg)
        expect(self._schleier(page, 0)).to_be_hidden()

        self._muelltonne(page, 0).click()

        expect(self._schleier(page, 0)).to_be_visible()
        # Unabhängig von der Sprache: Das Overlay enthält den Button, der
        # die Checkbox zurücksetzt.
        expect(self._schleier(page, 0).locator(
            'label[for="id_positionen-0-DELETE"]')).to_be_visible()
        # Nur diese Position; die andere bleibt unverändert.
        expect(self._schleier(page, 1)).to_be_hidden()

    def test_abbrechen_nimmt_ihn_wieder_weg(self, live_server, page,
                                            rechnung):
        beleg, _ = rechnung
        self._oeffnen(page, live_server, beleg)
        self._muelltonne(page, 0).click()
        expect(self._schleier(page, 0)).to_be_visible()

        self._schleier(page, 0).locator('label').click()

        expect(self._schleier(page, 0)).to_be_hidden()
        expect(page.locator('#id_positionen-0-DELETE')).not_to_be_checked()

    def test_beim_speichern_ist_sie_weg_und_die_zeit_wieder_offen(
            self, live_server, page, rechnung):
        beleg, zeile = rechnung
        self._oeffnen(page, live_server, beleg)
        self._muelltonne(page, 0).click()

        page.locator('button[name="_continue"]').click()
        page.wait_for_load_state('networkidle')

        assert [p.bezeichnung for p in beleg.positionen.all()] == ['Anfahrt']
        zeile.refresh_from_db()
        assert zeile.abgerechnet_in is None, 'die Stunden hängen noch'


@pytest.mark.django_db(transaction=True)
class TestPositionenDarstellung:
    """Layout der Positionen nach ``docs/belegansicht.md``, im Browser
    gemessen.

    Gemessen, weil Unfold eigene Klassen an denselben Zellen setzt und erst
    der Browser die Spezifität auflöst."""

    def _oeffnen(self, page, live_server, beleg):
        from faktura.admin import adresse_im_admin

        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}{adresse_im_admin(beleg)}')
        page.wait_for_load_state('networkidle')

    @staticmethod
    def _links(page, selektor):
        return page.locator(selektor).first.bounding_box()['x']

    def test_der_langtext_beginnt_unter_der_bezeichnung(
            self, live_server, page, chefin, kunde):
        page.set_viewport_size({'width': 1600, 'height': 900})
        beleg = _beleg_mit_fuenf_positionen(kunde, BelegTyp.RECHNUNG)
        self._oeffnen(page, live_server, beleg)

        bezeichnung = self._links(page, '#id_positionen-0-bezeichnung')
        langtext = self._links(page, '#id_positionen-0-langtext')
        # Ebenso die erste Zeile der leeren Position darunter: Zeilenart,
        # rechts daneben die Suche.
        suche = self._links(
            page, 'tbody.form-group:has(#id_positionen-5-bezeichnung) '
                  '.erste-zeile-feld.field-zeilenart select')

        assert abs(langtext - bezeichnung) <= 1
        assert abs(suche - bezeichnung) <= 1
        # Gleich breit, damit beides als ein Block erscheint.
        breite = [page.locator(f'#id_positionen-0-{feld}').bounding_box()
                  ['width'] for feld in ('bezeichnung', 'langtext')]
        assert abs(breite[0] - breite[1]) <= 1, breite

    def test_ueberall_derselbe_abstand(self, live_server, page, chefin,
                                       kunde):
        """Gleicher Abstand zwischen Suche, Bezeichnung, Langtext, Trennlinie
        und nächster Position. Regression: Eine spätere CSS-Regel
        überschrieb den Abstand unter dem Langtext."""
        page.set_viewport_size({'width': 1600, 'height': 900})
        beleg = _beleg_mit_fuenf_positionen(kunde, BelegTyp.RECHNUNG)
        TestPositionenDarstellung()._oeffnen(page, live_server, beleg)

        def kasten(selektor):
            return page.locator(selektor).first.bounding_box()

        def gruppe(nummer):
            return kasten(f'tbody.form-group:has(#id_positionen-{nummer}-'
                          f'bezeichnung)')

        bez0 = kasten('#id_positionen-0-bezeichnung')
        lang0 = kasten('#id_positionen-0-langtext')
        bez1 = kasten('#id_positionen-1-bezeichnung')
        # Position 5 ist neu und hat die Suche über sich.
        suche5 = kasten('tbody.form-group:has(#id_positionen-5-bezeichnung) '
                        '.erste-zeile-feld .select2')
        bez5 = kasten('#id_positionen-5-bezeichnung')

        abstaende = {
            'Bezeichnung bis Langtext': lang0['y'] - (bez0['y'] + bez0['height']),
            'Langtext bis Linie': gruppe(1)['y'] - (lang0['y'] + lang0['height']),
            'Linie bis Position': bez1['y'] - gruppe(1)['y'],
            'Linie bis Suche': suche5['y'] - gruppe(5)['y'],
            'Suche bis Bezeichnung': bez5['y'] - (suche5['y'] + suche5['height']),
        }
        assert max(abstaende.values()) - min(abstaende.values()) <= 2,             abstaende

    @pytest.mark.parametrize('breite', [1280, 1366, 1920])
    def test_die_datumsfelder_haben_platz(self, live_server, page, chefin,
                                          kunde, breite):
        """Die Datumsfelder haben Platz. Regression: Unfolds min-width schob
        "Leistung bis" über das Feld davor."""
        page.set_viewport_size({'width': breite, 'height': 900})
        beleg = _beleg_mit_fuenf_positionen(kunde, BelegTyp.RECHNUNG)
        TestPositionenDarstellung()._oeffnen(page, live_server, beleg)

        von = page.locator('.field-leistung_von').first.bounding_box()
        bis_beschriftung = page.locator(
            '.field-leistung_bis .pw-zusatzbeschriftung').first.bounding_box()
        bis_feld = page.locator('#id_positionen-0-leistung_bis').bounding_box()
        zelle = page.locator('td.pw-zusatzrest').first.bounding_box()

        assert von['x'] + von['width'] + 8 <= bis_beschriftung['x'], (
            von, bis_beschriftung)
        assert bis_feld['x'] + bis_feld['width'] <= (
            zelle['x'] + zelle['width'] - 8), (bis_feld, zelle)

    def test_e_rechnung_in_zwei_spalten(self, live_server, page, chefin,
                                        kunde):
        """E-Rechnungsfelder in zwei Spalten; ein einzelnes Feld endet auf Höhe
        des Felds Ort neben der PLZ."""
        page.set_viewport_size({'width': 1600, 'height': 900})
        beleg = _beleg_mit_fuenf_positionen(kunde, BelegTyp.RECHNUNG)
        TestPositionenDarstellung()._oeffnen(page, live_server, beleg)
        page.locator('a', has_text='E-Rechnung').first.click()

        name = page.locator('#id_empfaenger_name').bounding_box()
        plz = page.locator('#id_empfaenger_plz').bounding_box()

        assert abs((name['x'] + name['width']) - (plz['x'] + plz['width'])) <= 2

    def test_auch_nur_zum_lesen(self, live_server, page, chefin, kunde):
        """Auch readonly stimmt das Layout; ohne Eingabefelder ist die Spalte
        "Pos." schmaler. Regression: Padding links 18 px abweichend."""
        page.set_viewport_size({'width': 1600, 'height': 900})
        beleg = _beleg_mit_fuenf_positionen(kunde, BelegTyp.ANGEBOT)
        beleg = services.beleg_festschreiben(beleg_id=beleg.pk)
        self._oeffnen(page, live_server, beleg)

        bezeichnung = self._links(
            page, 'tr.form-row td.field-bezeichnung .readonly')
        langtext = self._links(
            page, 'tr.form-row-zweite-zeile .field-langtext .readonly')

        assert abs(langtext - bezeichnung) <= 1
        # Ein leerer Langtext hinterlässt keine Zeile.
        expect(page.locator('tr.form-row-zweite-zeile:visible')).to_have_count(1)

    @pytest.mark.parametrize('breite', [1280, 1366])
    @pytest.mark.parametrize('typ', [BelegTyp.RECHNUNG, BelegTyp.AUFTRAG])
    def test_auf_laptopbreite_ohne_querscrollen(
            self, live_server, page, chefin, kunde, typ, breite):
        """Bei 1366 px kein horizontales Scrollen.

        Regression: Spaltenköpfe wie "Einzelpreis netto (BT-146)" in einer
        Zeile schnitten die Summe ab. Der Auftrag hat zusätzlich die Spalte
        "Abgerechnet"."""
        page.set_viewport_size({'width': breite, 'height': 900})
        beleg = _beleg_mit_fuenf_positionen(kunde, typ)
        self._oeffnen(page, live_server, beleg)

        inhalt, sichtbar, seite, fenster = page.evaluate('''() => {
            const huelle = document.querySelector('#positionen-data')
                .closest('.formset-wrapper');
            const wurzel = document.documentElement;
            return [huelle.scrollWidth, huelle.clientWidth,
                    wurzel.scrollWidth, wurzel.clientWidth];
        }''')
        assert inhalt <= sichtbar, f'Tabelle {inhalt} px, sichtbar {sichtbar}'
        assert seite <= fenster

        tonne = page.locator('label:has(#id_positionen-0-DELETE)')
        box = tonne.bounding_box()
        assert box['x'] + box['width'] <= breite, 'Mülltonne außerhalb'

        # Ohne horizontales Scrollen bleiben die Zahlen vollständig.
        # Regression: Im Auftrag erschien "40.000" als "40.0".
        for feld in ('menge', 'einzelpreis'):
            voll, breit = page.locator(f'#id_positionen-0-{feld}').evaluate(
                'el => [el.scrollWidth, el.clientWidth]')
            assert voll <= breit, f'{feld} abgeschnitten'

    def test_unter_vorhandenen_positionen_eine_leere_zeile(
            self, live_server, page, chefin, kunde):
        beleg = _beleg_mit_fuenf_positionen(kunde, BelegTyp.RECHNUNG)
        self._oeffnen(page, live_server, beleg)

        expect(page.locator('input[name$="-bezeichnung"]:visible')
               ).to_have_count(6)

    def test_hervorgehoben_ist_nur_die_position_in_arbeit(
            self, live_server, page, chefin, kunde):
        beleg = _beleg_mit_fuenf_positionen(kunde, BelegTyp.RECHNUNG)
        self._oeffnen(page, live_server, beleg)

        def flaeche(nummer):
            return page.locator(
                f'tr.form-row:has(#id_positionen-{nummer}-bezeichnung) '
                f'td.field-bezeichnung').evaluate(
                    'td => getComputedStyle(td).backgroundColor')

        ohne = flaeche(1)
        page.locator('#id_positionen-1-menge').click()

        assert flaeche(1) != ohne
        assert flaeche(0) == ohne


@pytest.mark.django_db(transaction=True)
class TestZeilenartImBrowser:
    """Felder ohne Bedeutung für die Zeilenart werden beim Umstellen
    ausgeblendet und ``disabled``."""

    def test_titel_ohne_menge_zuschlag_mit_prozent(self, live_server, page,
                                                   chefin, kunde):
        beleg = _beleg_mit_fuenf_positionen(kunde, BelegTyp.ANGEBOT)
        TestPositionenDarstellung()._oeffnen(page, live_server, beleg)
        menge = page.locator('#id_positionen-5-menge')
        steuer = page.locator('#id_positionen-5-steuersatz')
        prozent = page.locator('#id_positionen-5-zuschlag_prozent')
        expect(menge).to_be_visible()
        expect(prozent).to_be_hidden()

        page.select_option('#id_positionen-5-zeilenart', 'titel')
        expect(menge).to_be_hidden()
        expect(menge).to_be_disabled()
        expect(steuer).to_be_hidden()
        expect(prozent).to_be_hidden()

        page.select_option('#id_positionen-5-zeilenart', 'zuschlag')
        expect(menge).to_be_hidden()
        expect(steuer).to_be_visible()
        expect(prozent).to_be_visible()
        expect(prozent).to_be_enabled()

        page.select_option('#id_positionen-5-zeilenart', 'leistung')
        expect(menge).to_be_visible()
        expect(menge).to_be_enabled()
        expect(prozent).to_be_hidden()

    def test_am_zuschlag_prozent_und_auf_unter_der_bezeichnung(
            self, live_server, page, chefin, kunde):
        """Prozent und "auf" stehen in der Spalte der Bezeichnung, darunter der
        Langtext, wie der Rechenweg im PDF. Der Zeitraum rechts daneben in
        einer Reihe innerhalb seiner Zelle."""
        from faktura.models import Zeilenart
        page.set_viewport_size({'width': 1600, 'height': 900})
        beleg = _beleg_mit_fuenf_positionen(kunde, BelegTyp.RECHNUNG)
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Nebenkosten 3 %', menge=Decimal('1'),
            einzelpreis=Decimal('0.00'), steuersatz='19.00',
            zeilenart=Zeilenart.ZUSCHLAG, zuschlag_prozent=Decimal('3'))
        TestPositionenDarstellung()._oeffnen(page, live_server, beleg)

        def kasten(selektor):
            return page.locator(selektor).bounding_box()

        bezeichnung = kasten('#id_positionen-5-bezeichnung')
        prozent = kasten('#id_positionen-5-zuschlag_prozent')
        auf = kasten('#id_positionen-5-zuschlag_auf')
        langtext = kasten('#id_positionen-5-langtext')
        assert abs(prozent['x'] - bezeichnung['x']) <= 1
        assert abs(prozent['y'] - auf['y']) <= 1
        assert (auf['x'] + auf['width']
                <= bezeichnung['x'] + bezeichnung['width'] + 1)
        assert langtext['y'] > prozent['y'] + prozent['height']

        zelle = kasten('tbody.form-group:has(#id_positionen-5-bezeichnung) '
                       'td.pw-zusatzrest')
        von = kasten('#id_positionen-5-leistung_von')
        bis = kasten('#id_positionen-5-leistung_bis')
        assert abs(von['y'] - bis['y']) <= 1
        assert bis['x'] + bis['width'] <= zelle['x'] + zelle['width'] + 1
        assert von['width'] > 80 and bis['width'] > 80


@pytest.mark.django_db(transaction=True)
class TestZuschlagBeiEingabe:
    """Der Betrag eines Zuschlags folgt der Eingabe, nicht erst dem
    Speichern (zeilensumme.js). Regression: Nach dem Umstellen von "auf" auf
    einen Titel blieb der alte Betrag stehen."""

    @pytest.fixture
    def angebot(self, chefin, kunde):
        """Titel 01 mit 01.1 (2 x 50,00), Titel 02 mit 02.1 (1 x 50,50),
        Zuschlag 3 % auf alles: 4,52 (150,50 x 3 % = 4,515, halber Cent
        aufgerundet)."""
        from faktura.models import Zeilenart
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT,
                                       betreff='Zuschlag')
        for nummer, text, art, menge, preis in (
                ('01', 'Erkundung', Zeilenart.TITEL, '0', '0'),
                ('01.1', 'Bohrung', Zeilenart.LEISTUNG, '2', '50.00'),
                ('02', 'Analytik', Zeilenart.TITEL, '0', '0'),
                ('02.1', 'Asbest', Zeilenart.LEISTUNG, '1', '50.50')):
            services.position_hinzufuegen(
                beleg=beleg, position=nummer, bezeichnung=text, zeilenart=art,
                menge=Decimal(menge), einzelpreis=Decimal(preis),
                steuersatz='19.00')
        services.position_hinzufuegen(
            beleg=beleg, position='04', bezeichnung='Nebenkosten',
            zeilenart=Zeilenart.ZUSCHLAG, zuschlag_prozent=Decimal('3'),
            menge=Decimal('1'), einzelpreis=Decimal('0'), steuersatz='19.00')
        return beleg

    @staticmethod
    def _betrag(page, nummer):
        return page.locator(
            f'tbody.form-group:has(#id_positionen-{nummer}-bezeichnung) '
            f'td.field-zeilensumme .readonly')

    def test_zuschlag_folgt_auf_menge_und_option(self, live_server, page,
                                                 angebot):
        TestPositionenDarstellung()._oeffnen(page, live_server, angebot)
        zuschlag = self._betrag(page, 4)
        expect(zuschlag).to_have_text('4,52 EUR')

        page.fill('#id_positionen-4-zuschlag_auf', '02')
        expect(zuschlag).to_have_text('1,52 EUR')     # 50,50 x 3 % = 1,515

        page.fill('#id_positionen-3-menge', '2')
        expect(zuschlag).to_have_text('3,03 EUR')     # 101,00 x 3 %

        page.check('#id_positionen-3-optional')
        expect(zuschlag).to_have_text('0,00 EUR')
        page.uncheck('#id_positionen-3-optional')

        page.fill('#id_positionen-4-zuschlag_prozent', '2.5')
        expect(zuschlag).to_have_text('2,53 EUR')     # 101,00 x 2,5 % = 2,525

        page.fill('#id_positionen-4-zuschlag_auf', '01')
        expect(zuschlag).to_have_text('2,50 EUR')     # 100,00 x 2,5 %

    def test_angezeigt_ist_was_der_server_speichert(self, live_server, page,
                                                    angebot):
        TestPositionenDarstellung()._oeffnen(page, live_server, angebot)
        page.fill('#id_positionen-4-zuschlag_auf', '02')
        page.fill('#id_positionen-3-menge', '3')
        angezeigt = self._betrag(page, 4).inner_text()

        page.locator('button[name="_continue"]').click()
        page.wait_for_load_state('networkidle')

        gespeichert = angebot.positionen.get(position='04').einzelpreis
        assert angezeigt == f'{gespeichert:.2f} EUR'.replace('.', ',')
        assert gespeichert == Decimal('4.55')          # 151,50 x 3 % = 4,545
        expect(self._betrag(page, 4)).to_have_text(angezeigt)


@pytest.mark.django_db(transaction=True)
class TestKatalogsucheNurAnNeuenZeilen:
    """Die Katalogsuche steht nur über neuen Zeilen.

    Eine gespeicherte Position wird durch Löschen und Neuwahl ersetzt.
    Verworfen: ein Button zum Aufklappen der Suche (erprobt)."""

    @pytest.fixture
    def katalog(self, db):
        return Katalogposition.objects.create(
            nummer='E-210', bezeichnung='Unterverteilung setzen',
            langtext='Aufputz, bis 24 Module, inkl. Hutschiene',
            einheit='Stk', einzelpreis=Decimal('340.00'))

    @staticmethod
    def _suche(page, nummer):
        return page.locator(
            f'tbody.form-group:has(#id_positionen-{nummer}-bezeichnung) '
            f'.erste-zeile-feld.field-katalog')

    def test_gespeichert_ohne_neu_mit(self, live_server, page, chefin,
                                      kunde):
        beleg = _beleg_mit_fuenf_positionen(kunde, BelegTyp.RECHNUNG)
        TestPositionenDarstellung()._oeffnen(page, live_server, beleg)

        expect(self._suche(page, 0)).to_be_hidden()
        expect(self._suche(page, 4)).to_be_hidden()
        # Die leere Zeile darunter ist neu und hat die Suche.
        expect(self._suche(page, 5)).to_be_visible()

    def test_die_neue_zeile_unter_gespeicherten_fuellt_sich(
            self, live_server, page, chefin, kunde, katalog):
        beleg = _beleg_mit_fuenf_positionen(kunde, BelegTyp.RECHNUNG)
        TestPositionenDarstellung()._oeffnen(page, live_server, beleg)

        _katalog_waehlen(page, 5, 'E-210', 'Unterverteilung')

        expect(page.locator('#id_positionen-5-bezeichnung')).to_have_value(
            'Unterverteilung setzen')
        expect(page.locator('#id_positionen-4-bezeichnung')).to_have_value(
            'Entsorgung')

    def test_auch_der_lieferschein(self, live_server, page, chefin, kunde):
        beleg = _entwurf(kunde, typ=BelegTyp.LIEFERSCHEIN)
        TestPositionenDarstellung()._oeffnen(page, live_server, beleg)

        expect(self._suche(page, 0)).to_be_hidden()
        expect(self._suche(page, 1)).to_be_visible()


@pytest.mark.django_db(transaction=True)
class TestSpaltenkoepfe:
    """Spaltenköpfe: Pos. und Bezeichnung linksbündig, Zahlen rechtsbündig;
    Kopf, BT-Nummer und Wert übereinander."""

    def test_kopf_und_wert_stehen_rechts_uebereinander(
            self, live_server, page, chefin, kunde):
        page.set_viewport_size({'width': 1600, 'height': 900})
        beleg = _beleg_mit_fuenf_positionen(kunde, BelegTyp.RECHNUNG)
        TestPositionenDarstellung()._oeffnen(page, live_server, beleg)

        for spalte in ('menge', 'einheit', 'einzelpreis', 'steuersatz'):
            kopf = page.locator(f'th.column-{spalte} > span > span').first
            bt = page.locator(f'th.column-{spalte} .pw-bt').first
            feld = page.locator(f'#id_positionen-0-{spalte}')
            rechts = [ort['x'] + ort['width'] for ort in (
                kopf.bounding_box(), bt.bounding_box(), feld.bounding_box())]
            assert max(rechts) - min(rechts) <= 2, (spalte, rechts)

        # Pos. bleibt links.
        pos_kopf = page.locator(
            'th.column-position > span > span').first.bounding_box()['x']
        pos_feld = page.locator('#id_positionen-0-position').bounding_box()['x']
        assert abs(pos_kopf - pos_feld) <= 2

    def test_das_sternchen_steht_neben_der_beschriftung(
            self, live_server, page, chefin, kunde):
        beleg = _beleg_mit_fuenf_positionen(kunde, BelegTyp.RECHNUNG)
        TestPositionenDarstellung()._oeffnen(page, live_server, beleg)

        kopf = page.locator('th.column-menge > span > span').first
        stern = kopf.locator('span.text-red-600')
        bt = kopf.locator('.pw-bt')

        # In der Zeile des Labels, nicht in einer dritten unter der
        # BT-Nummer.
        assert stern.bounding_box()['y'] < bt.bounding_box()['y']
        # Preis und Bezeichnung sind Pflicht, obwohl das Feld in Django
        # optional ist (clean() verlangt sie nach der Katalogübernahme).
        for spalte in ('bezeichnung', 'einzelpreis', 'menge', 'steuersatz'):
            expect(page.locator(f'th.column-{spalte} span.text-red-600')
                   ).to_have_count(1)
        expect(page.locator('th.column-einheit span.text-red-600')
               ).to_have_count(0)
        expect(page.locator('th.column-einzelpreis')).to_contain_text(
            'Preis (Netto)')
        expect(page.locator('th.column-steuersatz')).to_contain_text('USt.')
        expect(page.locator('th.column-zeilensumme')).to_contain_text('Betrag')

    def test_pos_menge_und_preis_ohne_pfeilchen(self, live_server, page, chefin,
                                            kunde):
        beleg = _beleg_mit_fuenf_positionen(kunde, BelegTyp.RECHNUNG)
        TestPositionenDarstellung()._oeffnen(page, live_server, beleg)

        for feld in ('menge', 'einzelpreis'):
            darstellung = page.locator(f'#id_positionen-0-{feld}').evaluate(
                'el => getComputedStyle(el).appearance')
            assert darstellung == 'textfield', feld
        # Textfeld ("01.01.0010"), daher ohne Spinner.
        expect(page.locator('#id_positionen-0-position')).to_have_attribute(
            'type', 'text')


@pytest.mark.django_db(transaction=True)
class TestWerteInDerMaske:
    """Die Formatierung im Feld ändert die Werte nicht.

    Die Menge steht ohne nachlaufende Nullen im Feld ("6"); der gesendete
    Wert muss zum gespeicherten Wert parsen, damit Speichern ohne Änderung
    die Summe nicht ändert."""

    @pytest.fixture
    def rechnung(self, kunde):
        beleg = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Mengen',
            leistungsdatum=date(2026, 8, 1))
        for bezeichnung, menge, preis in (
                ('Ingenieurstunde', '6', '95.00'),
                ('Ortstermin', '1.5', '640.00'),
                ('Kabel', '1200', '1.25'),
                ('Kleinteile', '0.125', '1450.00')):
            services.position_hinzufuegen(
                beleg=beleg, bezeichnung=bezeichnung, menge=Decimal(menge),
                einheit='Stk', einzelpreis=Decimal(preis),
                steuersatz='19.00')
        return beleg

    @staticmethod
    def _stand(beleg):
        return [(p.position, p.menge, p.einzelpreis, p.steuersatz,
                 services.positionssumme(menge=p.menge,
                                         einzelpreis=p.einzelpreis))
                for p in beleg.positionen.order_by('position')]

    def test_im_feld_ohne_ueberfluessige_nullen(self, live_server, page,
                                                 chefin, rechnung):
        TestPositionenDarstellung()._oeffnen(page, live_server, rechnung)

        werte = [page.locator(f'#id_positionen-{i}-menge').input_value()
                 for i in range(4)]

        assert werte == ['6', '1.5', '1200', '0.125']
        # Auch der Default der leeren Zeile: "1", nicht "1.000".
        assert page.locator('#id_positionen-4-menge').input_value() == '1'

    def test_unveraendert_gesichert_bleibt_alles_gleich(
            self, live_server, page, chefin, rechnung):
        vorher = self._stand(rechnung)
        TestPositionenDarstellung()._oeffnen(page, live_server, rechnung)

        page.locator('button[name="_continue"]').click()
        page.wait_for_load_state('networkidle')

        expect(page.locator('.errorlist')).to_have_count(0)
        assert self._stand(rechnung) == vorher
        assert [p.menge for p in rechnung.positionen.order_by('position')] \
            == [Decimal('6'), Decimal('1.5'), Decimal('1200'),
                Decimal('0.125')]

    def test_nur_zum_lesen_wie_auf_dem_blatt(self, live_server, page,
                                             chefin, kunde):
        beleg = services.beleg_festschreiben(beleg_id=(
            _beleg_mit_fuenf_positionen(kunde, BelegTyp.ANGEBOT)).pk)
        TestPositionenDarstellung()._oeffnen(page, live_server, beleg)

        zeile = page.locator('tr.form-row').nth(1)

        expect(zeile.locator('td.field-menge')).to_have_text('1')
        expect(zeile.locator('td.field-einzelpreis')).to_have_text('1.450,00')
        expect(zeile.locator('td.field-steuersatz')).to_have_text('19 %')
        expect(page.locator('tr.form-row').first.locator(
            'td.field-menge')).to_have_text('40')


@pytest.mark.django_db(transaction=True)
class TestDieOptik:
    """Browserseitige Teile der Oberfläche: Skript, Tab, Suche."""

    @pytest.fixture
    def rechnung(self, kunde):
        """Rechnung über 12.400 netto im laufenden Monat, damit die Achse des
        Controlling-Verlaufs über 10.000 reicht."""
        beleg = _entwurf(kunde, typ=BelegTyp.RECHNUNG)
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Material', menge=Decimal('1'),
            einheit='psch', einzelpreis=Decimal('9920.00'),
            steuersatz='19.00')
        return services.beleg_festschreiben(beleg_id=beleg.pk)

    def test_die_achse_des_controllings_schreibt_deutsch(
            self, live_server, page, chefin, rechnung):
        """Die Achse formatiert deutsch (core/static/core/js/diagramme.js);
        Unfold allein schrieb "10000 €"."""
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/controlling/')
        page.wait_for_load_state('networkidle')

        beschriftungen = page.evaluate(
            "() => Object.values(Chart.instances)"
            ".filter(c => c.config.type === 'bar')"
            ".flatMap(c => c.scales.y.ticks.map(t => t.label))")

        assert any(re.fullmatch(r'\d{1,3}\.\d{3} €', b) for b in beschriftungen), \
            beschriftungen

    def test_der_reiter_ueber_frist_filtert(self, live_server, page, chefin,
                                            rechnung):
        Beleg.objects.filter(pk=rechnung.pk).update(faellig_am=date(2026, 1, 1))
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/faktura/rechnung/')
        page.wait_for_load_state('networkidle')

        page.get_by_role('link', name='Über Frist', exact=True).click()
        page.wait_for_load_state('networkidle')

        assert 'zahlungsstand=ueberfaellig' in page.url
        expect(page.locator('#result_list tbody tr')).to_have_count(1)

    def test_die_schnellsuche_fuehrt_in_die_kundenakte(
            self, live_server, page, chefin, kunde):
        _anmelden(page, live_server.url)

        page.keyboard.press('Control+k')
        feld = page.get_by_placeholder('Suchen …').last
        feld.wait_for(state='visible', timeout=5000)
        # Mit type(), weil die Command Palette bei Keystrokes sucht und
        # fill() keinen Request auslöste.
        feld.press_sequentially('isartal', delay=50)
        treffer = page.get_by_text('K-1001 · Wohnbau Isartal eG')
        treffer.wait_for(timeout=5000)
        treffer.click()
        page.wait_for_load_state('networkidle')

        assert page.url.endswith(f'/admin/faktura/kontakt/{kunde.pk}/akte/')
