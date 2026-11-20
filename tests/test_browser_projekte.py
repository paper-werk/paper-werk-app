"""Browsertests der Projekte: Abschließen in Maske und Liste."""

import pytest

from core.adminhilfen import WEITERE
from faktura.models import Projekt
from tests.browserhilfen import _anmelden, _knopf, _menue


@pytest.mark.django_db(transaction=True)
class TestProjektAbschliessen:

    def test_abschliessen_und_wieder_oeffnen_in_der_maske(
            self, live_server, page, chefin, kunde):
        projekt = Projekt.objects.create(
            nummer='2026-001', bezeichnung='Ludwigsplatz 9', kunde=kunde)
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/faktura/projekt/'
                  f'{projekt.pk}/change/')

        _menue(page, WEITERE)
        _knopf(page, '/abschliessen/').click()
        page.wait_for_load_state('networkidle')
        projekt.refresh_from_db()
        assert projekt.abgeschlossen

        _menue(page, WEITERE)
        _knopf(page, '/oeffnen/').click()
        page.wait_for_load_state('networkidle')
        projekt.refresh_from_db()
        assert not projekt.abgeschlossen

    def test_abschliessen_in_der_liste(self, live_server, page, chefin, kunde):
        projekt = Projekt.objects.create(
            nummer='2026-001', bezeichnung='Ludwigsplatz 9', kunde=kunde)
        _anmelden(page, live_server.url)
        page.goto(f'{live_server.url}/admin/faktura/projekt/')

        page.check('#action-toggle')
        page.select_option('select[name="action"]', 'action_abschliessen')
        page.locator('button[name="index"]').click()
        page.wait_for_load_state('networkidle')

        projekt.refresh_from_db()
        assert projekt.abgeschlossen
