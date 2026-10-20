"""Änderungshistorie von Erfassungszeilen und Fremdleistungen (GoBD).

Eine erfasste Zeit ist abrechnungsrelevantes Ursprungsdatum; jede Änderung
vor der Abrechnung ist mit Benutzer, Zeitpunkt und vorigem Stand
nachvollziehbar.

Geprüft über das Formular im Admin, weil nur dort die Middleware den
Benutzer setzt. Kein Test als Superuser.
"""

from datetime import date, time
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from erfassung import services
from erfassung.models import Eingangsrechnung, Erfassungszeile, Fremdleistung
from faktura.models import Kontakt

AENDERN = 'admin:erfassung_erfassungszeile_change'
GESCHICHTE = 'admin:erfassung_erfassungszeile_history'


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
def zeile(projekt, zeitleistung, mitarbeiter):
    return services.zeile_erfassen(
        projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
        von=time(8, 0), bis=time(10, 0), beschreibung='Gutachten, Entwurf',
    )


def _aendern(client, zeile, **felder):
    daten = {
        'datum': zeile.datum.strftime('%d.%m.%Y'),
        'projekt': zeile.projekt_id,
        'leistung': zeile.leistung_id,
        'von': zeile.von.strftime('%H:%M'),
        'bis': zeile.bis.strftime('%H:%M'),
        'menge': '',
        'beschreibung': zeile.beschreibung,
        'abrechenbar': 'on',
    }
    daten.update(felder)
    return client.post(reverse(AENDERN, args=[zeile.pk]), daten)


@pytest.mark.django_db
class TestErfassungszeile:

    def test_anlegen_ist_der_erste_stand(self, zeile):
        assert [s.history_type for s in zeile.history.all()] == ['+']

    def test_aenderung_haelt_alten_und_neuen_stand_fest(
            self, als_mitarbeiter, zeile, mitarbeiter):
        antwort = _aendern(als_mitarbeiter, zeile, bis='11:30')
        assert antwort.status_code == 302, antwort.content.decode()[:2000]

        neu, alt = zeile.history.all()[:2]
        assert neu.history_type == '~'
        assert neu.history_user == mitarbeiter
        unterschied = {c.field: (c.old, c.new)
                       for c in neu.diff_against(alt).changes}
        assert unterschied['bis'] == (time(10, 0), time(11, 30))
        # In jedem Stand enthalten, aber nicht im Diff (kein Eingabefeld).
        assert (alt.dauer_minuten, neu.dauer_minuten) == (120, 210)

    def test_die_geschichte_ist_im_admin_zu_sehen(
            self, als_mitarbeiter, zeile):
        _aendern(als_mitarbeiter, zeile, beschreibung='Gutachten, Endfassung')

        antwort = als_mitarbeiter.get(reverse(GESCHICHTE, args=[zeile.pk]))

        assert antwort.status_code == 200
        inhalt = antwort.content.decode()
        assert 'Gutachten, Entwurf' in inhalt
        assert 'Gutachten, Endfassung' in inhalt

    def test_ein_frueherer_stand_laesst_sich_nicht_zurueckholen(
            self, als_mitarbeiter, zeile):
        """Kein Revert, weil er Sperre und Validierung der Maske umginge."""
        _aendern(als_mitarbeiter, zeile, bis='11:30')
        frueher = zeile.history.earliest()

        # Vollständiges, gültiges Formular, weil
        # SIMPLE_HISTORY_REVERT_DISABLED bis 3.13 nur den Button ausblendet
        # und der POST trotzdem speicherte.
        daten = {
            'datum': zeile.datum.strftime('%d.%m.%Y'),
            'projekt': zeile.projekt_id, 'leistung': zeile.leistung_id,
            'von': '08:00', 'bis': '10:00', 'menge': '',
            'beschreibung': zeile.beschreibung, 'abrechenbar': 'on',
        }
        antwort = als_mitarbeiter.post(
            reverse('admin:erfassung_erfassungszeile_simple_history',
                    args=[zeile.pk, frueher.history_id]), daten)

        assert antwort.status_code == 403
        zeile.refresh_from_db()
        assert zeile.bis == time(11, 30)

    def test_loeschen_bleibt_nachvollziehbar(self, zeile):
        pk = zeile.pk
        zeile.delete()

        staende = Erfassungszeile.history.filter(id=pk)
        assert [s.history_type for s in staende] == ['-', '+']


@pytest.mark.django_db
class TestFremdleistung:

    def test_aenderung_haelt_alten_stand_fest(self, projekt):
        labor = Kontakt.objects.create(
            ist_kunde=False, ist_lieferant=True, name='ISARTAL')
        rechnung = Eingangsrechnung.objects.create(
            lieferant=labor, nummer='AL-1', datum=date(2026, 8, 1),
            betrag_netto=Decimal('192.00'))
        posten = Fremdleistung.objects.create(
            rechnung=rechnung, projekt=projekt, bezeichnung='Paket 4711',
            menge=Decimal('2'), einkaufspreis=Decimal('96.00'))

        posten.menge = Decimal('3')
        posten.save()

        neu, alt = posten.history.all()[:2]
        unterschied = {c.field: (c.old, c.new)
                       for c in neu.diff_against(alt).changes}
        assert unterschied['menge'] == (Decimal('2.00'), Decimal('3.00'))
