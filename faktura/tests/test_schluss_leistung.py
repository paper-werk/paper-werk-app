"""Die Schlussrechnung führt die volle Leistung auf, darunter je Abschlag
eine Zeile (R-179).

Oben steht jede Leistung mit ihrer Gesamtmenge, unten je Abschlag eine
Zeile. Ohne diesen Schritt bestünde die Schlussrechnung nur aus negativen
Zeilen, eine je Abschlagsposition.
"""

from datetime import date
from decimal import Decimal

import pytest

from faktura import facturx, pdf, services
from faktura.models import (
    Abnahme,
    Abnahmeart,
    BelegTyp,
    Kontakt,
    Projekt,
    Rechnungsart,
)
from faktura.tests.test_pdf import xml_wert

ABNAHME = date(2025, 7, 1)


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-4100', name='Landratsamt Musterstadt', strasse='Ring 2',
        plz='85072', ort='Eichstätt', ust_id='DE111222333')


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(
        nummer='2024-048', bezeichnung='Rückbau Musterweg', kunde=kunde)


@pytest.fixture
def auftrag(projekt):
    """Auftrag mit Analysen nach Stück, Ingenieurleistung pauschal und
    Nebenkosten pauschal, mit LV-Nummern."""
    beleg = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.AUFTRAG,
                                   betreff='Rückbau')
    for nummer, text, menge, einheit, preis in (
            ('01.0010', 'Asbest Einzelprobe', '20', 'Stk', '65.00'),
            ('01.0020', 'Ausführungsplanung', '1', 'pausch', '8500.00'),
            ('01.0030', 'Nebenkosten 3%', '1', 'pausch', '340.50')):
        services.position_hinzufuegen(
            beleg=beleg, position=nummer, bezeichnung=text,
            menge=Decimal(menge), einheit=einheit,
            einzelpreis=Decimal(preis), steuersatz='19.00')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


def _ap(auftrag, nummer):
    return auftrag.positionen.get(position=nummer)


def _abschlag(projekt, *zeilen, tag, bezahlt=True):
    """``zeilen``: (Auftragsposition oder None, Bezeichnung, Menge, Einheit,
    Preis, Satz)."""
    beleg = services.beleg_anlegen(
        projekt=projekt, typ=BelegTyp.RECHNUNG,
        rechnungsart=Rechnungsart.ABSCHLAG, betreff='Abschlag',
        leistungsdatum=tag, leistungsdatum_bis=tag)
    for ap, text, menge, einheit, preis, satz in zeilen:
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung=text, menge=Decimal(menge),
            einheit=einheit, einzelpreis=Decimal(preis), steuersatz=satz,
            auftragsposition=ap, leistung_von=tag, leistung_bis=tag)
    beleg = services.beleg_festschreiben(beleg_id=beleg.pk)
    if bezahlt:
        services.zahlung_verbuchen(
            beleg_id=beleg.pk, datum=tag,
            betrag=services.belegsummen(beleg).brutto)
    return beleg


def _schluss(auftrag):
    gesamt = Abnahme.objects.create(
        auftrag=auftrag, art=Abnahmeart.GESAMT, abgenommen_am=ABNAHME)
    return services.rechnung_aus_abnahme(abnahme_id=gesamt.pk)


def _leistungen(schluss):
    return [(p.position, p.bezeichnung, p.menge, p.einzelpreis)
            for p in schluss.positionen.filter(ist_abzug=False)]


@pytest.fixture
def referenzfall(projekt, auftrag):
    """Referenzfall. AB 1: 6 Proben, 3.000 von 8.500 Planung, Nebenkosten
    214,50. AB 2: 4 Proben, 5.500 Planung, Nebenkosten 126,00."""
    probe, planung, nk = (_ap(auftrag, n)
                          for n in ('01.0010', '01.0020', '01.0030'))
    ab1 = _abschlag(
        projekt,
        (probe, 'Asbest Einzelprobe', '6', 'Stk', '65.00', '19.00'),
        (planung, 'Ausführungsplanung', '1', 'pausch', '3000.00',
         '19.00'),
        (None, 'Nebenkosten 3%', '1', 'pausch', '214.50', '19.00'),
        tag=date(2025, 2, 3))
    ab2 = _abschlag(
        projekt,
        (probe, 'Asbest Einzelprobe', '4', 'Stk', '65.00', '19.00'),
        (planung, 'Ausführungsplanung', '1', 'pausch', '5500.00',
         '19.00'),
        (None, 'Nebenkosten 3%', '1', 'pausch', '126.00', '19.00'),
        tag=date(2025, 6, 2))
    return ab1, ab2, (probe, planung, nk)


@pytest.mark.django_db
class TestLeistungAusDenAbschlaegen:

    def test_jede_leistung_steht_einmal_mit_ihrer_gesamtmenge(
            self, auftrag, referenzfall):
        """Proben zum Vertragspreis: 6 + 4. Planung als Teilbeträge: die
        Auftragsposition. Die frei eingegebenen Nebenkosten fehlen, weil sie
        ohne Auftrag, Katalog oder Erfassung nur Geld anfordern."""
        schluss = _schluss(auftrag)

        assert _leistungen(schluss) == [
            ('01.0010', 'Asbest Einzelprobe', Decimal('10.000'),
             Decimal('65.00')),
            ('01.0020', 'Ausführungsplanung', Decimal('1.000'),
             Decimal('8500.00')),
        ]

    def test_die_leistung_zeigt_auf_den_auftrag(self, auftrag, referenzfall):
        _, _, (probe, planung, _) = referenzfall
        schluss = _schluss(auftrag)

        bezug = [p.auftragsposition for p in
                 schluss.positionen.filter(ist_abzug=False)]
        assert bezug == [probe, planung]

    def test_zeitraum_der_position_spannt_ueber_die_abschlaege(
            self, auftrag, referenzfall):
        schluss = _schluss(auftrag)

        probe = schluss.positionen.get(position='01.0010')
        assert (probe.leistung_von, probe.leistung_bis) == (
            date(2025, 2, 3), date(2025, 6, 2))

    def test_summen_leistung_minus_abschlaege(self, auftrag, referenzfall):
        """Leistung 650 + 8.500 = 9.150. Abgesetzt 9.490,50 einschließlich der
        Nebenkosten, die oben manuell ergänzt werden; danach Restbetrag
        0."""
        schluss = _schluss(auftrag)

        assert services.leistungssummen(schluss).netto == Decimal('9150.00')
        assert services.belegsummen(schluss).netto == Decimal('-340.50')

        services.position_hinzufuegen(
            beleg=schluss, bezeichnung='Nebenkosten 3%', menge=Decimal('1'),
            einheit='pausch', einzelpreis=Decimal('340.50'),
            steuersatz='19.00',
            auftragsposition=_ap(auftrag, '01.0030'))
        assert services.belegsummen(schluss).netto == Decimal('0.00')
        assert services.belegsummen(schluss).brutto == Decimal('0.00')

    def test_noch_einmal_absetzen_doppelt_nichts(self, auftrag, referenzfall):
        schluss = _schluss(auftrag)
        vorher = schluss.positionen.count()

        assert services.abschlaege_absetzen(beleg_id=schluss.pk) == []
        assert schluss.positionen.count() == vorher

    def test_festgeschrieben_ist_der_auftrag_abgerechnet(
            self, auftrag, referenzfall):
        """Abschläge verbrauchen kein Kontingent (R-008), die festgeschriebene
        Schlussrechnung schon."""
        _, _, (probe, planung, _) = referenzfall
        schluss = _schluss(auftrag)
        services.beleg_festschreiben(beleg_id=schluss.pk)

        assert probe.offene_menge == Decimal('10')
        assert planung.offene_menge == Decimal('0')

    def test_pauschalabschlag_ohne_bezug_bringt_keine_leistung(
            self, projekt, auftrag):
        _abschlag(projekt, (None, 'Leistungsstand 1', '1', 'pausch',
                            '5000.00', '19.00'),
                  tag=date(2025, 2, 3))
        schluss = _schluss(auftrag)

        assert _leistungen(schluss) == []

    def test_katalogleistung_ohne_auftrag_wird_zusammengefasst(
            self, projekt, auftrag):
        """Aus dem Katalog (``art`` gesetzt), ohne Auftragsposition."""
        for tag, menge in ((date(2025, 2, 3), '2'), (date(2025, 6, 2), '3')):
            beleg = services.beleg_anlegen(
                projekt=projekt, typ=BelegTyp.RECHNUNG,
                rechnungsart=Rechnungsart.ABSCHLAG, betreff='Abschlag',
                leistungsdatum=tag, leistungsdatum_bis=tag)
            services.position_hinzufuegen(
                beleg=beleg, bezeichnung='Ortstermin', menge=Decimal(menge),
                einheit='Stk', einzelpreis=Decimal('150.00'),
                steuersatz='19.00', art='menge')
            services.beleg_festschreiben(beleg_id=beleg.pk)
        schluss = _schluss(auftrag)

        assert [(b, m) for _, b, m, _ in _leistungen(schluss)] == [
            ('Ortstermin', Decimal('5.000'))]

    def test_belegte_nummer_wird_nicht_doppelt_vergeben(
            self, projekt, auftrag, referenzfall):
        """Ist die LV-Nummer in der Rechnung vergeben, erhält die Leistung die
        nächste freie, weil die Nummer je Beleg unique ist."""
        schluss = services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG,
            rechnungsart=Rechnungsart.SCHLUSS, betreff='Schluss')
        services.position_hinzufuegen(
            beleg=schluss, position='01.0010', bezeichnung='Von Hand',
            menge=Decimal('1'), einzelpreis=Decimal('1.00'),
            steuersatz='19.00')

        services.abschlaege_absetzen(beleg_id=schluss.pk)

        nummern = list(schluss.positionen.values_list('position', flat=True))
        assert len(nummern) == len(set(nummern))
        assert schluss.positionen.filter(
            bezeichnung='Asbest Einzelprobe', ist_abzug=False).exists()

    def test_teilschluss_bleibt_wie_er_war(self, projekt, auftrag):
        """Die Teilschlussrechnung übernimmt ihre Positionen aus dem Auftrag,
        nicht zusätzlich aus den Abschlägen."""
        probe = _ap(auftrag, '01.0010')
        _abschlag(projekt, (probe, 'Asbest Einzelprobe', '6', 'Stk', '65.00',
                            '19.00'), tag=date(2025, 2, 3))
        teil = Abnahme.objects.create(
            auftrag=auftrag, art=Abnahmeart.TEIL, abgenommen_am=ABNAHME)
        teil.positionen.add(probe)

        rechnung = services.rechnung_aus_abnahme(abnahme_id=teil.pk)

        # Mit der LV-Nummer aus dem Auftrag.
        assert _leistungen(rechnung) == [
            ('01.0010', 'Asbest Einzelprobe', Decimal('20.000'),
             Decimal('65.00'))]


@pytest.mark.django_db
class TestJeAbschlagEineZeile:

    def test_unten_eine_zeile_je_abschlag(self, auftrag, referenzfall):
        ab1, ab2, _ = referenzfall
        schluss = _schluss(auftrag)

        block = services.abzugsblock(schluss.positionen.all())

        assert [(z.bezeichnung, z.betrag) for z in block] == [
            (f'1. Abschlagsrechnung {ab1.nummer} vom {ab1.belegdatum:%d.%m.%Y}',
             Decimal('-3604.50')),
            (f'2. Abschlagsrechnung {ab2.nummer} vom {ab2.belegdatum:%d.%m.%Y}',
             Decimal('-5886.00')),
        ]

    def test_der_block_ergibt_die_summe_der_abzugszeilen(
            self, auftrag, referenzfall):
        schluss = _schluss(auftrag)

        block = services.abzugsblock(schluss.positionen.all())

        assert sum(z.betrag for z in block) == sum(
            services.positionssumme(menge=p.menge, einzelpreis=p.einzelpreis)
            for p in schluss.positionen.filter(ist_abzug=True))

    def test_zwei_saetze_in_einem_abschlag_zwei_zeilen(
            self, projekt, auftrag):
        """§ 14 Abs. 5 Satz 2 UStG: Steuer je Satz, also eine Zeile je Abschlag
        und Satz."""
        ab = _abschlag(
            projekt,
            (None, 'Planung', '1', 'pausch', '1000.00', '19.00'),
            (None, 'Druck', '1', 'pausch', '100.00', '7.00'),
            tag=date(2025, 2, 3))
        schluss = _schluss(auftrag)

        block = services.abzugsblock(schluss.positionen.all())

        assert [(z.steuersatz_dezimal, z.betrag) for z in block] == [
            (Decimal('19'), Decimal('-1000.00')),
            (Decimal('7'), Decimal('-100.00'))]
        assert all(z.bezeichnung.startswith(f'1. Abschlagsrechnung {ab.nummer}')
                   for z in block)

    def test_teilweise_bezahlt_eine_zeile_mit_gestellt_und_bezahlt(
            self, projekt, auftrag):
        probe = _ap(auftrag, '01.0010')
        ab = _abschlag(
            projekt,
            (probe, 'Asbest Einzelprobe', '10', 'Stk', '65.00',
             '19.00'),
            (None, 'Nebenkosten 3%', '1', 'pausch', '350.00',
             '19.00'),
            tag=date(2025, 2, 3), bezahlt=False)
        # 1.000 netto, 1.190 brutto; bezahlt 595, die Hälfte.
        services.zahlung_verbuchen(beleg_id=ab.pk, datum=date(2025, 2, 20),
                                   betrag=Decimal('595.00'))
        schluss = _schluss(auftrag)

        (zeile,) = services.abzugsblock(schluss.positionen.all())

        assert zeile.bezeichnung == (
            f'1. Abschlagsrechnung {ab.nummer} vom {ab.belegdatum:%d.%m.%Y}, '
            f'gestellt 1.000,00, bezahlt 500,00')
        assert zeile.betrag == Decimal('-500.00')

    def test_das_blatt_zeigt_die_leistung_und_die_abschlaege(
            self, auftrag, referenzfall):
        ab1, _, _ = referenzfall
        schluss = _schluss(auftrag)

        html = pdf.beleg_als_html(schluss)

        assert 'Asbest Einzelprobe' in html
        assert (f'1. Abschlagsrechnung {ab1.nummer} vom '
                f'{ab1.belegdatum:%d.%m.%Y}<') in html
        assert 'Abschlagsrechnung' not in html.split(
            'Bereits berechnete')[0]

    def test_bt_113_bleibt_die_summe_der_abschlaege(self, auftrag, referenzfall):
        schluss = _schluss(auftrag)
        services.position_hinzufuegen(
            beleg=schluss, bezeichnung='Nebenkosten 3%', menge=Decimal('1'),
            einheit='pausch', einzelpreis=Decimal('340.50'),
            steuersatz='19.00',
            auftragsposition=_ap(auftrag, '01.0030'))
        schluss = services.beleg_festschreiben(beleg_id=schluss.pk)

        xml = facturx.xml_erzeugen(schluss).decode()

        # Leistung 9.490,50 netto, 11.293,70 brutto (gerundet je Satz);
        # abgesetzt dasselbe, also bleibt nichts zu zahlen.
        grand = Decimal(xml_wert(xml, 'GrandTotalAmount'))
        prepaid = Decimal(xml_wert(xml, 'TotalPrepaidAmount'))
        assert grand == Decimal('11293.70')
        assert grand - prepaid == Decimal(xml_wert(xml, 'DuePayableAmount'))
        assert Decimal(xml_wert(xml, 'DuePayableAmount')) == Decimal('0.00')


def _maskendaten(antwort) -> dict:
    """POST-Daten beim Speichern: alle Felder des Belegs und der Positionen
    mit den Werten der geladenen Maske."""
    daten = {}

    def eintragen(formular):
        for feld in formular:
            wert = feld.value()
            if wert is None:
                continue
            if isinstance(wert, bool):
                if wert:
                    daten[feld.html_name] = 'on'
                continue
            if isinstance(wert, (list, tuple)):
                daten[feld.html_name] = [str(w) for w in wert]
                continue
            daten[feld.html_name] = str(wert)

    eintragen(antwort.context['adminform'].form)
    for inline in antwort.context['inline_admin_formsets']:
        formset = inline.formset
        eintragen(formset.management_form)
        for formular in formset.forms:
            eintragen(formular)
    return daten


@pytest.mark.django_db
class TestMaskeWieBlatt:
    """Die Maske zeigt die Abzüge wie das PDF: eine Zeile je Abschlag unter
    den Positionen."""

    def _adresse(self, schluss):
        from django.urls import reverse
        return reverse('admin:faktura_schlussrechnung_change',
                       args=[schluss.pk])

    def test_positionen_ohne_abzuege_darunter_je_abschlag_eine_zeile(
            self, buero, auftrag, referenzfall):
        ab1, ab2, _ = referenzfall
        schluss = _schluss(auftrag)

        antwort = buero.get(self._adresse(schluss))
        html = antwort.content.decode()

        formset = antwort.context['inline_admin_formsets'][0].formset
        assert all(not f.instance.ist_abzug
                   for f in formset.forms if f.instance.pk)
        assert 'Bereits berechnete Abschläge' in html
        assert (f'1. Abschlagsrechnung {ab1.nummer} vom '
                f'{ab1.belegdatum:%d.%m.%Y}<') in html
        assert '-3.604,50 €' in html
        assert '-9.490,50 €' in html
        # Keine Zeile je Abschlagsposition in der Maske.
        assert f'{ab1.nummer} vom {ab1.belegdatum:%d.%m.%Y}: Nebenkosten' \
            not in html

    def test_sichern_laesst_die_abzuege_stehen(self, buero, auftrag,
                                              referenzfall):
        """Die Abzugszeilen sind nicht im Formular und bleiben beim Speichern
        erhalten; eine neue Zeile erhält eine freie Nummer."""
        schluss = _schluss(auftrag)
        abzuege_vorher = set(schluss.positionen.filter(ist_abzug=True)
                             .values_list('pk', flat=True))
        antwort = buero.get(self._adresse(schluss))
        daten = _maskendaten(antwort)
        # Leere Zeile für die Nebenkosten (S-A3).
        leer = antwort.context['inline_admin_formsets'][0].formset.forms[-1]
        daten.update({
            f'{leer.prefix}-bezeichnung': 'Nebenkosten 3%',
            f'{leer.prefix}-menge': '1',
            f'{leer.prefix}-einheit': 'pausch',
            f'{leer.prefix}-einzelpreis': '340.50',
            f'{leer.prefix}-steuersatz': '19.00',
        })

        ergebnis = buero.post(self._adresse(schluss), daten)

        assert ergebnis.status_code == 302, ergebnis.context[
            'adminform'].form.errors if ergebnis.context else ''
        assert set(schluss.positionen.filter(ist_abzug=True)
                   .values_list('pk', flat=True)) == abzuege_vorher
        nummern = list(schluss.positionen.values_list('position', flat=True))
        assert len(nummern) == len(set(nummern))
        assert services.belegsummen(schluss).netto == Decimal('0.00')
