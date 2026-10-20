"""Optionale Positionen ohne Anteil an der Summe (R-178).

Im Bauwesen "Eventualposition": Einzelpreis, Menge 0, kein Gesamtpreis.
Geprüft wird, dass sie in jeder Summe fehlen, in Python wie in SQL, und nie
als Überschreitung des Beauftragten gelten.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from auswertung import ergebnisse
from faktura import pdf, services
from faktura.models import (
    Abnahme,
    Abnahmeart,
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Kontakt,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(nummer='K-5150', name='Gemeinde Probedorf',
                           strasse='Rathausplatz 1', plz='84028', ort='Landshut')


def _beleg(kunde, typ, *zeilen):
    """Entwurf mit ``(menge, einzelpreis, optional)`` je Position."""
    beleg = services.beleg_anlegen(kunde=kunde, typ=typ, betreff='Feuerwehrhaus',
                                   leistungsdatum=date(2026, 9, 1))
    for menge, preis, optional in zeilen:
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Leistung', menge=Decimal(menge),
            einzelpreis=Decimal(preis), steuersatz='19.00',
            optional=optional)
    return beleg


class TestKeineSumme:
    """``_summen`` und ``POSITIONSNETTO`` schließen Optionen aus, geprüft
    gegen denselben Sollwert."""

    ZEILEN = (('12.5', '48.20', False),     # 602,50
              ('0', '48.20', True),         # Option ohne Menge
              ('12.5', '48.20', True),      # Option mit Menge: 602,50 nicht
              ('3', '100.00', False))       # 300,00

    def test_der_beleg_rechnet_ohne_sie(self, kunde):
        summen = services.belegsummen(_beleg(kunde, BelegTyp.ANGEBOT, *self.ZEILEN))

        assert summen.netto == Decimal('902.50')
        assert summen.steuer == Decimal('171.48')
        assert summen.brutto == Decimal('1073.98')

    def test_die_datenbank_rechnet_dasselbe(self, kunde):
        angebot = _beleg(kunde, BelegTyp.ANGEBOT, *self.ZEILEN)
        belege = Beleg.objects.filter(pk=angebot.pk)

        assert services.bruttosummen(belege) == {angebot.pk: Decimal('1073.98')}
        assert services.summe_ueber(belege).netto == Decimal('902.50')

    def test_ihr_eigener_betrag_bleibt(self, kunde):
        """Der eigene Betrag der Option wird wie jede Position berechnet und
        im PDF in Klammern gezeigt."""
        angebot = _beleg(kunde, BelegTyp.ANGEBOT, *self.ZEILEN)
        option = angebot.positionen.get(optional=True, menge=Decimal('12.5'))

        assert services.positionssumme(menge=option.menge,
                                       einzelpreis=option.einzelpreis) \
            == Decimal('602.50')

    def test_der_auftragswert_rechnet_ohne_sie(self, kunde):
        auftrag = services.beleg_festschreiben(beleg_id=_beleg(
            kunde, BelegTyp.AUFTRAG, *self.ZEILEN).pk)

        assert ergebnisse.auftragsstand(auftrag).beauftragt == Decimal('902.50')


class TestNurInAngebotUndAuftrag:

    def test_eine_rechnung_kennt_keine_option(self, kunde):
        rechnung = _beleg(kunde, BelegTyp.RECHNUNG)

        with pytest.raises(services.FakturaError, match='nur in Angebot und Auftrag'):
            services.position_hinzufuegen(
                beleg=rechnung, bezeichnung='Option', menge=Decimal('1'),
                einzelpreis=Decimal('10.00'), steuersatz='19.00',
                optional=True)

    def test_das_modell_prueft_dasselbe(self, kunde):
        position = Belegposition(
            beleg=_beleg(kunde, BelegTyp.RECHNUNG), position='10',
            bezeichnung='Option', menge=Decimal('1'),
            einzelpreis=Decimal('10.00'), optional=True)

        with pytest.raises(ValidationError, match='nur in Angebot und Auftrag'):
            position.full_clean()

    def test_menge_null_nur_als_option(self, kunde):
        angebot = _beleg(kunde, BelegTyp.ANGEBOT)
        position = Belegposition(beleg=angebot, position='10',
                                 bezeichnung='Leistung', menge=Decimal('0'),
                                 einzelpreis=Decimal('10.00'))

        with pytest.raises(ValidationError, match='Menge 0'):
            position.full_clean()
        position.optional = True
        position.full_clean()

    def test_umgewandelt_bleibt_sie_im_auftrag_und_faellt_aus_der_rechnung(
            self, kunde):
        angebot = services.beleg_festschreiben(beleg_id=_beleg(
            kunde, BelegTyp.ANGEBOT, ('2', '50.00', False),
            ('0', '80.00', True)).pk)

        auftrag = services.beleg_umwandeln(beleg_id=angebot.pk,
                                           neuer_typ=BelegTyp.AUFTRAG)
        assert [p.optional for p in auftrag.positionen.all()] == [False, True]

        auftrag = services.beleg_festschreiben(beleg_id=auftrag.pk)
        rechnung = services.beleg_umwandeln(beleg_id=auftrag.pk,
                                            neuer_typ=BelegTyp.RECHNUNG)
        assert [p.optional for p in rechnung.positionen.all()] == [False]


class TestAbgerufen:
    """Abruf einer Option durch eine Rechnung, die auf sie abrechnet; bei
    der Option ist der Preis beauftragt, nicht die Menge."""

    @pytest.fixture
    def option(self, kunde):
        auftrag = services.beleg_festschreiben(beleg_id=_beleg(
            kunde, BelegTyp.AUFTRAG, ('10', '50.00', False),
            ('0', '80.00', True)).pk)
        return auftrag.positionen.get(optional=True)

    def _rechnung_auf(self, kunde, option, menge):
        rechnung = _beleg(kunde, BelegTyp.RECHNUNG)
        services.position_hinzufuegen(
            beleg=rechnung, bezeichnung='Abgerufen', menge=Decimal(menge),
            einzelpreis=option.einzelpreis, steuersatz='19.00',
            auftragsposition=option)
        return rechnung

    def test_ist_nie_mehr_als_beauftragt(self, kunde, option):
        rechnung = self._rechnung_auf(kunde, option, '3')

        assert services.mengenueberschreitungen(rechnung) == []
        rechnung = services.beleg_festschreiben(beleg_id=rechnung.pk)
        assert rechnung.status == BelegStatus.FESTGESCHRIEBEN

    def test_der_abrechnungsstand_meldet_kein_zuviel(self, kunde, option):
        services.beleg_festschreiben(
            beleg_id=self._rechnung_auf(kunde, option, '3').pk)

        assert option.abrechnungsstand == '3 von 0 Stk abgerechnet'

    def test_in_der_auftragsakte_nicht_ueberzogen(self, kunde, option):
        services.beleg_festschreiben(
            beleg_id=self._rechnung_auf(kunde, option, '3').pk)

        stand = ergebnisse.auftragsstand(option.beleg)
        posten = next(p for p in stand.posten if p.position.pk == option.pk)
        assert posten.abgerechnet == Decimal('3')
        assert not posten.ist_ueberzogen
        # Berechnet zählt sie wie jede Leistung, als Beauftragtes nicht.
        assert stand.berechnet == Decimal('240.00')
        assert stand.beauftragt == Decimal('500.00')


class TestImPdf:

    def test_vermerk_und_betrag_in_klammern(self, kunde, firma):
        html = pdf.beleg_als_html(_beleg(
            kunde, BelegTyp.ANGEBOT, ('12.5', '48.20', False),
            ('12.5', '48.20', True), ('0', '80.00', True)))

        assert html.count('Optionale Position, nicht in der Summe') == 2
        assert '(602,50)' in html
        # Die Summe darunter ohne beide Optionen.
        assert '602,50 EUR' in html


class TestInDerMaske:
    """Speichern über das Formular mit Prüfung der Summen."""

    def _daten(self, kunde, menge, optional):
        daten = {
            'kunde': kunde.pk, 'betreff': 'Mit Option',
            'belegdatum': '', 'leistungsdatum': '', 'leistungsdatum_bis': '',
            'zahlungsziel_tage': '14', 'empfaenger': '', 'empfaenger_ust_id': '',
            'kopftext': '', 'fusstext': '',
            'positionen-TOTAL_FORMS': '1', 'positionen-INITIAL_FORMS': '0',
            'positionen-MIN_NUM_FORMS': '0', 'positionen-MAX_NUM_FORMS': '1000',
            'positionen-0-katalog': '', 'positionen-0-position': '01.0010',
            'positionen-0-bezeichnung': 'Wandschlitz Zulage',
            'positionen-0-menge': menge, 'positionen-0-einheit': 'm',
            'positionen-0-einzelpreis': '18.50',
            'positionen-0-steuersatz': '19.00',
        }
        if optional:
            daten['positionen-0-optional'] = 'on'
        return daten

    def test_option_mit_menge_null_wird_gesichert(self, buero, kunde):
        buero.post(reverse('admin:faktura_angebot_add'),
                   self._daten(kunde, '0', optional=True), follow=True)

        position = Belegposition.objects.get(bezeichnung='Wandschlitz Zulage')
        assert position.optional
        assert position.menge == 0

    def test_ohne_haken_ist_menge_null_ein_fehler(self, buero, kunde):
        antwort = buero.post(reverse('admin:faktura_angebot_add'),
                             self._daten(kunde, '0', optional=False))

        assert not Belegposition.objects.filter(
            bezeichnung='Wandschlitz Zulage').exists()
        assert 'nur eine optionale Position' in antwort.content.decode()

    def test_die_rechnung_hat_keinen_haken(self, buero):
        inhalt = buero.get(reverse('admin:faktura_rechnung_add')).content.decode()
        assert 'name="positionen-0-optional"' not in inhalt
        assert 'name="positionen-0-optional"' in buero.get(
            reverse('admin:faktura_auftrag_add')).content.decode()


class TestInDerAbnahme:
    """A7: Optionen zählen weder zum Entgelt noch gelangen sie automatisch
    in die Schlussrechnung, auch nicht mit geschätzter Menge."""

    @pytest.fixture
    def auftrag(self, kunde):
        return services.beleg_festschreiben(beleg_id=_beleg(
            kunde, BelegTyp.AUFTRAG, ('10', '50.00', False),
            ('12.5', '48.20', True)).pk)

    def test_das_entgelt_ohne_sie(self, auftrag):
        abnahme = Abnahme.objects.create(auftrag=auftrag, art=Abnahmeart.GESAMT)

        assert abnahme.entgelt_netto == Decimal('500.00')

    def test_die_teilschlussrechnung_ohne_sie(self, auftrag):
        abnahme = Abnahme.objects.create(
            auftrag=auftrag, art=Abnahmeart.TEIL, abgenommen_am=date(2026, 9, 30))
        abnahme.positionen.set(auftrag.positionen.all())

        rechnung = services.rechnung_aus_abnahme(abnahme_id=abnahme.pk)

        assert [p.bezeichnung for p in rechnung.positionen.all()] == ['Leistung']
        assert services.belegsummen(rechnung).netto == Decimal('500.00')
