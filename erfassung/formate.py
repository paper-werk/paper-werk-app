"""Formatierung von Dauer und Personennamen.

Dauer wird in ganzen Minuten gespeichert, weil etwa 20 Minuten als
Dezimalstunde nicht exakt darstellbar sind (0,333 h) und ein Integer keine
Rundungsfrage aufwirft.

Auf der Rechnung steht die Stunde; die auf die Viertelstunde gerundete Zeit
ist als Dezimalzahl exakt darstellbar.
"""

#: Obergrenze für eine einzelne Zeile, zusätzlich als CheckConstraint in der
#: Datenbank.
MINUTEN_JE_TAG = 24 * 60


def dauer_zeigen(minuten: int) -> str:
    """Ganze Minuten als ``h:mm``, im selben Format wie die Eingabe."""
    stunden, rest = divmod(int(minuten), 60)
    return f'{stunden}:{rest:02d}'


def dauer_dezimal(minuten: int) -> str:
    """Ganze Minuten als Dezimalstunden mit Dezimalkomma (``1,50``).

    Für Auswertungen und Rechnungen, deren Einheit die Stunde ist. Zwei
    Nachkommastellen, damit Viertelstunden darstellbar sind.
    """
    return f'{int(minuten) / 60:.2f}'.replace('.', ',')


def personenname(benutzer) -> str:
    """Voller Name einer Person ("Anna Weber").

    Für Leistungsnachweise und Auswahllisten, in denen der Benutzername
    (``mmueller``, ``mmueller2``) nicht aussagekräftig ist. Ohne gepflegten
    Namen der Benutzername, damit die Zelle nicht leer ist.

    Braucht ``faktura`` dieselbe Funktion (etwa für
    ``Beleg.festgeschrieben_von``), gehört sie in eine gemeinsame App.
    """
    if benutzer is None:
        return ''
    return benutzer.get_full_name() or benutzer.get_username()
