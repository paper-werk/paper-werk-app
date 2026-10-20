"""Legt einen Dienstzugang an und gibt seinen API-Schlüssel aus.

Ein Dienstzugang ist ein Benutzer für Automatisierung (n8n). Er wird
angelegt:

* **ohne nutzbares Passwort**, damit die Authentifizierung nur über den
  Schlüssel läuft;
* **ohne Admin-Zugang** (``is_staff=False``), damit ein entwendeter
  Schlüssel keinen Zugang zur Oberfläche gibt;
* **ohne eigene Rechte.** Rechte kommen über Gruppen; ``/api/v1/ich/``
  zeigt, welche der Zugang hat.

Aufrufe::

    python manage.py api_schluessel n8n --anlegen
    python manage.py api_schluessel n8n              # zeigt den Schlüssel
    python manage.py api_schluessel n8n --neu        # erneuert ihn

Ein bestehender Schlüssel lässt sich erneut ausgeben, weil
``rest_framework.authtoken`` ihn im Klartext speichert (wie Paperless-ngx).
Wer Zugriff auf die Datenbank hat, hat ohnehin Zugriff auf alle Daten.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from rest_framework.authtoken.models import Token

from core import gruppen

#: Vorgabe für --gruppe; beide Gruppen legt ``faktura_rechte`` an. n8n braucht
#: "Faktura Dienst" für die Belegabholung und "Belegübernahme" für die
#: Eingangsrechnungen aus dem Archiv.
#:
#: Die Gruppen sind hier als Vorgabe hinterlegt, weil Git Bash unter Windows
#: Umlaute in Argumenten für native Programme beschädigt und das Setup sie
#: deshalb nicht übergeben kann.
DIENSTGRUPPEN = [gruppen.DIENST, gruppen.BELEGUEBERNAHME]


class Command(BaseCommand):
    help = 'Zeigt oder erzeugt den API-Schlüssel eines Dienstzugangs.'

    def add_arguments(self, parser):
        parser.add_argument('benutzer', help='Anmeldename des Dienstzugangs.')
        parser.add_argument(
            '--anlegen', action='store_true',
            help='Den Benutzer anlegen, falls es ihn noch nicht gibt.',
        )
        parser.add_argument(
            '--neu', action='store_true',
            help='Einen neuen Schlüssel erzeugen. Der bisherige wird ungültig.',
        )
        parser.add_argument(
            '--gruppe', action='append',
            help='Gruppe, in die der Zugang kommt, mehrfach möglich '
                 f'(Vorgabe: {", ".join(DIENSTGRUPPEN)}). '
                 'Leer lassen mit --gruppe "" für einen Zugang ohne Rechte.',
        )

    def handle(self, *args, **optionen):
        name = optionen['benutzer']
        Benutzer = get_user_model()

        benutzer = Benutzer.objects.filter(username=name).first()

        if benutzer is None:
            if not optionen['anlegen']:
                raise CommandError(
                    f'Benutzer "{name}" gibt es nicht. '
                    f'Mit --anlegen wird er eingerichtet.'
                )
            benutzer = self._anlegen(Benutzer, name)

        gruppennamen = optionen['gruppe']
        if gruppennamen is None:
            gruppennamen = DIENSTGRUPPEN
        for gruppenname in gruppennamen:
            if gruppenname:
                self._einordnen(benutzer, gruppenname)

        schluessel, neu_erzeugt = self._schluessel(benutzer, erneuern=optionen['neu'])

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'  {schluessel.key}'))
        self.stdout.write('')
        self.stdout.write(f'  Benutzer: {benutzer.get_username()}')
        self.stdout.write(f'  Gruppen:  {self._gruppenliste(benutzer)}')
        self.stdout.write(
            f'  Schlüssel: {"neu erzeugt" if neu_erzeugt else "bestehend"}')
        self.stdout.write('')
        self.stdout.write('  Verwendung:')
        self.stdout.write(f'    Authorization: Token {schluessel.key}')
        self.stdout.write('')
        self.stdout.write('  Prüfen mit:')
        self.stdout.write(
            f'    curl -H "Authorization: Token {schluessel.key}" '
            f'http://localhost:8000/api/v1/ich/')
        self.stdout.write('')

    def _anlegen(self, Benutzer, name):
        with transaction.atomic():
            benutzer = Benutzer.objects.create(username=name, is_staff=False)
            # Kein Passwort, das jemand erraten oder wiederverwenden könnte.
            benutzer.set_unusable_password()
            benutzer.save(update_fields=['password'])

        self.stdout.write(self.style.SUCCESS(
            f'Dienstzugang "{name}" angelegt, ohne Passwort, ohne Admin-Zugang.'))
        return benutzer

    def _einordnen(self, benutzer, gruppenname):
        gruppe = Group.objects.filter(name=gruppenname).first()

        if gruppe is None:
            # Kein Abbruch, der Schlüssel wird trotzdem ausgegeben. Die
            # Warnung erklärt die 403, die der Zugang ohne Rechte erhält.
            self.stdout.write(self.style.WARNING(
                f'Gruppe "{gruppenname}" gibt es nicht; der Zugang bleibt '
                f'ohne Rechte.\n'
                f'Anlegen mit:  python manage.py faktura_rechte'))
            return

        if not benutzer.groups.filter(pk=gruppe.pk).exists():
            benutzer.groups.add(gruppe)
            self.stdout.write(f'In die Gruppe "{gruppenname}" aufgenommen.')

    @staticmethod
    def _schluessel(benutzer, *, erneuern: bool) -> tuple[Token, bool]:
        if erneuern:
            Token.objects.filter(user=benutzer).delete()
            return Token.objects.create(user=benutzer), True

        schluessel, neu = Token.objects.get_or_create(user=benutzer)
        return schluessel, neu

    @staticmethod
    def _gruppenliste(benutzer) -> str:
        namen = list(benutzer.groups.values_list('name', flat=True))
        return ', '.join(namen) if namen else '- keine -'
