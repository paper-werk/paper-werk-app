"""Schmale Belegauskunft der Archiv-Anbindung.

Dient dem Versand des XML an den Steuerberater: Paperless nimmt kein XML an
und archiviert das PDF. Geht eine Rechnung nur als XML hinaus (XRechnung an
ein Portal), ist das XML das Original und muss gesondert zum Steuerberater.
Der Workflow (n8n, ``sub-duo-versand-paperwerk``) beginnt beim Dokument im
Archiv::

    GET  /api/v1/belege/?paperless_id=<Dokument-ID>
         -> erechnungsprofil, xml_sha256
    GET  /api/v1/belege/{id}/xml/            (die abgelegte Datei)

Der Umfang ist bewusst begrenzt. Ein Zusatz kann den ViewSet erweitern und
unter derselben URL ersetzen (``core.erweiterungen.api_endpoint(ersetzt=True)``);
er muss die hier zugesagten Felder weiter liefern
(``faktura/tests/test_anbindung.py``).

``faktura/apps.py`` registriert den ViewSet.
"""

from django.http import FileResponse
from django_filters import rest_framework as filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ReadOnlyModelViewSet

from core.permissions import Modellrechte

from . import facturx
from .models import Beleg


class BelegAnbindungSerializer(serializers.ModelSerializer):
    """Felder eines Belegs für die Archiv-Anbindung: genug, um ihn zu finden
    und zu entscheiden, ob sein XML mitgesendet wird."""

    typ_kennung = serializers.CharField(source='typ', read_only=True)
    status_kennung = serializers.CharField(source='status', read_only=True)
    archiviert = serializers.SerializerMethodField()

    class Meta:
        model = Beleg
        fields = [
            'id', 'nummer', 'typ_kennung', 'status_kennung', 'belegdatum',
            'festgeschrieben_am', 'archiviert', 'paperless_id',
            'erechnungsprofil', 'xml_sha256',
        ]

    def get_archiviert(self, beleg: Beleg) -> bool:
        """Boolean neben ``paperless_id``, in n8n einfacher auszuwerten als
        "Zahl oder null"."""
        return beleg.paperless_id is not None


class BelegAnbindungFilter(filters.FilterSet):
    """Filter vom Archivdokument zum Beleg."""

    nummer = filters.CharFilter(lookup_expr='iexact', label='Belegnummer')

    # Für den Versand des XML: von der Dokument-ID zum Beleg; am Profil ist
    # erkennbar, ob das XML mitgeht.
    paperless_id = filters.NumberFilter(label='Dokument-ID im Archiv')
    erechnungsprofil = filters.CharFilter(
        lookup_expr='iexact',
        label='E-Rechnungsprofil ("EN 16931" oder "XRECHNUNG")',
    )
    mit_xml = filters.BooleanFilter(
        method='nach_xml',
        label='Hat ein abgelegtes XML',
    )

    class Meta:
        model = Beleg
        fields = []

    def nach_xml(self, queryset, name, wert):
        """``?mit_xml=true``: Belege, zu denen ein XML abgelegt ist.

        Über die Prüfsumme, weil sie nur gesetzt wird, wenn die Datei
        geschrieben wurde.
        """
        if wert:
            return queryset.exclude(xml_sha256='')
        return queryset.filter(xml_sha256='')


class BelegAnbindungViewSet(ReadOnlyModelViewSet):
    """Belege finden und ihr gespeichertes XML abrufen, nur lesend."""

    # Vorgabe aus den Settings, explizit gesetzt.
    permission_classes = [IsAuthenticated, Modellrechte]

    filter_backends = [DjangoFilterBackend]
    filterset_class = BelegAnbindungFilter
    serializer_class = BelegAnbindungSerializer
    queryset = Beleg.objects.order_by('-erstellt_am')

    @extend_schema(
        summary='Das Factur-X-XML holen',
        description='Die maschinenlesbare Fassung nach EN 16931, so wie sie '
                    'beim Festschreiben abgelegt wurde; byte-gleich mit dem '
                    'XML im PDF. Nur für festgeschriebene Steuerbelege.',
        responses={(200, 'application/xml'): bytes,
                   404: OpenApiResponse(description='Kein XML zu diesem Beleg')},
    )
    @action(detail=True, methods=['get'])
    def xml(self, request, pk=None):
        """Gespeichertes XML, nicht neu erzeugt, wie das PDF.

        Bei Versand nur als XML ist es das Original; neu erzeugt enthielte es
        die aktuellen Stammdaten.
        """
        beleg = self.get_object()

        if not facturx.ist_erechnungsfaehig(beleg):
            raise NotFound(
                f'Zu {beleg} gehört kein Factur-X-XML. Es gibt eines für '
                f'festgeschriebene Rechnungen, Stornorechnungen und '
                f'Rechnungskorrekturen.'
            )
        if not beleg.xml:
            raise NotFound(
                f'{beleg} hat kein gespeichertes XML. Es entsteht beim '
                f'Festschreiben zusammen mit dem PDF.'
            )

        from . import pdf as pdf_modul

        try:
            beleg.xml.open('rb')
        except FileNotFoundError as fehler:
            raise NotFound(
                f'{beleg}: Das XML ist vermerkt, die Datei fehlt aber '
                f'im Ablageverzeichnis.'
            ) from fehler
        return FileResponse(
            beleg.xml,
            content_type='application/xml',
            filename=pdf_modul.dateiname(beleg, 'xml'),
        )
