"""Darstellung von ``MengenFeld`` im Admin."""

from django.contrib import admin
from django.contrib.admin.options import InlineModelAdmin

from core.felder import MengenFeld

from .. import formate
from ..forms import MengeWidget


def _ersetzt(felder):
    return tuple(
        _ersetzt(feld) if isinstance(feld, (list, tuple))
        else 'menge_anzeige' if feld == 'menge' else feld
        for feld in felder)


class MengeOhneNullen:
    """Menge ohne nachlaufende Nullen im Eingabefeld und schreibgeschützt.

    Für die schreibgeschützte Ansicht wird ``menge`` durch ``menge_anzeige``
    ersetzt, weil ``display_for_field`` immer alle Nachkommastellen des
    Felds ausgibt.
    """

    formfield_overrides = {MengenFeld: {'widget': MengeWidget}}

    def _nur_lesend(self, request, obj) -> bool:
        if isinstance(self, InlineModelAdmin):
            return not (self.has_change_permission(request, obj)
                        or self.has_add_permission(request, obj))
        return obj is not None and not self.has_change_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        return [*super().get_readonly_fields(request, obj), 'menge_anzeige']

    def get_fieldsets(self, request, obj=None):
        gruppen = super().get_fieldsets(request, obj)
        if not self._nur_lesend(request, obj):
            return gruppen
        return [(name, {**optionen, 'fields': _ersetzt(optionen['fields'])})
                for name, optionen in gruppen]

    @admin.display(description='Menge', ordering='menge')
    def menge_anzeige(self, obj):
        return formate.menge(obj.menge)
