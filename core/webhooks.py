"""Versand von Ereignissen an die Ziele der Ereignisregeln (``docs/webhooks.md``).

``versenden`` ist als Empfänger in ``core.erweiterungen`` registriert
(``core/apps.py``). Es ermittelt die zutreffenden Regeln, baut die Nutzlast
im aufrufenden Thread, weil sie Datenbankzugriffe braucht, und sendet je
Regel in einem Hintergrund-Thread, damit die Maske nicht auf das Ziel
wartet. Antworten werden nicht ausgewertet; Fehler erscheinen nur als
Warnung im Log. Es gibt keine Wiederholung.
"""

import json
import logging
import threading

import requests
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from . import erweiterungen
from .models import Ereignisregel

logger = logging.getLogger(__name__)

#: Zeitlimit eines Aufrufs in Sekunden.
ZEITLIMIT = 5

#: Aktion des Testaufrufs aus der Maske.
TESTAKTION = 'test'


def absolute_url(pfad: str) -> str:
    """``pfad`` mit ``settings.PAPER_WERK_URL`` davor; ohne Einstellung der
    Pfad allein."""
    return f'{settings.PAPER_WERK_URL}{pfad}'


def nutzlast(quelle: str, aktion: str, objekt) -> dict:
    """Rumpf eines Aufrufs: Ereignis, Aktion, Zeit und die Eigenschaften
    des Objekts unter dem Namen der Quelle."""
    q = erweiterungen.ereignisquellen()[quelle]
    return {
        'ereignis': quelle,
        'aktion': aktion,
        'zeit': timezone.localtime().isoformat(timespec='seconds'),
        quelle: q.nutzlast(objekt) if objekt is not None else None,
    }


def zutreffende_regeln(quelle: str, aktion: str, objekt) -> list[Ereignisregel]:
    """Aktive Regeln der Quelle, deren Filter das Ereignis zulassen.

    Gefiltert wird in Python, weil es wenige Regeln gibt und die Listen in
    ``JSONField`` liegen.
    """
    typ = erweiterungen.ereignisquellen()[quelle].typ(objekt)
    return [regel for regel in Ereignisregel.objects.filter(aktiv=True, quelle=quelle)
            if regel.trifft_zu(aktion, typ)]


def senden(regel: Ereignisregel, daten: dict) -> requests.Response:
    """Ein POST an das Ziel der Regel. Wirft ``requests.RequestException``."""
    return requests.post(
        regel.url,
        data=json.dumps(daten, cls=DjangoJSONEncoder),
        headers={
            'Content-Type': 'application/json',
            'X-PaperWerk-Token': regel.token,
            'X-PaperWerk-Ereignis': f"{daten['ereignis']}.{daten['aktion']}",
        },
        timeout=ZEITLIMIT,
    )


def _senden_ohne_antwort(regel: Ereignisregel, daten: dict) -> None:
    try:
        antwort = senden(regel, daten)
    except requests.RequestException as fehler:
        logger.warning('Ereignisregel "%s": %s nicht erreicht: %s',
                       regel, regel.url, fehler)
        return
    if not antwort.ok:
        logger.warning('Ereignisregel "%s": %s antwortet mit Status %s.',
                       regel, regel.url, antwort.status_code)


def versenden(quelle: str, aktion: str, objekt) -> None:
    """Empfänger aller Ereignisse: sendet an jede zutreffende Regel."""
    regeln = zutreffende_regeln(quelle, aktion, objekt)
    if not regeln:
        return
    daten = nutzlast(quelle, aktion, objekt)
    for regel in regeln:
        threading.Thread(target=_senden_ohne_antwort, args=(regel, daten),
                         name=f'ereignis-{regel.pk}', daemon=True).start()


def probe_senden(regel: Ereignisregel) -> requests.Response:
    """Testaufruf aus der Maske: Aktion ``test`` mit einem Beispielobjekt
    der Quelle, im Request, damit die Maske die Antwort zeigen kann."""
    beispiel = erweiterungen.ereignisquellen()[regel.quelle].beispiel()
    return senden(regel, nutzlast(regel.quelle, TESTAKTION, beispiel))
