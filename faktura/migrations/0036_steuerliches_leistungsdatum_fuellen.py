"""Das Leistungsdatum (BT-72) der vorhandenen Rechnungen in sein eigenes
Feld.

Übernommen wird das Ende des Leistungszeitraums, ohne Zeitraum das
Leistungsdatum. Abschläge und was sie storniert oder korrigiert bleiben
leer, weil sie Anzahlungen sind. Über ``update()``: Festgeschriebene Belege
lassen sich sonst nicht anfassen, und das hier ist keine Änderung des
Inhalts, nur sein Umzug in ein anderes Feld.

Getrennt vom Schema (0035), wie in erfassung 0017 bis 0019: Daten und
Schema in einem Schritt scheitern bei PostgreSQL an "pending trigger
events".
"""

from django.db import migrations
from django.db.models import F, Q
from django.db.models.functions import Coalesce

STEUERBELEGE = ('rechnung', 'storno', 'gutschrift')


def fuellen(apps, schema_editor):
    Beleg = apps.get_model('faktura', 'Beleg')
    (Beleg.objects
     .filter(typ__in=STEUERBELEGE, steuerliches_leistungsdatum__isnull=True)
     .exclude(rechnungsart='abschlag')
     .exclude(Q(typ__in=('storno', 'gutschrift'))
              & Q(vorgaenger__rechnungsart='abschlag'))
     .update(steuerliches_leistungsdatum=Coalesce(
         F('leistungsdatum_bis'), F('leistungsdatum'))))


class Migration(migrations.Migration):

    dependencies = [
        ('faktura', '0035_steuerliches_leistungsdatum'),
    ]

    operations = [
        migrations.RunPython(fuellen, migrations.RunPython.noop),
    ]
