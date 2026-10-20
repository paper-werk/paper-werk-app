"""Prüft das Belegarchiv gegen die gespeicherten Prüfsummen.

Beim Festschreiben wird das PDF mit SHA-256-Prüfsumme gespeichert; dieser
Befehl prüft, ob Datei und Prüfsumme vorhanden sind und übereinstimmen.

Vorgesehen für den regelmäßigen Lauf, etwa täglich per Cron oder nach jeder
Datensicherung:

    python manage.py pruefe_belegarchiv

Bei Beanstandungen endet der Befehl mit Exit-Code 1 (CommandError), damit
Cron, CI oder die Überwachung Alarm schlagen können, ohne die Ausgabe zu
lesen. Die Prüflogik liegt in services.belegarchiv_pruefen(), der Befehl
gibt nur aus.
"""

from django.core.management.base import BaseCommand, CommandError

from faktura import services


class Command(BaseCommand):
    help = (
        'Prüft, ob jeder festgeschriebene Beleg sein PDF hat und dessen '
        'SHA-256-Prüfsumme noch stimmt. Exit-Code 1 bei Beanstandungen.'
    )

    def handle(self, *args, **options):
        bericht = services.belegarchiv_pruefen()

        for befund in bericht.befunde:
            self.stderr.write(f'{befund.beleg} (id {befund.beleg_id}): {befund.problem}')

        if not bericht.in_ordnung:
            raise CommandError(
                f'{len(bericht.befunde)} von {bericht.geprueft} Belegen beanstandet.'
            )

        self.stdout.write(self.style.SUCCESS(
            f'{bericht.geprueft} Belege geprüft, keine Beanstandung.'
        ))
