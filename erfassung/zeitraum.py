"""Relative Zeiträume wie "letztes Quartal", als Regel in der URL.

Djangos ``DateFieldListFilter`` schreibt absolute Daten in den Link, ein
Lesezeichen bliebe bei "August 2026", und bietet weder "letzter Monat" noch
"letztes Quartal".

Ohne Datenbank: ``heute`` ist Parameter, damit Monatsenden und
Jahreswechsel ohne Fixtures prüfbar sind.
"""

from datetime import date, timedelta

from django.db import models


class Zeitraum(models.TextChoices):
    """Auswählbare Zeitraumregeln.

    ``TextChoices`` ohne Datenbankbezug, deshalb neben der Umrechnung und
    nicht in ``models.py``; Regel und Umrechnung werden in derselben Datei
    ergänzt.
    """

    ALLES = 'alles', 'Alle Zeiträume'
    HEUTE = 'heute', 'Heute'
    DIESE_WOCHE = 'diese_woche', 'Diese Woche'
    LETZTE_WOCHE = 'letzte_woche', 'Letzte Woche'
    DIESER_MONAT = 'dieser_monat', 'Dieser Monat'
    LETZTER_MONAT = 'letzter_monat', 'Letzter Monat'
    DIESES_QUARTAL = 'dieses_quartal', 'Dieses Quartal'
    LETZTES_QUARTAL = 'letztes_quartal', 'Letztes Quartal'
    DIESES_JAHR = 'dieses_jahr', 'Dieses Jahr'
    LETZTES_JAHR = 'letztes_jahr', 'Letztes Jahr'
    LETZTE_7_TAGE = 'letzte_7_tage', 'Letzte 7 Tage'
    LETZTE_30_TAGE = 'letzte_30_tage', 'Letzte 30 Tage'
    FEST = 'fest', 'Fester Zeitraum'


def zeitraum_grenzen(schluessel, heute, von=None, bis=None):
    """Grenzen eines Zeitraums als ``(von, bis_ausschliesslich)``.

    Die obere Grenze ist ausschließlich, ``(1.8., 1.9.)`` ist der August,
    wie in Djangos Filtern (``__gte``/``__lt``). Bei Zeitstempeln vermeidet
    das Fehler mit 23:59:59.

    ``None`` bedeutet keine Grenze; bei ``ALLES`` sind beide ``None``.

    ``von`` und ``bis`` gelten nur bei ``FEST`` und sind einschließlich
    gemeint. Die Umrechnung auf die ausschließliche Grenze erfolgt nur hier.
    """
    if schluessel == Zeitraum.FEST:
        return von, (bis + timedelta(days=1)) if bis is not None else None

    regel = _REGELN.get(schluessel)
    if regel is None:
        # Ein unbekannter Schlüssel (getippte URL, spätere Version) wirft eine
        # Ausnahme, weil "keine Grenze" mehr zeigte als gewählt.
        raise ValueError(f'Unbekannter Zeitraum: {schluessel!r}')
    return regel(heute)


def _wochenanfang(tag: date) -> date:
    """Montag der Woche von ``tag``."""
    return tag - timedelta(days=tag.weekday())


def _monatsanfang(tag: date) -> date:
    return tag.replace(day=1)


def _quartalsanfang(tag: date) -> date:
    return date(tag.year, (tag.month - 1) // 3 * 3 + 1, 1)


def _monate_spaeter(erster: date, anzahl: int) -> date:
    """Monatserster ``anzahl`` Monate nach ``erster``, auch negativ.

    Über die Gesamtzahl der Monate, damit der Jahreswechsel in beide
    Richtungen stimmt; ``replace(month=...)`` könnte das nicht. Pythons
    Ganzzahldivision rundet ab: ``-3 // 12`` ist ``-1``, also das Vorjahr.
    """
    monate = erster.month - 1 + anzahl
    return date(erster.year + monate // 12, monate % 12 + 1, 1)


#: Je Schlüssel außer FEST genau eine Regel.
#
# Als Dict, damit ein Test die Vollständigkeit prüfen kann.
_REGELN = {
    Zeitraum.ALLES:
        lambda h: (None, None),
    Zeitraum.HEUTE:
        lambda h: (h, h + timedelta(days=1)),
    Zeitraum.DIESE_WOCHE:
        lambda h: (_wochenanfang(h), _wochenanfang(h) + timedelta(days=7)),
    Zeitraum.LETZTE_WOCHE:
        lambda h: (_wochenanfang(h) - timedelta(days=7), _wochenanfang(h)),
    Zeitraum.DIESER_MONAT:
        lambda h: (_monatsanfang(h), _monate_spaeter(_monatsanfang(h), 1)),
    Zeitraum.LETZTER_MONAT:
        lambda h: (_monate_spaeter(_monatsanfang(h), -1), _monatsanfang(h)),
    Zeitraum.DIESES_QUARTAL:
        lambda h: (_quartalsanfang(h), _monate_spaeter(_quartalsanfang(h), 3)),
    Zeitraum.LETZTES_QUARTAL:
        lambda h: (_monate_spaeter(_quartalsanfang(h), -3), _quartalsanfang(h)),
    Zeitraum.DIESES_JAHR:
        lambda h: (date(h.year, 1, 1), date(h.year + 1, 1, 1)),
    Zeitraum.LETZTES_JAHR:
        lambda h: (date(h.year - 1, 1, 1), date(h.year, 1, 1)),
    # Sieben Tage einschließlich heute, also h-6 bis h.
    #
    # Abweichend von Django, das "today - 7 Tage bis morgen" und damit acht
    # Tage rechnet (django/contrib/admin/filters.py).
    Zeitraum.LETZTE_7_TAGE:
        lambda h: (h - timedelta(days=6), h + timedelta(days=1)),
    Zeitraum.LETZTE_30_TAGE:
        lambda h: (h - timedelta(days=29), h + timedelta(days=1)),
}

#: Einträge der Auswahlliste. Ohne ALLES, weil Django "Alle" selbst anbietet,
#: und ohne FEST, weil die Filterleiste keine Datumsfelder hat.
AUSWAHLBAR = [z for z in Zeitraum if z not in (Zeitraum.ALLES, Zeitraum.FEST)]


__all__ = ['AUSWAHLBAR', 'Zeitraum', 'zeitraum_grenzen']
