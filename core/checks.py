"""Eigene Systemprüfungen.

Ergänzt ``check --deploy`` um Fälle, die durch Einstellungen dieses
Projekts entstehen.
"""

from django.conf import settings
from django.core.checks import Warning, register

from core import marke


@register('security', deploy=True)
def passwortregeln_vorhanden(app_configs, **kwargs):
    """Warnt, wenn eine Anlage ohne DEBUG keine Passwortregeln hat.

    ``DJANGO_EINFACHE_PASSWOERTER`` leert ``AUTH_PASSWORD_VALIDATORS``, für
    Test- und Vorführinstallationen gedacht. Django hat keine eigene Prüfung
    auf leere Passwortregeln. Typischer Fall: Die ``.env.app`` eines
    Teststacks wird als Vorlage für eine Kundeninstallation kopiert.

    Nur eine Warnung, weil Vorführinstallationen mit Betriebseinstellungen
    laufen und trotzdem starten sollen.
    """
    if settings.DEBUG or settings.AUTH_PASSWORD_VALIDATORS:
        return []

    return [
        Warning(
            'AUTH_PASSWORD_VALIDATORS ist leer; diese Installation nimmt '
            'jedes Passwort an, auch "1234".',
            hint='Das kommt von DJANGO_EINFACHE_PASSWOERTER=True. Auf einer '
                 'Test- oder Vorführinstallation ist das gewollt; auf einer '
                 'Anlage mit echten Daten gehört der Schalter entfernt. '
                 'Django selbst meldet das nicht.',
            id='paperwerk.W001',
        )
    ]


@register()
def markenbilder_vorhanden(app_configs, **kwargs):
    """Warnt, wenn ein eingestelltes Logo oder Favicon nicht im Medienordner liegt.

    ``PAPER_WERK_MARKE_LOGO`` enthält einen Pfad unter ``MEDIA_ROOT``. Fehlt die
    Datei, gibt ``core.marke`` nichts zurück und Unfold zeigt ohne Meldung das
    Material-Symbol. Häufige Ursachen sind ein Tippfehler im Dateinamen und ein
    Logo, das nur auf dem Host liegt und nicht im Volume.

    Ohne ``deploy=True``, weil das Logo beim Einrichten gesetzt und danach mit
    ``manage.py check`` geprüft wird.
    """
    aus = []
    for variable, pfad in (
        ('PAPER_WERK_MARKE_LOGO', settings.MARKE_LOGO),
        ('PAPER_WERK_MARKE_LOGO_DUNKEL', settings.MARKE_LOGO_DUNKEL),
        ('PAPER_WERK_MARKE_FAVICON', settings.MARKE_FAVICON),
    ):
        if pfad and not marke.medien_adresse(pfad):
            aus.append(Warning(
                f'{variable} zeigt auf "{pfad}"; dort liegt im Medienordner '
                f'keine Datei.',
                hint=f'Erwartet wird ein Pfad INNERHALB des Medienordners '
                     f'({settings.MEDIA_ROOT}), also "marke/logo.svg" und '
                     f'nicht der ganze Pfad von der Wurzel her. Im Container '
                     f'ist der Medienordner das Volume unter /app/media; ein '
                     f'Logo, das nur auf dem Host liegt, kommt dort nicht an. '
                     f'Solange die Datei fehlt, zeigt die Oberfläche das '
                     f'Material-Symbol, ohne Fehlermeldung.',
                id='paperwerk.W002',
            ))

    return aus
