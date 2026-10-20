"""Zähler für die Seitenleiste, von Unfold je Seite aufgerufen (``badge``
eines Eintrags in ``faktura/apps.py``).

Nur schnelle Abfragen, weil jeder Zähler auf jeder Seite des Admins läuft.
Eine COUNT-Abfrage kostet bei zehn Jahren Daten 2,5 ms; ``offene_posten()``
kostet 0,1 s und ist deshalb ausgenommen.
"""

from .models import Beleg, BelegStatus, BelegTyp, Rechnungsart


def _entwuerfe(rechnungsart: str) -> str:
    """Zahl der Entwürfe dieser Rechnungsart, leer bei 0, damit Unfold
    keinen Zähler zeigt. Je Art getrennt wie die Listen, damit ein
    Abschlagsentwurf bei "Abschlagsrechnungen" zählt."""
    anzahl = Beleg.objects.filter(
        typ=BelegTyp.RECHNUNG, rechnungsart=rechnungsart,
        status=BelegStatus.ENTWURF).count()
    return str(anzahl) if anzahl else ''


def rechnungsentwuerfe(request) -> str:
    return _entwuerfe(Rechnungsart.NORMAL)


def abschlagsentwuerfe(request) -> str:
    return _entwuerfe(Rechnungsart.ABSCHLAG)


def schlussentwuerfe(request) -> str:
    return _entwuerfe(Rechnungsart.SCHLUSS)


def teilschlussentwuerfe(request) -> str:
    """Zähler im eingeklappten Abschnitt, sichtbar, wenn er geöffnet ist."""
    return _entwuerfe(Rechnungsart.TEILSCHLUSS)
