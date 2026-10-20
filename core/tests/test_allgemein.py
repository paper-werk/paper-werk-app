"""Tests der Systemprüfungen in ``core/checks.py``.

Die Prüfungen werden über den Seiteneffekt eines Imports in
``CoreConfig.ready()`` registriert. Entfernt jemand den scheinbar ungenutzten
Import, meldet ``manage.py check`` nichts mehr, ohne dass etwas fehlschlägt.
``run_checks()`` findet die Prüfung nur nach dem Import; die Tests prüfen so
Registrierung und Verhalten zugleich.
"""

from django.core.checks import Tags, run_checks

MINDESTLAENGE = {
    'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
}


def _sicherheitsbefunde():
    return run_checks(tags=[Tags.security], include_deployment_checks=True)


class TestPasswortregelnVorhanden:
    """Warnung bei leeren Passwortregeln, die ``check --deploy`` nicht prüft.

    Typischer Fall: Die ``.env.app`` eines Teststacks wird als Vorlage für eine
    Kundeninstallation kopiert.
    """

    def test_meldet_leere_regeln_im_betrieb(self, settings):
        settings.DEBUG = False
        settings.AUTH_PASSWORD_VALIDATORS = []

        assert any(b.id == 'paperwerk.W001' for b in _sicherheitsbefunde())

    def test_schweigt_wenn_regeln_da_sind(self, settings):
        """Gegenprobe: keine Warnung bei gesetzten Regeln."""
        settings.DEBUG = False
        settings.AUTH_PASSWORD_VALIDATORS = [MINDESTLAENGE]

        assert not any(b.id == 'paperwerk.W001' for b in _sicherheitsbefunde())

    def test_schweigt_in_der_entwicklung(self, settings):
        """Keine Warnung mit DEBUG, weil die Entwicklung ohne Passwortregeln
        läuft."""
        settings.DEBUG = True
        settings.AUTH_PASSWORD_VALIDATORS = []

        assert not any(b.id == 'paperwerk.W001' for b in _sicherheitsbefunde())

    def test_es_ist_eine_warnung_und_kein_fehler(self, settings):
        """Nur eine Warnung, weil eine Vorführinstallation mit
        Betriebseinstellungen trotzdem starten soll."""
        settings.DEBUG = False
        settings.AUTH_PASSWORD_VALIDATORS = []

        befund = next(b for b in _sicherheitsbefunde() if b.id == 'paperwerk.W001')

        assert befund.is_serious() is False
        assert 'DJANGO_EINFACHE_PASSWOERTER' in befund.hint
