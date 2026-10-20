"""Admin der Leistungserfassung.

Der häufigste Fall, "heute von 7:00 bis 14:15 auf Projekt Halle Nord", soll
in drei Klicks erfasst sein, damit Zeiten zeitnah und nicht nachträglich
geschätzt eingetragen werden. Das Datum ist mit heute vorbelegt, die Person
ist der angemeldete Benutzer und erscheint nicht als Feld, die Dauer ergibt
sich aus von und bis.
"""

# Nur hier importierte Module durchlaufen ``@admin.register``; ein fehlender
# Import lässt den Menüpunkt ohne Fehlermeldung verschwinden.
from .erfassungszeile import ErfassungszeileAdmin
from .fremdleistung import (
    EingangsrechnungAdmin,
    ERechnungForm,
    FremdleistungAdmin,
    FremdleistungInline,
    KostensatzAdmin,
)
from .gemeinsam import (
    RECHT_FREMDE,
    AuftragspositionsAuswahl,
    AuftragspositionsWidget,
    LeistungsartFilter,
    LeistungsAuswahl,
    PersonenAuswahl,
    SortierFilter,
    ZeitraumFilter,
    ZustandFilter,
    entwuerfe_fuer,
    entwurfsname_von,
)

__all__ = [
    'AuftragspositionsAuswahl',
    'AuftragspositionsWidget',
    'ERechnungForm',
    'EingangsrechnungAdmin',
    'ErfassungszeileAdmin',
    'FremdleistungAdmin',
    'FremdleistungInline',
    'KostensatzAdmin',
    'LeistungsAuswahl',
    'LeistungsartFilter',
    'PersonenAuswahl',
    'RECHT_FREMDE',
    'SortierFilter',
    'ZeitraumFilter',
    'ZustandFilter',
    'entwuerfe_fuer',
    'entwurfsname_von',
]
