"""Belege über die Schnittstelle: lesen, holen, ablegen.

Was das Haus verlässt, gehört ins Archiv: Ein Ablauf (n8n) fragt nach dem
Zuwachs, holt PDF und Metadaten, legt beides in Paperless ab und meldet
zurück, wo das Dokument gelandet ist::

    GET  /api/v1/belege/?status=festgeschrieben&archiviert=false
                        &festgeschrieben_ab=<letzter Lauf>
    GET  /api/v1/belege/{id}/pdf/
    GET  /api/v1/belege/{id}/xml/            (nur bei Rechnungen)
    POST /api/v1/belege/{id}/archiviert/     {"paperless_document_id": 123}

Der Weg des XML zum Steuerberater (``?paperless_id=`` und ``xml/``) gehört
zur Archiv-Anbindung und steht in ``anbindung.py``. Diese Fassung erbt
ihn.

``status=festgeschrieben`` gehört dazu: ``archiviert=false`` allein liefert
auch Entwürfe, die kein Dokument haben (404) und sich nicht vermerken lassen
(409).

Adressiert wird über die Datenbank-ID, nicht die Belegnummer (anders als bei
Projekten): Entwürfe haben noch keine Nummer. Wer sie hat, findet den Beleg
über ``?nummer=``.
"""

from django.contrib.admin.models import CHANGE, LogEntry
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from core.permissions import Modellrechte
from faktura import services
from faktura.models import Beleg, proxy_fuer

from .anbindung import BelegAnbindungViewSet
from .filters import BelegFilter
from .serializers import (
    ArchivvermerkSerializer,
    BelegListeSerializer,
    BelegSerializer,
    FestschreibenEingabeSerializer,
    FestschreibungSerializer,
)


class DarfFestschreiben(BasePermission):
    """Prüft ``faktura.change_beleg``, dasselbe Recht wie im Admin.

    Der Dienstzugang bekommt es nicht: Ein Automatisierungslauf, der aus
    Versehen zwanzig Entwürfe festschreibt, hinterlässt zwanzig Rechnungen,
    die nur noch storniert werden können.
    """

    message = 'Dafür fehlt das Recht, Belege zu ändern.'

    def has_permission(self, request, view):
        return request.user.has_perm('faktura.change_beleg')


class DarfArchivieren(BasePermission):
    """Prüft das eigene Recht ``faktura.archivieren_beleg``.

    ``Modellrechte`` prüfte bei einem POST ``add_beleg``, ein
    Automatisierungslauf soll aber nicht Belege anlegen dürfen, nur
    vermerken, wo die Archivkopie liegt.
    """

    message = 'Dafür fehlt das Recht "Kann den Archivvermerk setzen".'

    def has_permission(self, request, view):
        return request.user.has_perm('faktura.archivieren_beleg')


class BelegViewSet(BelegAnbindungViewSet):
    """Belege lesen, ihr Dokument holen und die Ablage vermerken.

    Nur lesend, mit zwei benannten Ausnahmen: Was Geld anfasst, läuft über
    ``faktura.services``.

    Erbt von ``BelegAnbindungViewSet`` (``anbindung.py``). PDF, XML,
    ``PATCH`` auf Kopffelder und der Filter ``vorgaenger`` kommen von dort;
    alles, was die Archiv-Anbindung zusagt, gilt damit auch hier.
    """

    # Die Vorgabe aus den Settings, zum Mitlesen ausgeschrieben.
    permission_classes = [IsAuthenticated, Modellrechte]

    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = BelegFilter
    ordering_fields = ['belegdatum', 'nummer', 'festgeschrieben_am', 'erstellt_am']
    ordering = ['-erstellt_am']

    def get_queryset(self):
        """``positionen`` auch für die Liste: Die Summen entstehen daraus."""
        return (
            Beleg.objects
            .select_related('kunde', 'projekt', 'vorgaenger')
            .prefetch_related('positionen')
        )

    def get_serializer_class(self):
        if self.action == 'list':
            return BelegListeSerializer
        if self.action == 'archiviert':
            return ArchivvermerkSerializer
        return BelegSerializer

    # -- Der fachliche Vorgang ----------------------------------------------

    @extend_schema(
        summary='Beleg festschreiben',
        description=(
            'Vergibt die Nummer aus dem lückenlosen Kreis, setzt den Status '
            'und friert das Dokument ein. Danach ist der Beleg nicht mehr '
            'änderbar. Eine Korrektur läuft über eine Stornierung.\n\n'
            'Verlangt das Recht, Belege zu ändern. Dienstzugänge haben es '
            'nicht.\n\n'
            'Rechnet die Rechnung mehr ab, als beauftragt ist, kommt 409, '
            'es sei denn, `mengen_bestaetigt` ist gesetzt.'
        ),
        request=FestschreibenEingabeSerializer,
        responses={200: FestschreibungSerializer,
                   409: OpenApiResponse(description='Beleg ist kein Entwurf '
                                                    'mehr, oder mehr als '
                                                    'beauftragt ohne '
                                                    'Bestätigung'),
                   422: OpenApiResponse(description='Das PDF ließ sich nicht erzeugen')},
    )
    @action(
        detail=True, methods=['post'],
        permission_classes=[IsAuthenticated, DarfFestschreiben],
    )
    def festschreiben(self, request, pk=None):
        """Derselbe Vorgang wie die Admin-Aktion, über
        ``services.beleg_festschreiben``. Wer festgeschrieben hat, landet am
        Beleg und im Änderungsprotokoll."""
        beleg = self.get_object()
        eingabe = FestschreibenEingabeSerializer(data=request.data)
        eingabe.is_valid(raise_exception=True)
        festgeschrieben = services.beleg_festschreiben(
            beleg_id=beleg.pk, benutzer=request.user,
            mengen_bestaetigt=eingabe.validated_data['mengen_bestaetigt'],
        )
        self._protokollieren(request, festgeschrieben)

        # Trägt zusätzlich die Hinweise, die der Admin als Meldung zeigt.
        return Response(
            FestschreibungSerializer(
                festgeschrieben, context=self.get_serializer_context()).data,
        )

    @staticmethod
    def _protokollieren(request, beleg) -> None:
        """Schreibt den Vorgang in Djangos Änderungsprotokoll.

        Von Hand: Das Protokoll füllt sich nur auf den Formularwegen des
        Admin. Auf dem Proxy, nicht auf ``Beleg``, sonst erschiene der
        Eintrag im "Verlauf" der Rechnung nie. ``log_actions()`` nimmt den
        ContentType mit ``for_concrete_model=False``.
        """
        proxy = proxy_fuer(beleg.typ)

        LogEntry.objects.log_actions(
            request.user.pk,
            proxy.objects.filter(pk=beleg.pk),
            CHANGE,
            change_message=(
                f'Festgeschrieben als {beleg.nummer} (über die Schnittstelle).'
            ),
            single_object=True,
        )

    # -- Die Rückmeldung aus dem Archiv -------------------------------------

    @extend_schema(
        summary='Ablage im Archiv vermerken',
        description='Hält fest, unter welcher Dokument-ID der Beleg im Archiv '
                    'liegt. Derselbe Wert darf wiederholt gemeldet werden; ein '
                    'abweichender wird mit 409 abgelehnt.',
        request=ArchivvermerkSerializer,
        responses={200: BelegSerializer,
                   409: OpenApiResponse(description='Bereits unter anderer ID abgelegt')},
    )
    @action(
        detail=True, methods=['post'],
        permission_classes=[IsAuthenticated, DarfArchivieren],
        url_path='archiviert',
    )
    def archiviert(self, request, pk=None):
        """Hält fest, wo die Archivkopie liegt, auch bei festgeschriebenen
        Belegen, denn am Beleg selbst ändert sich nichts.

        Fachliche Fehler übersetzt ``core/exception_handler.py``.
        """
        eingabe = self.get_serializer(data=request.data)
        eingabe.is_valid(raise_exception=True)

        beleg = services.archivierung_vermerken(
            beleg_id=self.get_object().pk,
            paperless_id=eingabe.validated_data['paperless_document_id'],
        )

        return Response(
            BelegSerializer(beleg, context=self.get_serializer_context()).data,
            status=status.HTTP_200_OK,
        )
