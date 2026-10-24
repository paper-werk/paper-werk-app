"""Admins für Rechnung, Abschlags-, Schluss- und Teilschlussrechnung.

Vorgänge: Leistungen übernehmen, Zahlung, Mahnung, Nachlass, Storno,
E-Rechnung neu ausstellen. Vorgänge mit Eingaben (Nachlass, Zahlung,
Neuausstellung) haben eine Zwischenseite, die Detail- und Listenaktion
gemeinsam nutzen. Buttons erscheinen nur, wo der Vorgang möglich ist.
"""


from decimal import Decimal

from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.timezone import localdate, localtime
from unfold.decorators import action as unfold_action
from unfold.enums import ActionVariant

from core import erweiterungen
from core.adminhilfen import weitere

from .. import formate, services
from ..forms import (
    NachlassForm,
    NeuausstellungForm,
    ZahlungForm,
)
from ..models import (
    Abschlagsrechnung,
    BelegStatus,
    BelegTyp,
    Rechnung,
    Rechnungsart,
    Schlussrechnung,
    Teilschlussrechnung,
)
from .beleg import BelegAdmin
from .gemeinsam import (
    SchlusspositionInline,
    VersandstandFilter,
    ZahlungsstandFilter,
    adresse_im_admin,
    verweis_auf,
)


@admin.register(Rechnung)
class RechnungAdmin(BelegAdmin):
    typ = BelegTyp.RECHNUNG
    rechnungsart = Rechnungsart.NORMAL
    #: Die Liste verlinkt auf die Akte, wie bei den Kunden; zum Formular
    #: führt dort "Rechnung bearbeiten". ``list_display_links = None``, weil
    #: die Spalte ihren Link selbst setzt und verschachtelte Links entstünden.
    list_display_links = None
    list_display = ['bezeichnung_akte', 'empfaenger_zeile', 'belegdatum',
                    'faelligkeit', 'summe_brutto', 'offener_betrag',
                    'zahlungsstand', 'versandstand', 'dokument', 'schloss']

    # Abgeleitet von BelegAdmin, damit neue Filter dort auch hier gelten.
    list_filter = [*BelegAdmin.list_filter, VersandstandFilter,
                   ZahlungsstandFilter]

    @admin.display(description='Beleg', ordering='nummer')
    def bezeichnung_akte(self, beleg):
        """Belegnummer als Link auf die Rechnungsakte, über die Registry ohne
        Import aus ``auswertung``; ohne registrierte Akte nur Text.

        Nur die Nummer, ohne Nummer "Entwurf 54", weil "Rechnung" in jeder
        Zeile Breite kostete.
        """
        text = beleg.nummer or f'Entwurf {beleg.pk}'
        url = erweiterungen.akte_url('rechnung', beleg.pk)
        if url is None:
            return text
        return format_html(
            '<a href="{}" class="font-medium text-primary-600 '
            'dark:text-primary-500">{}</a>', url, text)

    def get_queryset(self, request):
        # Vermeidet Abfragen je Zeile für die Spalte "Offen".
        return super().get_queryset(request).prefetch_related(
            'zahlungszuordnungen', services.nachlaesse_vorladen())

    def change_view(self, request, object_id, form_url='', extra_context=None):
        """Im Entwurf ein Hinweis auf fehlende optionale Zuschläge des
        Auftrags, die wie jede Option nicht automatisch übernommen werden
        (``services.optionale_zuschlaege``)."""
        beleg = self._beleg_oder_none(object_id)
        if (request.method == 'GET' and beleg is not None
                and beleg.ist_entwurf and beleg.typ == BelegTyp.RECHNUNG):
            offen = services.optionale_zuschlaege(beleg)
            if offen:
                self.message_user(request, (
                    'Optionale Zuschläge aus dem Auftrag, falls angefallen: '
                    + '; '.join(
                        f'{p.bezeichnung} '
                        f'({services.zuschlagsbeschreibung(p, [])}, '
                        f'{p.beleg.nummer})' for p in offen)
                    + '. Abgerechnet wird ein Zuschlag als eigene Zeile auf '
                      'die Position, für die er angefallen ist.'),
                    messages.INFO)
        return super().change_view(request, object_id, form_url,
                                   extra_context)

    def get_list_display(self, request):
        """Spalte "Zahlung vermerken" nur mit Recht auf Zahlungen.

        Eingefügt nach "Zahlung", damit die Spaltennummer von "Fällig" gleich
        bleibt; der Tab "Über Frist" sortiert danach (faktura/apps.py).
        """
        spalten = list(super().get_list_display(request))
        if (request.user.has_perm('faktura.add_zahlung')
                and 'zahlungsstand' in spalten):
            spalten.insert(spalten.index('zahlungsstand') + 1,
                           'zahlung_vermerken')
        return spalten

    @admin.display(description='')
    def zahlung_vermerken(self, beleg):
        """Link "Zahlung vermerken", nur bei offenem Betrag.

        Keine Unfold-Zeilenaktion (``actions_row``), weil Unfold deren Rechte
        einmal je Liste und nicht je Zeile prüft; der Button stünde sonst
        auch an Entwürfen und bezahlten Rechnungen. ``add_zahlung`` prüft
        ``get_list_display``, beim Aufruf prüft Unfold zusätzlich
        ``has_zahlung_permission`` mit der Belegnummer.
        """
        if (beleg.status != BelegStatus.FESTGESCHRIEBEN
                or self._offen(beleg) <= 0):
            return ''
        opts = self.model._meta
        return format_html(
            '<a href="{}" title="Zahlung vermerken" '
            'class="flex items-center text-primary-600 dark:text-primary-500">'
            '<span class="material-symbols-outlined">payments</span></a>',
            reverse(f'admin:{opts.app_label}_{opts.model_name}_detail_zahlung',
                    args=[beleg.pk]))

    @admin.display(description='E-Mail', ordering='versendet_am')
    def versandstand(self, beleg):
        """Datum der ersten Mail an den Kunden, sonst leer.

        Nur die Mail ist erfasst; ein Versand per Post oder Portal nach dem
        Download nicht. Die Spalte zeigt deshalb nur das Maildatum.
        """
        if beleg.versendet_am:
            return localtime(beleg.versendet_am).strftime('%d.%m.%Y')
        return ''
    actions = ['action_festschreiben', 'action_korrigieren', 'action_nachlass',
               'action_mahnen', 'action_zahlung']

    # Ohne Button "Festschreiben", weil Versenden festschreibt. Vorn Akte,
    # Versenden und PDF, alles andere in "Weitere …", dort die Zahlung zuerst.
    #
    # Als Property, weil in "Weitere …" nach der Zahlung die über
    # core.erweiterungen.belegaktion() registrierten Detailaktionen stehen
    # (etwa "Erbrachte Leistungen hinzufügen" aus erfassung), die erst zur
    # Laufzeit bekannt sind. ``_belegaktionen_anhaengen`` setzt ihre Methoden
    # einmalig auf die Klasse, weil Unfold sie über ``getattr(self, name)``
    # sucht.
    @property
    def actions_detail(self):
        self._belegaktionen_anhaengen()
        return [
            'detail_akte', 'detail_versenden', 'detail_pdf',
            weitere('detail_zahlung',
                    *erweiterungen.belegaktionen(self.typ),
                    'detail_erneut_versenden', 'detail_mahnen',
                    'detail_nachlass', 'detail_erechnung_neu',
                    'detail_korrigieren', 'detail_duplizieren'),
        ]

    def _belegaktionen_anhaengen(self):
        """Setzt registrierte Belegaktionen als Methoden auf ``RechnungAdmin``,
        einmalig und idempotent (``hasattr`` verhindert Überschreiben).

        Der Name der Rechteprüfung kommt aus ``aktion.allowed_permissions``
        (gesetzt von ``@unfold_action(permissions=[...])``), unabhängig von
        ``name``. "detail_leistungen" prüft etwa mit
        ``permissions=['leistungen']`` und damit ``has_leistungen_permission``.
        """
        for name, (aktion, hat_recht) in erweiterungen.belegaktionen(
                self.typ).items():
            if not hasattr(RechnungAdmin, name):
                setattr(RechnungAdmin, name, aktion)
            if hat_recht is None:
                continue
            for berechtigung in getattr(aktion, 'allowed_permissions', ()):
                attributname = f'has_{berechtigung}_permission'
                if not hasattr(RechnungAdmin, attributname):
                    setattr(RechnungAdmin, attributname, hat_recht)

    @unfold_action(
        description='Rechnung duplizieren',
        icon='content_copy',
        permissions=['duplizieren'],
        url_path='duplizieren',
        dialog={
            'title': 'Rechnung duplizieren?',
            'description': 'Es entsteht eine neue Rechnung als Entwurf, mit '
                           'denselben Angaben und Positionen. Ihre eigene '
                           'Nummer bekommt sie beim Versenden. Bitte '
                           'beachten: Übernommene Positionen haben keinen '
                           'Bezug zu erfassten Leistungen; die Zeiten '
                           'bleiben auf dieser Rechnung abgerechnet. '
                           'Positionen aus Fremdleistungen werden nicht '
                           'übernommen. Beauftragte Mengen werden beim '
                           'Versenden wie immer geprüft.',
            'form_submit_text': 'Duplizieren',
        }, # type: ignore
    )
    def detail_duplizieren(self, request, form, object_id):
        """Nicht an der Schlussrechnung, siehe ``has_duplizieren_permission``
        und ``services.DUPLIZIERBAR``."""
        return self._duplizieren_als_detailaktion(request, object_id)

    @unfold_action(
        description='Rechnungsakte',
        icon='folder_open',
        permissions=['view'],
        url_path='akte',
    ) # type: ignore
    def detail_akte(self, request, object_id):
        """Link vom Formular auf die Akte über den URL-Namen, ohne Import aus
        ``auswertung``, wie beim Auftrag."""
        return redirect('rechnungsakte', pk=object_id)

    def has_mahnen_permission(self, request, object_id=None):
        """Wie ``nachgelagert``, zusätzlich mit offenem Betrag, weil eine
        bezahlte Rechnung nicht gemahnt wird."""
        if not super().has_nachgelagert_permission(request, object_id):
            return False

        beleg = self._beleg_oder_none(object_id)
        if beleg is None:
            return True
        return services.offener_betrag(beleg) > 0

    @unfold_action(
        description='Mahnung erzeugen',
        icon='notification_important',
        permissions=['mahnen'],
        url_path='mahnen',
        dialog={
            'title': 'Mahnung erzeugen?',
            'description': 'Erzeugt eine Mahnung (Entwurf)',
            'form_submit_text': 'Mahnung erzeugen',
        }, # type: ignore
    )
    def detail_mahnen(self, request, form, object_id):
        """Mit Bestätigung, damit keine Mahnung versehentlich entsteht."""
        return self._als_detailaktion(request, object_id, self.action_mahnen)

    def has_nachlass_permission(self, request, object_id=None):
        """Wie ``nachgelagert``, nicht am Abschlag, weil dort die Zahlung
        kürzt und die Schlussrechnung neu fordert."""
        if not super().has_nachgelagert_permission(request, object_id):
            return False
        beleg = self._beleg_oder_none(object_id)
        return beleg is None or beleg.rechnungsart != Rechnungsart.ABSCHLAG

    @unfold_action(
        description='Nachlass gewähren',
        icon='percent',
        permissions=['nachlass'],
        url_path='nachlass',
    ) # type: ignore
    def detail_nachlass(self, request, object_id):
        """Ruft die Zwischenseite der Listenaktion auf und gibt deren
        Response zurück, damit das Formular erscheint."""
        queryset = self.get_queryset(request).filter(pk=object_id)
        antwort = self.action_nachlass(request, queryset)
        if antwort is not None:
            return antwort

        opts = self.model._meta
        return redirect(
            f'admin:{opts.app_label}_{opts.model_name}_change', object_id
        )

    @unfold_action(
        description='Stornieren und neu schreiben',
        icon='undo',
        permissions=['nachgelagert'],
        url_path='korrigieren',
        variant=ActionVariant.DANGER,
        dialog={
            'title': 'Rechnung stornieren und neu schreiben?',
            'description': 'Erzeugt eine Stornorechnung und eine Neufassung '
                           'der Rechnung als Entwurf. Die ursprüngliche Rechnung '
                           'bleibt im Bestand. Nach Festschreibung einer Rechnung '
                           'ist dies die einzige Möglichkeit, die Rechnung zu ändern.',
            'form_submit_text': 'Stornieren',
        }, # type: ignore
    )
    def detail_korrigieren(self, request, form, object_id):
        """Rot, weil die Stornorechnung an den Kunden geht."""
        return self._als_detailaktion(
            request, object_id, self.action_korrigieren)

    @unfold_action(
        description='E-Rechnung neu ausstellen',
        icon='restart_alt',
        permissions=['erechnung_neu'],
        url_path='erechnung-neu',
    ) # type: ignore
    def detail_erechnung_neu(self, request, object_id):
        """Für eine vom Portal abgelehnte E-Rechnung: dieselbe Nummer, neue
        Dateien, Grund und Kopfangaben auf einer Zwischenseite
        (``services.erechnung_neu_ausstellen``)."""
        beleg = self._beleg_oder_none(object_id)
        if beleg is None:
            return self._zurueck_zum_beleg(request, object_id)

        if request.method == 'POST':
            formular = NeuausstellungForm(request.POST)
            if formular.is_valid():
                try:
                    neu = services.erechnung_neu_ausstellen(
                        beleg_id=beleg.pk,
                        grund=formular.cleaned_data['grund'],
                        leitweg_id=formular.cleaned_data['leitweg_id'],
                        bestellnummer=formular.cleaned_data['bestellnummer'],
                        benutzer=request.user,
                    )
                except services.FakturaError as fehler:
                    self.message_user(request, str(fehler), messages.ERROR)
                    return self._zurueck_zum_beleg(request, beleg.pk)
                self._vermerken(
                    request, neu,
                    f'E-Rechnung neu ausgestellt ({neu.erechnungsprofil}). '
                    f'Grund: {formular.cleaned_data["grund"]}')
                self.message_user(
                    request,
                    f'{neu}: E-Rechnung neu ausgestellt. Die vorige Fassung '
                    f'bleibt im Reiter „Status“ erhalten.',
                    messages.SUCCESS)
                return self._zurueck_zum_beleg(request, beleg.pk)
        else:
            formular = NeuausstellungForm(initial={
                'leitweg_id': beleg.leitweg_id,
                'bestellnummer': beleg.bestellnummer,
            })

        return render(
            request,
            'admin/faktura/erechnung_neu.html',
            {**self.admin_site.each_context(request),
             'beleg': beleg,
             'form': formular,
             'title': 'E-Rechnung neu ausstellen'},
        )

    def has_erechnung_neu_permission(self, request, object_id=None):
        """Wie die übrigen Folgevorgänge, nur wenn ein Dokument existiert."""
        if not self.has_nachgelagert_permission(request, object_id):
            return False
        beleg = self._beleg_oder_none(object_id)
        if beleg is None:
            return object_id is None
        return (beleg.status == BelegStatus.FESTGESCHRIEBEN
                and bool(beleg.pdf))

    @admin.action(description='Nachlass gewähren (Rechnung bleibt bestehen)')
    def action_nachlass(self, request, queryset):
        """Aktion mit Zwischenseite: erst das Formular, beim Absenden
        ("anwenden") der Vorgang; ``None`` führt zurück in die Liste.

        Verlangt genau eine festgeschriebene Rechnung, geprüft vor dem
        Formular.
        """
        if len(queryset) != 1:
            self.message_user(
                request,
                'Ein Nachlass wird je Rechnung einzeln gewährt: Betrag und '
                'Grund gehören zu genau einer. Bitte eine einzelne Rechnung '
                'auswählen.',
                messages.WARNING,
            )
            return None

        rechnung = queryset[0]

        if rechnung.status != BelegStatus.FESTGESCHRIEBEN:
            # Verbindlich prüft der Service; hier nur, damit das Formular
            # nicht erscheint.
            self.message_user(
                request,
                f'{rechnung}: Ein Nachlass bezieht sich auf eine '
                f'festgeschriebene Rechnung. Diese steht auf '
                f'"{rechnung.get_status_display()}".',
                messages.WARNING,
            )
            return None

        if 'anwenden' in request.POST:
            formular = NachlassForm(request.POST)
            if formular.is_valid():
                try:
                    korrektur = services.rechnungskorrektur_erstellen(
                        beleg_id=rechnung.pk,
                        betrag_netto=formular.cleaned_data['betrag_netto'],
                        grund=formular.cleaned_data['grund'],
                        steuersatz=formular.cleaned_data['steuersatz'],
                    )
                except services.FakturaError as exc:
                    self.message_user(request, f'{rechnung}: {exc}', messages.ERROR)
                else:
                    self.message_user(
                        request,
                        format_html(
                            'Rechnungskorrektur zu {} als Entwurf '
                            'angelegt: {}',
                            rechnung, verweis_auf(korrektur),
                        ),
                        messages.SUCCESS,
                    )
                    self._guthaben_melden(request, rechnung, korrektur)
                return None
        else:
            formular = NachlassForm()

        return render(
            request,
            'admin/faktura/nachlass.html',
            {**self.admin_site.each_context(request),
             'rechnung': rechnung,
             'summe': services.belegsummen(rechnung).brutto,
             'offen': services.offener_betrag(rechnung),
             'form': formular,
             'title': 'Rechnungskorrektur'},
        )

    def _guthaben_melden(self, request, rechnung, korrektur):
        """Meldet ein Guthaben, wenn der Nachlass den offenen Betrag
        übersteigt. Erstattungen bildet die Anwendung nicht ab."""
        offen = services.offener_betrag(rechnung)
        betrag = -services.belegsummen(korrektur).brutto
        if betrag > offen:
            self.message_user(
                request,
                f'Auf {rechnung} sind nur noch '
                f'{formate.geld_mit_waehrung(offen)} offen. Ist der '
                f'Nachlass festgeschrieben, hat der Kunde '
                f'{formate.geld_mit_waehrung(betrag - offen)} zu viel '
                f'bezahlt; die Erstattung erledigen Sie außerhalb von '
                f'Paper-Werk.',
                messages.WARNING,
            )

    # ── Tab "Zahlungen" ──────────────────────────────────────────────────

    def get_fieldsets(self, request, obj=None):  # type: ignore[override]
        """Ergänzt den Tab "Zahlungen", nur an festgeschriebenen Belegen."""
        felder = super().get_fieldsets(request, obj)
        if obj is None or obj.status == BelegStatus.ENTWURF:
            return felder
        return [*felder, ('Zahlungen', {
            'fields': ['zahlungsuebersicht'],
            'classes': ['tab'],
        })]

    def get_readonly_fields(self, request, obj=None):
        """Die Zahlungsübersicht als readonly field, weil Django sonst ein
        Modellfeld dieses Namens sucht."""
        return [*super().get_readonly_fields(request, obj),
                'zahlungsuebersicht']

    @admin.display(description='Zahlungseingänge')
    def zahlungsuebersicht(self, beleg):
        """Zahlungseingänge auf diese Rechnung und offener Rest. Skonto in
        eigener Spalte, weil es kein Zahlungseingang ist."""
        zuordnungen = list(
            beleg.zahlungszuordnungen.select_related('zahlung')
            .order_by('zahlung__datum', 'pk'))
        offen = services.offener_betrag(beleg)
        schluss = services.abgerechnet_in(beleg)
        gemindert = services.nachlass(beleg)
        if gemindert:
            minderung = format_html(
                ' Rechnungskorrekturen mindern die Forderung um '
                '<strong>{}</strong>.', formate.geld_mit_waehrung(gemindert))
        else:
            minderung = ''

        if not zuordnungen and schluss is not None:
            return format_html(
                '<p class="text-sm">Kein Zahlungseingang vermerkt. '
                'Abgerechnet mit <strong>{}</strong>; der Betrag wird dort '
                'gefordert.</p>', schluss)
        if not zuordnungen:
            return format_html(
                '<p class="text-sm">Noch kein Zahlungseingang '
                'vermerkt.{} Offen: <strong>{}</strong></p>',
                minderung, formate.geld_mit_waehrung(offen))

        # Unfolds CSS-Klassen wie in der Kundenakte, weil das Stylesheet
        # Tabellen zurücksetzt.
        zeilen = format_html_join(
            '',
            '<tr class="border-base-100 border-b last:border-0 '
            'dark:border-base-800">'
            '<td class="py-2 pr-6 whitespace-nowrap">{}</td>'
            '<td class="py-2 pr-6 text-right whitespace-nowrap">{}</td>'
            '<td class="py-2 pr-6 text-right whitespace-nowrap">{}</td>'
            '<td class="py-2 pr-6 text-right whitespace-nowrap">{}</td>'
            '<td class="py-2 pr-6 whitespace-nowrap">{}</td>'
            '<td class="py-2">{}</td></tr>',
            ((z.zahlung.datum.strftime('%d.%m.%Y'),
              formate.geld_mit_waehrung(z.betrag),
              formate.geld_mit_waehrung(z.skonto) if z.skonto else '–',
              formate.geld_mit_waehrung(z.kuerzung) if z.kuerzung else '–',
              z.zahlung.get_zahlungsart_display(),
              z.zahlung.verwendungszweck or '')
             for z in zuordnungen))

        return format_html(
            '<table class="text-sm w-full"><thead>'
            '<tr class="border-base-200 border-b text-font-subtle-light '
            'text-left text-xs uppercase dark:border-base-800 '
            'dark:text-font-subtle-dark">'
            '<th class="font-medium pb-2 pr-6" scope="col">Datum</th>'
            '<th class="font-medium pb-2 pr-6 text-right" scope="col">Betrag</th>'
            '<th class="font-medium pb-2 pr-6 text-right" scope="col">Skonto</th>'
            '<th class="font-medium pb-2 pr-6 text-right" scope="col">Gekürzt</th>'
            '<th class="font-medium pb-2 pr-6" scope="col">Art</th>'
            '<th class="font-medium pb-2" scope="col">Verwendungszweck</th>'
            '</tr></thead><tbody>{}</tbody></table>'
            '<p class="mt-4 text-sm">{}{}</p>',
            zeilen,
            minderung,
            (format_html('Abgerechnet mit <strong>{}</strong>; was hier '
                         'fehlte, fordert diese.', schluss)
             if schluss is not None else
             mark_safe('Die Rechnung ist <strong>ausgeglichen</strong>.')
             if offen <= 0 else
             format_html('Offen bleiben <strong>{}</strong>.',
                         formate.geld_mit_waehrung(offen))),
        )

    @admin.action(description='Zahlungseingang vermerken')
    def action_zahlung(self, request, queryset):
        """Zwischenseite für einen Zahlungseingang auf eine Rechnung,
        vorbelegt mit offenem Betrag und heute. Sammelüberweisungen verteilt
        die Zahlungsmaske."""
        if len(queryset) != 1:
            self.message_user(
                request,
                'Bitte genau eine Rechnung auswählen; ein Geldeingang '
                'gehört zu einem Beleg. Eine Überweisung über mehrere '
                'Rechnungen wird unter "Zahlungseingänge" erfasst.',
                messages.WARNING,
            )
            return None

        rechnung = queryset[0]

        if rechnung.status != BelegStatus.FESTGESCHRIEBEN:
            self.message_user(
                request,
                f'{rechnung}: Auf einen Entwurf wird nicht gezahlt. Diese '
                f'Rechnung steht auf "{rechnung.get_status_display()}".',
                messages.WARNING,
            )
            return None

        offen = services.offener_betrag(rechnung)
        # Gekürzt wird nur ein Abschlag, weil nur dort die Schlussrechnung
        # den Betrag erneut fordert (R-174).
        mit_kuerzung = rechnung.rechnungsart == Rechnungsart.ABSCHLAG

        if 'anwenden' in request.POST:
            formular = ZahlungForm(request.POST, mit_kuerzung=mit_kuerzung)
            if formular.is_valid():
                try:
                    services.zahlung_verbuchen(
                        beleg_id=rechnung.pk,
                        datum=formular.cleaned_data['datum'],
                        betrag=formular.cleaned_data['betrag'],
                        skonto=formular.cleaned_data['skonto'],
                        kuerzung=formular.cleaned_data.get(
                            'kuerzung', Decimal('0.00')),
                        zahlungsart=formular.cleaned_data['zahlungsart'],
                        verwendungszweck=formular.cleaned_data[
                            'verwendungszweck'],
                    )
                except services.FakturaError as exc:
                    self.message_user(request, f'{rechnung}: {exc}',
                                      messages.ERROR)
                else:
                    # Neu geladen, weil der Prefetch aus ``get_queryset`` die
                    # neue Zuordnung nicht enthält.
                    rest = services.offener_betrag(
                        type(rechnung).objects.get(pk=rechnung.pk))
                    self.message_user(
                        request,
                        ('Zahlung vermerkt. Die Rechnung ist ausgeglichen.'
                         if rest <= 0 else
                         'Zahlung vermerkt. Offen bleiben '
                         f'{formate.geld_mit_waehrung(rest)}.'),
                        messages.SUCCESS,
                    )
                return None
        else:
            formular = ZahlungForm(initial={
                'datum': localdate(),
                'betrag': offen,
                'skonto': Decimal('0.00'),
                'kuerzung': Decimal('0.00'),
                'verwendungszweck': rechnung.nummer or '',
            }, mit_kuerzung=mit_kuerzung)

        return render(
            request,
            'admin/faktura/zahlung.html',
            {**self.admin_site.each_context(request),
             'rechnung': rechnung,
             'brutto': services.belegsummen(rechnung).brutto,
             'offen': offen,
             'bereits': rechnung.ausgeglichen or None,
             'zurueck': adresse_im_admin(rechnung),
             'form': formular,
             'title': 'Zahlung vermerken'},
        )

    @unfold_action(
        description='Zahlung vermerken',
        icon='payments',
        permissions=['zahlung'],
        url_path='zahlung',
    ) # type: ignore
    def detail_zahlung(self, request, object_id):
        """Dieselbe Zwischenseite wie die Listenaktion, wie
        ``detail_nachlass``."""
        queryset = self.get_queryset(request).filter(pk=object_id)
        antwort = self.action_zahlung(request, queryset)
        if antwort is not None:
            return antwort

        opts = self.model._meta
        return redirect(
            f'admin:{opts.app_label}_{opts.model_name}_change', object_id
        )

    def has_zahlung_permission(self, request, object_id=None):
        """Recht ``add_zahlung``, weil die Rechnung unverändert bleibt. Nur
        bei offenem Betrag."""
        if not request.user.has_perm('faktura.add_zahlung'):
            return False

        beleg = self._beleg_oder_none(object_id)
        if beleg is None:
            return True
        return (beleg.status == BelegStatus.FESTGESCHRIEBEN
                and services.offener_betrag(beleg) > 0)

    @admin.action(description='Rechnung stornieren und neu schreiben')
    def action_korrigieren(self, request, queryset):
        for beleg in queryset:
            try:
                storno, entwurf = services.rechnung_korrigieren(
                    beleg_id=beleg.pk, benutzer=request.user
                )
            except services.FakturaError as exc:
                self.message_user(request, f'{beleg}: {exc}', messages.ERROR)
            else:
                # LogEntry am Original, damit dessen Verlauf den Vorgang
                # zeigt.
                self.log_change(
                    request, beleg,
                    f'Storniert durch {storno.nummer}; Neufassung als '
                    f'Entwurf {entwurf.pk} angelegt.',
                )
                self.message_user(
                    request,
                    format_html(
                        '{} erzeugt. Die Neufassung liegt als Entwurf '
                        'bereit: {}',
                        verweis_auf(storno), verweis_auf(entwurf),
                    ),
                    messages.SUCCESS,
                )

    @admin.action(description='Mahnung erzeugen (nächste Stufe)')
    def action_mahnen(self, request, queryset):
        for rechnung in queryset:
            # Die Stufe ergibt sich aus den bisherigen Mahnungen.
            bisher = rechnung.nachfolger.filter(typ=BelegTyp.MAHNUNG).count()
            stufe = min(bisher + 1, 3)
            try:
                mahnung = services.mahnung_erstellen(beleg_id=rechnung.pk, stufe=stufe)
            except services.FakturaError as exc:
                self.message_user(request, f'{rechnung}: {exc}', messages.ERROR)
            else:
                self.message_user(
                    request,
                    format_html('{} als Entwurf erzeugt: {}',
                                mahnung.mahntext, verweis_auf(mahnung)),
                    messages.SUCCESS,
                )


@admin.register(Abschlagsrechnung)
class AbschlagsrechnungAdmin(RechnungAdmin):
    """Abschlagsrechnung, bedient wie eine Rechnung; Überschrift, Zählung je
    Projekt und Hinweis auf die Schlussrechnung stehen im PDF."""

    rechnungsart = Rechnungsart.ABSCHLAG
    # Kein Nachlass am Abschlag, siehe ``has_nachlass_permission``.
    actions = [aktion for aktion in RechnungAdmin.actions
               if aktion != 'action_nachlass']

    #: Ein Abschlag ist eine Anzahlung auf unvollendete Leistung: ohne
    #: Leistungsdatum, mit Pflicht zum Zeitraum
    #: (``Beleg.steuerliches_leistungsdatum``).
    LEISTUNGSFELDER = {
        'leistungsdatum': (
            'Leistungsstand ab',
            'Pflicht: der Zeitraum, auf den sich der Abschlag bezieht, '
            'z. B. Projektbeginn bis zum Stichtag. Ein Leistungsdatum hat '
            'ein Abschlag nicht; die Leistung ist noch nicht vollendet.',
        ),
        'leistungsdatum_bis': ('Stichtag', ''),
    }
    list_display = ['bezeichnung_akte', 'abschlag_anzeige',
                    'empfaenger_zeile', 'belegdatum', 'faelligkeit',
                    'summe_brutto', 'zahlungsstand', 'dokument', 'schloss']

    #: Ab dem 2. Abschlag unter den Positionen die kumulierte Sicht wie im
    #: PDF, schreibgeschützt.
    change_form_after_template = 'admin/faktura/kumuliert.html'

    def change_view(self, request, object_id, form_url='', extra_context=None):
        beleg = self._beleg_oder_none(object_id)
        kumuliert = (services.kumulierter_abschlag(beleg)
                     if beleg is not None else None)
        if kumuliert is not None:
            extra_context = {
                **(extra_context or {}),
                'kumuliert': kumuliert,
                'kumuliert_netto': services.belegsummen(beleg).netto,
            }
        return super().change_view(request, object_id, form_url,
                                   extra_context)

    @admin.display(description='Abschlag', ordering='belegdatum')
    def abschlag_anzeige(self, beleg):
        """Bezeichnung wie "2. Abschlagsrechnung", sortiert nach Belegdatum,
        aus dem die Zählung entsteht."""
        return beleg.rechnungsbezeichnung


@admin.register(Schlussrechnung)
class SchlussrechnungAdmin(RechnungAdmin):
    """Schlussrechnung über die volle Leistung mit Absetzung der Abschläge
    (§ 14 Abs. 5 Satz 2 UStG).

    Aus einer Abnahme erzeugt, enthält sie die Abzugszeilen bereits; sonst
    legt sie "Abschläge absetzen" an (``services.abschlaege_absetzen``).
    """

    rechnungsart = Rechnungsart.SCHLUSS
    inlines = [SchlusspositionInline]
    #: Unter den Positionen die Abschläge wie im PDF, je Abschlag eine Zeile,
    #: schreibgeschützt.
    change_form_after_template = 'admin/faktura/abzugsblock.html'

    def change_view(self, request, object_id, form_url='', extra_context=None):
        beleg = self._beleg_oder_none(object_id)
        if beleg is not None:
            abzuege = services.abzugsblock(
                beleg.positionen.select_related('abgesetzte_position__beleg'))
            extra_context = {
                **(extra_context or {}),
                'abzuege': abzuege,
                'abzuege_summe': sum((z.betrag for z in abzuege),
                                     Decimal('0.00')),
            }
        return super().change_view(request, object_id, form_url,
                                   extra_context)

    @property
    def actions_detail(self):
        """Wie ``RechnungAdmin`` mit "Abschläge absetzen" nach der Akte.

        Eingefügt nach Name, weil die Liste der Elternklasse registrierte
        Belegaktionen enthält (``RechnungAdmin.actions_detail``) und ein fester
        Index sich verschieben könnte.
        """
        basis = list(super().actions_detail)
        basis.insert(basis.index('detail_akte') + 1, 'detail_abschlaege')
        return basis

    @unfold_action(
        description='Abschläge absetzen',
        icon='remove_circle_outline',
        permissions=['abschlaege'],
        url_path='abschlaege',
    )  # type: ignore
    def detail_abschlaege(self, request, object_id):
        """Setzt die gestellten, noch nicht angerechneten Abschläge des
        Projekts ab; idempotent, es kommt nur Fehlendes hinzu."""
        try:
            neu = services.abschlaege_absetzen(beleg_id=object_id)
        except services.FakturaError as fehler:
            self.message_user(request, str(fehler), level=messages.ERROR)
        else:
            self.message_user(
                request,
                f'{len(neu)} Abzugszeile(n) eingefügt.' if neu else
                'Es gibt keinen Abschlag, der hier noch abzusetzen wäre. '
                'Der nicht bezahlte Teil der abgesetzten ist auf dem Stand '
                'der Zahlungen.',
                level=messages.SUCCESS if neu else messages.INFO)
        return self._zurueck_zum_beleg(request, object_id)

    def has_abschlaege_permission(self, request, object_id=None):
        if not super().has_change_permission(request):
            return False
        beleg = self._beleg_oder_none(object_id)
        return beleg is not None and beleg.ist_entwurf


@admin.register(Teilschlussrechnung)
class TeilschlussrechnungAdmin(SchlussrechnungAdmin):
    """Teilschlussrechnung für eine gesondert abgenommene Teilleistung.

    Ohne "Hinzufügen": Sie entsteht nur aus einer Teilabnahme
    (Auftragsakte, Abnahme, "Rechnung erzeugen"), damit sie nicht
    versehentlich aus einem Abschlag entsteht.
    """

    rechnungsart = Rechnungsart.TEILSCHLUSS

    def has_add_permission(self, request):
        return False
