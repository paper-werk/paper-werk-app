"""Projektergebnis: Erlös gegen Kosten je Vorhaben.

Erlöse aus ``faktura``, Kosten aus ``erfassung``. Anders als die
Seiten-Module dieser App rechnet dieses Modul und liefert Zahlen.
"""

from dataclasses import dataclass
from decimal import Decimal

from erfassung import services as erfassung_services
from faktura import services as faktura_services

NULL = Decimal('0.00')


@dataclass(frozen=True)
class Projektergebnis:
    """Erlös und Kosten eines Vorhabens.

    Erlös ist der Leistungswert: Berechnetes plus erbrachte, noch nicht
    berechnete Leistung. Ein Projekt ohne Rechnung erschiene sonst als
    Verlust.

    Stunden von Personen ohne Kostensatz sind unbewertet
    (``Ergebnisuebersicht.ohne_kostensatz``); das Ergebnis ist dann zu hoch.
    """

    #: Belegstand (faktura.services.Projektstand), unverändert übernommen,
    #: damit seine Regeln nur dort stehen.
    stand: object
    #: Erfasste eigene Leistung ohne Rechnung, zum Verkaufswert nach der
    #: Rechenregel der Abrechnung.
    offene_leistung: Decimal
    #: Zugekaufte Leistung ohne Rechnung, zum Einkaufspreis, weil der
    #: Verkaufspreis erst an der Rechnung festgelegt wird.
    offene_fremdleistung: Decimal
    #: Eigene Stunden mal internem Kostensatz, auf Basis der ungerundeten
    #: Zeit.
    personalkosten: Decimal
    #: Eingangsrechnungen Dritter für das Vorhaben zum Einkaufspreis,
    #: einschließlich nicht weiterberechneter Anteile.
    fremdkosten: Decimal

    @property
    def projekt(self):
        return self.stand.projekt

    @property
    def beauftragt(self) -> Decimal:
        return self.stand.beauftragt

    @property
    def fakturiert(self) -> Decimal:
        return self.stand.fakturiert

    @property
    def offen(self) -> Decimal:
        """Auftragsbestand: beauftragt, noch nicht berechnet."""
        return self.stand.offen

    @property
    def fortschritt(self) -> int:
        return self.stand.fortschritt

    @property
    def nicht_abgerechnet(self) -> Decimal:
        """Nicht abgerechnete eigene und fremde Leistung, als eine Summe."""
        return self.offene_leistung + self.offene_fremdleistung

    @property
    def abgerechnete_leistung(self) -> Decimal:
        """Berechnete Leistung ohne Abschlagsrechnungen."""
        return self.stand.abgerechnete_leistung

    @property
    def leistungswert(self) -> Decimal:
        """Leistungswert: erbrachte Leistung, berechnet oder nicht.

        Ohne Abschlagsrechnungen, im Unterschied zu ``fakturiert``. Ein
        Abschlag berechnet einen Betrag, die Stunden dahinter bleiben offen
        (``NOCH_NICHT_ABGERECHNET``); mitgezählt stünde dieselbe Leistung
        doppelt im Leistungswert. Dieselbe Regel gilt für das
        Mengenkontingent in ``faktura.services``.
        """
        return self.abgerechnete_leistung + self.nicht_abgerechnet

    @property
    def kosten(self) -> Decimal:
        return self.personalkosten + self.fremdkosten

    @property
    def ergebnis(self) -> Decimal:
        return self.leistungswert - self.kosten

    @property
    def marge(self) -> int | None:
        """Das Ergebnis in Prozent des Leistungswerts, gerundet.

        ``None`` ohne Leistungswert, weil die Marge dann undefiniert ist.
        """
        if self.leistungswert <= 0:
            return None
        return int(self.ergebnis / self.leistungswert * 100)

    @property
    def ueberschreitung(self) -> Decimal:
        """Leistung über den beauftragten Wert hinaus.

        Der Leistungswert bewertet jede Stunde zum Katalogpreis, unabhängig
        davon, ob sie bezahlt wird. Ob die Überschreitung bezahlt wird, hängt
        von der Vertragsart ab (Stunden, Pauschale, Nachtrag), die nicht
        erfasst ist; deshalb wird sie angezeigt und nicht verrechnet.

        Null ohne Auftrag, damit kein Hinweis auf Überschreitung erscheint.
        """
        if self.beauftragt <= 0:
            return NULL
        darueber = self.leistungswert - self.beauftragt
        return darueber if darueber > 0 else NULL

    @property
    def ausschoepfung(self) -> int | None:
        """Geleisteter Anteil des Auftragswerts in Prozent, unbegrenzt.

        Werte über 100 zeigen eine Überschreitung; für Balkenbreiten muss
        der Aufrufer begrenzen. ``None`` ohne Auftrag.
        """
        if self.beauftragt <= 0:
            return None
        return int(self.leistungswert / self.beauftragt * 100)

    @property
    def ist_ueberzogen(self) -> bool:
        return self.ueberschreitung > 0

    @property
    def traegt(self) -> bool:
        return self.ergebnis >= 0


@dataclass(frozen=True)
class Ergebnisuebersicht:
    """Ergebnisse aller Vorhaben und Angaben zu unbewerteten Stunden."""

    zeilen: list
    #: Personen ohne Kostensatz. Ist die Liste nicht leer, sind die
    #: Ergebnisse zu hoch.
    ohne_kostensatz: set
    #: Unbewertete Minuten dieser Personen.
    minuten_ohne_satz: int

    @property
    def vollstaendig(self) -> bool:
        return not self.ohne_kostensatz

    @property
    def ergebnis(self) -> Decimal:
        return sum((z.ergebnis for z in self.zeilen), NULL)

    @property
    def kosten(self) -> Decimal:
        return sum((z.kosten for z in self.zeilen), NULL)

    @property
    def nicht_abgerechnet(self) -> Decimal:
        return sum((z.nicht_abgerechnet for z in self.zeilen), NULL)

    @property
    def auftragsbestand(self) -> Decimal:
        return sum((z.offen for z in self.zeilen), NULL)

    @property
    def ueberschreitung(self) -> Decimal:
        """Summe der Überschreitungen aller Vorhaben."""
        return sum((z.ueberschreitung for z in self.zeilen), NULL)

    @property
    def ueberzogene(self) -> list:
        return [z for z in self.zeilen if z.ist_ueberzogen]

    def je_projekt(self) -> dict[int, Projektergebnis]:
        return {z.projekt.pk: z for z in self.zeilen}

    def nach_ergebnis(self) -> list:
        """Dieselben Zeilen, nach Ergebnis aufsteigend sortiert.

        Die Startseite sortiert nach offenem Auftragsbestand.
        """
        return sorted(self.zeilen, key=lambda z: (z.ergebnis, z.projekt.nummer))


def projektergebnisse(*, nur_laufende: bool = True,
                      projekte=None) -> Ergebnisuebersicht:
    """Erlös und Kosten aller Vorhaben oder der in ``projekte`` genannten
    Primärschlüssel.

    Fünf Abfragen unabhängig von der Zahl der Projekte. Jede Zahl kommt aus
    der Funktion, die sie auch sonst liefert, der offene Leistungswert aus
    derselben Abrechnungsvorschau wie die Rechnung. Sortiert nach offenem
    Auftragsbestand (``projektstaende``).
    """
    staende = faktura_services.projektstaende(
        nur_laufende=nur_laufende, projekte=projekte)
    offene_leistung = erfassung_services.offene_leistung_je_projekt(
        projekte=projekte)
    offene_fremd = erfassung_services.offene_fremdleistung_je_projekt(
        projekte=projekte)
    fremdkosten = erfassung_services.fremdkosten_je_projekt(
        nur_laufende=nur_laufende, projekte=projekte)
    personal = erfassung_services.personalkosten_je_projekt(
        nur_laufende=nur_laufende, projekte=projekte)

    zeilen = [
        Projektergebnis(
            stand=stand,
            offene_leistung=offene_leistung.get(stand.projekt.pk, NULL),
            offene_fremdleistung=offene_fremd.get(stand.projekt.pk, NULL),
            personalkosten=personal.je_projekt.get(stand.projekt.pk, NULL),
            fremdkosten=fremdkosten.get(stand.projekt.pk, NULL),
        )
        for stand in staende
    ]

    return Ergebnisuebersicht(
        zeilen=zeilen,
        ohne_kostensatz=personal.ohne_satz,
        minuten_ohne_satz=personal.minuten_ohne_satz,
    )


def projektergebnis(projekt) -> Projektergebnis | None:
    """Ergebnis eines Vorhabens für die Projektakte.

    Über ``projektergebnisse`` mit nur diesem Projekt, damit beide Werte
    nach derselben Regel entstehen.
    """
    uebersicht = projektergebnisse(nur_laufende=False, projekte=[projekt.pk])
    return uebersicht.je_projekt().get(projekt.pk)


# ── Auftragsstand ─────────────────────────────────────────────────────────
#
# Bezugsgröße ist der Auftrag: Beauftragtes gegen Berechnetes je Position.
# Gerechnet wird hier, die Auftragsakte beschriftet.


@dataclass(frozen=True)
class Auftragsposten:
    """Beauftragte Position mit der darauf abgerechneten Menge."""

    position: object
    #: Über alle Rechnungen auf diese Position abgerechnete Menge.
    abgerechnet: Decimal

    @property
    def menge(self) -> Decimal:
        return self.position.menge

    @property
    def offen(self) -> Decimal:
        """Noch abzurechnende Menge, mindestens null.

        Wie ``Belegposition.offene_menge``: Eine Überschreitung ergibt null.
        """
        rest = self.menge - self.abgerechnet
        return rest if rest > 0 else NULL

    @property
    def fortschritt(self) -> int:
        """Berechneter Anteil der Position in Prozent, unbegrenzt.

        Werte über 100 werden hervorgehoben (R-077). Null ohne beauftragte
        Menge.
        """
        if not self.menge:
            return 0
        return int(self.abgerechnet / self.menge * 100)

    @property
    def optional(self) -> bool:
        return self.position.optional

    @property
    def ist_ueberzogen(self) -> bool:
        """Ob mehr abgerechnet als beauftragt ist.

        Optionale Positionen sind nie überzogen, weil dort nur der Preis
        beauftragt ist.
        """
        return not self.optional and self.abgerechnet > self.menge

    @property
    def netto(self) -> Decimal:
        """Nettowert der Position, gerundet wie in der Rechnung."""
        return faktura_services.positionssumme(
            menge=self.position.menge, einzelpreis=self.position.einzelpreis)


@dataclass(frozen=True)
class Auftragsstand:
    """Abrechnungsstand eines Auftrags: vier Beträge und ihr Verhältnis."""

    auftrag: object
    posten: list
    #: Auftragswert netto aus ``belegsummen``.
    beauftragt: Decimal
    #: Auf diesen Auftrag festgeschrieben berechneter Betrag, ohne
    #: Abschlagsrechnungen, weil sie steuerlich Anzahlungen sind und die
    #: Schlussrechnung dieselbe Leistung erneut aufführt.
    berechnet: Decimal
    #: Auf den Auftrag kontierte Leistung ohne Rechnung, zum Verkaufswert
    #: nach der Rechenregel der Abrechnung.
    nicht_berechnet: Decimal

    @property
    def offen(self) -> Decimal:
        """Noch abzurechnender Betrag des Auftrags."""
        return self.beauftragt - self.berechnet

    @property
    def fortschritt(self) -> int | None:
        """Berechnet im Verhältnis zu beauftragt, in Prozent, unbegrenzt.

        ``None`` bei einem Auftrag ohne Wert.
        """
        if not self.beauftragt:
            return None
        return int(self.berechnet / self.beauftragt * 100)

    @property
    def ist_ueberzogen(self) -> bool:
        return self.berechnet > self.beauftragt > 0

    @property
    def ueberzogene_posten(self) -> list:
        return [p for p in self.posten if p.ist_ueberzogen]


def auftragsstand(auftrag, positionen=None) -> Auftragsstand:
    """Auftragsstand aus den Funktionen der Services.

    ``positionen`` ist die bereits geladene Liste der Aktenseite. Drei
    Abfragen, unabhängig von der Zahl der Positionen.
    """
    from erfassung.models import Erfassungszeile

    positionen = (list(auftrag.positionen.order_by('sortierung', 'pk'))
                  if positionen is None else list(positionen))
    abgerechnet = faktura_services.abgerechnete_mengen(
        [p.pk for p in positionen])

    # NOCH_NICHT_ABGERECHNET und ``entwuerfe_zaehlen`` gehören zusammen: Der
    # Filter schließt Zeilen auf Rechnungsentwürfen ein, also muss die
    # Vorschau sie zählen.
    offene_zeilen = list(
        Erfassungszeile.objects
        .filter(erfassung_services.NOCH_NICHT_ABGERECHNET,
                auftragsposition__beleg=auftrag, abrechenbar=True)
        .select_related('auftragsposition', 'benutzer',
                        'abgerechnet_in__beleg')
    )

    return Auftragsstand(
        auftrag=auftrag,
        posten=[Auftragsposten(position=p,
                               abgerechnet=abgerechnet.get(p.pk, NULL))
                for p in positionen],
        beauftragt=faktura_services.belegsummen(auftrag).netto,
        berechnet=faktura_services.berechneter_wert(auftrag),
        nicht_berechnet=(
            erfassung_services.abrechnungsvorschau(
                offene_zeilen, entwuerfe_zaehlen=True).netto
            if offene_zeilen else NULL),
    )
