"""Archiviert Belege, die beim Festschreiben nicht ins Archiv gelangt sind.

Das Festschreiben lädt sofort hoch. Nachgeholt werden drei Fälle:

1. Das Archiv war nicht erreichbar (Neustart, Netz, Wartung).
2. Das Archiv hat die Datei angenommen, die Verarbeitung dauerte aber länger
   als ``PAPERLESS_WARTEZEIT``. Der Beleg hat dann eine Task-ID, aber noch
   keine Dokumentnummer.
3. Die Archivierung war ausgeschaltet, als die Belege entstanden.

Der Befehl ist idempotent und überspringt bereits archivierte Belege.
Vorgesehen für einen täglichen Lauf oder den manuellen Aufruf.

Aufruf::

    manage.py belege_archivieren            # alles Offene
    manage.py belege_archivieren --trocken  # nur zeigen, was anstünde
    manage.py belege_archivieren --grenze 20
"""

from django.core.management.base import BaseCommand, CommandError

from faktura import archiv, services
from faktura.models import Beleg, BelegStatus, BelegTyp


class Command(BaseCommand):
    help = 'Legt festgeschriebene Belege im Archiv ab, die noch nicht dort sind.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--trocken', action='store_true',
            help='Nur anzeigen, was hochgeladen würde.',
        )
        parser.add_argument(
            '--grenze', type=int, default=0,
            help='Höchstens so viele Belege bearbeiten (0 = alle).',
        )

    def handle(self, *args, **optionen):
        if not archiv.ist_eingerichtet():
            raise CommandError(
                'Die Archivierung ist nicht eingerichtet. Gebraucht werden '
                'PAPERLESS_URL, PAPERLESS_TOKEN und PAPERLESS_ARCHIVIERUNG=True.'
            )

        # Ohne Entwürfe, mit stornierten Belegen, weil auch eine stornierte
        # Rechnung aufbewahrungspflichtig ist (wie in belegarchiv_pruefen).
        #
        # Ohne Belegarten ohne Dokument (Auftrag). Der Service lehnte sie
        # ab; der Filter steht hier, damit die Zählung stimmt und der Lauf
        # sie nicht dauerhaft als "wartend" meldet.
        offen = (
            Beleg.objects
            .exclude(status=BelegStatus.ENTWURF)
            .filter(typ__in=BelegTyp.mit_dokument())
            .filter(paperless_id__isnull=True)
            .order_by('nummer')
        )
        if grenze := optionen['grenze']:
            offen = offen[:grenze]

        gesamt = len(offen)
        if not gesamt:
            self.stdout.write(self.style.SUCCESS('Nichts offen; alles archiviert.'))
            return

        if optionen['trocken']:
            self.stdout.write(f'{gesamt} Beleg(e) wären zu archivieren:')
            for beleg in offen:
                stand = (f'Aufgabe {beleg.paperless_task_id} offen'
                         if beleg.paperless_task_id else 'noch nicht hochgeladen')
                self.stdout.write(f'  {beleg.nummer}: {stand}')
            return

        abgelegt = wartend = gescheitert = 0

        for beleg in offen:
            try:
                # warten=False, weil bei vielen Belegen das Warten je Beleg
                # die Laufzeit bestimmte. Die Dokumentnummer holt der nächste
                # Lauf.
                ergebnis = services.beleg_archivieren(beleg_id=beleg.pk, warten=False)
            except Exception as fehler:
                gescheitert += 1
                self.stderr.write(self.style.ERROR(f'  {beleg.nummer}: {fehler}'))
                continue

            if ergebnis.paperless_id is not None:
                abgelegt += 1
                self.stdout.write(self.style.SUCCESS(
                    f'  {beleg.nummer}: Dokument {ergebnis.paperless_id}'))
            else:
                wartend += 1
                self.stdout.write(
                    f'  {beleg.nummer}: übergeben, Nummer steht noch aus')

        self.stdout.write('')
        self.stdout.write(
            f'{gesamt} geprüft: {abgelegt} abgelegt, {wartend} in Arbeit, '
            f'{gescheitert} gescheitert.'
        )
        if wartend:
            self.stdout.write(
                'Für die noch offenen genügt ein zweiter Lauf; die '
                'Aufgabennummern stehen an den Belegen.'
            )
