"""Gemeinsame Settings für Entwicklung und Betrieb.

Nie direkt als DJANGO_SETTINGS_MODULE verwendet. ``paperwerk.settings.dev``
und ``paperwerk.settings.prod`` importieren dieses Modul und setzen nur die
Abweichungen.

Der Betriebsmodus ergibt sich aus dem Modulnamen und kann deshalb nicht
fehlen; ein falscher Name verhindert den Start.

https://docs.djangoproject.com/en/6.1/topics/settings/
https://docs.djangoproject.com/en/6.1/ref/settings/
"""

from pathlib import Path

import environ

# Drei Mal .parent, weil die Datei zwei Ebenen unter der Projektwurzel liegt.
# read_env() meldet eine fehlende .env nicht; ein falsches BASE_DIR fiele erst
# beim SECRET_KEY auf.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Werte, die sich zwischen Entwicklung und Betrieb unterscheiden oder geheim
# sind, kommen aus der Umgebung. django-environ liest dazu die .env (nicht
# versioniert, Vorlage .env.example).
env = environ.Env(
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    GTK_BIN_DIR=(str, ""),
)
environ.Env.read_env(BASE_DIR / ".env")

# SECURITY WARNING: keep the secret key used in production secret!
# Ohne Default: Fehlt der Wert, schlägt der Start fehl.
SECRET_KEY = env("DJANGO_SECRET_KEY")

# DEBUG setzen dev.py und prod.py.

ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")


# Application definition

INSTALLED_APPS = [
    # Oberfläche des Admin.
    #
    # unfold.apps.DefaultAppConfig.ready() ersetzt ``admin.site`` durch
    # eine eigene AdminSite; SITE_HEADER/SITE_TITLE haben Vorrang vor den
    # Titeln in paperwerk/urls.py.
    'unfold',
    # Filterfelder mit Bereichsauswahl (Datum von/bis, Zahl von/bis).
    'unfold.contrib.filters',
    # Import- und Exportmasken im Stil von Unfold. Vor import_export, weil
    # die Templates gleich heißen und bei APP_DIRS die erste App gilt.
    'unfold.contrib.import_export',
    # Masken der Änderungshistorie im Stil von Unfold, vor simple_history
    # aus demselben Grund.
    'unfold.contrib.simple_history',
    'django.contrib.admin',
    'django.contrib.sessions',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_filters',
    # Import und Export von Tabellen (CSV, XLSX, JSON), etwa für den
    # Leistungskatalog und Preisänderungen.
    'import_export',
    'rest_framework',
    # API-Schlüssel: einer je Benutzer, unbegrenzt gültig, im Admin
    # löschbar, wie bei Paperless-ngx.
    'rest_framework.authtoken',
    # SSO über einen OIDC-Anbieter (Entra ID) mit dem generischen
    # OIDC-Provider, siehe core/anmeldung.py. allauth.account ist auch ohne
    # eigene Anmeldeseite nötig.
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.openid_connect',
    # Lückenlose Nummernkreise in einer eigenen Tabelle.
    'sequences.apps.SequencesConfig',
    # OpenAPI-Schema aus dem Code; der Sidecar liefert die Doku-Dateien
    # ohne CDN.
    'drf_spectacular',
    'drf_spectacular_sidecar',
    # Änderungshistorie (GoBD): je Modell eine Tabelle mit jedem früheren
    # Stand, Benutzer und Zeitpunkt.
    'simple_history',
    'core',
    'faktura',
    # Leistungserfassung: Zeiten, Anfahrten, Material. Abhängig von
    # faktura.Projekt; für eine eigenständige Auslieferung müssten Projekt
    # und Kunde in eine gemeinsame App.
    'erfassung',
    # Startseite, Controlling, Akten über faktura und erfassung.
    'auswertung',
    # Bedienungsanleitung unter /hilfe/ und als PDF. Nicht optional, weil
    # sie core, faktura und erfassung beschreibt.
    'hilfe',
]

# --- Zusatz-Haken ------------------------------------------------------------
#
# Ein Zusatz ist eine Django-App außerhalb dieses Repos. Eine Installation
# mountet sie in den Container (etwa nach
# /opt/paperwerk-zusatz/paperwerk_pruefung) und trägt sie in
# PAPERWERK_ZUSATZAPPS ein. Kein Modul dieses Repos importiert einen Zusatz;
# er registriert sich wie die eigenen Apps über core/erweiterungen.py.
# /opt/paperwerk-premium ist der frühere Pfad, auf den bestehende
# Installationen noch mounten.
import sys  # noqa: E402

PAPERWERK_ZUSATZPFAD = '/opt/paperwerk-zusatz'
sys.path += [PAPERWERK_ZUSATZPFAD, '/opt/paperwerk-premium']
INSTALLED_APPS += env.list('PAPERWERK_ZUSATZAPPS', default=[])

# --- Weglassbare Apps -------------------------------------------------------
#
# Kern heißen die Apps, die sich nicht abschalten lassen: ``core``,
# ``faktura``, ``erfassung`` und ``hilfe``. Sie tragen die GoBD-Pflichten
# (docs/entscheidungen.md, Grundsätze). Optional ist nur ``auswertung``.
# PAPERWERK_OHNE_APPS wird gegen eine Allowlist geprüft; ein Eintrag wie
# "PAPERWERK_OHNE_APPS=faktura" verhindert den Start mit
# ImproperlyConfigured.
PAPERWERK_OPTIONALE_APPS = {'auswertung'}
_ohne_apps = set(env.list('PAPERWERK_OHNE_APPS', default=[]))
_unbekannt = _ohne_apps - PAPERWERK_OPTIONALE_APPS
if _unbekannt:
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured(
        f'PAPERWERK_OHNE_APPS nennt Apps, die nicht optional sind: '
        f'{sorted(_unbekannt)}. Optional sind nur: '
        f'{sorted(PAPERWERK_OPTIONALE_APPS)}.')
INSTALLED_APPS = [app for app in INSTALLED_APPS if app not in _ohne_apps]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Von allauth vorausgesetzt; ohne sie startet die Anwendung nicht.
    'allauth.account.middleware.AccountMiddleware',
    # Speichert den Request, damit die Historie den Benutzer erfasst. Gilt
    # auch für die API: DRF authentifiziert in der View und setzt den
    # Benutzer dabei im Django-Request.
    'simple_history.middleware.HistoryRequestMiddleware',
]

# Die Debug Toolbar bindet dev.py ein; im Betrieb ist sie nicht installiert.


# Eigene Cookie-Namen, weil Cookies nicht nach Port getrennt werden (RFC 6265,
# 8.5) und Paperless-ngx auf demselben Host mit Djangos Vorgaben "sessionid"
# und "csrftoken" die Session überschreibt. Umbenannt wird auf dieser Seite,
# weil die Konfiguration von Paperless nicht zu diesem Projekt gehört.
SESSION_COOKIE_NAME = 'paperwerk_sessionid'
CSRF_COOKIE_NAME = 'paperwerk_csrftoken'

ROOT_URLCONF = 'paperwerk.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        # Für ``admin/index.html`` (Startseite): unfold liefert ein Template
        # gleichen Namens und steht in INSTALLED_APPS vorn; DIRS wird vor
        # allen Apps durchsucht.
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                # Button "Anmelden mit ..." auf der Anmeldeseite des
                # Admin; leer ohne SSO_CLIENT_ID.
                'core.anmeldung.sso_anmeldung',
                # Name der Anwendung für alle Templates. Unfold setzt ihn
                # nur im Admin; die Anmeldeseiten liegen zum Teil
                # außerhalb (core/marke.py).
                'core.marke.marke',
                # Versionsnummer unten in der Seitenleiste, Quelle ist
                # pyproject.toml (core/version.py).
                'core.version.version',
            ],
        },
    },
]

WSGI_APPLICATION = 'paperwerk.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases
#
# PostgreSQL über psycopg 3, konfiguriert über DATABASE_URL. Im Stack ist das
# der Container paper-werk-db (paper-werk).

DATABASES = {
    'default': env.db('DATABASE_URL'),
}

# Keine parallelen Abfragen. PostgreSQL startet für Abfragen über einige
# zehntausend Zeilen einen Parallel Worker; dessen Start kostete im Lasttest
# (Docker Desktop) rund 60 ms, die Abfrage selbst 3 ms. Bei den Datenmengen
# dieser Anwendung (nach zehn Jahren unter 100 MB) bringt Parallelität
# nichts: Ohne sie waren Startseite und Controlling doppelt so schnell, keine
# Seite wurde langsamer. Gesetzt in der App, damit es für jede Datenbank
# gilt, auch in der Entwicklung.
DATABASES['default'].setdefault('OPTIONS', {})['options'] = (
    '-c max_parallel_workers_per_gather=0')


# Password validation
# https://docs.djangoproject.com/en/3.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Einfache Passwörter für Test- und Vorführinstallationen. Ein eigener
# Schalter, weil jeder Container mit prod und damit DEBUG=False läuft, auch
# der Teststack. core/checks.py warnt, wenn er ohne DEBUG gesetzt ist.
if env.bool('DJANGO_EINFACHE_PASSWOERTER', default=False):
    AUTH_PASSWORD_VALIDATORS = []


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

# Deutsch einschließlich der Formate: 13.08.2026, Dezimalkomma ("1234,56").
# Siehe USE_THOUSAND_SEPARATOR.
LANGUAGE_CODE = 'de-de'

# Nur für die Anzeige; gespeichert wird UTC (USE_TZ).
TIME_ZONE = 'Europe/Berlin'

USE_I18N = True

# Überschreibt einzelne Übersetzungen von Django; LOCALE_PATHS hat Vorrang.
# locale/de/LC_MESSAGES/django.po enthält nur die abweichenden Einträge,
# wirksam nach "manage.py compilemessages".
LOCALE_PATHS = [BASE_DIR / 'locale']

# Deutsche Datumsformate auch in den Settings, weil Unfolds Datumsfilter
# ``settings.DATE_INPUT_FORMATS`` direkt liest (``unfold.utils.parse_date_str``)
# und mit Djangos amerikanischer Vorgabe ohne Fehlermeldung nichts filterte.
# ISO bleibt für Links von Startseite und Controlling. import_export
# exportiert Datumsfelder im ersten Format der Liste.
#
# DATETIME_INPUT_FORMATS ist nicht gesetzt; ein RangeDateTimeFilter hätte
# dasselbe Problem (``parse_datetime_str``).
DATE_INPUT_FORMATS = ['%d.%m.%Y', '%d.%m.%y', '%Y-%m-%d']

# Anzeige von Datum und Zeitpunkt als 28.07.2026. Djangos deutsches Locale
# schreibt den Monat aus ("28. Juli 2026"), wodurch Listen mit zwei
# Datumsspalten umbrechen. Das Modul überschreibt nur DATE_FORMAT und
# DATETIME_FORMAT. Belege und Masken setzen ihr Format selbst.
FORMAT_MODULE_PATH = ['paperwerk.datumsformate']

# Aus, weil Django mit True den Punkt als Tausendertrennzeichen liest und
# Eingaben mit drei Nachkommastellen mehrdeutig werden:
#
#   Eingabe "1.500"   mit False -> 1,5     mit True -> 1500
#
# Betroffen wäre vor allem Belegposition.menge. Test:
# faktura/tests/test_lokalisierung.py.
USE_THOUSAND_SEPARATOR = False

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/3.2/howto/static-files/

STATIC_URL = '/static/'

# Ziel von "manage.py collectstatic", gesetzt, damit der Befehl auch in der
# Entwicklung läuft.
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'

# Ablage der festgeschriebenen Beleg-PDFs, im Container /app/media auf einem
# Volume. Teilen sich Container und runserver eine Datenbank, müssen sie
# auch denselben Ordner verwenden, weil die Datenbank nur relative Pfade
# speichert.
MEDIA_ROOT = env('DJANGO_MEDIA_ROOT', default=str(BASE_DIR / 'media'))


# --- Import und Export (django-import-export) -------------------------------
#
# Der Import läuft in einer Transaktion. Das ist die Vorgabe, hier explizit
# gesetzt.
IMPORT_EXPORT_USE_TRANSACTIONS = True

# Nur gebräuchliche Formate. Als Klassen, weil das Paket die Einträge
# aufruft; ein Pfad als String schlüge erst beim Öffnen der Maske fehl.
from import_export.formats import base_formats  # noqa: E402

IMPORT_EXPORT_FORMATS = [
    base_formats.XLSX,
    base_formats.CSV,
    base_formats.JSON,
]

# Import verlangt das Änderungsrecht, Export das Ansichtsrecht.
IMPORT_EXPORT_IMPORT_PERMISSION_CODE = 'change'
IMPORT_EXPORT_EXPORT_PERMISSION_CODE = 'view'


# --- Name und Logo der Anwendung ---------------------------------------------
#
# Siehe core/marke.py. In base.py, damit Entwicklung und Tests dieselben
# Werte verwenden wie der Betrieb.

# Leer ergibt die Vorgabe.
MARKE_NAME = env('PAPER_WERK_MARKE_NAME', default='').strip() or 'Paper-Werk'

# Leer blendet den Untertitel aus.
MARKE_UNTERTITEL = env(
    'PAPER_WERK_MARKE_UNTERTITEL', default='Faktura, Projekte, Controlling')

# Material-Symbol, angezeigt ohne Logo.
MARKE_SYMBOL = env('PAPER_WERK_MARKE_SYMBOL', default='').strip() or 'finance_mode'

# Pfade relativ zu MEDIA_ROOT, etwa "marke/logo.svg". Keine URLs und keine
# absoluten Pfade, weil nur Dateien unter MEDIA_ROOT über "/media/"
# ausgeliefert werden (siehe core.marke.medien_adresse).
MARKE_LOGO = env('PAPER_WERK_MARKE_LOGO', default='').strip()
MARKE_LOGO_DUNKEL = env('PAPER_WERK_MARKE_LOGO_DUNKEL', default='').strip()
MARKE_FAVICON = env('PAPER_WERK_MARKE_FAVICON', default='').strip()

# Ziel von "Webseite anzeigen" im Benutzermenü, gedacht für die Webseite des
# Betriebs.
MARKE_WEBSEITE = env('PAPER_WERK_MARKE_WEBSEITE',
                     default='https://www.ki-werkstatt.net')


# --- Oberfläche des Admin (django-unfold) -----------------------------------
#
# Farben, Seitenleiste und Startseite: paperwerk/settings/unfold.py.
from .unfold import UNFOLD  # noqa: E402, F401

# PDF-Erzeugung (WeasyPrint)
#
# Nur unter Windows: GTK3-Verzeichnis für Pango (WeasyPrint). Python
# ignoriert PATH beim Laden von DLLs; faktura/pdf.py registriert es.
GTK_BIN_DIR = env('GTK_BIN_DIR')

# --- Archiv (Paperless-ngx) --------------------------------------------------
#
# Beim Festschreiben lädt die App das Beleg-PDF direkt ins Archiv hoch, ohne
# n8n. Das Archiv hält eine Kopie; maßgeblich bleibt media/ (geprüft von
# "pruefe_belegarchiv"), weil in Paperless Benutzer Dokumente löschen können.
#
# URL aus Sicht der App:
#   im Stack       http://paperless:8000   (Servicename im Compose-Netz)
#   bei runserver  http://localhost:8005   (der veröffentlichte Port)
PAPERLESS_URL = env('PAPERLESS_URL', default='').rstrip('/')

# URL des Archivs für den Browser des Benutzers.
#
# PAPERLESS_URL gilt nur im Compose-Netz. Leer bedeutet PAPERLESS_URL;
# richtig bei runserver, im Container muss der Wert gesetzt sein.
PAPERLESS_ANSICHT_URL = env('PAPERLESS_ANSICHT_URL', default='').rstrip('/')

# API-Token eines Paperless-Benutzers, Header "Authorization: Token <key>".
#   docker exec <paperless> python3 manage.py drf_create_token <benutzer>
PAPERLESS_TOKEN = env('PAPERLESS_TOKEN', default='')

# Ausgeschaltet wird nichts hochgeladen. Vorgabe aus, damit eine Kopie der
# Datenbank keine Dokumente ins Archiv schickt.
PAPERLESS_ARCHIVIERUNG = env.bool('PAPERLESS_ARCHIVIERUNG', default=False)

# Timeout je HTTP-Request in Sekunden; requests hat ohne Angabe keinen.
PAPERLESS_TIMEOUT = env.int('PAPERLESS_TIMEOUT', default=10)

# Ob das Festschreiben auf das Archiv wartet.
#
# Aus: hochladen ohne zu warten, weil Paperless die Dokumentnummer erst nach
# einigen Sekunden liefert. Die Task-ID bleibt am Beleg, die Dokumentnummer
# holt "manage.py belege_archivieren" nach. Läuft dieser Befehl nicht
# regelmäßig, den Wert auf True setzen.
PAPERLESS_WARTEN_BEIM_FESTSCHREIBEN = env.bool(
    'PAPERLESS_WARTEN_BEIM_FESTSCHREIBEN', default=False)

# ---------------------------------------------------------------------------
# Postausgang
# ---------------------------------------------------------------------------
#
# Versand über eigenes SMTP, damit der Rechnungsversand nicht von einem
# laufenden n8n-Workflow abhängt.
SMTP_HOST = env('EMAIL_HOST', default='')

# Absender. Leer bedeutet die Adresse aus den Firmenstammdaten
# (``services.absenderadresse()``). Manche SMTP-Server akzeptieren nur eine
# bestimmte Adresse.
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='')

# Keine Einstellung darf Versenden oder Festschreiben ausblenden
# (docs/entscheidungen.md).

# BCC an Firma.email, als Ersatz für den Ordner "Gesendet".
FAKTURA_VERSAND_KOPIE = env.bool('FAKTURA_VERSAND_KOPIE', default=True)

# Ohne SMTP_HOST schreibt Django die Mail auf die Konsole, damit sich eine
# neue Installation ohne echten Versand testen lässt. MAILERS, weil
# Django 6.1 die EMAIL_*-Settings als veraltet markiert.
MAILERS = {
    'default': {
        'BACKEND': ('django.core.mail.backends.smtp.EmailBackend' if SMTP_HOST
                    else 'django.core.mail.backends.console.EmailBackend'),
        'OPTIONS': {
            'host': SMTP_HOST,
            'port': env.int('EMAIL_PORT', default=587),
            'username': env('EMAIL_HOST_USER', default=''),
            'password': env('EMAIL_HOST_PASSWORD', default=''),
            'use_tls': env.bool('EMAIL_USE_TLS', default=True),
            'timeout': env.int('EMAIL_TIMEOUT', default=20),
        } if SMTP_HOST else {},
    },
}

# Wartezeit auf die Dokumentnummer nach dem Upload, in Sekunden. Nach Ablauf
# holt "manage.py belege_archivieren" die Nummer nach.
PAPERLESS_WARTEZEIT = env.int('PAPERLESS_WARTEZEIT', default=15)

# Speicherpfad der Belege in Paperless, als Name, weil die IDs je
# Installation verschieden sind.
PAPERLESS_SPEICHERPFAD = env('PAPERLESS_SPEICHERPFAD', default='Buchführung')

# Ob Demodaten eingespielt werden dürfen.
#
# Der Lader liegt in paper-werk (demodaten/). Er verbraucht Nummern
# aus den lückenlosen Nummernkreisen, was in einer produktiven Installation
# Lücken erzeugt. Ein eigener Schalter, weil jeder Container mit prod und
# damit DEBUG=False läuft, auch der Teststack.
FAKTURA_DEMODATEN_ERLAUBT = env.bool('FAKTURA_DEMODATEN_ERLAUBT', default=False)

# Default primary key field type
# https://docs.djangoproject.com/en/3.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    # COERCE_DECIMAL_TO_STRING bleibt auf der Vorgabe True, damit Beträge
    # als String übertragen werden und JavaScript keinen float daraus macht.

    'DEFAULT_AUTHENTICATION_CLASSES': (
        # Für Dienstzugänge, wie bei Paperless-ngx ("Authorization: Token");
        # in n8n für beide Systeme gleich einzurichten.
        'rest_framework.authentication.TokenAuthentication',
        # Mit Session aus dem Admin ist die Browsable API ohne Token nutzbar.
        'rest_framework.authentication.SessionAuthentication',
    ),

    # DRFs Vorgabe ist AllowAny. Modellrechte prüft dieselben Rechte wie der
    # Admin, siehe core/permissions.py.
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
        'core.permissions.Modellrechte',
    ),

    # Fachliche Fehler (core/exceptions.py) als HTTP-Antworten.
    'EXCEPTION_HANDLER': 'core.exception_handler.api_exception_handler',

    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',

    # Ohne Pagination liefert DRF jede Liste vollständig. Die Seitengröße
    # steht an der Klasse (core/pagination.py).
    'DEFAULT_PAGINATION_CLASS': 'core.pagination.Seitenweise',
}

# Kopf der API-Dokumentation.
SPECTACULAR_SETTINGS = {
    'TITLE': 'paper-werk',
    'DESCRIPTION': (
        'Schnittstelle zu Belegen, Projekten und Kunden.\n\n'
        'Anmeldung über einen Schlüssel im Kopf der Anfrage:\n\n'
        '    Authorization: Token <schluessel>\n\n'
        'Dasselbe Verfahren wie bei Paperless-ngx; in n8n lässt sich der '
        'HTTP-Request-Node für beide Systeme gleich einrichten.\n\n'
        'Einen Schluessel erzeugt `python manage.py api_schluessel <benutzer>`. '
        'Was ein Schluessel darf, beantwortet `/api/v1/ich/`.'
    ),
    'VERSION': '1.0.0',
    # Den Schema-Endpunkt nicht in der Doku auflisten.
    'SERVE_INCLUDE_SCHEMA': False,
    # Assets aus dem Sidecar-Paket, damit die Doku ohne CDN funktioniert.
    'SWAGGER_UI_DIST': 'SIDECAR',
    'SWAGGER_UI_FAVICON_HREF': 'SIDECAR',
    'REDOC_DIST': 'SIDECAR',
    # Die Version steht im Pfad (/api/v1/) und wird aus den Namen der
    # Operationen herausgehalten.
    'SCHEMA_PATH_PREFIX': '/api/v[0-9]',
    # Nur die eigenen Endpunkte, Begründung in core/schnittstelle/schema.py.
    'PREPROCESSING_HOOKS': ['core.schnittstelle.schema.nur_eigene_endpunkte'],
}

AUTH_USER_MODEL = 'core.User'


# --- Single Sign-on (OIDC, etwa Microsoft Entra ID) --------------------------
#
# Zusätzlich zum lokalen Login, der als Zugang bei Ausfall des Anbieters
# bleibt. Aktiv, sobald SSO_CLIENT_ID gesetzt ist.
#
# Redirect-URI, die beim Anbieter registriert sein muss:
#   <adresse-der-app>/accounts/oidc/<SSO_PROVIDER_ID>/login/callback/
# Im Teststack also http://localhost:8000/accounts/oidc/entra/login/callback/

AUTHENTICATION_BACKENDS = [
    # Zuerst Benutzername und Passwort am Admin.
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

SSO_PROVIDER_ID = env('SSO_PROVIDER_ID', default='entra')
SSO_NAME = env('SSO_NAME', default='Microsoft')
# Discovery-URL, bei Entra:
#   https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration
SSO_SERVER_URL = env('SSO_SERVER_URL', default='')
SSO_CLIENT_ID = env('SSO_CLIENT_ID', default='')
SSO_SECRET = env('SSO_SECRET', default='')

SOCIALACCOUNT_PROVIDERS = {
    'openid_connect': {
        'APPS': [{
            'provider_id': SSO_PROVIDER_ID,
            'name': SSO_NAME,
            'client_id': SSO_CLIENT_ID,
            'secret': SSO_SECRET,
            'settings': {
                'server_url': SSO_SERVER_URL,
                # Pflicht bei Microsoft, weil allauth sonst die userinfo
                # verwendet, in der email und roles fehlen.
                'fetch_userinfo': False,
            },
        }] if SSO_CLIENT_ID else [],
    },
}

# Rollen und Gruppen heißen gleich, siehe core/gruppen.py.

ACCOUNT_ADAPTER = 'core.anmeldung.KontoAdapter'
SOCIALACCOUNT_ADAPTER = 'core.anmeldung.AnmeldeAdapter'
SOCIALACCOUNT_AUTO_SIGNUP = True
ACCOUNT_LOGIN_METHODS = {'username'}
ACCOUNT_SIGNUP_FIELDS = ['username*', 'email']
ACCOUNT_EMAIL_VERIFICATION = 'none'
# Die Mailadresse ist nicht eindeutig, und Konten werden nicht über sie
# verknüpft (SOCIALACCOUNT_EMAIL_AUTHENTICATION aus), weil sonst ein Eintrag
# im Verzeichnis ein lokales Verwalterkonto übernehmen könnte.
ACCOUNT_UNIQUE_EMAIL = False

# Protokoll, mit dem allauth die Redirect-URI bildet. Ohne TLS (Teststack,
# runserver) muss es http sein, sonst passt die URI nicht zur Registrierung
# beim Anbieter.
ACCOUNT_DEFAULT_HTTP_PROTOCOL = env('SSO_HTTP_PROTOKOLL', default='https')

# Nach der Anmeldung in den Admin.
LOGIN_REDIRECT_URL = '/admin/'
LOGIN_URL = 'admin:login'


# --- HTTPS-Betrieb: Ablauf des Zertifikats ------------------------------------
#
# Gesetzt von compose.https.yml (paper-werk). Ohne HTTPS bleiben
# beide leer, und es wird nichts geprüft. Warum nur im Modus "datei"
# gewarnt wird: core/zertifikat.py.
PAPER_WERK_HOSTNAME = env('PAPER_WERK_HOSTNAME', default='')
PAPER_WERK_TLS_MODE = env('PAPER_WERK_TLS_MODE', default='')
# Host, bei dem die App das Zertifikat abfragt (Caddy im Compose-Netz).
# Konfigurierbar für einen anderen Dienstnamen.
ZERTIFIKAT_PRUEFADRESSE = env('ZERTIFIKAT_PRUEFADRESSE', default='caddy')


# --- Änderungshistorie (django-simple-history) -------------------------------
# Kein Revert, weil frühere Stände als Nachweis dienen. Korrekturen laufen
# über die Maske, wo Sperren und Validierung greifen. Siehe auch
# core.adminhilfen.GeschichteZumLesen.
SIMPLE_HISTORY_REVERT_DISABLED = True


# --- E-Rechnung: Dokumentart (BT-3) je Rechnungsart ------------------------
# Die Fachlogik kennt nur die Rechnungsart; der Code im XML wird hier
# zugeordnet und ist je Installation über die Umgebung änderbar. Vorgabe ist
# 380 (Handelsrechnung) für alle Arten; möglich sind etwa 386
# (Vorauszahlungsrechnung) oder 875/876/877 (Teil-, Teilschluss- und
# Schlussrechnung im Bau). Storno und Korrektur sind immer 381.
ERECHNUNG_TYPCODE = {
    'normal': env('ERECHNUNG_TYPCODE_RECHNUNG', default='380'),
    'abschlag': env('ERECHNUNG_TYPCODE_ABSCHLAG', default='380'),
    'schluss': env('ERECHNUNG_TYPCODE_SCHLUSS', default='380'),
    'teilschluss': env('ERECHNUNG_TYPCODE_TEILSCHLUSS', default='380'),
}
