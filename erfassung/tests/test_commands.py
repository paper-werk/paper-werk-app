"""Rechtegruppen aus ``erfassung_rechte``.

Geprüft wird, ob ein Konto der Gruppe die Masken nutzen kann, nicht ob die
Gruppe bestimmte Rechte enthält; ein fehlendes Modell ergäbe sonst 403 ohne
Testfehler (wie in ``faktura/tests/admin/``).
"""

from datetime import time

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.urls import reverse

from core import gruppen
from erfassung import services

LISTE = 'admin:erfassung_erfassungszeile_changelist'
ANLEGEN = 'admin:erfassung_erfassungszeile_add'


@pytest.fixture
def rechte(db):
    call_command('erfassung_rechte', verbosity=0)


@pytest.mark.django_db
class TestErfassungRechte:

    def test_die_gruppe_kann_zeiten_buchen(
        self, rechte, client, mitarbeiter, projekt
    ):
        mitarbeiter.groups.add(Group.objects.get(name=gruppen.BUERO))
        client.force_login(mitarbeiter)

        assert client.get(reverse(LISTE)).status_code == 200
        assert client.get(reverse(ANLEGEN)).status_code == 200

    def test_ohne_gruppe_geht_nichts(self, rechte, client, mitarbeiter):
        """Ohne Gruppe kein Zugang, damit der Test oben mehr als die Existenz
        der Seite prüft."""
        client.force_login(mitarbeiter)

        assert client.get(reverse(LISTE)).status_code != 200

    def test_die_grundgruppe_darf_nicht_fuer_andere_buchen(
        self, rechte, mitarbeiter
    ):
        """Die Grundgruppe darf nicht für andere erfassen; das unterscheidet
        sie von der Leitung."""
        mitarbeiter.groups.add(Group.objects.get(name=gruppen.BUERO))

        assert not mitarbeiter.has_perm('erfassung.fuer_andere_erfassen')

    def test_die_leitung_darf_es(self, rechte, kollege):
        kollege.groups.add(Group.objects.get(name=gruppen.PROJEKTLEITUNG))

        assert kollege.has_perm('erfassung.fuer_andere_erfassen')

    def test_die_leitung_sieht_fremde_zeiten(
        self, rechte, client, kollege, mitarbeiter, projekt, zeitleistung
    ):
        """Die Leitung sieht fremde Zeiten in der Liste."""
        services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Arbeit der Kollegin',
        )
        kollege.groups.add(Group.objects.get(name=gruppen.PROJEKTLEITUNG))
        client.force_login(kollege)

        inhalt = client.get(reverse(LISTE)).content.decode()

        assert 'Arbeit der Kollegin' in inhalt

    def test_ein_zweiter_lauf_aendert_nichts(self, rechte, capsys):
        """Ein zweiter Lauf ändert nichts, weil das Setup bei jeder
        Installation läuft."""
        call_command('erfassung_rechte')

        ausgabe = capsys.readouterr().out
        assert 'nichts zu tun' in ausgabe
        assert 'kommt dazu' not in ausgabe

    def test_der_trockenlauf_aendert_nichts(self, db, capsys):
        """``--trocken`` ändert nichts."""
        call_command('erfassung_rechte', trocken=True)

        # Die Gruppe legt die Migration an; ``--trocken`` gibt ihr keine
        # Rechte.
        assert not Group.objects.get(name=gruppen.BUERO).permissions.exists()

    @pytest.mark.parametrize('reihenfolge', [
        ('faktura_rechte', 'erfassung_rechte'),
        ('erfassung_rechte', 'faktura_rechte'),
    ])
    def test_die_beiden_befehle_lassen_sich_gegenseitig_stehen(
        self, db, reihenfolge
    ):
        """``faktura_rechte`` und ``erfassung_rechte`` entziehen einander
        keine Rechte.

        Beide schreiben in dieselben Gruppen. Geprüft in beiden Reihenfolgen
        und nach jedem Lauf, weil ein zweiter Durchlauf einen Fehler des
        ersten verdecken kann und das Setup beim Kunden einmal läuft.
        """
        buero = Group.objects.get(name=gruppen.BUERO)
        for durchlauf in (1, 2):
            for befehl in reihenfolge:
                call_command(befehl, verbosity=0)
            apps = set(buero.permissions.values_list(
                'content_type__app_label', flat=True))
            assert {'faktura', 'erfassung'} <= apps, f'nach Durchlauf {durchlauf}'
