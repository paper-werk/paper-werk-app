"""Belege als Ereignisquelle (``docs/webhooks.md``).

Meldestellen rufen ``melden(aktion, beleg)`` auf. ``faktura/apps.py``
registriert die Quelle; ``core`` kennt Belege nur über sie.
"""

from django.urls import NoReverseMatch, reverse

from core import erweiterungen
from core.optimistic_locking import FELD, version_von

#: Name der Quelle, zugleich Schlüssel der Belegdaten in der Nutzlast.
QUELLE = 'beleg'

ANGELEGT = 'angelegt'
GEAENDERT = 'geaendert'
FESTGESCHRIEBEN = 'festgeschrieben'
VERSENDET = 'versendet'
WIEDEREROEFFNET = 'wiedereroeffnet'

AKTIONEN = [
    (ANGELEGT, 'Angelegt'),
    (GEAENDERT, 'Geändert'),
    (FESTGESCHRIEBEN, 'Festgeschrieben'),
    (VERSENDET, 'Versendet'),
    (WIEDEREROEFFNET, 'Wiedereröffnet'),
]


def melden(aktion: str, beleg) -> None:
    """Löst das Ereignis ``beleg.<aktion>`` aus."""
    erweiterungen.ereignis(QUELLE, aktion, beleg)


def typ(beleg) -> str:
    return beleg.typ


def nutzlast(beleg) -> dict:
    """Elementare Eigenschaften des Belegs; alles Weitere über ``api_url``.

    Liest den Beleg neu, weil die Meldung nach dem Commit läuft und die
    Instanz der Meldestelle veraltet sein kann (Version als
    ``F()``-Ausdruck, Felder per ``queryset.update()``).
    """
    from .admin.gemeinsam import adresse_im_admin
    from .models import Beleg
    from .services import anschriftgeber, belegsummen

    pk = beleg.pk
    beleg = (Beleg.objects.select_related('kunde', 'projekt__kunde', 'vorgaenger')
             .filter(pk=pk).first())
    if beleg is None:
        # In derselben Transaktion wieder gelöscht.
        return {'id': pk}
    vorgaenger = beleg.vorgaenger
    try:
        api = reverse('api:beleg-detail', args=[beleg.pk])
    except NoReverseMatch:
        api = ''
    return {
        'id': beleg.pk,
        'typ': beleg.typ,
        'nummer': beleg.nummer or None,
        'betreff': beleg.betreff,
        'brutto': f'{belegsummen(beleg).brutto:.2f}',
        'faellig_am': beleg.faellig_am,
        # Bei Projektbelegen der Kunde des Projekts.
        'kunde': {'name': kunde.name} if (kunde := anschriftgeber(beleg)) else None,
        'projekt': ({'id': beleg.projekt.pk, 'nummer': beleg.projekt.nummer,
                     'bezeichnung': beleg.projekt.bezeichnung}
                    if beleg.projekt else None),
        'vorgaenger': ({'id': vorgaenger.pk, 'typ': vorgaenger.typ,
                        'nummer': vorgaenger.nummer or None}
                       if vorgaenger else None),
        FELD: version_von(beleg),
        'admin_url': _absolut(adresse_im_admin(beleg)),
        'api_url': _absolut(api),
    }


def beispiel():
    """Jüngster Beleg für den Testaufruf einer Regel."""
    from .models import Beleg

    return Beleg.objects.order_by('-pk').first()


def _absolut(pfad: str) -> str | None:
    from core.webhooks import absolute_url

    return absolute_url(pfad) if pfad else None


def registrieren() -> None:
    """Registriert die Quelle; aufgerufen in ``FakturaConfig.ready``."""
    from .models import BelegTyp

    erweiterungen.ereignisquelle(erweiterungen.Ereignisquelle(
        name=QUELLE, titel='Beleg', aktionen=AKTIONEN,
        typen=list(BelegTyp.choices), typ=typ, nutzlast=nutzlast,
        beispiel=beispiel,
    ))
