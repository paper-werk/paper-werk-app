"""Mengen mit sechs Nachkommastellen, dargestellt ohne nachlaufende Nullen."""

import re
from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from core.felder import MengenFeld
from erfassung.models import Eingangsrechnung, Erfassungszeile, Fremdleistung
from faktura import facturx, formate, pdf, services
from faktura.models import Belegposition, BelegTyp, Kontakt

DRITTEL = Decimal('0.333333')


@pytest.mark.parametrize('modell', [Belegposition, Erfassungszeile,
                                    Fremdleistung])
def test_alle_mengen_haben_dieselbe_genauigkeit(modell):
    feld = modell._meta.get_field('menge')

    assert isinstance(feld, MengenFeld)
    assert (feld.max_digits, feld.decimal_places) == (13, 6)


@pytest.mark.parametrize(('wert', 'text'), [
    (Decimal('1.500000'), '1,5'),
    (Decimal('2.000000'), '2'),
    (DRITTEL, '0,333333'),
])
def test_anzeige_ohne_nachlaufende_nullen(wert, text):
    assert formate.menge(wert) == text


@pytest.fixture
def rechnung(kunde):
    beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG,
                                   betreff='Drittel',
                                   leistungsdatum=date(2026, 10, 1))
    services.position_hinzufuegen(
        beleg=beleg, position='1', bezeichnung='Pauschale', menge=DRITTEL,
        einheit='psch', einzelpreis=Decimal('1755.00'), steuersatz='19.00')
    return beleg


@pytest.fixture
def anderthalb(kunde):
    beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG,
                                   betreff='Normal',
                                   leistungsdatum=date(2026, 10, 1))
    services.position_hinzufuegen(
        beleg=beleg, position='1', bezeichnung='Stunden', menge=Decimal('1.5'),
        einheit='Std', einzelpreis=Decimal('100.00'), steuersatz='19.00')
    return beleg


@pytest.mark.django_db
class TestBeleg:

    def test_ein_drittel_trifft_den_betrag(self, rechnung):
        rechnung.refresh_from_db()

        assert rechnung.positionen.get().menge == DRITTEL
        assert services.belegsummen(rechnung).netto == Decimal('585.00')

    def test_summe_in_sql_gleich(self, rechnung):
        assert services.summe_ueber(
            type(rechnung).objects.filter(pk=rechnung.pk)).netto == (
                Decimal('585.00'))

    def test_pdf(self, rechnung, anderthalb):
        assert '0,333333' in pdf.beleg_als_html(rechnung)
        html = pdf.beleg_als_html(anderthalb)
        assert re.search(r'class="menge">1,5<', html)

    def test_e_rechnung_traegt_die_stellen(self, rechnung):
        fest = services.beleg_festschreiben(beleg_id=rechnung.pk)

        xml = facturx.xml_erzeugen(fest).decode()

        assert re.search(r'<ram:BilledQuantity[^>]*>0\.333333<', xml)

    def test_eingabe_ohne_nullen(self, buero, anderthalb):
        inhalt = buero.get(reverse('admin:faktura_rechnung_change',
                                   args=[anderthalb.pk])).content.decode()

        assert 'value="1.5"' in inhalt
        assert '1.500000' not in inhalt
        assert '1,500000' not in inhalt

    def test_schreibgeschuetzt_ohne_nullen(self, buero, anderthalb):
        fest = services.beleg_festschreiben(beleg_id=anderthalb.pk)

        inhalt = buero.get(reverse('admin:faktura_rechnung_change',
                                   args=[fest.pk])).content.decode()

        assert '1,500000' not in inhalt
        assert re.search(r'field-menge.*?1,5\b', inhalt, re.S)

    def test_eingabe_in_der_maske_nimmt_sechs_stellen(self, kunde):
        from faktura.forms import BelegpositionForm

        feld = BelegpositionForm.base_fields['menge']

        assert feld.clean('0.333333') == DRITTEL


@pytest.mark.django_db
class TestFremdleistung:

    @pytest.fixture
    def fremd(self, kunde):
        from faktura.models import Projekt

        projekt = Projekt.objects.create(nummer='P-1', bezeichnung='Probe',
                                         kunde=kunde)
        lieferant = Kontakt.anlegen(name='Labor', nummer='L-1')
        rechnung = Eingangsrechnung.objects.create(
            lieferant=lieferant, nummer='AL-1', datum=date(2026, 8, 1),
            betrag_netto=Decimal('100.00'))
        return Fremdleistung.objects.create(
            rechnung=rechnung, projekt=projekt, bezeichnung='Paket',
            menge=Decimal('1.5'), einkaufspreis=Decimal('10.00'))

    def test_liste(self, leitung, fremd):
        inhalt = leitung.get(reverse(
            'admin:erfassung_fremdleistung_changelist')).content.decode()

        assert '1,500000' not in inhalt
        assert re.search(r'field-menge_anzeige[^>]*>1,5<', inhalt)

    def test_eingabe_in_der_eingangsrechnung(self, leitung, fremd):
        inhalt = leitung.get(reverse(
            'admin:erfassung_eingangsrechnung_change',
            args=[fremd.rechnung_id])).content.decode()

        assert 'value="1.5"' in inhalt
        assert '1.500000' not in inhalt

    def test_einzelmaske(self, leitung, fremd):
        inhalt = leitung.get(reverse('admin:erfassung_fremdleistung_change',
                                     args=[fremd.pk])).content.decode()

        assert 'value="1.5"' in inhalt
