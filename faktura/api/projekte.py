"""Projekte über die Schnittstelle: nachschlagen, auflösen, auswerten.

Die Gegenrichtung zu ``belege.py``: Zu welchem Vorhaben gehört dieses
Dokument im Archiv?

    GET /api/v1/projekte/                    Liste
    GET /api/v1/projekte/aufloesen/?q=...    unscharfe Suche
    GET /api/v1/projekte/{nummer}/           Einzelauskunft
    GET /api/v1/projekte/{nummer}/akte/      Belege und Summen

Adressiert über die Nummer (Pflicht, eindeutig): Die Anfrage kommt aus
einem Archivdokument und bringt Text mit, keine ID. Enthält eine Nummer
einen Schrägstrich, führt der Weg über ``/projekte/?nummer=2026%2F042``.
"""

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from core.permissions import Modellrechte
from faktura import services
from faktura.models import Projekt

from .serializers import (
    AufloesungSerializer,
    ProjektakteSerializer,
    ProjektSerializer,
)


class ProjektViewSet(ReadOnlyModelViewSet):
    """Projekte nachschlagen und auswerten."""

    serializer_class = ProjektSerializer
    permission_classes = [IsAuthenticated, Modellrechte]

    # Die fachliche Nummer als Adresse. ``[^/]+`` statt der Vorgabe
    # ``[^/.]+``: Djangos Standard schließt den Punkt aus, und eine
    # Projektnummer wie "2026.042" wäre damit unerreichbar.
    lookup_field = 'nummer'
    lookup_value_regex = '[^/]+'

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['abgeschlossen']
    search_fields = ['nummer', 'bezeichnung', 'kunde__name']
    ordering_fields = ['nummer', 'bezeichnung']
    ordering = ['-nummer']

    def get_queryset(self):
        return Projekt.objects.select_related('kunde')

    # -- Die unscharfe Suche ------------------------------------------------

    @extend_schema(
        summary='Projekt zu einem Textschnipsel finden',
        description=(
            'Für die Zuordnung eingehender Dokumente. Sucht über '
            'Projektnummer, Bezeichnung und Kundenname und sagt dazu, wie '
            'sicher der Fund ist.\n\n'
            'Stimmt die Projektnummer vollständig überein, ist das Ergebnis '
            'eindeutig und enthält genau einen Treffer. Sonst kommen alle '
            'Teiltreffer zurück, und `eindeutig` ist nur dann wahr, wenn es '
            'bei einem geblieben ist.\n\n'
            'Abgeschlossene Projekte sind enthalten, die Schlussrechnung '
            'eines Lieferanten trifft oft erst ein, wenn das Projekt '
            'abgehakt ist. Mit `nur_offene=true` bleiben sie draußen.'
        ),
        parameters=[
            OpenApiParameter('q', str, description='Der gesuchte Text.', required=True),
            OpenApiParameter('nur_offene', bool,
                             description='Abgeschlossene Projekte ausschließen.'),
        ],
        responses={200: AufloesungSerializer,
                   400: OpenApiResponse(description='Parameter q fehlt')},
    )
    @action(detail=False, methods=['get'], url_path='aufloesen')
    def aufloesen(self, request):
        """Sucht über das, was auf dem Papier steht: Die Texterkennung
        liefert nie einen Datenbankschlüssel. Die Arbeit macht
        ``services.projekt_aufloesen``."""
        text = request.query_params.get('q', '')
        if not text.strip():
            raise ValidationError({'q': 'Ohne Suchtext gibt es nichts aufzulösen.'})

        aufloesung = services.projekt_aufloesen(
            text,
            nur_offene=request.query_params.get('nur_offene', '').lower() == 'true',
        )

        return Response(AufloesungSerializer(aufloesung).data)

    # -- Die Akte -----------------------------------------------------------

    @extend_schema(
        summary='Alle Belege eines Projekts mit Summen',
        description=(
            'Was angeboten und was davon berechnet wurde, aufgeschlüsselt '
            'nach Belegart.\n\n'
            'In `fakturiert_*` zählen nur Steuerbelege (Rechnung, '
            'Stornorechnung, Rechnungskorrektur). Mahnungen bleiben draußen, '
            'obwohl sie einen Betrag tragen. Sie fordern eine bereits '
            'berechnete Leistung erneut an, und mitgezählt stünde jede '
            'gemahnte Rechnung doppelt in der Summe.\n\n'
            'Entwürfe sind nicht enthalten.'
        ),
        responses={200: ProjektakteSerializer},
    )
    @action(detail=True, methods=['get'])
    def akte(self, request, nummer=None):
        """Belege und Summen eines Vorhabens, für den Projektakte-Export."""
        projekt = self.get_object()
        auswertung = services.projektakte(projekt)

        return Response(ProjektakteSerializer({
            'projekt': projekt,
            'belege': auswertung.belege,
            'je_belegart': {
                typ: {
                    'anzahl': summe.anzahl,
                    'netto': str(summe.netto),
                    'brutto': str(summe.brutto),
                }
                for typ, summe in auswertung.je_belegart.items()
            },
            'fakturiert_netto': str(auswertung.fakturiert_netto),
            'fakturiert_brutto': str(auswertung.fakturiert_brutto),
            'angeboten_netto': str(auswertung.angeboten_netto),
        }, context=self.get_serializer_context()).data)
