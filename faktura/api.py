"""Belegauskunft: Archiv-Anbindung und Rückweg für Ereignisse.

Archiv-Anbindung. Dient dem Versand des XML an den Steuerberater: Paperless nimmt kein XML an
und archiviert das PDF. Geht eine Rechnung nur als XML hinaus (XRechnung an
ein Portal), ist das XML das Original und muss gesondert zum Steuerberater.
Der Workflow (n8n, ``sub-duo-versand-paperwerk``) beginnt beim Dokument im
Archiv::

    GET  /api/v1/belege/?paperless_id=<Dokument-ID>
         -> erechnungsprofil, xml_sha256
    GET  /api/v1/belege/{id}/xml/            (die abgelegte Datei)

Rückweg für Workflows, die auf Ereignisse reagieren (``docs/webhooks.md``)::

    GET   /api/v1/belege/{id}/               (Eigenschaften wie im Ereignis)
    GET   /api/v1/belege/{id}/pdf/
    GET   /api/v1/belege/?vorgaenger=<id>    (Nachfolger, etwa Auftrag zum Angebot)
    PATCH /api/v1/belege/{id}/               (Kopffelder eines Entwurfs)

Der Umfang ist bewusst begrenzt. Ein Zusatz kann den ViewSet erweitern und
unter derselben URL ersetzen (``core.erweiterungen.api_endpoint(ersetzt=True)``);
er muss die hier zugesagten Felder weiter liefern
(``faktura/tests/test_anbindung.py``).

``faktura/apps.py`` registriert den ViewSet.
"""

from django.db import transaction
from django.http import FileResponse
from django_filters import rest_framework as filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from core.optimistic_locking import FELD, VersionKonflikt, version_pruefen
from core.permissions import Modellrechte

from . import facturx
from .models import Beleg
from .services import belegsummen

#: Felder, die ``PATCH`` an einem Entwurf ändert. Ohne Wirkung auf Steuer,
#: Summen, Fristen und die Zuordnung zu Kunde und Projekt; Positionen,
#: Zustandswechsel und Anlegen werden nicht angeboten, weil dabei Summen,
#: Abschläge und erfasste Leistungen konsistent bleiben müssen.
AENDERBARE_KOPFFELDER = [
    'betreff', 'kopftext', 'fusstext', 'bestellnummer', 'leitweg_id',
    'empfaenger_email',
]


class BelegAnbindungSerializer(serializers.ModelSerializer):
    """Felder eines Belegs für die Archiv-Anbindung: genug, um ihn zu finden
    und zu entscheiden, ob sein XML mitgesendet wird."""

    typ_kennung = serializers.CharField(source='typ', read_only=True)
    status_kennung = serializers.CharField(source='status', read_only=True)
    archiviert = serializers.SerializerMethodField()
    kunde_name = serializers.CharField(source='kunde.name', default=None,
                                       read_only=True)
    brutto = serializers.SerializerMethodField()

    class Meta:
        model = Beleg
        fields = [
            'id', 'nummer', 'typ_kennung', 'status_kennung', 'belegdatum',
            'festgeschrieben_am', 'archiviert', 'paperless_id',
            'erechnungsprofil', 'xml_sha256',
            # Eigenschaften wie im Ereignis (faktura/ereignisse.py).
            'betreff', 'faellig_am', 'kunde_name', 'vorgaenger_id', 'brutto',
            FELD,
        ]

    def get_archiviert(self, beleg: Beleg) -> bool:
        """Boolean neben ``paperless_id``, in n8n einfacher auszuwerten als
        "Zahl oder null"."""
        return beleg.paperless_id is not None

    def get_brutto(self, beleg: Beleg) -> str:
        """Zahlbetrag aus ``belegsummen``, mit zwei Nachkommastellen."""
        return f'{belegsummen(beleg).brutto:.2f}'


class KopfaenderungSerializer(serializers.ModelSerializer):
    """Eingabe für ``PATCH``: Kopffelder aus ``AENDERBARE_KOPFFELDER`` und
    die Version beim Lesen (Optimistic Locking, Pflicht).

    Andere Felder werden abgewiesen statt ignoriert, damit ein Workflow
    nicht annimmt, er habe etwa das Zahlungsziel geändert.
    """

    class Meta:
        model = Beleg
        fields = AENDERBARE_KOPFFELDER

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields[FELD] = serializers.IntegerField(
            help_text='Version aus der letzten Auskunft oder dem Ereignis.')

    def to_internal_value(self, data):
        fremd = sorted(set(data) - set(self.fields))
        if fremd:
            raise serializers.ValidationError(
                dict.fromkeys(fremd, 'Über die Schnittstelle nicht änderbar.'))
        if FELD not in data:
            raise serializers.ValidationError({FELD: 'Pflichtangabe.'})
        return super().to_internal_value(data)


class DarfKopfAendern(BasePermission):
    """Prüft ``faktura.kopf_aendern_beleg``, ein eigenes Recht, damit ein
    Dienstzugang Kopffelder ändern kann, ohne ``change_beleg`` zu haben."""

    message = 'Dafür fehlt das Recht "Kann Kopffelder über die API ändern".'

    def has_permission(self, request, view):
        return request.user.has_perm('faktura.kopf_aendern_beleg')


class BelegAnbindungFilter(filters.FilterSet):
    """Filter vom Archivdokument zum Beleg."""

    nummer = filters.CharFilter(lookup_expr='iexact', label='Belegnummer')

    # Nachfolger eines Belegs, etwa der Auftrag zu einem Angebot.
    vorgaenger = filters.NumberFilter(field_name='vorgaenger_id',
                                      label='ID des Vorgängers')

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
    """Belege finden, PDF und XML abrufen, Kopffelder eines Entwurfs ändern.

    ``partial_update`` ist der einzige Schreibzugriff; ``PUT`` wird nicht
    geroutet, weil der ViewSet kein ``update`` hat. Änderungen über die API
    lösen kein Ereignis aus (``docs/webhooks.md``).
    """

    # Vorgabe aus den Settings, explizit gesetzt.
    permission_classes = [IsAuthenticated, Modellrechte]

    filter_backends = [DjangoFilterBackend]
    filterset_class = BelegAnbindungFilter
    serializer_class = BelegAnbindungSerializer
    # ``positionen`` für ``brutto``.
    queryset = (Beleg.objects.select_related('kunde')
                .prefetch_related('positionen').order_by('-erstellt_am'))

    def get_permissions(self):
        if self.action == 'partial_update':
            return [IsAuthenticated(), DarfKopfAendern()]
        return super().get_permissions()

    @extend_schema(
        summary='Kopffelder eines Entwurfs ändern',
        description=(
            'Ändert `betreff`, `kopftext`, `fusstext`, `bestellnummer`, '
            '`leitweg_id` und `empfaenger_email`. Die Version aus der '
            'letzten Auskunft ist Pflicht; weicht sie ab, kommt 409. Ein '
            'festgeschriebener Beleg antwortet mit 409. Andere Felder '
            'werden mit 400 abgewiesen.'
        ),
        request=KopfaenderungSerializer,
        responses={200: BelegAnbindungSerializer,
                   409: OpenApiResponse(description='Kein Entwurf oder '
                                                    'zwischenzeitlich geändert')},
    )
    def partial_update(self, request, pk=None):
        with transaction.atomic():
            beleg = self.get_object()
            if not beleg.ist_aenderbar:
                return Response(
                    {'detail': f'{beleg} ist festgeschrieben und nicht '
                               f'mehr änderbar.'}, status=409)
            eingabe = KopfaenderungSerializer(beleg, data=request.data,
                                              partial=True)
            eingabe.is_valid(raise_exception=True)
            daten = dict(eingabe.validated_data)
            try:
                version_pruefen(beleg, daten.pop(FELD))
            except VersionKonflikt as fehler:
                return Response({'detail': fehler.messages[0]}, status=409)
            for feld, wert in daten.items():
                setattr(beleg, feld, wert)
            beleg.save()
        beleg = self.get_queryset().get(pk=beleg.pk)
        return Response(self.get_serializer(beleg).data)

    @extend_schema(
        summary='Das PDF holen',
        description='Liefert die beim Festschreiben erzeugte Datei. Entwürfe '
                    'haben keine und antworten mit 404.',
        responses={(200, 'application/pdf'): bytes,
                   404: OpenApiResponse(description='Kein Dokument vorhanden')},
    )
    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        """Die gespeicherte Datei, nicht neu gerendert: Das versendete PDF
        ist der Beleg. Ein Entwurf bekommt 404, keine Vorschau."""
        beleg = self.get_object()

        if not beleg.pdf:
            raise NotFound(
                f'{beleg} hat kein gespeichertes Dokument. Entwürfe bekommen '
                f'ihres erst beim Festschreiben.'
            )

        from . import pdf as pdf_modul

        try:
            beleg.pdf.open('rb')
        except FileNotFoundError as fehler:
            raise NotFound(
                f'{beleg}: Das Dokument ist vermerkt, die Datei fehlt aber '
                f'im Ablageverzeichnis.'
            ) from fehler
        return FileResponse(
            beleg.pdf,
            content_type='application/pdf',
            filename=pdf_modul.dateiname(beleg),
        )

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
