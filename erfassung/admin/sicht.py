"""Sichtbarkeit und Sortierung der Erfassungszeilen."""


from django.contrib.admin.options import (
    IncorrectLookupParameters,
)

from ..sortierung import ordnung
from .gemeinsam import (
    RECHT_FREMDE,
    SortierFilter,
)


class SichtMixin:
    """Mixin von ``ErfassungszeileAdmin``: Sichtbarkeit und Sortierung.

    Eigene Stunden sieht jeder, fremde nur mit eigenem Recht. Geprüft wird
    im Queryset.
    """


    # ── Sichtbarkeit ─────────────────────────────────────────────────────────

    def _darf_fremde(self, request) -> bool:
        return request.user.has_perm(RECHT_FREMDE)

    def get_queryset(self, request):
        """Ohne ``RECHT_FREMDE`` nur die eigenen Zeilen.

        Schützt auch die Änderungsansicht bei erratener URL, weil Django für
        Datensätze außerhalb des Querysets umleitet.
        """
        bestand = super().get_queryset(request)
        if self._darf_fremde(request):
            return bestand
        return bestand.filter(benutzer=request.user)

    #: Lookups, die in URLs erlaubt sind, obwohl kein Filter sie führt:
    #: ``leistung__art`` aus alten Lesezeichen, die übrigen aus den Akten
    #: (``auswertung/zuordnung.py``): Auftrag, Auftragsposition, "ohne
    #: Auftragsposition", Rechnung, Projekt. Die Sichtbarkeit regelt
    #: weiterhin ``get_queryset``.
    VERWEISE_VON_AUSSEN = ('leistung__art', 'auftragsposition__beleg__id',
                           'auftragsposition__id', 'auftragsposition__isnull',
                           'abgerechnet_in__beleg__id', 'projekt__id')

    def lookup_allowed(self, lookup, value, request=None):
        """Erlaubt die Lookups aus ``VERWEISE_VON_AUSSEN``.

        Django erlaubt nur Lookups aus ``list_filter`` und wirft sonst
        DisallowedModelAdminLookup. Ein Lesezeichen mit ``leistung__art``
        filtert nur Katalogzeilen; vollständig filtert ``leistungsart``
        (``LeistungsartFilter``).
        """
        if lookup.startswith(self.VERWEISE_VON_AUSSEN):
            return True
        return super().lookup_allowed(lookup, value, request)

    def get_ordering(self, request):
        """Sortierung aus dem Parameter von ``SortierFilter``.

        Djangos Spaltenköpfe sortieren mehrstufig nur in umgekehrter
        Klickreihenfolge (der zuletzt angeklickte wird erster Schlüssel); hier
        sind die Sortierungen benannt (``sortierung.py``). Ein ``?o=`` aus
        einem Spaltenkopf hat Vorrang.
        """
        gewaehlt = request.GET.get(SortierFilter.parameter_name)
        if not gewaehlt:
            return super().get_ordering(request)
        try:
            return ordnung(gewaehlt)
        except ValueError as fehler:
            # Wie bei den Filtern ergäbe ein ValueError eine 500.
            raise IncorrectLookupParameters(fehler) from fehler

    def get_list_filter(self, request):
        """Personenfilter nur für Benutzer, die Zeilen anderer sehen.

        Abgeleitet aus ``list_filter``, damit keine zweite Liste gepflegt
        werden muss.
        """
        if self._darf_fremde(request):
            return self.list_filter
        return [f for f in self.list_filter if f != 'benutzer']
