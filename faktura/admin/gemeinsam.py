"""Gemeinsame Bausteine der Admins: Speichern vor Detailaktionen, Filter,
Links auf Belege, Positions-Inline."""

import logging
from decimal import Decimal

from django import forms
from django.contrib import admin
from django.contrib.admin.templatetags.admin_urls import add_preserved_filters
from django.db.models import Q
from django.forms import Script
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html
from unfold import admin as unfold_admin
from unfold.contrib.filters.admin import DropdownFilter
from unfold.contrib.filters.forms import AutocompleteDropdownForm

from core.adminhilfen import mit_stand

from .. import formate, services
from ..facturx import BT_POSITION, mit_bt
from ..forms import (
    BelegpositionForm,
    BelegpositionFormSet,
)
from ..models import (
    STEUERFREI,
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Kontakt,
    Zeilenart,
    proxy_fuer,
)

DESCRIPTION_TEXT = 'Verknüpfung zu Projekt oder Kunde. Übernimmt hinterlegte Daten.'


logger = logging.getLogger(__name__)


class AktionNachDemSichern:
    """Speichert das Formular und leitet auf die gewählte Detailaktion
    weiter; Serverseite von ``aktion_erst_speichern.js``.

    Ohne Speichern arbeitete die Aktion mit dem gespeicherten Stand, und
    ungespeicherte Eingaben gingen verloren. Übertragen wird nur das
    Pfadsegment der Aktion (``_danach``); die URL entsteht über
    ``reverse()`` und nur aus den für den Benutzer sichtbaren Aktionen, um
    Open Redirects und Umgehung der Rechte auszuschließen.
    """

    @property
    def media(self):
        """Bindet das Skript mit ``defer`` ein, weil Django Media im <head>
        einbindet und das Skript sonst vor dem Formular liefe."""
        return super().media + forms.Media(  # type: ignore[misc]
            js=[Script(  # type: ignore[list-item]
                mit_stand('faktura/js/aktion_erst_speichern.js'), defer=True)],
        )

    def response_change(self, request, obj):
        pfad = request.POST.get('_danach', '').strip('/')
        if pfad:
            ziel = self._adresse_der_aktion(request, obj, pfad)
            if ziel is not None:
                return redirect(ziel)
            # Gespeichert ist es; die Meldung erscheint trotzdem.
            logger.warning(
                'Unbekanntes Ziel nach dem Sichern von %s: %r', obj, pfad)
        return super().response_change(request, obj)  # type: ignore[misc]

    def _adresse_der_aktion(self, request, obj, pfad: str):
        """URL der Detailaktion mit diesem Pfadsegment oder None."""
        for aktion in self.get_actions_detail(request, obj.pk):  # type: ignore[attr-defined]
            if aktion.path.strip('/') == pfad:
                # ``action_name`` ist bereits der volle URL-Name
                # ('faktura_angebot_detail_pdf').
                return add_preserved_filters(
                    {'preserved_filters': self.get_preserved_filters(request),  # type: ignore[attr-defined]
                     'opts': obj._meta},
                    reverse(f'admin:{aktion.action_name}', args=[obj.pk]))
        return None


class VersandstandFilter(admin.SimpleListFilter):
    """Filter per Mail versendet oder festgeschrieben ohne Mail.

    Ein Versand per Post oder Portal ist nicht erfasst; die Option heißt
    deshalb "ohne E-Mail". Ohne Entwürfe.
    """

    title = 'E-Mail'
    parameter_name = 'versandstand'

    def lookups(self, request, model_admin):
        return [
            ('versendet', 'Per E-Mail versendet'),
            ('offen', 'Festgeschrieben, ohne E-Mail'),
        ]

    def queryset(self, request, queryset):
        if self.value() == 'versendet':
            return queryset.filter(versendet_am__isnull=False)
        if self.value() == 'offen':
            return queryset.filter(versendet_am__isnull=True,
                                   status=BelegStatus.FESTGESCHRIEBEN)
        return queryset


class ZahlungsstandFilter(admin.SimpleListFilter):
    """Offen, überfällig, bezahlt.

    In Python über ``offene_posten()``, weil Brutto die Steuer je Satz
    braucht und kein einzelner SQL-Ausdruck ist; bei den Mengen einer
    Rechnungsliste unkritisch. Ohne Entwürfe.
    """

    title = 'Zahlungsstand'
    parameter_name = 'zahlungsstand'

    def lookups(self, request, model_admin):
        return [
            ('offen', 'Offen'),
            ('ueberfaellig', 'Überfällig'),
            ('bezahlt', 'Bezahlt'),
        ]

    def queryset(self, request, queryset):
        if self.value() not in ('offen', 'ueberfaellig', 'bezahlt'):
            return queryset

        stand = services.offene_posten()
        if self.value() == 'ueberfaellig':
            offen = {p.beleg.pk for p in stand.ueberfaellig}
        else:
            offen = {p.beleg.pk for p in stand.posten}

        festgeschrieben = queryset.filter(
            typ=BelegTyp.RECHNUNG, status=BelegStatus.FESTGESCHRIEBEN)
        if self.value() == 'bezahlt':
            return festgeschrieben.exclude(pk__in=offen)
        return festgeschrieben.filter(pk__in=offen)


class ArchiviertFilter(admin.SimpleListFilter):
    """Blendet ohne Auswahl Erledigtes aus, weil meist die wenigen laufenden
    Einträge gesucht werden. "Alle" zeigt alles; die Vorauswahl ist
    beschriftet.

    Unterklassen setzen ``feld``, ``erledigt_heisst`` und die
    Beschriftungen.
    """

    #: Modellfeld, das die Erledigung anzeigt.
    feld = ''
    #: Wert dieses Feldes, der "erledigt" bedeutet.
    erledigt_heisst = True

    laufend_beschriftung = 'Nur laufende'
    erledigt_beschriftung = 'Nur erledigte'

    def lookups(self, request, model_admin):
        return [
            ('laufend', self.laufend_beschriftung),
            ('erledigt', self.erledigt_beschriftung),
            ('alle', 'Alle'),
        ]

    def choices(self, changelist):
        """Beschriftet die Vorauswahl, die Django "Alle" nennen würde."""
        auswahl = list(super().choices(changelist))
        auswahl[0]['display'] = self.laufend_beschriftung
        return auswahl

    def queryset(self, request, queryset):
        if self.value() == 'alle':
            return queryset
        if self.value() == 'erledigt':
            return queryset.filter(**{self.feld: self.erledigt_heisst})
        return queryset.exclude(**{self.feld: self.erledigt_heisst})


class KontaktAktivFilter(ArchiviertFilter):
    """Kunden, die noch zur Wahl stehen."""

    title = 'Sichtbarkeit'
    parameter_name = 'sichtbarkeit'
    feld = 'aktiv'
    erledigt_heisst = False
    laufend_beschriftung = 'Nur aktive'
    erledigt_beschriftung = 'Nur inaktive'


class RolleFilter(admin.SimpleListFilter):
    """Filter nach Rolle: Kunde, Lieferant, Partner, Interessent. Ein Kontakt
    mit mehreren Rollen erscheint in jeder."""

    title = 'Rolle'
    parameter_name = 'rolle'

    def lookups(self, request, model_admin):
        return [(feld.removeprefix('ist_'), name)
                for feld, name in Kontakt.ROLLEN.items()]

    def queryset(self, request, queryset):
        feld = f'ist_{self.value()}' if self.value() else None
        if feld not in Kontakt.ROLLEN:
            return queryset
        return queryset.filter(**{feld: True})


class ProjektAbgeschlossenFilter(ArchiviertFilter):
    """Filter auf laufende Vorhaben; abgeschlossene bleiben über "Alle"
    auffindbar."""

    title = 'Bearbeitungsstand'
    parameter_name = 'stand'
    feld = 'abgeschlossen'
    erledigt_heisst = True
    laufend_beschriftung = 'Nur laufende'
    erledigt_beschriftung = 'Nur abgeschlossene'




class KundeBelegFilter(DropdownFilter):
    """Alle Belege eines Kunden, einschließlich der Belege seiner Projekte.

    Ein Filter auf ``kunde`` fände Projektbelege nicht, weil sie keinen
    eigenen Kunden haben (``kunde_oder_projekt_nicht_beides``).

    Als Autocomplete, weil eine Auswahl jeden Kontakt in jede Belegliste
    lud, nach zehn Jahren über 400. Die Suche ist dieselbe wie in der
    Kundenliste. Der Parameter ist ``?kunde=``, auf den die Kundenakte
    verlinkt.
    """

    title = 'Kunde'
    parameter_name = 'kunde'

    def __init__(self, request, params, model, model_admin):
        super().__init__(request, params, model, model_admin)
        self.request = request
        self.model_admin = model_admin

    def lookups(self, request, model_admin):
        # Keine Optionen vorladen, die Auswahl kommt aus dem Autocomplete.
        # Ein leeres Tupel bedeutete für Django "kein Filter", deshalb
        # has_output unten.
        return ()

    def has_output(self):
        return True

    def choices(self, changelist):
        yield {
            'form': AutocompleteDropdownForm(
                request=self.request,
                name=self.parameter_name,
                label=f' Nach {self.title} ',
                choices=(),
                # Das Feld dient nur als Vorlage für das Autocomplete, das
                # über den Admin von Kontakt sucht. Gefiltert wird in
                # ``queryset`` über den Kunden oder sein Projekt.
                field=Beleg._meta.get_field('kunde'),
                model_admin=self.model_admin,
                data={self.parameter_name: self.value()},
            ),
        }

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        return queryset.filter(
            Q(kunde_id=self.value()) | Q(projekt__kunde_id=self.value()))


def adresse_im_admin(beleg) -> str:
    """Admin-URL des Belegs über den Proxy seiner Belegart, weil ``Beleg``
    nicht registriert ist. Leer ohne passenden Proxy."""
    modell = proxy_fuer(beleg.typ, beleg.rechnungsart)
    if modell is Beleg:
        return ''
    return reverse(
        f'admin:{modell._meta.app_label}_{modell._meta.model_name}_change',
        args=[beleg.pk],
    )


def verweis_auf(beleg):
    """Beleg als Link für Meldungen, etwa zu einem neuen Entwurf ohne
    Nummer."""
    adresse = adresse_im_admin(beleg)
    if not adresse:
        return format_html('{}', beleg)
    return format_html('<a href="{}">{}</a>', adresse, beleg)


class BelegpositionInline(unfold_admin.TabularInline):
    """Positionen eines Belegs."""

    model = Belegposition
    form = BelegpositionForm
    formset = BelegpositionFormSet
    extra = 3
    #: Ohne Unfolds Titelzeile ("10. Ingenieurstunde"), die nur Pos. und
    #: Bezeichnung wiederholt. Die Hidden Inputs (pk, fk) gibt Unfold in
    #: derselben Zeile aus.
    show_title = False
    #: CSS-Klasse ``positionszeile`` für Spaltenbreiten und Ausrichtung in
    #: faktura_admin.css.
    positionszeile = True
    #: Die Zeilenart steht vorn, weil die erste Zeile die Felder in dieser
    #: Reihenfolge ausgibt: links die Zeilenart, rechts daneben die Suche.
    #: In den Zusatzzeilen ebenso: Prozent und "auf" vor dem Langtext, wie
    #: der Rechenweg im PDF unter der Bezeichnung.
    fields = ['zeilenart', 'katalog', 'position', 'bezeichnung',
              'zuschlag_prozent', 'zuschlag_auf', 'langtext',
              'menge', 'einheit', 'einzelpreis', 'steuersatz', 'zeilensumme',
              'leistung_von', 'leistung_bis', 'optional']
    readonly_fields = ['zeilensumme']
    #: Felder in einer eigenen Zeile über die volle Breite über oder unter
    #: der Position; eigene Einstellungen, ausgewertet in
    #: ``templates/unfold/helpers/edit_inline/tabular_group.html``. Dazu
    #: gehören die Regeln in faktura_admin.css und ``zweite_zeile.js``.
    #: Die Katalogsuche steht oben, weil sie Platz für lange Bezeichnungen
    #: braucht und später weitere Angaben neben sich bekommen soll.
    #: Die Zeilenart steht links daneben und entfällt mit ihr nach dem
    #: Speichern, weil sie beim Anlegen gewählt wird. Was an einer
    #: Zeilenart nichts sagt (Menge an einem Titel, Prozent an einer
    #: Leistung), sperrt das Formular und verbirgt die Maske
    #: (``Zeilenart.felder_ohne_bedeutung``, zeilenart.js).
    erste_zeile_felder = ['zeilenart', 'katalog']
    zweite_zeile_felder = ['zuschlag_prozent', 'zuschlag_auf', 'langtext',
                           'leistung_von', 'leistung_bis', 'optional']
    #: Felder in der Spalte der Bezeichnung, wie im PDF. Zeitraum und Option
    #: stehen rechts daneben.
    zweite_zeile_links = ['zuschlag_prozent', 'zuschlag_auf', 'langtext']

    #: Ob die Spalten ihre BT-Nummer zeigen; gesetzt von
    #: ``FormularMixin.get_inline_instances``, nur bei Steuerbelegen.
    mit_bt_nummern = False
    #: Ob die Checkbox "Optional" erscheint; ebenso gesetzt, nur an Angebot
    #: und Auftrag (``BelegTyp.mit_optionen``).
    mit_optionen = False

    #: Pflichtfelder für die Anzeige des Sternchens im Spaltenkopf
    #: (``tabular_heading.html``). Geprüft werden sie erst in
    #: ``BelegpositionForm.clean()``, weil der Katalog Bezeichnung und Preis
    #: noch beim Speichern füllen kann.
    pflichtspalten = ['bezeichnung', 'einzelpreis']

    #: Kurze Spaltenköpfe wie auf einer Rechnung, nur in der
    #: Positionstabelle; Modell, Katalog und PDF behalten ihre Namen.
    SPALTENKOEPFE = {
        'einzelpreis': 'Preis (Netto)',
        'steuersatz': 'USt.',
        'zeilensumme': 'Betrag',
    }

    def get_formset(self, request, obj=None, **kwargs):
        """Spaltenköpfe und BT-Nummern über ``Meta.labels``, damit sie auch an
        den schreibgeschützten Positionen eines festgeschriebenen Belegs
        erscheinen."""
        felder = {f.name: str(f.verbose_name) for f in self.model._meta.fields}
        beschriftungen = {**felder, **self.SPALTENKOEPFE}
        if self.mit_bt_nummern:
            beschriftungen = {
                name: mit_bt(text, name, {**BT_POSITION,
                                          'zeilensumme': 'BT-131'})
                for name, text in beschriftungen.items()
            }
        kwargs.setdefault('labels', beschriftungen)
        return super().get_formset(request, obj, **kwargs)

    def get_extra(self, request, obj=None, **kwargs):
        """Drei leere Zeilen für einen neuen Beleg, eine unter vorhandenen
        Positionen. Weitere über "hinzufügen"."""
        if obj is not None and obj.pk and obj.positionen.exists():
            return 1
        return self.extra

    def get_fields(self, request, obj=None):
        """Am festgeschriebenen Beleg ohne Spalten Katalog und Zeilenart.

        ``katalog`` ist ein Formularfeld ohne Modellfeld, das die
        Read-only-Ansicht am Modell suchen würde. Die Zeilenart entfällt,
        weil dort ``lesewert`` am Objekt bestimmt, was angezeigt wird.
        """
        felder = super().get_fields(request, obj)
        if obj is not None and not obj.ist_aenderbar:
            felder = [f for f in felder if f not in ('katalog', 'zeilenart')]
        # Der Zeitraum je Position (BT-134/135) gehört nur zur Rechnung.
        if not self.mit_bt_nummern:
            felder = [f for f in felder
                      if f not in ('leistung_von', 'leistung_bis')]
        if not self.mit_optionen:
            felder = [f for f in felder if f != 'optional']
        return felder

    @admin.display(description='Betrag')
    def zeilensumme(self, position):
        # Ungespeichert rechnet zeilensumme.js beim Tippen mit.
        if position.pk is None:
            return '-'
        if position.zeilenart in Zeilenart.ohne_betrag():
            return ''
        # Der optionale Zuschlag hat keinen Betrag, nur den Satz.
        if position.zeilenart == Zeilenart.ZUSCHLAG and position.optional:
            return ''
        return formate.geld_mit_waehrung(services.positionssumme(
            menge=position.menge, einzelpreis=position.einzelpreis
        ))

    def has_change_permission(self, request, obj=None):
        # obj ist hier der Beleg.
        if obj is not None and not obj.ist_aenderbar:
            return False
        return super().has_change_permission(request, obj)

    def has_add_permission(self, request, obj=None):
        if obj is not None and not obj.ist_aenderbar:
            return False
        return super().has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and not obj.ist_aenderbar:
            return False
        return super().has_delete_permission(request, obj)


class SchlusspositionInline(BelegpositionInline):
    """Positionen einer Schluss- oder Teilschlussrechnung, nur die Leistung.

    Die Abzugszeilen stehen darunter je Abschlag zusammengefasst, wie im PDF
    (``admin/faktura/abzugsblock.html``). Sie sind Positionen des Belegs und
    zählen in den Summen, sind hier aber nicht bearbeitbar; angelegt und
    abgeglichen werden sie über "Abschläge absetzen"
    (``services.abschlaege_absetzen``). Das Formset berücksichtigt ihre
    Nummern (``BelegpositionFormSet._verborgene_nummern``).
    """

    def get_queryset(self, request):
        return super().get_queryset(request).filter(ist_abzug=False)


class LieferpositionInline(BelegpositionInline):
    """Positionen ohne Preis, gespeichert mit Preis null und 0 %."""

    fields = ['katalog', 'position', 'bezeichnung', 'menge', 'einheit']
    zweite_zeile_felder = []

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        grundform = formset.form

        class MitNullpreis(grundform):  # type: ignore[misc]
            def clean(self):
                super().clean()
                self.cleaned_data['einzelpreis'] = Decimal('0.00')
                self.cleaned_data['steuersatz'] = STEUERFREI
                # Auch an der Instanz, weil construct_instance() nur Felder des
                # Formulars übernimmt und Preis und Steuersatz fehlen.
                self.instance.einzelpreis = Decimal('0.00')
                self.instance.steuersatz = STEUERFREI
                return self.cleaned_data

        formset.form = MitNullpreis
        return formset


class MahnpositionInline(BelegpositionInline):
    """Aufstellung einer Mahnung: geforderte Posten und Beträge.

    Ohne Katalog, Menge, Einheit, Steuersatz und Langtext, weil die Mahnung
    eine berechnete Leistung anfordert. Gespeichert mit Menge 1 und 0 %, wie
    ``mahnung_erstellen`` die Zeilen anlegt.
    """

    fields = ['position', 'bezeichnung', 'einzelpreis']
    erste_zeile_felder = []
    zweite_zeile_felder = []
    SPALTENKOEPFE = {'bezeichnung': 'Offene Forderung', 'einzelpreis': 'Betrag'}

    def get_extra(self, request, obj=None, **kwargs):
        """Keine leere Zeile, weil die Mahnung ihre Zeilen mitbringt; weitere
        über "Position hinzufügen"."""
        if obj is not None and obj.pk and obj.positionen.exists():
            return 0
        return super().get_extra(request, obj, **kwargs)

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        grundform = formset.form

        class AlsForderung(grundform):  # type: ignore[misc]
            def clean(self):
                super().clean()
                # Auch an der Instanz, siehe ``LieferpositionInline``.
                self.instance.menge = Decimal('1')
                self.instance.einheit = ''
                self.instance.steuersatz = STEUERFREI
                return self.cleaned_data

        formset.form = AlsForderung
        return formset
