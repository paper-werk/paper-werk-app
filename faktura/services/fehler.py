"""Fachliche Exceptions von faktura.

Alle erben von ``core.exceptions.FachlicherFehler``: In der API werden sie
zu einer Response mit dem Statuscode der Klasse (Default 400), im Admin zu
einer Meldung.
"""

from core.exceptions import FachlicherFehler


class FakturaError(FachlicherFehler):
    """Basisklasse, die Admin und Views fangen."""


class BelegOhnePositionen(FakturaError):
    pass


class MengeUeberschritten(FakturaError):
    """Abrechnung über die beauftragte Menge ohne Bestätigung. Mit
    Bestätigung zulässig (``beleg_festschreiben(mengen_bestaetigt=True)``)."""

    http_status = 409


class LeistungsdatumFehlt(FakturaError):
    pass


class EmpfaengerFehlt(FakturaError):
    pass


class FalscherStatus(FakturaError):
    """Operation passt nicht zum Zustand des Belegs; 409, weil der Request
    gültig ist, der Zustand ihn aber nicht zulässt."""

    http_status = 409


class WiedereroeffnenGesperrt(FakturaError):
    """Diese Belegart lässt sich nicht wieder öffnen. Rechnungen werden
    storniert oder korrigiert."""

    http_status = 409


class UngueltigerBetrag(FakturaError):
    pass


class UnzulaessigerSteuersatz(FakturaError):
    """Umsatzsteuer, wo keine ausgewiesen werden darf: Kleinunternehmer
    (§ 19 UStG) oder ein Steuerfall wie § 13b."""


class BereitsArchiviert(FakturaError):
    """Der Beleg ist bereits unter einer anderen Dokumentnummer archiviert,
    also vermutlich doppelt."""

    http_status = 409


class EmpfaengeradresseFehlt(FakturaError):
    """Keine E-Mail-Adresse für den Versand.

    Als Exception, damit der Beleg nicht fälschlich als versendet gilt.
    """

    http_status = 422


class VersandFehlgeschlagen(FakturaError):
    """Der Beleg ist festgeschrieben, der Versand fehlgeschlagen. Die
    Meldung enthält beides, damit klar ist, dass die Nummer vergeben ist."""

    http_status = 502


class KeineERechnung(FakturaError):
    """XML verlangt, aber für diesen Beleg nicht vorhanden. Gemeldet vor dem
    Festschreiben, wo es prüfbar ist."""

    http_status = 422


class DokumentFehlt(FakturaError):
    """PDF des Belegs nicht erzeugt oder nicht gespeichert; 422, weil der
    Request gültig, aber nicht ausführbar ist."""

    http_status = 422
