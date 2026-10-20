"""Fieldsets, Beschriftungen und Widgets der Belegmaske, je nach Belegart und
Zustand gekürzt."""


from django.contrib import admin
from django.contrib.admin.exceptions import NotRegistered
from django.db.models import Q
from django.urls import reverse
from django.utils.text import capfirst
from django.utils.timezone import localdate
from unfold.widgets import UnfoldAdminTextareaWidget

from ..facturx import BT_BELEG, mit_bt
from ..forms import (
    TextfeldMitVorlagen,
)
from ..models import (
    BelegTyp,
    Projekt,
    Rechnungsart,
    Textbaustein,
    TextbausteinVerwendung,
)
from .gemeinsam import (
    DESCRIPTION_TEXT,
)


class FormularMixin:
    """Fieldsets, Beschriftungen und Widgets der Belegmaske."""


    #: Beschriftung und Hilfetext von leistungsdatum/_bis in dieser Belegart.
    #: Die Vorgabe gilt für Steuerbelege; Angebot, Auftrag und Lieferschein
    #: setzen eigene, weil dort keine Pflicht nach § 14 UStG besteht.
    #:
    #: Bei Steuerbelegen ist das Paar der Zeitraum; das Leistungsdatum hat
    #: ein eigenes Feld.
    LEISTUNGSFELDER = {
        'leistungsdatum': (
            'Leistung von',
            'Leistungsdatum: Pflicht (§ 14 Abs. 4 Nr. 6 UStG), der Tag, '
            'an dem die Leistung vollendet bzw. abgenommen ist. Leistung '
            'von/bis: freiwillig, der Zeitraum, in dem geleistet wurde.',
        ),
        'leistungsdatum_bis': ('Leistung bis', ''),
    }

    #: Belegarten, die als E-Rechnung versendet werden; nur sie zeigen die
    #: BT-Nummern an den Feldern.
    @property
    def mit_bt_nummern(self) -> bool:
        return self.typ in BelegTyp.steuerbelege()

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        """Beschriftet die Terminfelder nach Belegart und setzt das Widget für
        Textbausteine, ohne Recht darauf ein einfaches Textfeld."""
        feld = super().formfield_for_dbfield(db_field, request, **kwargs)
        if feld is None:
            return feld

        angaben = self.LEISTUNGSFELDER.get(db_field.name)
        if angaben:
            feld.help_text = angaben[1]
            # Der Hinweis steht als eigene Zeile unter den beiden Feldern
            # (``termin_hinweis``).
            if db_field.name == 'leistungsdatum':
                feld.help_text = ''
        # Aus dem Modell neu gebildet, weil ``feld.label`` schon die
        # Beschriftung aus ``Meta.labels`` (siehe ``get_form``) mit BT-Nummer
        # enthält; angehängt stünde sie doppelt ("Projekt (BT-11) (BT-11)").
        if db_field.name in BT_BELEG or db_field.name in self.LEISTUNGSFELDER:
            feld.label = self._beschriftung(db_field.name,
                                            capfirst(db_field.verbose_name))

        if isinstance(feld.widget, TextfeldMitVorlagen):
            if self._darf_bausteine_sehen(request):
                # Eine eigene Instanz je Aufruf, weil alle Belegarten das
                # Widget aus ``BelegForm.Meta.widgets`` teilen.
                feld.widget = TextfeldMitVorlagen(
                    TextbausteinVerwendung.BELEGTEXT,
                    attrs=feld.widget.attrs,
                    belegart=self.typ or '',
                )
            else:
                feld.widget = UnfoldAdminTextareaWidget(
                    attrs=feld.widget.attrs)
        return feld

    @admin.display(description='')
    def termin_hinweis(self, beleg):
        """Erklärung zum Ausführungszeitraum unter den Datumsfeldern."""
        return self.LEISTUNGSFELDER.get('leistungsdatum', ('', ''))[1]

    def _darf_bausteine_sehen(self, request):
        """Fragt ``has_view_permission`` des Admins der Textbausteine."""
        try:
            baustein_admin = self.admin_site.get_model_admin(Textbaustein)
        except NotRegistered:
            return False
        return baustein_admin.has_view_permission(request)

    fieldsets = [
        ('Info', {
            'fields': [('projekt', 'kunde'), ('betreff', 'bestellnummer')],
            'description': DESCRIPTION_TEXT,
        }),
        ('Empfänger', {
            'fields': [('empfaenger', 'empfaenger_email'),
                       ('empfaenger_ust_id', 'steuerfall')],
            'description': 'Erscheint zeilengetreu im Anschriftfeld. '
                           'Eine spätere Adressänderung beim '
                           'Kunden verändert den Beleg nicht.',
        }),
        ('Termine', {
            'fields': [('belegdatum', 'steuerliches_leistungsdatum'),
                       ('leistungsdatum', 'leistungsdatum_bis'),
                       'termin_hinweis', 'zahlungsziel_tage'],
        }),
        # Ab hier Tabs: oben die Felder zum Schreiben, darunter die
        # Positionen. Ein Tab zeigt die Zahl seiner Fehler.
        ('Texte', {
            'fields': ['kopftext', 'fusstext'],
            'classes': ['tab'],
        }),
        ('E-Rechnung', {
            'fields': ['empfaenger_name', 'empfaenger_strasse',
                       ('empfaenger_plz', 'empfaenger_ort'), 'empfaenger_land',
                       'leitweg_id'],
            'classes': ['tab'],
            'description': 'Die E-Rechnung verlangt die Anschrift '
                           'strukturiert und ist redundant zum '
                           'Empfängerfeld oben, das allein auf dem Beleg '
                           'erscheint. Beides kommt aus den Stammdaten des '
                           'Kunden; hier steht es, um einen einzelnen Beleg '
                           'abweichend zu adressieren.',
        }),
        ('Status', {
            'fields': ['status', 'nummer', 'vorgaenger', 'nachtrag_zu',
                       ('festgeschrieben_am', 'festgeschrieben_von'),
                       ('versendet_am', 'versendet_an'),
                       'aenderungsvermerk',
                       'faellig_am', 'summenaufstellung', 'dokumentnachweis',
                       'archivverweis'],
            'classes': ['tab'],
        }),
    ]

    add_fieldsets = [
        (None, {
            'fields': [('projekt', 'kunde'), ('betreff', 'bestellnummer')],
            'description': DESCRIPTION_TEXT,
        }),
        ('Empfänger', {
            'fields': [('empfaenger', 'empfaenger_email'),
                       ('empfaenger_ust_id', 'steuerfall')],
            'description': 'Wird beim Auswählen des Kunden gefüllt, wenn es '
                           'leer ist. Der Text erscheint zeilengetreu im '
                           'Anschriftfeld. Eine spätere Adressänderung beim Kunden '
                           'verändert den Beleg nicht mehr.',
        }),
        ('Termine', {
            'fields': [('belegdatum', 'steuerliches_leistungsdatum'),
                       ('leistungsdatum', 'leistungsdatum_bis'),
                       'termin_hinweis', 'zahlungsziel_tage'],
        }),
        ('Texte', {
            'fields': ['kopftext', 'fusstext'],
            'classes': ['tab'],
        }),
        # Auch beim Anlegen; leere Felder werden beim Speichern aus den
        # Stammdaten gefüllt.
        ('E-Rechnung', {
            'fields': ['empfaenger_name', 'empfaenger_strasse',
                       ('empfaenger_plz', 'empfaenger_ort'), 'empfaenger_land',
                       'leitweg_id'],
            'description': 'Die E-Rechnung verlangt die Anschrift '
                           'strukturiert und ist redundant zum '
                           'Empfängerfeld oben, das allein auf dem Beleg '
                           'erscheint. Leere Felder füllt das System beim '
                           'Sichern aus den Stammdaten.',
            'classes': ['tab'],
        }),
    ]

    def get_changeform_initial_data(self, request):
        """Belegdatum beim Anlegen mit heute vorbelegt; das Festschreiben
        ändert es nicht."""
        vorgabe = super().get_changeform_initial_data(request)
        vorgabe.setdefault('belegdatum', localdate())
        return vorgabe

    #: Inhalt des Tabs "E-Rechnung", nur an Steuerbelegen. Die Werte kommen
    #: aus den Stammdaten und werden beim Umwandeln übernommen.
    E_RECHNUNGSFELDER = frozenset({
        'empfaenger_name', 'empfaenger_strasse', 'empfaenger_plz',
        'empfaenger_ort', 'empfaenger_land', 'leitweg_id',
    })

    def _gekuerzt(self, fieldsets, zu_streichen):
        """Streicht Felder und lässt keinen leeren Block stehen."""
        gekuerzt = [
            (titel, {**optionen,
                     'fields': self._ohne_felder(optionen['fields'],
                                                 zu_streichen)})
            for titel, optionen in fieldsets
        ]
        return [(titel, optionen) for titel, optionen in gekuerzt
                if optionen['fields']]

    def get_fieldsets(self, request, obj=None):  # type: ignore[override]
        """Eigene Fieldsets zum Anlegen und Ändern (wie Djangos UserAdmin),
        ohne Felder, die hier keinen Wert haben:

        * "Zahlbar bis" nur, wo aus dem Zahlungsziel ein Datum wird.
        * "Nachtrag zu" nur am Auftrag.
        * Dokumentverweis nicht am Entwurf, weil er den gespeicherten Stand
          zeigte.
        * Dokument, Archiv und Versand nicht bei Belegarten ohne Dokument.
        * Der Tab "E-Rechnung" nur an Steuerbelegen.

        Neu aufgebaut, weil ``super().get_fieldsets`` das Klassenattribut
        selbst liefert und nicht verändert werden darf.
        """
        if obj is None:
            # Beim Anlegen kennt der Menüpunkt die Belegart (``self.typ``).
            if self.typ and self.typ not in BelegTyp.steuerbelege():
                return self._gekuerzt(
                    self.add_fieldsets,
                    self.E_RECHNUNGSFELDER | {'steuerliches_leistungsdatum'})
            if getattr(self, 'rechnungsart', None) == Rechnungsart.ABSCHLAG:
                return self._gekuerzt(self.add_fieldsets,
                                      {'steuerliches_leistungsdatum'})
            return self.add_fieldsets

        zu_streichen = set()
        # Leistungsdatum (BT-72) nicht am Angebot und nicht am Abschlag, der
        # eine Anzahlung ist.
        if obj.typ not in BelegTyp.steuerbelege() or obj.ist_anzahlung:
            zu_streichen.add('steuerliches_leistungsdatum')
        if obj.typ not in BelegTyp.mit_zahlungsziel():
            zu_streichen.add('faellig_am')

        if obj.typ != BelegTyp.AUFTRAG:
            zu_streichen.add('nachtrag_zu')

        if obj.ist_aenderbar:
            zu_streichen |= {'dokumentnachweis', 'archivverweis'}

        if obj.typ not in BelegTyp.mit_dokument():
            zu_streichen |= {'dokumentnachweis', 'archivverweis',
                             'versendet_am', 'versendet_an'}

        if obj.typ not in BelegTyp.steuerbelege():
            zu_streichen |= self.E_RECHNUNGSFELDER

        if not zu_streichen:
            return super().get_fieldsets(request, obj)

        return self._gekuerzt(super().get_fieldsets(request, obj),
                              zu_streichen)

    @staticmethod
    def _ohne_felder(felder, namen):
        """Entfernt Feldnamen, auch aus Tupeln einer Zeile; die übrigen
        Felder der Zeile bleiben."""
        ergebnis = []
        for eintrag in felder:
            if isinstance(eintrag, (tuple, list)):
                rest = [f for f in eintrag if f not in namen]
                if len(rest) == 1:
                    ergebnis.append(rest[0])
                elif rest:
                    ergebnis.append(tuple(rest))
            elif eintrag not in namen:
                ergebnis.append(eintrag)
        return ergebnis

    def get_inline_instances(self, request, obj=None):
        """Setzt an den Inlines, ob BT-Nummern und die Checkbox "Optional"
        erscheinen. Die Instanzen entstehen je Aufruf neu; das Attribut gilt
        nur für diese Maske."""
        instanzen = super().get_inline_instances(request, obj)
        for inline in instanzen:
            inline.mit_bt_nummern = self.mit_bt_nummern
            inline.mit_optionen = self.typ in BelegTyp.mit_optionen()
        return instanzen

    def _beschriftung(self, feldname: str, vorgabe: str) -> str:
        """Beschriftung eines Belegfelds in dieser Belegart: aus
        ``LEISTUNGSFELDER``, sonst die Vorgabe, bei Steuerbelegen mit
        BT-Nummer."""
        angaben = self.LEISTUNGSFELDER.get(feldname)
        beschriftung = angaben[0] if angaben else vorgabe
        if self.mit_bt_nummern:
            beschriftung = mit_bt(beschriftung, feldname, BT_BELEG)
        return beschriftung

    def get_form(self, request, obj=None, **kwargs):
        """Beim Anlegen sind die Empfängerfelder optional; leer werden sie aus
        den Stammdaten gefüllt.

        ``labels`` für die Read-only-Ansicht: Readonly-Felder beschriftet
        Django über das Modell und nicht über ``formfield_for_dbfield``, es
        sei denn, ``Meta.labels`` enthält sie. Sonst fehlten die BT-Nummern
        an der festgeschriebenen Rechnung.
        """
        felder = {f.name: f for f in self.model._meta.fields}
        kwargs.setdefault('labels', {
            name: self._beschriftung(name, str(felder[name].verbose_name))
            for name in {*BT_BELEG, *self.LEISTUNGSFELDER} if name in felder
        })
        formular = super().get_form(request, obj, **kwargs)
        if obj is None:
            for name in self.UEBERNAHMEFELDER:
                if name in formular.base_fields:
                    formular.base_fields[name].required = False
        return formular


    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Setzt ``data-stammdaten-url`` an Kunden- und Projektfeld für das
        Übernahme-Skript, je Belegart eine eigene URL.

        Abgeschlossene Projekte fehlen in der Auswahl, außer dem gespeicherten.
        """
        feld = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if feld is None:
            return feld

        if db_field.name in ('projekt', 'kunde'):
            feld.widget.attrs['data-stammdaten-url'] = reverse(
                f'admin:{self.model._meta.app_label}_'
                f'{self.model._meta.model_name}_kundendaten'
            )

        if db_field.name == 'projekt':
            beleg = self._beleg_der_seite(request)
            offen = Q(abgeschlossen=False)
            if beleg is not None and beleg.projekt_id:
                offen |= Q(pk=beleg.projekt_id)
            feld.queryset = Projekt.objects.filter(offen).select_related('kunde')

        return feld
