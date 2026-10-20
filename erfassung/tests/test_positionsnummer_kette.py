"""Erfasste Leistung auf eine Auftragsposition trägt deren Nummer in die
Rechnung. Die Wege in der Faktura prüft
``faktura/tests/test_positionsnummer_kette.py``."""

from datetime import date, time
from decimal import Decimal

import pytest

from erfassung import services
from erfassung.models import Eingangsrechnung, Erfassungszeile, Fremdleistung
from faktura import services as faktura_services
from faktura.models import (
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Kontakt,
    Leistungsart,
    Rechnungsart,
)


@pytest.fixture
def lv(projekt):
    """Ein festgeschriebener Auftrag mit LV-Nummern. Über ``bulk_create``
    wie ``auftragsposition`` in der conftest."""
    auftrag = Beleg.objects.create(
        typ=BelegTyp.AUFTRAG, status=BelegStatus.FESTGESCHRIEBEN,
        nummer='AU-2026-0011', projekt=projekt)
    planung, proben = Belegposition.objects.bulk_create([
        Belegposition(beleg=auftrag, position='2.1', bezeichnung='Planung',
                      menge=Decimal('100'), einheit='Std',
                      einzelpreis=Decimal('95.00'), steuersatz='19.00',
                      art=Leistungsart.ZEIT),
        Belegposition(beleg=auftrag, position='2.2',
                      bezeichnung='Bodenprobe', menge=Decimal('40'),
                      einheit='Stk', einzelpreis=Decimal('145.00'),
                      steuersatz='19.00', art=Leistungsart.MENGE),
    ])
    return planung, proben


def _zeiten(projekt, auftragsposition, benutzer):
    services.zeile_erfassen(
        projekt=projekt, auftragsposition=auftragsposition, benutzer=benutzer,
        von=time(8, 0), bis=time(12, 0), beschreibung='Entwurf')
    return Erfassungszeile.objects.all()


def _fremdleistung(projekt, auftragsposition):
    labor = Kontakt.objects.create(name='Labor', ist_kunde=False,
                                   ist_lieferant=True)
    rechnung = Eingangsrechnung.objects.create(
        lieferant=labor, nummer='RE-1', datum=date(2026, 9, 1),
        betrag_netto=Decimal('96.00'))
    Fremdleistung.objects.create(
        rechnung=rechnung, projekt=projekt, bezeichnung='Paket 4711',
        menge=Decimal('1'), einheit='Stk', einkaufspreis=Decimal('96.00'),
        auftragsposition=auftragsposition)
    return Fremdleistung.objects.all()


@pytest.mark.parametrize('art', [Rechnungsart.NORMAL, Rechnungsart.ABSCHLAG,
                                 Rechnungsart.SCHLUSS])
def test_zeiten_und_fremdleistung_behalten_die_nummer(
        projekt, lv, kollege, art):
    planung, proben = lv

    beleg, _ = services.in_rechnung_uebernehmen(
        zeilen=_zeiten(projekt, planung, kollege),
        fremdleistungen=_fremdleistung(projekt, proben), rechnungsart=art)

    assert sorted(beleg.positionen.values_list('position', flat=True)) \
        == ['2.1', '2.2']


def test_vergebene_nummer_im_entwurf_wird_nicht_doppelt_vergeben(
        projekt, lv, kollege):
    planung, _ = lv
    entwurf = faktura_services.beleg_anlegen(
        projekt=projekt, typ=BelegTyp.RECHNUNG)
    faktura_services.position_hinzufuegen(
        beleg=entwurf, position='2.1', bezeichnung='Von Hand',
        menge=Decimal('1'), einzelpreis=Decimal('10.00'), steuersatz='19.00')

    services.in_rechnung_uebernehmen(
        zeilen=_zeiten(projekt, planung, kollege), beleg=entwurf)

    nummern = list(entwurf.positionen.values_list('position', flat=True))
    assert len(nummern) == len(set(nummern)) == 2
