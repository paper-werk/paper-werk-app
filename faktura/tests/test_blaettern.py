"""Blättern an Belegen und Akten, Listenfilter nach Detailaktionen
(``core/blaettern.py``)."""

from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from django.urls import reverse

from faktura import services
from faktura.models import BelegStatus, BelegTyp, Kontakt

FILTER = 'status__exact=entwurf'


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(nummer='K-4000', name='Muster GmbH',
                           strasse='Hauptstraße 1', plz='10115', ort='Berlin')


def _beleg(kunde, typ=BelegTyp.AUFTRAG, festschreiben=False):
    beleg = services.beleg_anlegen(kunde=kunde, typ=typ, betreff='Planung',
                                   leistungsdatum=date(2026, 10, 1))
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Planung', menge=Decimal('1'),
        einzelpreis=Decimal('100.00'), steuersatz='19.00')
    if festschreiben:
        beleg = services.beleg_festschreiben(beleg_id=beleg.pk)
    return beleg


def _mit_filter(adresse):
    return f'{adresse}?{urlencode({"_changelist_filters": FILTER})}'


def _filter_in(url):
    return parse_qs(urlparse(url).query).get('_changelist_filters')


@pytest.mark.django_db
class TestDetailaktionenBehaltenDenFilter:
    """Nach einer Detailaktion führt "Sichern" in die gefilterte Liste
    zurück."""

    def test_die_aktionen_tragen_den_filter(self, admin_client, kunde):
        auftrag = _beleg(kunde)

        seite = admin_client.get(_mit_filter(
            reverse('admin:faktura_auftrag_change', args=[auftrag.pk])))

        pfade = [a['path'] for a in seite.context['actions_detail']
                 if 'path' in a]
        pfade += [e['path'] for a in seite.context['actions_detail']
                  for e in a.get('items', [])]
        assert pfade
        assert all(_filter_in(p) == [FILTER] for p in pfade), pfade

    def test_der_ruecksprung_traegt_den_filter(self, admin_client, kunde):
        auftrag = _beleg(kunde)

        antwort = admin_client.post(_mit_filter(
            reverse('admin:faktura_auftrag_detail_festschreiben',
                    args=[auftrag.pk])))

        auftrag.refresh_from_db()
        assert auftrag.status == BelegStatus.FESTGESCHRIEBEN
        assert urlparse(antwort['Location']).path == reverse(
            'admin:faktura_auftrag_change', args=[auftrag.pk])
        assert _filter_in(antwort['Location']) == [FILTER]


@pytest.mark.django_db
class TestBlaetternAmBeleg:

    def test_vom_ersten_zum_zweiten_entwurf(self, admin_client, kunde):
        erster, zweiter = _beleg(kunde), _beleg(kunde)
        _beleg(kunde, festschreiben=True)
        admin_client.get(
            f'{reverse("admin:faktura_auftrag_changelist")}?{FILTER}&o=-1')

        # Absteigend nach Bezeichnung: der jüngere Entwurf zuerst.
        pfeile = admin_client.get(_mit_filter(reverse(
            'admin:faktura_auftrag_change', args=[zweiter.pk]))
        ).context['blaettern']

        assert pfeile['anzahl'] == 2
        assert urlparse(pfeile['weiter']).path == reverse(
            'admin:faktura_auftrag_change', args=[erster.pk])
