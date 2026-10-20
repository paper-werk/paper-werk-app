"""Stunden auf einer Pauschale.

Das Controlling zeigt die Zeit, die in einer Pauschale steckt. Uhrzeiten auf
einer Pauschale machen die Zeile zu Aufwand: nicht abrechenbar, ohne Menge.
Abgerechnet wird die Pauschale über eine Zeile ohne Uhrzeit, sonst stünde
sie je Zeitzeile auf der Rechnung.
"""

from datetime import time
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from auswertung.zuordnung import Umfang
from erfassung.models import Erfassungszeile, Zustand
from erfassung.services import in_rechnung_uebernehmen, zeile_erfassen
from faktura.models import (
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Leistungsart,
)


@pytest.fixture
def als_mitarbeiter(client, mitarbeiter):
    mitarbeiter.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='erfassung',
        codename__in=['add_erfassungszeile', 'view_erfassungszeile',
                      'change_erfassungszeile']))
    client.force_login(mitarbeiter)
    return client


@pytest.fixture
def planung(projekt):
    """Pauschale im festgeschriebenen Auftrag, etwa eine Ausführungsplanung,
    über ``bulk_create`` wie in conftest.py."""
    auftrag = Beleg.objects.create(
        typ=BelegTyp.AUFTRAG, status=BelegStatus.FESTGESCHRIEBEN,
        nummer='AU-2026-0077', projekt=projekt)
    return Belegposition.objects.bulk_create([
        Belegposition(
            beleg=auftrag, position='01.0020',
            bezeichnung='Ausführungsplanung', menge=Decimal('1'),
            einheit='pausch', einzelpreis=Decimal('8500.00'),
            art=Leistungsart.PAUSCHALE)
    ])[0]


def _stunden(projekt, mitarbeiter, planung, von, bis):
    return zeile_erfassen(
        projekt=projekt, benutzer=mitarbeiter, beschreibung='Planung',
        auftragsposition=planung, von=time(*von), bis=time(*bis))


@pytest.mark.django_db
class TestDieZeile:

    def test_mit_uhrzeit_ist_sie_aufwand(self, projekt, mitarbeiter,
                                         planung):
        zeile = _stunden(projekt, mitarbeiter, planung, (8, 0), (11, 30))

        assert zeile.dauer_minuten == 210
        assert zeile.abrechenbar is False
        assert zeile.menge is None
        assert zeile.zustand == Zustand.NICHT_ABRECHENBAR
        assert zeile.dauer_anzeige == '3:30'

    def test_ohne_uhrzeit_rechnet_sie_die_pauschale_ab(
            self, projekt, mitarbeiter, planung):
        zeile = zeile_erfassen(
            projekt=projekt, benutzer=mitarbeiter, beschreibung='Planung',
            auftragsposition=planung)

        assert zeile.menge == Decimal('1')
        assert zeile.abrechenbar is True
        assert zeile.dauer_anzeige == ''

    def test_eine_zeitleistung_bleibt_abrechenbar(
            self, projekt, mitarbeiter, auftragsposition):
        """Zeilen auf Zeitleistungen bleiben abrechenbar."""
        zeile = zeile_erfassen(
            projekt=projekt, benutzer=mitarbeiter, beschreibung='Planung',
            auftragsposition=auftragsposition, von=time(8), bis=time(10))

        assert zeile.abrechenbar is True


@pytest.mark.django_db
class TestDieRechnung:

    def test_die_pauschale_steht_einmal_drauf(self, projekt, mitarbeiter,
                                              planung):
        """Zehn Stunden Aufwand und eine Pauschalzeile ergeben die Pauschale
        über 8.500 einmal."""
        zeilen = [
            _stunden(projekt, mitarbeiter, planung, (8, 0), (13, 0)),
            _stunden(projekt, mitarbeiter, planung, (13, 0), (18, 0)),
            zeile_erfassen(projekt=projekt, benutzer=mitarbeiter,
                           beschreibung='Planung', auftragsposition=planung),
        ]

        rechnung, vorschau = in_rechnung_uebernehmen(zeilen=zeilen)

        positionen = list(rechnung.positionen.all())
        assert [(p.menge, p.einzelpreis) for p in positionen] == [
            (Decimal('1.000'), Decimal('8500.00'))]
        assert len(vorschau.uebergangen) == 2


class TestControlling:

    def test_stunden_auf_der_pauschale_zaehlen_als_zeit(self):
        umfang = Umfang.aus(art=Leistungsart.PAUSCHALE, minuten=600,
                            menge=None, einheit='pausch', zeilen=2)

        assert umfang.minuten == 600
        assert umfang.mengen == ()

    def test_alter_bestand_ohne_menge_je_zeile_eine_pauschale(self):
        umfang = Umfang.aus(art=Leistungsart.PAUSCHALE, minuten=0,
                            menge=None, einheit='pausch', zeilen=2)

        assert umfang.mengen == (('pausch', Decimal('2')),)


@pytest.mark.django_db
class TestDieMaske:

    def test_hinweis_unter_von_und_bis_nur_bei_der_pauschale(
            self, als_mitarbeiter):
        """Der Hinweis erscheint unter von und bis nur bei einer Pauschale."""
        seite = als_mitarbeiter.get(reverse(
            'admin:erfassung_erfassungszeile_add')).content.decode()

        assert 'den Zustand „Nicht abrechenbar“' in seite
        assert ("erfassungsart() == &#x27;pauschale&#x27;" in seite)


@pytest.mark.django_db
class TestDasUhrzeitfeld:
    """Das Uhrzeitfeld akzeptiert jede Minute."""

    def test_krumme_minuten_werden_gespeichert(self, als_mitarbeiter,
                                               projekt, auftragsposition):
        als_mitarbeiter.post(reverse('admin:erfassung_erfassungszeile_add'), {
            'datum': timezone.localdate().strftime('%d.%m.%Y'),
            'projekt': projekt.pk, 'auftragsposition': auftragsposition.pk,
            'von': '07:52', 'bis': '09:13', 'menge': '',
            'beschreibung': 'Stundenzettel',
        })

        zeile = Erfassungszeile.objects.get(beschreibung='Stundenzettel')
        assert zeile.dauer_minuten == 81

