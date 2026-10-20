"""Browsertests der Belegabläufe: Festschreiben, Dokument, Belegkette, Blättern, Zahlung."""

import re
from decimal import Decimal

import pytest
from playwright.sync_api import expect

from core.adminhilfen import WEITERE
from faktura import services
from faktura.models import (
    Beleg,
    BelegStatus,
    BelegTyp,
)
from tests.browserhilfen import _anmelden, _bestaetigen, _entwurf, _knopf, _menue


@pytest.mark.django_db(transaction=True)
class TestFestschreiben:
    """Button "Festschreiben"."""

    def test_der_knopf_vergibt_wirklich_eine_nummer(
            self, live_server, page, chefin, kunde):
        """Der Klick vergibt eine Nummer; ein Test am HTML wäre auch ohne
        Wirkung grün."""
        beleg = _entwurf(kunde)
        assert not beleg.nummer

        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}'
                  f'/admin/faktura/auftrag/{beleg.pk}/change/')
        _knopf(page, f'/auftrag/{beleg.pk}/festschreiben/').click()
        page.wait_for_load_state('networkidle')
        _bestaetigen(page, 'Festschreiben')

        beleg.refresh_from_db()
        assert beleg.status == BelegStatus.FESTGESCHRIEBEN, (
            f'nach dem Klick immer noch {beleg.status}')
        assert beleg.nummer.startswith('AU-2026-'), beleg.nummer

    def test_danach_ist_der_knopf_weg(self, live_server, page, chefin, kunde):
        """Danach fehlt der Button, weil Festschreiben nicht wiederholbar
        ist."""
        beleg = _entwurf(kunde)

        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}'
                  f'/admin/faktura/auftrag/{beleg.pk}/change/')
        _knopf(page, f'/auftrag/{beleg.pk}/festschreiben/').click()
        page.wait_for_load_state('networkidle')
        _bestaetigen(page, 'Festschreiben')

        assert page.locator(
            f'a[href*="/auftrag/{beleg.pk}/festschreiben/"]').count() == 0


@pytest.mark.django_db(transaction=True)
class TestWiedereroeffnen:
    """Wiedereröffnen setzt den Beleg in den Entwurf zurück, **die Nummer
    bleibt**; ohne dritten Zustand."""

    def test_der_auftrag_geht_zurueck_in_den_entwurf(
            self, live_server, page, chefin, kunde):
        beleg = services.beleg_festschreiben(beleg_id=_entwurf(kunde).pk)
        nummer_vorher = beleg.nummer
        assert nummer_vorher

        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}'
                  f'/admin/faktura/auftrag/{beleg.pk}/change/')
        _menue(page, WEITERE)
        _knopf(page, f'/auftrag/{beleg.pk}/wieder-oeffnen/').click()
        # Der Dialog wird per HTMX geladen; ohne Warten fehlt die
        # Bestätigung noch im DOM.
        page.get_by_text('Beleg wieder öffnen?').wait_for(timeout=5000)
        _bestaetigen(page, 'Wieder öffnen')

        beleg.refresh_from_db()
        assert beleg.status == BelegStatus.ENTWURF, (
            f'nach dem Wiedereröffnen {beleg.status}')
        assert beleg.nummer == nummer_vorher, (
            'Die Nummer muss bleiben; ein neuer Kreis wäre eine Lücke '
            'im alten')


@pytest.mark.django_db(transaction=True)
class TestDasDokument:
    def test_der_pdf_knopf_liefert_wirklich_ein_pdf(
            self, live_server, page, chefin, kunde):
        """Der Button liefert ein PDF: Statuscode, Content-Type und ``%PDF`` am
        Anfang, weil ein Link auf eine Fehlerseite im HTML gleich
        aussieht.
        """
        beleg = services.beleg_festschreiben(beleg_id=_entwurf(kunde).pk)

        _anmelden(page, live_server.url)
        antwort = page.request.get(
            f'{live_server.url}/admin/faktura/auftrag/{beleg.pk}/pdf-ansehen/')

        assert antwort.status == 200, antwort.status
        assert 'pdf' in antwort.headers.get('content-type', '').lower()
        assert antwort.body()[:4] == b'%PDF'

    def test_der_pdf_knopf_sichert_vorher(
            self, live_server, page, chefin, kunde):
        """Nach einer Änderung enthält das PDF aus "PDF anzeigen" die Änderung.

        Regression: Der Button öffnet einen neuen Tab, den
        ``aktion_erst_speichern.js`` ohne Speichern durchließ."""
        beleg = _entwurf(kunde)

        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/faktura/auftrag/{beleg.pk}/change/')
        page.fill('#id_betreff', 'Kurz vor dem PDF geändert')
        # Headless startet einen Download und bricht die Navigation des
        # Tabs ab; geprüft wird deshalb der Request.
        with page.context.expect_event(
                'request', lambda anfrage: 'pdf-ansehen' in anfrage.url
                and anfrage.method == 'GET', timeout=15000):
            with page.context.expect_page():
                _knopf(page, f'/auftrag/{beleg.pk}/pdf-ansehen/').click()
        page.wait_for_load_state('networkidle')

        beleg.refresh_from_db()
        assert beleg.betreff == 'Kurz vor dem PDF geändert'
        # Die Maske ist mit dem gespeicherten Stand neu geladen, weil das
        # nächste Speichern sonst an der alten Version scheiterte.
        assert page.input_value('#id_betreff') == 'Kurz vor dem PDF geändert'
        page.get_by_role('button', name='Sichern', exact=True).first.click()
        page.wait_for_load_state('networkidle')
        assert 'bereits geändert' not in page.content()


@pytest.mark.django_db(transaction=True)
class TestDieSeitenLaufen:
    """Die drei eigenen Seiten im Browser.

    JavaScript-Fehler fallen in HTML-Tests nicht auf (200, leeres
    ``<canvas>``). Der Test schlägt fehl, sobald die Browserkonsole einen
    Fehler meldet.
    """

    @pytest.mark.parametrize('pfad', [
        '/admin/',
        '/admin/controlling/',
        '/admin/nicht-abgerechnet/',
        '/admin/faktura/angebot/add/',
    ])
    def test_ohne_fehler_in_der_konsole(
            self, live_server, page, chefin, kunde, pfad):
        # Erst anmelden, dann die Konsole überwachen, weil der Redirect auf
        # LOGIN_REDIRECT_URL (Default /accounts/profile/) im Admin einen 404
        # ergibt, der nichts über die geprüfte Seite aussagt.
        _anmelden(page, live_server.url)

        fehler = []
        page.on('pageerror', lambda e: fehler.append(str(e)))
        page.on('console', lambda m: (
            fehler.append(m.text) if m.type == 'error' else None))

        antwort = page.goto(f'{live_server.url}{pfad}')
        page.wait_for_load_state('networkidle')

        assert antwort.status == 200, f'{pfad}: {antwort.status}'
        assert not fehler, f'{pfad}: {fehler[:3]}'


@pytest.mark.django_db(transaction=True)
class TestDieBelegkette:
    """Vom angenommenen Angebot zum Auftrag über den Button."""

    def test_aus_dem_angebot_wird_ein_auftrag(self, live_server, page, chefin,
                                             kunde):
        angebot = services.beleg_festschreiben(
            beleg_id=_entwurf(kunde, typ=BelegTyp.ANGEBOT).pk)

        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}'
                  f'/admin/faktura/angebot/{angebot.pk}/change/')
        _menue(page, WEITERE)
        _knopf(page, f'/angebot/{angebot.pk}/in-auftrag/').click()
        page.get_by_text('Auftrag aus diesem Angebot erzeugen?').wait_for(
            timeout=5000)
        _bestaetigen(page, 'Auftrag erzeugen')

        auftrag = Beleg.objects.get(typ=BelegTyp.AUFTRAG, vorgaenger=angebot)
        assert auftrag.status == BelegStatus.ENTWURF
        assert [(p.bezeichnung, p.menge) for p in auftrag.positionen.all()] \
            == [('Gesellenstunde', Decimal('40.000'))]


@pytest.mark.django_db(transaction=True)
class TestVerlaufInWeitere:
    """Verlauf als letzter Eintrag in "Weitere …"."""

    def test_aus_dem_menue_in_den_verlauf(self, live_server, page, chefin,
                                          kunde):
        auftrag = _entwurf(kunde)

        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}'
                  f'/admin/faktura/auftrag/{auftrag.pk}/change/')
        _menue(page, WEITERE)
        _knopf(page, f'/auftrag/{auftrag.pk}/verlauf/').click()

        page.wait_for_url(f'**/admin/faktura/auftrag/{auftrag.pk}/history/')


@pytest.mark.django_db(transaction=True)
class TestBlaettern:
    """Blättern: Liste mit Filter, Datensatz öffnen, mit "Weiter" zum
    nächsten (``core/blaettern.py``)."""

    LISTE = '/admin/faktura/auftrag/?status__exact=entwurf'

    def _liste(self, page, url):
        """Öffnet die gefilterte Liste und liefert die Belegnummern (pk) in
        ihrer Reihenfolge."""
        page.goto(f'{url}{self.LISTE}')
        hrefs = page.eval_on_selector_all(
            'a[href*="/admin/faktura/auftrag/"][href*="/change/"]',
            'links => links.map(a => a.getAttribute("href"))')
        pks = []
        for href in hrefs:
            pk = re.search(r'/auftrag/(\d+)/change/', href).group(1)
            if pk not in pks:
                pks.append(pk)
        return pks

    def _oeffnen(self, page, pk):
        page.locator(f'a[href*="/auftrag/{pk}/change/"]').first.click()
        page.wait_for_load_state('networkidle')

    def _weiter(self, page):
        page.locator('a[aria-label="Weiter"]').click()
        page.wait_for_load_state('networkidle')

    def test_weiter_fuehrt_zum_naechsten(self, live_server, page, chefin,
                                         kunde):
        for _ in range(3):
            _entwurf(kunde)
        _anmelden(page, live_server.url)
        pks = self._liste(page, live_server.url)
        assert len(pks) == 3

        self._oeffnen(page, pks[0])
        self._weiter(page)

        assert f'/auftrag/{pks[1]}/change/' in page.url
        expect(page.locator('[data-blaettern]')).to_contain_text('2 von 3')

    def test_nach_dem_festschreiben_zum_naechsten_entwurf(
            self, live_server, page, chefin, kunde):
        """Der festgeschriebene Beleg fällt aus dem Filter "Entwurf"; "Weiter"
        findet den nächsten, danach führt "Sichern" in die gefilterte
        Liste."""
        for _ in range(2):
            _entwurf(kunde)
        _anmelden(page, live_server.url)
        pks = self._liste(page, live_server.url)

        self._oeffnen(page, pks[0])
        _knopf(page, f'/auftrag/{pks[0]}/festschreiben/').click()
        page.wait_for_load_state('networkidle')
        _bestaetigen(page, 'Festschreiben')
        assert 'status__exact' in page.url
        self._weiter(page)

        assert f'/auftrag/{pks[1]}/change/' in page.url
        page.locator('button[name="_save"]').first.click()
        page.wait_for_load_state('networkidle')
        assert '/admin/faktura/auftrag/?' in page.url
        assert 'status__exact=entwurf' in page.url

    def test_ungesicherte_aenderung_loest_die_warnung_aus(
            self, live_server, page, chefin, kunde):
        for _ in range(2):
            _entwurf(kunde)
        _anmelden(page, live_server.url)
        pks = self._liste(page, live_server.url)
        self._oeffnen(page, pks[0])
        dialoge = []

        def ablehnen(dialog):
            dialoge.append(dialog.type)
            dialog.dismiss()

        page.on('dialog', ablehnen)
        page.fill('#id_betreff', 'Geändert, nicht gesichert')
        page.locator('a[aria-label="Weiter"]').click()
        page.wait_for_timeout(500)

        assert dialoge == ['beforeunload']
        assert f'/auftrag/{pks[0]}/change/' in page.url
        assert Beleg.objects.get(pk=pks[0]).betreff != (
            'Geändert, nicht gesichert')


@pytest.mark.django_db(transaction=True)
class TestAngebotDuplizieren:
    """Duplizieren über "Weitere …" und den Dialog bis zur Kopie."""

    def test_aus_dem_menue_in_die_kopie(self, live_server, page, chefin,
                                        kunde):
        angebot = services.beleg_festschreiben(
            beleg_id=_entwurf(kunde, typ=BelegTyp.ANGEBOT).pk)

        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}'
                  f'/admin/faktura/angebot/{angebot.pk}/change/')
        _menue(page, WEITERE)
        _knopf(page, f'/angebot/{angebot.pk}/duplizieren/').click()
        page.get_by_text('Angebot duplizieren?').wait_for(timeout=5000)
        _bestaetigen(page, 'Duplizieren')

        kopie = Beleg.objects.exclude(pk=angebot.pk).get(
            typ=BelegTyp.ANGEBOT)
        assert page.url.endswith(
            f'/admin/faktura/angebot/{kopie.pk}/change/')
        assert kopie.status == BelegStatus.ENTWURF
        assert [(p.bezeichnung, p.menge) for p in kopie.positionen.all()] \
            == [('Gesellenstunde', Decimal('40.000'))]


@pytest.mark.django_db(transaction=True)
class TestZahlungVermerken:
    """Der vorbelegte Betrag steht im Feld des Browsers.

    Regression: "2951,20" in einem ``<input type="number">`` verwarf der
    Browser, und das Feld blieb leer; ein Test auf ``form.initial`` war
    grün (faktura/forms.py, BetragWidget)."""

    @pytest.fixture
    def rechnung(self, kunde):
        return services.beleg_festschreiben(
            beleg_id=_entwurf(kunde, typ=BelegTyp.RECHNUNG).pk)

    def test_unveraendert_abgeschickt_ist_die_rechnung_bezahlt(
            self, live_server, page, chefin, rechnung):
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/faktura/rechnung/'
                  f'{rechnung.pk}/zahlung/')
        page.wait_for_load_state('networkidle')

        # 40 Std zu 62,00 netto, 19 %: 2.951,20 brutto.
        expect(page.locator('#id_betrag')).to_have_value('2951.20')

        page.locator('button[name="anwenden"]').click()
        page.wait_for_load_state('networkidle')

        assert services.offener_betrag(rechnung) == Decimal('0.00')
