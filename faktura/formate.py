"""Zahlenformate für alle Ausgaben von faktura.

Auf einem Beleg gelten drei Formate:

* **Geld** mit genau zwei Nachkommastellen und Tausenderpunkt
  (``4.487,50``).
* **Mengen** mit bis zu drei Nachkommastellen ohne nachlaufende Nullen
  (``10``, ``1,5``).
* **Steuersätze** ganzzahlig, wenn sie ganzzahlig sind (``19 %``), ohne
  Tausendertrennzeichen.

Ein Modul neben den Template-Filtern, weil die Admin-Listen ohne Template
formatieren; zwei getrennte Implementierungen liefen auseinander (``4487.50``
in der Liste, ``4.487,50`` auf dem Beleg).

``faktura/templatetags/faktura_extras.py`` registriert die Funktionen als
Filter, der Admin ruft sie direkt auf.

``USE_THOUSAND_SEPARATOR = False`` bleibt gesetzt, weil die Einstellung auch
die Eingabe betrifft: ``1.500`` in einem Mengenfeld mit drei Nachkommastellen
wäre mehrdeutig (1,5 oder 1500) und ergäbe ohne Fehlermeldung Faktor 1000.
Die Einstellung regelt die Eingabe, dieses Modul die Ausgabe.
"""

from decimal import Decimal

from django.utils.formats import date_format, number_format

from core import rechnen

#: Währung als Konstante. Mit einem zweiten Währungsraum gehört sie an den
#: Beleg; die Verwendungen sind über diesen Namen auffindbar.
WAEHRUNG = 'EUR'


def monat(jahr: int, monat: int) -> str:
    """Monat und Jahr ("Januar 2026") über ``date_format``, mit Djangos
    Übersetzung der Monatsnamen."""
    from datetime import date

    return date_format(date(jahr, monat, 1), 'F Y')


def geld(wert) -> str:
    """Betrag mit zwei Nachkommastellen und Tausenderpunkt: ``1.234,56``."""
    if wert is None:
        return ''
    return number_format(
        rechnen.auf_cent(wert),
        decimal_pos=2,
        force_grouping=True,
    )


def geld_mit_waehrung(wert) -> str:
    """Wie :func:`geld`, mit angehängter Währung: ``1.234,56 EUR``."""
    if wert is None:
        return ''
    return f'{geld(wert)} {WAEHRUNG}'


def euro(wert) -> str:
    """Wie :func:`geld`, mit Eurozeichen (``1.234,56 €``), für Masken und
    Auswertungen; Belege verwenden ``EUR`` (:func:`geld_mit_waehrung`)."""
    if wert is None:
        return ''
    return f'{geld(wert)} €'


def faktor(wert) -> str:
    """Verhältnis mit zwei Nachkommastellen (``1,90``), etwa der
    Stundenfaktor (Erlös je Stunde durch Kostensatz), ohne Tausenderpunkt.

    Gerundet mit ``rechnen.auf_cent``, weil ``number_format`` zum geraden
    Nachbarn rundet (12,345 wird 12,34); für Beträge gilt kaufmännische
    Rundung."""
    if wert is None:
        return ''
    return number_format(rechnen.auf_cent(wert), decimal_pos=2)


def menge(wert) -> str:
    """Menge ohne überflüssige Nullen: ``10``, ``1,5``, ``1.200``."""
    if wert is None:
        return ''
    return number_format(
        _gekuerzt(wert), decimal_pos=_nachkommastellen(wert), force_grouping=True
    )


def menge_im_feld(wert) -> str:
    """Menge für ein ``<input type="number">`` ohne nachlaufende Nullen, im
    technischen Format (``6``, ``1.5``, ``1200``).

    Der Punkt ist Dezimalpunkt, weil das Feld ihn so erwartet; das Komma
    zeigt der Browser. Für Text auf dem Beleg :func:`menge`."""
    return str(_gekuerzt(wert))


def prozent(wert) -> str:
    """Steuersatz als ``19 %`` beziehungsweise ``7,5 %``."""
    if wert is None:
        return ''
    return f'{number_format(_gekuerzt(wert), decimal_pos=_nachkommastellen(wert))} %'


def _gekuerzt(wert) -> Decimal:
    """Entfernt nachlaufende Nullen, ohne in die Exponentialschreibweise zu
    rutschen.

    ``Decimal('10.000').normalize()`` ergibt ``1E+1``, das auf einer
    Rechnung nicht lesbar ist.
    """
    wert = Decimal(wert).normalize()
    if wert == wert.to_integral_value():
        return rechnen.auf_stufe(wert, Decimal('1'))
    return wert


def _nachkommastellen(wert) -> int:
    return max(0, -_gekuerzt(wert).as_tuple().exponent)
