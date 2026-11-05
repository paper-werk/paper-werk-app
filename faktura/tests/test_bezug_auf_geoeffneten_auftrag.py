"""Bezug einer Rechnungsposition auf einen wieder geöffneten Auftrag.

Neu gesetzt wird ein Bezug nur auf einen festgeschriebenen Auftrag. Ein
gespeicherter Bezug bleibt gültig, wenn der Auftrag danach wieder geöffnet
wird; die Rechnung lässt sich weiter speichern. Regression: Das Speichern
endete mit einem Serverfehler, weil ``Belegposition.clean`` den Bezug neu
prüfte und das Formular kein Feld ``auftragsposition`` hat.
"""

from decimal import Decimal
from html.parser import HTMLParser

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from faktura import services
from faktura.models import Belegposition, BelegTyp, Projekt

pytestmark = pytest.mark.django_db


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(nummer='2026-050', bezeichnung='Halle',
                                  kunde=kunde)


@pytest.fixture
def auftragsposition(projekt):
    auftrag = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.AUFTRAG)
    position = services.position_hinzufuegen(
        beleg=auftrag, position='2.20', bezeichnung='Bodenprobe',
        menge=Decimal('40'), einheit='Stk', einzelpreis=Decimal('145.00'),
        steuersatz='19.00')
    services.beleg_festschreiben(beleg_id=auftrag.pk)
    return Belegposition.objects.get(pk=position.pk)


@pytest.fixture
def rechnung(projekt, auftragsposition):
    beleg = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.RECHNUNG)
    services.position_hinzufuegen(
        beleg=beleg, position='2.20', bezeichnung='Bodenprobe',
        menge=Decimal('3'), einheit='Stk', einzelpreis=Decimal('145.00'),
        steuersatz='19.00', auftragsposition=auftragsposition)
    return beleg


def test_gespeicherter_bezug_bleibt_gueltig(rechnung, auftragsposition):
    """``clean`` statt ``full_clean``: Das Formular hat kein Feld
    ``auftragsposition``, dessen ``limit_choices_to`` zählt dort nicht."""
    services.beleg_wiedereroeffnen(beleg_id=auftragsposition.beleg_id)

    rechnung.positionen.get().clean()


def test_neuer_bezug_auf_einen_entwurf_wird_abgewiesen(
        rechnung, auftragsposition):
    services.beleg_wiedereroeffnen(beleg_id=auftragsposition.beleg_id)
    neu = Belegposition(
        beleg=rechnung, position='2.30', bezeichnung='Bodenprobe',
        menge=Decimal('1'), einheit='Stk', einzelpreis=Decimal('145.00'),
        steuersatz='19.00', auftragsposition=auftragsposition)

    with pytest.raises(ValidationError, match='noch ein Entwurf'):
        neu.full_clean()


def test_die_rechnung_laesst_sich_speichern(admin_client, rechnung,
                                            auftragsposition):
    services.beleg_wiedereroeffnen(beleg_id=auftragsposition.beleg_id)
    adresse = reverse('admin:faktura_rechnung_change', args=[rechnung.pk])
    daten = _formular(admin_client.get(adresse).content.decode())
    daten['_continue'] = '1'

    antwort = admin_client.post(adresse, daten)

    assert antwort.status_code == 302


class _Formular(HTMLParser):
    """Werte eines HTML-Formulars, wie der Browser sie sendet."""

    def __init__(self):
        super().__init__()
        self.daten, self._select, self._textarea = {}, None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        name = a.get('name')
        if tag == 'input' and name and a.get('type') not in (
                'submit', 'button', 'file'):
            if a.get('type') in ('checkbox', 'radio') and 'checked' not in a:
                return
            self.daten[name] = a.get('value', '')
        elif tag == 'select' and name:
            self._select = name
            self.daten.setdefault(name, '')
        elif tag == 'option' and self._select and 'selected' in a:
            self.daten[self._select] = a.get('value', '')
        elif tag == 'textarea' and name:
            self._textarea = name
            self.daten[name] = ''

    def handle_endtag(self, tag):
        if tag == 'select':
            self._select = None
        elif tag == 'textarea':
            self._textarea = None

    def handle_data(self, data):
        if self._textarea:
            self.daten[self._textarea] += data


def _formular(html: str) -> dict:
    leser = _Formular()
    leser.feed(html)
    return leser.daten
