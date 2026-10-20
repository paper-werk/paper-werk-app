"""Setzt die Rechte der Gruppen an der Leistungserfassung.

Die Rechte stehen im Code neben den Modellen, damit ein neues Modell nicht
in einer Liste der Installation fehlt. Idempotent; ``--trocken`` zeigt nur
an.

Die Gruppen teilt der Befehl mit ``faktura_rechte`` (Namen in
``core/gruppen.py``); jeder Befehl setzt nur die Rechte seiner Apps.
"""

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from core import gruppen

#: Erfassen eigener Zeiten.
GRUPPE = gruppen.BUERO

#: Erfassen für andere; schließt das Sehen der Stunden aller ein.
GRUPPE_LEITUNG = gruppen.PROJEKTLEITUNG

#: Alle Rechte: anlegen, ansehen, ändern, löschen. Nicht abgerechnete
#: Zeilen sind frei änderbar, abgerechnete sperrt der Service.
VOLL = ['erfassungszeile']

#: Apps, deren Rechte der Befehl setzt.
APPS = ['erfassung']

#: Zusätzliche Rechte der Leitung.
ZUSAETZLICH = ['fuer_andere_erfassen']

#: Modelle, die nur die Leitung sieht.
#
# Eingangsrechnungen enthalten Einkaufspreise und damit die Spanne des
# Betriebs. Ein Recht später zu vergeben ist einfacher, als es wieder zu
# entziehen.
NUR_LEITUNG = ['eingangsrechnung', 'fremdleistung', 'kostensatz']


class Command(BaseCommand):
    help = 'Setzt die Rechte der paper-werk-Gruppen an der Leistungserfassung.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--trocken', action='store_true',
            help='Nur anzeigen, was sich ändern würde.',
        )

    def handle(self, *args, **optionen):
        alle = Permission.objects.filter(content_type__app_label__in=APPS)
        grund = set(alle.filter(content_type__model__in=VOLL).exclude(
            codename__in=ZUSAETZLICH))
        leitung = (grund
                   | set(alle.filter(codename__in=ZUSAETZLICH))
                   | set(alle.filter(content_type__model__in=NUR_LEITUNG)))

        uebernahme = set(alle.filter(
            codename__in=['add_eingangsrechnung', 'view_eingangsrechnung']))

        for name, soll in ((GRUPPE, grund), (GRUPPE_LEITUNG, leitung),
                           (gruppen.BELEGUEBERNAHME, uebernahme)):
            self._gruppe_stellen(name, soll, optionen['trocken'])

    def _gruppe_stellen(self, name: str, soll: set, trocken: bool) -> None:
        # Erst prüfen, dann anlegen, damit ``--trocken`` nichts ändert.
        gruppe = Group.objects.filter(name=name).first()
        alle = set(gruppe.permissions.all()) if gruppe else set()
        # Nur die Rechte der eigenen Apps.
        ist = {r for r in alle if r.content_type.app_label in APPS}
        dazu, weg = soll - ist, ist - soll

        for beschriftung, menge, stil in (
            ('kommt dazu', dazu, self.style.SUCCESS),
            # Entzogene Rechte werden angezeigt, weil der Befehl den Sollstand
            # herstellt und dabei auch Rechte entfernt.
            ('fällt weg', weg, self.style.WARNING),
        ):
            for recht in sorted(menge, key=lambda r: r.codename):
                self.stdout.write(stil(f'  {beschriftung}: {recht.codename}'))

        if not dazu and not weg:
            self.stdout.write(self.style.SUCCESS(
                f'Gruppe "{name}": {len(soll)} Rechte, nichts zu tun.'))
            return

        if trocken:
            self.stdout.write(f'Gruppe "{name}": Trockenlauf, nichts geändert.')
            return

        gruppe = gruppe or Group.objects.create(name=name)
        gruppe.permissions.set((alle - ist) | soll)
        self.stdout.write(self.style.SUCCESS(
            f'Gruppe "{name}": {len(soll)} Rechte gesetzt.'))
