from django.apps import AppConfig
from django.urls import reverse_lazy


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = 'Benutzerverwaltung'

    def ready(self):
        """Registriert die Systemprüfungen und die Einträge der Seitenleiste.

        Der Import von ``checks`` wirkt über seinen Seiteneffekt: Erst er
        führt die ``@register``-Dekoratoren aus. Ohne ihn findet ``manage.py
        check`` die Prüfungen nicht. ``core/tests/test_allgemein.py`` sichert das über
        ``run_checks()`` ab, ``tests/test_seitenleiste.py`` die Seitenleiste.
        """
        from . import (
            checks,  # noqa: F401
            erweiterungen,
        )

        erweiterungen.menue(
            'Übersicht', separator=False, collapsible=False, eintraege=[
                {
                    'title': 'Startseite',
                    'icon': 'dashboard',
                    'link': reverse_lazy('admin:index'),
                },
            ])
        # Benutzer und Rechte, unabhängig von den Fachapps. ``rang`` stellt
        # die Gruppe ans Ende; ohne ihn stünde sie direkt hinter
        # "Übersicht", die in derselben ready() registriert wird.
        erweiterungen.menue('Verwaltung', collapsible=True, rang=50, eintraege=[
            {
                'title': 'Benutzer',
                'icon': 'person',
                'link': reverse_lazy('admin:core_user_changelist'),
                'permission': lambda r: r.user.has_perm('core.view_user'),
            },
            {
                'title': 'Gruppen',
                'icon': 'shield_person',
                'link': reverse_lazy('admin:auth_group_changelist'),
                'permission': lambda r: r.user.has_perm('auth.view_group'),
            },
            {
                'title': 'API-Schlüssel',
                'icon': 'key',
                'link': reverse_lazy('admin:authtoken_tokenproxy_changelist'),
                'permission': lambda r: r.user.has_perm(
                    'authtoken.view_tokenproxy'),
            },
        ])
