"""Optionaler Zuschlag (R-178, R-180).

Referenzfall: Raumluftmessungen, im Angebot optional 50 % an Samstagen
und 100 % an Sonn- und Feiertagen. Im Angebot steht nur der Satz; in die
Rechnung wird der Zuschlag manuell übernommen, die Rechnungsmaske nennt die
offenen.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from faktura import pdf, services
from faktura.models import Belegposition, BelegTyp, Kontakt, Projekt, Zeilenart
from faktura.tests.test_schluss_leistung import _maskendaten

VOLL = '19.00'


@pytest.fixture
def projekt(db):
    kunde = Kontakt.anlegen(
        nummer='K-5200', name='Stadtwerke Muster', strasse='Werkstraße 1',
        plz='84028', ort='Landshut')
    return Projekt.objects.create(
        nummer='2026-520', bezeichnung='Schule Süd', kunde=kunde)


def _zuschlag(beleg, nummer, text, prozent, auf, optional=True):
    return services.position_hinzufuegen(
        beleg=beleg, position=nummer, bezeichnung=text, menge=Decimal('1'),
        einzelpreis=Decimal('0.00'), steuersatz=VOLL,
        zeilenart=Zeilenart.ZUSCHLAG, zuschlag_prozent=Decimal(prozent),
        zuschlag_auf=auf, optional=optional)


def _mit_messungen(beleg):
    services.position_hinzufuegen(
        beleg=beleg, position='3.1', bezeichnung='Raumluftmessung',
        menge=Decimal('10'), einheit='Stk', einzelpreis=Decimal('300.00'),
        steuersatz=VOLL)
    _zuschlag(beleg, '3.2', 'Samstagszuschlag', '50', '3.1')
    _zuschlag(beleg, '3.3', 'Sonn- und Feiertagszuschlag', '100', '3.1')
    return beleg


@pytest.fixture
def angebot(projekt):
    return _mit_messungen(services.beleg_anlegen(
        projekt=projekt, typ=BelegTyp.ANGEBOT, betreff='Raumluft'))


@pytest.fixture
def auftrag(projekt):
    beleg = _mit_messungen(services.beleg_anlegen(
        projekt=projekt, typ=BelegTyp.AUFTRAG, betreff='Raumluft'))
    return services.beleg_festschreiben(beleg_id=beleg.pk)


def _p(beleg, nummer) -> Belegposition:
    return beleg.positionen.get(position=nummer)


class TestImAngebot:

    def test_bleibt_optional_ohne_betrag_und_ausser_der_summe(self, angebot):
        samstag = _p(angebot, '3.2')
        samstag.full_clean()

        assert samstag.optional
        assert samstag.einzelpreis == Decimal('0.00')
        assert services.belegsummen(angebot).netto == Decimal('3000.00')

    def test_ohne_haken_wieder_gerechnet(self, angebot):
        samstag = _p(angebot, '3.2')
        samstag.optional = False
        samstag.save()
        services.zuschlaege_nachrechnen(angebot)

        assert _p(angebot, '3.2').einzelpreis == Decimal('1500.00')

    def test_blatt_nennt_nur_den_satz(self, angebot):
        html = pdf.beleg_als_html(angebot)

        assert '50 % auf Pos. 3.1' in html
        assert '100 % auf Pos. 3.1' in html
        assert '(0,00)' not in html
        assert '1.500,00' not in html

    def test_ohne_bezug_auf_alle_leistungen(self, angebot):
        zuschlag = _zuschlag(angebot, '9', 'Nachtzuschlag', '25', '')

        assert services.zuschlagsbeschreibung(zuschlag, []) \
            == '25 % auf alle Leistungen'

    def test_nicht_in_der_rechnung(self, projekt):
        rechnung = services.beleg_anlegen(projekt=projekt,
                                          typ=BelegTyp.RECHNUNG)
        zuschlag = Belegposition(
            beleg=rechnung, position='1', bezeichnung='Samstag',
            menge=Decimal('1'), einzelpreis=Decimal('0'), steuersatz=VOLL,
            zeilenart=Zeilenart.ZUSCHLAG, zuschlag_prozent=Decimal('50'),
            optional=True)

        with pytest.raises(ValidationError, match='nur in Angebot'):
            zuschlag.full_clean()


class TestMaske:

    def test_haken_am_zuschlag_wird_gesichert(self, buero, projekt):
        """Über das Formular wird "optional" am Zuschlag gespeichert.
        Regression: Die Checkbox war am Zuschlag ``disabled``."""
        angebot = services.beleg_anlegen(projekt=projekt,
                                         typ=BelegTyp.ANGEBOT, betreff='R')
        services.position_hinzufuegen(
            beleg=angebot, position='3.1', bezeichnung='Raumluftmessung',
            menge=Decimal('10'), einzelpreis=Decimal('300.00'),
            steuersatz=VOLL)
        _zuschlag(angebot, '3.2', 'Samstagszuschlag', '50', '3.1',
                  optional=False)
        adresse = reverse('admin:faktura_angebot_change', args=[angebot.pk])
        daten = _maskendaten(buero.get(adresse))
        zeile = next(name.rsplit('-', 1)[0] for name, wert in daten.items()
                     if name.endswith('-position') and wert == '3.2')
        daten[f'{zeile}-optional'] = 'on'

        antwort = buero.post(adresse, daten)

        assert antwort.status_code == 302
        samstag = _p(angebot, '3.2')
        assert samstag.optional
        assert samstag.einzelpreis == Decimal('0.00')
        assert services.belegsummen(angebot).netto == Decimal('3000.00')


class TestInDerRechnung:

    def test_kommt_nicht_von_selbst_mit(self, auftrag):
        rechnung = services.beleg_umwandeln(beleg_id=auftrag.pk,
                                            neuer_typ=BelegTyp.RECHNUNG)

        assert list(rechnung.positionen.values_list('position', flat=True)) \
            == ['3.1']

    def test_die_offenen_werden_genannt(self, auftrag):
        rechnung = services.beleg_umwandeln(beleg_id=auftrag.pk,
                                            neuer_typ=BelegTyp.RECHNUNG)

        assert [p.bezeichnung for p in services.optionale_zuschlaege(rechnung)
                ] == ['Samstagszuschlag', 'Sonn- und Feiertagszuschlag']

    def test_abgerufen_wird_er_nicht_mehr_genannt(self, auftrag):
        rechnung = services.beleg_umwandeln(beleg_id=auftrag.pk,
                                            neuer_typ=BelegTyp.RECHNUNG)
        _zuschlag(rechnung, '3.2', 'Samstagszuschlag', '50', '3.1.1',
                  optional=False)

        assert [p.bezeichnung for p in services.optionale_zuschlaege(rechnung)
                ] == ['Sonn- und Feiertagszuschlag']

    def test_auch_ohne_vorgaenger_ueber_das_projekt(self, auftrag, projekt):
        rechnung = services.beleg_anlegen(projekt=projekt,
                                          typ=BelegTyp.RECHNUNG)

        assert len(services.optionale_zuschlaege(rechnung)) == 2

    def test_die_maske_zeigt_den_hinweis(self, buero, auftrag):
        rechnung = services.beleg_umwandeln(beleg_id=auftrag.pk,
                                            neuer_typ=BelegTyp.RECHNUNG)

        antwort = buero.get(reverse('admin:faktura_rechnung_change',
                                    args=[rechnung.pk]))

        meldungen = [str(m) for m in antwort.context['messages']]
        assert any('Samstagszuschlag (50 % auf Pos. 3.1, '
                   f'{auftrag.nummer})' in m for m in meldungen)
