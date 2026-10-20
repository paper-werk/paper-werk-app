"""Admins für Angebot, Auftrag, Lieferschein, Storno, Rechnungskorrektur und
Mahnung, je ein Menüpunkt. Die Rechnungen stehen in ``rechnung.py``.

Jede Klasse erbt von ``BelegAdmin`` und setzt nur Spalten, Buttons und
Feldbeschriftungen ihrer Art.

``list_display``, ``list_filter`` und ``actions_detail`` sind
Klassenattribute, die eine Unterklasse vollständig ersetzt; jede Liste ist
deshalb vollständig aufgeführt.
"""


from django.contrib import admin, messages
from django.shortcuts import redirect
from django.utils.html import format_html
from unfold.decorators import action as unfold_action
from unfold.enums import ActionVariant

from core import erweiterungen
from core.adminhilfen import weitere

from .. import formate, services
from ..models import (
    Angebot,
    Auftrag,
    BelegStatus,
    BelegTyp,
    Lieferschein,
    Mahnung,
    Rechnungskorrektur,
    Stornorechnung,
)
from .beleg import BelegAdmin
from .gemeinsam import (
    DESCRIPTION_TEXT,
    BelegpositionInline,
    LieferpositionInline,
    MahnpositionInline,
    verweis_auf,
)


@admin.register(Angebot)
class AngebotAdmin(BelegAdmin):
    typ = BelegTyp.ANGEBOT
    actions = ['action_festschreiben', 'action_in_auftrag', 'action_in_rechnung']

    #: Mit Projekt, weil Angebote meist nach Vorhaben gesucht werden.
    list_display = ['bezeichnung', 'projekt_zeile', 'empfaenger_zeile',
                    'belegdatum', 'summe_brutto', 'dokument', 'schloss']
    #: Vermeidet eine Abfrage je Zeile für den Projektnamen.
    list_select_related = ['projekt']

    # Vorn Versenden und PDF, der Rest in "Weitere …" in der Reihenfolge des
    # Regelfalls: erst Auftrag, dann direkt Rechnung. "Wieder öffnen" nur
    # bei Angebot und Auftrag. Unfold zeigt nur, was der Status erlaubt.
    actions_detail = [
        'detail_versenden', 'detail_pdf',
        weitere('detail_erneut_versenden', 'detail_in_auftrag',
                'detail_in_rechnung', 'detail_wiedereroeffnen',
                'detail_duplizieren'),
    ]

    #: Im Angebot der geplante Ausführungszeitraum, keine Pflichtangabe
    #: nach § 14 UStG.
    LEISTUNGSFELDER = {
        'leistungsdatum': (
            'Ausführung ab',
            'Zeitpunkt oder Zeitraum der Leistungserbringung. Keine steuerliche Pflichtangabe.',
        ),
        'leistungsdatum_bis': ('Ausführung bis', ''),
    }

    @admin.action(description='Auftrag daraus erzeugen')
    def action_in_auftrag(self, request, queryset):
        self._umwandeln(request, queryset, BelegTyp.AUFTRAG, 'Auftrag')

    @unfold_action(
        description='Auftrag erzeugen',
        icon='handshake',
        permissions=['nachgelagert'],
        url_path='in-auftrag',
        variant=ActionVariant.PRIMARY,
        dialog={
            'title': 'Auftrag aus diesem Angebot erzeugen?',
            'description': 'Kopiert Daten und erstellt einen Auftrag (Entwurf). ',
            'form_submit_text': 'Auftrag erzeugen',
        }, # type: ignore
    )
    def detail_in_auftrag(self, request, form, object_id):
        """Umwandlung in einen Auftrag, Regelfall nach Annahme des Angebots,
        in der Primärfarbe."""
        return self._umwandeln_als_detailaktion(
            request, object_id, BelegTyp.AUFTRAG, 'Auftrag')

    @unfold_action(
        description='Angebot duplizieren',
        icon='content_copy',
        permissions=['duplizieren'],
        url_path='duplizieren',
        dialog={
            'title': 'Angebot duplizieren?',
            'description': 'Es entsteht ein neues Angebot als Entwurf, mit '
                           'denselben Angaben und Positionen. Seine eigene '
                           'Nummer bekommt es beim Versenden. Dieses '
                           'Angebot bleibt, wie es ist.',
            'form_submit_text': 'Duplizieren',
        }, # type: ignore
    )
    def detail_duplizieren(self, request, form, object_id):
        return self._duplizieren_als_detailaktion(request, object_id)


class AuftragspositionInline(BelegpositionInline):
    """Positionen mit Spalte "Abgerechnet", damit die bereits berechnete
    Menge vor dem Festschreiben sichtbar ist (``MengeUeberschritten``)."""

    fields = [*BelegpositionInline.fields, 'stand']
    readonly_fields = [*BelegpositionInline.readonly_fields, 'stand']

    @admin.display(description='Abgerechnet')
    def stand(self, position):
        """Leer an einer ungespeicherten Zeile."""
        if position is None or position.pk is None:
            return ''
        return position.abrechnungsstand


@admin.register(Auftrag)
class AuftragAdmin(BelegAdmin):
    typ = BelegTyp.AUFTRAG
    inlines = [AuftragspositionInline]
    actions = ['action_festschreiben', 'action_in_lieferschein', 'action_in_rechnung']

    #: Akte als erste Spalte, weil meist der Stand eines Auftrags gesucht
    #: wird.
    list_display = ['akte', 'bezeichnung', 'projekt_zeile', 'empfaenger_zeile',
                    'belegdatum', 'summe_brutto', 'dokument', 'schloss']
    #: Explizit gesetzt, weil Django sonst die erste Spalte ("akte") auf das
    #: Formular verlinkt und verschachtelte Links entstünden.
    list_display_links = ['bezeichnung']
    list_filter = ['status', 'belegdatum', 'nachtrag_zu']

    @admin.display(description='Akte')
    def akte(self, beleg):
        """Link auf die Auftragsakte über die Registry, ohne Import aus
        ``auswertung``. Ohne registrierte Akte (App fehlt) bleibt die Spalte
        leer."""
        url = erweiterungen.akte_url('auftrag', beleg.pk)
        if url is None:
            return ''
        return format_html(
            '<a href="{}" class="text-primary-600 dark:text-primary-500">'
            'ansehen</a>', url)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'nachtrag_zu', 'projekt')

    def get_fieldsets(self, request, obj=None):  # type: ignore[override]
        """Stellt "Nachtrag zu" aus dem Statusblock nach vorn, weil es
        eingegeben wird; auch beim Anlegen."""
        felder = super().get_fieldsets(request, obj)
        if obj is None:
            erweitert = list(felder)
            erweitert.insert(1, ('Auftrag', {'fields': ['nachtrag_zu']}))
            return erweitert

        ohne = [
            (titel, {**optionen,
                     'fields': self._ohne_felder(optionen['fields'],
                                                 {'nachtrag_zu'})})
            for titel, optionen in felder
        ]
        ohne.insert(1, ('Auftrag', {
            'fields': ['nachtrag_zu'],
            'description': 'Leer beim Hauptauftrag. Bei einem Nachtrag der '
                           'Auftrag, zu dem er gehört. Dann erscheint '
                           'er in der Projektakte unter "Auftrag und '
                           'Nachträge" und zählt dort zur Auftragssumme.',
        }))
        return ohne

    # Festschreiben, weil der Auftrag nicht versendet wird; er ist die
    # Vorgabe im Projekt. ``detail_pdf`` erzeugt die Auftragsbestätigung.
    actions_detail = [
        'detail_akte', 'detail_festschreiben', 'detail_pdf',
        weitere('detail_nachtrag', 'detail_in_lieferschein',
                'detail_in_rechnung', 'detail_wiedereroeffnen'),
    ]

    #: Zugesagter Termin ohne steuerliche Bedeutung.
    LEISTUNGSFELDER = {
        'leistungsdatum': (
            'Ausführung ab',
            'Optionaler Leistungszeitraum. Keine steuerliche Pflichtangabe.',
        ),
        'leistungsdatum_bis': ('Ausführung bis', ''),
    }

    @unfold_action(
        description='Auftragsakte',
        icon='folder_open',
        permissions=['view'],
        url_path='akte',
    ) # type: ignore
    def detail_akte(self, request, object_id):
        """Link vom Formular auf die Akte über den URL-Namen, ohne Import,
        weil faktura nicht von ``auswertung`` abhängen darf."""
        return redirect('auftragsakte', pk=object_id)

    @unfold_action(
        description='Nachtrag anlegen',
        icon='playlist_add',
        permissions=['nachtragsfaehig'],
        url_path='nachtrag',
        dialog={
            'title': 'Nachtrag zu diesem Auftrag anlegen?',
            'description': 'Es entsteht ein leerer Auftrag, der auf '
                           'diesen verweist; Empfänger und '
                           'Konditionen werden übernommen, Positionen '
                           'sind leer. In der Projektakte erscheint er '
                           'unter "Auftrag und Nachträge" und zählt zur '
                           'Auftragssumme.',
            'form_submit_text': 'Nachtrag anlegen',
        }, # type: ignore
    )
    def detail_nachtrag(self, request, form, object_id):
        """Legt vom Auftrag aus einen Nachtrag an und öffnet ihn."""
        try:
            nachtrag = services.nachtrag_anlegen(beleg_id=object_id)
        except services.FakturaError as fehler:
            self.message_user(request, str(fehler), level=messages.ERROR)
            return self._zurueck_zum_beleg(request, object_id)

        self.message_user(
            request,
            f'{nachtrag.betreff} angelegt; jetzt die Positionen eintragen.',
            level=messages.SUCCESS)
        return redirect('admin:faktura_auftrag_change',
                        nachtrag.pk)

    def has_nachtragsfaehig_permission(self, request, object_id=None):
        """Nur an einem festgeschriebenen Hauptauftrag, nicht an einem
        Nachtrag, weil Nachträge nicht verschachtelt werden."""
        if not super().has_change_permission(request):
            return False

        beleg = self._beleg_oder_none(object_id)
        if beleg is None:
            return True
        return (beleg.status == BelegStatus.FESTGESCHRIEBEN
                and not beleg.ist_nachtrag)

    @admin.action(description='Lieferschein erzeugen')
    def action_in_lieferschein(self, request, queryset):
        self._umwandeln(request, queryset, BelegTyp.LIEFERSCHEIN, 'Lieferschein')

    @unfold_action(
        description='Lieferschein erzeugen',
        icon='local_shipping',
        permissions=['nachgelagert'],
        url_path='in-lieferschein',
        dialog={
            'title': 'Lieferschein aus diesem Auftrag erzeugen?',
            'description': 'Positionen werden ohne Preise kopiert',
            'form_submit_text': 'Lieferschein erzeugen',
        }, # type: ignore
    )
    def detail_in_lieferschein(self, request, form, object_id):
        return self._umwandeln_als_detailaktion(
            request, object_id, BelegTyp.LIEFERSCHEIN, 'Lieferschein')


@admin.register(Lieferschein)
class LieferscheinAdmin(BelegAdmin):
    """Lieferschein ohne Preise und Steuer in Liste und Formular, weil er
    kein Wertbeleg ist und beim Kunden keine Kalkulation zeigen soll."""

    typ = BelegTyp.LIEFERSCHEIN
    inlines = [LieferpositionInline]

    actions_detail = [
        'detail_versenden', 'detail_pdf',
        weitere('detail_erneut_versenden', 'detail_in_rechnung'),
    ]

    #: Das Lieferdatum belegt das Leistungsdatum der Rechnung. Ohne
    #: Bis-Datum, weil an einem Tag geliefert wird.
    LEISTUNGSFELDER = {
        'leistungsdatum': (
            'Lieferdatum',
            'Der Tag der Lieferung. Er belegt später das Leistungsdatum '
            'der Rechnung.',
        ),
        'leistungsdatum_bis': ('Lieferung bis', ''),
    }
    list_display = ['bezeichnung', 'empfaenger_zeile', 'belegdatum',
                    'dokument', 'schloss']
    actions = ['action_festschreiben', 'action_in_rechnung']

    fieldsets = [
        ('Info', {
            'fields': [('projekt', 'kunde'), 'betreff'],
            'description': DESCRIPTION_TEXT,
        }),
        ('Empfänger', {'fields': ['empfaenger']}),
        ('Termine', {'fields': [('belegdatum', 'leistungsdatum')]}),
        ('Texte', {
            'fields': ['kopftext', 'fusstext'],
            'classes': ['collapse'],
        }),
        ('Status', {'fields': ['status', 'nummer', 'vorgaenger',
                               ('festgeschrieben_am', 'festgeschrieben_von'),
                               'dokumentnachweis', 'archivverweis']}),
    ]

    #: Eigene Fieldsets auch zum Anlegen, sonst erschienen Felder der
    #: E-Rechnung, die nach dem Speichern fehlen. ``stammdaten_uebernehmen()``
    #: füllt sie trotzdem, weil eine daraus entstehende Rechnung sie braucht.
    add_fieldsets = [
        (None, {
            'fields': [('projekt', 'kunde'), 'betreff'],
            'description': DESCRIPTION_TEXT,
        }),
        ('Empfänger', {
            'fields': ['empfaenger'],
            'description': 'Wird beim Auswählen des Kunden gefüllt, falls es '
                           'leer ist, und erscheint zeilengetreu im '
                           'Anschriftfeld.',
        }),
        ('Termine', {'fields': [('belegdatum', 'leistungsdatum')]}),
        ('Texte', {
            'fields': ['kopftext', 'fusstext'],
            'classes': ['collapse'],
        }),
    ]


@admin.register(Stornorechnung)
class StornorechnungAdmin(BelegAdmin):
    """Stornorechnungen, angelegt nur über die Aktion an der Rechnung."""

    typ = BelegTyp.STORNO
    actions = []

    def has_add_permission(self, request):
        return False


@admin.register(Rechnungskorrektur)
class RechnungskorrekturAdmin(BelegAdmin):
    """Nachträglicher Nachlass; die Ausgangsrechnung bleibt bestehen."""

    typ = BelegTyp.GUTSCHRIFT
    actions = ['action_festschreiben']
    actions_detail = ['detail_versenden', 'detail_pdf',
                      weitere('detail_erneut_versenden',
                              'detail_nachlass_stornieren')]

    def has_add_permission(self, request):
        # Nur über die Aktion an der Rechnung, damit der Bezug gesetzt ist.
        return False

    @unfold_action(
        description='Nachlass stornieren',
        icon='undo',
        permissions=['nachgelagert'],
        url_path='stornieren',
        variant=ActionVariant.DANGER,
        dialog={
            'title': 'Nachlass stornieren?',
            'description': 'Erzeugt eine Stornorechnung, die diese '
                           'Rechnungskorrektur aufhebt; die Forderung der '
                           'Rechnung steigt wieder um den Nachlass. Hat der '
                           'Kunde den Nachlass bekommen, schicken Sie ihm '
                           'auch das Storno. Danach lässt sich die Rechnung '
                           'stornieren.',
            'form_submit_text': 'Stornieren',
        }, # type: ignore
    )
    def detail_nachlass_stornieren(self, request, form, object_id):
        """Storniert bei einer fehlerhaften Rechnung mit Nachlass zuerst den
        Nachlass, dann die Rechnung, je mit eigenem Storno
        (``services.nachlass_stornieren``)."""
        try:
            storno = services.nachlass_stornieren(
                beleg_id=object_id, benutzer=request.user)
        except services.FakturaError as exc:
            self.message_user(request, str(exc), messages.ERROR)
        else:
            korrektur = storno.vorgaenger
            self.log_change(request, korrektur,
                            f'Storniert durch {storno.nummer}.')
            self.message_user(
                request,
                format_html(
                    '{} erzeugt. Hat der Kunde den Nachlass bekommen, '
                    'schicken Sie ihm auch dieses Storno. Die Rechnung '
                    'lässt sich jetzt stornieren.',
                    verweis_auf(storno)),
                messages.SUCCESS,
            )
        return self._zurueck_zum_beleg(request, object_id)


@admin.register(Mahnung)
class MahnungAdmin(BelegAdmin):
    """Mahnung, ein Brief zu einer Rechnung und kein Leistungsbeleg.

    Eigene Fieldsets: oben gemahnte Rechnung und Stufe, dann Empfänger, Frist
    und Brieftext, darunter die Aufstellung mit Bezeichnung und Betrag. Kunde
    und Projekt kommen von der Rechnung und sind nicht änderbar; die
    USt-IdNr. entfällt.
    """

    typ = BelegTyp.MAHNUNG
    inlines = [MahnpositionInline]
    list_display = ['bezeichnung', 'mahnstufe', 'empfaenger_zeile',
                    'belegdatum', 'summe_brutto', 'schloss']
    list_filter = ['mahnstufe', 'status']
    actions = ['action_festschreiben']

    fieldsets = [
        (None, {
            'fields': [('vorgaenger', 'mahnstufe'), ('kunde', 'projekt'),
                       'betreff'],
            'description': 'Ein Wechsel der Stufe zieht beim Sichern den '
                           'Text und die Mahngebühr mit, solange beide '
                           'nicht von Hand geändert sind.',
        }),
        ('Empfänger', {'fields': [('empfaenger', 'empfaenger_email')]}),
        # Datum, Frist und Gegenstand zusammen. Ohne Summen nach
        # Steuersätzen, weil die Mahnung keine Steuer ausweist.
        ('Frist', {'fields': [('belegdatum', 'zahlungsziel_tage'),
                              ('zahlbar_bis_anzeige', 'gesamtbetrag')]}),
        ('Text', {'fields': ['kopftext', 'fusstext']}),
        ('Status', {
            'fields': ['status', 'nummer',
                       ('festgeschrieben_am', 'festgeschrieben_von'),
                       'dokumentnachweis', 'archivverweis'],
            'classes': ['tab'],
        }),
    ]

    #: Abweichende Beschriftungen gegenüber der Rechnung.
    BESCHRIFTUNGEN = {
        'vorgaenger': 'Gemahnte Rechnung',
        'zahlungsziel_tage': 'Frist (Tage)',
        'kopftext': 'Text über der Aufstellung',
        'fusstext': 'Text unter der Aufstellung',
    }

    def has_add_permission(self, request):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [*super().get_readonly_fields(request, obj), 'kunde', 'projekt',
                'zahlbar_bis_anzeige', 'gesamtbetrag']

    @admin.display(description='Zahlbar bis')
    def zahlbar_bis_anzeige(self, beleg):
        """Fälligkeitsdatum, schon am Entwurf, weil der Brief darauf
        verweist. Berechnet aus dem gespeicherten Stand, nach einer Änderung
        der Frist also erst nach dem Speichern."""
        datum = beleg.zahlbar_bis if beleg.pk else None
        return f'{datum:%d.%m.%Y}' if datum else '-'

    @admin.display(description='Offener Gesamtbetrag')
    def gesamtbetrag(self, beleg):
        if beleg.pk is None:
            return '-'
        return formate.geld_mit_waehrung(services.belegsummen(beleg).brutto)

    def get_form(self, request, obj=None, **kwargs):
        """Beschriftung über ``labels``, damit auch das schreibgeschützte Feld
        "Gemahnte Rechnung" heißt (siehe ``FormularMixin.get_form``). Ohne
        BT-Nummern, weil die Mahnung kein Steuerbeleg ist."""
        kwargs.setdefault('labels', self.BESCHRIFTUNGEN)
        return super().get_form(request, obj, **kwargs)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        """Die Stufe ist Pflicht, ohne leere Option."""
        feld = super().formfield_for_dbfield(db_field, request, **kwargs)
        if feld is not None and db_field.name == 'mahnstufe':
            feld.required = True
            feld.choices = [(wert, text) for wert, text in feld.choices
                            if wert != '']
        return feld

    def save_related(self, request, form, formsets, change):
        """Speichert erst die Positionen, dann den Abgleich, damit das
        Formular die angepasste Gebühr nicht überschreibt."""
        super().save_related(request, form, formsets, change)
        if change and 'mahnstufe' in form.changed_data:
            services.mahnstufe_angleichen(
                mahnung=form.instance,
                alte_stufe=form.initial.get('mahnstufe'),
                kopftext_geaendert='kopftext' in form.changed_data,
            )
