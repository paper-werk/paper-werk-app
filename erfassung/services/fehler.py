"""Fachliche Fehler der Leistungserfassung; in der API eine Antwort mit dem
Statuscode der Klasse (Vorgabe 400)."""

from core.exceptions import FachlicherFehler


class ErfassungError(FachlicherFehler):
    """Basisklasse der fachlichen Fehler dieser App."""


class ProjektAbgeschlossen(ErfassungError):
    """Auf ein abgeschlossenes Projekt wird nicht mehr kontiert."""

    http_status = 409


class PersonFehlt(ErfassungError):
    """Erfassungszeile ohne Person; tritt nur aus Shell oder Skript auf."""


class ZeileAbgerechnet(ErfassungError):
    """Die Zeile steht auf einer Rechnung, auch auf einem Entwurf, der zur
    Prüfung beim Kunden sein kann. Freigegeben wird sie über die Rechnung
    (Position entfernen)."""

    http_status = 409


class LeistungNichtKontierbar(ErfassungError):
    """Die Katalogposition ist nicht für die Erfassung freigegeben."""


class LieferantFehlt(ErfassungError):
    """Eingangsrechnung ohne Lieferant."""

    http_status = 400


class ProjektUnbekannt(ErfassungError):
    """Die übermittelte Projektnummer existiert nicht.

    Eine fehlende Nummer ergibt eine Rechnung mit offenem Rest; eine falsche
    wird abgelehnt, damit der Tippfehler auffällt.
    """

    http_status = 400


class UebertragGesperrt(ErfassungError):
    """Die Eingangsrechnung ist bereits weiterberechnet, auch auf einem
    Entwurf; eine erneute Übernahme änderte dessen Kalkulation."""

    http_status = 409


class MehrereProjekte(ErfassungError):
    """Die Auswahl enthält Zeilen mehrerer Vorhaben; eine Rechnung gehört zu
    einem."""


class NichtsAbzurechnen(ErfassungError):
    """In der Auswahl steht keine Zeile, die abgerechnet werden könnte."""


class ZielUngeeignet(ErfassungError):
    """Der gewählte Beleg nimmt diese Zeilen nicht auf."""

    http_status = 409


class RechnungBereitsErfasst(ErfassungError):
    """Rechnungsnummer beim Lieferanten existiert bereits, etwa bei Eingang
    per Mail und per Post. Ersetzt den IntegrityError."""

    http_status = 409
