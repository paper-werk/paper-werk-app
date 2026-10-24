"""Auswertungen der erfassten Zeit und der Fremdleistung.

Kosten und Stunden beruhen auf der ungerundeten Zeit. Nicht abrechenbare
Stunden zählen mit, weil Kulanz Kosten verursacht. Der offene Wert läuft über
``abrechnungsvorschau``, damit er auf den Cent mit der späteren Rechnung
übereinstimmt.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import (
    Case,
    DecimalField,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    When,
)
from django.utils import timezone

from core import rechnen
from faktura.models import Leistungsart

from ..formate import dauer_zeigen, personenname
from ..models import Erfassungszeile, Fremdleistung, Kostensatz
from .abrechnen import NOCH_NICHT_ABGERECHNET, abrechnungsvorschau


def offene_leistung_je_projekt(*, projekte=None) -> dict[int, Decimal]:
    """Nettowert der nicht abgerechneten Leistung je Projekt; Projekte ohne
    offene Leistung fehlen. ``projekte`` (Primärschlüssel) schränkt ein.

    Über ``abrechnungsvorschau``, weil eine SQL-Summe die Rundung auf die
    Viertelstunde je Leistung nicht abbildet. Eine Abfrage über alle offenen
    Zeilen, gruppiert und gerundet in Python. Zeilen auf Rechnungsentwürfen
    zählen mit.
    """
    zeilen = (
        Erfassungszeile.objects
        .filter(NOCH_NICHT_ABGERECHNET, abrechenbar=True)
        .select_related('leistung', 'projekt', 'abgerechnet_in__beleg')
    )
    if projekte is not None:
        zeilen = zeilen.filter(projekt__in=projekte)

    nach_projekt: dict[int, list] = {}
    for zeile in zeilen:
        nach_projekt.setdefault(zeile.projekt_id, []).append(zeile)

    # Ein Projekt je Aufruf, weil die Vorschau mehrere ablehnt.
    return {
        projekt_id: abrechnungsvorschau(gruppe, entwuerfe_zaehlen=True).netto
        for projekt_id, gruppe in nach_projekt.items()
    }


@dataclass(frozen=True)
class Personalkosten:
    """Personalkosten je Projekt und nicht bewertete Stunden.

    Ist ``ohne_satz`` nicht leer, sind die Kosten zu niedrig und die
    Deckungsbeiträge zu hoch.
    """

    je_projekt: dict[int, Decimal]
    #: Personen (``benutzer_id``) ohne Kostensatz für ihre Stunden.
    ohne_satz: set
    #: Unbewertete Minuten dieser Personen.
    minuten_ohne_satz: int

    @property
    def vollstaendig(self) -> bool:
        return not self.ohne_satz


def personalkosten_je_projekt(*, nur_laufende: bool = True,
                              projekte=None) -> Personalkosten:
    """Erfasste Zeit mal dem am Tag gültigen Kostensatz.

    Ungerundete Zeit, einschließlich nicht abrechenbarer Stunden, nur
    Zeitleistungen (eine Anfahrt ist Sachaufwand). Der Satz gilt zum Datum
    der Zeile, eine Lohnerhöhung im Juli verteuert den Juni nicht.
    ``projekte`` (Primärschlüssel) schränkt ein.

    Berechnet in der Datenbank: Der Satz je Zeile kommt aus einer Subquery
    nach der Regel von ``Kostensatz.satz_am`` (jüngster Satz mit
    ``gueltig_ab`` bis zum Tag). Summiert wird Minuten mal Satz exakt,
    geteilt durch 60 und gerundet je Projekt. Eine Bewertung je Zeile in
    Python bedeutete bei zehn Jahren Daten 73.000 Aufrufe (Lasttest).
    """
    zeilen = Erfassungszeile.objects.filter(dauer_minuten__gt=0)
    if nur_laufende:
        zeilen = zeilen.filter(projekt__abgeschlossen=False)
    if projekte is not None:
        zeilen = zeilen.filter(projekt__in=projekte)

    zeilen = zeilen.annotate(satz=Subquery(
        Kostensatz.objects
        .filter(benutzer=OuterRef('benutzer_id'),
                gueltig_ab__lte=OuterRef('datum'))
        .order_by('-gueltig_ab')
        .values('satz')[:1]
    ))

    bewertet = (
        zeilen.filter(satz__isnull=False)
        .values('projekt_id')
        .annotate(minutenkosten=Sum(
            F('dauer_minuten') * F('satz'),
            output_field=DecimalField(max_digits=20, decimal_places=2)))
        .values_list('projekt_id', 'minutenkosten')
    )
    ohne = dict(
        zeilen.filter(satz__isnull=True)
        .values('benutzer_id')
        .annotate(minuten=Sum('dauer_minuten'))
        .values_list('benutzer_id', 'minuten')
    )

    # Gerundet je Projekt am Ende.
    return Personalkosten(
        je_projekt={projekt_id: rechnen.auf_cent(summe / 60)
                    for projekt_id, summe in bewertet},
        ohne_satz=set(ohne),
        minuten_ohne_satz=sum(ohne.values()),
    )


@dataclass(frozen=True)
class Aufwandszeile:
    """Zeile der Aufwandsübersicht je Person oder Leistung; Zeit und Menge
    stehen getrennt."""

    name: str
    minuten: int
    menge: Decimal | None
    einheit: str
    zeilen: int

    @property
    def zeit(self) -> str:
        return dauer_zeigen(self.minuten) if self.minuten else ''

    @property
    def umfang(self) -> str:
        if self.menge is None or not self.menge:
            return ''
        return f'{self.menge.normalize():f} {self.einheit}'.strip()


@dataclass(frozen=True)
class Monatsstunden:
    """Erfasste Zeit eines Monats für den Verlauf in der Projektakte."""

    jahr: int
    monat: int
    minuten: int

    @property
    def beschriftung(self) -> str:
        return f'{self.monat:02d}/{self.jahr}'

    @property
    def stunden(self) -> float:
        """Stunden als Dezimalzahl, nur für das Diagramm; sonst bleibt die
        Zeit in ganzen Minuten."""
        return round(self.minuten / 60, 2)


def aufwand_je_monat(projekt, *, monate: int = 12) -> list[Monatsstunden]:
    """Erfasste Zeit je Monat für die letzten ``monate`` einschließlich,
    leere Monate mit null. Alle Zeilen zählen, unabhängig von Abrechnung."""
    from django.db.models.functions import TruncMonth
    from django.utils import timezone

    heute = timezone.localdate()
    gesamtmonate = heute.year * 12 + (heute.month - 1) - (monate - 1)
    beginn = date(gesamtmonate // 12, gesamtmonate % 12 + 1, 1)

    summen = (
        Erfassungszeile.objects
        .filter(projekt=projekt, datum__gte=beginn, datum__lte=heute)
        .annotate(monat=TruncMonth('datum'))
        .values('monat')
        .annotate(minuten=Sum('dauer_minuten'))
    )
    gefunden = {(z['monat'].year, z['monat'].month): z['minuten'] or 0
                for z in summen}

    return [
        Monatsstunden(
            jahr=(gesamtmonate + versatz) // 12,
            monat=(gesamtmonate + versatz) % 12 + 1,
            minuten=gefunden.get(
                ((gesamtmonate + versatz) // 12,
                 (gesamtmonate + versatz) % 12 + 1), 0),
        )
        for versatz in range(monate)
    ]


def aufwand_je_person(projekt, auftrag=None) -> list[Aufwandszeile]:
    """Arbeitszeit je Person am Vorhaben, ohne Beträge.

    ``auftrag`` schränkt auf einen Auftrag ein (Auftragsakte).
    Mengenleistungen zählen als Zeilen; über Einheiten hinweg wird nicht
    summiert.
    """
    auswahl = Erfassungszeile.objects.filter(projekt=projekt)
    if auftrag is not None:
        auswahl = auswahl.filter(auftragsposition__beleg=auftrag)

    zeilen: dict[int, dict] = {}
    for zeile in auswahl.select_related('benutzer'):
        eintrag = zeilen.setdefault(zeile.benutzer_id, {
            'name': personenname(zeile.benutzer), 'minuten': 0, 'zeilen': 0})
        eintrag['minuten'] += zeile.dauer_minuten
        eintrag['zeilen'] += 1

    ergebnis = [
        Aufwandszeile(name=e['name'], minuten=e['minuten'], menge=None,
                      einheit='', zeilen=e['zeilen'])
        for e in zeilen.values()
    ]
    # Bei Gleichstand nach Namen, damit die Reihenfolge stabil ist.
    ergebnis.sort(key=lambda z: (-z.minuten, z.name))
    return ergebnis


def aufwand_je_leistung(projekt) -> list[Aufwandszeile]:
    """Aufwand am Vorhaben je Leistung: Zeitleistungen mit Dauer, andere mit
    Menge, ungerundet."""
    zeilen: dict[tuple, dict] = {}
    for zeile in (Erfassungszeile.objects
                  .filter(projekt=projekt)
                  .select_related('leistung', 'auftragsposition')):
        schluessel = (('auftrag', zeile.auftragsposition_id)
                      if zeile.auftragsposition_id
                      else ('katalog', zeile.leistung_id))
        eintrag = zeilen.setdefault(schluessel, {
            'name': zeile.leistungsbezeichnung,
            'einheit': zeile.einheit,
            'ist_zeit': zeile.leistungsart == Leistungsart.ZEIT,
            'minuten': 0, 'menge': Decimal('0'), 'zeilen': 0})
        eintrag['minuten'] += zeile.dauer_minuten
        eintrag['menge'] += zeile.menge or Decimal('0')
        eintrag['zeilen'] += 1

    ergebnis = [
        Aufwandszeile(
            name=e['name'],
            minuten=e['minuten'],
            menge=None if e['ist_zeit'] else e['menge'],
            einheit='Std' if e['ist_zeit'] else e['einheit'],
            zeilen=e['zeilen'],
        )
        for e in zeilen.values()
    ]
    ergebnis.sort(key=lambda z: (-z.minuten, z.name))
    return ergebnis


def fremdkosten_je_projekt(*, nur_laufende: bool = True,
                           projekte=None) -> dict[int, Decimal]:
    """Fremdleistung je Projekt zum Einkaufspreis, alle Positionen
    einschließlich nicht abrechenbarer und abgerechneter. Summe der
    Zeilenbeträge in der Datenbank."""
    positionen = Fremdleistung.objects.all()
    if nur_laufende:
        positionen = positionen.filter(projekt__abgeschlossen=False)
    if projekte is not None:
        positionen = positionen.filter(projekt__in=projekte)

    return {
        zeile['projekt']: zeile['summe'] or Decimal('0.00')
        for zeile in positionen.values('projekt').annotate(
            summe=Sum('einkauf_netto'))
    }


def offene_fremdleistung_je_projekt(*, projekte=None) -> dict[int, Decimal]:
    """Abrechenbare Fremdleistung auf keiner Rechnung, zum Einkaufspreis.

    Der Verkaufswert entsteht erst an der Rechnungsposition; ohne Aufschlag
    ist der Wert eine Untergrenze. Summiert in der Datenbank.
    """
    positionen = Fremdleistung.objects.filter(NOCH_NICHT_ABGERECHNET,
                                              weiterberechenbar=True)
    if projekte is not None:
        positionen = positionen.filter(projekt__in=projekte)
    return {zeile['projekt']: zeile['summe'] or Decimal('0.00')
            for zeile in positionen.values('projekt')
            .annotate(summe=Sum('einkauf_netto'))}


def aeltester_offener_posten_je_projekt() -> dict[int, "date"]:
    """Frühestes Datum nicht abgerechneter Posten je Vorhaben aus
    Erfassungszeilen und Fremdleistungen (Rechnungsdatum), in zwei
    Abfragen."""
    from django.db.models import Min

    aeltestes: dict[int, date] = {}

    zeilen = (
        Erfassungszeile.objects
        .filter(NOCH_NICHT_ABGERECHNET, abrechenbar=True)
        .values('projekt_id')
        .annotate(aeltestes=Min('datum'))
    )
    for zeile in zeilen:
        aeltestes[zeile['projekt_id']] = zeile['aeltestes']

    fremdes = (
        Fremdleistung.objects
        .filter(NOCH_NICHT_ABGERECHNET, weiterberechenbar=True)
        .values('projekt_id')
        .annotate(aeltestes=Min('rechnung__datum'))
    )
    for zeile in fremdes:
        vorhanden = aeltestes.get(zeile['projekt_id'])
        if vorhanden is None or zeile['aeltestes'] < vorhanden:
            aeltestes[zeile['projekt_id']] = zeile['aeltestes']

    return aeltestes


def offene_fremdleistung_gesamt() -> Decimal:
    return sum(offene_fremdleistung_je_projekt().values(), Decimal('0.00'))


def unvollstaendige_eingangsrechnungen() -> list:
    """Eingangsrechnungen, deren Positionen nicht den Betrag ergeben, der
    größte offene Rest zuerst.

    Vollständige Rechnungen filtert die Datenbank mit der Bedingung von
    ``ist_vollstaendig`` (Betrag gleich Summe der Zeilenbeträge); geladen
    werden nur die übrigen.
    """
    from django.db.models.functions import Coalesce

    from ..models import Eingangsrechnung

    rechnungen = (
        Eingangsrechnung.objects
        .annotate(zugeordnet_summe=Coalesce(
            Sum('positionen__einkauf_netto'), Decimal('0.00'),
            output_field=DecimalField(max_digits=14, decimal_places=2)))
        .exclude(betrag_netto=F('zugeordnet_summe'))
        .select_related('lieferant')
        # Mit Projekt für ``Eingangsrechnung.projekte``.
        .prefetch_related('positionen__projekt')
    )
    offen = [r for r in rechnungen if not r.ist_vollstaendig]
    offen.sort(key=lambda r: abs(r.rest), reverse=True)
    return offen


def offene_leistung_gesamt() -> Decimal:
    """Nettowert aller nicht abgerechneten Leistung über alle Projekte."""
    return sum(offene_leistung_je_projekt().values(), Decimal('0.00'))


def stunden_je_projekt(*, nur_laufende: bool = True) -> dict[int, Decimal]:
    """Geleistete Stunden je Vorhaben, ungerundet, als Nenner des effektiven
    Stundensatzes; gerundete Stunden senkten den Satz."""
    zeilen = Erfassungszeile.objects.filter(dauer_minuten__gt=0)
    if nur_laufende:
        zeilen = zeilen.filter(projekt__abgeschlossen=False)

    summen = (
        zeilen
        .values('projekt_id')
        .annotate(minuten=Sum('dauer_minuten'))
    )
    return {
        zeile['projekt_id']: rechnen.auf_cent(
            Decimal(zeile['minuten']) / 60)
        for zeile in summen
    }


@dataclass(frozen=True)
class Auslastung:
    """Aufteilung der Zeit einer Person in abgerechnet, abrechenbar offen und
    nicht abrechenbar; überschneidungsfrei, zusammen die erfasste Zeit."""

    benutzer_id: int
    name: str
    minuten_abgerechnet: int
    minuten_offen: int
    minuten_nicht_abrechenbar: int

    @property
    def minuten_gesamt(self) -> int:
        return (self.minuten_abgerechnet + self.minuten_offen
                + self.minuten_nicht_abrechenbar)

    @property
    def stunden_gesamt(self) -> Decimal:
        return rechnen.auf_stufe(Decimal(self.minuten_gesamt) / 60,
                                 rechnen.ZEHNTEL)

    @property
    def minuten_verkaufbar(self) -> int:
        """Abgerechnet plus abrechenbar offen."""
        return self.minuten_abgerechnet + self.minuten_offen

    @property
    def quote(self) -> int | None:
        """Abrechenbarer Anteil in Prozent ("produktive Quote", üblich etwa
        70 bis 85). None ohne erfasste Zeit."""
        if self.minuten_gesamt <= 0:
            return None
        return int(self.minuten_verkaufbar / self.minuten_gesamt * 100)


def _name_aus_werten(vorname: str, nachname: str, anmeldename: str) -> str:
    """``personenname`` für eine values()-Abfrage: gepflegter Name, sonst
    der Benutzername."""
    voll = f'{vorname or ""} {nachname or ""}'.strip()
    return voll or anmeldename or ''


def auslastung_je_person(*, seit: date | None = None) -> list[Auslastung]:
    """Auslastung je Person über alle Vorhaben; ``seit`` schränkt ein.
    Sortiert nach Zeit absteigend."""
    zeilen = Erfassungszeile.objects.filter(dauer_minuten__gt=0)
    if seit is not None:
        zeilen = zeilen.filter(datum__gte=seit)

    # Drei Kategorien in einer Abfrage, damit ihre Summe die Gesamtzeit
    # ergibt. "Abgerechnet" ist die Negation von NOCH_NICHT_ABGERECHNET; eine
    # Zeile auf einem Entwurf ist offen.
    summen = (
        zeilen
        .values('benutzer_id', 'benutzer__first_name', 'benutzer__last_name',
                'benutzer__username')
        .annotate(
            abgerechnet=Sum(Case(
                When(Q(abrechenbar=True) & ~NOCH_NICHT_ABGERECHNET,
                     then='dauer_minuten'),
                default=0, output_field=IntegerField())),
            offen=Sum(Case(
                When(Q(abrechenbar=True) & NOCH_NICHT_ABGERECHNET,
                     then='dauer_minuten'),
                default=0, output_field=IntegerField())),
            unverkaeuflich=Sum(Case(
                When(abrechenbar=False, then='dauer_minuten'),
                default=0, output_field=IntegerField())),
        )
    )

    ergebnis = [
        Auslastung(
            benutzer_id=zeile['benutzer_id'],
            name=_name_aus_werten(
                zeile['benutzer__first_name'], zeile['benutzer__last_name'],
                zeile['benutzer__username']),
            minuten_abgerechnet=zeile['abgerechnet'] or 0,
            minuten_offen=zeile['offen'] or 0,
            minuten_nicht_abrechenbar=zeile['unverkaeuflich'] or 0,
        )
        for zeile in summen
    ]
    return sorted(ergebnis, key=lambda a: -a.minuten_gesamt)


@dataclass(frozen=True)
class Altersklasse:
    """Altersklasse der nicht abgerechneten Leistung."""

    #: Untere Grenze in Tagen (einschließlich).
    ab_tagen: int
    #: Obere Grenze in Tagen, None für die älteste Klasse.
    bis_tagen: int | None
    betrag: Decimal

    @property
    def beschriftung(self) -> str:
        """Beschriftung wie "bis 30 Tage", "31 bis 60 Tage", "über 90 Tage";
        die offene Klasse nennt die Grenze."""
        if self.bis_tagen is None:
            return f'über {self.ab_tagen - 1} Tage'
        if self.ab_tagen == 0:
            return f'bis {self.bis_tagen} Tage'
        return f'{self.ab_tagen} bis {self.bis_tagen} Tage'


def offene_leistung_nach_alter(
    *, grenzen: tuple[int, ...] = (30, 60, 90), stichtag: date | None = None
) -> list[Altersklasse]:
    """Nicht abgerechnete eigene Leistung nach Altersklassen.

    Eine Berechnung je Klasse rundete viermal auf die Viertelstunde und
    ergäbe mehr als die Gesamtzahl. Deshalb wird der Betrag je Projekt (wie
    ``offene_leistung_je_projekt``) im Verhältnis der ungerundeten
    Zeilenwerte auf die Klassen verteilt; die Summe stimmt exakt. Nur eigene
    Leistung, weil Fremdleistung bereits bezahlt ist.
    """
    heute = stichtag or timezone.localdate()

    zeilen = list(
        Erfassungszeile.objects
        .filter(NOCH_NICHT_ABGERECHNET, abrechenbar=True)
        .select_related('leistung', 'projekt', 'abgerechnet_in__beleg')
    )
    if not zeilen:
        return _leere_klassen(grenzen)

    faecher = _faecher(grenzen)

    nach_projekt: dict[int, list] = {}
    for zeile in zeilen:
        nach_projekt.setdefault(zeile.projekt_id, []).append(zeile)

    verteilt = [Decimal('0.00') for _ in faecher]
    for gruppe in nach_projekt.values():
        gesamt = abrechnungsvorschau(gruppe, entwuerfe_zaehlen=True).netto
        if gesamt <= 0:
            continue

        roh = [Decimal('0') for _ in faecher]
        for zeile in gruppe:
            roh[_fachnummer(faecher, (heute - zeile.datum).days)] += (
                _rohwert(zeile))
        summe_roh = sum(roh)
        if summe_roh <= 0:
            continue

        # Der letzte Anteil bekommt den Rest, damit die Summe exakt aufgeht.
        rest = gesamt
        letztes = max(i for i, wert in enumerate(roh) if wert > 0)
        for i, wert in enumerate(roh):
            if wert <= 0 or i == letztes:
                continue
            anteil = rechnen.auf_cent(gesamt * wert / summe_roh)
            verteilt[i] += anteil
            rest -= anteil
        verteilt[letztes] += rest

    return [
        Altersklasse(ab_tagen=ab, bis_tagen=bis, betrag=betrag)
        for (ab, bis), betrag in zip(faecher, verteilt, strict=True)
    ]


def _faecher(grenzen: tuple[int, ...]) -> list[tuple[int, int | None]]:
    """Wandelt (30, 60, 90) in [(0,30), (31,60), (61,90), (91,None)]."""
    faecher: list[tuple[int, int | None]] = []
    untergrenze = 0
    for grenze in grenzen:
        faecher.append((untergrenze, grenze))
        untergrenze = grenze + 1
    faecher.append((untergrenze, None))
    return faecher


def _fachnummer(faecher, alter_in_tagen: int) -> int:
    """Index der Altersklasse für ein Alter. Ein Datum in der Zukunft
    (Tippfehler) kommt in die jüngste Klasse, damit kein Posten fehlt."""
    for nummer, (_ab, bis) in enumerate(faecher):
        if bis is None or alter_in_tagen <= bis:
            return nummer
    return len(faecher) - 1


def _rohwert(zeile) -> Decimal:
    """Ungerundeter Wert einer Zeile, nur als Verteilungsschlüssel."""
    preis = zeile.einzelpreis
    if zeile.leistungsart == Leistungsart.ZEIT:
        return Decimal(zeile.dauer_minuten) / 60 * preis
    return (zeile.menge or Decimal('0')) * preis


def _leere_klassen(grenzen: tuple[int, ...]) -> list[Altersklasse]:
    return [
        Altersklasse(ab_tagen=ab, bis_tagen=bis, betrag=Decimal('0.00'))
        for ab, bis in _faecher(grenzen)
    ]
