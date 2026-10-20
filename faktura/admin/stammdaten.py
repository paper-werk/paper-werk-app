"""Admin der Stammdaten: Firma, Kunden mit Anschriften, Kontaktwegen und
Ansprechpartnern, Projekte, Textbausteine, Leistungskatalog."""


from decimal import Decimal

from django.contrib import admin
from django.contrib.admin.options import IS_POPUP_VAR
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join
from import_export.admin import ImportExportModelAdmin
from unfold import admin as unfold_admin
from unfold.contrib.filters.admin import AutocompleteSelectFilter
from unfold.contrib.import_export.forms import (
    ImportForm,
    SelectableFieldsExportForm,
)
from unfold.decorators import action as unfold_action

from core import erweiterungen
from core.adminhilfen import Kopfleiste, weitere
from core.optimistic_locking import VersionAdminMixin

from .. import formate
from ..forms import (
    AdresseFormSet,
    KatalogpositionForm,
    KontaktwegFormSet,
    StandardZeileForm,
)
from ..models import (
    Adresse,
    Ansprechpartner,
    Firma,
    Katalogposition,
    Kontakt,
    Kontaktweg,
    Projekt,
    Steuersatz,
    Textbaustein,
    kundennummer_vorschlag,
    projektnummer_vorschlag,
)
from ..ressourcen import (
    KatalogpositionResource,
    KontaktResource,
    ProjektResource,
)
from .gemeinsam import (
    AktionNachDemSichern,
    KontaktAktivFilter,
    ProjektAbgeschlossenFilter,
    RolleFilter,
)


@admin.register(Firma)
class FirmaAdmin(Kopfleiste, unfold_admin.ModelAdmin):
    """Eigene Firma, genau ein Datensatz; "Hinzufügen" entfällt danach."""

    list_display = ['name', 'ort', 'steuerangabe', 'kleinunternehmer']
    fieldsets = [
        (None, {'fields': ['name', 'zusatz', 'logo']}),
        ('Anschrift', {'fields': ['strasse', ('plz', 'ort'), 'land']}),
        ('Kontakt', {'fields': ['telefon', 'email', 'web']}),
        ('Steuerlich', {
            'fields': ['steuernummer', 'ust_id', 'kleinunternehmer'],
            'description': 'Eine Rechnung braucht Steuernummer <b>oder</b> '
                           'USt-IdNr. (§ 14 Abs. 4 Nr. 2 UStG). Fehlt '
                           'beides, ist sie beim Kunden nicht '
                           'vorsteuerabzugsfähig.',
        }),
        ('Bankverbindung', {'fields': ['bank', 'iban', 'bic']}),
        ('Pflichtangaben im Geschäftsbrief', {
            'fields': ['geschaeftsfuehrung', 'registergericht', 'handelsregister'],
            'classes': ['collapse'],
            'description': 'Bei Kapitalgesellschaften vorgeschrieben '
                           '(§ 35a GmbHG).',
        }),
        ('Mahngebühren', {
            'fields': [('mahngebuehr_erinnerung', 'mahngebuehr_mahnung',
                        'mahngebuehr_letzte')],
            'description': 'Je Mahnstufe, in EUR, ohne Umsatzsteuer. '
                           'Ersetzt werden nur die tatsächlichen Kosten '
                           '(Porto, Papier), die erste Mahnung, die den '
                           'Verzug erst auslöst, gar nicht.',
        }),
        ('Texte', {'fields': ['standard_fusstext'], 'classes': ['collapse']}),
    ]

    @admin.display(description='Steuerliche Kennung')
    def steuerangabe(self, firma):
        return firma.steuerangabe or '- fehlt -'

    def has_add_permission(self, request):
        if Firma.objects.exists():
            return False
        return super().has_add_permission(request)


class AdresseInline(unfold_admin.TabularInline):
    """Anschriften eines Kunden. Mit Land, das als BT-55 in die E-Rechnung
    geht."""

    model = Adresse
    formset = AdresseFormSet
    form = StandardZeileForm
    extra = 0
    fields = ['verwendung', 'bezeichnung', 'zusatz', 'strasse', 'plz', 'ort',
              'land', 'ist_standard']
    verbose_name = 'Anschrift'
    verbose_name_plural = 'Anschriften'


class KundenkontaktInline(unfold_admin.TabularInline):
    """Kontaktwege des Betriebs (Telefon, E-Mail usw.), beschriftet als
    "Kontaktdaten". Die der Personen stehen an den Ansprechpartnern."""

    model = Kontaktweg
    formset = KontaktwegFormSet
    form = StandardZeileForm
    extra = 0
    fields = ['art', 'wert', 'bezeichnung', 'ist_standard']
    fk_name = 'kontakt'
    verbose_name = 'Kontaktdatensatz'
    verbose_name_plural = 'Kontaktdaten des Betriebs'


class PersonenkontaktInline(unfold_admin.TabularInline):
    """Kontaktwege einer Person: Durchwahl, Mobil, persönliche E-Mail."""

    model = Kontaktweg
    formset = KontaktwegFormSet
    form = StandardZeileForm
    extra = 0
    fields = ['art', 'wert', 'bezeichnung', 'ist_standard']
    fk_name = 'ansprechpartner'
    verbose_name = 'Kontaktdatensatz'
    verbose_name_plural = 'Kontaktdaten dieser Person'


class AnsprechpartnerInline(unfold_admin.TabularInline):
    """Ansprechpartner des Kunden als Übersicht.

    Angelegt und bearbeitet auf der Seite der Person, weil dort ihre
    Kontaktwege stehen und Django keine verschachtelten Inlines kennt. Name
    und "Ansprechpartner hinzufügen" verlinken dorthin, "Zum Kontakt" zurück.
    """

    model = Ansprechpartner
    extra = 0
    fields = ['person', 'funktion', 'kontaktdaten', 'ist_standard', 'aktiv']
    readonly_fields = fields
    template_after = 'admin/faktura/ansprechpartner_hinzufuegen.html'
    verbose_name = 'Ansprechpartner'
    verbose_name_plural = 'Ansprechpartner'

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='Name')
    def person(self, person):
        return format_html(
            '<a href="{}" class="text-primary-600 dark:text-primary-500 '
            'font-medium">{}</a>',
            reverse('admin:faktura_ansprechpartner_change', args=[person.pk]),
            person.name)

    @admin.display(description='Telefon, E-Mail, Mobil')
    def kontaktdaten(self, person):
        return format_html_join(
            '', '<div>{}: {}{}</div>',
            ((weg.get_art_display(), weg.wert,
              f' ({weg.bezeichnung})' if weg.bezeichnung else '')
             for weg in person.kontaktwege.all())) or '-'


@admin.register(Kontakt)
class KontaktAdmin(Kopfleiste, VersionAdminMixin, ImportExportModelAdmin,
                   unfold_admin.ModelAdmin):
    resource_classes = [KontaktResource]
    import_form_class = ImportForm
    export_form_class = SelectableFieldsExportForm

    inlines = [AdresseInline, KundenkontaktInline, AnsprechpartnerInline]

    actions_detail = ['detail_akte', weitere()]

    #: Die Liste verlinkt auf die Akte, weil Kunden häufiger nachgeschlagen
    #: als geändert werden. ``list_display_links = None``, weil Nummer und
    #: Name eigene Links setzen.
    list_display = ['nummer_akte', 'name_akte', 'rollen', 'ort',
                    'zahlungsziel_tage', 'anzahl_belege', 'aktiv']
    list_display_links = None
    list_filter = [RolleFilter, KontaktAktivFilter]
    # Ort und E-Mail stehen in Anschriften und Kontaktwegen.
    search_fields = ['nummer', 'name', 'adressen__ort', 'adressen__plz',
                     'kontaktwege__wert', 'ansprechpartner__nachname']
    ordering = ['nummer']
    fieldsets = [
        (None, {'fields': ['nummer', 'name', 'aktiv']}),
        ('Rollen', {
            'fields': [('ist_kunde', 'ist_lieferant', 'ist_partner',
                        'ist_interessent')],
            'description': 'Mehrere zugleich sind möglich. Belege und '
                           'Projekte bieten nur Kunden an, Eingangsrechnungen '
                           'nur Lieferanten.',
        }),
        ('Kaufmännisch', {
            'fields': ['ust_id', 'eigene_kundennummer', 'zahlungsziel_tage',
                       ('skonto_prozent', 'skonto_tage'),
                       'steuerfall'],
            'description': 'Skonto wirkt nirgends automatisch; es steht '
                           'hier, damit man es beim Zuordnen einer Zahlung '
                           'nachsehen kann.',
        }),
        ('E-Rechnung und Versand', {
            'fields': ['zustellweg', 'kaeuferreferenz'],
            'description': 'Käuferreferenz oder bei Behörden die Leitweg-ID.',
        }),
        ('Besonderheiten', {
            'fields': ['rechnungsempfaenger', 'notiz'],
            'classes': ['collapse'],
            'description': 'Der Rechnungsempfänger ist nur für den Fall da, '
                           'dass ein <b>anderer Kunde</b> die Rechnung '
                           'bekommt, etwa Hausverwaltung, Konzernmutter, '
                           'Versicherung. Ansprechpartner stehen unten.',
        }),
    ]
    autocomplete_fields = ['rechnungsempfaenger']

    @unfold_action(
        description='Akte',
        icon='badge',
        url_path='akte',
        permissions=['view'],
    )  # type: ignore
    def detail_akte(self, request, object_id):
        """Link vom Formular auf die Akte über den URL-Namen, ohne Import aus
        ``auswertung``."""
        return redirect('kundenakte', pk=object_id)

    # Eigene Methodennamen, weil Django bei gleichem Namen das Modellfeld
    # verwendet und der Link ohne Meldung fehlte.
    @admin.display(description='Kundennummer', ordering='nummer')
    def nummer_akte(self, kunde):
        """Nummer als Link auf die Akte über die Registry; ohne registrierte
        Akte nur Text."""
        url = erweiterungen.akte_url('kunde', kunde.pk)
        if url is None:
            return kunde.nummer
        return format_html(
            '<a href="{}" class="text-primary-600 dark:text-primary-500">'
            '{}</a>', url, kunde.nummer)

    @admin.display(description='Name', ordering='name')
    def name_akte(self, kunde):
        """Name mit demselben Link wie die Nummer."""
        url = erweiterungen.akte_url('kunde', kunde.pk)
        if url is None:
            return kunde.name
        return format_html(
            '<a href="{}" class="text-primary-600 dark:text-primary-500">'
            '{}</a>', url, kunde.name)

    @admin.display(description='Rolle')
    def rollen(self, kontakt):
        return ', '.join(kontakt.rollen)

    @admin.display(description='Ort')
    def ort(self, kunde):
        """Ort der Standardanschrift. Nicht sortierbar, weil der Join Kunden
        mit mehreren Anschriften mehrfach ergäbe."""
        return kunde.ort or '-'

    def get_changeform_initial_data(self, request):
        """Nächste freie Kundennummer als Vorbelegung, gelesen und nicht
        verbraucht (``kundennummer_vorschlag``)."""
        vorgabe = super().get_changeform_initial_data(request)
        vorgabe.setdefault('nummer', kundennummer_vorschlag())
        return vorgabe

    def get_queryset(self, request):
        # Belegzahl per annotate; Anschriften vorgeladen für die Spalte "Ort".
        return (super().get_queryset(request)
                # Beide Zuordnungen: Ein Beleg gehört zum Kunden oder zu einem
                # seiner Projekte.
                .annotate(belegzahl=Count('belege', distinct=True)
                          + Count('projekte__belege', distinct=True))
                .prefetch_related('adressen'))

    @admin.display(description='Belege', ordering='belegzahl')
    def anzahl_belege(self, kunde):
        return kunde.belegzahl


@admin.register(Ansprechpartner)
class AnsprechpartnerAdmin(Kopfleiste, VersionAdminMixin,
                           AktionNachDemSichern,
                           unfold_admin.ModelAdmin):
    """Seite je Ansprechpartner mit Kontaktwegen, auch Ausgangspunkt einer
    DSGVO-Auskunft. Meist vom Kunden aus geöffnet; "Zum Kontakt" und
    "Sichern" führen dorthin zurück."""

    list_display = ['name', 'kontakt', 'funktion', 'ist_standard', 'aktiv']
    list_filter = ['aktiv', ('kontakt', AutocompleteSelectFilter)]
    search_fields = ['nachname', 'vorname', 'funktion', 'kontakt__name',
                     'kontakt__nummer']
    autocomplete_fields = ['kontakt']
    inlines = [PersonenkontaktInline]
    fieldsets = [
        (None, {'fields': ['kontakt', ('anrede', 'titel'),
                           ('vorname', 'nachname')]}),
        ('Zuordnung', {'fields': ['funktion', 'adresse',
                                  ('ist_standard', 'aktiv')]}),
        ('Weiteres', {'fields': ['notiz', 'erfasst_am']}),
    ]
    readonly_fields = ['erfasst_am']
    actions_detail = ['detail_zum_kontakt', weitere()]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('kontakt')

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Nur Anschriften des Kunden der Person; beim Anlegen des Kunden aus
        ``?kontakt=``."""
        if db_field.name == 'adresse':
            person = request.resolver_match.kwargs.get('object_id')
            kunde = (Ansprechpartner.objects.filter(pk=person)
                     .values_list('kontakt_id', flat=True).first()
                     if person else request.GET.get('kontakt'))
            kwargs['queryset'] = (Adresse.objects.filter(kontakt_id=kunde)
                                  if kunde else Adresse.objects.none())
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @unfold_action(
        description='Zum Kontakt',
        icon='arrow_back',
        url_path='zum-kontakt',
        permissions=['view'],
    )  # type: ignore
    def detail_zum_kontakt(self, request, object_id):
        person = get_object_or_404(Ansprechpartner, pk=object_id)
        return redirect('admin:faktura_kontakt_change', person.kontakt_id)

    def _nur_gesichert(self, request) -> bool:
        """Nur "Sichern", ohne "Weiter bearbeiten" und "Sichern und neu
        hinzufügen"."""
        return not any(knopf in request.POST for knopf in
                       ('_continue', '_addanother', '_saveasnew', '_danach'))

    def response_add(self, request, obj, post_url_continue=None):
        antwort = super().response_add(request, obj, post_url_continue)
        if self._nur_gesichert(request) and not self.is_popup(request):
            return redirect('admin:faktura_kontakt_change', obj.kontakt_id)
        return antwort

    def response_change(self, request, obj):
        antwort = super().response_change(request, obj)
        if self._nur_gesichert(request) and not self.is_popup(request):
            return redirect('admin:faktura_kontakt_change', obj.kontakt_id)
        return antwort

    def is_popup(self, request) -> bool:
        """Im Popup schließt Django das Fenster; kein Redirect."""
        return IS_POPUP_VAR in request.POST or IS_POPUP_VAR in request.GET


@admin.register(Projekt)
class ProjektAdmin(Kopfleiste, VersionAdminMixin, AktionNachDemSichern,
                   ImportExportModelAdmin,
                   unfold_admin.ModelAdmin):
    """Projekte mit Belegzahl, Link auf die Akte und Filter auf den
    Abschluss."""

    resource_classes = [ProjektResource]
    import_form_class = ImportForm
    export_form_class = SelectableFieldsExportForm

    actions_detail = ['detail_akte', weitere()]
    list_display = ['akte', 'nummer', 'bezeichnung', 'kunde', 'anzahl_belege',
                    'abgeschlossen']
    list_display_links = ['nummer', 'bezeichnung']
    # Kunde als Autocomplete, weil eine Liste alle Kunden enthielte.
    list_filter = [ProjektAbgeschlossenFilter, ('kunde', AutocompleteSelectFilter)]
    search_fields = ['nummer', 'bezeichnung', 'beschreibung', 'kunde__name']
    autocomplete_fields = ['kunde']
    ordering = ['-nummer']
    fieldsets = [
        (None, {'fields': ['nummer', 'bezeichnung', 'kunde']}),
        ('Weiteres', {
            'fields': ['beschreibung', 'abgeschlossen', 'notiz'],
            'description': 'Beschreibung und Notiz für interne Zwecke.',
        }),
    ]

    def get_changeform_initial_data(self, request):
        """Nächste freie Projektnummer des Jahres als Vorbelegung, gelesen und
        nicht verbraucht, überschreibbar."""
        vorgabe = super().get_changeform_initial_data(request)
        vorgabe.setdefault('nummer', projektnummer_vorschlag())
        return vorgabe

    @unfold_action(
        description='Projektakte',
        icon='folder_open',
        url_path='akte',
    )
    def detail_akte(self, request, object_id):
        """Link vom Formular auf die Akte über den URL-Namen, ohne Import aus
        ``auswertung``."""
        return redirect('projektakte', pk=object_id)

    @admin.display(description='Akte')
    def akte(self, projekt):
        """Link auf die Akte aus der Liste über die Registry; ohne registrierte
        Akte bleibt die Spalte leer."""
        url = erweiterungen.akte_url('projekt', projekt.pk)
        if url is None:
            return ''
        return format_html(
            '<a href="{}" class="text-primary-600 dark:text-primary-500">'
            'ansehen</a>', url)

    @admin.display(description='Belege', ordering='belege__count')
    def anzahl_belege(self, projekt):
        return projekt.belege__count

    def get_queryset(self, request):
        # Die Annotation ist auch für die Sortierung nötig
        # (ordering='belege__count').
        return (
            super().get_queryset(request)
            .select_related('kunde')
            .annotate(Count('belege'))
        )


@admin.register(Textbaustein)
class TextbausteinAdmin(Kopfleiste, unfold_admin.ModelAdmin):
    """Textbausteine, eingefügt über das Auswahlmenü am Textfeld
    (``forms.TextfeldMitVorlagen``)."""

    list_display = ['name', 'verwendung', 'textanfang']
    list_filter = ['verwendung']
    search_fields = ['name', 'text']

    @admin.display(description='Text')
    def textanfang(self, baustein):
        if len(baustein.text) <= 80:
            return baustein.text
        return baustein.text[:80] + '…'


class SteuersatzFilter(admin.SimpleListFilter):
    """Filter nach den Sätzen, die im Katalog vorkommen."""

    title = 'Steuersatz'
    parameter_name = 'steuersatz'

    def lookups(self, request, model_admin):
        # Numerisch sortiert, weil als Text "7.00" nach "19.00" käme.
        werte = set(Katalogposition.objects.values_list('steuersatz', flat=True))
        return [(wert, formate.prozent(wert))
                for wert in sorted(werte, key=Decimal, reverse=True)]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(steuersatz=self.value())
        return queryset


@admin.register(Steuersatz)
class SteuersatzAdmin(Kopfleiste, unfold_admin.ModelAdmin):
    """Wählbare Umsatzsteuersätze (``models/steuersatz.py``).

    Ohne Löschen und mit unveränderlichem Satz nach dem Anlegen, weil
    Positionen den Satz als Wert speichern. Abgelöst wird über "Wählbar".
    """

    list_display = ['__str__', 'aktiv', 'vorgabe', 'reihenfolge']
    list_editable = ['reihenfolge']
    fields = ['satz', 'bezeichnung', 'aktiv', 'vorgabe', 'reihenfolge']

    def get_readonly_fields(self, request, obj=None):
        return ['satz'] if obj else []

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Katalogposition)
class KatalogpositionAdmin(Kopfleiste, ImportExportModelAdmin,
                           unfold_admin.ModelAdmin):
    """Leistungskatalog mit Import und Export, weil Kataloge als Tabelle
    angeliefert werden. Belege haben keinen Import, weil sie in der
    Anwendung entstehen und festgeschrieben werden.

    ImportExportModelAdmin vor Unfolds ModelAdmin in der MRO
    (``changelist_view`` und URLs).
    """

    form = KatalogpositionForm
    resource_classes = [KatalogpositionResource]
    import_form_class = ImportForm
    # Wählbare Spalten, damit eine Preisliste ohne interne Felder exportiert
    # werden kann.
    export_form_class = SelectableFieldsExportForm

    list_display = ['nummer', 'bezeichnung', 'hat_langtext', 'einheit',
                    'preis', 'satz']
    list_display_links = ['nummer', 'bezeichnung']
    list_filter = [SteuersatzFilter, 'art', 'kontierbar']
    search_fields = ['nummer', 'bezeichnung', 'langtext']
    ordering = ['nummer', 'bezeichnung']

    @admin.display(description='Langtext', boolean=True)
    def hat_langtext(self, position) -> bool:
        """Ob ein Langtext vorhanden ist; der Text selbst passt in keine
        Spalte."""
        return bool(position.langtext)

    @admin.display(description='Einzelpreis netto', ordering='einzelpreis')
    def preis(self, position):
        return formate.geld_mit_waehrung(position.einzelpreis)

    @admin.display(description='Steuersatz', ordering='steuersatz')
    def satz(self, position):
        return formate.prozent(position.steuersatz)

    def get_urls(self):
        eigene = [
            path(
                'daten/',
                self.admin_site.admin_view(self.daten),
                name='faktura_katalogposition_daten',
            ),
            path(
                'suche/',
                self.admin_site.admin_view(self.suche),
                name='faktura_katalogposition_suche',
            ),
        ]
        return eigene + super().get_urls()

    #: Treffer je Seite; die Auswahl lädt beim Scrollen nach.
    SUCHTREFFER_JE_SEITE = 30

    def suche(self, request):
        """Katalogpositionen zum Suchbegriff für die Auswahl über der
        Positionszeile (``KatalogsucheWidget``, katalog_suche.js).

        Dieselbe Suche wie in der Katalogliste (``search_fields``) im Format
        von Select2. Djangos Autocomplete-Endpunkt setzt einen ForeignKey am
        Beleg voraus, den es nicht gibt, weil Katalogwerte kopiert werden.

        Ohne Preis, weil der Lieferschein dieselbe Auswahl nutzt.
        """
        if not self.has_view_permission(request):
            raise PermissionDenied
        treffer, _ = self.get_search_results(
            request, self.get_queryset(request), request.GET.get('term', ''))
        try:
            seite = max(int(request.GET.get('page') or 1), 1)
        except ValueError:
            seite = 1
        je_seite = self.SUCHTREFFER_JE_SEITE
        # Ein Treffer mehr als angezeigt, damit ohne COUNT feststeht, ob es
        # weitere gibt.
        ausschnitt = list(treffer.order_by(*self.ordering)[
            (seite - 1) * je_seite:seite * je_seite + 1])
        return JsonResponse({
            'results': [{'id': p.pk, 'text': str(p)}
                        for p in ausschnitt[:je_seite]],
            'pagination': {'more': len(ausschnitt) > je_seite},
        })

    def daten(self, request):
        """Werte einer Katalogposition als JSON zum Vorbefüllen einer
        Positionszeile; verbindlich ist ``BelegpositionForm.clean()``.

        Preis als String ('10.00'), damit er kein float wird. Mit Prüfung
        des Leserechts, weil die Antwort Preise enthält.
        """
        if not self.has_view_permission(request):
            raise PermissionDenied
        position = get_object_or_404(
            Katalogposition, pk=request.GET.get('katalog')
        )
        return JsonResponse({
            'bezeichnung': position.bezeichnung,
            'langtext': position.langtext,
            'einheit': position.einheit,
            'einzelpreis': str(position.einzelpreis),
            'steuersatz': position.steuersatz,
        })
