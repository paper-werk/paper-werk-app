"""URL-Konfiguration des Projekts paperwerk.

https://docs.djangoproject.com/en/6.1/topics/http/urls/
"""
from allauth.account import views as konto_views
from allauth.socialaccount.providers.openid_connect import views as oidc_views
from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from core import erweiterungen
from core.anmeldung import anbieter_erreichbar
from core.medien import medien

admin.site.site_header = 'paper-werk'
admin.site.site_title = 'paper-werk'
admin.site.index_title = 'Verwaltung'

urlpatterns = [
    # Akten (Projekt, Auftrag, Rechnung, Kunde) und "Nicht abgerechnet" vor
    # dem Admin. Django prüft die Muster der Reihe nach; ein eigener Pfad
    # unterhalb von "admin/" hat damit Vorrang vor der Catch-all-Route des
    # Admin.
    #
    # ``auswertung`` registriert die Views über ``core.erweiterungen.urls()``
    # in ``AppConfig.ready()``. Begründung für eigene URLs neben
    # ``ModelAdmin.get_urls()``: auswertung/apps.py.
    *erweiterungen.registrierte_urls(),
    path('admin/', admin.site.urls),
    # Nur die URLs für SSO. include('allauth.urls') brächte eine zweite
    # Anmeldeseite, Registrierung und Passwort-Reset neben dem Admin.
    #
    # Eingebunden sind der OIDC-Flow (oidc/<anbieter>/login/ und
    # .../callback/) und allauths Seiten für Abbruch und Fehler. allauth
    # löst während der Anmeldung die drei Namen darunter auf; fehlen sie,
    # folgt NoReverseMatch. Sie leiten auf den Admin um.
    path('accounts/', include([
        # Die beiden Views des OIDC-Flows sind einzeln eingebunden, um sie mit
        # anbieter_erreichbar zu umschließen (Hinweisseite mit 503 bei nicht
        # erreichbarem Anbieter). Pfade und Namen entsprechen allauths
        # openid_connect.urls.
        path('oidc/<str:provider_id>/login/',
             anbieter_erreichbar(oidc_views.login), name='openid_connect_login'),
        path('oidc/<str:provider_id>/login/callback/',
             anbieter_erreichbar(oidc_views.callback),
             name='openid_connect_callback'),
        path('3rdparty/', include('allauth.socialaccount.urls')),
        path('login/', RedirectView.as_view(pattern_name='admin:login'),
             name='account_login'),
        path('signup/', RedirectView.as_view(pattern_name='admin:login'),
             name='account_signup'),
        path('inactive/', konto_views.account_inactive, name='account_inactive'),
    ])),
]

# Die Schnittstelle ist immer eingebunden, weil die Anbindung an Paperless
# und n8n zu core, faktura und erfassung gehört. Die Endpunkte bestimmen die installierten Apps und
# Zusätze (core/schnittstelle/__init__.py). Die Version steht im Pfad, damit
# eine spätere Version bestehende Clients nicht bricht.
urlpatterns.append(path('api/v1/', include('core.schnittstelle.urls')))

# Debug Toolbar.
#
# debug_toolbar_urls() liefert bei DEBUG=False eine leere Liste; die
# Bedingung braucht es wegen des Imports. Im Betrieb ist die Toolbar nicht
# installiert (uv sync --no-dev), und selbst installiert, aber nicht in
# INSTALLED_APPS, wirft ihr Modell beim Import:
#
#   RuntimeError: Model class debug_toolbar.models.HistoryEntry doesn't
#   declare an explicit app_label and isn't in an application in INSTALLED_APPS
#
# Tests laufen immer mit dev und finden das nicht; nur "check --deploy" gegen
# paperwerk.settings.prod zeigt es.
if settings.DEBUG:
    from debug_toolbar.toolbar import debug_toolbar_urls

    urlpatterns += debug_toolbar_urls()

# Logo der Marke und der Firma, in jeder Umgebung gleich (core/medien.py).
#
# Für das PDF ist das nicht nötig, weil der BelegUrlFetcher die Datei im
# Dateisystem auflöst; gebraucht wird es für die HTML-Vorschau im Browser.
urlpatterns.append(
    path(f"{settings.MEDIA_URL.lstrip('/')}<path:pfad>", medien, name='medien'))
