from django.apps import AppConfig
from django.urls import reverse_lazy


class AuswertungConfig(AppConfig):
    """Startseite, Controlling und Akten über Daten aus faktura und erfassung.

    Eigene App, weil sie beide importiert; die Abhängigkeit verläuft
    auswertung, erfassung, faktura und nie umgekehrt. Ohne Modelle.
    """

    name = 'auswertung'
    verbose_name = 'Auswertung'

    def ready(self):
        """Registriert Einträge der Seitenleiste, URLs und Links der Akten und
        die Startseite (``core/erweiterungen.py``, Test:
        ``tests/test_seitenleiste.py``).

        Die Akten (Projekt, Auftrag, Rechnung, Kunde) haben eigene URLs, weil
        ``ProjektAdmin`` in ``faktura`` liegt, die Akte aber Belege und
        erfasste Leistung zeigt und ``faktura`` ``auswertung`` nicht
        importieren darf. ``admin.site.admin_view()`` sorgt für die
        Login-Prüfung.
        """
        from django.contrib import admin
        from django.urls import path, reverse

        from core import erweiterungen

        from . import (
            auftragsakte,
            controllingseite,
            dashboard,
            kundenakte,
            liegengeblieben,
            projektakte,
            rechnungsakte,
        )

        # Controlling betrifft den ganzen Betrieb und steht deshalb neben der
        # Startseite; unter "Leistung" stehen Einträge zu einzelnen
        # Vorhaben.
        erweiterungen.menue('Übersicht', separator=False, eintraege=[
            {
                'title': 'Controlling',
                'icon': 'monitoring',
                'link': reverse_lazy('controlling'),
                'permission': lambda r: r.user.has_perm(
                    'faktura.controlling_ansehen'),
                'rang': 20,
            },
        ])

        # Zwischen "Erfassung" und "Eingangsrechnungen" (erfassung/apps.py,
        # rang 10 und 30), weil die Liste der nicht abgerechneten Leistung
        # die tägliche Arbeitsliste ist.
        erweiterungen.menue('Leistung', collapsible=False, eintraege=[
            {
                'title': 'Nicht abgerechnet',
                'icon': 'savings',
                'link': reverse_lazy('liegengeblieben'),
                'permission': lambda r: r.user.has_perm(
                    'faktura.view_rechnung'),
                'rang': 20,
            },
        ])

        # Links "zur Akte" in Anzeigespalten von faktura und erfassung, siehe
        # core.erweiterungen.akte_url().
        erweiterungen.akte_verweis(
            'projekt', lambda pk: reverse('projektakte', args=[pk]))
        erweiterungen.akte_verweis(
            'auftrag', lambda pk: reverse('auftragsakte', args=[pk]))
        erweiterungen.akte_verweis(
            'rechnung', lambda pk: reverse('rechnungsakte', args=[pk]))
        erweiterungen.akte_verweis(
            'kunde', lambda pk: reverse('kundenakte', args=[pk]))

        erweiterungen.urls([
            path('admin/faktura/projekt/<int:pk>/akte/',
                 admin.site.admin_view(projektakte.akte), name='projektakte'),
            path('admin/faktura/auftrag/<int:pk>/akte/',
                 admin.site.admin_view(auftragsakte.akte), name='auftragsakte'),
            path('admin/faktura/rechnung/<int:pk>/akte/',
                 admin.site.admin_view(rechnungsakte.akte), name='rechnungsakte'),
            path('admin/faktura/kontakt/<int:pk>/akte/',
                 admin.site.admin_view(kundenakte.akte), name='kundenakte'),
            path('admin/nicht-abgerechnet/',
                 admin.site.admin_view(liegengeblieben.liegengeblieben),
                 name='liegengeblieben'),
            path('admin/controlling/',
                 admin.site.admin_view(controllingseite.controllingseite),
                 name='controlling'),
        ])

        erweiterungen.startseite(dashboard.startseite)
