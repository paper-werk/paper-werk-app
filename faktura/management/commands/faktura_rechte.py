"""Setzt die Rechte der paper-werk-Gruppen an den Modellen von faktura.

Die Rechteliste steht im Code neben den Modellen, weil manuell gepflegte
Gruppen bei neuen Modellen nicht mitwachsen und das als Superuser nicht
auffällt. Idempotent: Jeder Lauf stellt denselben Zustand her.

    python manage.py faktura_rechte
    python manage.py faktura_rechte --trocken   # nur zeigen, nichts ändern

Arbeitsgruppen (Personen) und die Lesegruppe für Dienstzugänge leiten ihre
Rechte aus derselben Modellliste ab. ``erfassung_rechte`` pflegt dieselben
Gruppen; jeder Befehl setzt nur die Rechte seiner App und lässt die übrigen
unverändert. Die Gruppennamen stehen in
``core/gruppen.py``.
"""

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction

from core import gruppen

#: Gruppen, die Belege erstellen. Die Verwaltung fehlt, weil sie Superuser
#: ist.
ARBEITSGRUPPEN = [gruppen.BUERO, gruppen.PROJEKTLEITUNG]

#: Lesegruppe für Dienstzugänge (n8n), nur ``view``, damit ein fehlerhafter
#: Workflow keine Buchungsdaten ändert. Schreibrechte werden einzeln
#: vergeben (``DIENST_ZUSAETZLICH``).
GRUPPE_DIENST = gruppen.DIENST

#: Volle Rechte (add, change, view, delete), auch an den Stammdaten.
#
# Die Custom Permissions am Beleg sind enthalten (``archivieren_beleg``,
# ``controlling_ansehen``, ``beleg_wiedereroeffnen``), weil über den
# Modelltyp gefiltert wird. Eine Einschränkung gehört hierher; im Admin
# entfernt, setzte der nächste Lauf das Recht wieder.
VOLL = [
    'kontakt',
    # Alle Tabellen eines Kunden einzeln, weil das Kundenformular sonst ein
    # leeres Inline ohne Hinweis zeigt.
    'adresse', 'ansprechpartner', 'kontaktweg',
    'projekt',
    'katalogposition',
    'textbaustein',
    'beleg', 'belegposition',
    'angebot', 'auftrag', 'lieferschein',
    'rechnung', 'abschlagsrechnung', 'schlussrechnung', 'teilschlussrechnung',
    # Abnahmen, aus denen die Schlussrechnung entsteht.
    'abnahme',
    'stornorechnung', 'rechnungskorrektur', 'mahnung',
    # Zahlungseingänge; erfasst von denselben Gruppen, die Rechnungen
    # schreiben. Verworfen: eine eigene Gruppe für Zahlungen.
    'zahlung', 'zahlungszuordnung',
]

#: Eingeschränkte Rechte je Tabelle.
#
# Die Firma enthält die Angaben des Absenders (Bankverbindung, Steuernummer,
# Handelsregister). Es gibt genau eine (FirmaAdmin verbietet das Anlegen);
# gelöscht fehlte allen Belegen der Briefkopf.
#
# Frühere Fassungen entstehen nur durch ``erechnung_neu_ausstellen`` und
# dienen als Nachweis: nur ``view``.
#
# Steuersätze: anlegen und ändern, nicht löschen. Positionen speichern den
# Satz als Wert; abgelöst wird über "wählbar", siehe models/steuersatz.py.
EINGESCHRAENKT = {'firma': ['view', 'change'], 'belegfassung': ['view'],
                  'steuersatz': ['view', 'add', 'change']}

#: Ausgenommen von den Rechten der Lesegruppe.
#
# Die Firma mit Bankverbindung, Steuernummer und Handelsregister. Ein
# Dienstzugang, der Belege abruft, erhält diese Angaben über das PDF und
# braucht die Tabelle nicht.
OHNE_DIENST = ['firma']

#: Rechte der Lesegruppe über ``view`` hinaus, einzeln aufgezählt.
#
# Der Archivierungslauf speichert die Dokumentnummer, weil er sonst dieselbe
# Rechnung erneut ablegt.
#
# Dafür ein eigenes Recht, weil ``change_beleg`` das Ändern von Belegen
# erlaubte. Weitere Einträge aus demselben Grund einzeln ergänzen.
DIENST_ZUSAETZLICH = ['archivieren_beleg']


class Command(BaseCommand):
    help = 'Setzt die Faktura-Rechte der paper-werk-Gruppen und von "Faktura Dienst".'

    def add_arguments(self, parser):
        parser.add_argument(
            '--trocken', action='store_true',
            help='Nur anzeigen, was sich ändern würde.',
        )

    def handle(self, *args, **optionen):
        geaendert = False

        auftraege = [(name, self._gewuenschte_rechte()) for name in ARBEITSGRUPPEN]
        auftraege.append((GRUPPE_DIENST, self._dienstrechte()))
        auftraege.append((gruppen.BELEGUEBERNAHME, set(Permission.objects.filter(
            content_type__app_label='faktura', codename='view_projekt'))))
        for name, soll in auftraege:
            geaendert |= self._gruppe_stellen(name, soll, optionen['trocken'])

        if optionen['trocken'] and geaendert:
            self.stdout.write('Trockenlauf; nichts geändert.')

    def _gruppe_stellen(self, name: str, soll: set, trocken: bool) -> bool:
        """Setzt die Rechte einer Gruppe auf den Sollzustand. Gibt zurück, ob
        sich etwas änderte."""
        # Erst suchen, dann anlegen, damit ``--trocken`` nichts ändert.
        gruppe = Group.objects.filter(name=name).first()
        alle = set(gruppe.permissions.all()) if gruppe else set()
        # Nur Rechte dieser App; Rechte anderer Apps bleiben (siehe
        # Modul-Docstring).
        ist = {r for r in alle if r.content_type.app_label == 'faktura'}

        dazu = soll - ist
        weg = ist - soll

        if gruppe is None:
            self.stdout.write(f'Gruppe "{name}" gibt es noch nicht.')

        self._auflisten('kommt dazu', dazu, self.style.SUCCESS)
        # Entfernte Rechte werden ausgegeben, weil der Befehl den Sollzustand
        # auch durch Entziehen herstellt; ``--trocken`` zeigt sie vorab.
        self._auflisten('fällt weg', weg, self.style.WARNING)

        if not dazu and not weg:
            self.stdout.write(self.style.SUCCESS(
                f'Gruppe "{name}": {len(soll)} Rechte, nichts zu tun.'))
            return False

        if trocken:
            return True

        with transaction.atomic():
            gruppe, _ = Group.objects.get_or_create(name=name)
            gruppe.permissions.set((alle - ist) | soll)

        self.stdout.write(self.style.SUCCESS(
            f'Gruppe "{name}": {len(soll)} Rechte gesetzt.'))
        return True

    def _auflisten(self, titel, rechte, stil):
        if not rechte:
            return
        self.stdout.write(stil(f'  {titel} ({len(rechte)}):'))
        for recht in sorted(rechte, key=lambda r: r.codename):
            self.stdout.write(f'    {recht.codename}')

    @staticmethod
    def _gewuenschte_rechte() -> set:
        """Die Rechte als Set von Permission-Objekten.

        Über ``content_type__model``, weil ein Codename auch zu einem Modell
        einer anderen App passen kann.
        """
        gesucht = Permission.objects.filter(
            content_type__app_label='faktura')

        rechte = set(gesucht.filter(content_type__model__in=VOLL))

        for modell, arten in EINGESCHRAENKT.items():
            rechte |= set(gesucht.filter(
                content_type__model=modell,
                codename__in=[f'{art}_{modell}' for art in arten],
            ))

        return rechte

    @staticmethod
    def _dienstrechte() -> set:
        """Nur ``view``, und nur auf den fachlichen Modellen.

        Abgeleitet aus derselben Liste wie die Arbeitsgruppe, damit ein neues
        Modell ohne zweiten Eintrag das Leserecht für Dienstzugänge erhält.
        """
        modelle = [m for m in VOLL if m not in OHNE_DIENST]

        faktura = Permission.objects.filter(content_type__app_label='faktura')

        return set(faktura.filter(
            content_type__model__in=modelle,
            codename__startswith='view_',
        )) | set(faktura.filter(codename__in=DIENST_ZUSAETZLICH))
