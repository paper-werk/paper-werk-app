"""Optimistic Locking an Zahlung, Eingangsrechnung, Abnahme, Projekt,
Kontakt und Ansprechpartner (``core/optimistic_locking.py``).

Ablauf wie in ``test_gleichzeitig.py``: Zwei Clients laden dieselbe
Änderungsseite, A speichert ``notiz``, danach sendet B seine beim Laden
gelesenen Formulardaten. Erwartet: B erhält ``VersionKonflikt``, in der
Datenbank steht A's Notiz.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from erfassung.models import Eingangsrechnung, Fremdleistung
from faktura import services
from faktura.models import (
    Abnahme,
    Abnahmeart,
    Ansprechpartner,
    Beleg,
    BelegTyp,
    Kontakt,
    Kontaktart,
    Kontaktweg,
    Projekt,
    Zahlung,
    Zahlungszuordnung,
)
from faktura.tests.test_gleichzeitig import HINWEIS, formulardaten, gesichert, setze

HEUTE = date(2026, 10, 14)


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-3000', name='Muster GmbH', strasse='Hauptstraße 1',
        plz='10115', ort='Berlin')


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(nummer='2026-100', bezeichnung='Halle',
                                  kunde=kunde)


@pytest.fixture
def ansprechpartner(kunde):
    return Ansprechpartner.objects.create(kontakt=kunde, vorname='Eva',
                                          nachname='Klein')


@pytest.fixture
def zahlung(kunde):
    return Zahlung.objects.create(datum=HEUTE, betrag=Decimal('100.00'),
                                  kunde=kunde)


@pytest.fixture
def eingangsrechnung(db):
    labor = Kontakt.objects.create(ist_kunde=False, ist_lieferant=True,
                                   name='Labor')
    return Eingangsrechnung.objects.create(
        lieferant=labor, nummer='L-1', datum=HEUTE,
        betrag_netto=Decimal('50.00'))


@pytest.fixture
def abnahme(projekt):
    auftrag = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.AUFTRAG,
                                     betreff='Planung')
    services.position_hinzufuegen(
        beleg=auftrag, bezeichnung='Planung', menge=Decimal('1'),
        einheit='pausch', einzelpreis=Decimal('1000.00'),
        steuersatz='19.00')
    auftrag = services.beleg_festschreiben(beleg_id=auftrag.pk)
    return Abnahme.objects.create(auftrag=auftrag, art=Abnahmeart.GESAMT,
                                  abgenommen_am=HEUTE)


@pytest.fixture
def zwei(db):
    """Zwei Clients A und B mit Superuser-Konten."""
    benutzer = get_user_model()
    anna = benutzer.objects.create_superuser(
        username='anna', email='anna@example.invalid', password='x',
        first_name='Anna', last_name='Bach')
    bea = benutzer.objects.create_superuser(
        username='bea', email='bea@example.invalid', password='x')
    a, b = Client(), Client()
    a.force_login(anna)
    b.force_login(bea)
    return a, b


MASKEN = ['zahlung', 'eingangsrechnung', 'abnahme', 'projekt', 'kontakt',
          'ansprechpartner']


@pytest.mark.django_db
@pytest.mark.parametrize('maske', MASKEN)
def test_b_ueberschreibt_a_nicht(maske, request, zwei):
    objekt = request.getfixturevalue('kunde' if maske == 'kontakt' else maske)
    opts = objekt._meta
    adresse = reverse(f'admin:{opts.app_label}_{opts.model_name}_change',
                      args=[objekt.pk])
    a, b = zwei
    daten_a = formulardaten(a.get(adresse), opts.model_name)
    daten_b = formulardaten(b.get(adresse), opts.model_name)
    assert 'version_beim_laden' in daten_b

    setze(daten_a, 'notiz', 'Von A')
    assert gesichert(a.post(adresse, daten_a))

    setze(daten_b, 'notiz', 'Von B')
    antwort = b.post(adresse, daten_b)

    assert antwort.status_code == 200
    text = antwort.content.decode()
    assert HINWEIS in text
    assert 'Letzte Änderung: Anna Bach' in text
    objekt.refresh_from_db()
    assert objekt.notiz == 'Von A'


def _version(objekt):
    return type(objekt).objects.values_list('version', flat=True).get(
        pk=objekt.pk)


@pytest.mark.django_db
class TestInlineZeilenInkrementierenDasElternobjekt:
    """Schreibzugriffe auf Inline-Zeilen außerhalb des Admins (Services,
    Import) inkrementieren die Version des Elternobjekts."""

    def test_adresse_und_kontaktweg_am_kontakt(self, kunde):
        vorher = _version(kunde)
        adresse = kunde.adressen.first()
        adresse.ort = 'Potsdam'
        adresse.save()
        weg = Kontaktweg.objects.create(kontakt=kunde, art=Kontaktart.EMAIL,
                                        wert='info@example.invalid')
        weg.delete()
        assert _version(kunde) == vorher + 3

    def test_ansprechpartner_am_kontakt(self, kunde, ansprechpartner):
        vorher = _version(kunde)
        ansprechpartner.funktion = 'Bauleitung'
        ansprechpartner.save()
        assert _version(kunde) == vorher + 1

    def test_kontaktweg_am_ansprechpartner(self, ansprechpartner):
        vorher = _version(ansprechpartner)
        Kontaktweg.objects.create(ansprechpartner=ansprechpartner,
                                  art=Kontaktart.EMAIL,
                                  wert='eva@example.invalid')
        assert _version(ansprechpartner) == vorher + 1

    def test_zuordnung_an_der_zahlung(self, zahlung, kunde):
        rechnung = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)
        vorher = _version(zahlung)
        Zahlungszuordnung.objects.create(zahlung=zahlung, beleg=rechnung,
                                         betrag=Decimal('100.00'))
        assert _version(zahlung) == vorher + 1

    def test_fremdleistung_an_der_eingangsrechnung(self, eingangsrechnung,
                                                    projekt):
        vorher = _version(eingangsrechnung)
        Fremdleistung.objects.create(
            rechnung=eingangsrechnung, projekt=projekt, bezeichnung='Probe',
            menge=Decimal('1'), einkaufspreis=Decimal('50.00'))
        assert _version(eingangsrechnung) == vorher + 1

    def test_belegposition_am_beleg(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        vorher = Beleg.objects.values_list('version', flat=True).get(
            pk=beleg.pk)
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='X', menge=Decimal('1'),
            einzelpreis=Decimal('1.00'), steuersatz='19.00')
        assert Beleg.objects.values_list('version', flat=True).get(
            pk=beleg.pk) > vorher
