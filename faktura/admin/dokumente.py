"""Dokument eines Belegs: Auslieferung von PDF und XML, Vorschau, Spalten
mit Link ins Archiv.

Bei festgeschriebenen Belegen wird die gespeicherte Datei ausgeliefert, nie
eine neu gerenderte; nur Entwürfe werden beim Abruf erzeugt.
"""


from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import Resolver404, resolve, reverse
from django.utils.html import format_html, format_html_join
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.safestring import mark_safe
from django.utils.timezone import localtime
from unfold.decorators import action as unfold_action

from .. import archiv
from ..facturx import PROFIL_NAME_XRECHNUNG


class DokumentMixin:
    """PDF, XML und Vorschau eines Belegs mit den zugehörigen Spalten."""


    @unfold_action(
        description='PDF anzeigen',
        icon='picture_as_pdf',
        permissions=['view'],
        url_path='pdf-ansehen',
        # In einem neuen Tab, damit der Beleg offen bleibt.
        attrs={'target': '_blank'},
    ) # type: ignore
    def detail_pdf(self, request, object_id):
        """PDF des geöffneten Belegs, ohne Dialog, weil die Ansicht nichts
        ändert."""
        return self.ansicht_pdf(request, object_id)

    def _beleg_der_seite(self, request):
        """Bearbeiteter Beleg oder None beim Anlegen.

        ``formfield_for_foreignkey`` erhält das Objekt nicht; der
        Primärschlüssel steht im Pfad.
        """
        try:
            treffer = resolve(request.path_info)
        except Resolver404:
            return None
        pk = treffer.kwargs.get('object_id')
        return self.model.objects.filter(pk=pk).first() if pk else None

    # --- Dokument: Ansicht und Vorschau ---

    @staticmethod
    def _pdf_modul():
        """Importiert faktura.pdf und damit WeasyPrint und Pango erst beim
        Zugriff, weil es sonst unter Windows beim Start warnt und der Admin
        ohne Pango nicht lädt."""
        from .. import pdf
        return pdf

    def _leserecht_verlangen(self, request) -> None:
        """Verlangt das Leserecht an der Belegart.

        ``admin_view()`` prüft nur Login und Staff, nicht das Modellrecht;
        PDF und Vorschau zeigen den ganzen Beleg mit Preisen.
        """
        if not self.has_view_permission(request):
            raise PermissionDenied

    def ansicht_pdf(self, request, pk):
        """Liefert das PDF: die gespeicherte Datei, am Entwurf eine neu
        erzeugte Vorschau.

        ``?speichern=1`` (Button "Herunterladen" der Versandmaske) liefert es
        als Download, sonst zur Anzeige im Browser. ``admin_view()`` setzt
        bereits never_cache.
        """
        self._leserecht_verlangen(request)
        pdf = self._pdf_modul()
        beleg = get_object_or_404(self.model, pk=pk)

        if beleg.pdf:
            try:
                beleg.pdf.open('rb')
            except FileNotFoundError as fehler:
                self.message_user(
                    request,
                    f'{beleg}: Das Dokument ist vermerkt, die Datei fehlt '
                    f'aber im Ablageverzeichnis ({fehler}).',
                    messages.ERROR,
                )
                return redirect(self._zurueck(request))
            antwort = FileResponse(
                beleg.pdf, content_type='application/pdf',
                filename=pdf.dateiname(beleg),
            )
        else:
            try:
                daten = pdf.beleg_als_pdf(beleg)
            except Exception as fehler:
                self.message_user(
                    request, f'PDF nicht möglich: {fehler}', messages.ERROR
                )
                return redirect(self._zurueck(request))
            antwort = HttpResponse(daten, content_type='application/pdf')

        art = 'attachment' if 'speichern' in request.GET else 'inline'
        antwort['Content-Disposition'] = (
            f'{art}; filename="{pdf.dateiname(beleg)}"'
        )
        return antwort

    def ansicht_xml(self, request, pk):
        """Liefert das gespeicherte XML als Download, etwa für ein
        Rechnungsportal. Nie neu erzeugt, auch nicht am Entwurf.

        Nur bei XRechnung, weil Empfänger ein einzelnes XML als XRechnung
        behandeln. Bei den übrigen Profilen ist das PDF die E-Rechnung und
        enthält das XML. Über die API ist es weiter abrufbar, dort mit
        Profil.
        """
        self._leserecht_verlangen(request)
        beleg = get_object_or_404(self.model, pk=pk)

        if not beleg.xml:
            self.message_user(
                request, f'Zu {beleg} ist kein XML abgelegt.', messages.ERROR)
            return redirect(self._zurueck(request))
        if beleg.erechnungsprofil != PROFIL_NAME_XRECHNUNG:
            self.message_user(
                request,
                f'{beleg} ist keine XRechnung. Die E-Rechnung steckt im PDF '
                f'(ZUGFeRD); das PDF ist die Datei für den Kunden.',
                messages.ERROR)
            return redirect(self._zurueck(request))
        try:
            beleg.xml.open('rb')
        except FileNotFoundError as fehler:
            self.message_user(
                request,
                f'{beleg}: Das XML ist vermerkt, die Datei fehlt aber im '
                f'Ablageverzeichnis ({fehler}).',
                messages.ERROR,
            )
            return redirect(self._zurueck(request))
        return FileResponse(
            beleg.xml, content_type='application/xml', as_attachment=True,
            filename=self._pdf_modul().dateiname(beleg, 'xml'),
        )

    def ansicht_fassung(self, request, pk, fassung_pk, art):
        """Datei einer abgelösten Fassung des Belegs."""
        self._leserecht_verlangen(request)
        beleg = get_object_or_404(self.model, pk=pk)
        fassung = get_object_or_404(beleg.fassungen, pk=fassung_pk)
        if (art not in ('pdf', 'xml') or not getattr(fassung, art)
                or (art == 'xml'
                    and fassung.erechnungsprofil != PROFIL_NAME_XRECHNUNG)):
            self.message_user(request, 'Diese Datei gibt es nicht.',
                              messages.ERROR)
            return redirect(self._zurueck(request))
        datei = getattr(fassung, art)
        try:
            datei.open('rb')
        except FileNotFoundError as fehler:
            self.message_user(
                request, f'Die Datei fehlt im Ablageverzeichnis ({fehler}).',
                messages.ERROR)
            return redirect(self._zurueck(request))
        stamm = self._pdf_modul().dateiname(beleg, art).rsplit('.', 1)[0]
        return FileResponse(
            datei,
            content_type='application/pdf' if art == 'pdf' else 'application/xml',
            as_attachment=True,
            filename=f'{stamm}_bis_{fassung.abgeloest_am:%Y%m%d-%H%M}.{art}',
        )

    @staticmethod
    def _zurueck(request) -> str:
        """Redirect nach einem Fehler auf den Referer, nur auf dem eigenen
        Host, weil der Referer vom Client kommt."""
        ziel = request.META.get('HTTP_REFERER', '')
        if ziel and url_has_allowed_host_and_scheme(
            ziel, allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return ziel
        return '..'

    def ansicht_html(self, request, pk):
        """Dasselbe Template als HTML für die Layoutarbeit, nicht verlinkt.
        Rechteprüfung wie beim PDF."""
        self._leserecht_verlangen(request)
        beleg = get_object_or_404(self.model, pk=pk)
        return HttpResponse(self._pdf_modul().beleg_als_html(beleg))

    @admin.display(description='Dokument')
    def _pdf_verweis(self, beleg):
        """Link auf das PDF."""
        basis = f'admin:{beleg._meta.app_label}_{beleg._meta.model_name}'
        return format_html(
            '<a href="{}" target="_blank">PDF</a>',
            reverse(f'{basis}_pdf', args=[beleg.pk]),
        )

    @admin.display(description='Dokument')
    def dokument(self, beleg):
        """Listenspalte mit PDF und, falls archiviert, Link ins Archiv.
        Prüfsummen stehen im Formular (``dokumentnachweis``)."""
        if beleg.pk is None:
            return '-'

        verweis = self._pdf_verweis(beleg)
        adresse = archiv.dokument_adresse(beleg)
        if not adresse:
            return verweis
        return format_html(
            '{} <span style="color:#666">&middot;</span> '
            '<a href="{}" target="_blank">Archiv</a>',
            verweis, adresse,
        )

    @admin.display(description='Dokument')
    def dokumentnachweis(self, beleg):
        """Feld im Formular: PDF und XML mit Prüfsumme (acht Stellen),
        Version des Templates und abgelöste Fassungen."""
        if beleg.pk is None:
            return '-'

        verweis = self._pdf_verweis(beleg)
        if not beleg.pdf:
            return verweis
        nachweis = format_html(
            '{} <span style="color:#666">&middot; SHA-256 {} &middot; '
            'Vorlage {}</span>',
            verweis, beleg.pdf_sha256[:8], beleg.vorlagenversion,
        )
        basis = f'admin:{beleg._meta.app_label}_{beleg._meta.model_name}'
        # Link nur bei XRechnung (siehe ``ansicht_xml``); sonst das XML ohne
        # Link, mit Prüfsumme.
        if beleg.xml and beleg.erechnungsprofil == PROFIL_NAME_XRECHNUNG:
            nachweis = format_html(
                '{}<br><a href="{}">XRechnung</a> <span style="color:#666">'
                '&middot; SHA-256 {}</span>',
                nachweis, reverse(f'{basis}_xml', args=[beleg.pk]),
                beleg.xml_sha256[:8],
            )
        elif beleg.xml:
            nachweis = format_html(
                '{}<br><span style="color:#666">E-Rechnung im PDF &middot; '
                'SHA-256 {} &middot; {}</span>',
                nachweis, beleg.xml_sha256[:8], beleg.erechnungsprofil,
            )
        for fassung in beleg.fassungen.all():
            arten = ['pdf']
            if fassung.xml and fassung.erechnungsprofil == PROFIL_NAME_XRECHNUNG:
                arten.append('xml')
            dateien = format_html_join(
                ' ', '<a href="{}">{}</a>',
                ((reverse(f'{basis}_fassung', args=[beleg.pk, fassung.pk, art]),
                  art.upper())
                 for art in arten if getattr(fassung, art)))
            nachweis = format_html(
                '{}<br><span style="color:#666">Frühere Fassung bis {}: </span>'
                '{} <span style="color:#666">&middot; {}</span>',
                nachweis,
                localtime(fassung.abgeloest_am).strftime('%d.%m.%Y %H:%M'),
                dateien, fassung.grund,
            )
        return nachweis

    @admin.display(description='Im Archiv')
    def archivverweis(self, beleg):
        """Archivstatus: Dokumentnummer mit Link, "wird abgelegt" (Upload
        läuft) oder "nicht archiviert"."""
        if beleg.pk is None:
            return '-'

        if beleg.paperless_id:
            adresse = archiv.dokument_adresse(beleg)
            marke = format_html(
                '<a href="{}" target="_blank">Dokument {}</a>',
                adresse, beleg.paperless_id,
            ) if adresse else f'Dokument {beleg.paperless_id}'
            if beleg.archiviert_am:
                return format_html(
                    '{} <span style="color:#666">&middot; {}</span>',
                    marke, localtime(beleg.archiviert_am).strftime('%d.%m.%Y %H:%M'),
                )
            return marke

        # mark_safe für festen Text, weil format_html Argumente verlangt.
        if beleg.paperless_task_id:
            return mark_safe(
                '<span style="color:#9a6700">wird abgelegt &hellip;</span>')

        return mark_safe('<span style="color:#666">nicht archiviert</span>')
