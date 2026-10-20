"""Admin der Abnahme, im Menü zwischen Aufträgen und Lieferscheinen.

Meist aus der Auftragsakte angelegt ("Abnahme erfassen", mit vorbelegtem
Auftrag). Aus der Abnahme entsteht die Schluss- oder Teilschlussrechnung;
eine Teilschlussrechnung entsteht nur hier.
"""

from django import forms
from django.contrib import admin, messages
from django.db.models import Q
from django.shortcuts import redirect
from django.utils.html import format_html
from unfold import admin as unfold_admin
from unfold.decorators import action as unfold_action
from unfold.enums import ActionVariant

from core.adminhilfen import GeschichteZumLesen, Kopfleiste, weitere
from core.optimistic_locking import VersionAdminMixin

from .. import formate, services
from ..models import (
    Abnahme,
    Abnahmeart,
    Abnahmestand,
    Beleg,
    Belegposition,
    BelegTyp,
)
from .gemeinsam import adresse_im_admin


class AbnahmeForm(forms.ModelForm):
    class Meta:
        model = Abnahme
        fields = '__all__'  # noqa: DJ007

    def clean(self):
        """Regeln zu den Positionen. Im Formular, weil eine
        ManyToMany-Beziehung am Modell erst nach dem Speichern vorliegt."""
        daten = super().clean()
        art = daten.get('art')
        positionen = daten.get('positionen') or []
        auftrag = daten.get('auftrag')

        if art == Abnahmeart.GESAMT and positionen:
            self.add_error('positionen', 'Die Gesamtabnahme umfasst den '
                           'ganzen Auftrag; Positionen nur bei der '
                           'Teilabnahme.')
        if art == Abnahmeart.TEIL and not positionen:
            self.add_error('positionen', 'Welche Teilleistung abgenommen '
                           'wurde, steht in den Positionen.')
        for position in positionen:
            if auftrag and position.beleg_id != auftrag.pk and (
                    position.beleg.nachtrag_zu_id != auftrag.pk):
                self.add_error('positionen', f'{position} gehört nicht zu '
                               f'{auftrag}.')
            if art == Abnahmeart.TEIL and not position.offene_menge:
                self.add_error('positionen', f'Position {position.position} '
                               f'"{position.bezeichnung}" ist schon '
                               f'vollständig abgerechnet.')
            andere = position.teilabnahmen.exclude(pk=self.instance.pk)
            if andere.exists():
                self.add_error('positionen', f'Position {position.position} '
                               f'"{position.bezeichnung}" gehört schon zu '
                               f'{andere.first()}.')
        return daten


@admin.register(Abnahme)
class AbnahmeAdmin(Kopfleiste, VersionAdminMixin, GeschichteZumLesen,
                   unfold_admin.ModelAdmin):
    form = AbnahmeForm
    list_display = ['auftrag', 'art', 'bezeichnung', 'abgenommen_am',
                    'steuerliches_leistungsdatum', 'stand_anzeige']
    list_filter = ['art']
    search_fields = ['bezeichnung', 'auftrag__nummer']
    fields = ['auftrag', 'art', 'bezeichnung', 'positionen',
              ('leistungsbeginn', 'leistungsende'),
              ('abgenommen_am', 'steuerliches_leistungsdatum'),
              'notiz', 'stand_anzeige', 'entgelt_anzeige', 'rechnung_anzeige']
    readonly_fields = ['stand_anzeige', 'entgelt_anzeige', 'rechnung_anzeige']
    actions_detail = ['detail_rechnung', weitere()]

    # --- Vorbelegung und Auswahl ---

    def _auftrag_aus(self, request, obj=None):
        if obj is not None:
            return obj.auftrag
        pk = request.GET.get('auftrag')
        return Beleg.objects.filter(pk=pk, typ=BelegTyp.AUFTRAG).first() \
            if pk and pk.isdigit() else None

    def get_changeform_initial_data(self, request):
        """``?auftrag=`` aus der Auftragsakte; Beginn und Ende kommen aus der
        Erfassung (erster und letzter Tag mit gebuchter Leistung)."""
        vorgabe = super().get_changeform_initial_data(request)
        auftrag = self._auftrag_aus(request)
        if auftrag is not None:
            beginn, ende = services.leistungszeitraum_vorschlag(auftrag)
            vorgabe.setdefault('leistungsbeginn', beginn)
            vorgabe.setdefault('leistungsende', ende)
        return vorgabe

    def get_form(self, request, obj=None, **kwargs):
        # Für formfield_for_manytomany, das das Objekt nicht erhält.
        request._abnahme_auftrag = self._auftrag_aus(request, obj)
        return super().get_form(request, obj, **kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        """Nur Positionen dieses Auftrags und seiner Nachträge, als
        Checkboxen, weil es selten mehr als ein Dutzend sind."""
        if db_field.name == 'positionen':
            auftrag = getattr(request, '_abnahme_auftrag', None)
            kwargs['queryset'] = (
                Belegposition.objects.filter(
                    Q(beleg=auftrag) | Q(beleg__nachtrag_zu=auftrag))
                .select_related('beleg').order_by('beleg__pk', 'sortierung')
                if auftrag else Belegposition.objects.none())
            kwargs['widget'] = forms.CheckboxSelectMultiple
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'auftrag':
            kwargs['queryset'] = Beleg.objects.filter(
                typ=BelegTyp.AUFTRAG, status='festgeschrieben',
                nachtrag_zu__isnull=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # --- Sperre nach der Abrechnung ---

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.ist_abgerechnet:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.rechnungen.exists():
            return False
        return super().has_delete_permission(request, obj)

    # --- Anzeigen ---

    @admin.display(description='Stand')
    def stand_anzeige(self, abnahme):
        if abnahme.pk is None:
            return '-'
        return Abnahmestand(abnahme.stand).label

    @admin.display(description='Vereinbartes Entgelt netto')
    def entgelt_anzeige(self, abnahme):
        if abnahme.pk is None:
            return '-'
        return formate.geld_mit_waehrung(abnahme.entgelt_netto)

    @admin.display(description='Rechnung')
    def rechnung_anzeige(self, abnahme):
        if abnahme.pk is None:
            return '-'
        rechnung = abnahme.rechnungen.order_by('-pk').first()
        if rechnung is None:
            return '-'
        return format_html('<a href="{}" class="text-primary-600">{}</a>',
                           adresse_im_admin(rechnung), rechnung)

    # --- (Teil-)Schlussrechnung ---

    @unfold_action(
        description='Rechnung erzeugen',
        icon='receipt_long',
        permissions=['rechnungsfaehig'],
        url_path='rechnung',
        variant=ActionVariant.PRIMARY,
    )  # type: ignore
    def detail_rechnung(self, request, object_id):
        """Legt aus einer Teilabnahme eine Teilschlussrechnung an, aus einer
        Gesamtabnahme eine Schlussrechnung, jeweils als Entwurf."""
        try:
            rechnung = services.rechnung_aus_abnahme(abnahme_id=object_id)
        except services.FakturaError as fehler:
            self.message_user(request, str(fehler), level=messages.ERROR)
            return redirect('admin:faktura_abnahme_change', object_id)
        hinweis = ('' if rechnung.positionen.exists() else
                   ' Die Leistungen kommen über "Erbrachte Leistungen '
                   'hinzufügen".')
        self.message_user(request, f'{rechnung} angelegt.{hinweis}',
                          level=messages.SUCCESS)
        return redirect(adresse_im_admin(rechnung))

    def has_rechnungsfaehig_permission(self, request, object_id=None):
        if not request.user.has_perm('faktura.add_rechnung'):
            return False
        if object_id is None:
            return True
        abnahme = Abnahme.objects.filter(pk=object_id).first()
        return (abnahme is not None and bool(abnahme.abgenommen_am)
                and not abnahme.rechnungen.exists())
