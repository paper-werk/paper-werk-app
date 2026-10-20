"""Leistungsnachweis und Übernahme in Rechnungen aus der Erfassungsliste."""


from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.admin.options import (
    ActionLocation,
)
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.html import format_html

from core.adminhilfen import AUSWAHL_KLASSEN

from .. import nachweis as nachweis_pdf
from ..services import (
    ErfassungError,
    abrechnungsvorschau,
    in_rechnung_uebernehmen,
    zeitaufstellung,
)
from .gemeinsam import (
    NEUE_ZIELE,
    _rechnungsadresse,
    entwuerfe_fuer,
    ziel_aus_auswahl,
)


class AbrechnenMixin:
    """Mixin von ``ErfassungszeileAdmin``: Leistungsnachweis und Übernahme in
    einen Rechnungsentwurf.

    Beide arbeiten auf mehreren Zeilen und sind deshalb Listenaktionen.
    """


    # ── Aktionen ─────────────────────────────────────────────────────────────
    #
    # Listenaktionen, weil die Liste über Filter und Häkchen die Zeilen
    # auswählt, auf denen die Aktion arbeitet.

    @admin.action(description='Leistungsnachweis als PDF (mit Uhrzeit)')
    def leistungsnachweis(self, request, queryset):
        """Erzeugt den Leistungsnachweis über die ausgewählten Zeilen.

        Die Reihenfolge kommt aus der Liste (Django übergibt das Queryset mit
        deren ``order_by``) und wird nicht neu sortiert. Der Nachweis schreibt
        nichts fest, siehe ``nachweis.py``.
        """
        return self._nachweis(request, queryset, mit_uhrzeit=True)

    @admin.action(description='Leistungsnachweis als PDF (kompakt)')
    def leistungsnachweis_kompakt(self, request, queryset):
        """Derselbe Nachweis ohne Von und Bis, nur mit Stunden je Tag."""
        return self._nachweis(request, queryset, mit_uhrzeit=False)

    def _nachweis(self, request, queryset, *, mit_uhrzeit):
        aufstellung = zeitaufstellung(queryset)
        if not aufstellung.zeilen:
            self.message_user(request, 'Keine Zeilen ausgewählt.',
                              level=messages.WARNING)
            return None

        antwort = HttpResponse(
            nachweis_pdf.nachweis_als_pdf(aufstellung, erzeugt_von=request.user,
                                          mit_uhrzeit=mit_uhrzeit),
            content_type='application/pdf',
        )
        # inline: Der Browser zeigt das PDF an, gespeichert wird aus dem
        # Viewer.
        antwort['Content-Disposition'] = (
            f'inline; filename="{nachweis_pdf.dateiname(aufstellung)}"')
        return antwort

    @admin.action(description='In Rechnung übernehmen')
    def in_rechnung(self, request, queryset):
        """Zeigt eine Vorschau und übernimmt erst nach Bestätigung.

        Gruppierung, Aufrundung und übergangene Zeilen sind an der Auswahl
        nicht erkennbar. Die Vorschau übergibt die Auswahl weiter
        (``_selected_action``); der zweite POST enthält ``bestaetigt``.
        """
        try:
            vorschau = abrechnungsvorschau(queryset)
        except ErfassungError as fehler:
            self.message_user(request, str(fehler), level=messages.ERROR)
            return None

        if not vorschau.positionen:
            self.message_user(
                request,
                'In der Auswahl steht nichts, was abgerechnet werden könnte.',
                level=messages.WARNING)
            return None

        if request.POST.get('bestaetigt'):
            return self._uebernehmen(request, queryset, vorschau)

        return render(request, 'admin/erfassung/uebernehmen.html', {
            **self.admin_site.each_context(request),
            'title': 'In Rechnung übernehmen',
            'opts': self.opts,
            'vorschau': vorschau,
            'neue_ziele': NEUE_ZIELE,
            'entwuerfe': [(e, self.entwurfsname(e))
                          for e in self._entwuerfe(vorschau.projekt)],
            'auswahl': request.POST.getlist(ACTION_CHECKBOX_NAME),
            'aktion': 'in_rechnung',
            # Das Template rendert die Zielauswahl ohne Widget; die
            # CSS-Klassen kommen aus Unfold, damit sie bei Updates aktuell
            # bleiben.
            'select_klassen': AUSWAHL_KLASSEN,
        })

    def _uebernehmen(self, request, queryset, vorschau):
        # Nur angebotene Entwürfe. Der Service lehnt ein ungeeignetes Ziel
        # ebenfalls ab, hier ist die Meldung genauer.
        try:
            ziel, art = ziel_aus_auswahl(request.POST.get('ziel', ''),
                                         vorschau.projekt)
        except LookupError:
            self.message_user(request, 'Die gewählte Rechnung gibt es '
                                       'nicht mehr.', messages.ERROR)
            return None

        try:
            beleg, ergebnis = in_rechnung_uebernehmen(
                zeilen=queryset, beleg=ziel, rechnungsart=art)
        except ErfassungError as fehler:
            self.message_user(request, str(fehler), level=messages.ERROR)
            return None

        self.message_user(request, format_html(
            '{} Zeilen als {} Positionen übernommen: <a href="{}">{}</a>',
            ergebnis.zeilenzahl, len(ergebnis.positionen),
            _rechnungsadresse(beleg), beleg,
        ), level=messages.SUCCESS)

        if ergebnis.uebergangen:
            # Meldung über übergangene Zeilen, damit fehlende Stunden nicht
            # erst bei der Monatsabrechnung auffallen.
            self.message_user(request, format_html(
                '{} Zeilen wurden übergangen: {}', len(ergebnis.uebergangen),
                ', '.join(sorted({grund for _, grund in ergebnis.uebergangen})),
            ), level=messages.WARNING)
        return None

    def _entwuerfe(self, projekt):
        """Rechnungsentwürfe als mögliches Ziel, siehe ``entwuerfe_fuer``."""
        return entwuerfe_fuer(projekt)

    #: Das Übernehmen ändert Belege in faktura und verlangt deshalb ein Recht
    #: über das der Erfassung hinaus.
    RECHT_ABRECHNEN = 'faktura.add_beleg'

    def get_actions(self, request,
                    action_location=ActionLocation.CHANGE_LIST):
        """Entfernt die Übernahme aus den Aktionen, wenn das Recht fehlt.

        Damit ist sie auch per POST gesperrt, weil Django nur Aktionen aus
        ``get_actions`` ausführt. ``action_location`` (Django 6.1) ist ab
        Django 7 Pflicht.
        """
        aktionen = super().get_actions(request, action_location)
        if not request.user.has_perm(self.RECHT_ABRECHNEN):
            aktionen.pop('in_rechnung', None)
        return aktionen

    actions = ['leistungsnachweis', 'leistungsnachweis_kompakt', 'in_rechnung']

    #: Aktionen, deren Ergebnis in einem neuen Tab öffnet, damit die Liste mit
    #: der Auswahl erhalten bleibt.
    AKTIONEN_NEUES_FENSTER = ['leistungsnachweis', 'leistungsnachweis_kompakt']
