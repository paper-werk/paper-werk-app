"""``BelegAdmin``, Basisklasse der Admins aller Belegarten.

Nicht registriert; im Menü stehen nur die Belegarten.
"""


from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.templatetags.admin_urls import add_preserved_filters
from django.db import models
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils import timezone
from unfold import admin as unfold_admin
from unfold.contrib.filters.admin import (
    AutocompleteSelectFilter,
    ChoicesDropdownFilter,
    RangeDateFilter,
)

from core.adminhilfen import (
    Kopfleiste,
    jquery_entdoppeln,
    mit_stand,
    skript_mit_stand,
    weitere,
)
from core.optimistic_locking import VersionAdminMixin

from ..forms import (
    BelegForm,
)
from ..models import (
    Beleg,
)
from .belegkette import BelegketteMixin
from .dokumente import DokumentMixin
from .formular import FormularMixin
from .gemeinsam import (
    AktionNachDemSichern,
    BelegpositionInline,
    KundeBelegFilter,
)
from .spalten import SpaltenMixin
from .uebernahme import UebernahmeMixin
from .versand import VersandMixin


class BelegAdmin(
    Kopfleiste, VersionAdminMixin,
    VersandMixin, DokumentMixin, BelegketteMixin, FormularMixin, UebernahmeMixin, SpaltenMixin,
    AktionNachDemSichern,
    unfold_admin.ModelAdmin,
):
    """Basisklasse aller Belegarten.

    Die Mixins übernehmen Versand, Dokumente, Festschreiben und Umwandeln,
    Formular, Übernahme der Stammdaten und Listenspalten.
    ``VersionAdminMixin`` ergänzt Optimistic Locking
    (``core/optimistic_locking.py``).
    """


    form = BelegForm
    inlines = [BelegpositionInline]

    #: Buttons über dem geöffneten Beleg. Die Listenaktionen gelten für
    #: mehrere Belege; die Detailaktion ruft die Listenaktion auf
    #: (``_als_detailaktion``).
    #
    # "Versenden", weil Versenden auch festschreibt. ``actions_detail`` ist
    # ein Klassenattribut; jede Unterklasse führt es vollständig auf, damit
    # kein geerbter Eintrag unbemerkt fehlt. Vorn der nächste Schritt laut
    # Status und PDF, der Rest in "Weitere …" (``core.adminhilfen.weitere``).
    actions_detail = ['detail_versenden', 'detail_pdf',
                      weitere('detail_erneut_versenden')]
    # ``schloss`` steht in jeder Liste zuletzt und zeigt dort als einzige
    # Spalte die Sperre.
    list_display = ['bezeichnung', 'empfaenger_zeile', 'belegdatum',
                    'summe_brutto', 'dokument', 'schloss']
    # Datumsbereich, weil nach Zeiträumen wie einem Quartal gesucht wird;
    # Djangos Vorgabe bietet nur "Heute/7 Tage/Monat". Projekt als
    # Autocomplete, weil eine Auswahl nach zehn Jahren 1.200 Projekte in
    # jede Liste lud.
    list_filter = [
        ('status', ChoicesDropdownFilter),
        ('belegdatum', RangeDateFilter),
        ('projekt', AutocompleteSelectFilter),
        KundeBelegFilter,
    ]
    # Filtern erst per Button, weil der Datumsbereich sonst nach dem ersten
    # Feld neu lädt.
    list_filter_submit = True
    search_fields = ['nummer', 'empfaenger', 'betreff']
    autocomplete_fields = ['kunde']
    date_hierarchy = 'erstellt_am'
    actions = ['action_festschreiben']
    warn_unsaved_form = True

    # Summe der gefilterten Liste.
    list_after_template = 'admin/faktura/belegsumme.html'

    #: Belegtyp, gesetzt von den Unterklassen und beim Anlegen übernommen.
    typ = None
    #: Nur in den Admins der Rechnungen gesetzt, siehe save_model.
    rechnungsart = None

    def _antwort_auf(self, request, ziel):
        """Redirect nach einer Detailaktion.

        Aus einem Bestätigungsdialog (htmx) mit ``HX-Redirect``, weil htmx
        sonst nur den Dialog ersetzt.
        """
        if request.headers.get('HX-Request'):
            antwort = HttpResponse(status=204)
            antwort['HX-Redirect'] = ziel
            return antwort

        return redirect(ziel)

    def _zurueck_zum_beleg(self, request, object_id):
        """Redirect auf den Beleg der Aktion, wo ihre Meldungen erscheinen.
        Mit ``_changelist_filters``, damit "Sichern" danach in die gefilterte
        Liste führt."""
        opts = self.model._meta
        ziel = add_preserved_filters(
            {'preserved_filters': self.get_preserved_filters(request),
             'opts': opts},
            reverse(f'admin:{opts.app_label}_{opts.model_name}_change',
                    args=[object_id]))
        return self._antwort_auf(request, ziel)

    def _vermerken(self, request, beleg, text):
        """Schreibt einen LogEntry zum Beleg über den Proxy der Belegart.

        Djangos Verlauf filtert nach dem ContentType des Proxys (Rechnung,
        Angebot); ein Eintrag am Basismodell ``Beleg``, wie ihn die Services
        zurückgeben, wäre dort unsichtbar.
        """
        objekt = self.get_object(request, str(beleg.pk))
        if objekt is not None:
            self.log_change(request, objekt, text)

    @property
    def media(self):
        """Hängt die eigenen Skripte hinter Djangos Admin-Skripte.

        Djangos jQuery-Dateien werden mit denselben Pfaden erneut aufgeführt,
        damit die eigenen danach geladen werden (``django.jQuery`` muss
        existieren). ``extra`` folgt ``ModelAdmin.media`` (min im Betrieb),
        sonst entstünden zwei jQuery-Instanzen. Eigene Dateien mit
        Cache-Buster.
        """
        extra = '' if settings.DEBUG else '.min'
        zusammen = super().media + forms.Media(css={
            'all': [
                # Katalogsuche; die Farben liefert Unfold. Dieselbe Version
                # wie Djangos Autocomplete am Kunden, damit das Stylesheet
                # nur einmal eingebunden wird.
                f'admin/css/vendor/select2/select2{extra}.css',
                'admin/css/autocomplete.css',
                mit_stand('faktura/css/faktura_admin.css'),
            ],
        }, js=[  # type: ignore[list-item]  (Media nimmt auch __html__-Objekte)
            f'admin/js/vendor/jquery/jquery{extra}.js',
            # Select2 registriert sich am zuvor geladenen jQuery, vor
            # jquery.init.js, das es zu django.jQuery macht.
            f'admin/js/vendor/select2/select2.full{extra}.js',
            'admin/js/vendor/select2/i18n/de.js',
            'admin/js/jquery.init.js',
            skript_mit_stand('faktura/js/kunde_uebernehmen.js'),
            skript_mit_stand('faktura/js/textbaustein_einfuegen.js'),
            skript_mit_stand('faktura/js/katalog_suche.js'),
            skript_mit_stand('faktura/js/katalog_uebernehmen.js'),
            skript_mit_stand('faktura/js/positionsnummer.js'),
            skript_mit_stand('faktura/js/zeilensumme.js'),
            # Nötig, weil der Langtext sonst nach dem Löschen einer
            # ungespeicherten Zeile deren Nummer behält.
            skript_mit_stand('faktura/js/zweite_zeile.js'),
            skript_mit_stand('faktura/js/zeilenart.js'),
            skript_mit_stand('faktura/js/zuschlag_auf.js'),
        ])
        return jquery_entdoppeln(zusammen, extra)

    def get_urls(self):
        """Eigene URLs unterhalb der Modell-URL, mit Login- und Rechteprüfung
        des Admin."""
        eigene = [
            path(
                '<int:pk>/pdf/',
                self.admin_site.admin_view(self.ansicht_pdf),
                name=f'{self.model._meta.app_label}_'
                     f'{self.model._meta.model_name}_pdf',
            ),
            path(
                '<int:pk>/xml/',
                self.admin_site.admin_view(self.ansicht_xml),
                name=f'{self.model._meta.app_label}_'
                     f'{self.model._meta.model_name}_xml',
            ),
            path(
                '<int:pk>/fassung/<int:fassung_pk>/<str:art>/',
                self.admin_site.admin_view(self.ansicht_fassung),
                name=f'{self.model._meta.app_label}_'
                     f'{self.model._meta.model_name}_fassung',
            ),
            path(
                '<int:pk>/vorschau/',
                self.admin_site.admin_view(self.ansicht_html),
                name=f'{self.model._meta.app_label}_'
                     f'{self.model._meta.model_name}_vorschau',
            ),
            path(
                'kundendaten/',
                self.admin_site.admin_view(self.kundendaten),
                name=f'{self.model._meta.app_label}_'
                     f'{self.model._meta.model_name}_kundendaten',
            ),
        ]
        return eigene + super().get_urls()

    def get_readonly_fields(self, request, obj=None):
        immer = ['status', 'nummer', 'festgeschrieben_am', 'festgeschrieben_von',
                 'versendet_am', 'versendet_an', 'aenderungsvermerk',
                 'vorgaenger', 'faellig_am', 'summenaufstellung', 'dokumentnachweis',
                 'archivverweis', 'termin_hinweis']
        if obj is not None and not obj.ist_aenderbar:
            # Festgeschrieben: alles schreibgeschützt.
            return immer + [f.name for f in Beleg._meta.fields
                            if f.name not in immer and f.editable]
        return immer

    def changeform_view(self, request, object_id=None, form_url='',
                        extra_context=None):
        """POST auf einen inzwischen festgeschriebenen Beleg: Redirect auf die
        Read-only-Ansicht mit Warnung, ohne zu speichern.

        Ohne diese Behandlung antwortete ``has_change_permission`` mit 403.
        Ohne View-Recht bleibt es bei 403.
        """
        if request.method == 'POST' and object_id:
            beleg = self.get_object(request, object_id)
            if (beleg is not None and not beleg.ist_aenderbar
                    and self.has_view_permission(request, beleg)):
                self.message_user(request, self._nicht_mehr_aenderbar(beleg),
                                  messages.WARNING)
                return self._zurueck_zum_beleg(request, beleg.pk)
        return super().changeform_view(request, object_id, form_url,
                                       extra_context)

    @staticmethod
    def _nicht_mehr_aenderbar(beleg) -> str:
        text = f'{beleg} ist inzwischen {beleg.get_status_display().lower()}'
        if beleg.festgeschrieben_am:
            wann = timezone.localtime(beleg.festgeschrieben_am)
            wer = beleg.festgeschrieben_von
            von = f' von {wer.get_full_name() or wer.get_username()}' if wer else ''
            text += f' (festgeschrieben{von} am {wann:%d.%m.%Y um %H:%M})'
        return f'{text}. Die Änderungen sind nicht gesichert.'

    def has_change_permission(self, request, obj=None):
        """Kein Änderungsrecht an festgeschriebenen Belegen.

        Schreibgeschützte Felder allein reichen nicht, weil Django die
        Speichern-Buttons weiter zeigte und ein POST eine 500 ergab. So zeigt
        Django die Read-only-Ansicht und lehnt POST mit 403 ab. Ohne Objekt
        (Liste) bleibt das Recht, sonst fehlten die Aktionen.
        """
        beleg = self._beleg_oder_none(obj)
        if beleg is not None and not beleg.ist_aenderbar:
            return False
        return super().has_change_permission(request, beleg)

    def has_delete_permission(self, request, obj=None):
        beleg = self._beleg_oder_none(obj)
        if beleg is not None and not beleg.ist_entwurf:
            return False
        return super().has_delete_permission(request, beleg)

    def _beleg_oder_none(self, obj):
        """Lädt den Beleg zum zweiten Argument der Rechteprüfung.

        Unfold übergibt bei Detailaktionen die ID als String. Ein nicht
        vorhandener Beleg ergibt None.
        """
        # ``models.Model``, weil die Services einen ``Beleg`` zurückgeben und
        # ``self.model`` der Proxy der Belegart ist.
        if obj is None or isinstance(obj, models.Model):
            return obj
        return self.model.objects.filter(pk=obj).first()
