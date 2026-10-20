"""Zahlungseingänge und ihre Zuordnung auf Rechnungen.

Eigenes Modul, weil eine Zahlung kein Beleg ist: kein Nummernkreis, keine
Festschreibung, kein PDF.
"""

from django.contrib import admin
from django.db.models import Q
from unfold import admin as unfold_admin
from unfold.contrib.filters.admin import AutocompleteSelectFilter

from core.adminhilfen import Kopfleiste
from core.optimistic_locking import VersionAdminMixin

from .. import formate
from ..models import (
    BelegStatus,
    BelegTyp,
    Zahlung,
    Zahlungszuordnung,
)


class ZahlungszuordnungInline(unfold_admin.TabularInline):
    """Verteilung der Zahlung auf Rechnungen."""

    model = Zahlungszuordnung
    extra = 1
    fields = ['beleg', 'betrag', 'skonto', 'kuerzung', 'notiz']
    verbose_name = 'Zuordnung'
    verbose_name_plural = 'Zuordnung Rechnungen'

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Zur Wahl stehen Rechnungen mit offenem Betrag und die bereits
        zugeordneten, weil eine ausgeglichene Rechnung nicht mehr offen ist
        und die Zeile sonst beim Speichern ungültig wäre.

        Kein Autocomplete, weil ``Beleg`` im Admin nicht registriert ist.
        """
        if db_field.name == 'beleg':
            from .. import services
            from ..models import Beleg

            offene = [p.beleg.pk for p in services.offene_posten().posten]
            zahlung = request.resolver_match.kwargs.get('object_id')
            eigene = (Zahlungszuordnung.objects.filter(zahlung_id=zahlung)
                      .values_list('beleg_id', flat=True) if zahlung else [])
            kwargs['queryset'] = Beleg.objects.filter(
                Q(pk__in=offene) | Q(pk__in=list(eigene)),
                typ=BelegTyp.RECHNUNG,
                status=BelegStatus.FESTGESCHRIEBEN,
            ).order_by('-nummer')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class VerteiltFilter(admin.SimpleListFilter):
    """Zahlungen mit nicht zugeordnetem Rest. In Python berechnet, weil die
    Mengen gering sind."""

    title = 'Verteilung'
    parameter_name = 'verteilung'

    def lookups(self, request, model_admin):
        return [
            ('offen', 'Noch nicht ganz verteilt'),
            ('ohne', 'Gar nicht zugeordnet'),
        ]

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        if self.value() == 'ohne':
            return queryset.filter(zuordnungen__isnull=True)
        offene = [z.pk for z in queryset.prefetch_related('zuordnungen')
                  if z.rest > 0]
        return queryset.filter(pk__in=offene)


@admin.register(Zahlung)
class ZahlungAdmin(Kopfleiste, VersionAdminMixin,
                   unfold_admin.ModelAdmin):
    """Zahlungseingänge und ihre Zuordnung; wichtigste Spalte ist der
    nicht zugeordnete Rest."""

    list_display = ['datum', 'wer', 'betrag_anzeige', 'verteilt_anzeige',
                    'rest_anzeige', 'zahlungsart']
    list_display_links = ['datum', 'wer']
    # Kunde als Filter, den der Link "Alle Zahlungen dieses Kunden" aus der
    # Kundenakte verwendet.
    list_filter = [VerteiltFilter, 'zahlungsart', 'datum',
                   ('kunde', AutocompleteSelectFilter)]
    search_fields = ['zahlername', 'verwendungszweck', 'referenz',
                     'kunde__name', 'kunde__nummer']
    date_hierarchy = 'datum'
    ordering = ['-datum', '-pk']
    autocomplete_fields = ['kunde']
    inlines = [ZahlungszuordnungInline]
    readonly_fields = ['erfasst_am']
    # Zwei offene Abschnitte: Betrag und Zuordnung.
    fieldsets = [
        (None, {'fields': ['datum', 'betrag', 'zahlungsart']}),
        ('Zuordnung Kunde', {
            'fields': ['kunde', 'zahlername', 'verwendungszweck',
                       'referenz', 'notiz', 'erfasst_am'],
        }),
    ]

    def get_fieldsets(self, request, obj=None):  # type: ignore[override]
        """Beim Anlegen ohne "Erfasst am", das dann noch leer ist."""
        felder = super().get_fieldsets(request, obj)
        if obj is not None:
            return felder
        return [
            (titel, {**optionen,
                     'fields': [f for f in optionen['fields']
                                if f != 'erfasst_am']})
            for titel, optionen in felder
        ]

    def get_queryset(self, request):
        # Prefetch der Zuordnungen für die Spalten "Verteilt" und "Rest".
        return (super().get_queryset(request)
                .select_related('kunde')
                .prefetch_related('zuordnungen'))

    @admin.display(description='Zahler', ordering='zahlername')
    def wer(self, zahlung):
        return zahlung.zahlername or (zahlung.kunde.name if zahlung.kunde_id
                                      else '- unbekannt -')

    @admin.display(description='Betrag', ordering='betrag')
    def betrag_anzeige(self, zahlung):
        return formate.geld_mit_waehrung(zahlung.betrag)

    @admin.display(description='Verteilt')
    def verteilt_anzeige(self, zahlung):
        return formate.geld_mit_waehrung(zahlung.zugeordnet)

    @admin.display(description='Rest')
    def rest_anzeige(self, zahlung):
        """Nicht verteilter Rest, ein Strich, wenn alles verteilt ist."""
        if zahlung.rest == 0:
            return '-'
        return formate.geld_mit_waehrung(zahlung.rest)


@admin.register(Zahlungszuordnung)
class ZahlungszuordnungAdmin(Kopfleiste, unfold_admin.ModelAdmin):
    """Zuordnungen aus Sicht der Rechnung (welche Zahlung sie ausgleicht);
    gepflegt an der Zahlung."""

    list_display = ['beleg', 'zahlung', 'betrag_anzeige', 'skonto_anzeige',
                    'kuerzung_anzeige']
    list_filter = ['zahlung__zahlungsart']
    search_fields = ['beleg__nummer', 'zahlung__zahlername',
                     'zahlung__verwendungszweck']
    # Kein Autocomplete auf den Beleg, weil ``Beleg`` nicht registriert ist
    # und der System-Check sonst fehlschlüge.

    def get_queryset(self, request):
        return (super().get_queryset(request)
                .select_related('beleg', 'zahlung'))

    @admin.display(description='Betrag', ordering='betrag')
    def betrag_anzeige(self, zuordnung):
        return formate.geld_mit_waehrung(zuordnung.betrag)

    @admin.display(description='Skonto', ordering='skonto')
    def skonto_anzeige(self, zuordnung):
        if zuordnung.skonto == 0:
            return '-'
        return formate.geld_mit_waehrung(zuordnung.skonto)

    @admin.display(description='Gekürzt', ordering='kuerzung')
    def kuerzung_anzeige(self, zuordnung):
        if zuordnung.kuerzung == 0:
            return '-'
        return formate.geld_mit_waehrung(zuordnung.kuerzung)
