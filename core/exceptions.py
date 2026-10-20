"""Gemeinsame Oberklasse der fachlichen Fehler.

Ein fachlicher Fehler ist ein erwarteter Zustand, den die Anwendung dem
Aufrufer meldet, etwa "der Beleg ist bereits festgeschrieben". Programmfehler
gehören ins Log. Über die Oberklasse erkennt ``core/exception_handler.py``
alle fachlichen Fehler, ohne die einzelnen Klassen zu kennen.

Die Fehlerklasse trägt ihren HTTP-Status selbst (``http_status``).

Verworfene Alternative: eine Zuordnungstabelle Fehlerklasse zu Statuscode in
der Web-Schicht. Die Fachschicht wüsste dann nichts von HTTP, aber ein neuer
Fehler ohne Tabelleneintrag ergäbe ohne Hinweis eine 400. Die Kopplung ist
eine Zahl, kein Import; die Services hängen nicht an DRF und bleiben für
Admin, Management-Commands und Tests nutzbar.

Vorgabe ist 400, weil der häufigste fachliche Fehler eine unzulässige Eingabe
ist.
"""


class FachlicherFehler(Exception):
    """Erwarteter Fehlerzustand, der dem Aufrufer gemeldet wird.

    ``http_status`` ist der Statuscode der API-Antwort. 400: Die übergebenen
    Daten sind unzulässig. 409: Die Daten sind zulässig, der aktuelle Zustand
    erlaubt den Vorgang aber nicht, etwa beim Ändern eines festgeschriebenen
    Belegs. 405 passt dort nicht, weil die Methode auf der Ressource erlaubt
    ist und nur im aktuellen Zustand scheitert.
    """

    http_status = 400
