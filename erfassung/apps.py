from django.apps import AppConfig
from django.urls import reverse_lazy


class ZeitenConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'erfassung'
    verbose_name = 'Erfassung'

    def ready(self):
        """Registriert Einträge der Seitenleiste, Belegaktionen, eine
        Positionsprüfung, die App als fachlich und einen API-Endpunkt
        (``core/erweiterungen.py``; Tests: ``tests/test_seitenleiste.py``,
        ``tests/test_richtung.py``)."""
        from core import erweiterungen
        from faktura.models import BelegTyp

        from . import api as erfassung_api
        from . import nachweis
        from .admin import leistungen_hinzufuegen, nachweis_zur_rechnung
        from .services import hat_nachweis

        # Für die API-Selbstauskunft (core.schnittstelle.views.IchAnsicht).
        erweiterungen.fachliche_app('erfassung')

        # "eingangsrechnungen" gehört zur Archiv-Anbindung;
        # core/schnittstelle/urls.py importiert weder ViewSet noch Modell.
        erweiterungen.api_endpoint(
            'eingangsrechnungen', erfassung_api.EingangsrechnungViewSet,
            'eingangsrechnung')

        # "Erbrachte Leistungen hinzufügen" an der Rechnung;
        # faktura.admin.rechnung.RechnungAdmin setzt Methode und Recht über
        # ``belegaktionen(self.typ)``.
        erweiterungen.belegaktion(
            BelegTyp.RECHNUNG, 'detail_leistungen',
            leistungen_hinzufuegen.detail_leistungen,
            leistungen_hinzufuegen.has_leistungen_permission,
        )

        # Leistungsnachweis zur Rechnung: als Anlage in der Versandmaske und
        # als Vorschau an der Rechnung. Kein Beleg, wird nicht gespeichert.
        erweiterungen.beleganlage(BelegTyp.RECHNUNG, erweiterungen.Anlagenquelle(
            art=nachweis_zur_rechnung.ART,
            titel=nachweis_zur_rechnung.TITEL,
            hat_inhalt=hat_nachweis,
            pdf=nachweis.zur_rechnung_als_pdf,
        ))
        erweiterungen.belegaktion(
            BelegTyp.RECHNUNG, 'detail_leistungsnachweis',
            nachweis_zur_rechnung.detail_leistungsnachweis,
            nachweis_zur_rechnung.has_leistungsnachweis_permission,
        )

        # Positionsprüfung ohne Import in faktura: ``beleg_duplizieren``
        # kopiert keine Positionen aus Fremdleistungen.
        erweiterungen.positionsbezug(
            lambda position: position.fremdleistungen.exists())

        # Eingangsrechnungen stehen neben der eigenen Leistung, weil beide
        # den Aufwand eines Vorhabens zeigen. Dazwischen steht "Nicht
        # abgerechnet" (rang 20) aus auswertung (auswertung/apps.py).
        erweiterungen.menue('Leistung', collapsible=False, rang=30, eintraege=[
            {
                'title': 'Erfassung',
                'icon': 'schedule',
                'link': reverse_lazy(
                    'admin:erfassung_erfassungszeile_changelist'),
                'permission': lambda r: r.user.has_perm(
                    'erfassung.view_erfassungszeile'),
                'rang': 10,
            },
            {
                'title': 'Eingangsrechnungen',
                'icon': 'receipt_long',
                'link': reverse_lazy(
                    'admin:erfassung_eingangsrechnung_changelist'),
                'permission': lambda r: r.user.has_perm(
                    'erfassung.view_eingangsrechnung'),
                'rang': 30,
            },
            # Kein Eintrag "Fremdleistungen", weil in der Eingangsrechnung
            # zugeordnet wird. Die Liste bleibt registriert, weil die
            # Projektakte gefiltert auf sie verlinkt.
        ])

        # Zwischen Textbausteine und Eigene Firma (faktura/apps.py).
        erweiterungen.menue('Stammdaten', collapsible=True, eintraege=[
            {
                'title': 'Kostensätze',
                'icon': 'payments',
                'link': reverse_lazy('admin:erfassung_kostensatz_changelist'),
                'permission': lambda r: r.user.has_perm(
                    'erfassung.view_kostensatz'),
                'rang': 40,
            },
        ])
