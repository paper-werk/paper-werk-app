"""Stammdaten in den Beleg kopieren.

Zwei Wege mit derselben Feldliste (``services.stammdatenwerte``): Im
Browser füllt ein Skript das Formular vor (JSON-Endpunkt ``kundendaten``),
verbindlich ist ``save_model`` auf dem Server. Eingaben des Benutzers
bleiben in beiden Fällen erhalten.
"""


from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from .. import services
from ..models import (
    Kontakt,
    Projekt,
)


class UebernahmeMixin:
    """Setzt beim Anlegen im Admin Belegart und Stammdaten."""


    def save_model(self, request, obj, form, change):
        """Setzt beim Anlegen Belegart und Rechnungsart aus dem Menüpunkt und
        kopiert die Stammdaten des Kunden oder Projekts.

        Die Rechnungsart bleibt am Entwurf änderbar. Übernommen werden Felder,
        die der Benutzer nicht ausgefüllt hat; eine Prüfung auf leere Felder
        reicht nicht, weil Felder mit Vorgabe (14 Tage, 'DE') nie leer sind.
        """
        if not change:
            if self.typ:
                obj.typ = self.typ
            if self.rechnungsart:
                obj.rechnungsart = self.rechnungsart
            quelle = services.anschriftgeber(obj)
            if quelle is not None:
                services.stammdaten_uebernehmen(
                    beleg=obj, kunde=quelle,
                    ausser=self._vom_anwender_gesetzt(form),
                )
        super().save_model(request, obj, form, change)
        self._auf_abweichung_hinweisen(request, obj)

    @staticmethod
    def _vom_anwender_gesetzt(form) -> list[str]:
        """Felder, die im Formular tatsächlich ausgefüllt wurden.

        ``form.changed_data`` enthält auch Felder, die im POST fehlen und für
        die Django die Modellvorgabe einsetzt. Ausgeschlossen werden sie über
        ``value_omitted_from_data()``, das Django dafür selbst verwendet.
        """
        return [
            name for name in form.changed_data
            if not form.fields[name].widget.value_omitted_from_data(
                form.data, form.files, form.add_prefix(name)
            )
        ]

    def _auf_abweichung_hinweisen(self, request, beleg, nachsatz=''):
        """Warnt, wenn Ausdruck und E-Rechnung verschiedene Empfänger nennen;
        korrigiert wird nichts."""
        befunde = services.empfaenger_abweichungen(beleg)
        if not befunde:
            return
        self.message_user(
            request,
            f'{beleg}: Der Ausdruck zeigt das Empfängerfeld, die eingebettete '
            f'E-Rechnung die Felder unter "E-Rechnung", und beide weichen ab '
            f'({"; ".join(befunde)}). {nachsatz}'.strip(),
            messages.WARNING,
        )

    #: Felder aus den Stammdaten, im Anlegeformular optional; abgeleitet aus
    #: den Schlüsseln von ``services.stammdatenwerte``.
    UEBERNAHMEFELDER = list(services.stammdatenwerte(Kontakt()))

    def kundendaten(self, request):
        """Stammdaten als JSON zum Vorbefüllen, nach ``?kunde=`` oder
        ``?projekt=``.

        Nur für die Bedienung, keine Quelle der Fachlogik. Prüft das
        Leserecht an Kunde und Projekt, weil ``admin_view()`` nur Login und
        Staff prüft.
        """
        kunden_admin = self.admin_site.get_model_admin(Kontakt)
        if not kunden_admin.has_view_permission(request):
            raise PermissionDenied

        if 'projekt' in request.GET:
            projekt_admin = self.admin_site.get_model_admin(Projekt)
            if not projekt_admin.has_view_permission(request):
                raise PermissionDenied
            projekt = get_object_or_404(Projekt, pk=request.GET['projekt'])
            kunde = projekt.kunde
        else:
            kunde = get_object_or_404(Kontakt, pk=request.GET.get('kunde'))

        # ForeignKeys (Ansprechpartner) als ID, weil JsonResponse keine
        # Modellobjekte serialisiert.
        werte = services.stammdatenwerte(kunde)
        return JsonResponse({name: getattr(wert, 'pk', wert)
                             for name, wert in werte.items()})
