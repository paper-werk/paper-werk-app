"""Die Positionsnummer bleibt über die Belegkette erhalten.

Eine "2.1" im Angebot bleibt "2.1" im Auftrag und in jeder Rechnung
daraus. Den Weg über die Leistungserfassung prüft
``erfassung/tests/test_positionsnummer_kette.py``, den über die Abschläge in die
Schlussrechnung ``test_schluss_leistung.py``.
"""

from datetime import date
from decimal import Decimal

import pytest

from faktura import services
from faktura.models import (
    Abnahme,
    Abnahmeart,
    BelegTyp,
    Kontakt,
    Projekt,
    Rechnungsart,
)

LV = ['1', '2.1', '2.2', '10.01.0010']


@pytest.fixture
def projekt(db):
    kunde = Kontakt.anlegen(
        nummer='K-3000', name='Beispiel AG', strasse='Industriestraße 5',
        plz='90402', ort='Nürnberg')
    return Projekt.objects.create(
        nummer='2026-031', bezeichnung='Kläranlage Nord', kunde=kunde)


def _mit_lv(beleg):
    for nummer in LV:
        services.position_hinzufuegen(
            beleg=beleg, position=nummer, bezeichnung=f'Position {nummer}',
            menge=Decimal('1'), einheit='pausch',
            einzelpreis=Decimal('1000.00'), steuersatz='19.00')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


def _nummern(beleg):
    return list(beleg.positionen.values_list('position', flat=True))


@pytest.fixture
def angebot(projekt):
    return _mit_lv(services.beleg_anlegen(
        projekt=projekt, typ=BelegTyp.ANGEBOT, betreff='Planung'))


@pytest.fixture
def auftrag(angebot):
    entwurf = services.beleg_umwandeln(beleg_id=angebot.pk,
                                       neuer_typ=BelegTyp.AUFTRAG)
    return services.beleg_festschreiben(beleg_id=entwurf.pk)


def test_angebot_auftrag_rechnung(auftrag):
    rechnung = services.beleg_umwandeln(beleg_id=auftrag.pk,
                                        neuer_typ=BelegTyp.RECHNUNG)

    assert _nummern(auftrag) == LV
    assert _nummern(rechnung) == LV


def test_teilschluss_aus_teilabnahme(auftrag):
    """Die Teilschlussrechnung übernimmt die Nummern aus dem Auftrag; die
    Schlussrechnung aus der Gesamtabnahme übernimmt die Leistung aus den
    Abschlägen (siehe Modul-Docstring)."""
    abnahme = Abnahme.objects.create(auftrag=auftrag, art=Abnahmeart.TEIL,
                                     abgenommen_am=date(2026, 10, 1))
    abnahme.positionen.add(*auftrag.positionen.all())

    rechnung = services.rechnung_aus_abnahme(abnahme_id=abnahme.pk)

    assert rechnung.rechnungsart == Rechnungsart.TEILSCHLUSS
    assert _nummern(rechnung) == LV
