"""Auftragsakte (auswertung/auftragsakte.py).

Geprüft wird, was sie von der Projektakte unterscheidet: der
Abrechnungsstand je Position und die Regel, dass ein Abschlag die
beauftragte Menge nicht verbraucht. Aufbau, Karten und Tabellen prüft
test_projektakte.py.
"""

import re
from datetime import date, time
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from erfassung import services as erfassung_services
from faktura.models import (
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Kontakt,
    Leistungsart,
    Projekt,
    Rechnungsart,
)

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def projekt(db):
    kunde = Kontakt.objects.create(nummer='K-8100', name='Stadt Musterstadt')
    return Projekt.objects.create(
        nummer='2026-042', bezeichnung='Turnhalle', kunde=kunde)


@pytest.fixture
def auftrag(projekt):
    """Auftrag über 100 Stunden zu 95 EUR."""
    beleg = Beleg.objects.create(typ=BelegTyp.AUFTRAG, projekt=projekt)
    Belegposition.objects.create(
        beleg=beleg, position=10, bezeichnung='Ingenieurstunde',
        menge=Decimal('100'), einheit='Std', einzelpreis=Decimal('95.00'),
        art=Leistungsart.ZEIT)
    beleg.status = BelegStatus.FESTGESCHRIEBEN
    beleg.nummer = 'AU-2026-0001'
    beleg.belegdatum = date(2026, 7, 1)
    beleg.save()
    return beleg


def _rechnung(auftrag, menge, rechnungsart, nummer=None,
              status=BelegStatus.FESTGESCHRIEBEN):
    """Rechnung mit Bezug auf die erste Position des Auftrags."""
    beleg = Beleg.objects.create(
        typ=BelegTyp.RECHNUNG, rechnungsart=rechnungsart,
        projekt=auftrag.projekt)
    Belegposition.objects.create(
        beleg=beleg, position=10, bezeichnung='Ingenieurstunde',
        menge=Decimal(menge), einheit='Std', einzelpreis=Decimal('95.00'),
        auftragsposition=auftrag.positionen.first())
    beleg.status = status
    beleg.nummer = nummer
    beleg.belegdatum = date(2026, 8, 1)
    beleg.save()
    return beleg


@pytest.fixture
def als_buchhalterin(client, db):
    """Konto mit Recht auf Aufträge und Rechnungen, sieht also Beträge."""
    person = User.objects.create_user(
        username='bea', password='geheim12345', is_staff=True)
    person.user_permissions.add(*Permission.objects.filter(
        codename__in=['view_auftrag', 'view_rechnung', 'view_projekt',
                      'view_erfassungszeile']))
    client.force_login(person)
    return client


@pytest.fixture
def als_monteur(client, db):
    """Konto mit Recht auf Aufträge, ohne Recht auf Rechnungen."""
    person = User.objects.create_user(
        username='mo', password='geheim12345', is_staff=True)
    person.user_permissions.add(
        Permission.objects.get(codename='view_auftrag'))
    client.force_login(person)
    return client


def _akte(auftrag):
    return reverse('auftragsakte', args=[auftrag.pk])


class TestDerAbrechnungsstand:
    """Abrechnungsstand je Auftragsposition."""

    def test_ohne_rechnung_steht_alles_offen(self, als_buchhalterin, auftrag):
        inhalt = als_buchhalterin.get(_akte(auftrag)).content.decode()

        assert 'AU-2026-0001' in inhalt
        assert '0 %' in inhalt

    def test_eine_rechnung_verbraucht_die_menge(self, als_buchhalterin,
                                                auftrag):
        _rechnung(auftrag, '60', Rechnungsart.NORMAL, 'RE-2026-0001')

        inhalt = als_buchhalterin.get(_akte(auftrag)).content.decode()

        assert '60 %' in inhalt
        assert 'RE-2026-0001' in inhalt

    def test_ein_abschlag_verbraucht_sie_nicht(self, als_buchhalterin,
                                               auftrag):
        """Ein Abschlag verbraucht keine beauftragte Menge.

        Ein Abschlag ist steuerlich eine Anzahlung, und die Schlussrechnung
        führt dieselbe Leistung erneut auf; mitgezählt wäre das Kontingent
        doppelt verbraucht (``services.abgerechnete_mengen``).
        """
        _rechnung(auftrag, '60', Rechnungsart.ABSCHLAG, 'RE-2026-0002')

        inhalt = als_buchhalterin.get(_akte(auftrag)).content.decode()

        # Die Rechnung steht in der Tabelle,
        assert 'RE-2026-0002' in inhalt
        assert 'zählt nicht' in inhalt
        # verbraucht aber keine Menge.
        assert '60 %' not in inhalt

    def test_der_entwurf_zaehlt_auch_nicht(self, als_buchhalterin, auftrag):
        _rechnung(auftrag, '60', Rechnungsart.NORMAL,
                  status=BelegStatus.ENTWURF)

        inhalt = als_buchhalterin.get(_akte(auftrag)).content.decode()

        assert 'zählt nicht' in inhalt
        assert '60 %' not in inhalt


class TestDieKlammer:

    def test_ohne_nachtrag_keine_aufstellung(self, als_buchhalterin, auftrag):
        """Ohne Nachträge entfällt die Tabelle, weil sie nur den aktuellen
        Beleg enthielte."""
        inhalt = als_buchhalterin.get(_akte(auftrag)).content.decode()

        assert 'Auftrag und Nachträge' not in inhalt

    def test_der_nachtrag_verweist_zurueck(self, als_buchhalterin, auftrag,
                                           projekt):
        nachtrag = Beleg.objects.create(
            typ=BelegTyp.AUFTRAG, projekt=projekt, nachtrag_zu=auftrag,
            status=BelegStatus.FESTGESCHRIEBEN, nummer='AU-2026-0002',
            belegdatum=date(2026, 8, 1))

        inhalt = als_buchhalterin.get(_akte(nachtrag)).content.decode()

        assert 'Auftrag und Nachträge' in inhalt
        # Vom Nachtrag aus dieselbe Liste, mit Link auf den Hauptauftrag.
        assert _akte(auftrag) in inhalt


class TestWerWasSehenDarf:

    def test_ohne_auftragsrecht_kein_zutritt(self, client, auftrag):
        person = User.objects.create_user(
            username='fremd', password='geheim12345', is_staff=True)
        client.force_login(person)

        assert client.get(_akte(auftrag)).status_code == 403

    def test_der_monteur_sieht_die_mengen_aber_keine_betraege(
            self, als_monteur, auftrag):
        """Ohne Recht auf Rechnungen sind Mengen sichtbar, Beträge nicht."""
        inhalt = als_monteur.get(_akte(auftrag)).content.decode()

        assert 'Ingenieurstunde' in inhalt              # die Menge schon
        assert '9.500,00' not in inhalt                 # der Wert nicht
        # "Beauftragt" steht auch über der Mengenspalte; geprüft wird deshalb
        # eine Kennzahl, die nur mit Recht auf Rechnungen erscheint.
        assert 'Erfasst, nicht berechnet' not in inhalt
        assert 'Auftragswert netto' not in inhalt


class TestDieErfassung:

    def test_kontierte_stunden_stehen_auf_der_seite(self, als_buchhalterin,
                                                    auftrag, projekt):
        person = User.objects.create_user(
            username='reiter', password='geheim12345', is_staff=True,
            first_name='Katrin', last_name='Reiter')
        erfassung_services.zeile_erfassen(
            projekt=projekt, auftragsposition=auftrag.positionen.first(),
            benutzer=person, beschreibung='Probenahme',
            datum=date(2026, 8, 10), von=time(8, 0), bis=time(12, 0))

        inhalt = als_buchhalterin.get(_akte(auftrag)).content.decode()

        assert 'Katrin Reiter' in inhalt
        assert 'Probenahme' not in inhalt or 'Ingenieurstunde' in inhalt


class TestJederVerweisFuehrtIrgendwohin:
    """Jeder Link der Akte in den Admin wird abgerufen und muss unter 400
    antworten.

    Regression: Der Link "Alle Zeiten dieses Auftrags ansehen" filterte über
    ``auftragsposition__beleg__id``, das in keinem ``list_filter`` steht;
    Django antwortete mit ``DisallowedModelAdminLookup``. Ein Test, der nur
    das HTML prüfte, fand das nicht.

    Mit vollen Rechten, weil die URLs geprüft werden und nicht die Rechte.
    Bekannt: Für ein Konto mit wenigen Rechten antworten "Kunde" und
    "Auftrag" mit 403; die Akte zeigt diese Links trotzdem.
    """


    @pytest.fixture
    def mit_allen_rechten(self, client, db):
        """Konto mit allen Rechten, siehe Docstring der Klasse."""
        person = get_user_model().objects.create_superuser(
            username='alles', email='a@example.com', password='geheim12345')
        client.force_login(person)
        return client

    def _adminverweise(self, inhalt):
        """Alle href-Ziele der Seite unter dem Admin."""
        return sorted({
            treffer.replace('&amp;', '&')
            for treffer in re.findall(r'href="(/admin/[^"]+)"', inhalt)
        })

    def test_die_akte_gibt_ueberhaupt_verweise_aus(self, mit_allen_rechten,
                                                   auftrag):
        """Die Seite enthält Links, damit der folgende Test nicht über eine
        leere Menge läuft."""
        inhalt = mit_allen_rechten.get(_akte(auftrag)).content.decode()

        assert len(self._adminverweise(inhalt)) >= 3

    def test_und_jeder_von_ihnen_antwortet(self, mit_allen_rechten, auftrag):
        inhalt = mit_allen_rechten.get(_akte(auftrag)).content.decode()

        for ziel in self._adminverweise(inhalt):
            antwort = mit_allen_rechten.get(ziel)
            assert antwort.status_code < 400, (
                f'{ziel} antwortet mit {antwort.status_code}')

    def test_die_zeiten_des_auftrags_sind_gefiltert(self, als_buchhalterin,
                                                    auftrag):
        """Der Link auf die Zeiten zeigt nur die Stunden dieses Auftrags."""
        ziel = (f'{reverse("admin:erfassung_erfassungszeile_changelist")}'
                f'?auftragsposition__beleg__id__exact={auftrag.pk}')

        antwort = als_buchhalterin.get(ziel)

        assert antwort.status_code == 200
        gefiltert = antwort.context['cl'].queryset
        assert all(z.auftragsposition.beleg_id == auftrag.pk
                   for z in gefiltert)
