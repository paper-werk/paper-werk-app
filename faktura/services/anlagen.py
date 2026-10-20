"""Anlagen zum Beleg, z. B. der Leistungsnachweis zur Rechnung.

Den Inhalt bestimmt die App, die die Anlage über
``core.erweiterungen.beleganlage()`` registriert (``erfassung``: der
Leistungsnachweis). Eine Anlage wird weder festgeschrieben noch
gespeichert; sie wird bei jedem Aufruf aus dem Beleg erzeugt, am Entwurf
wie am festgeschriebenen Beleg. Dort ist ihr Inhalt stabil, weil die
abgerechneten Zeilen gesperrt sind.
"""

from core import erweiterungen

from ..models import Beleg


def anlagenquellen(beleg: Beleg) -> dict[str, erweiterungen.Anlagenquelle]:
    """Registrierte Anlagen mit Inhalt zu diesem Beleg."""
    return {art: quelle
            for art, quelle in erweiterungen.beleganlagen(beleg.typ).items()
            if quelle.hat_inhalt(beleg)}


def anlage_pdf(beleg: Beleg, art: str) -> bytes | None:
    """Anlage als PDF, ``None``, wenn sie zu diesem Beleg fehlt."""
    quelle = anlagenquellen(beleg).get(art)
    if quelle is None:
        return None
    return quelle.pdf(beleg)


def anlage_dateiname(beleg: Beleg, titel: str) -> str:
    kennung = beleg.nummer or f'Entwurf_{beleg.pk}'
    return f'{titel}_{kennung}.pdf'.replace(' ', '_').replace('/', '-')
