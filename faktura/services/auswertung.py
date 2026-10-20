"""Auswertungen über alle Belege: Umsatzverlauf, Auftragseingang, Umsatz
je Kunde, Mahnstand.

Summiert wird in der Datenbank über ``POSITIONSNETTO``, damit dieselbe
Regel gilt wie auf dem Beleg. Maßgeblich ist das Belegdatum. Entwürfe
zählen nie.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Count, DecimalField, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from ..models import Beleg, Belegposition, BelegStatus, BelegTyp, Kontakt
from .summen import POSITIONSNETTO, belegsummen


@dataclass(frozen=True)
class Monatssumme:
    jahr: int
    monat: int
    netto: Decimal

    @property
    def beschriftung(self) -> str:
        return f'{self.monat:02d}/{self.jahr}'


def fakturaverlauf(*, monate: int = 12) -> list[Monatssumme]:
    """Netto der Steuerbelege je Monat für die letzten ``monate``
    einschließlich des laufenden.

    Monate ohne Belege mit 0, weil eine Lücke im Diagramm als "keine
    Angabe" erschiene.
    """
    heute = timezone.localdate()

    # Über die Monatszahl gerechnet, weil Monate verschieden lang sind.
    gesamtmonate = heute.year * 12 + (heute.month - 1) - (monate - 1)
    beginn = date(gesamtmonate // 12, gesamtmonate % 12 + 1, 1)

    summen = (
        Belegposition.objects
        .filter(
            beleg__typ__in=BelegTyp.steuerbelege(),
            beleg__belegdatum__gte=beginn,
            beleg__belegdatum__lte=heute,
        )
        .exclude(beleg__status=BelegStatus.ENTWURF)
        # Der nicht bezahlte Abschlag steht schon im Abschlag (R-174).
        .exclude(ist_abschlagsrest=True)
        .annotate(monat=TruncMonth('beleg__belegdatum'))
        .values('monat')
        .annotate(netto=Sum(POSITIONSNETTO))
    )
    gefunden = {(z['monat'].year, z['monat'].month): z['netto'] or Decimal('0.00')
                for z in summen}

    verlauf = []
    for versatz in range(monate):
        laufend = gesamtmonate + versatz
        jahr, monat = laufend // 12, laufend % 12 + 1
        verlauf.append(Monatssumme(
            jahr=jahr, monat=monat,
            netto=gefunden.get((jahr, monat), Decimal('0.00')),
        ))
    return verlauf


def fakturiert_im_jahr(jahr: int | None = None) -> Decimal:
    """Nettosumme aller Steuerbelege eines Kalenderjahres."""
    jahr = jahr or timezone.localdate().year
    ergebnis = (
        Belegposition.objects
        .filter(
            beleg__typ__in=BelegTyp.steuerbelege(),
            beleg__belegdatum__year=jahr,
        )
        .exclude(beleg__status=BelegStatus.ENTWURF)
        # Der nicht bezahlte Abschlag steht schon im Abschlag (R-174).
        .exclude(ist_abschlagsrest=True)
        .aggregate(netto=Coalesce(
            Sum(POSITIONSNETTO),
            Decimal('0.00'),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ))
    )
    return ergebnis['netto']


@dataclass(frozen=True)
class Mahnstand:
    """Gemahnte Rechnungen und ihr Betrag."""

    anzahl: int
    brutto: Decimal


def gemahnte_rechnungen() -> Mahnstand:
    """Festgeschriebene Rechnungen mit mindestens einer Mahnung, brutto.

    Ergänzt ``offene_posten()`` um die bereits gemahnten Rechnungen.
    Gezählt wird der Rechnungsbetrag ohne Zahlungen und Nachlässe (R-182);
    den offenen Teil liefert ``offene_posten()``.
    """
    rechnungen = (
        Beleg.objects
        .filter(typ=BelegTyp.RECHNUNG, status=BelegStatus.FESTGESCHRIEBEN)
        .filter(nachfolger__typ=BelegTyp.MAHNUNG)
        .distinct()
        .prefetch_related('positionen')
    )
    # Über belegsummen(), weil Brutto die Steuer je Satz braucht; die Zahl
    # gemahnter Rechnungen ist klein.
    betraege = [belegsummen(r).brutto for r in rechnungen]
    return Mahnstand(
        anzahl=len(betraege),
        brutto=sum(betraege, Decimal('0.00')),
    )


def auftragseingang_je_monat(*, monate: int = 12) -> list[Monatssumme]:
    """Netto der neuen Aufträge je Monat, Nachträge eingeschlossen.

    Der Umsatz zeigt Abgerechnetes, der Auftragseingang künftige Arbeit.
    Dieselbe Zeitzuordnung wie ``fakturaverlauf``, damit beide Reihen
    vergleichbar sind.
    """
    heute = timezone.localdate()
    gesamtmonate = heute.year * 12 + (heute.month - 1) - (monate - 1)
    beginn = date(gesamtmonate // 12, gesamtmonate % 12 + 1, 1)

    summen = (
        Belegposition.objects
        .filter(
            beleg__typ=BelegTyp.AUFTRAG,
            beleg__belegdatum__gte=beginn,
            beleg__belegdatum__lte=heute,
        )
        .exclude(beleg__status=BelegStatus.ENTWURF)
        .annotate(monat=TruncMonth('beleg__belegdatum'))
        .values('monat')
        .annotate(netto=Sum(POSITIONSNETTO))
    )
    gefunden = {(z['monat'].year, z['monat'].month): z['netto'] or Decimal('0.00')
                for z in summen}

    verlauf = []
    for versatz in range(monate):
        laufend = gesamtmonate + versatz
        jahr, monat = laufend // 12, laufend % 12 + 1
        verlauf.append(Monatssumme(
            jahr=jahr, monat=monat,
            netto=gefunden.get((jahr, monat), Decimal('0.00')),
        ))
    return verlauf


@dataclass(frozen=True)
class Kundenumsatz:
    """Umsatz eines Kunden in einem Zeitraum."""

    kunde: object
    netto: Decimal
    #: Anzahl der Steuerbelege.
    belege: int

    @property
    def name(self) -> str:
        return str(self.kunde) if self.kunde else 'Ohne Kunden'


def umsatz_je_kunde(*, seit: date | None = None,
                    bis: date | None = None) -> list[Kundenumsatz]:
    """Umsatz nach Auftraggebern, absteigend; zeigt die Abhängigkeit von
    einzelnen Kunden.

    Der Kunde kommt vom Beleg oder seinem Projekt; Belege mit freier
    Anschrift fasst die Zeile "Ohne Kunden" zusammen. Ohne Zeitraum das
    laufende Kalenderjahr.
    """
    heute = timezone.localdate()
    von = seit if seit is not None else date(heute.year, 1, 1)
    nach = bis if bis is not None else heute

    positionen = (
        Belegposition.objects
        .filter(
            beleg__typ__in=BelegTyp.steuerbelege(),
            beleg__belegdatum__gte=von,
            beleg__belegdatum__lte=nach,
        )
        .exclude(beleg__status=BelegStatus.ENTWURF)
        # Der nicht bezahlte Abschlag steht schon im Abschlag (R-174).
        .exclude(ist_abschlagsrest=True)
    )

    # Coalesce in SQL, damit die Gruppierung eine Abfrage bleibt.
    summen = (
        positionen
        .annotate(kunde_id=Coalesce('beleg__kunde_id',
                                    'beleg__projekt__kunde_id'))
        .values('kunde_id')
        .annotate(netto=Sum(POSITIONSNETTO),
                  belege=Count('beleg_id', distinct=True))
    )

    kunden = {k.pk: k for k in Kontakt.objects.filter(
        pk__in=[z['kunde_id'] for z in summen if z['kunde_id']])}

    zeilen = [
        Kundenumsatz(
            kunde=kunden.get(z['kunde_id']),
            netto=z['netto'] or Decimal('0.00'),
            belege=z['belege'],
        )
        for z in summen
    ]
    return sorted(zeilen, key=lambda z: (-z.netto, z.name))
