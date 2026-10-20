"""Berechnung von Positionsnetto, Steuer je Satz und Belegsummen.

Die Regel ist zweimal implementiert, in Python (``positionssumme``,
``belegsummen``) und in SQL (``POSITIONSNETTO``, ``summe_ueber``), und an
keiner weiteren Stelle. ``test_rechenabgleich.py`` prüft, dass beide
übereinstimmen.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Case, DecimalField, F, Sum, Value, When
from django.db.models.functions import Round

from core import rechnen

from ..models import Beleg, Belegposition, BelegTyp


@dataclass(frozen=True)
class Steueranteil:
    satz: Decimal
    netto: Decimal
    steuer: Decimal

    @property
    def brutto(self) -> Decimal:
        return self.netto + self.steuer


@dataclass(frozen=True)
class Belegsummen:
    netto: Decimal = Decimal('0.00')
    steuer: Decimal = Decimal('0.00')
    brutto: Decimal = Decimal('0.00')
    # Je Steuersatz getrennt, wie der Steuerausweis auf der Rechnung es
    # verlangt.
    anteile: list[Steueranteil] = field(default_factory=list)


def positionssumme(*, menge: Decimal, einzelpreis: Decimal) -> Decimal:
    """Nettobetrag einer Position, kaufmännisch auf Cent gerundet.

    Rundungsregel: je Position runden, dann summieren. Beide Verfahren sind
    zulässig und liefern verschiedene Ergebnisse; festgelegt ist dieses.
    """
    return rechnen.auf_cent(menge * einzelpreis)


def belegsummen(beleg: Beleg) -> Belegsummen:
    """Summen des Belegs (netto, Steuer je Satz, brutto) einschließlich
    abgesetzter Abschläge, also der Zahlbetrag."""
    return _summen(beleg.positionen.all())


def leistungssummen(beleg: Beleg) -> Belegsummen:
    """Wie ``belegsummen`` ohne abgesetzte Abschläge: die volle Leistung
    einer Schluss- oder Teilschlussrechnung. Die E-Rechnung enthält sie als
    Rechnungssumme und die Abschläge als BT-113. Ohne Abzugszeilen gleich
    ``belegsummen``."""
    return _summen([p for p in beleg.positionen.all() if not p.ist_abzug])


def umsatzsummen(beleg: Beleg) -> Belegsummen:
    """Wie ``belegsummen`` ohne Restzeilen nicht bezahlter Abschläge
    (R-174): der Beitrag des Belegs zum Umsatz. Ohne diesen Abzug zählte
    der im Abschlag enthaltene Rest doppelt. Ohne Restzeilen gleich
    ``belegsummen``."""
    return _summen([p for p in beleg.positionen.all()
                    if not p.ist_abschlagsrest])


def _summen(positionen) -> Belegsummen:
    netto_je_satz: dict[Decimal, Decimal] = {}

    for position in positionen:
        # Optionale Positionen zählen nicht zur Summe (R-178); geregelt hier
        # und in POSITIONSNETTO, an keiner weiteren Stelle.
        if position.optional:
            continue
        satz = position.steuersatz_dezimal
        betrag = positionssumme(menge=position.menge, einzelpreis=position.einzelpreis)
        netto_je_satz[satz] = netto_je_satz.get(satz, Decimal('0.00')) + betrag

    anteile = []
    for satz in sorted(netto_je_satz, reverse=True):
        netto = netto_je_satz[satz]
        # Steuer auf die Nettosumme je Satz, damit sich keine
        # Rundungsdifferenzen je Position summieren.
        steuer = rechnen.auf_cent(netto * satz / Decimal('100'))
        anteile.append(Steueranteil(satz=satz, netto=netto, steuer=steuer))

    netto_gesamt = sum((a.netto for a in anteile), Decimal('0.00'))
    steuer_gesamt = sum((a.steuer for a in anteile), Decimal('0.00'))

    return Belegsummen(
        netto=netto_gesamt,
        steuer=steuer_gesamt,
        brutto=netto_gesamt + steuer_gesamt,
        anteile=anteile,
    )


#: ``positionssumme`` als SQL-Ausdruck: ``sum(round(menge * einzelpreis, 2))``,
#: nicht ``round(sum(...))``. PostgreSQL rundet ``round(numeric, 2)`` wie
#: ``core.rechnen.auf_cent`` von der Null weg. ``Sum(F('menge') *
#: F('einzelpreis'))`` weicht bei dreistelligen Mengen um Cent von der
#: Rechnung ab.
#:
#: ``output_field`` ist nötig, weil Django die Genauigkeit von
#: decimal(10,3) mal decimal(12,2) nicht ableitet.
#:
#: Eine optionale Position zählt 0, wie in ``_summen`` (R-178).
_BETRAG = DecimalField(max_digits=14, decimal_places=2)
POSITIONSNETTO = Case(
    When(optional=True, then=Value(Decimal('0.00'), output_field=_BETRAG)),
    default=Round(F('menge') * F('einzelpreis'), 2, output_field=_BETRAG),
    output_field=_BETRAG,
)


@dataclass(frozen=True)
class Belegmengensumme:
    """Netto, Steuer und Brutto über eine Menge von Belegen."""

    anzahl: int
    #: Belege ohne Wert (Lieferscheine).
    ohne_wert: int
    netto: Decimal
    steuer: Decimal

    @property
    def brutto(self) -> Decimal:
        return self.netto + self.steuer


def bruttosummen(belege) -> dict[int, Decimal]:
    """Brutto je Beleg einer Menge, ohne die Belege zu laden.

    Dieselbe Berechnung wie ``belegsummen``: Netto je (Beleg, Steuersatz)
    als ``POSITIONSNETTO`` gruppiert, die Steuer je Gruppe auf den Cent.
    Belege ohne Positionen fehlen im Ergebnis; ihr Brutto ist 0.

    Für Abfragen über viele Belege ("welche sind offen?"), weil bei zehn
    Jahren Daten allein das Instanziieren der Objekte über eine Sekunde
    dauert (Lasttest).
    """
    gruppen = (
        Belegposition.objects
        .filter(beleg__in=belege)
        .values_list('beleg_id', 'steuersatz')
        .annotate(netto=Sum(POSITIONSNETTO))
    )
    brutto: dict[int, Decimal] = {}
    for beleg_id, steuersatz, netto in gruppen:
        netto = netto or Decimal('0.00')
        steuer = rechnen.auf_cent(netto * Decimal(steuersatz) / Decimal('100'))
        brutto[beleg_id] = brutto.get(beleg_id, Decimal('0.00')) + netto + steuer
    return brutto


def summe_ueber(belege, *, als_umsatz: bool = False) -> Belegmengensumme:
    """Summe einer Belegmenge in einer Abfrage, für die Summenzeile unter
    einer gefilterten Belegliste.

    Gruppiert nach (Beleg, Steuersatz) und je Gruppe gerundet wie
    ``belegsummen``, damit die Summe auf den Cent zur Liste passt.
    Lieferscheine zählen getrennt, weil sie keinen Wert haben.
    ``als_umsatz`` lässt die Restzeilen nicht bezahlter Abschläge aus, wie
    ``umsatzsummen`` (R-174).
    """
    wertbelege = belege.filter(typ__in=BelegTyp.wertbelege())

    positionen = Belegposition.objects.filter(beleg__in=wertbelege)
    if als_umsatz:
        positionen = positionen.filter(ist_abschlagsrest=False)
    gruppen = (
        positionen
        .values('beleg_id', 'steuersatz')
        .annotate(netto=Sum(POSITIONSNETTO))
    )

    netto_gesamt = Decimal('0.00')
    steuer_gesamt = Decimal('0.00')
    for gruppe in gruppen:
        netto = gruppe['netto'] or Decimal('0.00')
        satz = Decimal(gruppe['steuersatz'])
        netto_gesamt += netto
        steuer_gesamt += rechnen.auf_cent(netto * satz / Decimal('100'))

    gesamt = belege.count()
    mit_wert = wertbelege.count()
    return Belegmengensumme(
        anzahl=mit_wert,
        ohne_wert=gesamt - mit_wert,
        netto=netto_gesamt,
        steuer=steuer_gesamt,
    )
