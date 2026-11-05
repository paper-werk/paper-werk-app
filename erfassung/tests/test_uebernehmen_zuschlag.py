"""Übernahme in eine Rechnung: Zuschläge des Auftrags („Nebenkosten 3 %“).

Ein nicht optionaler Zuschlag des Auftrags kommt mit, wenn er sich auf eine
übernommene Position bezieht, einmal je Bezeichnung, mit dem Betrag auf die
Positionen der Rechnung. Gilt für jede Rechnungsart und für die
Schlussrechnung aus Abschlägen, auch wenn die Abschläge ihn nicht hatten.
"""

from datetime import date, time
from decimal import Decimal

import pytest

from erfassung import services
from erfassung.models import Erfassungszeile
from faktura import services as faktura_services
from faktura.models import (
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Firma,
    Leistungsart,
    Rechnungsart,
    Zeilenart,
)


@pytest.fixture(autouse=True)
def firma(db):
    """Firma für das PDF beim Festschreiben des Abschlags."""
    return Firma.objects.create(
        name='Werkstatt Amper GmbH', strasse='Musterweg 12', plz='80331',
        ort='München', email='post@example.de', steuernummer='143/815/47110',
        ust_id='DE123456789', iban='DE02120300000000202051',
        bic='BYLADEM1001')


@pytest.fixture
def lv(projekt):
    """Auftrag mit 2.10 (Zeit, 95 €/Std) und 2.20 (Stück, 145 €), dem
    Zuschlag 2.90 „Erschwernis“ 10 % auf 2.20 und auf alles „Nebenkosten“
    3 % (90) sowie optional „Samstag“ 50 % (91)."""
    auftrag = Beleg.objects.create(
        typ=BelegTyp.AUFTRAG, status=BelegStatus.FESTGESCHRIEBEN,
        nummer='AU-2026-0030', projekt=projekt)

    def zeile(position, bezeichnung, zeilenart=Zeilenart.LEISTUNG, **rest):
        rest.setdefault('menge', Decimal('1'))
        rest.setdefault('einzelpreis', Decimal('0'))
        return Belegposition(beleg=auftrag, position=position,
                             bezeichnung=bezeichnung, zeilenart=zeilenart,
                             steuersatz='19.00', **rest)

    def zuschlag(position, bezeichnung, prozent, auf='', **rest):
        return zeile(position, bezeichnung, Zeilenart.ZUSCHLAG,
                     zuschlag_prozent=Decimal(prozent), zuschlag_auf=auf,
                     **rest)

    angelegt = Belegposition.objects.bulk_create([
        zeile('2', 'Erkundung', Zeilenart.TITEL, menge=Decimal('0')),
        zeile('2.10', 'Probenahme', menge=Decimal('20'), einheit='Std',
              einzelpreis=Decimal('95.00'), art=Leistungsart.ZEIT),
        zeile('2.20', 'Bodenprobe', menge=Decimal('40'), einheit='Stk',
              einzelpreis=Decimal('145.00'), art=Leistungsart.MENGE),
        zuschlag('2.90', 'Erschwernis', '10', '2.20'),
        zuschlag('90', 'Nebenkosten', '3'),
        zuschlag('91', 'Samstag', '50', optional=True),
    ])
    return {p.position: p for p in angelegt}


def _stunden(projekt, kollege, auftragsposition, tag):
    """Zwei Stunden, 190 €."""
    return services.zeile_erfassen(
        projekt=projekt, auftragsposition=auftragsposition, benutzer=kollege,
        datum=date(2026, 10, tag), von=time(8, 0), bis=time(10, 0),
        beschreibung='Arbeit')


def _proben(projekt, kollege, auftragsposition, tag, menge):
    return services.zeile_erfassen(
        projekt=projekt, auftragsposition=auftragsposition, benutzer=kollege,
        datum=date(2026, 10, tag), menge=menge, beschreibung='Proben')


def _uebernehmen(zeilen, rechnung=None, **rest):
    beleg, _ = services.in_rechnung_uebernehmen(
        zeilen=Erfassungszeile.objects.filter(pk__in=[z.pk for z in zeilen]),
        beleg=rechnung, **rest)
    return beleg


def _zuschlaege(beleg):
    return [(p.position, p.bezeichnung, p.einzelpreis)
            for p in beleg.positionen.filter(zeilenart=Zeilenart.ZUSCHLAG)
            .order_by('sortierung')]


@pytest.mark.parametrize('art', [Rechnungsart.NORMAL, Rechnungsart.ABSCHLAG])
def test_nebenkosten_kommen_mit(projekt, kollege, lv, art):
    rechnung = _uebernehmen([_stunden(projekt, kollege, lv['2.10'], 6)],
                            rechnungsart=art)

    assert _zuschlaege(rechnung) == [
        ('90', 'Nebenkosten', Decimal('5.70'))]


def test_zuschlag_auf_eine_position_nur_mit_ihr(projekt, kollege, lv):
    """Erschwernis auf 2.20 erst, wenn 2.20 übernommen ist; Nebenkosten
    rechnen nicht auf die Erschwernis."""
    rechnung = _uebernehmen([_proben(projekt, kollege, lv['2.20'], 6, 3)],
                            rechnungsart=Rechnungsart.ABSCHLAG)

    assert _zuschlaege(rechnung) == [
        ('2.90', 'Erschwernis', Decimal('43.50')),
        ('90', 'Nebenkosten', Decimal('13.05')),
    ]


def test_zweite_uebernahme_rechnet_neu_statt_doppelt(projekt, kollege, lv):
    rechnung = _uebernehmen([_stunden(projekt, kollege, lv['2.10'], 6)],
                            rechnungsart=Rechnungsart.ABSCHLAG)
    _uebernehmen([_stunden(projekt, kollege, lv['2.10'], 7)], rechnung)

    assert _zuschlaege(rechnung) == [
        ('90', 'Nebenkosten', Decimal('11.40'))]


def test_vorhandener_zuschlag_gleicher_bezeichnung_bleibt(projekt, kollege,
                                                          lv):
    """Von Hand angelegt, etwa mit anderem Satz: kein zweiter."""
    rechnung = faktura_services.beleg_anlegen(
        projekt=projekt, typ=BelegTyp.RECHNUNG,
        rechnungsart=Rechnungsart.ABSCHLAG)
    faktura_services.position_hinzufuegen(
        beleg=rechnung, position='99', bezeichnung='Nebenkosten',
        zeilenart=Zeilenart.ZUSCHLAG, menge=Decimal('1'),
        einzelpreis=Decimal('0'), steuersatz='19.00',
        zuschlag_prozent=Decimal('5'))

    _uebernehmen([_stunden(projekt, kollege, lv['2.10'], 6)], rechnung)

    assert _zuschlaege(rechnung) == [
        ('99', 'Nebenkosten', Decimal('9.50'))]


def test_ohne_auftragsposition_kein_zuschlag(projekt, kollege, lv,
                                            zeitleistung):
    zeile = services.zeile_erfassen(
        projekt=projekt, leistung=zeitleistung, benutzer=kollege,
        datum=date(2026, 10, 6), von=time(8, 0), bis=time(9, 0),
        beschreibung='Katalog')

    rechnung = _uebernehmen([zeile], rechnungsart=Rechnungsart.ABSCHLAG)

    assert _zuschlaege(rechnung) == []


def _abschlag_festschreiben(abschlag):
    abschlag.leistungsdatum = date(2026, 10, 1)
    abschlag.leistungsdatum_bis = date(2026, 10, 31)
    abschlag.save()
    faktura_services.beleg_festschreiben(beleg_id=abschlag.pk)


def _schluss(projekt):
    schluss = faktura_services.beleg_anlegen(
        projekt=projekt, typ=BelegTyp.RECHNUNG,
        rechnungsart=Rechnungsart.SCHLUSS)
    faktura_services.abschlaege_absetzen(beleg_id=schluss.pk)
    return schluss


def test_schlussrechnung_einmal_auf_die_volle_leistung(projekt, kollege, lv):
    for tag in (6, 7):
        _abschlag_festschreiben(_uebernehmen(
            [_stunden(projekt, kollege, lv['2.10'], tag)],
            rechnungsart=Rechnungsart.ABSCHLAG))

    schluss = _schluss(projekt)

    assert _zuschlaege(schluss) == [
        ('90', 'Nebenkosten', Decimal('11.40'))]


def test_schlussrechnung_holt_fehlende_nebenkosten_nach(projekt, kollege,
                                                         lv):
    """Abschlag ohne Nebenkosten, etwa von vor dieser Regel."""
    abschlag = _uebernehmen([_stunden(projekt, kollege, lv['2.10'], 6)],
                            rechnungsart=Rechnungsart.ABSCHLAG)
    abschlag.positionen.filter(zeilenart=Zeilenart.ZUSCHLAG).delete()
    _abschlag_festschreiben(abschlag)

    schluss = _schluss(projekt)

    assert _zuschlaege(schluss) == [
        ('90', 'Nebenkosten', Decimal('5.70'))]
