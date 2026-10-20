"""Views der Schnittstelle ohne Fachdaten: Status, Verzeichnis, Selbstauskunft.

Jede View setzt ``permission_classes`` explizit. Die Vorgabe
``Modellrechte`` verlangt ein ``queryset`` und wirft ohne Modell eine
Ausnahme; so muss jede View ohne Modell ihre Rechte festlegen.
"""

from django.urls import reverse
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core import erweiterungen

# Apps, deren Rechte die Selbstauskunft zeigt, registriert über
# core.erweiterungen.fachliche_app() (faktura/apps.py, erfassung/apps.py).
# Die Rechte von admin, sessions und contenttypes werden ausgefiltert.
FACHLICHE_APPS = erweiterungen.fachliche_apps()


class StatusAnsicht(APIView):
    """Status für Healthchecks, als einzige View ohne Authentifizierung.

    Liefert keine Daten und keine Endpunkte. Dient Healthchecks und der
    Fehlersuche, bevor ein Token eingerichtet ist.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        summary='Lebenszeichen',
        description='Antwortet ohne Anmeldung. Für Healthchecks und die '
                    'Frage, ob der Dienst erreichbar ist.',
        responses={200: dict},
        examples=[OpenApiExample('Bereit', value={'dienst': 'paper-werk', 'stand': 'bereit'})],
    )
    def get(self, request):
        return Response({'dienst': 'paper-werk', 'stand': 'bereit'})


class WurzelAnsicht(APIView):
    """Verzeichnis der Endpunkte.

    Die URLs entstehen über ``reverse()``, damit eine umbenannte Route einen
    Fehler wirft. Die Liste kommt aus ``core.erweiterungen.api_endpunkte()``:
    die Archiv-Anbindung und die Endpunkte der Zusätze.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary='Inhaltsverzeichnis',
        description='Die verfuegbaren Endpunkte dieser Fassung.',
        responses={200: dict},
    )
    def get(self, request):
        verzeichnis = {
            praefix: request.build_absolute_uri(reverse(f'api:{name}-list'))
            for praefix, _viewset, name in erweiterungen.api_endpunkte()
        }
        for schluessel, url_name in erweiterungen.api_verweise().items():
            verzeichnis[schluessel] = request.build_absolute_uri(
                reverse(f'api:{url_name}'))
        for schluessel in ('ich', 'schema', 'doku'):
            verzeichnis[schluessel] = request.build_absolute_uri(
                reverse(f'api:{schluessel}'))
        return Response(verzeichnis)


class IchAnsicht(APIView):
    """Selbstauskunft: angemeldeter Benutzer und seine fachlichen Rechte.

    Zeigt beim Einrichten eines n8n-Workflows, welches Recht zu einer 403
    fehlt. Liefert nur Angaben zum eigenen Konto.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary='Selbstauskunft',
        description='Der angemeldete Benutzer und seine fachlichen Rechte, '
                    'nach Modell gruppiert.',
        responses={200: dict},
        examples=[OpenApiExample('Dienstbenutzer', value={
            'benutzer': 'n8n',
            'ist_mitarbeiter': False,
            'ist_verwalter': False,
            'rechte': {'faktura.beleg': ['view'], 'faktura.projekt': ['view']},
        })],
    )
    def get(self, request):
        return Response({
            'benutzer': request.user.get_username(),
            'ist_mitarbeiter': request.user.is_staff,
            'ist_verwalter': request.user.is_superuser,
            'rechte': self._rechte(request.user),
        })

    @staticmethod
    def _rechte(benutzer) -> dict[str, list[str]]:
        """Fachliche Rechte, nach Modell gruppiert.

        ``faktura.view_beleg`` wird zu ``faktura.beleg: ['view']``.
        ``get_all_permissions()`` berücksichtigt Gruppen und Superuser.
        """
        nach_modell: dict[str, list[str]] = {}

        for bezeichner in sorted(benutzer.get_all_permissions()):
            app, _, rest = bezeichner.partition('.')
            if app not in FACHLICHE_APPS:
                continue
            taetigkeit, _, modell = rest.partition('_')
            nach_modell.setdefault(f'{app}.{modell}', []).append(taetigkeit)

        return nach_modell
