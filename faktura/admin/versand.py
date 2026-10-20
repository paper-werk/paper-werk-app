"""Versandmaske für Versenden und erneutes Versenden.

Der Ablauf steht in ``services.beleg_versenden`` (erst festschreiben, dann
senden); hier nur die Bedienung.
"""


from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse
from unfold.decorators import action as unfold_action
from unfold.enums import ActionVariant

from .. import facturx, formate, services
from ..forms import (
    VersandForm,
)
from ..models import (
    BelegStatus,
    BelegTyp,
    Firma,
    Textbaustein,
    TextbausteinVerwendung,
)


class VersandMixin:
    """Versandmaske: festschreiben und per Mail senden, nur festschreiben
    oder festschreiben und herunterladen."""


    @unfold_action(
        description='Versenden',
        icon='send',
        permissions=['versenden'],
        url_path='versenden',
        variant=ActionVariant.PRIMARY,
    ) # type: ignore
    def detail_versenden(self, request, object_id):
        """Festschreiben und versenden in einem Vorgang.

        Als Zwischenseite, damit Adresse und Anschreiben sichtbar und
        änderbar sind. Jeder Button schreibt fest.
        """
        return self._versandmaske(request, object_id)

    def _versandmaske(self, request, object_id):
        """Maske für beide Versandaktionen, ohne Decorator, damit nicht die
        Rechteprüfung der jeweils anderen Aktion greift."""
        beleg = self._beleg_oder_none(object_id)
        if beleg is None:
            return self._zurueck_zum_beleg(request, object_id)

        if request.method == 'POST':
            return self._versand_ausfuehren(request, beleg)

        formular = VersandForm(
            belegart=beleg.typ, anlagen=self._versandanlagen(beleg), initial={
                'an': beleg.empfaenger_email,
                'betreff': self._versandbetreff(beleg),
                'nachricht': self._versandtext(beleg),
            })
        return self._versandseite(request, beleg, formular)

    @staticmethod
    def _versandanlagen(beleg) -> list[tuple[str, str]]:
        """Anhängbare Anlagen für ``VersandForm``."""
        return [(art, quelle.titel)
                for art, quelle in services.anlagenquellen(beleg).items()]

    @staticmethod
    def _formattext(beleg) -> str:
        """Beschreibung der versendeten Dateien für Maske und Verlauf."""
        if services.versandformat(beleg) == services.Versandanhang.XML:
            return 'XRechnung (XML für das Rechnungsportal)'
        if beleg.typ in facturx.TYP_CODE:
            return 'PDF mit eingebetteter E-Rechnung (ZUGFeRD)'
        return 'PDF'

    @unfold_action(
        description='Erneut versenden',
        icon='forward_to_inbox',
        permissions=['erneut_versenden'],
        url_path='erneut-versenden',
    ) # type: ignore
    def detail_erneut_versenden(self, request, object_id):
        """Dieselbe Maske am bereits versendeten Beleg, nicht in der
        Primärfarbe, weil ein zweiter Versand die Ausnahme ist.

        Ruft ``_versandmaske`` auf, weil der Decorator von
        ``detail_versenden`` dessen Recht prüft, das an einem versendeten
        Beleg False ist.
        """
        return self._versandmaske(request, object_id)

    def _versand_ausfuehren(self, request, beleg):
        """Führt die Aktion des gedrückten Buttons aus. Nur der Mailversand
        verlangt ein gültiges Formular, damit ein Tippfehler in der Adresse
        das Festschreiben nicht verhindert."""
        will_mailen = 'senden' in request.POST
        formular = VersandForm(request.POST, belegart=beleg.typ,
                               anlagen=self._versandanlagen(beleg))

        if will_mailen:
            if not formular.is_valid():
                return self._versandseite(request, beleg, formular)
            try:
                versendet = services.beleg_versenden(
                    beleg_id=beleg.pk,
                    an=formular.cleaned_data['an'],
                    betreff=formular.cleaned_data['betreff'],
                    nachricht=formular.cleaned_data['nachricht'],
                    benutzer=request.user,
                    mengen_bestaetigt=self._mengen_bestaetigt(request),
                    anlagen=formular.anzuhaengende_anlagen(),
                )
            except services.MengeUeberschritten as fehler:
                return self._nicht_bestaetigt(request, beleg, formular,
                                              fehler)
            except services.FakturaError as fehler:
                # Redirect auf den Beleg, weil er bereits festgeschrieben sein
                # kann.
                self.message_user(request, str(fehler), messages.ERROR)
                return self._zurueck_zum_beleg(request, beleg.pk)

            # Bei einer E-Rechnung steht der Anhang im LogEntry, weil er das
            # Original bezeichnet.
            zusatz = ''
            if versendet.typ in facturx.TYP_CODE:
                zusatz = f' (Anhang: {self._formattext(versendet)})'
            quellen = services.anlagenquellen(versendet)
            mitgesendet = [quellen[art].titel
                           for art in formular.anzuhaengende_anlagen()
                           if art in quellen]
            if mitgesendet:
                zusatz += f', dazu {", ".join(mitgesendet)}'
            self._vermerken(
                request, versendet,
                f'Per E-Mail versendet an {formular.cleaned_data["an"]}'
                f'{zusatz}.')

            # Ohne konfiguriertes SMTP weist die Meldung darauf hin.
            if services.versand_geht_hinaus():
                self.message_user(
                    request,
                    f'{versendet} festgeschrieben und an '
                    f'{versendet.versendet_an} versendet.',
                    messages.SUCCESS)
            else:
                self.message_user(
                    request,
                    f'{versendet} festgeschrieben. Die E-Mail an '
                    f'{versendet.versendet_an} wurde NICHT verschickt, '
                    f'sondern nur in die Server-Konsole geschrieben; '
                    f'dieser Rechner hat keinen Postausgang eingerichtet.',
                    messages.WARNING)
            return self._zurueck_zum_beleg(request, beleg.pk)

        # Die übrigen Buttons schreiben fest, auch vor dem Download, weil
        # jeder herausgegebene Beleg festgeschrieben sein muss.
        if beleg.ist_aenderbar:
            try:
                beleg = services.beleg_festschreiben(
                    beleg_id=beleg.pk, benutzer=request.user,
                    mengen_bestaetigt=self._mengen_bestaetigt(request))
            except services.MengeUeberschritten as fehler:
                return self._nicht_bestaetigt(request, beleg, formular,
                                              fehler)
            except services.FakturaError as fehler:
                self.message_user(request, str(fehler), messages.ERROR)
                return self._zurueck_zum_beleg(request, beleg.pk)
            self._vermerken(request, beleg,
                            f'Festgeschrieben als {beleg.nummer}.')
            self.message_user(request, f'{beleg} festgeschrieben.',
                              messages.SUCCESS)

        if ('herunterladen' in request.POST
                and services.versandformat(beleg)
                == services.Versandanhang.XML):
            # Für Rechnungsportale; wie der PDF-Download im Verlauf
            # vermerkt.
            self._vermerken(request, beleg, 'XRechnung heruntergeladen.')
            ziel = reverse(
                f'admin:{self.model._meta.app_label}_'
                f'{self.model._meta.model_name}_xml',
                args=[beleg.pk])
            return redirect(ziel)

        if 'herunterladen' in request.POST:
            # Auch ein Download wird im Verlauf vermerkt.
            self._vermerken(request, beleg, 'PDF heruntergeladen.')
            # ``self.model``, weil der Service einen ``Beleg`` zurückgibt und
            # die URL nur am Proxy existiert. ``?speichern=1`` erzwingt den
            # Download.
            ziel = reverse(
                f'admin:{self.model._meta.app_label}_'
                f'{self.model._meta.model_name}_pdf',
                args=[beleg.pk])
            return redirect(f'{ziel}?speichern=1')
        return self._zurueck_zum_beleg(request, beleg.pk)

    @staticmethod
    def _mengen_bestaetigt(request) -> bool:
        """Checkbox zur Bestätigung von "Mehr als beauftragt"."""
        return bool(request.POST.get('mengen_bestaetigt'))

    def _nicht_bestaetigt(self, request, beleg, formular, fehler):
        """Ohne Bestätigung zurück auf die Maske, weil der Beleg noch Entwurf
        ist; die Eingaben bleiben erhalten."""
        self.message_user(request, str(fehler), messages.ERROR)
        return self._versandseite(request, beleg, formular)

    def _versandseite(self, request, beleg, formular):
        return render(
            request,
            'admin/faktura/versenden.html',
            {**self.admin_site.each_context(request),
             'beleg': beleg,
             'summe': services.belegsummen(beleg).brutto,
             'ist_entwurf': beleg.status == BelegStatus.ENTWURF,
             'kopie_an': services.absenderadresse(),
             'mit_kopie': getattr(settings, 'FAKTURA_VERSAND_KOPIE', True),
             'geht_hinaus': services.versand_geht_hinaus(),
             'formattext': self._formattext(beleg),
             'kunde': facturx.kunde_des_belegs(beleg),
             # Vor dem Versand angezeigt, weil sich der Zustellweg nur am
             # Entwurf ändern lässt; danach nur durch Neuausstellung.
             'zustellweg_warnung': facturx.zustellweg_warnung(beleg),
             # Nur am Entwurf, weil ein festgeschriebener Beleg nicht mehr
             # geändert werden kann.
             'ueberschreitungen': (
                 services.mengenueberschreitungen(beleg)
                 if beleg.status == BelegStatus.ENTWURF else []),
             # Nur ein Hinweis, weil gestellte Abschläge abgesetzt werden,
             # auch unbezahlte.
             'offene_abschlaege': (
                 services.offene_abgesetzte_abschlaege(beleg)
                 if beleg.status == BelegStatus.ENTWURF else []),
             'anlagenvorschau': self._anlagenvorschau(beleg),
             'form': formular,
             'title': 'Versenden'},
        )

    def _anlagenvorschau(self, beleg) -> list[tuple[str, str]]:
        """Je anhängbarer Anlage ``(titel, url)``. Die URL folgt der
        Konvention der registrierenden App (Detailaktion ``detail_<art>``);
        fehlt sie, entfällt der Link."""
        ergebnis = []
        for art, quelle in services.anlagenquellen(beleg).items():
            try:
                url = reverse(f'admin:{self.model._meta.app_label}_'
                              f'{self.model._meta.model_name}_detail_{art}',
                              args=[beleg.pk])
            except NoReverseMatch:
                continue
            ergebnis.append((quelle.titel, url))
        return ergebnis

    def _versandbetreff(self, beleg) -> str:
        """Vorgeschlagener Betreff, mit Belegnummer, sobald es eine gibt."""
        teile = [beleg.rechnungsbezeichnung or beleg.get_typ_display()]
        if beleg.nummer:
            teile.append(beleg.nummer)
        return ' '.join(teile)

    def _versandtext(self, beleg) -> str:
        """Anschreiben aus dem Mail-Baustein der Belegart, sonst dem
        allgemeinen, sonst ein eingebauter Text für Installationen ohne
        Bausteine."""
        firma = Firma.objects.first()
        werte = {
            'nummer': beleg.nummer or '',
            # Nicht ``str(beleg)``, das am Entwurf "Rechnung (Entwurf 590)"
            # ergäbe.
            'beleg': self._versandbetreff(beleg),
            'empfaenger': beleg.empfaenger_kurz,
            # Deutsches Zahlenformat, weil der Text an den Kunden geht.
            'betrag': formate.geld_mit_waehrung(
                services.belegsummen(beleg).brutto),
            'firma': firma.name if firma else '',
        }

        baustein = Textbaustein.fuer(
            TextbausteinVerwendung.MAIL, beleg.typ).first()
        if baustein:
            return baustein.gefuellt(**werte)

        return (
            'Sehr geehrte Damen und Herren,\n\n'
            f'im Anhang: {werte["beleg"]}.\n\n'
            'Mit freundlichen Grüßen\n'
            f'{werte["firma"]}'
        ).strip()

    def has_versenden_permission(self, request, object_id=None):
        """Versenden mit Änderungsrecht, an noch nicht versendeten Belegen.

        Ohne eigenes Recht, das auf jeder Installation erst zu vergeben wäre,
        und ohne Schalter, weil Versenden an vielen Belegarten das
        Festschreiben ersetzt.
        """
        beleg = self._darf_versenden(request, object_id)
        return beleg is not None and beleg.versendet_am is None

    def has_erneut_versenden_permission(self, request, object_id=None):
        """Dasselbe am bereits versendeten Beleg. Zwei Aktionen, weil Unfold
        die Beschriftung nicht vom Zustand abhängig machen kann; sichtbar ist
        immer nur eine."""
        beleg = self._darf_versenden(request, object_id)
        return beleg is not None and beleg.versendet_am is not None

    def _darf_versenden(self, request, object_id):
        """Der Beleg, wenn er versendet werden kann, sonst None.

        None auch ohne ID; dann entscheidet der Aufrufer. Nicht bei Stornos
        und Belegarten ohne Dokument; geprüft hier und nicht nur über
        ``actions_detail``, damit die URL nicht aufrufbar bleibt.
        """
        if not super().has_change_permission(request):
            return None

        beleg = self._beleg_oder_none(object_id)
        if beleg is None:
            return None
        if beleg.status == BelegStatus.STORNIERT:
            return None
        if beleg.typ not in BelegTyp.mit_dokument():
            return None
        return beleg
