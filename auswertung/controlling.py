"""Controlling-Kennzahlen des Betriebs.

``ergebnisse.py`` rechnet je Vorhaben Erlös gegen Kosten. Dieses Modul
bildet daraus Kennzahlen zur Ursache und Entwicklung, etwa wie stark das
Ergebnis auf eine Änderung des effektiven Stundensatzes reagiert.

Jede Grundzahl kommt aus derselben Funktion, die sie auch sonst liefert;
hier entstehen nur Verhältnisse. Eine eigene Berechnung eines Betrags
könnte von der Rechnung abweichen.

Die vier Kennzahlen:

    Effektiver Stundensatz   Erlös und Kosten je geleisteter Stunde
    Deckungsbeitragsstaffel  DB I und DB II bis zum Ergebnis
    Auftragsreichweite       Bestand in Monaten abgerechneter Leistung
    Kundenabhängigkeit       Umsatzanteile der Auftraggeber
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.utils import timezone

from core import rechnen
from erfassung import services as erfassung_services
from faktura import services as faktura_services

from . import ergebnisse

NULL = Decimal('0.00')

#: Umsatzanteil, ab dem ein einzelner Kunde als Klumpenrisiko gilt.
#
# Dreißig Prozent ist eine gebräuchliche Faustzahl: Darüber ist der Ausfall
# eines Auftraggebers nicht durch Einsparungen aufzufangen. Als Konstante im
# Code, weil sie eine fachliche Festlegung ist.
KLUMPENGRENZE = 30

#: Länge des gleitenden Durchschnitts für die Reichweite, in Monaten.
#
# Drei Monate glätten einen einzelnen Großauftrag, ohne eine Entwicklung zu
# verdecken. Mit zwölf Monaten wäre ein Rückgang über ein Quartal an der
# Reichweite nicht zu sehen.
REICHWEITE_MONATE = 3


# ══════════════════════════════════════════════════════════════════════════
# Effektiver Stundensatz
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Stundenertrag:
    """Erlös und Kosten je geleisteter Stunde.

    Der Katalogpreis ist der Sollwert. Nicht abrechenbare Zeit, Kulanz,
    gerundete Viertelstunden und zu knappe Pauschalen senken den
    tatsächlichen Erlös je Stunde, jeweils einzeln wenig, zusammen deutlich.
    """

    #: Eigenleistung netto: Leistungswert ohne weiterberechnete
    #: Fremdleistung.
    eigenleistung: Decimal
    #: Geleistete Stunden, ungerundet.
    stunden: Decimal
    #: Lohnkosten dieser Stunden.
    personalkosten: Decimal

    @property
    def erloes_je_stunde(self) -> Decimal | None:
        """Erlös je geleisteter Stunde.

        ``None`` ohne erfasste Stunden, weil der Satz dann undefiniert ist;
        eine Null wäre falsch.
        """
        if self.stunden <= 0:
            return None
        return rechnen.auf_cent(self.eigenleistung / self.stunden)

    @property
    def kosten_je_stunde(self) -> Decimal | None:
        """Durchschnittlicher Kostensatz, gewichtet mit den geleisteten Stunden.

        Ein ungewichteter Mittelwert der hinterlegten Kostensätze zählte eine
        Aushilfe mit wenigen Stunden so stark wie eine Vollzeitkraft.
        """
        if self.stunden <= 0:
            return None
        return rechnen.auf_cent(self.personalkosten / self.stunden)

    @property
    def faktor(self) -> Decimal | None:
        """Erlös durch Kosten, also der Faktor auf den Lohn.

        In Ingenieurbüros liegt er üblicherweise zwischen 2,2 und 2,8.
        Darunter deckt die Stunde die Gemeinkosten nicht, darüber ist ein
        Sondergeschäft enthalten oder ein Kostensatz zu niedrig hinterlegt.

        Eine Gemeinkostenrechnung ersetzt er nicht, weil Miete und
        Versicherung hier nicht erfasst sind; als Verhältnis ist er über
        Monate vergleichbar.
        """
        if self.personalkosten <= 0 or self.stunden <= 0:
            return None
        return rechnen.auf_cent(self.eigenleistung / self.personalkosten)

    @property
    def deckung_je_stunde(self) -> Decimal | None:
        """Erlös je Stunde abzüglich Kosten je Stunde."""
        erloes, kosten = self.erloes_je_stunde, self.kosten_je_stunde
        if erloes is None or kosten is None:
            return None
        return erloes - kosten


# ══════════════════════════════════════════════════════════════════════════
# Deckungsbeitragsstaffel
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Deckungsbeitrag:
    """Deckungsbeitragsstaffel vom Leistungswert bis zum Ergebnis.

    Die Staffel zeigt die Ursache eines Ergebnisses: Ist DB I gut und DB II
    schwach, wird zu viel Zeit für das Verkaufte gebraucht; ist schon DB I
    schwach, liegt es am Einkauf oder am Aufschlag.

    DB I ist die Spanne auf weiterberechnete Fremdleistung, etwa
    Laboranalytik, zu 96 Euro eingekauft und zu 145 Euro berechnet.

    DB II ist DB I abzüglich eigener Lohnkosten, vor Miete, Geräten,
    Versicherung und Verwaltung, die hier nicht erfasst sind. Deshalb heißt
    der Wert Deckungsbeitrag und nicht Gewinn.
    """

    leistungswert: Decimal
    fremdkosten: Decimal
    personalkosten: Decimal

    @property
    def db1(self) -> Decimal:
        """Leistungswert minus Zukauf."""
        return self.leistungswert - self.fremdkosten

    @property
    def db2(self) -> Decimal:
        """DB I minus eigene Lohnkosten."""
        return self.db1 - self.personalkosten

    @property
    def db1_quote(self) -> int | None:
        return self._quote(self.db1)

    @property
    def db2_quote(self) -> int | None:
        return self._quote(self.db2)

    def _quote(self, betrag: Decimal) -> int | None:
        if self.leistungswert <= 0:
            return None
        return int(betrag / self.leistungswert * 100)

    @property
    def stufen(self) -> list[dict]:
        """Staffel als Wasserfalldiagramm: Wert, Abzug, Rest.

        Hier aufbereitet, weil ein Wasserfall je Stufe den Sockel des Balkens
        braucht und Djangos Template-Sprache nicht subtrahieren kann.
        """
        return [
            {'titel': 'Leistungswert', 'betrag': self.leistungswert,
             'sockel': NULL, 'art': 'summe'},
            {'titel': 'Zugekauft', 'betrag': -self.fremdkosten,
             'sockel': self.db1, 'art': 'abzug'},
            {'titel': 'Deckungsbeitrag I', 'betrag': self.db1,
             'sockel': NULL, 'art': 'zwischensumme'},
            {'titel': 'Eigene Arbeit', 'betrag': -self.personalkosten,
             'sockel': self.db2 if self.db2 > 0 else NULL, 'art': 'abzug'},
            {'titel': 'Deckungsbeitrag II', 'betrag': self.db2,
             'sockel': NULL, 'art': 'ergebnis'},
        ]


# ══════════════════════════════════════════════════════════════════════════
# Auftragsreichweite
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Reichweite:
    """Reichweite des Auftragsbestands in Monaten.

    Der Bestand geteilt durch die monatlich abgerechnete Leistung. Dieselben
    59.000 Euro reichen bei zwei Personen ein halbes Jahr, bei acht knapp
    einen Monat.
    """

    auftragsbestand: Decimal
    #: Durchschnittlich je Monat berechnete Leistung der letzten Monate.
    monatsleistung: Decimal
    monate_grundlage: int

    @property
    def monate(self) -> Decimal | None:
        """Bestand geteilt durch die Monatsleistung.

        ``None``, solange nichts abgerechnet wurde, weil der Nenner fehlt.
        """
        if self.monatsleistung <= 0:
            return None
        return rechnen.auf_stufe(self.auftragsbestand / self.monatsleistung,
                                 rechnen.ZEHNTEL)

    @property
    def ist_knapp(self) -> bool:
        """Reichweite unter einem Monat.

        Ab hier ist Akquise dringlicher als Abarbeitung, weil von der Abgabe
        eines Angebots bis zum Auftrag Wochen vergehen.
        """
        monate = self.monate
        return monate is not None and monate < 1


# ══════════════════════════════════════════════════════════════════════════
# Kundenabhängigkeit
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Kundenanteil:
    """Auftraggeber mit Umsatzanteil und kumuliertem Anteil."""

    umsatz: object
    anteil: int
    #: Kumulierter Anteil bis einschließlich dieses Kunden (ABC-Analyse).
    kumuliert: int

    @property
    def name(self) -> str:
        return self.umsatz.name

    @property
    def netto(self) -> Decimal:
        return self.umsatz.netto

    @property
    def ist_klumpen(self) -> bool:
        return self.anteil >= KLUMPENGRENZE


@dataclass(frozen=True)
class Kundenstruktur:
    """Verteilung des Umsatzes auf die Auftraggeber."""

    zeilen: list
    gesamt: Decimal

    @property
    def klumpen(self) -> list:
        return [z for z in self.zeilen if z.ist_klumpen]

    @property
    def groesster(self):
        return self.zeilen[0] if self.zeilen else None

    @property
    def anteil_top3(self) -> int:
        """Umsatzanteil der drei größten Kunden.

        Gebräuchliches Maß der Abhängigkeit: unter fünfzig Prozent breit
        aufgestellt, über achtzig abhängig von wenigen Auftraggebern.
        """
        if not self.zeilen:
            return 0
        return min(100, self.zeilen[min(2, len(self.zeilen) - 1)].kumuliert)

    @property
    def anzahl(self) -> int:
        return len(self.zeilen)


def kundenstruktur(*, seit: date | None = None) -> Kundenstruktur:
    """Umsatz nach Auftraggebern mit Anteilen und kumuliertem Anteil."""
    umsaetze = faktura_services.umsatz_je_kunde(seit=seit)
    gesamt = sum((u.netto for u in umsaetze), NULL)

    zeilen = []
    laufend = NULL
    for umsatz in umsaetze:
        laufend += umsatz.netto
        zeilen.append(Kundenanteil(
            umsatz=umsatz,
            anteil=int(umsatz.netto / gesamt * 100) if gesamt > 0 else 0,
            kumuliert=int(laufend / gesamt * 100) if gesamt > 0 else 0,
        ))
    return Kundenstruktur(zeilen=zeilen, gesamt=gesamt)


# ══════════════════════════════════════════════════════════════════════════
# Gesamtlage
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Lage:
    """Alle Werte der Controlling-Seite, in einem Durchlauf berechnet.

    Die aufwendigen Teile (Projektstände, offene Leistung, Kosten) brauchen
    mehrere Kennzahlen; als ein Objekt werden ihre Abfragen nur einmal
    ausgeführt.
    """

    uebersicht: object
    stundenertrag: Stundenertrag
    deckungsbeitrag: Deckungsbeitrag
    reichweite: Reichweite
    kunden: Kundenstruktur
    altersklassen: list
    auslastung: list
    auftragseingang: list
    umsatzverlauf: list

    @property
    def vollstaendig(self) -> bool:
        """Ob alle Stunden einen Kostensatz haben.

        Stunden ohne Kostensatz machen DB II und Faktor um deren Lohn zu
        hoch. Jede darauf beruhende Anzeige trägt dann einen Hinweis.
        """
        return self.uebersicht.vollstaendig

    @property
    def auftragseingang_summe(self) -> Decimal:
        return sum((m.netto for m in self.auftragseingang), NULL)

    @property
    def umsatz_summe(self) -> Decimal:
        return sum((m.netto for m in self.umsatzverlauf), NULL)

    @property
    def eingang_gegen_umsatz(self) -> int | None:
        """Auftragseingang in Prozent des Umsatzes im selben Zeitraum
        (Book-to-Bill).

        Über 100 wächst der Bestand, unter 100 schrumpft er. Für einige
        Monate ist beides üblich; aussagekräftig ist die Dauer.
        """
        if self.umsatz_summe <= 0:
            return None
        return int(self.auftragseingang_summe / self.umsatz_summe * 100)

    @property
    def offene_leistung_gesamt(self) -> Decimal:
        return sum((k.betrag for k in self.altersklassen), NULL)

    @property
    def alt_liegengeblieben(self) -> Decimal:
        """Nicht abgerechnete Leistung älter als die vorletzte Altersgrenze."""
        return sum((k.betrag for k in self.altersklassen
                    if k.bis_tagen is None), NULL)


def lage(*, monate: int = 12) -> Lage:
    """Alle Kennzahlen der Controlling-Seite.

    ``monate`` gilt für die beiden Zeitreihen (Auftragseingang und Umsatz)
    und damit auch für ihr Verhältnis.
    """
    uebersicht = ergebnisse.projektergebnisse()

    leistungswert = sum((z.leistungswert for z in uebersicht.zeilen), NULL)
    fremdkosten = sum((z.fremdkosten for z in uebersicht.zeilen), NULL)
    personalkosten = sum((z.personalkosten for z in uebersicht.zeilen), NULL)
    # Offene zugekaufte Leistung geht nicht in den Stundenertrag ein, weil
    # für weiterberechnete Analysen keine Stunden gebucht sind; Vorhaben mit
    # viel Analytik hätten sonst überhöhte Stundensätze. Bewertet zum
    # Einkaufspreis, wie im Leistungswert.
    fremdverkauf = sum((z.offene_fremdleistung for z in uebersicht.zeilen), NULL)

    stunden = sum(
        erfassung_services.stunden_je_projekt().values(), Decimal('0'))

    umsatzverlauf = faktura_services.fakturaverlauf(monate=monate)

    return Lage(
        uebersicht=uebersicht,
        stundenertrag=Stundenertrag(
            eigenleistung=leistungswert - fremdverkauf,
            stunden=stunden,
            personalkosten=personalkosten,
        ),
        deckungsbeitrag=Deckungsbeitrag(
            leistungswert=leistungswert,
            fremdkosten=fremdkosten,
            personalkosten=personalkosten,
        ),
        reichweite=reichweite(
            auftragsbestand=uebersicht.auftragsbestand,
            verlauf=umsatzverlauf),
        kunden=kundenstruktur(),
        altersklassen=erfassung_services.offene_leistung_nach_alter(),
        auslastung=erfassung_services.auslastung_je_person(
            seit=_vor_monaten(monate)),
        auftragseingang=faktura_services.auftragseingang_je_monat(
            monate=monate),
        umsatzverlauf=umsatzverlauf,
    )


def projektertrag(ergebnis) -> Stundenertrag:
    """Stundenertrag eines Vorhabens für die Projektakte.

    Aus denselben Funktionen wie die Gesamtzahl, damit beide Werte nach
    derselben Regel entstehen.
    """
    stunden = erfassung_services.stunden_je_projekt(
        nur_laufende=False).get(ergebnis.projekt.pk, Decimal('0'))
    return Stundenertrag(
        eigenleistung=ergebnis.leistungswert - ergebnis.offene_fremdleistung,
        stunden=stunden,
        personalkosten=ergebnis.personalkosten,
    )


def projektdeckungsbeitrag(ergebnis) -> Deckungsbeitrag:
    """Deckungsbeitragsstaffel eines Vorhabens."""
    return Deckungsbeitrag(
        leistungswert=ergebnis.leistungswert,
        fremdkosten=ergebnis.fremdkosten,
        personalkosten=ergebnis.personalkosten,
    )


def reichweite(*, auftragsbestand: Decimal, verlauf) -> Reichweite:
    """Reichweite aus Bestand und vorhandenem Umsatzverlauf.

    Eigene Funktion für die Startseite, die Bestand und Verlauf schon hat
    und dafür nicht ``lage()`` vollständig berechnen soll.
    """
    return Reichweite(
        auftragsbestand=auftragsbestand,
        monatsleistung=_monatsleistung(verlauf),
        monate_grundlage=REICHWEITE_MONATE,
    )


def _monatsleistung(verlauf) -> Decimal:
    """Durchschnittlich je Monat berechnete Leistung.

    Über die letzten abgeschlossenen Monate ohne den laufenden. Der laufende
    Monat ist am Fünften zu einem Sechstel gefüllt, senkte den Durchschnitt
    und ließe die Reichweite zu hoch erscheinen.
    """
    if len(verlauf) < 2:
        return NULL
    abgeschlossen = verlauf[:-1][-REICHWEITE_MONATE:]
    if not abgeschlossen:
        return NULL
    summe = sum((m.netto for m in abgeschlossen), NULL)
    return rechnen.auf_cent(summe / len(abgeschlossen))


def _vor_monaten(monate: int) -> date:
    heute = timezone.localdate()
    gesamt = heute.year * 12 + (heute.month - 1) - (monate - 1)
    return date(gesamt // 12, gesamt % 12 + 1, 1)
