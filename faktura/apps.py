from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.urls import reverse_lazy


class FakturaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'faktura'

    def ready(self):
        """Registriert die Einträge der Seitenleiste und die App als fachlich
        (``core/erweiterungen.py``; Tests: ``tests/test_seitenleiste.py``,
        ``core/schnittstelle/``)."""
        from core import erweiterungen

        from . import api as faktura_api
        from .models.steuersatz import grundausstattung_anlegen

        # Anfangsbestand der Steuersätze, siehe faktura/models/steuersatz.py.
        post_migrate.connect(grundausstattung_anlegen, sender=self)

        # Für die API-Selbstauskunft (core.schnittstelle.views.IchAnsicht).
        erweiterungen.fachliche_app('faktura')

        # Die schmale Belegauskunft der Archiv-Anbindung (XML zum
        # Steuerberater), siehe faktura/api.py.
        erweiterungen.api_endpoint(
            'belege', faktura_api.BelegAnbindungViewSet, 'beleg')

        # Abschnitt Vorhaben in der Reihenfolge des Ablaufs: Projekt,
        # Angebot, Auftrag, Lieferschein.
        erweiterungen.menue('Projekte', collapsible=False, rang=10, eintraege=[
            {
                'title': 'Projekte',
                'icon': 'construction',
                'link': reverse_lazy('admin:faktura_projekt_changelist'),
                'permission': lambda r: r.user.has_perm('faktura.view_projekt'),
            },
            {
                'title': 'Angebote',
                'icon': 'request_quote',
                'link': reverse_lazy('admin:faktura_angebot_changelist'),
                'permission': lambda r: r.user.has_perm('faktura.view_angebot'),
            },
            {
                'title': 'Aufträge',
                'icon': 'handshake',
                'link': reverse_lazy('admin:faktura_auftrag_changelist'),
                'permission': lambda r: r.user.has_perm(
                    'faktura.view_auftrag'),
            },
            # Nach dem Auftrag, weil sie ihn abschließt; aus ihr entsteht
            # die (Teil-)Schlussrechnung.
            {
                'title': 'Abnahmen',
                'icon': 'task_alt',
                'link': reverse_lazy('admin:faktura_abnahme_changelist'),
                'permission': lambda r: r.user.has_perm(
                    'faktura.view_abnahme'),
            },
            {
                'title': 'Lieferscheine',
                'icon': 'local_shipping',
                'link': reverse_lazy(
                    'admin:faktura_lieferschein_changelist'),
                'permission': lambda r: r.user.has_perm(
                    'faktura.view_lieferschein'),
            },
        ])

        # Abschnitt Rechnungen in der Reihenfolge des Ablaufs: Abschlag,
        # Schluss, Rechnung, Mahnung, Zahlung. Storno, Korrektur und
        # Teilschluss stehen im eingeklappten Abschnitt darunter.
        erweiterungen.menue('Rechnungen', collapsible=False, rang=20, eintraege=[
            {
                'title': 'Rechnungen',
                'icon': 'receipt_long',
                'link': reverse_lazy('admin:faktura_rechnung_changelist'),
                'permission': lambda r: r.user.has_perm(
                    'faktura.view_rechnung'),
                # Zahl der Entwürfe (faktura/zaehler.py), je Rechnungsart.
                # Ein Zähler "über Frist" kostete bei zehn Jahren Daten 0,1 s
                # auf jeder Seite (gemessen); überfällige Rechnungen zeigen
                # Startseite und Liste.
                'badge': 'faktura.zaehler.rechnungsentwuerfe',
                'badge_variant': 'primary',
            },
            {
                'title': 'Abschlagsrechnungen',
                'icon': 'hourglass_top',
                'link': reverse_lazy(
                    'admin:faktura_abschlagsrechnung_changelist'),
                'permission': lambda r: r.user.has_perm(
                    'faktura.view_abschlagsrechnung'),
                'badge': 'faktura.zaehler.abschlagsentwuerfe',
                'badge_variant': 'primary',
            },
            {
                'title': 'Schlussrechnungen',
                'icon': 'done_all',
                'link': reverse_lazy(
                    'admin:faktura_schlussrechnung_changelist'),
                'permission': lambda r: r.user.has_perm(
                    'faktura.view_schlussrechnung'),
                'badge': 'faktura.zaehler.schlussentwuerfe',
                'badge_variant': 'primary',
            },
            {
                'title': 'Mahnungen',
                'icon': 'notification_important',
                'link': reverse_lazy('admin:faktura_mahnung_changelist'),
                'permission': lambda r: r.user.has_perm(
                    'faktura.view_mahnung'),
            },
            {
                'title': 'Zahlungseingänge',
                'icon': 'payments',
                'link': reverse_lazy('admin:faktura_zahlung_changelist'),
                'permission': lambda r: r.user.has_perm(
                    'faktura.view_zahlung'),
            },
        ])

        # Selten gebrauchte Belegarten, die aus einer Akte entstehen:
        # Teilschluss aus der Abnahme, Storno und Korrektur aus der Rechnung.
        # Eingeklappt, damit die Seitenleiste nicht scrollt.
        erweiterungen.menue('Weitere Rechnungsarten', collapsible=True, rang=25,
                            eintraege=[
            # Liste ohne "Hinzufügen", weil Teilschlussrechnungen aus einer
            # Teilabnahme in der Auftragsakte entstehen.
            {
                'title': 'Teilschlussrechnungen',
                'icon': 'rule',
                'link': reverse_lazy(
                    'admin:faktura_teilschlussrechnung_changelist'),
                'permission': lambda r: r.user.has_perm(
                    'faktura.view_teilschlussrechnung'),
                'badge': 'faktura.zaehler.teilschlussentwuerfe',
                'badge_variant': 'primary',
            },
            {
                'title': 'Stornorechnungen',
                'icon': 'undo',
                'link': reverse_lazy(
                    'admin:faktura_stornorechnung_changelist'),
                'permission': lambda r: r.user.has_perm(
                    'faktura.view_stornorechnung'),
            },
            {
                'title': 'Rechnungskorrekturen',
                'icon': 'edit_document',
                'link': reverse_lazy(
                    'admin:faktura_rechnungskorrektur_changelist'),
                'permission': lambda r: r.user.has_perm(
                    'faktura.view_rechnungskorrektur'),
            },
        ])

        # Tabs der Rechnungsliste nach anstehender Arbeit. Sie setzen
        # vorhandene Filter; "Über Frist" sortiert zusätzlich nach "Fällig",
        # älteste zuerst.
        erweiterungen.reiter('faktura.rechnung', _rechnungsreiter())

        # Kontakte, Projekte, Belege und Beträge in der Schnellsuche
        # (Strg+K), siehe faktura/suche.py.
        from . import suche
        erweiterungen.suche(suche.treffer)

        # Stammdaten mit Lücke im ``rang`` (10/20/30/45/50) für die
        # Kostensätze aus ``erfassung`` (40) zwischen Textbausteinen und
        # Steuersätzen (erfassung/apps.py).
        erweiterungen.menue('Stammdaten', collapsible=True, rang=40, eintraege=[
            {
                'title': 'Kontakte',
                'icon': 'groups',
                'link': reverse_lazy('admin:faktura_kontakt_changelist'),
                'permission': lambda r: r.user.has_perm('faktura.view_kontakt'),
                'rang': 10,
            },
            {
                'title': 'Leistungskatalog',
                'icon': 'format_list_bulleted',
                'link': reverse_lazy(
                    'admin:faktura_katalogposition_changelist'),
                'permission': lambda r: r.user.has_perm(
                    'faktura.view_katalogposition'),
                'rang': 20,
            },
            {
                'title': 'Textbausteine',
                'icon': 'notes',
                'link': reverse_lazy('admin:faktura_textbaustein_changelist'),
                'permission': lambda r: r.user.has_perm(
                    'faktura.view_textbaustein'),
                'rang': 30,
            },
            {
                'title': 'Steuersätze',
                'icon': 'percent',
                'link': reverse_lazy('admin:faktura_steuersatz_changelist'),
                'permission': lambda r: r.user.has_perm(
                    'faktura.view_steuersatz'),
                'rang': 45,
            },
            {
                'title': 'Eigene Firma',
                'icon': 'apartment',
                'link': reverse_lazy('admin:faktura_firma_changelist'),
                'permission': lambda r: r.user.has_perm('faktura.view_firma'),
                'rang': 50,
            },
        ])


#: Filter, die ein Tab der Rechnungsliste setzt; ohne einen gilt "Alle".
_REITERFILTER = ('status__exact', 'zahlungsstand')


def _rechnungsreiter() -> list[dict]:
    """Tabs über der Rechnungsliste.

    "Alle" hat eine eigene Regel, weil Unfold einen Tab als aktiv
    markiert, wenn der Request alle seine Parameter enthält; ohne Parameter
    wäre er immer aktiv.

    "Über Frist" sortiert mit ``o=4``, Spalte vier einschließlich Checkbox
    (``RechnungAdmin.list_display``, "faelligkeit"). Verschiebt sich die
    Spalte, schlägt ``faktura/tests/test_listen.py`` fehl.
    """
    from urllib.parse import urlencode

    from django.urls import reverse

    def liste(**filter):
        return lambda request: (reverse('admin:faktura_rechnung_changelist')
                                + ('?' + urlencode(filter) if filter else ''))

    def alle_aktiv(request):
        return not any(k in request.GET for k in _REITERFILTER)

    return [
        {'title': 'Alle', 'link': liste(), 'active': alle_aktiv},
        {'title': 'Entwürfe', 'link': liste(status__exact='entwurf')},
        {'title': 'Offen', 'link': liste(zahlungsstand='offen')},
        {'title': 'Über Frist', 'link': liste(zahlungsstand='ueberfaellig', o='4')},
        {'title': 'Bezahlt', 'link': liste(zahlungsstand='bezahlt')},
    ]
