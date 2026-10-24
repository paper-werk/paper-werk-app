"""Geschäftslogik von faktura, alle Operationen mit Beträgen.

Nicht in Views, Admin oder Templates. Kein HTTP, keine Abhängigkeit von
DRF, Parameter keyword-only. Hier erzwungen: kaufmännische Rundung,
lückenlose Nummern, Unveränderlichkeit festgeschriebener Belege.

``fehler``         die fachlichen Fehler
``summen``         Rechenkern: Positionsnetto, Steuer je Satz, Belegsummen
``anlegen``        Belege anlegen, Stammdaten übernehmen, kopieren, umwandeln
``festschreiben``  Nummer, Festschreiben, Wiedereröffnen, Dokument speichern
``archivierung``   Upload nach Paperless, Archivvermerk, Archivprüfung
``versand``        Versand per E-Mail
``korrektur``      Storno, Rechnungskorrektur, Mahnung
``zahlungen``      offene Posten, Zahlungseingang
``projekte``       Projekt aus Text auflösen, Projektakte, Projektstände
``auswertung``     Umsatzverlauf, Auftragseingang, Umsatz je Kunde
``zuschlaege``     Titelsummen und Zuschläge aus der Positionsnummer
``kumuliert``      kumulierte Darstellung der Abschlagsrechnung

Importiert wird über ``faktura.services``.
"""

from ..archiv import ArchivFehler
from ..models import BelegNichtAenderbar
from .abnahme import leistungszeitraum_vorschlag, rechnung_aus_abnahme
from .abschlaege import (
    OffenerAbschlag,
    abgerechnet_in,
    abschlaege_absetzen,
    abschlagsrest,
    abzugsblock,
    anrechenbare_abschlagspositionen,
    offene_abgesetzte_abschlaege,
    veraltete_abschlagsreste,
)
from .anlagen import (
    anlage_dateiname,
    anlage_pdf,
    anlagenquellen,
)
from .anlegen import (
    ANSCHRIFTSFELDER,
    DUPLIZIERBAR,
    Duplikat,
    anschriftgeber,
    beleg_anlegen,
    beleg_duplizieren,
    beleg_umwandeln,
    empfaenger_abweichungen,
    nachtrag_anlegen,
    position_hinzufuegen,
    stammdaten_uebernehmen,
    stammdatenwerte,
)
from .archivierung import (
    Archivbefund,
    Archivbericht,
    archivierung_vermerken,
    beleg_archivieren,
    belegarchiv_pruefen,
)
from .auswertung import (
    Kundenumsatz,
    Mahnstand,
    Monatssumme,
    auftragseingang_je_monat,
    fakturaverlauf,
    fakturiert_im_jahr,
    gemahnte_rechnungen,
    umsatz_je_kunde,
)
from .fehler import (
    BelegOhnePositionen,
    BereitsArchiviert,
    DokumentFehlt,
    EmpfaengeradresseFehlt,
    EmpfaengerFehlt,
    FakturaError,
    FalscherStatus,
    KeineERechnung,
    LeistungsdatumFehlt,
    MengeUeberschritten,
    UngueltigerBetrag,
    UnzulaessigerSteuersatz,
    VersandFehlgeschlagen,
    WiedereroeffnenGesperrt,
)
from .festschreiben import (
    NUMMERNKREIS,
    PRAEFIX,
    Mengenueberschreitung,
    abgerechnete_mengen,
    beleg_festschreiben,
    beleg_wiedereroeffnen,
    berechneter_wert,
    erechnung_neu_ausstellen,
    mengenueberschreitungen,
    naechste_belegnummer,
)
from .korrektur import (
    mahngebuehr,
    mahnstufe_angleichen,
    mahnung_erstellen,
    nachlass_stornieren,
    rechnung_korrigieren,
    rechnungskorrektur_erstellen,
)
from .kumuliert import (
    KumulierterAbschlag,
    ist_kumulierbar,
    kumulierter_abschlag,
    vorgaenger_abschlaege,
)
from .projekte import (
    Aufloesung,
    Projektauswertung,
    Projektstand,
    Projekttreffer,
    projekt_aufloesen,
    projektakte,
    projektstaende,
)
from .summen import (
    POSITIONSNETTO,
    Belegmengensumme,
    Belegsummen,
    Steueranteil,
    belegsummen,
    bruttosummen,
    leistungssummen,
    positionssumme,
    summe_ueber,
    umsatzsummen,
)
from .versand import (
    Versandanhang,
    absenderadresse,
    beleg_versenden,
    versand_geht_hinaus,
    versandformat,
)
from .zahlungen import (
    ZAHLUNGSSTAND_ABGERECHNET,
    ZAHLUNGSSTAND_BEZAHLT,
    ZAHLUNGSSTAND_OFFEN,
    ZAHLUNGSSTAND_TEXT,
    ZAHLUNGSSTAND_UEBER_FRIST,
    OffenerPosten,
    Postenstand,
    nachlaesse,
    nachlaesse_vorladen,
    nachlass,
    offene_posten,
    offener_betrag,
    tage_ueber_frist,
    zahlung_verbuchen,
    zahlungsstand,
)
from .zuschlaege import (
    Titelsumme,
    bezugsfehler,
    gehoert_zu,
    ohne_bezug,
    optionale_zuschlaege,
    titelsummen,
    zuschlaege_nachrechnen,
    zuschlagsbasis,
    zuschlagsbeschreibung,
)

__all__ = [
    'Titelsumme', 'bezugsfehler', 'gehoert_zu', 'ohne_bezug',
    'optionale_zuschlaege', 'titelsummen',
    'zuschlaege_nachrechnen',
    'zuschlagsbasis', 'zuschlagsbeschreibung',
    'ZAHLUNGSSTAND_ABGERECHNET', 'ZAHLUNGSSTAND_BEZAHLT', 'ZAHLUNGSSTAND_OFFEN',
    'ZAHLUNGSSTAND_TEXT', 'ZAHLUNGSSTAND_UEBER_FRIST', 'tage_ueber_frist', 'zahlungsstand',
    'leistungszeitraum_vorschlag', 'rechnung_aus_abnahme',
    'leistungssummen', 'umsatzsummen', 'OffenerAbschlag', 'abschlaege_absetzen',
    'anrechenbare_abschlagspositionen', 'offene_abgesetzte_abschlaege',
    'abgerechnet_in', 'abschlagsrest', 'abzugsblock', 'veraltete_abschlagsreste',
    'KumulierterAbschlag', 'ist_kumulierbar', 'kumulierter_abschlag',
    'vorgaenger_abschlaege',
    'ANSCHRIFTSFELDER', 'DUPLIZIERBAR', 'NUMMERNKREIS', 'POSITIONSNETTO', 'PRAEFIX',
    'ArchivFehler', 'Archivbefund', 'Archivbericht', 'Aufloesung',
    'BelegNichtAenderbar', 'BelegOhnePositionen', 'Belegmengensumme',
    'Belegsummen', 'BereitsArchiviert', 'DokumentFehlt', 'Duplikat',
    'EmpfaengerFehlt',
    'EmpfaengeradresseFehlt', 'FakturaError', 'FalscherStatus',
    'KeineERechnung', 'Kundenumsatz', 'LeistungsdatumFehlt', 'Mahnstand',
    'MengeUeberschritten', 'Mengenueberschreitung', 'Monatssumme', 'OffenerPosten', 'Postenstand',
    'Projektauswertung', 'Projektstand', 'Projekttreffer', 'Steueranteil',
    'UngueltigerBetrag', 'UnzulaessigerSteuersatz', 'VersandFehlgeschlagen',
    'Versandanhang', 'WiedereroeffnenGesperrt', 'abgerechnete_mengen',
    'absenderadresse', 'anschriftgeber', 'beleg_duplizieren',
    'anlage_dateiname',
    'anlage_pdf',
    'anlagenquellen',
    'archivierung_vermerken',
    'auftragseingang_je_monat', 'beleg_anlegen', 'beleg_archivieren',
    'beleg_festschreiben', 'beleg_umwandeln', 'beleg_versenden',
    'beleg_wiedereroeffnen', 'belegarchiv_pruefen', 'belegsummen', 'bruttosummen',
    'berechneter_wert', 'empfaenger_abweichungen', 'erechnung_neu_ausstellen',
    'fakturaverlauf', 'fakturiert_im_jahr', 'gemahnte_rechnungen',
    'mahngebuehr', 'mahnstufe_angleichen', 'mahnung_erstellen',
    'mengenueberschreitungen', 'nachlaesse', 'nachlaesse_vorladen', 'nachlass',
    'naechste_belegnummer', 'nachtrag_anlegen',
    'offene_posten', 'offener_betrag', 'position_hinzufuegen',
    'positionssumme', 'projekt_aufloesen', 'projektakte', 'projektstaende',
    'nachlass_stornieren', 'rechnung_korrigieren',
    'rechnungskorrektur_erstellen',
    'stammdaten_uebernehmen', 'stammdatenwerte', 'summe_ueber',
    'umsatz_je_kunde', 'versand_geht_hinaus', 'versandformat',
    'zahlung_verbuchen',
]
