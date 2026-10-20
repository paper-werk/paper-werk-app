"""Import und Export der Erfassung (``erfassung/ressourcen.py``).

Geprüft werden Dateien aus deutscher Tabellenkalkulation, Zeilen für andere
Personen ohne Recht dazu, abgeschlossene Projekte und ein zweiter Lauf
derselben Datei ohne Duplikate.
"""

import io
from datetime import time, timedelta
from decimal import Decimal

import pytest
import tablib
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from .. import services
from ..models import Erfassungszeile
from ..ressourcen import ErfassungszeileResource

pytestmark = pytest.mark.django_db

SPALTEN = ['datum', 'person', 'projekt', 'auftrag', 'position', 'leistung',
           'von', 'bis', 'menge', 'beschreibung', 'abrechenbar']

GESTERN = timezone.localdate() - timedelta(days=1)


def _tabelle(*zeilen) -> tablib.Dataset:
    daten = tablib.Dataset(headers=SPALTEN)
    for zeile in zeilen:
        daten.append(zeile)
    return daten


def _zeile(**werte) -> list:
    vorgabe = {'datum': f'{GESTERN:%d.%m.%Y}', 'person': '',
               'projekt': '2026-042', 'auftrag': '', 'position': '',
               'leistung': '', 'von': '', 'bis': '', 'menge': '',
               'beschreibung': '', 'abrechenbar': ''}
    vorgabe.update(werte)
    return [vorgabe[s] for s in SPALTEN]


def _einlesen(daten, nutzer):
    return ErfassungszeileResource().import_data(
        daten, dry_run=False, user=nutzer)


def _fehler(ergebnis) -> str:
    """Alle Meldungen eines Laufs als ein Text."""
    return ' '.join(
        ' '.join(str(m) for m in zeile.error.messages)
        for zeile in ergebnis.invalid_rows)


def _darf_fremde(person):
    person.user_permissions.add(Permission.objects.get(
        codename='fuer_andere_erfassen'))
    # Django cacht die Rechte am User-Objekt.
    return type(person).objects.get(pk=person.pk)


class TestWasAusEinerDateiHereinkommt:

    def test_eine_zeitzeile_auf_eine_katalogleistung(
            self, projekt, zeitleistung, mitarbeiter):
        daten = _tabelle(_zeile(leistung='Montage', von='8:00', bis='12:30',
                                beschreibung='Kabeltrasse'))

        ergebnis = _einlesen(daten, mitarbeiter)

        assert not ergebnis.has_errors() and not ergebnis.has_validation_errors()
        zeile = Erfassungszeile.objects.get()
        assert zeile.datum == GESTERN
        assert zeile.benutzer == mitarbeiter
        assert zeile.projekt == projekt
        assert zeile.leistung == zeitleistung
        assert (zeile.von, zeile.bis) == (time(8, 0), time(12, 30))
        assert zeile.dauer_minuten == 270
        assert zeile.abrechenbar is True

    def test_auf_eine_auftragsposition_ueber_auftrag_und_pos(
            self, projekt, auftragsposition, mitarbeiter):
        """Kontierung auf eine Auftragsposition über Auftrag und Pos."""
        daten = _tabelle(_zeile(auftrag='AU-2026-0005', position='10',
                                von='09:00', bis='11:00'))

        _einlesen(daten, mitarbeiter)

        assert Erfassungszeile.objects.get().auftragsposition == auftragsposition

    def test_eine_menge_mit_dezimalkomma(self, projekt, mengenleistung,
                                         mitarbeiter):
        daten = _tabelle(_zeile(leistung='Anfahrt', menge='23,5'))

        _einlesen(daten, mitarbeiter)

        assert Erfassungszeile.objects.get().menge == Decimal('23.5')

    def test_eine_pauschale_hat_immer_menge_eins(
            self, projekt, pauschalleistung, mitarbeiter):
        """Eine Pauschale hat Menge eins, unabhängig von der Spalte, wie in der
    Maske."""
        daten = _tabelle(_zeile(leistung='Kleinmaterial', menge='5'))

        _einlesen(daten, mitarbeiter)

        assert Erfassungszeile.objects.get().menge == Decimal('1')

    def test_ohne_person_gilt_wer_einliest(self, projekt, zeitleistung,
                                           mitarbeiter):
        _einlesen(_tabelle(_zeile(leistung='Montage', von='8:00',
                                  bis='9:00')), mitarbeiter)

        assert Erfassungszeile.objects.get().benutzer == mitarbeiter

    def test_die_person_auch_mit_vor_und_nachnamen(
            self, projekt, zeitleistung, mitarbeiter, kollege):
        kollege.first_name, kollege.last_name = 'Bernd', 'Huber'
        kollege.save()
        chef = _darf_fremde(mitarbeiter)

        _einlesen(_tabelle(_zeile(person='Bernd Huber', leistung='Montage',
                                  von='8:00', bis='9:00')), chef)

        assert Erfassungszeile.objects.get().benutzer == kollege


class TestWasAbgewiesenWird:
    """Ablehnungen nach denselben Regeln wie in der Maske."""

    def test_fuer_andere_nur_mit_dem_recht(self, projekt, zeitleistung,
                                           mitarbeiter, kollege):
        daten = _tabelle(_zeile(person='bernd', leistung='Montage',
                                von='8:00', bis='9:00'))

        ergebnis = _einlesen(daten, mitarbeiter)

        assert 'Recht' in _fehler(ergebnis)
        assert not Erfassungszeile.objects.exists()

    def test_mit_dem_recht_geht_es(self, projekt, zeitleistung,
                                   mitarbeiter, kollege):
        chef = _darf_fremde(mitarbeiter)
        daten = _tabelle(_zeile(person='bernd', leistung='Montage',
                                von='8:00', bis='9:00', abrechenbar='nein'))

        ergebnis = _einlesen(daten, chef)

        assert not ergebnis.has_validation_errors()
        zeile = Erfassungszeile.objects.get()
        assert zeile.benutzer == kollege
        assert zeile.abrechenbar is False

    def test_ohne_berechnung_nur_mit_dem_recht(self, projekt, zeitleistung,
                                               mitarbeiter):
        daten = _tabelle(_zeile(leistung='Montage', von='8:00', bis='9:00',
                                abrechenbar='nein'))

        ergebnis = _einlesen(daten, mitarbeiter)

        assert 'Ohne Berechnung' in _fehler(ergebnis)

    def test_kein_abgeschlossenes_projekt(self, abgeschlossenes_projekt,
                                          zeitleistung, mitarbeiter):
        daten = _tabelle(_zeile(projekt='2025-001', leistung='Montage',
                                von='8:00', bis='9:00'))

        ergebnis = _einlesen(daten, mitarbeiter)

        assert 'abgeschlossen' in _fehler(ergebnis)

    def test_keine_leistung_die_nicht_kontierbar_ist(
            self, projekt, nur_fuer_angebote, mitarbeiter):
        daten = _tabelle(_zeile(leistung='Baustelleneinrichtung'))

        ergebnis = _einlesen(daten, mitarbeiter)

        assert 'nicht für die Erfassung freigegeben' in _fehler(ergebnis)

    def test_eine_zeitleistung_ohne_uhrzeiten(self, projekt, zeitleistung,
                                              mitarbeiter):
        """Eine Zeitleistung ohne Uhrzeiten wird über ``full_clean`` und
        ``_pruefe_umfang`` abgelehnt."""
        ergebnis = _einlesen(_tabelle(_zeile(leistung='Montage')), mitarbeiter)

        assert 'keine Dauer' in _fehler(ergebnis)

    def test_ein_unbekanntes_projekt_wird_beim_namen_genannt(
            self, zeitleistung, mitarbeiter):
        ergebnis = _einlesen(_tabelle(_zeile(projekt='9999', leistung='Montage',
                                             von='8:00', bis='9:00')),
                             mitarbeiter)

        assert 'Projekt "9999" gibt es nicht' in _fehler(ergebnis)

    def test_eine_position_ohne_auftrag(self, projekt, auftragsposition,
                                        mitarbeiter):
        ergebnis = _einlesen(_tabelle(_zeile(position='10', von='8:00',
                                             bis='9:00')), mitarbeiter)

        assert 'gehören zusammen' in _fehler(ergebnis)

    def test_ein_fehler_haelt_die_ganze_datei_an(self, projekt, zeitleistung,
                                                 mitarbeiter):
        """Ein Fehler verhindert den Import der ganzen Datei."""
        daten = _tabelle(
            _zeile(leistung='Montage', von='8:00', bis='9:00'),
            _zeile(projekt='9999', leistung='Montage', von='8:00', bis='9:00'))

        ErfassungszeileResource().import_data(
            daten, dry_run=False, user=mitarbeiter,
            rollback_on_validation_errors=True)

        assert not Erfassungszeile.objects.exists()


class TestDerZweiteLauf:

    def test_dieselbe_datei_verdoppelt_nichts(self, projekt, zeitleistung,
                                              mitarbeiter):
        daten = _tabelle(_zeile(leistung='Montage', von='8:00', bis='9:00',
                                beschreibung='Aufmaß'))

        _einlesen(daten, mitarbeiter)
        ergebnis = _einlesen(daten, mitarbeiter)

        assert Erfassungszeile.objects.count() == 1
        assert ergebnis.totals['skip'] == 1

    def test_eine_andere_uhrzeit_ist_eine_neue_zeile(
            self, projekt, zeitleistung, mitarbeiter):
        _einlesen(_tabelle(_zeile(leistung='Montage', von='8:00', bis='9:00')),
                  mitarbeiter)
        _einlesen(_tabelle(_zeile(leistung='Montage', von='10:00', bis='11:00')),
                  mitarbeiter)

        assert Erfassungszeile.objects.count() == 2


class TestWasHinausgeht:

    def test_die_ausgabe_laesst_sich_wieder_einlesen(
            self, projekt, auftragsposition, zeitleistung, mitarbeiter):
        """Der Export lässt sich wieder importieren und dient als Vorlage."""
        services.zeile_erfassen(
            projekt=projekt, auftragsposition=auftragsposition,
            benutzer=mitarbeiter, datum=GESTERN,
            von=time(7, 30), bis=time(9, 0), beschreibung='Aufmaß')

        daten = ErfassungszeileResource().export()

        assert daten.headers == SPALTEN
        zeile = dict(zip(daten.headers, daten[0], strict=True))
        assert zeile['person'] == 'anna'
        assert zeile['auftrag'] == 'AU-2026-0005'
        assert zeile['position'] == '10'
        assert zeile['von'] == '07:30'

        ergebnis = _einlesen(daten, mitarbeiter)
        assert ergebnis.totals['skip'] == 1


@pytest.fixture
def als_mitarbeiter(client, mitarbeiter):
    mitarbeiter.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='erfassung',
        codename__in=['add_erfassungszeile', 'view_erfassungszeile',
                      'change_erfassungszeile'],
    ))
    client.force_login(mitarbeiter)
    return client


class TestDieMaskeImAdmin:

    @pytest.mark.parametrize('seite', ['import', 'export'])
    def test_die_seiten_laufen(self, als_mitarbeiter, seite):
        adresse = reverse(f'admin:erfassung_erfassungszeile_{seite}')

        assert als_mitarbeiter.get(adresse).status_code == 200

    def test_die_liste_bietet_den_import_an(self, als_mitarbeiter):
        inhalt = als_mitarbeiter.get(
            reverse('admin:erfassung_erfassungszeile_changelist')
        ).content.decode()

        assert reverse('admin:erfassung_erfassungszeile_import') in inhalt

    def test_hochladen_und_bestaetigen_legt_die_zeile_an(
            self, als_mitarbeiter, mitarbeiter, projekt, zeitleistung):
        """Upload und Bestätigung über die Maske legen die Zeile für den
        importierenden Benutzer an; die Vorschau speichert nichts."""
        datei = io.BytesIO(
            ('datum,person,projekt,auftrag,position,leistung,von,bis,menge,'
             'beschreibung,abrechenbar\n'
             f'{GESTERN:%d.%m.%Y},,2026-042,,,Montage,8:00,10:00,,Aufmaß,\n'
             ).encode())
        datei.name = 'stunden.csv'

        vorschau = als_mitarbeiter.post(
            reverse('admin:erfassung_erfassungszeile_import'),
            {'import_file': datei, 'format': '1'})

        assert vorschau.status_code == 200
        assert not Erfassungszeile.objects.exists()
        bestaetigen = vorschau.context['confirm_form']
        assert bestaetigen is not None, vorschau.content.decode()[:2000]

        antwort = als_mitarbeiter.post(
            reverse('admin:erfassung_erfassungszeile_process_import'),
            bestaetigen.initial)

        assert antwort.status_code == 302
        zeile = Erfassungszeile.objects.get()
        assert zeile.benutzer == mitarbeiter
        assert zeile.dauer_minuten == 120
