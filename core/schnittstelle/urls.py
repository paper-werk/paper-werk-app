"""URLs der Schnittstelle.

Versioniert unter ``/api/v1/``, damit eine spätere Version die n8n-Workflows
nicht bricht. Die Pfade sind deutsch wie das übrige Projekt.

Im Router ist kein fachlicher Endpunkt fest eingetragen. Jede App registriert
ihre über ``core.erweiterungen.api_endpoint()``: ``erfassung`` die
Eingangsrechnungen, ``faktura`` die Belegauskunft, ein Zusatz gegebenenfalls
weitere (siehe ``core/schnittstelle/__init__.py``).
"""

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from core import erweiterungen

from . import views

app_name = 'api'

router = DefaultRouter()
for _praefix, _viewset, _basename in erweiterungen.api_endpunkte():
    router.register(_praefix, _viewset, basename=_basename)

urlpatterns = [
    path('', views.WurzelAnsicht.as_view(), name='wurzel'),
    path('status/', views.StatusAnsicht.as_view(), name='status'),
    path('ich/', views.IchAnsicht.as_view(), name='ich'),

    path('', include(router.urls)),

    # Das Schema wird aus dem Code erzeugt und beschreibt die registrierten
    # Endpunkte.
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path(
        'doku/',
        SpectacularSwaggerView.as_view(url_name='api:schema'),
        name='doku',
    ),
]
