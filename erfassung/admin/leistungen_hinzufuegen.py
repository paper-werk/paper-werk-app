"""Detailaktion „Erbrachte Leistungen hinzufügen“ an der Rechnung.

Gegenstück zur Listenaktion der Erfassungsliste
(``erfassung/admin/abrechnen.py``); beide rufen
``services.in_rechnung_uebernehmen`` auf. Die Detailaktion füllt eine
bestimmte Rechnung, die Listenaktion rechnet eine Auswahl ab.

Registriert über ``core.erweiterungen.belegaktion()`` in
``ZeitenConfig.ready()`` (erfassung/apps.py). Die Admins der Belegarten in
``faktura/admin/rechnung.py`` setzen ``detail_leistungen`` und
``has_leistungen_permission`` als Methoden; ``self`` ist zur Laufzeit eine
Instanz von ``RechnungAdmin`` oder einer Belegart.
"""

from django.contrib import messages
from django.shortcuts import render
from django.utils.html import format_html
from unfold.decorators import action as unfold_action
from unfold.enums import ActionVariant

from core.adminhilfen import mit_stand
from faktura.admin.gemeinsam import adresse_im_admin

from ..models import Erfassungszeile, Fremdleistung, Zustand
from ..services import (
    ErfassungError,
    in_rechnung_uebernehmen,
    offene_fremdleistungen,
    offene_leistungen,
)


@unfold_action(
    description='Erbrachte Leistungen hinzufügen',
    icon='playlist_add_check',
    permissions=['leistungen'],
    url_path='leistungen',
    variant=ActionVariant.PRIMARY,
)  # type: ignore
def detail_leistungen(self, request, object_id):
    """Zeigt die offene Leistung des Vorhabens der Rechnung zur Auswahl."""
    beleg = self._beleg_oder_none(object_id)
    if beleg is None:
        return self._zurueck_zum_beleg(request, object_id)

    if request.method == 'POST':
        return _leistungen_uebernehmen(self, request, beleg)

    return render(request, 'admin/erfassung/leistungen.html', {
        **self.admin_site.each_context(request),
        'title': 'Erbrachte Leistungen hinzufügen',
        'opts': self.opts,
        'beleg': beleg,
        'gruppen': offene_leistungen(beleg.projekt),
        # Fremdleistungen, nach Eingangsrechnung sortiert.
        'fremdgruppen': offene_fremdleistungen(beleg.projekt),
        'zurueck': adresse_im_admin(beleg),
        # Mit Cache-Buster.
        'skript': mit_stand('erfassung/js/leistungsauswahl.js'),
    })


def has_leistungen_permission(self, request, object_id=None):
    """Nur an einem Entwurf mit Projekt, weil Leistung immer auf ein
    Projekt erfasst wird."""
    if not self.has_change_permission(request):
        return False

    beleg = self._beleg_oder_none(object_id)
    if beleg is None:
        return False
    return beleg.ist_entwurf and bool(beleg.projekt_id)


def _leistungen_uebernehmen(self, request, beleg):
    """Übernimmt die ausgewählten Zeilen in diesen Beleg.

    Eingeschränkt auf das Vorhaben des Belegs und auf offene Zeilen, weil
    die IDs aus dem Request kommen; übernommen wird nur, was angeboten war.
    """
    kennungen = request.POST.getlist('zeile')
    fremde = request.POST.getlist('fremdleistung')
    if not kennungen and not fremde:
        self.message_user(request, 'Es war nichts ausgewählt.',
                          messages.WARNING)
        return self._zurueck_zum_beleg(request, beleg.pk)

    zeilen = (Erfassungszeile.objects
              .filter(pk__in=kennungen, projekt=beleg.projekt)
              .im_zustand(Zustand.OFFEN))
    # "Offen" ist bei der Fremdleistung eine Property ohne Feld, deshalb die
    # Bedingung ausgeschrieben.
    fremdleistungen = Fremdleistung.objects.filter(
        pk__in=fremde, projekt=beleg.projekt,
        weiterberechenbar=True, abgerechnet_in__isnull=True)

    try:
        _, ergebnis = in_rechnung_uebernehmen(
            zeilen=zeilen, fremdleistungen=fremdleistungen, beleg=beleg)
    except ErfassungError as fehler:
        self.message_user(request, str(fehler), messages.ERROR)
        return self._zurueck_zum_beleg(request, beleg.pk)

    self.message_user(request, format_html(
        '{} Zeilen als {} Positionen übernommen.{}',
        ergebnis.zeilenzahl, len(ergebnis.alle_positionen),
        (f' Davon {len(ergebnis.fremdpositionen)} aus Eingangsrechnungen.'
         if ergebnis.fremdpositionen else ''),
    ), messages.SUCCESS)

    if ergebnis.uebergangen:
        # Übergangene Zeilen werden gemeldet.
        self.message_user(request, format_html(
            '{} Zeilen wurden übergangen: {}',
            len(ergebnis.uebergangen),
            ', '.join(sorted({g for _, g in ergebnis.uebergangen})),
        ), messages.WARNING)
    return self._zurueck_zum_beleg(request, beleg.pk)
