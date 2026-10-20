"""Leistungsdatum als eigenes Feld, BT-Nummern in der Maske, BT-3 aus den
Settings.

Das XML zu Zeitraum und Abschlag prüft ``test_pdf.TestLeistungsdaten``.
"""

import re
from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from faktura import facturx, services
from faktura.models import BelegTyp, Kontakt, Rechnungsart
from faktura.tests.test_pdf import xml_datum, xml_wert

ARBEIT_BEGINN = date(2026, 9, 5)
ARBEIT_ENDE = date(2026, 9, 8)
ABNAHME = date(2026, 9, 12)


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-2000', name='Beispiel AG', strasse='Industriestraße 5',
        plz='90402', ort='Nürnberg', ust_id='DE987654321',
    )


def rechnung(kunde, art=Rechnungsart.NORMAL, **felder):
    beleg = services.beleg_anlegen(
        kunde=kunde, typ=BelegTyp.RECHNUNG, rechnungsart=art,
        betreff='Gutachten', **felder)
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Gutachten', menge=Decimal('1'),
        einheit='pausch', einzelpreis=Decimal('900.00'),
        steuersatz='19.00')
    return beleg


@pytest.mark.django_db
class TestEigenesFeld:
    """BT-72 steht in ``steuerliches_leistungsdatum``, vorbelegt und nicht
    abgeleitet."""

    def test_abnahme_nach_der_letzten_stunde(
            self, kunde):
        """Gearbeitet am 05.09. und 08.09., abgenommen am 12.09.: Das
        Leistungsdatum liegt an einem Tag ohne erfasste Stunde."""
        beleg = rechnung(kunde, leistungsdatum=ARBEIT_BEGINN,
                         leistungsdatum_bis=ARBEIT_ENDE,
                         steuerliches_leistungsdatum=ABNAHME)
        beleg = services.beleg_festschreiben(beleg_id=beleg.pk)

        xml = facturx.xml_erzeugen(beleg).decode()

        assert xml_datum(xml, 'OccurrenceDateTime') == ABNAHME
        assert xml_datum(xml, 'StartDateTime') == ARBEIT_BEGINN
        assert xml_datum(xml, 'EndDateTime') == ARBEIT_ENDE

    def test_beim_anlegen_vorbelegt_mit_dem_ende(self, kunde):
        beleg = rechnung(kunde, leistungsdatum=ARBEIT_BEGINN,
                         leistungsdatum_bis=ARBEIT_ENDE)

        assert beleg.steuerliches_leistungsdatum == ARBEIT_ENDE

    def test_ein_eingetragenes_datum_wird_nie_ueberschrieben(self, kunde):
        beleg = rechnung(kunde, steuerliches_leistungsdatum=ABNAHME)
        beleg.leistungsdatum, beleg.leistungsdatum_bis = (ARBEIT_BEGINN,
                                                          ARBEIT_ENDE)
        beleg.save()

        assert beleg.steuerliches_leistungsdatum == ABNAHME

    def test_auch_ein_spaeter_eingetragener_zeitraum_belegt_vor(self, kunde):
        """Ein später eingetragener Zeitraum belegt BT-72 vor, weil die
        Rechnung aus der Erfassung ohne Datum entsteht."""
        beleg = rechnung(kunde)
        beleg.leistungsdatum_bis = ARBEIT_ENDE
        beleg.save()

        assert beleg.steuerliches_leistungsdatum == ARBEIT_ENDE

    def test_ganz_ohne_datum_wird_nicht_festgeschrieben(self, kunde):
        beleg = rechnung(kunde)

        with pytest.raises(services.LeistungsdatumFehlt):
            services.beleg_festschreiben(beleg_id=beleg.pk)

    def test_der_zeitraum_ist_bei_der_rechnung_freiwillig(self, kunde):
        beleg = rechnung(kunde, steuerliches_leistungsdatum=ABNAHME)

        beleg = services.beleg_festschreiben(beleg_id=beleg.pk)
        xml = facturx.xml_erzeugen(beleg).decode()

        assert xml_datum(xml, 'OccurrenceDateTime') == ABNAHME
        assert 'BillingSpecifiedPeriod' not in xml

    def test_ein_abschlag_hat_nie_ein_leistungsdatum(self, kunde):
        """Ein Abschlag hat auch bei Übergabe eines Werts kein Leistungsdatum,
        damit er keine Teilleistung wird."""
        beleg = rechnung(kunde, art=Rechnungsart.ABSCHLAG,
                         leistungsdatum=ARBEIT_BEGINN,
                         leistungsdatum_bis=ARBEIT_ENDE,
                         steuerliches_leistungsdatum=ABNAHME)

        assert beleg.steuerliches_leistungsdatum is None

    def test_umgewidmet_zum_abschlag_verliert_es_das_datum(self, kunde):
        beleg = rechnung(kunde, leistungsdatum=ARBEIT_BEGINN,
                         leistungsdatum_bis=ARBEIT_ENDE)
        beleg.rechnungsart = Rechnungsart.ABSCHLAG
        beleg.save()

        beleg.refresh_from_db()
        assert beleg.steuerliches_leistungsdatum is None

    def test_storno_behaelt_das_leistungsdatum_des_originals(self, kunde):
        original = services.beleg_festschreiben(beleg_id=rechnung(
            kunde, leistungsdatum=ARBEIT_BEGINN,
            leistungsdatum_bis=ARBEIT_ENDE,
            steuerliches_leistungsdatum=ABNAHME).pk)

        storno, neu = services.rechnung_korrigieren(beleg_id=original.pk)

        assert storno.steuerliches_leistungsdatum == ABNAHME
        assert neu.steuerliches_leistungsdatum == ABNAHME


@pytest.mark.django_db
class TestTypcode:
    """BT-3 kommt aus den Settings; die Fachlogik verwendet nur die
    Rechnungsart."""

    def _typcode(self, kunde, art):
        beleg = rechnung(kunde, art=art, leistungsdatum=ARBEIT_BEGINN,
                         leistungsdatum_bis=ARBEIT_ENDE)
        beleg = services.beleg_festschreiben(beleg_id=beleg.pk)
        return xml_wert(facturx.xml_erzeugen(beleg).decode(), 'TypeCode')

    def test_vorgabe_ist_380(self, kunde):
        assert self._typcode(kunde, Rechnungsart.ABSCHLAG) == '380'

    def test_je_rechnungsart_einstellbar(self, kunde, settings):
        settings.ERECHNUNG_TYPCODE = {**settings.ERECHNUNG_TYPCODE,
                                      'abschlag': '386'}

        assert self._typcode(kunde, Rechnungsart.ABSCHLAG) == '386'
        assert self._typcode(kunde, Rechnungsart.NORMAL) == '380'


def spaltenkopf(beschriftung: str, bt: str) -> re.Pattern:
    """Erwartetes HTML eines Spaltenkopfs der Positionen: BT-Nummer klein
    darunter, Pflichtsternchen dazwischen (``tabular_heading.html``)."""
    return re.compile(re.escape(beschriftung)
                      + r'(<span class="[^"]*">\*</span>)?'
                      + re.escape(f'<span class="pw-bt">{bt}</span>'))


def ohne_doppelte_bt(inhalt: str) -> None:
    """Die BT-Nummer genau einmal, weil ``in`` "(BT-2)" auch in
    "(BT-2) (BT-2)" findet."""
    doppelt = re.findall(r'\(BT-[\d/]+\)\s*\(BT-', inhalt)
    assert not doppelt, doppelt


@pytest.mark.django_db
class TestBtNummernInDerMaske:
    """Label "Feldname (BT-xxx)" an allen Feldern der E-Rechnung, nur bei
    Steuerbelegen."""

    def test_rechnungsentwurf(self, buero, kunde):
        beleg = rechnung(kunde, steuerliches_leistungsdatum=ABNAHME)

        inhalt = buero.get(reverse('admin:faktura_rechnung_change',
                                   args=[beleg.pk])).content.decode()

        for beschriftung in ('Belegdatum (BT-2)', 'Leistungsdatum (BT-72)',
                             'Leistung von (BT-73)', 'Leistung bis (BT-74)',
                             spaltenkopf('Menge', 'BT-129'),
                             spaltenkopf('Preis (Netto)', 'BT-146')):
            muster = (re.escape(beschriftung) if isinstance(beschriftung, str)
                      else beschriftung)
            assert re.search(muster, inhalt), beschriftung
        ohne_doppelte_bt(inhalt)

    def test_auch_an_der_festgeschriebenen_rechnung(self, buero, kunde):
        """Auch an readonly-Feldern, die Django nach dem Modell beschriftet,
        sofern ``Meta.labels`` nichts anderes setzt."""
        beleg = services.beleg_festschreiben(beleg_id=rechnung(
            kunde, steuerliches_leistungsdatum=ABNAHME).pk)

        inhalt = buero.get(reverse('admin:faktura_rechnung_change',
                                   args=[beleg.pk])).content.decode()

        for beschriftung in ('Leistungsdatum (BT-72)',
                             spaltenkopf('Menge', 'BT-129'),
                             spaltenkopf('Betrag', 'BT-131')):
            muster = (re.escape(beschriftung) if isinstance(beschriftung, str)
                      else beschriftung)
            assert re.search(muster, inhalt), beschriftung
        ohne_doppelte_bt(inhalt)

    def test_der_abschlag_hat_kein_leistungsdatum_in_der_maske(
            self, buero, kunde):
        beleg = rechnung(kunde, art=Rechnungsart.ABSCHLAG,
                         leistungsdatum=ARBEIT_BEGINN,
                         leistungsdatum_bis=ARBEIT_ENDE)

        inhalt = buero.get(reverse('admin:faktura_abschlagsrechnung_change',
                                   args=[beleg.pk])).content.decode()

        assert 'BT-72' not in inhalt
        assert 'Leistungsstand ab (BT-73)' in inhalt
        assert 'Stichtag (BT-74)' in inhalt
        ohne_doppelte_bt(inhalt)

    def test_das_angebot_bleibt_ohne(self, buero, kunde):
        angebot = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)

        inhalt = buero.get(reverse('admin:faktura_angebot_change',
                                   args=[angebot.pk])).content.decode()

        assert 'BT-' not in inhalt
        # Die kurzen Spaltenköpfe gelten auch ohne BT-Nummern.
        for kopf in ('Preis (Netto)', 'USt.', 'Betrag'):
            assert re.search(re.escape(kopf) + r'\s*(<span[^>]*>\*</span>)?\s*</span>',
                             inhalt), kopf


@pytest.mark.django_db
class TestZeitraumJePosition:
    """BT-134/135: Zeitraum einer einzelnen Position."""

    def test_steht_im_xml_an_der_position(self, kunde):
        beleg = rechnung(kunde, steuerliches_leistungsdatum=ABNAHME)
        position = beleg.positionen.get()
        position.leistung_von, position.leistung_bis = (ARBEIT_BEGINN,
                                                        ARBEIT_ENDE)
        position.save()
        beleg = services.beleg_festschreiben(beleg_id=beleg.pk)

        xml = facturx.xml_erzeugen(beleg).decode()

        # Kein Zeitraum am Kopf; der Beginn kommt von der Position.
        assert xml_datum(xml, 'StartDateTime') == ARBEIT_BEGINN
        assert xml_datum(xml, 'EndDateTime') == ARBEIT_ENDE
        assert xml.index('StartDateTime') < xml.index(
            'ApplicableHeaderTradeAgreement')

    def test_ohne_zeitraum_nichts(self, kunde):
        beleg = services.beleg_festschreiben(beleg_id=rechnung(
            kunde, steuerliches_leistungsdatum=ABNAHME).pk)

        assert 'BillingSpecifiedPeriod' not in facturx.xml_erzeugen(
            beleg).decode()

    def test_storno_nimmt_ihn_mit(self, kunde):
        beleg = rechnung(kunde, steuerliches_leistungsdatum=ABNAHME)
        beleg.positionen.update(leistung_von=ARBEIT_BEGINN,
                                leistung_bis=ARBEIT_ENDE)
        original = services.beleg_festschreiben(beleg_id=beleg.pk)

        storno, _ = services.rechnung_korrigieren(beleg_id=original.pk)

        assert storno.positionen.get().leistung_bis == ARBEIT_ENDE

    def test_in_der_rechnungsmaske_mit_bt_nummer(self, buero, kunde):
        beleg = rechnung(kunde, steuerliches_leistungsdatum=ABNAHME)

        inhalt = buero.get(reverse('admin:faktura_rechnung_change',
                                   args=[beleg.pk])).content.decode()

        # Klein nach dem Label, wie unter den Spaltenköpfen.
        assert 'Leistung von <span class="pw-bt-neben">BT-134</span>' in inhalt
        assert 'Leistung bis <span class="pw-bt-neben">BT-135</span>' in inhalt

    def test_nicht_im_angebot(self, buero, kunde):
        angebot = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)

        inhalt = buero.get(reverse('admin:faktura_angebot_change',
                                   args=[angebot.pk])).content.decode()

        assert 'leistung_von' not in inhalt


class TestBtZerlegen:
    """Template-Filter, die "Menge (BT-129)" für die Spaltenköpfe und die
    schmalen Datumsfelder der Positionen zerlegen."""

    def test_zerlegt_die_beschriftung(self):
        from faktura.templatetags import faktura_extras

        assert faktura_extras.ohne_bt('Preis (Netto) (BT-146)')             == 'Preis (Netto)'
        assert faktura_extras.nur_bt('Preis (Netto) (BT-146)') == 'BT-146'
        assert faktura_extras.ohne_bt('Pos.') == 'Pos.'
        assert faktura_extras.nur_bt('Preis (Netto)') == ''
