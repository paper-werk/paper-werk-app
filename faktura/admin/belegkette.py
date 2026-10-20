"""Belegkette: festschreiben, umwandeln, wieder öffnen.

Angebot, Auftrag, Lieferschein, Rechnung; jeder Beleg entsteht aus dem
festgeschriebenen vorigen.
"""


from django.contrib import admin, messages
from django.shortcuts import render
from django.urls import reverse
from django.utils.html import format_html
from unfold.decorators import action as unfold_action
from unfold.enums import ActionVariant

from .. import services
from ..models import (
    BelegStatus,
    BelegTyp,
    proxy_fuer,
)
from .gemeinsam import (
    adresse_im_admin,
    verweis_auf,
)


class BelegketteMixin:
    """Festschreiben, umwandeln, wieder öffnen als Detail- und Listenaktion."""


    def _als_detailaktion(self, request, object_id, listenaktion):
        """Führt eine Listenaktion für einen Beleg aus und leitet auf ihn
        zurück, damit die Logik nur in der Listenaktion steht."""
        queryset = self.get_queryset(request).filter(pk=object_id)
        listenaktion(request, queryset)
        return self._zurueck_zum_beleg(request, object_id)

    @unfold_action(
        description='Festschreiben',
        icon='lock',
        permissions=['festschreiben'],
        url_path='festschreiben',
        variant=ActionVariant.PRIMARY,
    ) # type: ignore
    def detail_festschreiben(self, request, object_id):
        """Festschreiben ohne Versand, für den Auftrag.

        Als eigene Bestätigungsseite, weil ``aktion_erst_speichern.js`` den
        Beleg speichert und dann auf die URL der Aktion leitet, wo ein
        htmx-Dialog ohne Seitenrahmen ankäme. GET fragt, POST führt aus.
        """
        beleg = self._beleg_oder_none(object_id)
        if beleg is None:
            return self._zurueck_zum_beleg(request, object_id)

        if request.method == 'POST':
            return self._als_detailaktion(request, object_id,
                                          self.action_festschreiben)

        basis = f'admin:{self.model._meta.app_label}_{self.model._meta.model_name}'
        return render(
            request,
            'admin/faktura/festschreiben.html',
            {**self.admin_site.each_context(request),
             'beleg': beleg,
             'summe': services.belegsummen(beleg).brutto,
             'mit_dokument': beleg.typ in BelegTyp.mit_dokument(),
             'entsperrbar': beleg.typ in BelegTyp.entsperrbar(),
             'zurueck': reverse(f'{basis}_change', args=[beleg.pk]),
             'title': 'Festschreiben'},
        )

    def has_festschreiben_permission(self, request, object_id=None):
        """Am Entwurf mit Änderungsrecht, ohne eigenes Recht."""
        if not super().has_change_permission(request):
            return False

        beleg = self._beleg_oder_none(object_id)
        if beleg is None:
            return True
        return beleg.status == BelegStatus.ENTWURF

    def has_wiedereroeffnen_permission(self, request, object_id=None):
        """Eigenes Recht ``beleg_wiedereroeffnen``, nur an festgeschriebenem
        Angebot oder Auftrag.

        Eigenes Recht, damit nicht jeder, der Angebote schreibt, ein beim
        Kunden liegendes öffnen kann. ``faktura_rechte`` vergibt es.
        """
        if not request.user.has_perm('faktura.beleg_wiedereroeffnen'):
            return False

        beleg = self._beleg_oder_none(object_id)
        if beleg is None:
            return True
        return (
            beleg.typ in BelegTyp.entsperrbar()
            and beleg.status == BelegStatus.FESTGESCHRIEBEN
        )

    @unfold_action(
        description='Wieder öffnen',
        icon='lock_open',
        permissions=['wiedereroeffnen'],
        url_path='wieder-oeffnen',
        dialog={
            'title': 'Beleg wieder öffnen?',
            # Der Hinweis erklärt, warum die Positionen eines geöffneten
            # Auftrags in der Erfassung fehlen.
            'description': 'Der Beleg wird erneut zum Entwurf und lässt '
                           'sich bearbeiten. Seine Nummer behält er bei. '
                           'Vermeiden Sie nachträgliches Öffnen und Ändern, '
                           'wenn immer möglich. Bei einem Auftrag gilt '
                           'außerdem: Solange er offen ist, kann niemand '
                           'Stunden darauf kontieren.',
            'form_submit_text': 'Wieder öffnen',
        }, # type: ignore
    )
    def detail_wiedereroeffnen(self, request, form, object_id):
        """Setzt den Beleg in den Entwurf zurück. ``form`` verlangt Unfold bei
        Dialogen; es ist leer."""
        beleg = self._beleg_oder_none(object_id)
        if beleg is None:
            return self._zurueck_zum_beleg(request, object_id)

        try:
            beleg = services.beleg_wiedereroeffnen(
                beleg_id=beleg.pk, benutzer=request.user)
        except services.FakturaError as fehler:
            self.message_user(request, str(fehler), messages.ERROR)
            return self._zurueck_zum_beleg(request, object_id)

        self._vermerken(
            request, beleg,
            f'Wieder geöffnet; zurück in den Entwurf, Nummer '
            f'{beleg.nummer} bleibt.')
        # Der Hinweis zusätzlich als Meldung, weil Dialogtexte oft
        # übersprungen werden.
        nachsatz = (
            ' Solange er offen ist, kann niemand Stunden darauf kontieren.'
            if beleg.typ == BelegTyp.AUFTRAG else ''
        )
        self.message_user(
            request,
            f'{beleg} ist wieder ein Entwurf und behält die Nummer '
            f'{beleg.nummer}. Mit „Versenden" wird er erneut '
            f'festgeschrieben; das PDF entsteht dabei neu.{nachsatz}',
            messages.SUCCESS)
        return self._zurueck_zum_beleg(request, object_id)

    def has_nachgelagert_permission(self, request, object_id=None):
        """Recht für Vorgänge an festgeschriebenen Belegen: umwandeln, mahnen,
        stornieren, Nachlass.

        Änderungsrecht an der Belegart und festgeschriebener Beleg;
        ``has_change_permission`` am Beleg selbst ist dann False.
        """
        if not super().has_change_permission(request):
            return False

        beleg = self._beleg_oder_none(object_id)
        if beleg is None:
            return True
        return beleg.status == BelegStatus.FESTGESCHRIEBEN

    def _duplizieren_als_detailaktion(self, request, object_id):
        """Legt das Duplikat an und öffnet es zur Bearbeitung. Für Angebot
        und Rechnung; was kopiert wird, regelt
        ``services.beleg_duplizieren``."""
        try:
            duplikat = services.beleg_duplizieren(beleg_id=object_id)
        except services.FakturaError as fehler:
            self.message_user(request, str(fehler), level=messages.ERROR)
            return self._zurueck_zum_beleg(request, object_id)

        original = self._beleg_oder_none(object_id)
        kopie = duplikat.beleg
        # Am Proxy, weil der LogEntry am Beleg aus dem Service in keinem
        # Verlauf erschiene (siehe _vermerken in beleg.py).
        self.log_addition(
            request,
            proxy_fuer(kopie.typ, kopie.rechnungsart).objects.get(pk=kopie.pk),
            f'Dupliziert aus {original}.')
        self.message_user(
            request,
            format_html('Duplikat von {} angelegt; ein Entwurf, die Nummer '
                        'folgt beim Versenden.', original),
            level=messages.SUCCESS)
        if duplikat.ohne_fremdleistungen:
            self.message_user(
                request,
                f'{duplikat.ohne_fremdleistungen} Position(en) aus '
                f'Fremdleistungen nicht übernommen; eine Fremdleistung wird '
                f'nur einmal weiterberechnet.',
                level=messages.WARNING)
        # Über _antwort_auf, weil der Request aus dem Dialog per htmx kommt.
        return self._antwort_auf(request, adresse_im_admin(kopie))

    def has_duplizieren_permission(self, request, object_id=None):
        """Recht zum Anlegen der Belegart, in jedem Status, weil das Original
        unverändert bleibt.

        Welche Arten den Button zeigen, steht in ``actions_detail``. Ob die
        Art duplizierbar ist, entscheidet der Service (``DUPLIZIERBAR``);
        die Prüfung hier verhindert einen Button, der nur einen Fehler
        auslöst.
        """
        if not self.has_add_permission(request):
            return False
        beleg = self._beleg_oder_none(object_id)
        if beleg is None:
            return True
        return (beleg.typ, beleg.rechnungsart) in services.DUPLIZIERBAR

    def _umwandeln_als_detailaktion(self, request, object_id, neuer_typ,
                                    bezeichnung):
        """Umwandlung eines Belegs mit Redirect auf den neuen Beleg."""
        queryset = self.get_queryset(request).filter(pk=object_id)
        neu = self._umwandeln(request, queryset, neuer_typ, bezeichnung)
        if neu is None:
            return self._zurueck_zum_beleg(request, object_id)
        return self._antwort_auf(request, adresse_im_admin(neu))

    # --- Aktionen für fachliche Vorgänge ---

    @admin.action(description='Ausgewählte Belege festschreiben')
    def action_festschreiben(self, request, queryset):
        """Festschreiben mit Benutzer am Beleg und LogEntry.

        Aktionen erzeugen in Django keinen LogEntry. Er wird am ``beleg`` aus
        dem Queryset (Proxy der Belegart) geschrieben, weil er am Rückgabewert
        des Service im Verlauf nicht erschiene.
        """
        erfolg, fehler = 0, 0
        for beleg in queryset:
            try:
                festgeschrieben = services.beleg_festschreiben(
                    beleg_id=beleg.pk, benutzer=request.user
                )
            except services.FakturaError as exc:
                self.message_user(request, f'{beleg}: {exc}', messages.ERROR)
                fehler += 1
            else:
                self.log_change(
                    request, beleg,
                    f'Festgeschrieben als {festgeschrieben.nummer}.',
                )
                self.message_user(
                    request,
                    format_html('{} festgeschrieben, Nummer {}.',
                                verweis_auf(festgeschrieben),
                                festgeschrieben.nummer),
                    messages.SUCCESS,
                )
                # Abweichungen werden beim Erzeugen von PDF und XML gemeldet,
                # bevor der Beleg zum Kunden geht.
                self._auf_abweichung_hinweisen(
                    request, festgeschrieben,
                    'Der Beleg ist festgeschrieben; zu ändern ist das nur '
                    'noch über eine Stornierung.',
                )
                erfolg += 1
        if erfolg and fehler:
            self.message_user(request, f'{erfolg} erfolgreich, {fehler} abgelehnt.',
                              messages.WARNING)

    @unfold_action(
        description='Rechnung erzeugen',
        icon='receipt_long',
        permissions=['nachgelagert'],
        url_path='in-rechnung',
        dialog={
            'title': 'Rechnung aus diesem Beleg erzeugen?',
            'description': 'Kopiert Daten und erstellt eine Rechnung (Entwurf)',
            'form_submit_text': 'Rechnung erzeugen',
        }, # type: ignore
    )
    def detail_in_rechnung(self, request, form, object_id):
        """Umwandlung in eine Rechnung; sichtbar, wo sie in
        ``actions_detail`` steht."""
        return self._umwandeln_als_detailaktion(
            request, object_id, BelegTyp.RECHNUNG, 'Rechnung')

    @admin.action(description='Rechnung daraus erzeugen')
    def action_in_rechnung(self, request, queryset):
        """Für Angebot, Auftrag und Lieferschein; sichtbar, wo sie in
        ``actions`` steht."""
        self._umwandeln(request, queryset, BelegTyp.RECHNUNG, 'Rechnung')

    def _umwandeln(self, request, queryset, neuer_typ, bezeichnung):
        """Gemeinsamer Ablauf der Umwandlungen. Gibt den zuletzt erzeugten
        Beleg zurück, None bei Fehler."""
        neu = None
        for beleg in queryset:
            try:
                neu = services.beleg_umwandeln(beleg_id=beleg.pk, neuer_typ=neuer_typ)
            except services.FakturaError as exc:
                self.message_user(request, f'{beleg}: {exc}', messages.ERROR)
                neu = None
            else:
                self.message_user(
                    request,
                    format_html('{} aus {} erzeugt: {}',
                                bezeichnung, beleg, verweis_auf(neu)),
                    messages.SUCCESS,
                )
        return neu
