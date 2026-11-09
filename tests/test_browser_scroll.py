"""Scroll-Position nach dem Speichern einer Admin-Maske."""

from datetime import date
from decimal import Decimal

import pytest

from faktura import services
from faktura.models import BelegTyp
from tests.browserhilfen import _anmelden

POSITION = 600


@pytest.fixture
def maske(live_server, page, chefin, kunde):
    beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG,
                                   betreff='Lang',
                                   leistungsdatum=date(2026, 10, 1))
    for nummer in range(1, 31):
        services.position_hinzufuegen(
            beleg=beleg, position=str(nummer), bezeichnung=f'Zeile {nummer}',
            menge=Decimal('1'), einheit='Std', einzelpreis=Decimal('10.00'),
            steuersatz='19.00')
    page.set_viewport_size({'width': 1280, 'height': 700})
    _anmelden(page, live_server.url)
    adresse = f'{live_server.url}/admin/faktura/rechnung/{beleg.pk}/change/'
    page.goto(adresse)
    page.wait_for_load_state('load')
    page.evaluate(f'window.scrollTo(0, {POSITION})')
    return adresse


def _speichern(page):
    with page.expect_navigation(wait_until='load'):
        page.locator('[name="_continue"]').click()


def _position(page) -> float:
    return page.evaluate('window.scrollY')


@pytest.mark.django_db(transaction=True)
class TestScrollNachDemSpeichern:

    def test_bleibt_an_der_stelle(self, page, maske):
        _speichern(page)

        assert page.url.split('?')[0] == maske
        assert abs(_position(page) - POSITION) < 5

    def test_erstes_speichern_bleibt_an_der_stelle(self, page, maske):
        """Der Redirect von ``/add/`` auf die Änderungsmaske, nachgestellt
        über den abgelegten Ausgangspfad."""
        page.evaluate('''() => window.addEventListener('submit', () => {
            sessionStorage.setItem('pw-scroll-nach-speichern', JSON.stringify(
                {pfad: '/admin/faktura/rechnung/add/', y: window.scrollY}));
        })''')

        _speichern(page)

        assert abs(_position(page) - POSITION) < 5

    def test_validierungsfehler_steht_oben(self, page, maske):
        page.evaluate('''() => {
            document.querySelector('form.warn-unsaved-form').noValidate = true;
            document.querySelector('[name="positionen-0-menge"]').value = '';
        }''')

        _speichern(page)

        assert _position(page) == 0

    def test_neu_geoeffnet_steht_oben(self, page, maske):
        _speichern(page)

        page.goto(maske)
        page.wait_for_load_state('load')

        assert _position(page) == 0
