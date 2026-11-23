"""Einbehalte: Kennzahl über Abschläge und Schlussrechnungen (R-192),
Einbehalten an der Zuordnung auf eine Schlussrechnung (R-144).

Referenzfall: Sicherheitseinbehalt 5 % vom Brutto der Abschläge, frei mit
der Schlussrechnung; Mängeleinbehalt 3 % auf die Schlussrechnung, nicht
gemahnt bis zur Auszahlung.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from faktura import services
from faktura.forms import ZahlungForm
from faktura.models import (
    Abnahme,
    Abnahmeart,
    Abzugsgrundlage,
    Beleg,
    BelegTyp,
    Kontakt,
    Projekt,
    Rechnungsart,
    Zahlung,
    Zahlungszuordnung,
)

pytestmark = pytest.mark.django_db

EINGANG = date(2026, 3, 20)


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(nummer='K-5100', name='Gemeinde Oberfeld',
                           strasse='Rathausplatz 1', plz='84028',
                           ort='Landshut')


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(
        nummer='2026-510', bezeichnung='Feuerwehrhaus', kunde=kunde,
        einbehalt_prozent=Decimal('5'),
        einbehalt_grundlage=Abzugsgrundlage.BRUTTO)


@pytest.fixture
def auftrag(projekt):
    beleg = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.AUFTRAG,
                                   betreff='Objektüberwachung')
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='LPH 8', menge=Decimal('1'), einheit='LS',
        einzelpreis=Decimal('10000.00'), steuersatz='19.00')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


@pytest.fixture
def abschlag(projekt, auftrag):
    """4.000,00 netto, 4.760,00 brutto, Einbehalt 238,00, voll bezahlt."""
    beleg = services.beleg_anlegen(
        projekt=projekt, typ=BelegTyp.RECHNUNG,
        rechnungsart=Rechnungsart.ABSCHLAG, betreff='Abschlag',
        leistungsdatum=date(2026, 1, 1), leistungsdatum_bis=date(2026, 1, 31))
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='LPH 8', menge=Decimal('1'), einheit='LS',
        einzelpreis=Decimal('4000.00'), steuersatz='19.00',
        auftragsposition=auftrag.positionen.get())
    beleg = services.beleg_festschreiben(beleg_id=beleg.pk)
    services.zahlung_verbuchen(beleg_id=beleg.pk, datum=EINGANG,
                               betrag=Decimal('4522.00'))
    return beleg


def _schluss(auftrag):
    gesamt = Abnahme.objects.create(auftrag=auftrag, art=Abnahmeart.GESAMT,
                                    abgenommen_am=date(2026, 3, 1))
    schluss = services.rechnung_aus_abnahme(abnahme_id=gesamt.pk)
    return services.beleg_festschreiben(beleg_id=schluss.pk)


def _stand(projekt):
    return services.einbehalten(Beleg.objects.filter(projekt=projekt))


class TestSicherheitseinbehalt:

    def test_zaehlt_bis_zur_schlussrechnung(self, projekt, abschlag):
        assert abschlag.einbehalt == Decimal('238.00')
        assert services.offener_betrag(abschlag) == Decimal('0.00')
        assert _stand(projekt).abschlaege == Decimal('238.00')

    def test_die_schlussrechnung_fordert_ihn_zurueck(self, projekt, auftrag,
                                                     abschlag):
        schluss = _schluss(auftrag)

        assert _stand(projekt).abschlaege == Decimal('0.00')
        # 11.900,00 Leistung brutto minus 4.522,00 vereinnahmt.
        assert services.offener_betrag(schluss) == Decimal('7378.00')


class TestEinbehaltAnDerSchlussrechnung:

    @pytest.fixture
    def schluss(self, auftrag, abschlag):
        return _schluss(auftrag)

    @pytest.fixture
    def zahlung(self, schluss):
        """Schlusszahlung abzüglich 357,00 Mängeleinbehalt (3 % von
        11.900,00)."""
        return services.zahlung_verbuchen(
            beleg_id=schluss.pk, datum=date(2026, 4, 9),
            betrag=Decimal('7021.00'), einbehalten=Decimal('357.00'))

    def test_schliesst_den_offenen_posten(self, schluss, zahlung):
        assert services.offener_betrag(schluss) == Decimal('0.00')
        assert schluss.pk not in [p.beleg.pk
                                  for p in services.offene_posten().posten]

    def test_wird_nicht_gemahnt(self, schluss, zahlung):
        with pytest.raises(services.FalscherStatus):
            services.mahnung_erstellen(beleg_id=schluss.pk, stufe=1)

    def test_bleibt_als_einbehalten_stehen(self, projekt, zahlung):
        assert _stand(projekt).schlussrechnungen == Decimal('357.00')
        assert zahlung.zuordnungen.get().vereinnahmt == Decimal('7021.00')

    def test_nach_auszahlung_ist_nichts_mehr_einbehalten(
            self, projekt, kunde, schluss, zahlung):
        zuordnung = zahlung.zuordnungen.get()
        zuordnung.einbehalten = Decimal('0.00')
        zuordnung.notiz = 'Mängeleinbehalt ausgezahlt am 20.05.2027'
        zuordnung.full_clean()
        zuordnung.save()
        auszahlung = Zahlung.objects.create(
            datum=date(2027, 5, 20), betrag=Decimal('357.00'), kunde=kunde)
        neu = Zahlungszuordnung(zahlung=auszahlung, beleg=schluss,
                                betrag=Decimal('357.00'))
        neu.full_clean()
        neu.save()

        assert _stand(projekt).gesamt == Decimal('0.00')
        assert services.offener_betrag(schluss) == Decimal('0.00')

    def test_der_stand_des_kunden_ist_der_des_projekts(self, kunde,
                                                       projekt, zahlung):
        belege = Beleg.objects.filter(projekt__kunde=kunde)

        assert services.einbehalten(belege) == _stand(projekt)


class TestNurAnDerSchlussrechnung:

    def test_nicht_am_abschlag(self, abschlag):
        zahlung = Zahlung.objects.create(datum=EINGANG,
                                         betrag=Decimal('1.00'))
        zuordnung = Zahlungszuordnung(zahlung=zahlung, beleg=abschlag,
                                      betrag=Decimal('0.00'),
                                      einbehalten=Decimal('1.00'))

        with pytest.raises(ValidationError) as fehler:
            zuordnung.full_clean()
        assert 'einbehalten' in fehler.value.message_dict

    def test_das_formular_hat_das_feld_nur_an_der_schlussrechnung(self):
        assert 'einbehalten' in ZahlungForm(mit_einbehalt=True).fields
        assert 'einbehalten' not in ZahlungForm().fields

