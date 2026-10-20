"""Aus jedem Lieferanten wird ein Kontakt mit der Rolle Lieferant.

Heißt ein Kontakt schon so (ohne Rücksicht auf Groß- und Kleinschreibung),
bekommt er die Rolle dazu; ein Betrieb, der zugleich Kunde und Lieferant
ist, steht danach einmal da. Sonst entsteht ein neuer Kontakt mit Nummer
aus dem Kundennummernkreis. "Unsere Nummer dort" wird zur Eigenen
Kundennummer, die Notiz wandert mit. Die Eingangsrechnungen zeigen danach
auf den Kontakt.
"""

from django.db import migrations
from sequences import get_next_value


def _neue_nummer(Kontakt) -> str:
    """Wie ``naechste_kundennummer``; die Modellmethode gibt es in einer
    Migration nicht."""
    while True:
        nummer = f'K-{get_next_value("kundennummer", initial_value=1000)}'
        if not Kontakt.objects.filter(nummer=nummer).exists():
            return nummer


def lieferanten_uebernehmen(apps, schema_editor):
    Lieferant = apps.get_model('erfassung', 'Lieferant')
    Eingangsrechnung = apps.get_model('erfassung', 'Eingangsrechnung')
    Kontakt = apps.get_model('faktura', 'Kontakt')

    for lieferant in Lieferant.objects.order_by('pk'):
        kontakt = (Kontakt.objects.filter(name__iexact=lieferant.name)
                   .order_by('pk').first())
        if kontakt is None:
            kontakt = Kontakt.objects.create(
                nummer=_neue_nummer(Kontakt),
                name=lieferant.name,
                ist_kunde=False,
                ist_lieferant=True,
                eigene_kundennummer=lieferant.kundennummer,
                notiz=lieferant.notiz,
            )
        else:
            kontakt.ist_lieferant = True
            if not kontakt.eigene_kundennummer:
                kontakt.eigene_kundennummer = lieferant.kundennummer
            if lieferant.notiz:
                kontakt.notiz = '\n\n'.join(
                    teil for teil in (kontakt.notiz, lieferant.notiz) if teil)
            kontakt.save(update_fields=['ist_lieferant', 'eigene_kundennummer',
                                        'notiz'])
        Eingangsrechnung.objects.filter(lieferant=lieferant).update(
            lieferant_kontakt=kontakt)


class Migration(migrations.Migration):

    dependencies = [
        ('erfassung', '0014_lieferant_kontakt_anlegen'),
        ('sequences', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(lieferanten_uebernehmen, migrations.RunPython.noop),
    ]
