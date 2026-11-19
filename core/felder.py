"""Modellfelder, die mehrere Apps teilen."""

from django.db import models


class MengenFeld(models.DecimalField):
    """Menge einer Leistung: Belegposition, Erfassungszeile, Fremdleistung.

    Sechs Nachkommastellen, damit Bruchteile wie 0,333333 einer Pauschale
    den Betrag treffen, ohne Hilfsposition. Eine Definition, damit Mengen
    gleicher Bedeutung gleich genau sind. Dargestellt werden sie ohne
    nachlaufende Nullen (``formate.menge``, ``MengeWidget``).
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_digits', 13)
        kwargs.setdefault('decimal_places', 6)
        super().__init__(*args, **kwargs)


class ProzentFeld(models.DecimalField):
    """Prozentsatz: Zuschlag, Skonto, Umlage, Sicherheitseinbehalt.

    Sechs Nachkommastellen wie ``MengenFeld``, damit vertraglich krumme
    Sätze (0,123456 %) ohne Rundung übernommen werden. Vier Vorkommastellen.
    Dargestellt ohne nachlaufende Nullen (``formate.prozent``,
    ``ProzentWidget``). Der Steuersatz ist ausgenommen, weil die
    gesetzlichen Sätze mit zwei Stellen auskommen.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_digits', 10)
        kwargs.setdefault('decimal_places', 6)
        super().__init__(*args, **kwargs)
