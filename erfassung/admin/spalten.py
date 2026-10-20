"""Spalten der Erfassungsliste."""


from django.contrib import admin
from django.utils.html import format_html

from ..formate import dauer_zeigen, personenname
from ..services import (
    zeitsumme,
)
from .gemeinsam import (
    entwurfsname_von,
)


class SpaltenMixin:
    """Mixin von ``ErfassungszeileAdmin``: Spalten der Liste, vor allem
    Grundlage und Abrechnungszustand."""


    @admin.display(description='Worauf')
    def worauf(self, obj):
        """Grundlage der Zeile: Auftragsposition oder Katalogleistung.

        Eine gemeinsame Spalte, weil immer nur eines gesetzt ist. Nicht
        sortierbar, weil das über zwei Relationen eine Annotation bräuchte.
        """
        if obj.auftragsposition_id:
            auftrag = obj.auftragsposition.beleg
            return format_html(
                '{}<br><span class="text-xs text-base-500">{}</span>',
                obj.leistungsbezeichnung,
                auftrag.nummer or 'Auftrag ohne Nummer')
        return obj.leistungsbezeichnung

    @staticmethod
    def _oder_nichts(anzeige: str):
        """Wandelt leeren Text in ``None``, damit der Admin "-" anzeigt.

        Unfolds ``display_for_value`` prüft nur auf ``None``; ein leerer
        String ergäbe eine leere Zelle. Im Admin umgesetzt, weil der
        Leistungsnachweis dieselben Properties als ``str`` liest.
        """
        return anzeige or None

    @admin.display(description='Dauer', ordering='dauer_minuten')
    def dauer(self, zeile):
        """Berechnete Dauer. Die Formatierung steht am Modell, weil der
        Leistungsnachweis sie ebenfalls verwendet."""
        return self._oder_nichts(zeile.dauer_anzeige)

    @admin.display(description='Umfang', ordering='menge')
    def umfang(self, zeile):
        """Menge mit Einheit, etwa die Kilometer einer Anfahrt; bei
        Zeitzeilen leer."""
        return self._oder_nichts(zeile.umfang)

    @admin.display(description='Person', ordering='benutzer__last_name')
    def person(self, zeile):
        """Voller Name der Person ("Anna Weber")."""
        return personenname(zeile.benutzer)

    @admin.display(description='Zustand')
    def zustand(self, zeile):
        """Aus zwei Feldern abgeleitet und deshalb nicht sortierbar; dafür
        gibt es den Zustandsfilter."""
        return zeile.zustand_anzeige

    @staticmethod
    def entwurfsname(beleg) -> str:
        """Bezeichnung eines Entwurfs in der Auswahl, siehe
        ``entwurfsname_von``."""
        return entwurfsname_von(beleg)

    def get_list_display(self, request):
        """Personenspalte nur für Benutzer, die Zeilen anderer sehen."""
        if self._darf_fremde(request):
            return self.list_display
        return [s for s in self.list_display if s != 'person']

    # ── Summe über der Liste ─────────────────────────────────────────────────

    def changelist_view(self, request, extra_context=None):
        """Zeigt die Summe des gefilterten Bestands über alle Seiten.

        Ungerundet, weil die Rundung auf die Viertelstunde erst beim
        Übernehmen in die Rechnung erfolgt.
        """
        antwort = super().changelist_view(request, extra_context)
        liste = getattr(antwort, 'context_data', {}).get('cl')
        if liste is not None:
            antwort.context_data['zeitsumme'] = dauer_zeigen(zeitsumme(liste.queryset))
            antwort.context_data['aktionen_neues_fenster'] = (
                self.AKTIONEN_NEUES_FENSTER)
        return antwort
