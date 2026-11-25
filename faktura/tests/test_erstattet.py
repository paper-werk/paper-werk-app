"""Erstattet: an den Zahler zurücküberwiesener Teil einer Zahlung (R-142).

Referenzfall: 1.500,00 eingegangen auf eine Rechnung über 1.190,00, die
Überzahlung von 310,00 wird erstattet.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from faktura import services
from faktura.models import BelegTyp, Kontakt, Zahlung, Zahlungszuordnung

pytestmark = pytest.mark.django_db

HEUTE = timezone.localdate()


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(nummer='K-5200', name='Muster GmbH',
                           strasse='Hauptstraße 1', plz='10115',
                           ort='Berlin')


@pytest.fixture
def rechnung(kunde):
    """1.000,00 netto, 1.190,00 brutto."""
    beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG,
                                   betreff='Beratung', leistungsdatum=HEUTE)
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Beratung', menge=Decimal('1'),
        einheit='LS', einzelpreis=Decimal('1000.00'), steuersatz='19.00')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


@pytest.fixture
def ueberzahlung(kunde, rechnung):
    """1.500,00 eingegangen, 1.190,00 zugeordnet, Rest 310,00."""
    zahlung = Zahlung.objects.create(datum=HEUTE, betrag=Decimal('1500.00'),
                                     kunde=kunde)
    Zahlungszuordnung.objects.create(zahlung=zahlung, beleg=rechnung,
                                     betrag=Decimal('1190.00'))
    return zahlung


class TestDerRest:

    def test_erstattet_mindert_den_rest(self, ueberzahlung):
        ueberzahlung.erstattet = Decimal('310.00')

        assert ueberzahlung.rest == Decimal('0.00')
        assert ueberzahlung.ist_verteilt is True

    def test_teilweise_erstattet_laesst_den_rest_stehen(self, ueberzahlung):
        ueberzahlung.erstattet = Decimal('300.00')

        assert ueberzahlung.rest == Decimal('10.00')

    def test_ganz_erstattet_ohne_zuordnung(self, kunde):
        zahlung = Zahlung.objects.create(
            datum=HEUTE, betrag=Decimal('500.00'), kunde=kunde,
            erstattet=Decimal('500.00'))

        assert zahlung.rest == Decimal('0.00')

    def test_die_rechnung_bleibt_unberuehrt(self, ueberzahlung, rechnung):
        ueberzahlung.erstattet = Decimal('310.00')
        ueberzahlung.save()

        assert services.offener_betrag(rechnung) == Decimal('0.00')
        assert ueberzahlung.zugeordnet == Decimal('1190.00')


class TestWasAbgewiesenWird:

    def test_mehr_erstatten_als_eingegangen(self, kunde):
        zahlung = Zahlung(datum=HEUTE, betrag=Decimal('500.00'), kunde=kunde,
                          erstattet=Decimal('500.01'))

        with pytest.raises(ValidationError) as fehler:
            zahlung.full_clean()

        assert 'erstattet' in fehler.value.message_dict

    def test_ganz_erstatten_ist_zulaessig(self, kunde):
        Zahlung(datum=HEUTE, betrag=Decimal('500.00'), kunde=kunde,
                erstattet=Decimal('500.00')).full_clean()

    def test_zuordnung_ueber_den_nicht_erstatteten_teil(self, kunde,
                                                       rechnung):
        """1.500,00 eingegangen, 400,00 erstattet: frei sind 1.100,00."""
        zahlung = Zahlung.objects.create(
            datum=HEUTE, betrag=Decimal('1500.00'), kunde=kunde,
            erstattet=Decimal('400.00'))
        zuordnung = Zahlungszuordnung(zahlung=zahlung, beleg=rechnung,
                                      betrag=Decimal('1190.00'))

        with pytest.raises(ValidationError) as fehler:
            zuordnung.full_clean()

        assert 'betrag' in fehler.value.message_dict

    def test_zuordnung_bis_zum_nicht_erstatteten_teil(self, kunde,
                                                     rechnung):
        zahlung = Zahlung.objects.create(
            datum=HEUTE, betrag=Decimal('1500.00'), kunde=kunde,
            erstattet=Decimal('310.00'))
        zuordnung = Zahlungszuordnung(zahlung=zahlung, beleg=rechnung,
                                      betrag=Decimal('1190.00'))

        zuordnung.full_clean()


def _formular(zahlung, zuordnung, *, erstattet, betrag='1190.00'):
    return {
        'datum': HEUTE.strftime('%d.%m.%Y'),
        'betrag': str(zahlung.betrag),
        'zahlungsart': zahlung.zahlungsart,
        'erstattet': erstattet,
        'kunde': zahlung.kunde_id or '',
        'zahlername': '',
        'verwendungszweck': '',
        'referenz': '',
        'notiz': 'Überzahlung zurücküberwiesen',
        'version': zahlung.version,
        'zuordnungen-TOTAL_FORMS': '1',
        'zuordnungen-INITIAL_FORMS': '1',
        'zuordnungen-MIN_NUM_FORMS': '0',
        'zuordnungen-MAX_NUM_FORMS': '1000',
        'zuordnungen-0-id': zuordnung.pk,
        'zuordnungen-0-zahlung': zahlung.pk,
        'zuordnungen-0-beleg': zuordnung.beleg_id,
        'zuordnungen-0-betrag': betrag,
        'zuordnungen-0-skonto': '0.00',
        'zuordnungen-0-kuerzung': '0.00',
        'zuordnungen-0-einbehalten': '0.00',
        'zuordnungen-0-notiz': '',
    }


class TestImAdmin:

    def test_erstatten_schliesst_den_rest(self, buero, ueberzahlung):
        url = reverse('admin:faktura_zahlung_change', args=[ueberzahlung.pk])

        antwort = buero.post(url, _formular(
            ueberzahlung, ueberzahlung.zuordnungen.get(), erstattet='310.00'))

        assert antwort.status_code == 302
        ueberzahlung.refresh_from_db()
        assert ueberzahlung.erstattet == Decimal('310.00')
        assert ueberzahlung.rest == Decimal('0.00')

    def test_zu_viel_erstattet_wird_abgewiesen(self, buero, ueberzahlung):
        """Zugeordnet 1.190,00 plus erstattet 311,00 übersteigt 1.500,00;
        abgewiesen über die Prüfung der Zuordnung mit dem Wert aus dem
        Formular."""
        url = reverse('admin:faktura_zahlung_change', args=[ueberzahlung.pk])

        antwort = buero.post(url, _formular(
            ueberzahlung, ueberzahlung.zuordnungen.get(), erstattet='311.00'))

        assert antwort.status_code == 200
        ueberzahlung.refresh_from_db()
        assert ueberzahlung.erstattet == Decimal('0.00')

    def test_ganz_erstattete_fehlen_im_filter_ohne_zuordnung(
            self, buero, kunde):
        offen = Zahlung.objects.create(datum=HEUTE, betrag=Decimal('200.00'),
                                       kunde=kunde)
        erledigt = Zahlung.objects.create(
            datum=HEUTE, betrag=Decimal('300.00'), kunde=kunde,
            erstattet=Decimal('300.00'))

        antwort = buero.get(reverse('admin:faktura_zahlung_changelist'),
                            {'verteilung': 'ohne'})

        treffer = {z.pk for z in antwort.context['cl'].result_list}
        assert offen.pk in treffer
        assert erledigt.pk not in treffer

    def test_ganz_erstattete_fehlen_im_filter_offen(self, buero,
                                                    ueberzahlung):
        Zahlung.objects.filter(pk=ueberzahlung.pk).update(
            erstattet=Decimal('310.00'))

        antwort = buero.get(reverse('admin:faktura_zahlung_changelist'),
                            {'verteilung': 'offen'})

        treffer = {z.pk for z in antwort.context['cl'].result_list}
        assert ueberzahlung.pk not in treffer
