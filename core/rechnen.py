"""Rundungsregel der Anwendung.

``quantize`` rundet ohne Angabe des Modus zur geraden Nachbarzahl
(``ROUND_HALF_EVEN``, 0,125 wird 0,12), kaufmännisch falsch. Mit der Regel an
mehreren Stellen wichen Vorschau und Rechnung um einen Cent voneinander ab::

    0,75 Std zu 89,50 EUR   Vorschau 67,12   Rechnung 67,13

Liegt in ``core``, weil alle Apps runden; importiert nur ``decimal``.
"""

from decimal import ROUND_HALF_UP, Decimal

#: Rundungsstufe für Geldbeträge.
CENT = Decimal('0.01')

#: Rundungsstufe für Werte, die keine Beträge sind, etwa Stunden in einer
#: Übersicht oder Monate Reichweite. Zwei Nachkommastellen täuschten dort eine
#: Genauigkeit vor, die der Wert nicht hat.
ZEHNTEL = Decimal('0.1')


def auf_stufe(wert, stufe: Decimal) -> Decimal:
    """Rundet kaufmännisch, die Hälfte von der Null weg.

    ``ROUND_HALF_UP`` rundet in Python betragsmäßig auf: 0,125 wird 0,13,
    -0,125 wird -0,13. Darauf beruht die Stornorechnung, die die
    Originalrechnung auf den Cent aufheben muss.
    """
    return Decimal(wert).quantize(stufe, rounding=ROUND_HALF_UP)


def auf_cent(wert) -> Decimal:
    """Rundet kaufmännisch auf zwei Nachkommastellen."""
    return auf_stufe(wert, CENT)
