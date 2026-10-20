"""Settings für den Betrieb.

``DJANGO_SETTINGS_MODULE=paperwerk.settings.prod`` ist im Dockerfile
gesetzt und gilt damit für jeden Container.
"""

from .base import *  # noqa: F403

DEBUG = False

# Statische Dateien liefert WhiteNoise aus, weil Django das bei DEBUG=False
# nicht tut. Der Manifest-Storage schreibt einen Hash in jeden Dateinamen,
# damit der Browser nach einem Update kein altes CSS zu neuem HTML lädt.
MIDDLEWARE.insert(  # noqa: F405
    MIDDLEWARE.index('django.middleware.security.SecurityMiddleware') + 1,  # noqa: F405
    'whitenoise.middleware.WhiteNoiseMiddleware',
)

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'paperwerk.statisch.OhneBrotli',
    },
}

# Source Maps (.map) nicht komprimieren. Sie werden nur von den Developer
# Tools geladen; die von Swagger und Redoc sind bis zu 4 MB groß, und ihre
# Kompression war der größte Posten im collectstatic-Schritt des Image-Builds.
from whitenoise.compress import Compressor  # noqa: E402

WHITENOISE_SKIP_COMPRESS_EXTENSIONS = [*Compressor.SKIP_COMPRESS_EXTENSIONS, 'map']

# Hinter dem Reverse Proxy kommt der Request per HTTP an, auch wenn der
# Browser HTTPS verwendet. Ohne den Header hält Django jeden Request für
# unverschlüsselt, und SECURE_SSL_REDIRECT erzeugt eine Redirect-Schleife.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Vertrauenswürdige Origins für POST. Muss die URL enthalten, unter der die
# Anwendung im Browser erreichbar ist, hinter einem Reverse Proxy also dessen
# Hostnamen.
CSRF_TRUSTED_ORIGINS = env.list('DJANGO_CSRF_TRUSTED_ORIGINS', default=[])  # noqa: F405

# Session- und CSRF-Cookies nur über HTTPS. Abschaltbar für einen Stack im
# lokalen Netz ohne Zertifikat; im Internet gilt die Vorgabe.
SESSION_COOKIE_SECURE = env.bool('DJANGO_COOKIE_SECURE', default=True)  # noqa: F405
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE

# Redirect auf HTTPS, Vorgabe aus.
#
# Django empfiehlt True; "check --deploy" meldet sonst security.W008. Die
# Warnung wird nicht über SILENCED_SYSTEM_CHECKS unterdrückt, weil eine
# Installation ohne TLS tatsächlich weniger sicher ist.
#
# Die Vorgabe ist trotzdem False, weil True ohne erreichbares HTTPS eine
# Redirect-Schleife erzeugt und die Anwendung dann nicht erreichbar ist.
SECURE_SSL_REDIRECT = env.bool('DJANGO_SSL_REDIRECT', default=False)  # noqa: F405

# Kein HSTS als Vorgabe.
#
# Der Header verpflichtet den Browser, die Domain für die angegebene Dauer
# nur über HTTPS aufzurufen, und lässt sich nicht zurücknehmen: Ein Wert von
# einem Jahr gilt beim Browser ein Jahr, auch wenn der Server ihn nicht mehr
# sendet. Bei einer Installation im Kundennetz mit unbekannter
# Zertifikatslage ist das als Vorgabe ungeeignet. Aktiviert wird HSTS über
# DJANGO_HSTS_SEKUNDEN.
#
# Mit gesetztem Wert meldet "check --deploy" W005 (INCLUDE_SUBDOMAINS) und
# W021 (PRELOAD). Beide sind ebenfalls nicht rücknehmbar, PRELOAD über eine
# Liste der Browser, aus der eine Domain nur auf Antrag und nach Monaten
# entfernt wird. Wer sie braucht, ergänzt sie hier.
SECURE_HSTS_SECONDS = env.int('DJANGO_HSTS_SEKUNDEN', default=0)  # noqa: F405
