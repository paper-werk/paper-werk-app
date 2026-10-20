"""API für die Übernahme von Eingangsrechnungen aus dem Archiv.

    GET  /api/v1/eingangsrechnungen/                    Liste, filterbar
    GET  /api/v1/eingangsrechnungen/{id}/               Einzelauskunft
    POST /api/v1/eingangsrechnungen/                    übernehmen oder
                                                        aktualisieren
    POST /api/v1/eingangsrechnungen/erechnung-pruefen/  steckt eine
                                                        E-Rechnung im PDF?
    POST /api/v1/eingangsrechnungen/erechnung/          E-Rechnung aus dem
                                                        Archiv übernehmen

Ablauf: Ein Dokument liegt in Paperless, n8n lässt die Felder erkennen, ein
Benutzer prüft sie. Übertragen werden die geprüften Werte und die
Dokumentnummer; das PDF bleibt im Archiv.

Schreibzugriff ist erlaubt, weil eine Eingangsrechnung weder Nummernkreis
noch Festschreibung hat, aber nur über
``services.eingangsrechnung_aus_archiv()``.

Zweiter Fall ist die E-Rechnung: Enthält das PDF XML, ist keine
Texterkennung nötig. n8n sendet dann die Datei selbst, einmal zur Prüfung,
bevor die Felder in Paperless gefüllt werden, und einmal zur Übernahme,
wenn der Benutzer "Paper-Werk senden" gesetzt hat. n8n holt die Datei aus
Paperless, weil es dort ohnehin Zugriff hat und paper-werk so keinen
lesenden Schlüssel für fremde Dokumente braucht.

``ZeitenConfig.ready()`` registriert ``EingangsrechnungViewSet`` über
``core.erweiterungen.api_endpoint()``. Der Endpunkt gehört zur
Archiv-Anbindung des Kerns.
"""

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.mixins import CreateModelMixin
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ReadOnlyModelViewSet

from core.permissions import Modellrechte

from . import services
from .models import Eingangsrechnung


class EingangsrechnungSerializer(serializers.ModelSerializer):
    """Lesende Darstellung einer Eingangsrechnung."""

    lieferant = serializers.CharField(source='lieferant.name', read_only=True)
    rest = serializers.DecimalField(max_digits=12, decimal_places=2,
                                    read_only=True)
    zugeordnet = serializers.DecimalField(max_digits=12, decimal_places=2,
                                          read_only=True)
    archiv_adresse = serializers.CharField(read_only=True)
    projekte = serializers.SerializerMethodField()

    class Meta:
        model = Eingangsrechnung
        fields = ['id', 'lieferant', 'nummer', 'datum', 'betrag_netto',
                  'zugeordnet', 'rest', 'paperless_id', 'archiv_adresse',
                  'projekte', 'notiz', 'erfasst_am']

    def get_projekte(self, rechnung) -> list[str]:
        """Vorhaben, auf die die Rechnung verteilt ist."""
        return sorted({p.projekt.nummer for p in rechnung.positionen.all()
                       if p.projekt_id})


class UebertragSerializer(serializers.Serializer):
    """Eingabe eines Workflows zur Übernahme.

    Mit Namen, weil die IDs in Paperless je Installation verschieden sind.
    Beträge netto, weil die Anwendung netto rechnet.
    """

    paperless_id = serializers.IntegerField(
        min_value=1,
        help_text='Die Nummer des Dokuments in Paperless.')
    lieferant = serializers.CharField(
        max_length=200,
        help_text='Der Name, so wie er auf der Rechnung steht; im Archiv '
                  'der Korrespondent. Unbekannte werden angelegt.')
    nummer = serializers.CharField(
        max_length=50, help_text='Die Rechnungsnummer des Lieferanten.')
    datum = serializers.DateField(help_text='Das Rechnungsdatum.')
    betrag_netto = serializers.DecimalField(
        max_digits=12, decimal_places=2,
        help_text='Der Nettobetrag. Damit rechnet die Projektauswertung.')
    projekt = serializers.CharField(
        max_length=30, required=False, allow_blank=True,
        help_text='Die Projektnummer. Leer lassen, wenn sie am Dokument '
                  'fehlt; die Rechnung kommt dann unkontiert an und ihr '
                  'Rest steht offen sichtbar da.')
    notiz = serializers.CharField(
        required=False, allow_blank=True, default='',
        help_text='Freitext, etwa ein Hinweis aus der Sichtung.')


#: Höchstgröße wie beim Upload im Admin.
MAX_DATEIGROESSE = 10 * 1024 * 1024


def _datei_lesen(datei) -> bytes:
    if datei.size > MAX_DATEIGROESSE:
        raise serializers.ValidationError(
            {'datei': f'Die Datei ist größer als '
                      f'{MAX_DATEIGROESSE // (1024 * 1024)} MB.'})
    return datei.read()


class DateiSerializer(serializers.Serializer):
    """Datei aus dem Archiv, das Original und nicht die Archivfassung."""

    datei = serializers.FileField(
        help_text='Das PDF, so wie Paperless es unter '
                  '/api/documents/{id}/download/?original=true liefert. '
                  'Die Archivfassung (PDF/A) hat den Anhang oft verloren.')


class BefundSerializer(serializers.Serializer):
    """Antwort der Prüfung, immer 200, auch ohne E-Rechnung."""

    erechnung = serializers.BooleanField(
        help_text='Ob XML im PDF steckt.')
    lesbar = serializers.BooleanField(
        help_text='Ob daraus eine Eingangsrechnung würde. Nur dann '
                  'übernimmt der Workflow die Felder.')
    meldung = serializers.CharField(
        help_text='Warum nicht; leer, wenn alles lesbar ist.')
    lieferant = serializers.CharField(help_text='Der Verkäufer (BT-27).')
    projektreferenz = serializers.CharField(
        help_text='Die Projektreferenz (BT-11), wie sie in der Datei steht.')
    felder = serializers.DictField(
        child=serializers.CharField(),
        help_text='Werte nach dem Namen des Zusatzfelds in Paperless: '
                  'Rechnungsnummer, Rechnungsdatum, Nettobetrag, '
                  'Gesamtbetrag, Fällig am, Projektnummer.')


class ArchivERechnungSerializer(DateiSerializer):
    """Eingabe von n8n zur Übernahme einer E-Rechnung."""

    paperless_id = serializers.IntegerField(
        min_value=1,
        help_text='Die Nummer des Dokuments in Paperless.')
    projekt = serializers.CharField(
        max_length=30, required=False, allow_blank=True, default='',
        help_text='Die Projektnummer aus Paperless. Leer lassen, dann '
                  'entscheidet die Projektreferenz der Rechnung.')


class EingangsrechnungViewSet(CreateModelMixin, ReadOnlyModelViewSet,
                              GenericViewSet):
    """Eingangsrechnungen lesen und übernehmen.

    Mit ``?paperless_id=`` prüft ein Workflow, ob ein Dokument bereits
    übernommen ist.
    """

    permission_classes = [IsAuthenticated, Modellrechte]
    serializer_class = EingangsrechnungSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['paperless_id', 'lieferant__name', 'nummer']
    queryset = Eingangsrechnung.objects.none()  # nur für die Rechteprüfung

    def get_queryset(self):
        return (Eingangsrechnung.objects
                .select_related('lieferant')
                .prefetch_related('positionen__projekt')
                .order_by('-datum', '-pk'))

    @extend_schema(
        request=UebertragSerializer,
        responses={
            201: OpenApiResponse(EingangsrechnungSerializer,
                                 description='Neu übernommen.'),
            200: OpenApiResponse(EingangsrechnungSerializer,
                                 description='Schon vorhanden, aktualisiert.'),
            400: OpenApiResponse(description='Unbekannte Projektnummer oder '
                                             'fehlender Lieferant.'),
            409: OpenApiResponse(description='Bereits weiterberechnet; hier '
                                             'ändert sich nichts mehr.'),
        },
        summary='Eine Rechnung aus dem Archiv übernehmen',
    )
    def create(self, request, *args, **kwargs):
        """Übernimmt (201) oder aktualisiert (200); ein wiederholter Lauf
        desselben Workflows ist idempotent. Fachliche Fehler tragen ihren
        HTTP-Status selbst (``FachlicherFehler``).
        """
        eingabe = UebertragSerializer(data=request.data)
        eingabe.is_valid(raise_exception=True)

        rechnung, neu = services.eingangsrechnung_aus_archiv(
            **eingabe.validated_data)

        return Response(
            EingangsrechnungSerializer(rechnung).data,
            status=status.HTTP_201_CREATED if neu else status.HTTP_200_OK,
        )

    @extend_schema(
        request={'multipart/form-data': DateiSerializer},
        responses={200: BefundSerializer},
        summary='Prüfen, ob in einem PDF eine E-Rechnung steckt',
    )
    @action(detail=False, methods=['post'], url_path='erechnung-pruefen',
            parser_classes=[MultiPartParser, FormParser])
    def erechnung_pruefen(self, request):
        """Prüft nur und legt nichts an. Verlangt trotzdem das Recht zum
        Anlegen, weil die Prüfung der Übernahme vorausgeht."""
        eingabe = DateiSerializer(data=request.data)
        eingabe.is_valid(raise_exception=True)

        befund = services.erechnung_befund(
            _datei_lesen(eingabe.validated_data['datei']))

        return Response(BefundSerializer(befund).data)

    @extend_schema(
        request={'multipart/form-data': ArchivERechnungSerializer},
        responses={
            201: OpenApiResponse(EingangsrechnungSerializer,
                                 description='Neu übernommen, mit Positionen.'),
            200: OpenApiResponse(EingangsrechnungSerializer,
                                 description='Schon vorhanden; höchstens '
                                             'die Positionen nachgetragen.'),
            400: OpenApiResponse(description='Keine lesbare E-Rechnung oder '
                                             'unbekannte Projektnummer.'),
            409: OpenApiResponse(description='Dieselbe Rechnung hängt schon '
                                             'an einem anderen Dokument.'),
        },
        summary='Eine E-Rechnung aus dem Archiv übernehmen',
    )
    @action(detail=False, methods=['post'], url_path='erechnung',
            parser_classes=[MultiPartParser, FormParser])
    def erechnung(self, request):
        eingabe = ArchivERechnungSerializer(data=request.data)
        eingabe.is_valid(raise_exception=True)
        werte = eingabe.validated_data

        rechnung, neu = services.eingangsrechnung_aus_archiv_erechnung(
            daten=_datei_lesen(werte['datei']),
            paperless_id=werte['paperless_id'],
            projekt=werte['projekt'],
        )

        return Response(
            EingangsrechnungSerializer(rechnung).data,
            status=status.HTTP_201_CREATED if neu else status.HTTP_200_OK,
        )
