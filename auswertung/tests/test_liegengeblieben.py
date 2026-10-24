"""Seite "Nicht abgerechnet" (auswertung/liegengeblieben.py).

Geprüft wird, dass beide Quellen erscheinen, die Reihenfolge der
Dringlichkeit folgt und Vorhaben ohne offene Posten fehlen.
"""

import re
from datetime import time, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from erfassung import services as erfassung_services
from erfassung.models import Eingangsrechnung, Fremdleistung
from faktura.models import (
    BelegStatus,
    Katalogposition,
    Kontakt,
    Leistungsart,
    Projekt,
)

pytestmark = pytest.mark.django_db

User = get_user_model()
LISTE = reverse('liegengeblieben')


@pytest.fixture
def kunde(db):
    return Kontakt.objects.create(nummer='K-7000', name='Stadt Musterstadt')


@pytest.fixture
def stunde(db):
    return Katalogposition.objects.create(
        bezeichnung='Ingenieurstunde', einheit='Std',
        einzelpreis=Decimal('95.00'), kontierbar=True, art=Leistungsart.ZEIT)


@pytest.fixture
def person(db):
    return User.objects.create_user(
        username='reiter', password='geheim12345', is_staff=True)


@pytest.fixture
def als_chefin(client, db):
    person = User.objects.create_user(
        username='bea', password='geheim12345', is_staff=True)
    person.user_permissions.add(*Permission.objects.filter(
        codename__in=['view_rechnung', 'view_projekt']))
    client.force_login(person)
    return client


def _projekt(kunde, nummer='2026-042'):
    return Projekt.objects.create(
        nummer=nummer, bezeichnung=f'Vorhaben {nummer}', kunde=kunde)


def _stunden(projekt, stunde, person, *, tage_zurueck=1, bis=time(12, 0)):
    return erfassung_services.zeile_erfassen(
        projekt=projekt, leistung=stunde, benutzer=person,
        beschreibung='Arbeit',
        datum=timezone.localdate() - timedelta(days=tage_zurueck),
        von=time(8, 0), bis=bis)


def _labor(projekt, *, nummer='AL-1', betrag='96.00', tage_zurueck=1):
    """Laborposition über 96,00 Einkauf, offen zum Einkaufspreis bewertet."""
    labor, _ = Kontakt.objects.get_or_create(
        name='ISARTAL', defaults={'ist_kunde': False, 'ist_lieferant': True})
    rechnung = Eingangsrechnung.objects.create(
        lieferant=labor, nummer=nummer,
        datum=timezone.localdate() - timedelta(days=tage_zurueck),
        betrag_netto=Decimal(betrag))
    return Fremdleistung.objects.create(
        rechnung=rechnung, projekt=projekt, bezeichnung='Paket 4711',
        menge=Decimal('1'), einkaufspreis=Decimal('96.00'))


def _zeilen(inhalt, tabelle=0) -> list[str]:
    """Zeilen des ``<tbody>`` der Tabelle mit Index ``tabelle`` als Text.

    Nur der Rumpf, weil die Kopfzeile dieselbe CSS-Klasse hat und eine
    Prüfung der Sortierung sonst den Kopf mitläse (wie in
    erfassung/tests/hilfen.py).
    """
    rumpfe = re.findall(r'<tbody>(.*?)</tbody>', inhalt, re.S)
    if len(rumpfe) <= tabelle:
        return []
    return [
        re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', z)).strip()
        for z in re.findall(r'<tr[^>]*>(.*?)</tr>', rumpfe[tabelle], re.S)
    ]


def _fremde_zeilen(inhalt) -> list[str]:
    """Zeilen der Tabelle "Eingangsrechnungen ohne vollständige Zuordnung".

    Ohne offene Leistung fehlt die erste Tabelle, die zweite ist dann die
    einzige.
    """
    rumpfe = re.findall(r'<tbody>', inhalt)
    return _zeilen(inhalt, tabelle=len(rumpfe) - 1)


class TestWasAufDerListeSteht:

    def test_beide_quellen_kommen_zusammen(self, als_chefin, kunde, stunde,
                                           person):
        projekt = _projekt(kunde)
        _stunden(projekt, stunde, person)          # 4 Std à 95 = 380
        _labor(projekt)                            # 1 × 96 im Einkauf

        inhalt = als_chefin.get(LISTE).content.decode()

        assert '380,00' in inhalt
        assert '96,00' in inhalt
        assert '476,00' in inhalt                  # die Summe daneben

    def test_das_groesste_steht_oben(self, als_chefin, kunde, stunde, person):
        klein = _projekt(kunde, '2026-001')
        gross = _projekt(kunde, '2026-002')
        _stunden(klein, stunde, person, bis=time(9, 0))
        _stunden(gross, stunde, person, bis=time(16, 0))

        zeilen = _zeilen(als_chefin.get(LISTE).content.decode())

        assert zeilen[0].startswith('2026-002')

    def test_ein_vorhaben_ohne_offenes_taucht_nicht_auf(
            self, als_chefin, kunde, stunde, person):
        """Ein Vorhaben ohne offene Posten erscheint nicht."""
        _projekt(kunde, '2026-999')      # ohne alles
        _projekt(kunde, '2026-001')

        inhalt = als_chefin.get(LISTE).content.decode()

        assert '2026-999' not in inhalt

    def test_abgerechnetes_verschwindet_von_der_liste(
            self, als_chefin, kunde, stunde, person):
        projekt = _projekt(kunde)
        _stunden(projekt, stunde, person)
        beleg, _ = erfassung_services.in_rechnung_uebernehmen(
            zeilen=erfassung_services.Erfassungszeile.objects.all())
        beleg.status = BelegStatus.FESTGESCHRIEBEN
        beleg.nummer = 'RE-1'
        beleg.save()

        inhalt = als_chefin.get(LISTE).content.decode()

        assert 'Nichts offen' in inhalt

    def test_der_weg_fuehrt_in_die_akte_und_in_die_erfassung(
            self, als_chefin, kunde, stunde, person):
        projekt = _projekt(kunde)
        _stunden(projekt, stunde, person)

        inhalt = als_chefin.get(LISTE).content.decode()

        assert reverse('projektakte', args=[projekt.pk]) in inhalt
        assert f'?projekt__id__exact={projekt.pk}' in inhalt


class TestWieLangeEsSchonLiegt:
    """Alter des ältesten Postens je Vorhaben."""

    def test_das_alter_steht_daneben(self, als_chefin, kunde, stunde, person):
        projekt = _projekt(kunde)
        _stunden(projekt, stunde, person, tage_zurueck=10)

        inhalt = als_chefin.get(LISTE).content.decode()

        assert '(10 Tage)' in inhalt

    def test_ab_sechzig_tagen_wird_es_rot(self, als_chefin, kunde, stunde,
                                          person):
        projekt = _projekt(kunde)
        _stunden(projekt, stunde, person, tage_zurueck=61)

        zeilen = _zeilen(als_chefin.get(LISTE).content.decode())
        inhalt = als_chefin.get(LISTE).content.decode()

        assert '(61 Tage)' in zeilen[0]
        assert 'text-red-600' in inhalt

    def test_die_aeltere_quelle_gewinnt(self, als_chefin, kunde, stunde,
                                        person):
        """Maßgeblich ist der älteste Posten über beide Quellen."""
        projekt = _projekt(kunde)
        _stunden(projekt, stunde, person, tage_zurueck=3)
        _labor(projekt, tage_zurueck=40)

        inhalt = als_chefin.get(LISTE).content.decode()

        assert '(40 Tage)' in inhalt


class TestDieFremdenRechnungen:

    def test_eine_nicht_verteilte_rechnung_steht_unten(self, als_chefin,
                                                       kunde):
        projekt = _projekt(kunde)
        _labor(projekt, nummer='AL-4711', betrag='500.00')

        inhalt = als_chefin.get(LISTE).content.decode()

        assert 'AL-4711' in inhalt
        assert '404,00' in inhalt      # 500,00 abzüglich 96,00 zugeordnet

    def test_eine_vollstaendig_verteilte_nicht(self, als_chefin, kunde):
        projekt = _projekt(kunde)
        _labor(projekt, nummer='AL-fertig', betrag='96.00')

        inhalt = als_chefin.get(LISTE).content.decode()

        assert 'AL-fertig' not in inhalt
        assert 'vollständig auf Projekte verteilt' in inhalt

    def test_die_teilweise_verteilte_nennt_ihr_projekt(self, als_chefin,
                                                       kunde):
        """Das Projekt der verteilten Positionen steht an der Rechnung, als
        wahrscheinlicher Ort des Rests."""
        projekt = _projekt(kunde, '2026-077')
        _labor(projekt, nummer='AL-4711', betrag='500.00')

        inhalt = als_chefin.get(LISTE).content.decode()
        (zeile,) = _fremde_zeilen(inhalt)

        assert 'AL-4711' in zeile
        assert '2026-077' in zeile
        assert reverse('projektakte', args=[projekt.pk]) in inhalt

    def test_eine_rechnung_ohne_positionen_ist_nicht_verteilt(
            self, als_chefin, kunde):
        labor = Kontakt.objects.create(name='ISARTAL', ist_kunde=False,
                                       ist_lieferant=True)
        Eingangsrechnung.objects.create(
            lieferant=labor, nummer='AL-leer', datum=timezone.localdate(),
            betrag_netto=Decimal('120.00'))

        (zeile,) = _fremde_zeilen(als_chefin.get(LISTE).content.decode())

        assert 'AL-leer' in zeile
        assert 'noch nicht verteilt' in zeile


class TestWerDasSehenDarf:

    def test_ohne_das_recht_auf_rechnungen_bleibt_die_tuer_zu(
            self, client, db, kunde):
        """Ohne Recht auf Rechnungen ist die Seite gesperrt."""
        person = User.objects.create_user(
            username='mo', password='geheim12345', is_staff=True)
        person.user_permissions.add(
            Permission.objects.get(codename='view_projekt'))
        client.force_login(person)

        assert client.get(LISTE).status_code == 403

    def test_ohne_anmeldung_geht_es_zum_anmeldeschirm(self, client, db):
        antwort = client.get(LISTE)

        assert antwort.status_code == 302
        assert '/admin/login/' in antwort['Location']

    def test_im_menue_steht_sie_fuer_die_richtigen(self, als_chefin, kunde,
                                                   stunde, person):
        projekt = _projekt(kunde)
        _stunden(projekt, stunde, person)

        inhalt = als_chefin.get(reverse('admin:index')).content.decode()

        assert LISTE in inhalt
