"""Kontakte über die Schnittstelle, für die Korrespondenten in Paperless.

``/kunden/`` liefert nur Kontakte mit der Rolle Kunde, so wie vor der
Zusammenlegung mit den Lieferanten; bestehende n8n-Workflows merken nichts.
``/kontakte/`` liefert alle, mit ihren Rollen. Nur lesend: Stammdaten
pflegt das Büro im Admin.
"""

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ReadOnlyModelViewSet

from core.permissions import Modellrechte
from faktura.models import Kontakt

from .serializers import KontaktSerializer, KundeSerializer


class KundeViewSet(ReadOnlyModelViewSet):
    """Kunden nachschlagen."""

    serializer_class = KundeSerializer
    permission_classes = [IsAuthenticated, Modellrechte]

    # Die fachliche Nummer als Adresse, wie bei den Projekten.
    lookup_field = 'nummer'
    lookup_value_regex = '[^/]+'

    # Vorgeladen, was der Serializer ausgibt, sonst zwei Abfragen je Kunde.
    queryset = Kontakt.objects.filter(ist_kunde=True).prefetch_related(
        'adressen', 'kontaktwege', 'ansprechpartner__kontaktwege')

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    # ``ort`` ist eine Eigenschaft, gesucht wird über die Adressen.
    search_fields = ['nummer', 'name', 'adressen__ort']
    filterset_fields = ['aktiv']
    ordering_fields = ['nummer', 'name']
    ordering = ['nummer']


class KontaktViewSet(KundeViewSet):
    """Alle Kontakte, filterbar nach Rolle (``?ist_lieferant=true``)."""

    serializer_class = KontaktSerializer
    queryset = Kontakt.objects.prefetch_related(
        'adressen', 'kontaktwege', 'ansprechpartner__kontaktwege')
    filterset_fields = ['aktiv', 'ist_kunde', 'ist_lieferant', 'ist_partner',
                        'ist_interessent']
