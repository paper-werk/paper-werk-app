"""Settings für die Entwicklung.

``DJANGO_SETTINGS_MODULE=paperwerk.settings.dev`` ist die Vorgabe in
manage.py und in pyproject.toml für pytest.
"""

from .base import *  # noqa: F403

DEBUG = True

# Die Debug Toolbar steht in der dev-Dependency-Gruppe und ist im Betrieb
# nicht installiert. Eingebunden wird sie deshalb nur hier; aus base.py
# heraus ließe sich prod.py nicht laden.
INSTALLED_APPS += ['debug_toolbar']  # noqa: F405

# Als erste Middleware, damit sie die Antwort als äußerste Schicht sieht.
MIDDLEWARE.insert(0, 'debug_toolbar.middleware.DebugToolbarMiddleware')  # noqa: F405

# Die Toolbar erscheint nur für Requests von diesen Adressen.
INTERNAL_IPS = ['127.0.0.1']

# Kein echter Mailversand aus der Entwicklung, auch wenn die .env gültige
# SMTP-Zugangsdaten enthält. Die Testdaten haben erfundene Adressen, ein
# Tippfehler kann aber eine echte treffen.
#
# Der Versand läuft trotzdem vollständig durch; die Mail erscheint mit
# Hinweis auf die Anhänge in der Konsole des Entwicklungsservers.
#
# Echter Versand braucht zwei Angaben: EMAIL_HOST und EMAIL_ECHT_SENDEN=True.
# Eine von einer anderen Installation kopierte .env enthält nur die erste.
if not (env('EMAIL_HOST', default='')  # noqa: F405
        and env.bool('EMAIL_ECHT_SENDEN', default=False)):  # noqa: F405
    MAILERS = {
        'default': {
            'BACKEND': 'django.core.mail.backends.console.EmailBackend',
        },
    }

# Keine Passwortregeln in der Entwicklung, weil dort nur Testkonten
# entstehen. Diese Settings gelten nur mit manage.py runserver und pytest;
# im Container gilt prod.py, wo DJANGO_EINFACHE_PASSWOERTER nötig ist (siehe
# base.py).
AUTH_PASSWORD_VALIDATORS = []
