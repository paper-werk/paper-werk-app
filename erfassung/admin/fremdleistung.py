"""Admin für Eingangsrechnungen und Fremdleistungen. Lieferanten sind
Kontakte aus ``faktura``.

Eigene Stunden kommen aus der Erfassung, fremde Leistung aus
Eingangsrechnungen; beide werden in dieselbe Projektrechnung übernommen.
"""


from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from unfold import admin as unfold_admin
from unfold.contrib.filters.admin import (
    AutocompleteSelectFilter,
    RangeDateFilter,
    RelatedDropdownFilter,
)
from unfold.decorators import action as unfold_action
from unfold.enums import ActionVariant
from unfold.widgets import UnfoldAdminFileFieldWidget

from core import erweiterungen
from core.adminhilfen import (
    AUSWAHL_KLASSEN,
    GeschichteZumLesen,
    Kopfleiste,
)
from core.exceptions import FachlicherFehler
from core.optimistic_locking import VersionAdminMixin
from faktura.formate import geld
from faktura.models import Belegposition, BelegStatus, BelegTyp, Projekt

from ..formate import personenname
from ..models import (
    Eingangsrechnung,
    Fremdleistung,
    Kostensatz,
    Zustand,
)
from ..services import (
    ErfassungError,
    abrechnungsvorschau,
    eingangsrechnung_aus_xml,
    in_rechnung_uebernehmen,
)
from .gemeinsam import (
    NEUE_ZIELE,
    AuftragspositionsAuswahl,
    AuftragspositionsWidget,
    _rechnungsadresse,
    entwuerfe_fuer,
    entwurfsname_von,
    ziel_aus_auswahl,
)


class AuftragspositionFeld:
    """Auswahl der Auftragsposition an einer Fremdleistung, im Inline der
    Eingangsrechnung und in der Einzelmaske.

    Zur Wahl stehen Positionen festgeschriebener Aufträge laufender Projekte
    und die bereits gespeicherten Werte. ``fremdleistungsauswahl.js``
    schränkt im Browser auf das Projekt der Zeile ein (``data-projekt``),
    wie in der Erfassung. Die Regel selbst steht in ``Fremdleistung.clean()``.
    """

    #: Lookup von ``object_id`` zu den Zeilen, deren gespeicherte Position
    #: wählbar bleiben muss.
    eigene_zeilen = 'fremdkontierungen__pk'

    class Media:
        js = ['erfassung/js/fremdleistungsauswahl.js']

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'auftragsposition':
            erlaubt = Q(beleg__typ=BelegTyp.AUFTRAG,
                        beleg__status=BelegStatus.FESTGESCHRIEBEN,
                        beleg__projekt__abgeschlossen=False,
                        zeilenart='leistung')
            kennung = (request.resolver_match.kwargs.get('object_id')
                       if request.resolver_match else None)
            if kennung:
                erlaubt |= Q(**{self.eigene_zeilen: kennung})
            kwargs['queryset'] = (
                Belegposition.objects.filter(erlaubt).distinct()
                .select_related('beleg__projekt')
                .order_by('beleg__projekt__nummer', 'beleg__nummer',
                          'sortierung'))
            kwargs['form_class'] = AuftragspositionsAuswahl
            kwargs['widget'] = AuftragspositionsWidget()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        """Kein "anlegen" oder "ändern" neben der Auftragsposition, weil
        Auftragspositionen im Auftrag gepflegt werden."""
        feld = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == 'auftragsposition' and feld is not None:
            for schalter in ('can_add_related', 'can_change_related',
                             'can_delete_related', 'can_view_related'):
                setattr(feld.widget, schalter, False)
        return feld


class FremdleistungInline(AuftragspositionFeld, unfold_admin.TabularInline):
    """Positionen einer Eingangsrechnung, je Zeile ein Vorhaben.

    Im selben Formular wie der Rechnungsbetrag, damit der Beleg in einem
    Durchgang verteilt wird und der offene Rest sichtbar ist.
    """

    model = Fremdleistung
    extra = 1
    # Nur der Einkaufspreis; der Verkaufspreis entsteht beim Übernehmen in
    # die Rechnung.
    fields = ['projekt', 'auftragsposition', 'bezeichnung', 'leistungsdatum',
              'einheit', 'menge', 'einkaufspreis', 'einkauf_netto',
              'weiterberechenbar', 'abgerechnet']
    readonly_fields = ['abgerechnet']
    autocomplete_fields = ['projekt']

    #: ``object_id`` in der URL ist die Eingangsrechnung.
    eigene_zeilen = 'fremdkontierungen__rechnung_id'

    @admin.display(description='Abgerechnet')
    def abgerechnet(self, obj):
        """Rechnung, auf der die Zeile abgerechnet ist; deshalb ist sie nicht
        mehr änderbar."""
        if obj is None or obj.pk is None:
            return ''
        beleg = obj.abgerechneter_beleg
        if beleg is None:
            return obj.zustand_anzeige
        return format_html('<a href="{}">{}</a>',
                           _rechnungsadresse(beleg), beleg)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'projekt', 'auftragsposition__beleg', 'abgerechnet_in__beleg')


#: Höchstgröße einer Rechnungsdatei. Ein PDF mit Logo und Schriften hat
#: einige hundert Kilobyte; die Grenze fängt versehentlich hochgeladene
#: Archive ab.
MAX_DATEIGROESSE = 10 * 1024 * 1024


class ERechnungForm(forms.Form):
    """Formular zum Einlesen einer E-Rechnung: Datei und Vorhaben.

    Das Vorhaben steht nicht in der Rechnung des Lieferanten, alles andere
    wird gelesen. Es ist optional; eine Sammelrechnung über mehrere Vorhaben
    wird danach von Hand verteilt, bis dahin bleibt der Rest offen.
    """

    #: Unfolds Dateifeld (``FileFieldMixin``), das das native
    #: ``<input type="file">`` im Stil der übrigen Masken darstellt.
    datei = forms.FileField(
        label='Datei der E-Rechnung',
        widget=UnfoldAdminFileFieldWidget,
        help_text='Das PDF (ZUGFeRD/Factur-X) oder das nackte XML, so wie '
                  'es der Lieferant geschickt hat. Aus einem PDF wird das '
                  'eingebettete XML geholt.',
    )
    projekt = forms.ModelChoiceField(
        label='Projekt',
        queryset=Projekt.objects.none(),
        required=False,
        empty_label='Noch nicht zuordnen',
        help_text='Alle Positionen der Rechnung werden darauf kontiert. '
                  'Leer lassen: Dann gilt das Projekt, das der Lieferant '
                  'als Projektreferenz angegeben hat, sofern es eindeutig '
                  'passt; sonst steht die Rechnung mit offenem Rest da '
                  'und wird danach verteilt.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Im Konstruktor, weil ein Queryset auf Klassenebene beim Import
        # ausgewertet würde. Abgeschlossene Vorhaben sind ausgeschlossen.
        self.fields['projekt'].queryset = Projekt.objects.filter(
            abgeschlossen=False).order_by('nummer')

        # ``forms.Select`` mit Unfolds CSS-Klassen, aus Unfold importiert,
        # damit sie bei Updates aktuell bleiben.
        self.fields['datei'].widget.attrs['accept'] = (
            '.pdf,.xml,application/pdf,text/xml')
        self.fields['projekt'].widget.attrs['class'] = AUSWAHL_KLASSEN

    def clean_datei(self):
        """Lehnt zu große Dateien vor dem Parsen ab, damit pypdf und lxml
        keine 200 MB verarbeiten. Den Inhalt prüft ``erechnung.lesen``; die
        Dateiendung wird nicht ausgewertet.
        """
        datei = self.cleaned_data['datei']
        if datei.size > MAX_DATEIGROESSE:
            raise forms.ValidationError(
                f'Die Datei ist {datei.size / 1024 / 1024:.1f} MB groß. '
                f'Eine E-Rechnung hat wenige hundert Kilobyte; das hier ist '
                f'vermutlich etwas anderes.')
        return datei


@admin.register(Eingangsrechnung)
class EingangsrechnungAdmin(Kopfleiste, VersionAdminMixin,
                            unfold_admin.ModelAdmin):
    """Eingangsrechnungen erfassen und auf Vorhaben verteilen.

    Wichtigste Spalte der Liste ist der Rest: Betrag, der noch keinem
    Vorhaben zugeordnet ist.
    """

    inlines = [FremdleistungInline]
    #: Der Button steht über der Liste, weil er im Formular "Hinzufügen" über
    #: einem leeren Formular stünde, das der Upload ersetzt.
    actions_list = ['liste_erechnung']
    #: Volle Breite ohne die 1760-px-Grenze (core/css/unfold-overrides.css),
    #: weil die Tabelle breit ist. Unfolds Schalter wirkt auf Kopfzeile,
    #: Inhalt und Pagination zugleich.
    list_fullwidth = True

    list_display = ['datum', 'lieferant', 'nummer', 'betrag_anzeige',
                    'zugeordnet_anzeige', 'rest_anzeige', 'projekte_anzeige',
                    'archiv_anzeige']
    list_display_links = ['datum', 'nummer']
    # Datum als Bereichsfilter, weil Rechnungen in einem Zeitraum gesucht
    # werden.
    list_filter = [
        ('lieferant', RelatedDropdownFilter),
        ('datum', RangeDateFilter),
    ]
    list_filter_submit = True
    search_fields = ['nummer', 'lieferant__name', 'positionen__bezeichnung',
                     'positionen__projekt__nummer']
    date_hierarchy = 'datum'
    autocomplete_fields = ['lieferant']
    fieldsets = [
        (None, {'fields': ['lieferant', 'nummer', 'datum', 'betrag_netto']}),
        ('Weiteres', {'fields': ['notiz', 'archivverweis'],
                      'classes': ['collapse']}),
    ]
    #: Die Archivkennung kommt aus der Übernahme und ist schreibgeschützt;
    #: von Hand geändert verwiese die Rechnung auf ein fremdes Dokument.
    readonly_fields = ['archivverweis']

    @admin.display(description='Archiv')
    def archivverweis(self, rechnung):
        """Link auf das Dokument in Paperless; ein PDF wird hier nicht
        gespeichert (``Eingangsrechnung.paperless_id``).
        """
        if rechnung.pk is None or not rechnung.paperless_id:
            # format_html verlangt Argumente.
            return mark_safe(
                '<span class="text-font-subtle-light '
                'dark:text-font-subtle-dark">Von Hand erfasst, kein '
                'Dokument im Archiv.</span>')
        return format_html(
            '<a href="{}" target="_blank" class="text-primary-600 '
            'dark:text-primary-500">Dokument {} ansehen</a>',
            rechnung.archiv_adresse, rechnung.paperless_id)

    @admin.display(description='Archiv', ordering='paperless_id')
    def archiv_anzeige(self, rechnung):
        """Symbol in der Liste, nur bei Rechnungen aus dem Archiv."""
        if not rechnung.paperless_id:
            return ''
        return format_html(
            '<a href="{}" target="_blank" title="Dokument {} im Archiv" '
            'class="text-primary-600 dark:text-primary-500">'
            '<span class="material-symbols-outlined text-base!">'
            'description</span></a>',
            rechnung.archiv_adresse, rechnung.paperless_id)

    def get_queryset(self, request):
        return (super().get_queryset(request)
                .select_related('lieferant')
                .prefetch_related('positionen__projekt'))

    @admin.display(description='Betrag netto', ordering='betrag_netto')
    def betrag_anzeige(self, obj) -> str:
        return f'{geld(obj.betrag_netto)} €'

    @admin.display(description='Zugeordnet')
    def zugeordnet_anzeige(self, obj) -> str:
        return f'{geld(obj.zugeordnet)} €'

    @admin.display(description='Rest')
    def rest_anzeige(self, obj):
        """Offener Betrag, rot nur bei negativem Wert.

        Ein positiver Rest ist noch zu verteilen. Ein negativer bedeutet,
        dass mehr verteilt ist, als die Rechnung fordert, meist durch einen
        Zahlendreher.
        """
        if obj.ist_vollstaendig:
            # format_html ohne Platzhalter wirft beim Rendern der Liste einen
            # TypeError.
            return format_html(
                '<span class="text-green-600 dark:text-green-500">{}</span>',
                'vollständig')
        if obj.rest < 0:
            return format_html(
                '<span class="font-semibold text-red-600 dark:text-red-500">'
                '{} €</span>', geld(obj.rest))
        return format_html(
            '<span class="text-green-600 dark:text-green-500">{} €</span>',
            geld(obj.rest))

    @admin.display(description='Projekt')
    def projekte_anzeige(self, obj) -> str:
        nummern = sorted({p.projekt.nummer for p in obj.positionen.all()})
        if not nummern:
            return '—'
        if len(nummern) <= 3:
            return ', '.join(nummern)
        return f'{", ".join(nummern[:3])} … (+{len(nummern) - 3})'

    # ── E-Rechnung einlesen ──────────────────────────────────────────────

    @unfold_action(
        description='E-Rechnung einlesen',
        icon='upload_file',
        url_path='erechnung-einlesen',
        permissions=['add'],
        variant=ActionVariant.PRIMARY,
    )
    def liste_erechnung(self, request):
        """Datei hochladen und einlesen in einem Schritt, ohne Vorschau.

        Eine Eingangsrechnung ist frei änderbar und löschbar; das Ergebnis
        zeigt die Änderungsansicht, in der danach verteilt wird. Eine
        Vorschau müsste die Datei über einen zweiten POST weitergeben.
        """
        if request.method != 'POST':
            return self._erechnung_maske(request, ERechnungForm())

        formular = ERechnungForm(request.POST, request.FILES)
        if not formular.is_valid():
            return self._erechnung_maske(request, formular)

        datei = formular.cleaned_data['datei']
        gewaehlt = formular.cleaned_data['projekt']
        try:
            rechnung, gelesen = eingangsrechnung_aus_xml(
                daten=datei.read(),
                dateiname=datei.name,
                projekt=gewaehlt,
            )
        except FachlicherFehler as fehler:
            # Auch ERechnungFehler aus erfassung/erechnung.py, der nicht von
            # ErfassungError erbt.
            self.message_user(request, str(fehler), level=messages.ERROR)
            return self._erechnung_maske(request, formular)

        self._erechnung_melden(request, rechnung, gelesen)
        if gewaehlt is None:
            self._projektreferenz_melden(request, rechnung, gelesen)
        return HttpResponseRedirect(reverse(
            f'admin:{self.opts.app_label}_{self.opts.model_name}_change',
            args=[rechnung.pk]))

    def _erechnung_maske(self, request, formular):
        return render(request, 'admin/erfassung/erechnung_einlesen.html', {
            **self.admin_site.each_context(request),
            'title': 'E-Rechnung einlesen',
            'opts': self.opts,
            'formular': formular,
        })

    def _projektreferenz_melden(self, request, rechnung, gelesen) -> None:
        """Meldet die Herkunft des Projekts oder warum keines zugeordnet ist.

        Nur ohne Auswahl im Formular, weil eine Auswahl Vorrang vor der
        Projektreferenz der Rechnung hat.
        """
        referenz = gelesen.projektreferenz
        if not referenz:
            return
        erste = rechnung.positionen.select_related('projekt').first()
        if erste is not None:
            self.message_user(request, format_html(
                'Projekt {} aus der Projektreferenz der Rechnung ({}) '
                'übernommen. Stimmt es nicht, hier in den Positionen '
                'ändern.', erste.projekt, referenz,
            ), level=messages.INFO)
        else:
            self.message_user(request, format_html(
                'Die Projektreferenz der Rechnung ({}) passt zu keinem '
                'laufenden Projekt eindeutig. Bitte die Positionen von Hand '
                'zuordnen.', referenz,
            ), level=messages.WARNING)

    def _erechnung_melden(self, request, rechnung, gelesen) -> None:
        """Meldet das Ergebnis des Einlesens und warnt bei Abweichungen.

        Weicht die Positionssumme vom Kopfbetrag ab, enthält das Dokument
        einen Zu- oder Abschlag (Versand, Skonto), den das Modell nicht
        abbildet. Der Rest bleibt offen; die Warnung nennt den Grund.
        """
        zahl = len(gelesen.positionen)
        self.message_user(request, format_html(
            '{} eingelesen{}: {} {}, {} € netto.',
            rechnung.nummer,
            ' (XML aus dem PDF geholt)' if gelesen.aus_pdf else '',
            zahl, 'Position' if zahl == 1 else 'Positionen',
            geld(rechnung.betrag_netto),
        ), level=messages.SUCCESS)

        abweichung = gelesen.betrag_netto - gelesen.positionssumme
        if gelesen.positionen and abweichung:
            self.message_user(request, format_html(
                'Die Positionen ergeben {} €, der Rechnungsbetrag lautet '
                'auf {} €, eine Abweichung von {} €. Im Dokument steht '
                'vermutlich ein Zu- oder Abschlag auf Belegebene (Versand, '
                'Skonto, Rabatt). Der Rest steht so lange offen.',
                geld(gelesen.positionssumme), geld(gelesen.betrag_netto),
                geld(abweichung),
            ), level=messages.WARNING)


class FremdZustandFilter(admin.SimpleListFilter):
    """Filter nicht abrechenbar, offen, abgerechnet, mit denselben Werten wie
    der Zustandsfilter der Erfassung, damit Links aus den Akten in beiden
    Listen gleich wirken."""

    title = 'Zustand'
    parameter_name = 'zustand'

    def lookups(self, request, model_admin):
        return [(z.value, z.label) for z in Zustand]

    def queryset(self, request, queryset):
        wert = self.value()
        if wert == Zustand.NICHT_ABRECHENBAR:
            return queryset.filter(weiterberechenbar=False)
        if wert == Zustand.OFFEN:
            return queryset.filter(weiterberechenbar=True,
                                   abgerechnet_in__isnull=True)
        if wert == Zustand.ABGERECHNET:
            return queryset.filter(weiterberechenbar=True,
                                   abgerechnet_in__isnull=False)
        return queryset


@admin.register(Fremdleistung)
class FremdleistungAdmin(Kopfleiste, AuftragspositionFeld,
                         GeschichteZumLesen,
                         unfold_admin.ModelAdmin):
    """Alle Fremdleistungen über alle Eingangsrechnungen, mit Angabe, was
    bereits weiterberechnet ist.
    """

    #: Volle Breite, siehe ``EingangsrechnungAdmin``.
    list_fullwidth = True

    list_display = ['datum_anzeige', 'projekt', 'auftragsposition',
                    'bezeichnung', 'menge', 'einkauf_anzeige',
                    'zustand_anzeige_spalte', 'rechnung_spalte']
    # Auch das Datum ist verlinkt, weil im Admin die erste Spalte auf den
    # Datensatz führt.
    list_display_links = ['datum_anzeige', 'bezeichnung']
    list_filter = [FremdZustandFilter, 'weiterberechenbar',
                   'rechnung__lieferant', ('projekt', AutocompleteSelectFilter),
                   'rechnung__datum']
    search_fields = ['bezeichnung', 'projekt__nummer', 'projekt__bezeichnung',
                     'rechnung__nummer']
    autocomplete_fields = ['projekt', 'rechnung']
    fields = ['rechnung', 'projekt', 'auftragsposition', 'bezeichnung',
              'leistungsdatum', 'einheit', 'menge', 'einkaufspreis',
              'einkauf_netto', 'weiterberechenbar']
    actions = ['in_rechnung']

    #: Lookups der Links aus den Akten (``auswertung/zuordnung.py``), wie in
    #: der Erfassungsliste. Ohne Eintrag lehnt Django sie ab, weil kein
    #: Filter sie führt.
    VERWEISE_VON_AUSSEN = ('auftragsposition__beleg__id',
                           'auftragsposition__id', 'auftragsposition__isnull',
                           'abgerechnet_in__beleg__id', 'projekt__id')

    def lookup_allowed(self, lookup, value, request=None):
        if lookup.startswith(self.VERWEISE_VON_AUSSEN):
            return True
        return super().lookup_allowed(lookup, value, request)

    change_list_template = 'admin/erfassung/fremdleistung/change_list.html'

    def changelist_view(self, request, extra_context=None):
        """Summe des gefilterten Bestands zum Einkaufspreis, wie die
        Zeitsumme über der Erfassungsliste; über ``cl.queryset`` und damit
        über alle Seiten."""
        from django.db.models import Sum

        antwort = super().changelist_view(request, extra_context)
        liste = getattr(antwort, 'context_data', {}).get('cl')
        if liste is not None:
            summe = liste.queryset.aggregate(s=Sum('einkauf_netto'))['s']
            antwort.context_data['einkaufssumme'] = geld(summe or 0)
            antwort.context_data['anzahl'] = liste.result_count
        return antwort

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        feld = super().formfield_for_dbfield(db_field, request, **kwargs)
        if feld is not None and db_field.name == 'menge':
            feld.widget.attrs['step'] = '1'
        return feld

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'projekt', 'auftragsposition__beleg', 'rechnung__lieferant',
            'abgerechnet_in__beleg')

    @admin.display(description='Datum', ordering='rechnung__datum')
    def datum_anzeige(self, obj):
        return obj.rechnung.datum

    # Ohne Verkaufspreis und Spanne, weil der Verkaufspreis erst an der
    # Rechnungsposition entsteht, die oft mehrere Zeilen bündelt.
    @admin.display(description='Einkauf', ordering='einkauf_netto')
    def einkauf_anzeige(self, obj) -> str:
        return f'{geld(obj.einkauf_netto)} €'

    @admin.display(description='Zustand')
    def zustand_anzeige_spalte(self, obj):
        return obj.zustand_anzeige

    @admin.display(description='Rechnungsnummer',
                   ordering='abgerechnet_in__beleg__nummer')
    def rechnung_spalte(self, obj):
        """Ausgangsrechnung, auf der die Fremdleistung steht, als Link auf
        deren Akte, auch bei Entwürfen.

        Eigene Spalte, damit sie sortierbar ist. Verlinkt wird die Rechnung,
        weil die Position allein ("10. Montage") nicht auffindbar ist.
        """
        beleg = obj.abgerechneter_beleg
        if beleg is None:
            return ''
        text = beleg.nummer or f'Entwurf {beleg.pk}'
        url = erweiterungen.akte_url('rechnung', beleg.pk)
        if url is None:
            return text
        return format_html(
            '<a href="{}" class="text-primary-600 dark:text-primary-500">'
            '{}</a>', url, text)

    @admin.action(description='In Rechnung übernehmen')
    def in_rechnung(self, request, queryset):
        """Dieselbe Vorschau wie bei den Stunden.

        Template und Service sind gemeinsam, nur die Quelle unterscheidet
        sich. Verworfen: ein gemeinsames Mixin mit ``ErfassungszeileAdmin``,
        weil es für diesen einen Unterschied mehr Indirektion als Nutzen
        brächte.
        """
        try:
            vorschau = abrechnungsvorschau([], queryset)
        except ErfassungError as fehler:
            self.message_user(request, str(fehler), level=messages.ERROR)
            return None

        if not vorschau.fremdpositionen:
            self.message_user(
                request,
                'In der Auswahl steht nichts, was weiterberechnet werden '
                'könnte.',
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
            'entwuerfe': [(e, entwurfsname_von(e))
                          for e in entwuerfe_fuer(vorschau.projekt)],
            'auswahl': request.POST.getlist(ACTION_CHECKBOX_NAME),
            'aktion': 'in_rechnung',
            'select_klassen': AUSWAHL_KLASSEN,
        })

    def _uebernehmen(self, request, queryset, vorschau):
        try:
            ziel, art = ziel_aus_auswahl(request.POST.get('ziel', ''),
                                         vorschau.projekt)
        except LookupError:
            self.message_user(request, 'Die gewählte Rechnung gibt es '
                                       'nicht mehr.', messages.ERROR)
            return None

        try:
            beleg, ergebnis = in_rechnung_uebernehmen(
                zeilen=[], fremdleistungen=queryset, beleg=ziel,
                rechnungsart=art)
        except ErfassungError as fehler:
            self.message_user(request, str(fehler), level=messages.ERROR)
            return None

        self.message_user(request, format_html(
            '{} Positionen weiterberechnet: <a href="{}">{}</a>',
            len(ergebnis.fremdpositionen), _rechnungsadresse(beleg), beleg,
        ), level=messages.SUCCESS)

        if ergebnis.uebergangen:
            self.message_user(request, format_html(
                '{} Positionen wurden übergangen: {}',
                len(ergebnis.uebergangen),
                ', '.join(sorted({grund for _, grund in ergebnis.uebergangen})),
            ), level=messages.WARNING)
        return None


@admin.register(Kostensatz)
class KostensatzAdmin(Kopfleiste, unfold_admin.ModelAdmin):
    """Kostensätze je Person mit Gültigkeitsbeginn; neuester Satz oben."""

    list_display = ['person', 'gueltig_ab', 'satz_anzeige', 'notiz']
    list_display_links = ['person', 'gueltig_ab']
    list_filter = ['benutzer']
    ordering = ['benutzer', '-gueltig_ab']
    date_hierarchy = 'gueltig_ab'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('benutzer')

    @admin.display(description='Person', ordering='benutzer__last_name')
    def person(self, obj) -> str:
        return personenname(obj.benutzer)

    @admin.display(description='Kostensatz', ordering='satz')
    def satz_anzeige(self, obj) -> str:
        return f'{geld(obj.satz)} €/Std'
