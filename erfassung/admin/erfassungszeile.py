"""Admin der Erfassungszeilen aus den Mixins Spalten, Abrechnen, Sicht und
Formular."""


from django import forms
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.text import smart_split, unescape_string_literal
from import_export.admin import ImportExportModelAdmin
from unfold import admin as unfold_admin
from unfold.contrib.filters.admin import AutocompleteSelectFilter
from unfold.contrib.import_export.forms import (
    ImportForm,
    SelectableFieldsExportForm,
)

from core.adminhilfen import (
    GeschichteZumLesen,
    Kopfleiste,
    jquery_entdoppeln,
    mit_stand,
    skript_mit_stand,
)
from faktura.admin.menge import MengeOhneNullen
from faktura.models import Projekt

from ..models import (
    Erfassungszeile,
)
from ..ressourcen import ErfassungszeileResource
from .abrechnen import AbrechnenMixin
from .formular import FormularMixin
from .gemeinsam import (
    LeistungsartFilter,
    SortierFilter,
    ZeitraumFilter,
    ZustandFilter,
)
from .sicht import SichtMixin
from .spalten import SpaltenMixin


@admin.register(Erfassungszeile)
class ErfassungszeileAdmin(
    MengeOhneNullen,
    Kopfleiste, SpaltenMixin, AbrechnenMixin, SichtMixin, FormularMixin,
    GeschichteZumLesen, ImportExportModelAdmin, unfold_admin.ModelAdmin,
):
    #: Import von Stundenzetteln aus Excel und Export des Bestands
    #: (``erfassung/ressourcen.py``). ImportExportModelAdmin vor Unfold in der
    #: MRO, wie bei ``KatalogpositionAdmin``. Exportiert wird, was
    #: ``get_queryset`` liefert, ohne Recht für andere also nur eigene Zeilen.
    resource_classes = [ErfassungszeileResource]
    import_form_class = ImportForm
    export_form_class = SelectableFieldsExportForm

    #: Volle Breite, siehe ``EingangsrechnungAdmin``.
    list_fullwidth = True

    list_display = ['datum', 'von', 'bis', 'dauer', 'umfang',
                    'projekt', 'worauf', 'person', 'beschreibung', 'zustand']

    # projekt__kunde muss enthalten sein, weil lookup_allowed sonst URLs mit
    # Kundenfilter ablehnt (zwei Relationen tief).
    #
    # Kunde und Projekt als Autocomplete-Filter: Als Liste ergäben zehn
    # Jahre Daten 1.200 Projekte und 440 Kunden als Links, die Seite wog
    # 1,3 MB, und die Hälfte der Renderzeit entfiel auf die Filterleiste
    # (Lasttest). Leistung und Person bleiben Listen, weil es davon wenige
    # gibt.
    list_filter = [SortierFilter, ZeitraumFilter, ZustandFilter,
                   ('projekt__kunde', AutocompleteSelectFilter),
                   ('projekt', AutocompleteSelectFilter), LeistungsartFilter,
                   'leistung', 'benutzer']
    # Autocomplete-Filter senden nicht selbst ab.
    list_filter_submit = True
    date_hierarchy = 'datum'
    # Suche nach Projekt, Person und Beschreibung, siehe
    # ``get_search_results``. Die Leistung hat einen eigenen Filter.
    search_fields = ['projekt__nummer', 'projekt__bezeichnung',
                     'benutzer__first_name', 'benutzer__last_name',
                     'benutzer__username', 'beschreibung']
    # Mit dem Auftrag, weil die Spalte "Position / Leistung" seine Nummer zeigt; sonst
    # eine Abfrage je Zeile (Lasttest).
    list_select_related = ['projekt', 'leistung', 'auftragsposition__beleg',
                           'benutzer']
    change_list_template = 'admin/erfassung/erfassungszeile/change_list.html'

    def get_search_results(self, request, queryset, search_term):
        """Suche mit derselben Semantik wie ``search_fields``, aber schneller.

        Django prüft jedes Suchwort an jeder Zeile gegen alle Felder über die
        Joins zu Projekt und Person. Bei 75.000 Zeilen (zehn Jahre) lief das
        in jeder der vier Abfragen der Liste (Anzahl, Summe, Jahresleiste,
        Seite) und kostete über eine Sekunde je Suche (Lasttest). Hier werden
        Projekte und Personen zuerst in ihren kleinen Tabellen gesucht; an
        der Zeile bleibt die Bedingung "Projekt in Treffern, Person in
        Treffern oder Beschreibung enthält das Wort". Ein Index auf der
        Beschreibung brachte keinen Gewinn.

        Wie bei Django müssen mehrere Wörter alle vorkommen; in
        Anführungszeichen gilt eine Wortgruppe als ein Wort.
        """
        for wort in smart_split(search_term):
            if wort[0] in '"\'' and wort[0] == wort[-1]:
                wort = unescape_string_literal(wort)
            projekte = Projekt.objects.filter(
                Q(nummer__icontains=wort) | Q(bezeichnung__icontains=wort))
            personen = get_user_model().objects.filter(
                Q(first_name__icontains=wort) | Q(last_name__icontains=wort)
                | Q(username__icontains=wort))
            queryset = queryset.filter(
                Q(projekt__in=projekte) | Q(benutzer__in=personen)
                | Q(beschreibung__icontains=wort))
        return queryset, False

    @property
    def media(self):
        """Eigene Skripte am Ende; ``?stand=`` dient als Cache-Buster.

        Select2 für die Auswahlfelder mit Suche, eingebunden wie in
        ``BelegAdmin.media``: jQuery mit Djangos Pfaden erneut aufgeführt,
        damit Select2 und suchauswahl.js danach geladen werden.
        """
        extra = '' if settings.DEBUG else '.min'
        zusammen = super().media + forms.Media(
            css={'all': [
                f'admin/css/vendor/select2/select2{extra}.css',
                'admin/css/autocomplete.css',
                mit_stand('erfassung/css/erfassung_admin.css'),
            ]},
            js=[  # type: ignore[list-item]  (Media nimmt auch __html__-Objekte)
                f'admin/js/vendor/jquery/jquery{extra}.js',
                # Select2 registriert sich am zuvor geladenen jQuery, vor
                # jquery.init.js, das es zu django.jQuery macht.
                f'admin/js/vendor/select2/select2.full{extra}.js',
                'admin/js/vendor/select2/i18n/de.js',
                'admin/js/jquery.init.js',
                skript_mit_stand('erfassung/js/erfassungsart.js'),
                skript_mit_stand('erfassung/js/erfassungsauswahl.js'),
                skript_mit_stand('erfassung/js/suchauswahl.js'),
            ],
        )
        return jquery_entdoppeln(zusammen, extra)
