"""Übernahme in eine Rechnung: Titel des Auftrags und eine Position je
Auftragsposition.

* Die Rechnung bekommt die Titel, unter denen ihre Auftragspositionen
  stehen, damit Überschrift und Zwischensumme (``titelsummen``) entstehen.
  Auch die Schlussrechnung aus Abschlägen.
* Wird zu derselben Auftragsposition mehrfach übernommen, wächst die
  vorhandene Position, statt dass eine zweite mit fortlaufender Nummer
  entsteht, die nicht im Auftrag steht.
"""

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
    Firma,
    Kontakt,
    Leistungsart,
    Rechnungsart,
    Zeilenart,
)
from faktura.services.zuschlaege import titelsummen


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
    """Auftrag mit Titel 2 und den Positionen 2.10 (Zeit) und 2.20 (Stück),
    dazu Titel 03 und 03.01 mit Position 03.01.0010, und einem Text."""
    auftrag = Beleg.objects.create(
        typ=BelegTyp.AUFTRAG, status=BelegStatus.FESTGESCHRIEBEN,
        nummer='AU-2026-0020', projekt=projekt)

    def zeile(position, bezeichnung, zeilenart=Zeilenart.LEISTUNG, **rest):
        # bulk_create ruft save() nicht auf, das bei Titel und Text Menge
        # und Preis setzt.
        rest.setdefault('menge', Decimal('0'))
        rest.setdefault('einzelpreis', Decimal('0'))
        return Belegposition(beleg=auftrag, position=position,
                             bezeichnung=bezeichnung, zeilenart=zeilenart,
                             steuersatz='19.00', **rest)

    angelegt = Belegposition.objects.bulk_create([
        zeile('2', 'Erkundung', Zeilenart.TITEL),
        zeile('2.05', 'Vorbemerkung zur Erkundung', Zeilenart.TEXT),
        zeile('2.10', 'Probenahme', menge=Decimal('20'), einheit='Std',
              einzelpreis=Decimal('95.00'), art=Leistungsart.ZEIT),
        zeile('2.20', 'Bodenprobe', menge=Decimal('40'), einheit='Stk',
              einzelpreis=Decimal('145.00'), art=Leistungsart.MENGE),
        zeile('03', 'Gutachten', Zeilenart.TITEL),
        zeile('03.01', 'Bericht', Zeilenart.TITEL),
        zeile('03.01.0010', 'Bericht erstellen', menge=Decimal('1'),
              einheit='Std', einzelpreis=Decimal('95.00'),
              art=Leistungsart.ZEIT),
    ])
    return {p.position: p for p in angelegt}


@pytest.fixture
def labor(db):
    lieferant = Kontakt.objects.create(name='AGROLAB', ist_kunde=False,
                                       ist_lieferant=True)
    return Eingangsrechnung.objects.create(
        lieferant=lieferant, nummer='RE-2026-0901', datum=date(2026, 10, 1),
        betrag_netto=Decimal('1000.00'))


def _stunden(projekt, kollege, auftragsposition, tag, bis=time(10, 0)):
    return services.zeile_erfassen(
        projekt=projekt, auftragsposition=auftragsposition, benutzer=kollege,
        datum=date(2026, 10, tag), von=time(8, 0), bis=bis,
        beschreibung='Arbeit')


def _proben(projekt, kollege, auftragsposition, tag, menge):
    return services.zeile_erfassen(
        projekt=projekt, auftragsposition=auftragsposition, benutzer=kollege,
        datum=date(2026, 10, tag), menge=menge, beschreibung='Proben')


def _uebernehmen(zeilen, rechnung=None, fremd=None, **rest):
    beleg, _ = services.in_rechnung_uebernehmen(
        zeilen=Erfassungszeile.objects.filter(pk__in=[z.pk for z in zeilen]),
        fremdleistungen=fremd, beleg=rechnung, **rest)
    return beleg


def _zeilen(beleg):
    return [(p.position, p.zeilenart, p.menge if p.zeilenart ==
             Zeilenart.LEISTUNG else None)
            for p in beleg.positionen.filter(ist_abzug=False)
            .order_by('sortierung')]


# ── Titel ────────────────────────────────────────────────────────────────


class TestTitel:

    def test_der_titel_kommt_mit_und_summiert(self, projekt, kollege, lv):
        rechnung = _uebernehmen([_stunden(projekt, kollege, lv['2.10'], 6)])

        assert _zeilen(rechnung) == [
            ('2', Zeilenart.TITEL, None),
            ('2.10', Zeilenart.LEISTUNG, Decimal('2.00')),
        ]
        titel = rechnung.positionen.get(zeilenart=Zeilenart.TITEL)
        assert titel.bezeichnung == 'Erkundung'
        [[summe]] = titelsummen(rechnung.positionen.all()).values()
        assert (summe.titel, summe.netto) == (titel, Decimal('190.00'))

    def test_verschachtelte_titel(self, projekt, kollege, lv):
        rechnung = _uebernehmen(
            [_stunden(projekt, kollege, lv['03.01.0010'], 6)])

        assert [p for p, _, _ in _zeilen(rechnung)] == [
            '03', '03.01', '03.01.0010']

    def test_texte_bleiben_draussen(self, projekt, kollege, lv):
        rechnung = _uebernehmen([_stunden(projekt, kollege, lv['2.10'], 6)])

        assert not rechnung.positionen.filter(
            zeilenart=Zeilenart.TEXT).exists()

    def test_kein_zweiter_titel(self, projekt, kollege, lv):
        rechnung = _uebernehmen([_stunden(projekt, kollege, lv['2.10'], 6)])
        _uebernehmen([_proben(projekt, kollege, lv['2.20'], 7, 3)], rechnung)

        assert rechnung.positionen.filter(
            zeilenart=Zeilenart.TITEL).count() == 1

    def test_ein_eigener_titel_mit_der_nummer_bleibt(self, projekt, kollege,
                                                     lv):
        rechnung = faktura_services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG)
        faktura_services.position_hinzufuegen(
            beleg=rechnung, position='2', bezeichnung='Eigene Überschrift',
            zeilenart=Zeilenart.TITEL, menge=Decimal('0'),
            einzelpreis=Decimal('0'), steuersatz='19.00')

        _uebernehmen([_stunden(projekt, kollege, lv['2.10'], 6)], rechnung)

        assert list(rechnung.positionen.filter(zeilenart=Zeilenart.TITEL)
                    .values_list('bezeichnung', flat=True)) == [
            'Eigene Überschrift']

    def test_ohne_auftragsposition_kein_titel(self, projekt, kollege,
                                              zeitleistung):
        zeile = services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=kollege,
            datum=date(2026, 10, 6), von=time(8, 0), bis=time(9, 0),
            beschreibung='Katalog')

        rechnung = _uebernehmen([zeile])

        assert not rechnung.positionen.filter(
            zeilenart=Zeilenart.TITEL).exists()

    def test_die_schlussrechnung_aus_abschlaegen(self, projekt, kollege, lv):
        abschlag = _uebernehmen([_stunden(projekt, kollege, lv['2.10'], 6)],
                                rechnungsart=Rechnungsart.ABSCHLAG)
        abschlag.leistungsdatum = date(2026, 10, 1)
        abschlag.leistungsdatum_bis = date(2026, 10, 6)
        abschlag.save()
        faktura_services.beleg_festschreiben(beleg_id=abschlag.pk)

        schluss = faktura_services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG,
            rechnungsart=Rechnungsart.SCHLUSS)
        faktura_services.abschlaege_absetzen(beleg_id=schluss.pk)

        titel = schluss.positionen.get(zeilenart=Zeilenart.TITEL)
        assert (titel.position, titel.bezeichnung) == ('2', 'Erkundung')


# ── Kumulieren ───────────────────────────────────────────────────────────


class TestKumulieren:

    @pytest.mark.parametrize('art', [Rechnungsart.NORMAL,
                                     Rechnungsart.ABSCHLAG])
    def test_zweimal_dieselbe_position(self, projekt, kollege, lv, art):
        erste = _proben(projekt, kollege, lv['2.20'], 6, 3)
        rechnung = _uebernehmen([erste], rechnungsart=art)
        zweite = _proben(projekt, kollege, lv['2.20'], 9, 4)

        _uebernehmen([zweite], rechnung)

        [position] = rechnung.positionen.filter(zeilenart=Zeilenart.LEISTUNG)
        assert (position.position, position.menge) == ('2.20', Decimal('7'))
        assert (position.leistung_von, position.leistung_bis) == (
            date(2026, 10, 6), date(2026, 10, 9))
        assert set(Erfassungszeile.objects.values_list(
            'abgerechnet_in', flat=True)) == {position.pk}

    def test_stunden_und_zukauf_in_einem_durchgang(self, projekt, kollege,
                                                   lv, labor):
        proben = _proben(projekt, kollege, lv['2.20'], 6, 3)
        analyse = Fremdleistung.objects.create(
            rechnung=labor, projekt=projekt, auftragsposition=lv['2.20'],
            bezeichnung='Analyse', einheit='Stk', menge=Decimal('2'),
            einkaufspreis=Decimal('56.70'))

        rechnung = _uebernehmen(
            [proben], fremd=Fremdleistung.objects.filter(pk=analyse.pk))

        [position] = rechnung.positionen.filter(zeilenart=Zeilenart.LEISTUNG)
        assert position.menge == Decimal('5')
        analyse.refresh_from_db()
        assert analyse.abgerechnet_in == position

    def test_von_hand_geaenderter_preis_bleibt(self, projekt, kollege, lv):
        rechnung = _uebernehmen([_proben(projekt, kollege, lv['2.20'], 6, 3)])
        vorhanden = rechnung.positionen.get(zeilenart=Zeilenart.LEISTUNG)
        vorhanden.einzelpreis = Decimal('120.00')
        vorhanden.save()

        _uebernehmen([_proben(projekt, kollege, lv['2.20'], 9, 4)], rechnung)

        mengen = sorted(rechnung.positionen.filter(
            zeilenart=Zeilenart.LEISTUNG).values_list('menge', flat=True))
        assert mengen == [Decimal('3'), Decimal('4')]

    def test_zukauf_zum_einkaufspreis_wird_nicht_kumuliert(
            self, projekt, kollege, lv, labor):
        """Zum Einkaufspreis (Einheit passt nicht) gilt die Bezeichnung des
        Lieferanten; zwei verschiedene Pakete bleiben zwei Positionen."""
        for paket in ('Paket A', 'Paket B'):
            Fremdleistung.objects.create(
                rechnung=labor, projekt=projekt, auftragsposition=lv['2.10'],
                bezeichnung=paket, einheit='Stk', menge=Decimal('1'),
                einkaufspreis=Decimal('50.00'))

        rechnung = _uebernehmen([], fremd=Fremdleistung.objects.all())

        assert rechnung.positionen.filter(
            zeilenart=Zeilenart.LEISTUNG).count() == 2
