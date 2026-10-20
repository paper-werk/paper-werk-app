from django.apps import AppConfig
from django.urls import reverse_lazy


class HilfeConfig(AppConfig):
    """Bedienungsanleitung unter ``/hilfe/`` und als PDF.

    Quelle sind die Markdown-Dateien in ``hilfe/texte/``, versioniert mit dem
    Code: Jede Installation zeigt die Anleitung ihrer eigenen Version.
    Keine Modelle.
    """

    name = 'hilfe'
    verbose_name = 'Hilfe'

    def ready(self):
        """Registriert Seite und Eintrag der Seitenleiste. ``admin_view()``
        verlangt Anmeldung; ein weiteres Recht gibt es nicht, weil jeder
        Benutzer die Anleitung lesen darf."""
        from django.contrib import admin
        from django.urls import path

        from core import erweiterungen

        from . import views

        erweiterungen.menue('Hilfe', collapsible=False, rang=60, eintraege=[
            {
                'title': 'Bedienungsanleitung',
                'icon': 'help',
                'link': reverse_lazy('hilfe'),
            },
        ])

        erweiterungen.urls([
            path('hilfe/', admin.site.admin_view(views.seite), name='hilfe'),
        ])
