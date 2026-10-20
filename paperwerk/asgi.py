"""
ASGI config for paperwerk project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/3.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

# Vorgabe prod, anders als in manage.py. Gunicorn lädt dieses Modul im
# Betrieb; mit dev als Vorgabe ergäbe eine fehlende Umgebungsvariable
# DEBUG=True mit Stacktraces samt Datenbankzugang. In der Entwicklung fällt
# prod dagegen sofort auf.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'paperwerk.settings.prod')

application = get_asgi_application()
