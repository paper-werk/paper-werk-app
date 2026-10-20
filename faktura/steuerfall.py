"""Steuerfälle für Rechnungen ohne deutsche Umsatzsteuer.

Ein Steuerfall bestimmt den Satz (immer 0 %), den Pflichtvermerk im PDF
sowie Kategorie und Befreiungsgrund in der E-Rechnung. Die Angaben stehen an
einer Stelle, weil Vermerk und Kategorie zusammenpassen müssen.

Der Regelfall (Inland, Regelbesteuerung, auch mit 0-%-Positionen für
steuerfreie Leistungen nach § 4 UStG) ist der leere Wert.

Die Fälle und Vermerke folgen dem UStG in der Fassung von 2026 (§ 13b,
§ 14a, § 3a Abs. 2, § 4 Nr. 1 mit §§ 6, 6a). Welcher Fall auf einen Kunden
zutrifft, klärt der Betrieb mit seinem Steuerberater; die Software setzt
die Einstellung um.

Die Kategorien stammen aus UNTDID 5305, die Befreiungscodes aus der
VATEX-Liste, beide von EN 16931 vorgeschrieben.
"""

from dataclasses import dataclass

from django.db import models


class Steuerfall(models.TextChoices):
    """Am Kunden Vorbelegung, am Beleg maßgeblich.

    Der Regelfall ist der leere Wert, weil bestehende Belege so ohne
    Datenmigration gültig bleiben und das Übernahme-Skript im Admin ein
    Auswahlfeld nur füllt, wenn es leer ist (kunde_uebernehmen.js,
    ``istFrei``). Mit einem nicht leeren Default würde der Steuerfall des
    Kunden nie übernommen. Verworfen: ein eigener Eintrag "Inland".
    """

    REGULAER = '', 'Inland (Regelbesteuerung)'
    INLAND_13B = 'inland_13b', '§ 13b UStG: Kunde schuldet die Steuer (Inland)'
    EU_DIENSTLEISTUNG = ('eu_dienstleistung',
                         'Dienstleistung an Unternehmen in der EU '
                         '(Reverse Charge)')
    EU_LIEFERUNG = ('eu_lieferung',
                    'Warenlieferung an Unternehmen in der EU '
                    '(innergemeinschaftlich)')
    DRITTLAND_DIENSTLEISTUNG = ('drittland_dienstleistung',
                                'Dienstleistung an Unternehmen außerhalb der '
                                'EU (nicht steuerbar)')
    AUSFUHR = 'ausfuhr', 'Warenlieferung außerhalb der EU (Ausfuhr)'


@dataclass(frozen=True)
class Regel:
    """Auswirkung eines Steuerfalls auf PDF und E-Rechnung."""

    #: Steuerkategorie nach UNTDID 5305.
    kategorie: str
    #: Befreiungscode (BT-121) nach der VATEX-Liste.
    befreiungscode: str
    #: Pflichtvermerk im PDF und als Befreiungsgrund (BT-120).
    vermerk: str
    #: Ob die USt-IdNr. des Kunden auf die Rechnung (§ 14a UStG) und ins
    #: XML (BR-AE-02, BR-IC-02) gehört.
    braucht_kunden_ust_id: bool
    #: Ob die eigene USt-IdNr. ins XML gehört, weil die Steuernummer dort
    #: nicht genügt (BR-IC-02, BR-G-02, bei der EU-Dienstleistung § 14a
    #: Abs. 1).
    braucht_eigene_ust_id: bool
    #: Ob das XML eine USt-IdNr. enthalten darf; bei "nicht steuerbar"
    #: weder die eigene noch die des Kunden (BR-O-02).
    ohne_ust_id: bool = False
    #: Ob das XML das Lieferland (BT-80) braucht; Pflicht bei der
    #: innergemeinschaftlichen Lieferung (BR-IC-12).
    mit_lieferland: bool = False


REGELN: dict[str, Regel] = {
    Steuerfall.INLAND_13B: Regel(
        kategorie='AE',
        befreiungscode='VATEX-EU-AE',
        # Wortlaut nach § 14a Abs. 5 UStG.
        vermerk='Steuerschuldnerschaft des Leistungsempfängers '
                '(§ 13b UStG).',
        braucht_kunden_ust_id=True,
        braucht_eigene_ust_id=False,
    ),
    Steuerfall.EU_DIENSTLEISTUNG: Regel(
        kategorie='AE',
        befreiungscode='VATEX-EU-AE',
        vermerk='Steuerschuldnerschaft des Leistungsempfängers '
                '(Reverse Charge).',
        braucht_kunden_ust_id=True,
        braucht_eigene_ust_id=True,
    ),
    Steuerfall.EU_LIEFERUNG: Regel(
        kategorie='K',
        befreiungscode='VATEX-EU-IC',
        vermerk='Steuerfreie innergemeinschaftliche Lieferung '
                '(§ 4 Nr. 1 Buchst. b i. V. m. § 6a UStG).',
        braucht_kunden_ust_id=True,
        braucht_eigene_ust_id=True,
        mit_lieferland=True,
    ),
    Steuerfall.DRITTLAND_DIENSTLEISTUNG: Regel(
        kategorie='O',
        befreiungscode='VATEX-EU-O',
        vermerk='Nicht im Inland steuerbare Leistung '
                '(Leistungsort im Ausland, § 3a Abs. 2 UStG).',
        braucht_kunden_ust_id=False,
        braucht_eigene_ust_id=False,
        ohne_ust_id=True,
    ),
    Steuerfall.AUSFUHR: Regel(
        kategorie='G',
        befreiungscode='VATEX-EU-G',
        vermerk='Steuerfreie Ausfuhrlieferung '
                '(§ 4 Nr. 1 Buchst. a i. V. m. § 6 UStG).',
        braucht_kunden_ust_id=False,
        braucht_eigene_ust_id=True,
    ),
}


def regel(steuerfall: str) -> Regel | None:
    """Regel zu einem Steuerfall, ``None`` beim Regelfall."""
    return REGELN.get(steuerfall or '')


def vermerk(steuerfall: str) -> str:
    """Pflichtvermerk für das PDF, leer beim Regelfall."""
    gefunden = regel(steuerfall)
    return gefunden.vermerk if gefunden else ''
