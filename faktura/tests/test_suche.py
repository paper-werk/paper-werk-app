"""Schnellsuche (Strg+K), faktura/suche.py.

Geprüft über Unfolds Endpunkt ``admin:search``, den die Command Palette
aufruft; jedem Treffer wird gefolgt, um tote Links auszuschließen.
"""

import re
from datetime import date
from decimal import Decimal

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.urls import reverse

from faktura import services, suche
from faktura.models import BelegTyp, Kontakt, Projekt

User = get_user_model()


@pytest.fixture(autouse=True)
def ohne_zwischenspeicher():
    """Leert den Cache, weil Unfold Treffer fünf Minuten je Benutzer und
    Begriff cacht."""
    cache.clear()
    yield
    cache.clear()


@pytest.mark.parametrize('begriff,betrag', [
    ('1.445,14', Decimal('1445.14')),
    ('1445,14', Decimal('1445.14')),
    ('1445.14', Decimal('1445.14')),
    ('12.000,00 €', Decimal('12000.00')),
    ('891,5', Decimal('891.5')),
    ('2026', None),          # eine Jahreszahl, keine Summe
    ('RE-2026', None),
    ('1.445', None),         # ohne Cent mehrdeutig
])
def test_was_als_betrag_gilt(begriff, betrag):
    assert suche.als_betrag(begriff) == betrag


@pytest.fixture
def bestand(db):
    kunde = Kontakt.anlegen(nummer='K-4711', name='Bäckerei Wimmer GmbH',
                            strasse='Markt 1', plz='84028', ort='Landshut')
    projekt = Projekt.objects.create(nummer='2026-077', kunde=kunde,
                                     bezeichnung='Backstube umbauen')
    rechnung = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.RECHNUNG,
                                      betreff='Elektrik Backstube')
    rechnung.leistungsdatum = date(2026, 9, 1)
    rechnung.save()
    services.position_hinzufuegen(
        beleg=rechnung, bezeichnung='Arbeit', menge=Decimal('1'),
        einzelpreis=Decimal('1214.40'), steuersatz='19.00')
    rechnung = services.beleg_festschreiben(beleg_id=rechnung.pk)
    angebot = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.ANGEBOT,
                                     betreff='Backofen anschließen')
    return {'kunde': kunde, 'projekt': projekt, 'rechnung': rechnung,
            'angebot': angebot}


def _ziel(akte: str, formular: str, pk) -> str:
    """Erwartetes Ziel eines Treffers: die Akte, ohne ``auswertung`` (nur
    Kern, paperwerk/settings/kern.py) das Formular."""
    if apps.is_installed('auswertung'):
        return reverse(akte, args=[pk])
    return reverse(formular, args=[pk])


def _suche(client, begriff) -> list[tuple[str, str]]:
    """``(Titel, URL)`` der Treffer, wie die Command Palette sie zeigt."""
    antwort = client.get(reverse('admin:search'), {'s': begriff})
    assert antwort.status_code == 200
    return [(t.title, str(t.link)) for t in antwort.context['results']]


@pytest.mark.django_db
class TestWasGefundenWird:

    def test_der_kunde_fuehrt_in_die_kundenakte(self, admin_client, bestand):
        treffer = dict(_suche(admin_client, 'wimmer'))

        verweis = treffer['K-4711 · Bäckerei Wimmer GmbH']
        assert verweis == _ziel('kundenakte', 'admin:faktura_kontakt_change',
                                bestand['kunde'].pk)
        assert admin_client.get(verweis).status_code == 200

    def test_das_projekt_fuehrt_in_die_projektakte(self, admin_client, bestand):
        treffer = dict(_suche(admin_client, 'backstube'))

        verweis = treffer['2026-077 · Backstube umbauen']
        assert verweis == _ziel('projektakte', 'admin:faktura_projekt_change',
                                bestand['projekt'].pk)
        assert admin_client.get(verweis).status_code == 200

    def test_die_rechnung_nach_nummer_fuehrt_in_die_rechnungsakte(
            self, admin_client, bestand):
        nummer = bestand['rechnung'].nummer

        treffer = dict(_suche(admin_client, nummer.lower()))

        verweis = treffer[f'{nummer} · Elektrik Backstube']
        assert verweis == _ziel('rechnungsakte', 'admin:faktura_rechnung_change',
                                bestand['rechnung'].pk)
        assert admin_client.get(verweis).status_code == 200

    def test_der_betrag_vom_kontoauszug_findet_die_rechnung(
            self, admin_client, bestand):
        """Der Bruttobetrag vom Kontoauszug findet die Rechnung (1.214,40 netto
        sind 1.445,14 brutto)."""
        treffer = _suche(admin_client, '1.445,14')

        assert [t for t, _ in treffer] == [
            f'{bestand["rechnung"].nummer} · Elektrik Backstube']

    def test_der_entwurf_fuehrt_ins_formular(self, admin_client, bestand):
        """Ein Angebot ohne Akte führt ins Formular."""
        treffer = dict(_suche(admin_client, 'backofen'))

        (verweis,) = [v for t, v in treffer.items() if 'Backofen' in t]
        assert verweis == reverse('admin:faktura_angebot_change',
                                  args=[bestand['angebot'].pk])

    def test_ein_buchstabe_sucht_nichts(self, admin_client, bestand):
        assert not [t for t, _ in _suche(admin_client, 'w') if '·' in t]


@pytest.mark.django_db
class TestNurWasManSehenDarf:

    def test_ohne_rechte_auf_rechnungen_und_kontakte(self, client, bestand):
        person = User.objects.create_user('mo', password='x', is_staff=True)
        person.user_permissions.add(
            Permission.objects.get(codename='view_angebot'))
        client.force_login(person)

        titel = [t for t, _ in _suche(client, 'backstube')]

        assert titel == []          # Projekt und Rechnung: kein Recht
        titel = [t for t, _ in _suche(client, 'backofen')]
        assert any('Backofen' in t for t in titel)

    def test_der_betrag_verraet_nichts(self, client, bestand):
        person = User.objects.create_user('mo', password='x', is_staff=True)
        person.user_permissions.add(
            Permission.objects.get(codename='view_angebot'))
        client.force_login(person)

        assert _suche(client, '1.445,14') == []


@pytest.mark.django_db
def test_die_daten_anderer_modelle_bleiben_draussen(admin_client, bestand):
    """``search_models`` ist aus, weil Unfold sonst jedes Modell mit
    search_fields durchsucht und ins Formular führt. Geprüft mit einem
    Adressfeld, das nur so gefunden würde."""
    titel = [t for t, _ in _suche(admin_client, 'markt 1')]

    assert not [t for t in titel if re.search(r'markt', t, re.I)]
