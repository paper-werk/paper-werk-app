"""Absenderzeile über dem Anschriftfeld (Issue #45).

Das PDF druckt ``Firma.absenderzeile`` unverändert; Briefkopf und Fußzeile
behalten Name und Zusatz.
"""

import importlib

import pytest
from django.apps import apps

from faktura import pdf, services
from faktura.models import BelegTyp, Firma, Kontakt

pytestmark = pytest.mark.django_db


@pytest.fixture
def rechnung():
    kunde = Kontakt.anlegen(
        nummer='K-4500', name='Stadtwerke Muster', strasse='Werkstraße 1',
        plz='84028', ort='Landshut')
    return services.beleg_anlegen(
        kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Absender')


def _ruecksendeangabe(html: str) -> str:
    anfang = html.index('class="ruecksendeangabe">') + len('class="ruecksendeangabe">')
    return html[anfang:html.index('</div>', anfang)]


def test_pdf_druckt_absenderzeile_unveraendert(firma, rechnung):
    firma.zusatz = 'Ingenieurbüro für Umwelt- und Geotechnik'
    firma.absenderzeile = 'Amper GmbH · Postfach 12 · 80331 München'
    firma.save()

    html = pdf.beleg_als_html(rechnung)

    assert _ruecksendeangabe(html) == 'Amper GmbH · Postfach 12 · 80331 München'
    assert 'Werkstatt Amper GmbH' in html
    assert 'Ingenieurbüro für Umwelt- und Geotechnik' in html


def test_leere_absenderzeile_bleibt_leer(firma, rechnung):
    assert firma.absenderzeile == ''

    assert _ruecksendeangabe(pdf.beleg_als_html(rechnung)) == ''


def test_migration_befuellt_bestehende_firma(firma):
    migration = importlib.import_module(
        'faktura.migrations.0057_firma_absenderzeile')

    migration.befuellen(apps, None)

    firma.refresh_from_db()
    assert firma.absenderzeile == (
        'Werkstatt Amper GmbH - Musterweg 12 - 80331 München')


def test_migration_ueberschreibt_gefuellte_zeile_nicht(firma):
    Firma.objects.update(absenderzeile='Amper GmbH · München')
    migration = importlib.import_module(
        'faktura.migrations.0057_firma_absenderzeile')

    migration.befuellen(apps, None)

    firma.refresh_from_db()
    assert firma.absenderzeile == 'Amper GmbH · München'
