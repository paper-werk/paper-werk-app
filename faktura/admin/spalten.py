"""Spalten und Summenzeile der Beleglisten. Angaben, die nur am einzelnen
Beleg gebraucht werden, stehen im Formular."""


from django.contrib import admin
from django.utils.formats import date_format
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.timezone import localtime
from unfold.decorators import display

from .. import formate, services
from ..models import (
    BelegStatus,
)


class SpaltenMixin:
    """Listenspalten und Summenzeile der Belegarten."""


    def changelist_view(self, request, extra_context=None):
        """Ergänzt die Summe der gefilterten Menge über alle Seiten
        (``cl.queryset``), nur mit Recht auf Rechnungen, wie auf der
        Startseite."""
        antwort = super().changelist_view(request, extra_context)

        if not request.user.has_perm('faktura.view_rechnung'):
            return antwort
        # Nach einer Aktion ist die Response ein Redirect ohne Kontext.
        if not hasattr(antwort, 'context_data'):
            return antwort
        liste = antwort.context_data.get('cl')
        if liste is None:
            return antwort

        summe = self._belegsumme(liste.queryset)
        # Keine Summenzeile über null Belegen.
        if summe['anzahl']:
            antwort.context_data['belegsumme'] = summe
        return antwort

    def get_queryset(self, request):
        """Lädt die Positionen vorab, weil "Brutto" und "Offen" je Zeile
        ``belegsummen`` berechnen; ohne Prefetch zwei Abfragen je Beleg,
        rund 200 je Seite (Lasttest)."""
        return super().get_queryset(request).prefetch_related('positionen')

    def _belegsumme(self, belege):
        """Netto, Steuer und Brutto über die Menge in einer Abfrage
        (``services.summe_ueber``)."""
        summe = services.summe_ueber(belege)
        return {
            'anzahl': summe.anzahl,
            'uebersprungen': summe.ohne_wert,
            'netto': summe.netto,
            'steuer': summe.steuer,
            'brutto': summe.brutto,
        }

    def get_list_display(self, request):
        """Ergänzt die Dokumentspalte, falls sie in ``list_display`` einer
        Belegart fehlt."""
        spalten = list(super().get_list_display(request))
        if 'dokument' not in spalten:
            spalten.append('dokument')
        return spalten

    @admin.display(description='Beleg', ordering='nummer')
    def bezeichnung(self, beleg):
        return str(beleg)

    @admin.display(description='Empfänger', ordering='empfaenger')
    def empfaenger_zeile(self, beleg):
        """Die erste Zeile des Anschriftfelds."""
        return beleg.empfaenger_kurz

    @admin.display(description='Projekt', ordering='projekt__nummer')
    def projekt_zeile(self, beleg):
        """Projekt des Belegs, leer bei einem Beleg am Kunden."""
        return beleg.projekt or ''

    # ``formatting='price'`` (Unfold): rechtsbündig in Kopf und Zelle, damit
    # Beträge stellengerecht untereinander stehen.
    @display(description='Brutto', formatting='price')
    def summe_brutto(self, beleg):
        return formate.geld_mit_waehrung(services.belegsummen(beleg).brutto)

    @staticmethod
    def _offen(beleg):
        """``offener_betrag`` einmal je Zeile, weil drei Spalten ihn brauchen
        (Offen, Zahlung, Fällig) und jeder Aufruf ``belegsummen`` rechnet."""
        if not hasattr(beleg, '_pw_offen'):
            beleg._pw_offen = services.offener_betrag(beleg)
        return beleg._pw_offen

    @display(description='Offen', formatting='price')
    def offener_betrag(self, beleg):
        """Offener Betrag; ohne offenen Betrag ein Strich, den Grund zeigt die
        Spalte "Zahlung". Am Entwurf leer. Nur in der Rechnungsliste."""
        if beleg.status == BelegStatus.ENTWURF:
            return ''
        offen = self._offen(beleg)
        if offen <= 0:
            return mark_safe(
                '<span class="text-font-subtle-light '
                'dark:text-font-subtle-dark">–</span>')
        return formate.geld_mit_waehrung(offen)

    @display(description='Zahlung', label={
        services.ZAHLUNGSSTAND_OFFEN: 'info',
        services.ZAHLUNGSSTAND_UEBER_FRIST: 'danger',
        services.ZAHLUNGSSTAND_BEZAHLT: 'success',
        services.ZAHLUNGSSTAND_ABGERECHNET: 'default',
    })
    def zahlungsstand(self, beleg):
        """Zahlungsstatus als Badge (R-176).

        Den Belegstatus zeigt die Spalte ``schloss``; diese Spalte zeigt nur,
        ob bezahlt ist. Am Entwurf und am Storno leer.
        """
        stand = services.zahlungsstand(beleg, offen=self._offen(beleg))
        if not stand:
            return None
        # Unfold setzt die Beschriftung in Großbuchstaben.
        return stand, services.ZAHLUNGSSTAND_TEXT[stand]

    @display(description='Fällig', ordering='faellig_am')
    def faelligkeit(self, beleg):
        """Fälligkeitsdatum mit Abstand, "+39 T" nach und "in 7 T" vor der
        Frist (R-150); der Abstand nur bei offenem Betrag."""
        if beleg.faellig_am is None:
            return ''
        datum = date_format(beleg.faellig_am, 'SHORT_DATE_FORMAT')
        if beleg.status != BelegStatus.FESTGESCHRIEBEN or self._offen(beleg) <= 0:
            return datum
        tage = services.tage_ueber_frist(beleg)
        if tage > 0:
            return format_html(
                '{} <span class="text-red-600 text-xs dark:text-red-500" '
                'title="{} Tage über der Frist">+{} T</span>', datum, tage, tage)
        return format_html(
            '{} <span class="text-font-subtle-light text-xs '
            'dark:text-font-subtle-dark" title="fällig in {} Tagen">in {} T</span>',
            datum, -tage, -tage)

    @admin.display(description='Summen')
    def summenaufstellung(self, beleg):
        """Aufteilung je Steuersatz wie auf dem Beleg."""
        if beleg.pk is None:
            return '-'
        summen = services.belegsummen(beleg)
        zeilen = format_html_join(
            '',
            '<tr><td style="padding-right:2em">Netto {}</td>'
            '<td align="right">{} EUR</td></tr>'
            '<tr><td style="padding-right:2em">USt {}</td>'
            '<td align="right">{} EUR</td></tr>',
            (
                (formate.prozent(a.satz), formate.geld(a.netto),
                 formate.prozent(a.satz), formate.geld(a.steuer))
                for a in summen.anteile
            ),
        )
        return format_html(
            # Abstand zwischen "Gesamt brutto" und Betrag.
            '<table>{}<tr><td style="padding-right:2em"><b>Gesamt brutto</b></td>'
            '<td align="right"><b>{}</b></td></tr></table>',
            zeilen,
            formate.geld_mit_waehrung(summen.brutto),
        )

    @admin.display(description='', ordering='status')
    def schloss(self, beleg):
        """Belegstatus als Symbol in der letzten Spalte: Schloss für
        festgeschrieben, eigenes Symbol für storniert, am Entwurf leer. Beide
        in derselben Farbe, weil ein Storno kein Fehler ist."""
        if beleg.status == BelegStatus.STORNIERT:
            return mark_safe(
                '<span class="material-symbols-outlined text-base-400" '
                'title="Storniert">block</span>')
        if beleg.ist_aenderbar:
            return ''
        return mark_safe(
            '<span class="material-symbols-outlined text-base-400" '
            'title="Festgeschrieben">lock</span>')

    @admin.display(description='Wiedereröffnet')
    def aenderungsvermerk(self, beleg):
        """Ob der Beleg nach dem Festschreiben wieder geöffnet wurde (GoBD).
        Nur im Tab "Status"."""
        if beleg.pk is None:
            return '-'
        if not beleg.geaendert_am:
            return mark_safe(
                '<span style="color:#666">seit der Festschreibung '
                'unverändert</span>')
        return format_html(
            'Zuletzt wieder geöffnet am {} von {}',
            localtime(beleg.geaendert_am).strftime('%d.%m.%Y %H:%M'),
            beleg.geaendert_von or 'unbekannt',
        )
