"""Formular der Erfassung: Felder, Auswahllisten, Verhalten nach dem
Speichern."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django import forms
from django.contrib import admin
from django.db.models import Q
from django.utils.html import format_html
from unfold.widgets import INPUT_CLASSES

from faktura.models import (
    Belegposition,
    BelegStatus,
    BelegTyp,
    Katalogposition,
    Projekt,
)

from ..models import (
    Erfassungszeile,
)
from .gemeinsam import (
    AuftragspositionsAuswahl,
    AuftragspositionsWidget,
    LeistungsAuswahl,
    PersonenAuswahl,
)


class UhrzeitWidget(forms.TimeInput):
    """Uhrzeitfeld des Browsers (``<input type="time">``).

    Eingabe als "0830", Stunde und Minute per Pfeiltasten, auf dem Telefon
    als Uhrzeitrad. Der Browser sendet unabhängig von der Anzeigesprache
    "08:30". Verworfen: Djangos Uhr-Widget mit vier festen Zeiten ("Jetzt,
    Mitternacht, 6 Uhr, Mittag").

    Ohne ``step`` für Fünferschritte, weil Chrome und Edge in der Auswahl
    trotzdem alle Minuten zeigen und nur die Pfeiltasten in Fünferschritten
    springen (ausprobiert).
    """

    input_type = 'time'

    def __init__(self):
        super().__init__(format='%H:%M',
                         attrs={'class': ' '.join(INPUT_CLASSES)})


class FormularMixin:
    """Mixin für das Erfassungsformular, auf schnelle Eingabe ausgelegt.

    Felder je Leistungsart, Übernahme von Werten in die nächste Zeile,
    "Sichern und neu hinzufügen" ohne die Maske zu verlassen.
    """


    # ── Formular ─────────────────────────────────────────────────────────

    #: Sichtbarkeit der Felder; Unfold setzt die Ausdrücke als ``x-show``
    #: (Alpine). ``erfassungsart()`` steht in erfassungsart.js, weil Alpine
    #: nur die Feldwerte sieht, nicht die Art der gewählten Leistung. Eine
    #: Anfahrt hat kein "von". Eine Pauschale nimmt Uhrzeiten als Aufwand
    #: für das Controlling (``Erfassungszeile._pauschale_angleichen``), aber
    #: keine Menge, die ist immer 1.
    conditional_fields = {
        # Projekt vor Position, weil die Positionen auf das Projekt
        # eingeschränkt werden.
        'auftragsposition': 'projekt',
        # Mit Position kein Katalog (``_pruefe_grundlage``);
        # erfassungsauswahl.js leert das Feld, weil ein ausgeblendetes Feld
        # sonst mitgesendet würde.
        'leistung': 'projekt && !auftragsposition',
        'von': "(auftragsposition || leistung) && "
               "['zeit', 'pauschale'].includes(erfassungsart())",
        'bis': "(auftragsposition || leistung) && "
               "['zeit', 'pauschale'].includes(erfassungsart())",
        'menge': "(auftragsposition || leistung) && erfassungsart() == 'menge'",
        'hinweis_pauschale': "(auftragsposition || leistung) && "
                             "erfassungsart() == 'pauschale'",
    }

    #: Hinweistext unter Von und Bis als readonly field, damit Unfold ihn wie
    #: ein Feld ein- und ausblendet.
    readonly_fields = ['hinweis_pauschale']

    @admin.display(description='')
    def hinweis_pauschale(self, obj=None):
        """Hinweis an den Uhrzeitfeldern, dass eine Zeile mit Uhrzeiten auf
        einer Pauschale nicht abrechenbar wird
        (``Erfassungszeile._pauschale_angleichen``)."""
        return format_html(
            '<span class="pw-hinweis">{}</span>',
            'Auftragspositionen vom Typ pauschal mit Zeitangaben erhalten '
            'den Zustand „Nicht abrechenbar“. Für die Abrechnung einmal '
            'ohne Zeitangaben erfassen.')

    def get_fields(self, request, obj=None):
        """Person und "abrechenbar" nur mit dem Recht, für andere zu erfassen.

        Felder, die nicht im Formular stehen, lassen sich auch per POST
        nicht setzen; das ist die Rechteprüfung.
        """
        felder = ['datum', 'projekt', 'auftragsposition', 'leistung',
                  ('von', 'bis'), 'hinweis_pauschale', 'menge',
                  'beschreibung']
        if self._darf_fremde(request):
            # Als erstes Feld, weil beim Abtippen eines fremden
            # Stundenzettels die Person für alle Zeilen gilt.
            felder.insert(0, 'benutzer')
            # Als letztes Feld, weil es eine kaufmännische Entscheidung ist.
            felder.append('abrechenbar')
        return felder

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Gefilterte Auswahllisten; der gespeicherte Wert bleibt jeweils
        wählbar, sonst fehlte er beim nächsten Öffnen.

        * **Projekt:** nur laufende.
        * **Leistung:** nur kontierbare Katalogpositionen.
        * **Auftragsposition:** Positionen festgeschriebener Aufträge
          laufender Projekte. Auf das gewählte Projekt engt
          erfassungsauswahl.js im Browser ein (``data-projekt``).
        """
        zeile = self._zeile_aus_adresse(request)

        if db_field.name == 'projekt':
            offen = Q(abgeschlossen=False)
            if zeile is not None and zeile.projekt_id:
                offen |= Q(pk=zeile.projekt_id)
            kwargs['queryset'] = Projekt.objects.filter(offen).select_related('kunde')

        if db_field.name == 'leistung':
            erlaubt = Q(kontierbar=True)
            if zeile is not None and zeile.leistung_id:
                erlaubt |= Q(pk=zeile.leistung_id)
            kwargs['queryset'] = Katalogposition.objects.filter(erlaubt)
            # Trägt die Erfassungsart an den Einträgen.
            kwargs['widget'] = LeistungsAuswahl()

        if db_field.name == 'auftragsposition':
            erlaubt = Q(beleg__typ=BelegTyp.AUFTRAG,
                        beleg__status=BelegStatus.FESTGESCHRIEBEN,
                        beleg__projekt__abgeschlossen=False,
                        zeilenart='leistung')
            if zeile is not None and zeile.auftragsposition_id:
                erlaubt |= Q(pk=zeile.auftragsposition_id)
            kwargs['queryset'] = (
                Belegposition.objects
                .filter(erlaubt)
                .select_related('beleg__projekt')
                .order_by('beleg__projekt__nummer', 'beleg__nummer',
                          'sortierung'))
            kwargs['form_class'] = AuftragspositionsAuswahl
            # Trägt Erfassungsart und Projekt an den Einträgen.
            kwargs['widget'] = AuftragspositionsWidget()

        if db_field.name == 'benutzer':
            # form_class überschreibt ForeignKey.formfield()s Vorgabe.
            kwargs['form_class'] = PersonenAuswahl

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    #: Symbole neben den Auswahlfeldern. Nur beim Katalog bleibt "anlegen";
    #: Projekte werden nicht in der Erfassung gepflegt.
    KNOEPFE = {
        'leistung': {'can_add_related'},
    }

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        """Blendet die Symbole an den Auswahlfeldern aus; Von und Bis erhalten
        ``UhrzeitWidget``.

        In dieser Methode, weil Django das Widget erst nach
        ``formfield_for_foreignkey`` in ``RelatedFieldWidgetWrapper``
        einpackt und die ``can_*``-Attribute zum Wrapper gehören.
        """
        if db_field.name in ('von', 'bis'):
            kwargs['widget'] = UhrzeitWidget()
        feld = super().formfield_for_dbfield(db_field, request, **kwargs)
        if feld is not None and db_field.name == 'menge':
            # Der Spinner springt um ganze Einheiten.
            feld.widget.attrs['step'] = '1'
        if feld is not None and hasattr(feld.widget, 'can_add_related'):
            erlaubt = self.KNOEPFE.get(db_field.name, set())
            for schalter in ('can_add_related', 'can_change_related',
                             'can_delete_related', 'can_view_related'):
                setattr(feld.widget, schalter, schalter in erlaubt)
        return feld

    def _zeile_aus_adresse(self, request):
        """Die bearbeitete Zeile oder None beim Anlegen."""
        kennung = (request.resolver_match.kwargs.get('object_id')
                   if request.resolver_match else None)
        if not kennung:
            return None
        return Erfassungszeile.objects.filter(pk=kennung).first()

    def save_model(self, request, obj, form, change):
        """Ohne gewählte Person gilt der angemeldete Benutzer. Hier gesetzt,
        weil der Admin nicht über den Service speichert."""
        if not obj.benutzer_id:
            obj.benutzer = request.user
        super().save_model(request, obj, form, change)

    #: Felder, die "Sichern und neu hinzufügen" in die nächste Zeile
    #: übernimmt, weil mehrere Zeilen meist zum selben Projekt gehören. Die
    #: Person nur, wo das Feld angezeigt wird. Nicht übernommen: Datum
    #: (vorbelegt mit heute) und Leistung (wechselt am häufigsten).
    UEBERNAHME_BEIM_WEITERERFASSEN = ['projekt', 'benutzer']

    def response_add(self, request, obj, post_url_continue=None):
        """Hängt die übernommenen Werte als Query-Parameter an die URL der
        nächsten Maske.

        In der URL, weil sie dort sichtbar sind, mehrere Tabs nicht stören
        und nicht in der Session liegen bleiben. Vorhandene Parameter bleiben
        erhalten, darunter ``_changelist_filters`` für die Rückkehr in die
        gefilterte Liste.
        """
        antwort = super().response_add(request, obj, post_url_continue)

        if '_addanother' not in request.POST or antwort.status_code != 302:
            return antwort

        adresse = urlsplit(antwort['Location'])
        parameter = dict(parse_qsl(adresse.query))
        for name in self.UEBERNAHME_BEIM_WEITERERFASSEN:
            # Der Primärschlüssel, weil die Vorbelegung über ihn erfolgt.
            wert = getattr(obj, f'{name}_id', getattr(obj, name, None))
            if wert is not None:
                parameter[name] = str(wert)
        antwort['Location'] = urlunsplit(
            adresse._replace(query=urlencode(parameter)))
        return antwort
