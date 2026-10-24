"""Leistungsnachweis: Aufstellung, PDF und Listenaktion.

Der Nachweis schreibt nichts fest: keine Nummer, keine Ablage, kein Verweis
an den Zeilen. Jeder Aufruf zeigt den aktuellen Stand.
"""

import logging
from datetime import time, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from erfassung import nachweis, services
from erfassung.models import Erfassungszeile
from erfassung.sortierung import Sortierung
from faktura.models import Katalogposition, Leistungsart

LISTE = 'admin:erfassung_erfassungszeile_changelist'


@pytest.fixture
def als_mitarbeiter(client, mitarbeiter):
    mitarbeiter.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='erfassung',
        codename__in=['add_erfassungszeile', 'view_erfassungszeile',
                      'change_erfassungszeile'],
    ))
    client.force_login(mitarbeiter)
    return client


@pytest.fixture
def firma(db):
    """Firma für den Briefkopf des Templates."""
    from faktura.models import Firma
    return Firma.objects.create(
        name='Werkstatt Amper GmbH', strasse='Hauptstraße 1',
        plz='85221', ort='Dachau',
    )


@pytest.fixture
def tag(projekt, zeitleistung, mengenleistung, mitarbeiter):
    """Ein Tag mit zwei Zeitblöcken und einer Anfahrt."""
    mitarbeiter.first_name, mitarbeiter.last_name = 'Anna', 'Weber'
    mitarbeiter.save()
    services.zeile_erfassen(
        projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
        von=time(9, 0), bis=time(12, 0), beschreibung='Fundament geschalt')
    services.zeile_erfassen(
        projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
        von=time(13, 0), bis=time(17, 0), beschreibung='Bewehrung')
    services.zeile_erfassen(
        projekt=projekt, leistung=mengenleistung, benutzer=mitarbeiter,
        menge=Decimal('23'), beschreibung='Hin und zurück')
    return Erfassungszeile.objects.all()


# ── Aufstellung ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestDieAufstellungRechnetRichtig:

    def test_die_zeitsumme_zaehlt_nur_die_zeit(self, tag):
        """Die Zeitsumme enthält nur Zeitleistungen."""
        a = services.zeitaufstellung(tag)

        assert a.minuten == 7 * 60
        assert a.zeitsumme == '7:00'

    def test_mengen_stehen_je_einheit_getrennt(self, tag):
        a = services.zeitaufstellung(tag)

        assert [(m.einheit, m.menge) for m in a.mengen] == [('km', Decimal('23'))]

    def test_zwei_einheiten_werden_nicht_verschmolzen(
        self, projekt, mengenleistung, mitarbeiter
    ):
        """Mengen verschiedener Einheiten (23 km, 2 Stk) werden nicht
        addiert."""
        probe = Katalogposition.objects.create(
            bezeichnung='Bodenprobe', einheit='Stk',
            einzelpreis=Decimal('45.00'), kontierbar=True,
            art=Leistungsart.MENGE)
        services.zeile_erfassen(
            projekt=projekt, leistung=mengenleistung, benutzer=mitarbeiter,
            menge=Decimal('23'), beschreibung='Anfahrt')
        services.zeile_erfassen(
            projekt=projekt, leistung=probe, benutzer=mitarbeiter,
            menge=Decimal('2'), beschreibung='Proben')

        a = services.zeitaufstellung(Erfassungszeile.objects.all())

        assert [(m.einheit, m.menge) for m in a.mengen] == [
            ('Stk', Decimal('2')), ('km', Decimal('23'))]

    def test_pauschalen_ohne_mengensumme(
        self, projekt, mengenleistung, pauschalleistung, mitarbeiter
    ):
        """Eine Summe über Pauschalen ("psch 3") sagt nichts aus."""
        services.zeile_erfassen(
            projekt=projekt, leistung=mengenleistung, benutzer=mitarbeiter,
            menge=Decimal('23'), beschreibung='Anfahrt')
        services.zeile_erfassen(
            projekt=projekt, leistung=pauschalleistung, benutzer=mitarbeiter,
            beschreibung='Kleinmaterial')

        a = services.zeitaufstellung(Erfassungszeile.objects.all())

        assert [(m.einheit, m.menge) for m in a.mengen] == [
            ('km', Decimal('23'))]

    def test_pauschale_ohne_art_an_der_einheit(self, projekt, mitarbeiter):
        """Von Hand angelegte Positionen haben keine Art Pauschale, nur die
        Einheit."""
        ingenieur = Katalogposition.objects.create(
            bezeichnung='Ingenieurleistungen', einheit='psch.',
            einzelpreis=Decimal('900.00'), kontierbar=True,
            art=Leistungsart.MENGE)
        services.zeile_erfassen(
            projekt=projekt, leistung=ingenieur, benutzer=mitarbeiter,
            menge=Decimal('1'), beschreibung='Verzeichnis übermittelt')

        a = services.zeitaufstellung(Erfassungszeile.objects.all())

        assert a.mengen == []

    def test_der_zeitraum_kommt_aus_den_zeilen(self, projekt, zeitleistung,
                                               mitarbeiter):
        heute = timezone.localdate()
        for abstand in (0, 5, 2):
            services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
                projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
                datum=heute - timedelta(days=abstand), beschreibung='Arbeit')

        a = services.zeitaufstellung(Erfassungszeile.objects.all())

        assert a.von == heute - timedelta(days=5)
        assert a.bis == heute

    def test_projekt_und_kunde_nur_wenn_eindeutig(self, tag, projekt, kunde):
        a = services.zeitaufstellung(tag)

        assert a.projekt == projekt
        assert a.kunde == kunde

    def test_bei_mehreren_projekten_bleibt_der_kopf_leer(
        self, tag, projekt, kunde, zeitleistung, mitarbeiter
    ):
        """Bei mehreren Projekten bleibt das Projekt im Kopf leer."""
        anderes = projekt.__class__.objects.create(
            nummer='2026-099', bezeichnung='Anderswo', kunde=kunde)
        services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=anderes, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Arbeit')

        a = services.zeitaufstellung(Erfassungszeile.objects.all())

        assert a.projekt is None
        # Der Kunde bleibt eindeutig, beide Projekte gehören ihm.
        assert a.kunde == kunde

    def test_die_reihenfolge_bleibt_wie_geliefert(self, tag):
        """Die Reihenfolge des Aufrufers bleibt erhalten; sie kommt aus der
        Sortierung der Liste."""
        aufsteigend = [z.pk for z in Erfassungszeile.objects.order_by('pk')]

        a = services.zeitaufstellung(Erfassungszeile.objects.order_by('-pk'))

        assert [z.pk for z in a.zeilen] == list(reversed(aufsteigend))

    def test_nicht_abrechenbares_wird_getrennt_ausgewiesen(
        self, projekt, zeitleistung, mitarbeiter
    ):
        """Nicht abrechenbare Zeit wird gesondert ausgewiesen, damit der
        Kunde sie sieht."""
        services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            von=time(8, 0), bis=time(10, 0), beschreibung='Arbeit')
        services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            von=time(10, 0), bis=time(11, 0), beschreibung='Gewährleistung',
            abrechenbar=False)

        a = services.zeitaufstellung(Erfassungszeile.objects.all())

        assert a.minuten == 180
        assert a.minuten_ohne_berechnung == 60
        assert a.hat_unberechnetes


# ── PDF ──────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestDasBlatt:

    def test_der_personenname_steht_da_nicht_der_anmeldename(self, firma, tag):
        html = nachweis.nachweis_als_html(services.zeitaufstellung(tag))

        assert 'Anna Weber' in html
        assert '>anna<' not in html

    def test_uhrzeiten_und_dauer_stehen_da(self, firma, tag):
        html = nachweis.nachweis_als_html(services.zeitaufstellung(tag))

        assert '09:00' in html and '12:00' in html
        assert '7:00' in html

    def test_kompakt_ohne_uhrzeiten_aber_mit_dauer(self, firma, tag):
        """Die kompakte Fassung ohne Von und Bis, mit Dauer."""
        html = nachweis.nachweis_als_html(services.zeitaufstellung(tag),
                                          mit_uhrzeit=False)

        assert '09:00' not in html and '12:00' not in html
        assert '>Von<' not in html and '>Bis<' not in html
        assert '7:00' in html

    def test_die_anfahrt_steht_mit_kilometern(self, firma, tag):
        html = nachweis.nachweis_als_html(services.zeitaufstellung(tag))

        assert '23 km' in html

    def test_keine_preise(self, firma, tag):
        """Der Nachweis enthält keine Preise; die Bewertung steht auf der
        Rechnung."""
        html = nachweis.nachweis_als_html(services.zeitaufstellung(tag))

        assert '68,00' not in html
        assert '68.00' not in html

    def test_nicht_abrechenbares_wird_vermerkt(self, firma, projekt,
                                               zeitleistung, mitarbeiter):
        """Nicht abrechenbare Stunden erscheinen mit Vermerk."""
        services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            von=time(8, 0), bis=time(10, 0), beschreibung='Nachbesserung',
            abrechenbar=False)

        html = nachweis.nachweis_als_html(
            services.zeitaufstellung(Erfassungszeile.objects.all()))

        assert 'ohne Berechnung' in html

    def test_die_unterschriftszeile_fehlt_nicht(self, firma, tag):
        """Das PDF enthält eine Unterschriftszeile."""
        html = nachweis.nachweis_als_html(services.zeitaufstellung(tag))

        assert 'Unterschrift Auftraggeber' in html

    def test_ohne_zeilen_steht_ein_satz_da_und_kein_leeres_blatt(self, firma):
        html = nachweis.nachweis_als_html(services.zeitaufstellung(
            Erfassungszeile.objects.none()))

        assert 'keine Erfassungen' in html


@pytest.mark.django_db
class TestDasPdf:

    def test_es_entsteht_ein_pdf(self, firma, tag):
        daten = nachweis.nachweis_als_pdf(services.zeitaufstellung(tag))

        assert daten.startswith(b'%PDF-')

    def test_die_stildateien_werden_wirklich_geladen(self, firma, tag, caplog):
        """Die Stylesheets werden geladen; der Test fängt Warnungen von
        WeasyPrint ab.

        Ohne Stylesheet entsteht ein unformatiertes PDF, das WeasyPrint nur
        als Warnung meldet. Ausgenommen ist der Hinweis zu HarfBuzz-Subset
        (seit WeasyPrint 70), der die Umgebung betrifft: Die ältere
        GTK3-Runtime unter Windows hat die Bibliothek nicht, Image und CI
        haben sie (Dockerfile, pruefen.yml).
        """
        with caplog.at_level(logging.WARNING, logger='weasyprint'):
            nachweis.nachweis_als_pdf(services.zeitaufstellung(tag))

        assert not [s for s in caplog.records if s.name.startswith('weasyprint')
                    and 'HarfBuzz-Subset' not in s.getMessage()]

    def test_der_dateiname_nennt_projekt_und_zeitraum(self, tag):
        name = nachweis.dateiname(services.zeitaufstellung(tag))

        assert name.startswith('Leistungsnachweis_2026-042_')
        assert name.endswith('.pdf')

    def test_ohne_eindeutiges_projekt_bleibt_er_karg(self, projekt, kunde,
                                                     zeitleistung, mitarbeiter):
        anderes = projekt.__class__.objects.create(
            nummer='2026-099', bezeichnung='Anderswo', kunde=kunde)
        for vorhaben in (projekt, anderes):
            services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
                projekt=vorhaben, leistung=zeitleistung, benutzer=mitarbeiter,
                beschreibung='Arbeit')

        name = nachweis.dateiname(
            services.zeitaufstellung(Erfassungszeile.objects.all()))

        assert '2026-042' not in name
        assert name.startswith('Leistungsnachweis_')


# ── Listenaktion ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestDieAktionInDerListe:
    """Der Nachweis als Listenaktion über die gefilterte und ausgewählte
    Liste."""

    def _ausloesen(self, client, zeilen, adresse=None,
                   aktion='leistungsnachweis'):
        return client.post(adresse or reverse(LISTE), {
            'action': aktion,
            '_selected_action': [str(z.pk) for z in zeilen],
            'index': '0',
        })

    def test_die_aktion_liefert_ein_pdf(self, als_mitarbeiter, firma, tag):
        antwort = self._ausloesen(als_mitarbeiter, tag)

        assert antwort.status_code == 200
        assert antwort['Content-Type'] == 'application/pdf'
        assert antwort.content.startswith(b'%PDF-')
        assert 'Leistungsnachweis' in antwort['Content-Disposition']

    @pytest.mark.parametrize('aktion, mit_uhrzeit', [
        ('leistungsnachweis', True),
        ('leistungsnachweis_kompakt', False),
    ])
    def test_jede_aktion_zieht_ihre_fassung(
        self, als_mitarbeiter, firma, tag, monkeypatch, aktion, mit_uhrzeit
    ):
        """Jede der beiden Aktionen erzeugt ihre Fassung; geprüft wird der
        Aufruf, nicht der Text im PDF."""
        gesehen = {}
        echt = nachweis.nachweis_als_pdf

        def horcher(aufstellung, **rest):
            gesehen['mit_uhrzeit'] = rest['mit_uhrzeit']
            return echt(aufstellung, **rest)

        monkeypatch.setattr(nachweis, 'nachweis_als_pdf', horcher)

        antwort = self._ausloesen(als_mitarbeiter, tag, aktion=aktion)

        assert antwort['Content-Type'] == 'application/pdf'
        assert gesehen['mit_uhrzeit'] is mit_uhrzeit

    def test_ohne_auswahl_gibt_es_kein_pdf(self, als_mitarbeiter, firma):
        antwort = self._ausloesen(als_mitarbeiter, [])

        assert antwort.status_code == 302

    def test_fremde_zeilen_kommen_nicht_ins_pdf(
        self, als_mitarbeiter, firma, tag, projekt, zeitleistung, kollege,
        monkeypatch
    ):
        """Fremde Zeilen gelangen nicht ins PDF.

        Die IDs kommen aus dem Request; Django schneidet sie mit dem Queryset
        der Liste, das auf eigene Zeilen gefiltert ist. Geprüft wird die
        Aufstellung, die das PDF erhält, weil der Text in den PDF-Bytes nicht
        durchsuchbar ist.
        """
        eigene = list(tag)
        fremd = services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=kollege,
            beschreibung='Was der Kollege gemacht hat')

        gesehen = {}
        echt = nachweis.nachweis_als_pdf

        def horcher(aufstellung, **rest):
            gesehen['zeilen'] = {z.pk for z in aufstellung.zeilen}
            return echt(aufstellung, **rest)

        monkeypatch.setattr(nachweis, 'nachweis_als_pdf', horcher)

        antwort = self._ausloesen(als_mitarbeiter, [*eigene, fremd])

        assert antwort.status_code == 200
        assert gesehen['zeilen'] == {z.pk for z in eigene}
        assert fremd.pk not in gesehen['zeilen']

    @pytest.mark.parametrize('sortierung, erwartet', [
        # Pauschale vor Zeit, wie für Kundenberichte festgelegt.
        (Sortierung.NACHWEIS, ['Pauschalzeile', 'Stundenzeile']),
        # Absteigend nach Uhrzeit, Zeilen ohne Uhrzeit zuletzt: kehrt die
        # Reihenfolge um und zeigt, dass die Sortierung ankommt.
        (Sortierung.NEUESTE, ['Stundenzeile', 'Pauschalzeile']),
        # Alphabetisch: "Kleinmaterial" vor "Montage".
        (Sortierung.LEISTUNG, ['Pauschalzeile', 'Stundenzeile']),
    ])
    def test_die_sortierung_der_liste_erreicht_die_aktion(
        self, als_mitarbeiter, firma, projekt, zeitleistung, pauschalleistung,
        mitarbeiter, monkeypatch, sortierung, erwartet
    ):
        """Die Aktion erhält das Queryset der Liste mit dessen Sortierung.

        Drei Sortierungen, von denen eine die Reihenfolge umkehrt, damit der
        Test nicht besteht, wenn alle gleich sortieren.
        """
        services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            von=time(9, 0), bis=time(12, 0), beschreibung='Stundenzeile')
        services.zeile_erfassen(
            projekt=projekt, leistung=pauschalleistung, benutzer=mitarbeiter,
            beschreibung='Pauschalzeile')

        gesehen = {}
        echt = nachweis.nachweis_als_pdf

        def horcher(aufstellung, **rest):
            gesehen['reihenfolge'] = [z.beschreibung for z in aufstellung.zeilen]
            return echt(aufstellung, **rest)

        monkeypatch.setattr(nachweis, 'nachweis_als_pdf', horcher)

        antwort = self._ausloesen(
            als_mitarbeiter, Erfassungszeile.objects.all(),
            f'{reverse(LISTE)}?sortierung={sortierung.value}')

        assert antwort.status_code == 200
        assert gesehen['reihenfolge'] == erwartet
