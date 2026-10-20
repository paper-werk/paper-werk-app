"""Optimierte Abfragen der Erfassung gegen eine Referenzberechnung.

``personalkosten_je_projekt`` bewertet die Zeit in der Datenbank, und die
Datenbank filtert vollständige Eingangsrechnungen vorab. Referenz für die
Personalkosten ist ``Kostensatz.satz_am``, je Zeile angewandt und je
Projekt gerundet.
"""

from datetime import date, time
from decimal import Decimal

import pytest
from django.contrib import admin
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core import rechnen
from erfassung import services
from erfassung.models import (
    Eingangsrechnung,
    Erfassungszeile,
    Fremdleistung,
    Kostensatz,
)
from faktura.models import Kontakt, Projekt

pytestmark = pytest.mark.django_db


def _alte_regel(*, nur_laufende=True, projekte=None):
    """Referenz: Personalkosten mit ``satz_am`` je Zeile in Python."""
    verlauf = Kostensatz.verlauf()
    zeilen = Erfassungszeile.objects.filter(dauer_minuten__gt=0)
    if nur_laufende:
        zeilen = zeilen.filter(projekt__abgeschlossen=False)
    if projekte is not None:
        zeilen = zeilen.filter(projekt__in=projekte)
    je_projekt, ohne, minuten = {}, set(), 0
    for z in zeilen:
        satz = Kostensatz.satz_am(verlauf, z.benutzer_id, z.datum)
        if satz is None:
            ohne.add(z.benutzer_id)
            minuten += z.dauer_minuten
            continue
        je_projekt[z.projekt_id] = (je_projekt.get(z.projekt_id, Decimal('0'))
                                    + Decimal(z.dauer_minuten) / 60 * satz)
    return ({k: rechnen.auf_cent(v) for k, v in je_projekt.items()},
            ohne, minuten)


@pytest.fixture
def zweites_projekt(kunde):
    return Projekt.objects.create(nummer='2026-043', bezeichnung='Halle Süd',
                                  kunde=kunde)


@pytest.fixture
def stunden(projekt, zweites_projekt, abgeschlossenes_projekt, zeitleistung,
            mitarbeiter, kollege, django_user_model):
    """Testdaten mit ungeraden Minuten und Sätzen, einer Lohnerhöhung im
    Zeitraum, einer Person mit Satz erst ab Juni und einer ohne Satz."""
    Kostensatz.objects.create(benutzer=mitarbeiter, gueltig_ab=date(2026, 1, 1),
                              satz=Decimal('47.33'))
    Kostensatz.objects.create(benutzer=mitarbeiter, gueltig_ab=date(2026, 7, 1),
                              satz=Decimal('49.71'))
    Kostensatz.objects.create(benutzer=kollege, gueltig_ab=date(2026, 6, 1),
                              satz=Decimal('38.17'))
    aushilfe = django_user_model.objects.create_user(
        username='aushilfe', password='geheim12345', is_staff=True)

    stuecke = [(8, 0, 9, 7), (9, 7, 11, 20), (11, 20, 11, 33), (13, 0, 16, 59)]
    for monat in (5, 6, 7, 8):
        for tag in (4, 18):
            for person in (mitarbeiter, kollege, aushilfe):
                for ziel in (projekt, zweites_projekt):
                    for v1, v2, b1, b2 in stuecke[:3 if ziel == projekt else 1]:
                        services.zeile_erfassen(
                            projekt=ziel, benutzer=person,
                            leistung=zeitleistung, beschreibung='Arbeit',
                            datum=date(2026, monat, tag), von=time(v1, v2),
                            bis=time(b1, b2))
    # Der Service lehnt abgeschlossene Projekte ab; die Stunden werden
    # deshalb direkt angelegt.
    Erfassungszeile.objects.create(
        projekt=abgeschlossenes_projekt, benutzer=mitarbeiter,
        leistung=zeitleistung, beschreibung='Altlast', datum=date(2026, 7, 2),
        von=time(8, 0), bis=time(10, 17), dauer_minuten=137)
    return aushilfe


class TestPersonalkosten:
    """R-052 bis R-054: Berechnung in SQL gegen ``satz_am``."""

    @pytest.mark.parametrize('nur_laufende', [True, False])
    def test_wie_die_alte_regel(self, stunden, nur_laufende):
        ergebnis = services.personalkosten_je_projekt(nur_laufende=nur_laufende)

        je_projekt, ohne, minuten = _alte_regel(nur_laufende=nur_laufende)
        assert ergebnis.je_projekt == je_projekt
        assert ergebnis.ohne_satz == ohne
        assert ergebnis.minuten_ohne_satz == minuten

    def test_der_bestand_prueft_wirklich_etwas(self, stunden, kollege):
        """Gegenprobe: Kosten auf beiden laufenden Projekten, zwei Personen
        mit Lücken (eine ganz, eine bis Ende Mai)."""
        ergebnis = services.personalkosten_je_projekt()

        assert len(ergebnis.je_projekt) == 2
        assert ergebnis.ohne_satz == {stunden.pk, kollege.pk}

    def test_eingeschraenkt_auf_ein_projekt(self, stunden, zweites_projekt):
        ergebnis = services.personalkosten_je_projekt(
            nur_laufende=False, projekte=[zweites_projekt.pk])

        je_projekt, ohne, minuten = _alte_regel(
            nur_laufende=False, projekte=[zweites_projekt.pk])
        assert ergebnis.je_projekt == je_projekt
        assert list(ergebnis.je_projekt) == [zweites_projekt.pk]
        assert ergebnis.ohne_satz == ohne
        assert ergebnis.minuten_ohne_satz == minuten


class TestUnvollstaendigeEingangsrechnungen:

    def test_vorsortiert_wie_ist_vollstaendig(self, projekt):
        labor = Kontakt.objects.create(name='Labor', ist_kunde=False,
                                       ist_lieferant=True)
        faelle = {
            'ohne Positionen': ('100.00', []),
            'zu wenig': ('100.00', [('1', '60.00')]),
            'zu viel': ('100.00', [('2', '60.00')]),
            'genau': ('100.00', [('3', '33.33'), ('1', '0.01')]),
            'null ohne Positionen': ('0.00', []),
        }
        for nummer, (betrag, positionen) in faelle.items():
            rechnung = Eingangsrechnung.objects.create(
                lieferant=labor, nummer=nummer, datum=date(2026, 8, 1),
                betrag_netto=Decimal(betrag))
            for menge, preis in positionen:
                Fremdleistung.objects.create(
                    rechnung=rechnung, projekt=projekt, bezeichnung='Analyse',
                    menge=Decimal(menge), einkaufspreis=Decimal(preis))

        offen = services.unvollstaendige_eingangsrechnungen()

        alle = Eingangsrechnung.objects.all()
        referenz = sorted((r for r in alle if not r.ist_vollstaendig),
                          key=lambda r: abs(r.rest), reverse=True)
        assert [r.nummer for r in offen] == [r.nummer for r in referenz]
        assert {r.nummer for r in offen} == {
            'ohne Positionen', 'zu wenig', 'zu viel'}


class TestAbfragenDerErfassungsliste:

    def _abfragen(self, client):
        with CaptureQueriesContext(connection) as abfragen:
            antwort = client.get(reverse(
                'admin:erfassung_erfassungszeile_changelist'))
        assert antwort.status_code == 200
        return len(abfragen.captured_queries)

    def test_doppelt_so_viele_zeilen_gleich_viele_abfragen(
            self, verwaltung, projekt, auftragsposition, mitarbeiter):
        """Die Zahl der Abfragen hängt nicht von der Zahl der Zeilen ab; die
        Spalte "Worauf" lädt den Auftrag mit."""
        def erfassen(tage):
            for tag in tage:
                services.zeile_erfassen(
                    projekt=projekt, benutzer=mitarbeiter,
                    auftragsposition=auftragsposition, beschreibung='Arbeit',
                    datum=date(2026, 9, tag), von=time(8), bis=time(9))

        erfassen(range(1, 4))
        wenige = self._abfragen(verwaltung)
        erfassen(range(4, 10))
        viele = self._abfragen(verwaltung)

        assert viele == wenige


class TestFilterDerErfassungAlsSuchfeld:

    def test_projekt_und_kunde_filtern_wie_vorher(
            self, verwaltung, projekt, kunde, zeitleistung, mitarbeiter):
        anderer = Kontakt.objects.create(nummer='K-2999', name='Andere GmbH')
        fremdes = Projekt.objects.create(nummer='2026-999', bezeichnung='Fremd',
                                         kunde=anderer)
        for ziel in (projekt, fremdes):
            services.zeile_erfassen(
                projekt=ziel, benutzer=mitarbeiter, leistung=zeitleistung,
                beschreibung='Arbeit', datum=date(2026, 9, 1), von=time(8),
                bis=time(9))
        liste = reverse('admin:erfassung_erfassungszeile_changelist')

        for parameter, wert in (('projekt__id__exact', projekt.pk),
                                ('projekt__kunde__id__exact', kunde.pk)):
            antwort = verwaltung.get(liste, {parameter: wert})
            assert {z.projekt_id for z in antwort.context['cl'].result_list} == {
                projekt.pk}, parameter

    def test_das_suchfeld_findet_das_projekt(self, verwaltung, projekt):
        antwort = verwaltung.get(reverse('admin:autocomplete'), {
            'app_label': 'erfassung', 'model_name': 'erfassungszeile',
            'field_name': 'projekt', 'term': 'Halle'})

        assert antwort.status_code == 200
        assert [r['id'] for r in antwort.json()['results']] == [str(projekt.pk)]


class TestSucheDerErfassung:
    """Eigene Suche gegen Djangos Suche über ``search_fields`` als
    Referenz."""

    @pytest.fixture
    def zeilen(self, projekt, zweites_projekt, zeitleistung, mitarbeiter,
               kollege):
        mitarbeiter.first_name, mitarbeiter.last_name = 'Anna', 'Huber'
        mitarbeiter.save()
        texte = ['Anfahrt Baustelle', 'Bohrprofil zeichnen',
                 'Anfahrt und Probenahme', 'Gutachten Halle', 'Abstimmung "Süd"']
        for i, text in enumerate(texte):
            for person in (mitarbeiter, kollege):
                services.zeile_erfassen(
                    projekt=projekt if i % 2 else zweites_projekt,
                    benutzer=person, leistung=zeitleistung, beschreibung=text,
                    datum=date(2026, 9, i + 1), von=time(8), bis=time(9))

    @pytest.mark.parametrize('suche', [
        'Anfahrt', 'anfahrt', 'Halle', 'Süd', '2026-042', 'Huber', 'bernd',
        'Anfahrt Huber', 'Anfahrt Nord', '"Anfahrt und"', 'Gibt es nicht', '',
    ])
    def test_dieselben_treffer_wie_django(self, zeilen, suche, rf):
        modell_admin = admin.site._registry[Erfassungszeile]
        anfrage = rf.get('/')
        alle = Erfassungszeile.objects.all()

        eigene, doppelte = modell_admin.get_search_results(anfrage, alle, suche)
        referenz, _ = admin.ModelAdmin.get_search_results(
            modell_admin, anfrage, alle, suche)

        assert doppelte is False
        assert set(eigene) == set(referenz)

    def test_der_bestand_prueft_wirklich_etwas(self, zeilen):
        """Gegenprobe: Jedes Feld liefert eigene Treffer, keine Suche alle
        Zeilen."""
        modell_admin = admin.site._registry[Erfassungszeile]
        alle = Erfassungszeile.objects.all()

        def zahl(suche):
            return modell_admin.get_search_results(None, alle, suche)[0].count()

        assert alle.count() == 10
        assert zahl('Anfahrt') == 4        # Beschreibung
        assert zahl('Nord') == 4           # Projektbezeichnung
        assert zahl('2026-043') == 6       # Projektnummer
        assert zahl('Huber') == 5          # Nachname
        assert zahl('Anfahrt Huber') == 2  # beide Wörter
        assert zahl('Halle') == 10         # beide Projekte heißen "Halle ..."

    def test_die_liste_sucht_in_der_beschreibung(self, verwaltung, zeilen):
        antwort = verwaltung.get(
            reverse('admin:erfassung_erfassungszeile_changelist'),
            {'q': 'Probenahme'})

        assert antwort.status_code == 200
        assert {z.beschreibung for z in antwort.context['cl'].result_list} == {
            'Anfahrt und Probenahme'}

