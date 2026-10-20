"""Services der Leistungserfassung, ohne HTTP und DRF.

``fehler``      die fachlichen Fehler
``erfassen``    Zeilen erfassen und ändern, Leistungsnachweis
``abrechnen``   Vorschau und Übernahme in Rechnungen
``eingang``     Eingangsrechnungen aus Archiv und E-Rechnung
``auswertung``  Kosten, Stunden, offene Leistung, Auslastung, Altersstaffel

Importiert wird über ``erfassung.services``.
"""

from ..models import Erfassungszeile
from .abrechnen import (
    GRUND_NICHT_ABRECHENBAR,
    GRUND_OHNE_UMFANG,
    GRUND_OHNE_WERT,
    GRUND_SCHON_ABGERECHNET,
    NOCH_NICHT_ABGERECHNET,
    VIERTELSTUNDE,
    Abrechnungsposition,
    Auftragsgruppe,
    Fremdleistungsgruppe,
    Fremdposition,
    Grundlagengruppe,
    Personenzeilen,
    Uebernahmevorschau,
    abrechnungsvorschau,
    aufgerundete_stunden,
    in_rechnung_uebernehmen,
    offene_fremdleistungen,
    offene_leistungen,
)
from .auswertung import (
    Altersklasse,
    Aufwandszeile,
    Auslastung,
    Monatsstunden,
    Personalkosten,
    _fachnummer,
    _faecher,
    aeltester_offener_posten_je_projekt,
    aufwand_je_leistung,
    aufwand_je_monat,
    aufwand_je_person,
    auslastung_je_person,
    fremdkosten_je_projekt,
    offene_fremdleistung_gesamt,
    offene_fremdleistung_je_projekt,
    offene_leistung_gesamt,
    offene_leistung_je_projekt,
    offene_leistung_nach_alter,
    personalkosten_je_projekt,
    stunden_je_projekt,
    unvollstaendige_eingangsrechnungen,
)
from .eingang import (
    ERechnungBefund,
    eingangsrechnung_aus_archiv,
    eingangsrechnung_aus_archiv_erechnung,
    eingangsrechnung_aus_xml,
    erechnung_befund,
    projekt_aus_referenz,
)
from .erfassen import (
    Mengensumme,
    Zeitaufstellung,
    hat_nachweis,
    nachweis_zur_rechnung,
    zeile_aendern,
    zeile_erfassen,
    zeitaufstellung,
    zeitsumme,
)
from .fehler import (
    ErfassungError,
    LeistungNichtKontierbar,
    LieferantFehlt,
    MehrereProjekte,
    NichtsAbzurechnen,
    PersonFehlt,
    ProjektAbgeschlossen,
    ProjektUnbekannt,
    RechnungBereitsErfasst,
    UebertragGesperrt,
    ZeileAbgerechnet,
    ZielUngeeignet,
)

__all__ = [
    'GRUND_NICHT_ABRECHENBAR', 'GRUND_OHNE_UMFANG', 'GRUND_OHNE_WERT',
    'GRUND_SCHON_ABGERECHNET', 'NOCH_NICHT_ABGERECHNET', 'VIERTELSTUNDE',
    'Abrechnungsposition', 'Altersklasse', 'Auftragsgruppe', 'Aufwandszeile',
    'Auslastung', 'ERechnungBefund', 'ErfassungError', 'Erfassungszeile', 'Fremdleistungsgruppe',
    'Fremdposition', 'Grundlagengruppe', 'LeistungNichtKontierbar',
    'LieferantFehlt', 'MehrereProjekte', 'Mengensumme', 'Monatsstunden',
    'NichtsAbzurechnen', 'Personalkosten', 'Personenzeilen', 'PersonFehlt',
    'ProjektAbgeschlossen', 'ProjektUnbekannt', 'RechnungBereitsErfasst',
    'UebertragGesperrt', 'Uebernahmevorschau', 'ZeileAbgerechnet',
    'Zeitaufstellung', 'ZielUngeeignet', '_fachnummer', '_faecher',
    'abrechnungsvorschau', 'aeltester_offener_posten_je_projekt',
    'aufgerundete_stunden', 'aufwand_je_leistung', 'aufwand_je_monat',
    'aufwand_je_person', 'auslastung_je_person', 'eingangsrechnung_aus_archiv',
    'eingangsrechnung_aus_archiv_erechnung', 'eingangsrechnung_aus_xml',
    'erechnung_befund', 'fremdkosten_je_projekt', 'projekt_aus_referenz',
    'in_rechnung_uebernehmen', 'offene_fremdleistung_gesamt',
    'offene_fremdleistung_je_projekt', 'offene_fremdleistungen',
    'offene_leistung_gesamt', 'offene_leistung_je_projekt',
    'offene_leistung_nach_alter', 'offene_leistungen',
    'personalkosten_je_projekt', 'stunden_je_projekt',
    'unvollstaendige_eingangsrechnungen', 'zeile_aendern', 'zeile_erfassen',
    'hat_nachweis', 'nachweis_zur_rechnung',
    'zeitaufstellung', 'zeitsumme',
]
