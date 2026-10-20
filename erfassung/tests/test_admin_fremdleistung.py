"""Admin von Eingangsrechnung und Fremdleistung, geprüft am gerenderten HTML.

Jeder Test rendert eine Liste mit Inhalt. ``format_html()`` ohne
Platzhalter wirft seit Django 5 einen TypeError, aber erst beim Rendern
einer Zeile; weder der Start noch ``manage.py check`` noch eine leere Liste
zeigen ihn.

Kein Test läuft als Superuser, weil die Fremdleistung der Leitung
vorbehalten ist.
"""

import re
from datetime import date
from decimal import Decimal

import pytest
from django.apps import apps
from django.contrib.auth.models import Permission
from django.urls import reverse

from erfassung.models import (
    Eingangsrechnung,
    Erfassungszeile,
    Fremdleistung,
    Kostensatz,
)
from faktura.models import Kontakt


@pytest.fixture
def als_leitung(client, kollege):
    """Konto der Leitung mit Einkaufspreisen und Kostensätzen.

    Zusätzlich ``view_projekt``, weil die Maske Projekte anzeigt.
    """
    kollege.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='erfassung'))
    kollege.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='faktura',
        codename__in=['view_projekt', 'change_projekt']))
    client.force_login(kollege)
    return client


@pytest.fixture
def als_monteur(client, mitarbeiter):
    """Konto, das eigene Stunden erfasst, ohne Einkaufspreise."""
    mitarbeiter.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='erfassung',
        codename__in=['add_erfassungszeile', 'view_erfassungszeile',
                      'change_erfassungszeile'],
    ))
    client.force_login(mitarbeiter)
    return client


@pytest.fixture
def bestand(db, projekt):
    """Zwei Eingangsrechnungen, eine vollständig verteilt, eine nicht, weil
    die Restspalte für beide Fälle verschiedene Zweige durchläuft."""
    labor = Kontakt.objects.create(ist_kunde=False, ist_lieferant=True, name='ISARTAL')
    fertig = Eingangsrechnung.objects.create(
        lieferant=labor, nummer='AL-1', datum=date(2026, 8, 1),
        betrag_netto=Decimal('192.00'))
    Fremdleistung.objects.create(
        rechnung=fertig, projekt=projekt, bezeichnung='Paket 4711',
        menge=Decimal('2'), einkaufspreis=Decimal('96.00'))
    offen = Eingangsrechnung.objects.create(
        lieferant=labor, nummer='AL-2', datum=date(2026, 8, 2),
        betrag_netto=Decimal('500.00'))
    Fremdleistung.objects.create(
        rechnung=offen, projekt=projekt, bezeichnung='Paket 8802',
        menge=Decimal('1'), einkaufspreis=Decimal('168.00'),
        weiterberechenbar=False)
    return fertig, offen


class TestDieListenLaufen:
    """Jede Maske lädt mit Inhalt."""

    @pytest.mark.parametrize('maske', [
        'erfassung_eingangsrechnung',
        'erfassung_fremdleistung',
    ])
    def test_die_liste_rendert(self, als_leitung, bestand, maske):
        antwort = als_leitung.get(reverse(f'admin:{maske}_changelist'))

        assert antwort.status_code == 200

    def test_die_kostensatzliste_rendert(self, als_leitung, kollege):
        Kostensatz.objects.create(
            benutzer=kollege, gueltig_ab=date(2026, 1, 1),
            satz=Decimal('55.00'))

        antwort = als_leitung.get(
            reverse('admin:erfassung_kostensatz_changelist'))

        assert antwort.status_code == 200

    def test_das_formular_mit_positionen_rendert(self, als_leitung, bestand):
        """Die Eingangsrechnung mit Inline der Positionen lädt."""
        fertig, _ = bestand

        antwort = als_leitung.get(reverse(
            'admin:erfassung_eingangsrechnung_change', args=[fertig.pk]))

        assert antwort.status_code == 200

    def test_das_leere_formular_rendert(self, als_leitung):
        """Das leere Formular lädt; die Summenzelle einer ungespeicherten
        Zeile ist leer."""
        antwort = als_leitung.get(
            reverse('admin:erfassung_eingangsrechnung_add'))

        assert antwort.status_code == 200


class TestWasInDerListeSteht:

    def test_die_vollstaendige_rechnung_wird_als_solche_ausgewiesen(
            self, als_leitung, bestand):
        antwort = als_leitung.get(
            reverse('admin:erfassung_eingangsrechnung_changelist'))
        inhalt = antwort.content.decode()

        assert 'vollständig' in inhalt

    def test_der_offene_rest_steht_mit_seinem_betrag_da(
            self, als_leitung, bestand):
        """Der offene Rest erscheint mit Betrag: 332,00 von 500,00."""
        antwort = als_leitung.get(
            reverse('admin:erfassung_eingangsrechnung_changelist'))

        assert '332,00' in antwort.content.decode()

    def test_ein_offener_rest_steht_gruen(self, als_leitung, bestand):
        """Ein positiver Rest ist nicht rot, weil die Rechnung noch verteilt
        wird."""
        inhalt = als_leitung.get(
            reverse('admin:erfassung_eingangsrechnung_changelist')
        ).content.decode()

        assert re.search(r'class="text-green-600[^"]*">332,00 €<', inhalt)

    def test_nur_der_negative_rest_steht_rot(self, als_leitung, bestand):
        """Ein negativer Rest ist rot."""
        _, offen = bestand
        Eingangsrechnung.objects.filter(pk=offen.pk).update(
            betrag_netto=Decimal('100.00'))

        inhalt = als_leitung.get(
            reverse('admin:erfassung_eingangsrechnung_changelist')
        ).content.decode()

        assert re.search(r'text-red-600[^"]*">-68,00 €<', inhalt)


class TestDieRechnungsspalte:
    """Ausgangsrechnung in eigener Spalte mit Link auf ihre Akte."""

    @pytest.mark.skipif(
        not apps.is_installed('auswertung'),
        reason='Die Rechnungsakte lebt in auswertung; siehe "nur Kern" '
               '(paperwerk/settings/kern.py).')
    def test_abgerechnet_mit_nummer_und_verweis(self, als_leitung, bestand,
                                                projekt):
        from faktura.models import Beleg, Belegposition, BelegStatus, BelegTyp
        rechnung = Beleg.objects.create(
            typ=BelegTyp.RECHNUNG, projekt=projekt,
            status=BelegStatus.FESTGESCHRIEBEN, nummer='RE-2026-0200')
        position = Belegposition.objects.bulk_create([Belegposition(
            beleg=rechnung, position=10, bezeichnung='Analysen',
            menge=Decimal('2'), einzelpreis=Decimal('120.00'))])[0]
        Fremdleistung.objects.filter(bezeichnung='Paket 4711').update(
            abgerechnet_in=position)

        inhalt = als_leitung.get(
            reverse('admin:erfassung_fremdleistung_changelist')
        ).content.decode()

        assert 'Rechnungsnummer' in inhalt
        assert (f'href="{reverse("rechnungsakte", args=[rechnung.pk])}"'
                in inhalt)
        assert 'RE-2026-0200' in inhalt


class TestWerDasSehenDarf:
    """Einkaufspreise und Kostensätze sieht nur die Leitung."""

    @pytest.mark.parametrize('maske', [
        'erfassung_eingangsrechnung',
        'erfassung_fremdleistung',
        'erfassung_kostensatz',
    ])
    def test_der_monteur_kommt_nicht_hinein(self, als_monteur, bestand, maske):
        antwort = als_monteur.get(reverse(f'admin:{maske}_changelist'))

        assert antwort.status_code == 403


class TestDerEinstiegInDieZeile:
    """Die erste Spalte der Fremdleistungsliste verlinkt auf den Datensatz,
    wie im Admin üblich."""

    def test_die_erste_spalte_fuehrt_in_den_datensatz(
            self, als_leitung, bestand):
        position = Fremdleistung.objects.first()

        antwort = als_leitung.get(
            reverse('admin:erfassung_fremdleistung_changelist'))
        inhalt = antwort.content.decode()

        ziel = reverse('admin:erfassung_fremdleistung_change',
                       args=[position.pk])
        assert 'field-datum_anzeige' in inhalt
        # Der Link liegt in der Datumszelle.
        datumszellen = re.findall(
            r'<t[dh] class="field-datum_anzeige[^>]*>(.*?)</t[dh]>',
            inhalt, re.S)
        assert any(ziel in z for z in datumszellen)

    def test_die_aenderungsseite_laesst_sich_oeffnen(
            self, als_leitung, bestand):
        position = Fremdleistung.objects.first()

        antwort = als_leitung.get(reverse(
            'admin:erfassung_fremdleistung_change', args=[position.pk]))

        assert antwort.status_code == 200


class TestZugeordnetWirdInDerRechnung:
    """Fremdleistungen werden in der Eingangsrechnung einem Vorhaben
    zugeordnet.

    Verworfen: ein Inline "Fremdleistungen" in der Projektmaske. In der
    Praxis wird von der Eingangsrechnung aus zugeordnet, deren Positionen
    ihr Projekt tragen.
    """

    def test_die_position_traegt_ihr_projekt_in_der_rechnung(
            self, als_leitung, bestand):
        fertig, _ = bestand

        inhalt = als_leitung.get(reverse(
            'admin:erfassung_eingangsrechnung_change',
            args=[fertig.pk])).content.decode()

        assert re.search(r'name="positionen-\d+-projekt"', inhalt)

    def test_das_projektformular_fuehrt_keine_fremdleistungen_mehr(
            self, als_leitung, projekt, bestand):
        """Die Projektmaske hat kein Inline "Fremdleistungen"."""
        inhalt = als_leitung.get(reverse(
            'admin:faktura_projekt_change', args=[projekt.pk])).content.decode()

        assert not re.findall(r'name="fremdleistungen-\d+-bezeichnung"',
                              inhalt)

    def test_die_projektmaske_kommt_aus_faktura(self):
        """Der ProjektAdmin stammt aus ``faktura`` und wird nicht ersetzt,
        damit keine Abhängigkeit von der Reihenfolge in INSTALLED_APPS
        entsteht (``admin.site.unregister``)."""
        from django.contrib.admin.sites import site

        from faktura.models import Projekt

        verwaltung = site.get_model_admin(Projekt)

        assert type(verwaltung).__module__.startswith('faktura.')
        assert not verwaltung.inlines


class TestFremdleistungVonDerRechnungAus:
    """Fremdleistungen lassen sich von der Rechnung aus hinzufügen.

    "Erbrachte Leistungen hinzufügen" zeigt neben eigenen Stunden auch die
    offenen Fremdleistungen des Vorhabens.
    """


    @pytest.fixture
    def abrechnerin(self, client, kollege):
        """Konto mit Recht auf Fremdleistungen und auf das Ändern von Belegen,
        weil die Maske am Beleg hängt."""
        kollege.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='erfassung'))
        kollege.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='faktura',
            codename__in=['view_projekt', 'change_projekt', 'view_beleg',
                          'add_beleg', 'change_beleg', 'view_rechnung',
                          'add_rechnung', 'change_rechnung']))
        client.force_login(kollege)
        return client

    @pytest.fixture
    def entwurf(self, projekt):
        """Rechnungsentwurf zum Vorhaben als Ziel."""
        from faktura import services as faktura_services
        from faktura.models import BelegTyp

        return faktura_services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG, betreff='Sammelrechnung')

    def _maske(self, client, beleg):
        return client.get(reverse('admin:faktura_rechnung_detail_leistungen',
                                  args=[beleg.pk]))

    def test_die_maske_zeigt_das_zugekaufte(self, abrechnerin, projekt,
                                            bestand, entwurf):
        antwort = self._maske(abrechnerin, entwurf)
        inhalt = antwort.content.decode()

        assert antwort.status_code == 200
        assert 'Fremdleistung:' in inhalt
        assert 'name="fremdleistung"' in inhalt

    def test_nicht_weiterberechenbares_bleibt_draussen(
            self, abrechnerin, projekt, bestand, entwurf):
        """Nicht abrechenbare Fremdleistung erscheint nicht in der Auswahl."""
        Fremdleistung.objects.update(weiterberechenbar=False)

        inhalt = self._maske(abrechnerin, entwurf).content.decode()

        assert 'name="fremdleistung"' not in inhalt

    def test_das_haengt_sie_an_die_rechnung(self, abrechnerin, projekt,
                                            bestand, entwurf):
        """Die Auswahl wird übernommen; die Zeile verweist danach auf die
        Rechnungsposition."""
        position = Fremdleistung.objects.filter(
            projekt=projekt, weiterberechenbar=True,
            abgerechnet_in__isnull=True).first()
        vorher = entwurf.positionen.count()

        abrechnerin.post(
            reverse('admin:faktura_rechnung_detail_leistungen',
                    args=[entwurf.pk]),
            {'fremdleistung': [str(position.pk)]})

        position.refresh_from_db()
        assert entwurf.positionen.count() == vorher + 1
        assert position.abgerechnet_in is not None
        assert position.abgerechnet_in.beleg_id == entwurf.pk

    def test_eine_fremde_position_wird_nicht_untergeschoben(
            self, abrechnerin, kunde, projekt, bestand, entwurf):
        """Eine Fremdleistung eines anderen Vorhabens wird abgelehnt; die IDs
        kommen aus dem Request (wie bei den Stunden)."""
        from faktura.models import Projekt

        anderes = Projekt.objects.create(
            nummer='2026-998', bezeichnung='Woanders', kunde=kunde)
        fremd = Fremdleistung.objects.filter(weiterberechenbar=True).first()
        Fremdleistung.objects.filter(pk=fremd.pk).update(projekt=anderes)

        abrechnerin.post(
            reverse('admin:faktura_rechnung_detail_leistungen',
                    args=[entwurf.pk]),
            {'fremdleistung': [str(fremd.pk)]})

        fremd.refresh_from_db()
        assert fremd.abgerechnet_in is None


class TestEineAbgerechnetePositionBlockiertDieRechnungNicht:
    """Eine abgerechnete Position verhindert nicht das Speichern der
    Eingangsrechnung.

    Regression: Beim Hinzufügen einer Position meldete das Formular für eine
    unveränderte, abgerechnete Position "Diese Position steht auf Rechnung
    ... und kann nicht geändert werden". Django validiert im Formset jede
    vorhandene Zeile, auch unveränderte.
    """

    @pytest.fixture
    def mit_gesperrter_position(self, db, projekt):
        """Rechnung mit zwei Positionen, eine davon auf einem Entwurf."""
        from erfassung.services import in_rechnung_uebernehmen
        from faktura.models import BelegTyp
        from faktura.services import beleg_anlegen

        rechnung = Eingangsrechnung.objects.create(
            lieferant=Kontakt.objects.create(ist_kunde=False, ist_lieferant=True, name='ISARTAL'),
            nummer='AL-9', datum=date(2026, 9, 1),
            betrag_netto=Decimal('500.00'))
        abgerechnet = Fremdleistung.objects.create(
            rechnung=rechnung, projekt=projekt, bezeichnung='Paket 4711',
            menge=Decimal('2'), einkaufspreis=Decimal('96.00'))

        entwurf = beleg_anlegen(projekt=projekt, typ=BelegTyp.RECHNUNG,
                                betreff='Sammelrechnung')
        in_rechnung_uebernehmen(zeilen=Erfassungszeile.objects.none(),
                                fremdleistungen=[abgerechnet], beleg=entwurf)
        abgerechnet.refresh_from_db()
        assert abgerechnet.abgerechnet_in_id is not None
        return rechnung, abgerechnet

    def _daten(self, rechnung, position, **abweichend):
        """POST-Daten wie vom Browser: die vorhandene Zeile unverändert, dazu
        eine neue."""
        daten = {
            'lieferant': str(rechnung.lieferant_id),
            'nummer': rechnung.nummer,
            'datum': '2026-09-01',
            'betrag_netto': '500.00',
            'notiz': '',
            'positionen-TOTAL_FORMS': '2',
            'positionen-INITIAL_FORMS': '1',
            'positionen-MIN_NUM_FORMS': '0',
            'positionen-MAX_NUM_FORMS': '1000',
            'positionen-0-id': str(position.pk),
            'positionen-0-rechnung': str(rechnung.pk),
            'positionen-0-projekt': str(position.projekt_id),
            'positionen-0-auftragsposition': '',
            'positionen-0-bezeichnung': position.bezeichnung,
            'positionen-0-einheit': position.einheit,
            'positionen-0-menge': '2',
            'positionen-0-einkaufspreis': '96.00',
            # Der Browser sendet den gespeicherten Betrag.
            'positionen-0-einkauf_netto': '192.00',
            'positionen-0-weiterberechenbar': 'on',
            'positionen-1-id': '',
            'positionen-1-rechnung': str(rechnung.pk),
            'positionen-1-projekt': str(position.projekt_id),
            'positionen-1-auftragsposition': '',
            'positionen-1-bezeichnung': 'Paket 8802',
            'positionen-1-einheit': 'Stk',
            'positionen-1-menge': '1',
            'positionen-1-einkaufspreis': '168.00',
            'positionen-1-einkauf_netto': '',
            'positionen-1-weiterberechenbar': 'on',
            '_save': 'Sichern',
        }
        daten.update(abweichend)
        return daten

    def _senden(self, client, rechnung, daten):
        return client.post(
            reverse('admin:erfassung_eingangsrechnung_change',
                    args=[rechnung.pk]), daten)

    def test_die_weitere_position_laesst_sich_erfassen(
            self, als_leitung, mit_gesperrter_position):
        rechnung, position = mit_gesperrter_position

        antwort = self._senden(als_leitung, rechnung,
                               self._daten(rechnung, position))

        assert antwort.status_code == 302, 'Das Formular kam mit Fehlern zurück'
        assert rechnung.positionen.count() == 2

    def test_wer_sie_wirklich_anfasst_wird_weiter_gestoppt(
            self, als_leitung, mit_gesperrter_position):
        """Eine tatsächliche Änderung der gesperrten Position wird weiterhin
        abgelehnt."""
        rechnung, position = mit_gesperrter_position

        antwort = self._senden(
            als_leitung, rechnung,
            self._daten(rechnung, position, **{'positionen-0-menge': '3'}))

        position.refresh_from_db()
        assert antwort.status_code == 200
        assert 'kann nicht geändert werden' in antwort.content.decode()
        assert position.menge == Decimal('2')


class TestNurDerEinkauf:
    """Die Maske der Fremdleistung enthält nur den Einkauf: ohne
    Verkaufspreis und Katalogleistung, mit optionaler Auftragsposition."""

    @pytest.fixture
    def auftragszeile(self, projekt):
        from faktura.models import Beleg, Belegposition, BelegStatus, BelegTyp

        auftrag = Beleg.objects.create(
            typ=BelegTyp.AUFTRAG, status=BelegStatus.FESTGESCHRIEBEN,
            nummer='AU-2026-0031', projekt=projekt)
        return Belegposition.objects.bulk_create([Belegposition(
            beleg=auftrag, position=10, bezeichnung='Bodenprobe LAGA-Paket',
            menge=Decimal('40'), einheit='Stk',
            einzelpreis=Decimal('145.00'))])[0]

    def test_die_maske_fragt_nur_den_einkauf(self, als_leitung, bestand,
                                             auftragszeile):
        fertig, _ = bestand

        inhalt = als_leitung.get(reverse(
            'admin:erfassung_eingangsrechnung_change', args=[fertig.pk])
        ).content.decode()

        assert 'positionen-0-einkauf_netto' in inhalt
        assert 'positionen-0-auftragsposition' in inhalt
        assert 'verkaufspreis' not in inhalt
        # Kein Feld "leistung"; "leistungsdatum" gehört zum Einkauf.
        assert 'positionen-0-leistung"' not in inhalt
        assert 'positionen-0-leistungsdatum"' in inhalt
        # Projekt an jeder Auftragsposition, danach filtert das Skript.
        assert f'data-projekt="{auftragszeile.beleg.projekt_id}"' in inhalt
        assert 'fremdleistungsauswahl.js' in inhalt

    def test_die_auftragsposition_wird_gespeichert(
            self, als_leitung, projekt, auftragszeile):
        rechnung = Eingangsrechnung.objects.create(
            lieferant=Kontakt.objects.create(
                ist_kunde=False, ist_lieferant=True, name='ISARTAL'),
            nummer='AL-77', datum=date(2026, 9, 1),
            betrag_netto=Decimal('450.00'))

        antwort = als_leitung.post(
            reverse('admin:erfassung_eingangsrechnung_change',
                    args=[rechnung.pk]),
            {
                'lieferant': str(rechnung.lieferant_id),
                'nummer': rechnung.nummer, 'datum': '2026-09-01',
                'betrag_netto': '450.00', 'notiz': '',
                'positionen-TOTAL_FORMS': '1',
                'positionen-INITIAL_FORMS': '0',
                'positionen-MIN_NUM_FORMS': '0',
                'positionen-MAX_NUM_FORMS': '1000',
                'positionen-0-id': '',
                'positionen-0-rechnung': str(rechnung.pk),
                'positionen-0-projekt': str(projekt.pk),
                'positionen-0-auftragsposition': str(auftragszeile.pk),
                'positionen-0-bezeichnung': 'Paket 4711',
                'positionen-0-einheit': 'Stk',
                'positionen-0-menge': '5',
                'positionen-0-einkaufspreis': '100.00',
                # Rabatt auf der Zeile: 500 laut Preis, 450 berechnet.
                'positionen-0-einkauf_netto': '450.00',
                'positionen-0-weiterberechenbar': 'on',
                '_save': 'Sichern',
            })

        assert antwort.status_code == 302, 'Das Formular kam mit Fehlern zurück'
        position = rechnung.positionen.get()
        assert position.auftragsposition == auftragszeile
        assert position.einkauf_netto == Decimal('450.00')
        rechnung.refresh_from_db()
        assert rechnung.ist_vollstaendig

    def test_die_liste_zeigt_keinen_verkauf_mehr(self, als_leitung, bestand):
        inhalt = als_leitung.get(
            reverse('admin:erfassung_fremdleistung_changelist')
        ).content.decode()

        assert 'field-einkauf_anzeige' in inhalt
        assert 'field-verkauf_anzeige' not in inhalt
        assert 'field-spanne_anzeige' not in inhalt

    def test_im_menue_steht_sie_nicht_mehr(self):
        """Kein Menüeintrag; die Liste bleibt registriert, weil die
        Projektakte auf sie verlinkt."""
        from core import erweiterungen

        ziel = reverse('admin:erfassung_fremdleistung_changelist')
        links = [
            str(eintrag.get('link', ''))
            for gruppe in erweiterungen.menue_abschnitte()
            for eintrag in gruppe.get('items', [])
        ]

        assert ziel not in links
        assert reverse('admin:erfassung_eingangsrechnung_changelist') in links
