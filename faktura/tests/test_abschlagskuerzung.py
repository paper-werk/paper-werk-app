"""Nicht voll bezahlte Abschläge (Rechenregister R-174, R-175).

Referenzfall: Der Kunde kürzt einen Abschlag, weil er einen Teil der
Leistung noch nicht anerkennt; der Betrieb fordert den Rest mit dem
nächsten Abschlag. Auftrag 120.000, Abschlag 1 über 50.000, bezahlt 40.000,
Abschlag 2 über 50.000 + 10.000 = 60.000. Die Schlussrechnung fordert
**20.000**. Regression: Mit einer Minderung des Abschlags per Nachlass
setzte die Schlussrechnung ihn voll ab und forderte ohne Warnung 10.000 zu
wenig.

Regel: Netto abgesetzt wird nur Vereinnahmtes (§ 14 Abs. 5 Satz 2 UStG);
unter jeder Absetzung steht der nicht bezahlte Teil als positive Restzeile.
Mit dem Festschreiben der Schlussrechnung erlischt die Abschlagsforderung.
Die Kürzung an der Zahlung schließt nur den offenen Posten, damit nicht
gemahnt wird, was anderweitig gefordert ist. Im Umsatz zählt die Restzeile
nicht, weil der Betrag im Abschlag enthalten ist.
"""

from datetime import date
from decimal import Decimal

import pytest

from auswertung import kundenakte
from faktura import facturx, pdf, services
from faktura.models import (
    Abnahme,
    Abnahmeart,
    BelegStatus,
    BelegTyp,
    Kontakt,
    Projekt,
    Rechnungsart,
)
from faktura.tests.test_pdf import xml_wert

pytestmark = pytest.mark.django_db

ABNAHME = date(2026, 3, 10)
EINGANG = date(2026, 2, 20)


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-3100', name='Gemeinde Musterdorf', strasse='Rathausplatz 1',
        plz='84028', ort='Landshut', ust_id='DE123123123')


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(
        nummer='2026-301', bezeichnung='Kläranlage Süd', kunde=kunde)


def _auftrag(projekt, betrag):
    beleg = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.AUFTRAG,
                                   betreff='Planung Kläranlage')
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Planung', menge=Decimal('1'),
        einheit='pausch', einzelpreis=Decimal(betrag),
        steuersatz='19.00')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


def _abschlag(projekt, *betraege):
    beleg = services.beleg_anlegen(
        projekt=projekt, typ=BelegTyp.RECHNUNG,
        rechnungsart=Rechnungsart.ABSCHLAG, betreff='Abschlag',
        leistungsdatum=date(2026, 1, 1), leistungsdatum_bis=date(2026, 1, 31))
    for nummer, betrag in enumerate(betraege, start=1):
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung=f'Leistungsstand {nummer}',
            menge=Decimal('1'), einheit='pausch',
            einzelpreis=Decimal(betrag), steuersatz='19.00')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


def _schluss(auftrag, leistung):
    """Schlussrechnung zur Gesamtabnahme als Entwurf."""
    gesamt = Abnahme.objects.create(
        auftrag=auftrag, art=Abnahmeart.GESAMT, abgenommen_am=ABNAHME)
    schluss = services.rechnung_aus_abnahme(abnahme_id=gesamt.pk)
    services.position_hinzufuegen(
        beleg=schluss, bezeichnung='Planung', menge=Decimal('1'),
        einheit='pausch', einzelpreis=Decimal(leistung),
        steuersatz='19.00')
    return schluss


def _zahlen(beleg, betrag, **abzuege):
    return services.zahlung_verbuchen(
        beleg_id=beleg.pk, datum=EINGANG, betrag=Decimal(betrag),
        **{k: Decimal(v) for k, v in abzuege.items()})


def _abzugszeilen(rechnung) -> list[tuple]:
    return [(p.ist_abschlagsrest, p.abgesetzte_position.beleg,
             services.positionssumme(menge=p.menge, einzelpreis=p.einzelpreis))
            for p in rechnung.positionen.filter(ist_abzug=True)
            .select_related('abgesetzte_position__beleg')]


def _stand(projekt):
    return next(s for s in services.projektstaende(nur_laufende=False)
                if s.projekt == projekt)


class TestGekuerzterErsterAbschlag:
    """Auftrag 120.000; AB 1 über 50.000, davon 40.000 bezahlt und 10.000
    gekürzt; AB 2 über 60.000 voll bezahlt. Netto, 19 %."""

    @pytest.fixture
    def belege(self, projekt):
        auftrag = _auftrag(projekt, '120000.00')
        ab1 = _abschlag(projekt, '50000.00')
        _zahlen(ab1, '47600.00', kuerzung='11900.00')
        ab2 = _abschlag(projekt, '50000.00', '10000.00')
        _zahlen(ab2, '71400.00')
        return auftrag, ab1, ab2

    @pytest.fixture
    def schluss(self, belege):
        auftrag, _, _ = belege
        return _schluss(auftrag, '120000.00')

    def test_die_schlussrechnung_fordert_20000(self, schluss):
        summen = services.belegsummen(schluss)

        assert summen.netto == Decimal('20000.00')
        assert summen.brutto == Decimal('23800.00')

    def test_abgesetzt_wird_der_abschlag_und_darunter_sein_rest(
            self, belege, schluss):
        _, ab1, ab2 = belege

        assert _abzugszeilen(schluss) == [
            (False, ab1, Decimal('-50000.00')),
            (True, ab1, Decimal('10000.00')),
            (False, ab2, Decimal('-50000.00')),
            (False, ab2, Decimal('-10000.00')),
        ]

    def test_das_blatt_zeigt_je_abschlag_eine_zeile(self, belege, schluss):
        """Keine positive Zeile im PDF: AB 1 erscheint als "gestellt 50.000,
        bezahlt 40.000" mit -40.000. Der Rest war mit AB 2 gefordert; "mit
        dieser Rechnung gefordert" wäre falsch."""
        _, ab1, _ = belege
        block = services.abzugsblock(schluss.positionen.all())
        html = pdf.beleg_als_html(schluss)

        # AB 2 hat zwei Positionen und erscheint in einer Zeile, eine je
        # Abschlag.
        assert [z.betrag for z in block] == [
            Decimal('-40000.00'), Decimal('-60000.00')]
        assert block[0].bezeichnung.startswith(f'1. Abschlagsrechnung {ab1.nummer}')
        assert block[0].bezeichnung.endswith(
            'gestellt 50.000,00, bezahlt 40.000,00')
        assert sum(z.betrag for z in block) == sum(
            services.positionssumme(menge=p.menge, einzelpreis=p.einzelpreis)
            for p in schluss.positionen.filter(ist_abzug=True))
        assert services.abschlaege.RESTTEXT not in html
        assert 'gestellt 50.000,00, bezahlt 40.000,00' in html

    def test_bt_113_ist_das_bezahlte(self, schluss):
        schluss = services.beleg_festschreiben(beleg_id=schluss.pk)
        xml = facturx.xml_erzeugen(schluss).decode()

        assert Decimal(xml_wert(xml, 'GrandTotalAmount')) == Decimal('142800.00')
        assert Decimal(xml_wert(xml, 'TotalPrepaidAmount')) == Decimal('119000.00')
        assert Decimal(xml_wert(xml, 'DuePayableAmount')) == Decimal('23800.00')

    def test_der_gekuerzte_abschlag_wird_nicht_gemahnt(self, belege):
        _, ab1, _ = belege

        assert services.offener_betrag(ab1) == 0
        assert ab1 not in [p.beleg for p in services.offene_posten().posten]

    def test_kein_hinweis_bei_voll_bezahltem_abschlag(self, belege, schluss):
        """R-169 nennt den erneut geforderten Betrag: den gekürzten Teil von
        AB 1, nicht AB 2."""
        _, ab1, _ = belege

        befund = services.offene_abgesetzte_abschlaege(schluss)

        assert [(o.abschlag, o.offen) for o in befund] == [
            (ab1, Decimal('11900.00'))]

    def test_im_umsatz_steht_der_auftrag_nicht_mehr(self, projekt, kunde,
                                                     schluss):
        """R-023, R-018, R-027, R-028, R-031 und die Kundenakte: 50.000 +
        60.000 + 20.000 sind gestellt, der Kunde schuldet 120.000; die
        Restzeile zählt nicht, weil ihr Betrag in AB 1 enthalten ist."""
        schluss = services.beleg_festschreiben(beleg_id=schluss.pk)
        jahr = schluss.belegdatum.year
        voll = Decimal('120000.00')

        assert _stand(projekt).fakturiert == voll
        assert _stand(projekt).abgerechnete_leistung == voll
        assert _stand(projekt).offen == 0
        assert services.projektakte(projekt).fakturiert_netto == voll
        assert services.fakturiert_im_jahr(jahr) == voll
        assert sum(m.netto for m in services.fakturaverlauf()) == voll
        assert [(z.kunde, z.netto) for z in services.umsatz_je_kunde(
            seit=date(jahr, 1, 1), bis=date(jahr, 12, 31))] == [(kunde, voll)]
        assert kundenakte._zahlen(kunde)['umsatz_netto'] == voll

    def test_danach_ist_nichts_mehr_offen_als_die_schlussrechnung(
            self, belege, schluss):
        _, ab1, ab2 = belege
        schluss = services.beleg_festschreiben(beleg_id=schluss.pk)

        posten = services.offene_posten().posten

        assert [(p.beleg, p.offen) for p in posten] == [
            (schluss, Decimal('23800.00'))]
        assert services.abgerechnet_in(ab1) == schluss
        assert services.abgerechnet_in(ab2) == schluss


class TestDieKuerzung:

    def test_nur_am_abschlag(self, projekt):
        rechnung = services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG, betreff='Regie',
            leistungsdatum=date(2026, 1, 15))
        services.position_hinzufuegen(
            beleg=rechnung, bezeichnung='Regie', menge=Decimal('1'),
            einheit='pausch', einzelpreis=Decimal('1000.00'),
            steuersatz='19.00')
        rechnung = services.beleg_festschreiben(beleg_id=rechnung.pk)

        with pytest.raises(services.UngueltigerBetrag, match='Abschlag'):
            _zahlen(rechnung, '1000.00', kuerzung='190.00')

    def test_skonto_wird_nicht_nachgefordert(self, projekt):
        """Skonto ist erlassen, die Kürzung nur verschoben; ein Abschlag mit
        Skonto hat keinen Rest."""
        auftrag = _auftrag(projekt, '40000.00')
        abschlag = _abschlag(projekt, '3000.00')
        _zahlen(abschlag, '3498.60', skonto='71.40')

        schluss = _schluss(auftrag, '40000.00')

        assert not schluss.positionen.filter(ist_abschlagsrest=True).exists()
        assert services.belegsummen(schluss).netto == Decimal('37000.00')

    def test_teilzahlung_ohne_kuerzung(self, projekt):
        """Der Rest ist der unbezahlte Anteil am Brutto, auf die Position
        umgelegt: 3.000 x 2.570 / 3.570 = 2.159,66."""
        auftrag = _auftrag(projekt, '40000.00')
        abschlag = _abschlag(projekt, '3000.00')
        _zahlen(abschlag, '1000.00')

        schluss = _schluss(auftrag, '40000.00')

        assert _abzugszeilen(schluss) == [
            (False, abschlag, Decimal('-3000.00')),
            (True, abschlag, Decimal('2159.66')),
        ]


class TestUnbezahlterAbschlag:
    """Variante (b): Den am Tag der Schlussrechnung unbezahlten Teil fordert
    sie selbst; die Abschlagsforderung erlischt."""

    @pytest.fixture
    def belege(self, projekt):
        auftrag = _auftrag(projekt, '40000.00')
        abschlag = _abschlag(projekt, '3000.00')
        schluss = services.beleg_festschreiben(
            beleg_id=_schluss(auftrag, '40000.00').pk)
        return abschlag, schluss

    def test_die_schlussrechnung_fordert_die_volle_leistung(self, belege):
        _, schluss = belege

        assert services.belegsummen(schluss).netto == Decimal('40000.00')

    def test_der_abschlag_ist_danach_nicht_mehr_offen(self, belege):
        abschlag, schluss = belege

        assert services.offener_betrag(abschlag) == 0
        assert [p.beleg for p in services.offene_posten().posten] == [schluss]
        assert services.abgerechnet_in(abschlag) == schluss

    def test_der_abschlag_heisst_abgerechnet_nicht_bezahlt(self, belege):
        """Ein abgerechneter Abschlag ohne Zahlung heißt "abgerechnet" (R-176).

        Regression: Die Liste zeigte "bezahlt" für einen Abschlag ohne
        Zahlung."""
        abschlag, schluss = belege

        assert (services.zahlungsstand(abschlag)
                == services.ZAHLUNGSSTAND_ABGERECHNET)
        assert services.zahlungsstand(schluss) in (
            services.ZAHLUNGSSTAND_OFFEN, services.ZAHLUNGSSTAND_UEBER_FRIST)

    def test_eine_spaete_zahlung_gehoert_auf_die_schlussrechnung(self, belege):
        abschlag, schluss = belege

        with pytest.raises(services.UngueltigerBetrag, match=schluss.nummer):
            _zahlen(abschlag, '3570.00')

    def test_im_umsatz_einmal(self, projekt, belege):
        assert _stand(projekt).fakturiert == Decimal('40000.00')

    def test_das_storno_der_schlussrechnung_belebt_den_abschlag(
            self, projekt, belege):
        abschlag, schluss = belege

        services.rechnung_korrigieren(beleg_id=schluss.pk)

        assert services.abgerechnet_in(abschlag) is None
        assert services.offener_betrag(abschlag) == Decimal('3570.00')
        assert _stand(projekt).fakturiert == Decimal('3000.00')


class TestZahlungNachDemAbsetzen:
    """Eine Zahlung nach dem Absetzen macht die Restzeile veraltet; das
    Festschreiben lehnt die Rechnung dann ab."""

    @pytest.fixture
    def lage(self, projekt):
        auftrag = _auftrag(projekt, '40000.00')
        abschlag = _abschlag(projekt, '3000.00')
        schluss = _schluss(auftrag, '40000.00')
        _zahlen(abschlag, '3570.00')
        return abschlag, schluss

    def test_das_festschreiben_weist_ab(self, lage):
        abschlag, schluss = lage

        assert services.veraltete_abschlagsreste(schluss) == [abschlag]
        with pytest.raises(services.UngueltigerBetrag,
                           match='Abschläge absetzen'):
            services.beleg_festschreiben(beleg_id=schluss.pk)

    def test_erneut_absetzen_gleicht_ab(self, lage):
        _, schluss = lage

        assert services.abschlaege_absetzen(beleg_id=schluss.pk) == []
        schluss = services.beleg_festschreiben(beleg_id=schluss.pk)

        assert schluss.status == BelegStatus.FESTGESCHRIEBEN
        assert not schluss.positionen.filter(ist_abschlagsrest=True).exists()
        assert services.belegsummen(schluss).netto == Decimal('37000.00')
