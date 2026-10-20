"""Detailaktion „Leistungsnachweis“ an der Rechnung: PDF anzeigen.

Am Entwurf und an der festgeschriebenen Rechnung, bei jedem Aufruf neu
erzeugt. Der Nachweis ist kein Beleg und wird nicht festgeschrieben; hier
lässt er sich auch nach dem Versand erzeugen.

Registriert wie „Erbrachte Leistungen hinzufügen“ über
``core.erweiterungen.belegaktion()``; ``self`` ist zur Laufzeit eine
Instanz von ``RechnungAdmin``. Der Name ist ``detail_`` plus die Art der
Anlage, damit die Versandmaske in ``faktura`` ohne Import dieser App auf die
Vorschau verlinkt.
"""

from django.contrib import messages
from django.http import HttpResponse
from unfold.decorators import action as unfold_action

from faktura import services as faktura_services

from ..services import hat_nachweis

ART = 'leistungsnachweis'
TITEL = 'Leistungsnachweis'


@unfold_action(
    description=TITEL,
    icon='fact_check',
    permissions=['leistungsnachweis'],
    url_path=ART,
    attrs={'target': '_blank'},
)  # type: ignore
def detail_leistungsnachweis(self, request, object_id):
    beleg = self._beleg_oder_none(object_id)
    if beleg is None:
        return self._zurueck_zum_beleg(request, object_id)

    daten = faktura_services.anlage_pdf(beleg, ART)
    if daten is None:
        self.message_user(
            request, f'Zu {beleg} gibt es keinen Leistungsnachweis.',
            messages.WARNING)
        return self._zurueck_zum_beleg(request, object_id)

    antwort = HttpResponse(daten, content_type='application/pdf')
    antwort['Content-Disposition'] = (
        f'inline; filename="{faktura_services.anlage_dateiname(beleg, TITEL)}"')
    return antwort


def has_leistungsnachweis_permission(self, request, object_id=None):
    """Mit Leserecht an jeder Rechnung mit abgerechneten Stunden oder
    Fremdleistungen, auch nach dem Festschreiben."""
    if not self.has_view_permission(request):
        return False
    beleg = self._beleg_oder_none(object_id)
    return beleg is not None and hat_nachweis(beleg)
