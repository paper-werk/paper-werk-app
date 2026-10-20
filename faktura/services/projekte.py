"""Projekte: Auflösung aus Text, Auswertung einzeln und aller Projekte.

Entwürfe zählen in keiner Summe, weil eine Auswertung sich sonst
rückwirkend änderte. Die Mahnung zählt nicht als fakturiert, weil sie
Berechnetes erneut fordert.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Sum

from ..models import Beleg, Belegposition, BelegStatus, BelegTyp, Projekt, Rechnungsart
from .summen import POSITIONSNETTO, belegsummen, umsatzsummen


@dataclass(frozen=True)
class Projekttreffer:
    """Gefundenes Projekt mit Güte des Treffers."""

    projekt: Projekt
    #: Feld mit dem Treffer: nummer, bezeichnung oder kunde.
    fundstelle: str
    #: 'exakt' bei vollständiger Übereinstimmung der Nummer, sonst 'teilweise'.
    guete: str


@dataclass(frozen=True)
class Aufloesung:
    treffer: list[Projekttreffer]

    @property
    def eindeutig(self) -> bool:
        """Ob der Treffer eine Zuordnung ohne Rückfrage erlaubt."""
        return len(self.treffer) == 1


#: Mindestlänge einer Projektnummer für die Suche im Fließtext, weil
#: kurze Nummern wie "12" in jedem Datum vorkommen.
MINDESTLAENGE_IM_TEXT = 3


def _nummer_steckt_im_text(nummer: str, text: str) -> bool:
    """Ob die Projektnummer als eigenes Wort im Text vorkommt.

    An Wortgrenzen, damit "M-123" nicht in "M-1234" trifft; ``re.escape``,
    weil Projektnummern Zeichen wie den Punkt enthalten können.
    """
    if len(nummer) < MINDESTLAENGE_IM_TEXT:
        return False

    return re.search(rf'\b{re.escape(nummer)}\b', text, re.IGNORECASE) is not None


def projekt_aufloesen(text: str, *, nur_offene: bool = False) -> Aufloesung:
    """Sucht das Projekt zu einem Textfragment aus der Texterkennung
    ("BV Halle Nord", "Projekt 2026-042 Abschlag").

    Drei Stufen; ein Treffer in einer Stufe schließt die folgenden aus:

    1. Der Text *ist* eine Projektnummer.
    2. Der Text *enthält* eine Projektnummer (an Wortgrenzen, ab drei
       Zeichen), der häufigste Fall aus der Texterkennung.
    3. Teiltreffer in Nummer, Bezeichnung, Kundenname.

    Die Güte wird zurückgegeben, damit der Aufrufer einen eindeutigen von
    mehreren Treffern unterscheiden kann. Abgeschlossene Projekte werden
    durchsucht, weil Schlussrechnungen von Lieferanten spät eintreffen.
    """
    text = text.strip()
    if not text:
        return Aufloesung(treffer=[])

    projekte = Projekt.objects.select_related('kunde')
    if nur_offene:
        projekte = projekte.filter(abgeschlossen=False)

    # Stufe 1: Der Text ist die Nummer.
    genau = projekte.filter(nummer__iexact=text).first()
    if genau is not None:
        return Aufloesung(treffer=[
            Projekttreffer(projekt=genau, fundstelle='nummer', guete='exakt'),
        ])

    # Stufe 2: Der Text enthält eine Nummer. In Python, weil sich das nicht
    # als Abfrage ausdrücken lässt; bei einigen hundert Projekten
    # vertretbar.
    im_text = [
        Projekttreffer(projekt=projekt, fundstelle='nummer', guete='exakt')
        for projekt in projekte
        if _nummer_steckt_im_text(projekt.nummer, text)
    ]
    if im_text:
        return Aufloesung(treffer=im_text)

    # Stufe 3: Teiltreffer, nach Aussagekraft geordnet.
    treffer: list[Projekttreffer] = []
    gesehen: set[int] = set()

    for feld, fundstelle in (
        ('nummer__icontains', 'nummer'),
        ('bezeichnung__icontains', 'bezeichnung'),
        ('kunde__name__icontains', 'kunde'),
    ):
        for projekt in projekte.filter(**{feld: text}):
            if projekt.pk in gesehen:
                continue
            gesehen.add(projekt.pk)
            treffer.append(Projekttreffer(
                projekt=projekt, fundstelle=fundstelle, guete='teilweise',
            ))

    return Aufloesung(treffer=treffer)


@dataclass(frozen=True)
class Belegartsumme:
    anzahl: int
    netto: Decimal
    brutto: Decimal


@dataclass(frozen=True)
class Projektauswertung:
    belege: list[Beleg]
    je_belegart: dict[str, Belegartsumme]
    #: Summe der Steuerbelege, also des dem Kunden Berechneten.
    fakturiert_netto: Decimal
    fakturiert_brutto: Decimal
    #: Summe der Angebote.
    angeboten_netto: Decimal


def projektakte(projekt: Projekt, *,
                mit_entwuerfen: bool = False) -> Projektauswertung:
    """Alle Belege eines Projekts mit Summen je Belegart.

    "Fakturiert" sind die Steuerbelege; Stornos heben sich über ihre
    negativen Beträge auf. ``mit_entwuerfen`` nimmt Entwürfe in die Liste
    auf, nie in die Summen. Default ``False``, damit eine weitergegebene
    Liste nur festgeschriebene Belege enthält.
    """
    alle = list(
        projekt.belege
        .prefetch_related('positionen')
        .order_by('belegdatum', 'nummer')
    )
    belege = alle if mit_entwuerfen else [b for b in alle if not b.ist_entwurf]

    je_belegart: dict[str, Belegartsumme] = {}
    fakturiert_netto = Decimal('0.00')
    fakturiert_brutto = Decimal('0.00')
    angeboten_netto = Decimal('0.00')

    steuerbelege = BelegTyp.steuerbelege()

    for beleg in alle:
        if beleg.ist_entwurf:
            continue

        summen = belegsummen(beleg)

        bisher = je_belegart.get(beleg.typ)
        je_belegart[beleg.typ] = Belegartsumme(
            anzahl=(bisher.anzahl if bisher else 0) + 1,
            netto=(bisher.netto if bisher else Decimal('0.00')) + summen.netto,
            brutto=(bisher.brutto if bisher else Decimal('0.00')) + summen.brutto,
        )

        if beleg.typ in steuerbelege:
            # Ohne Restzeilen nicht bezahlter Abschläge, weil der Betrag im
            # Abschlag enthalten ist (R-174).
            umsatz = umsatzsummen(beleg)
            fakturiert_netto += umsatz.netto
            fakturiert_brutto += umsatz.brutto
        elif beleg.typ == BelegTyp.ANGEBOT:
            angeboten_netto += summen.netto

    return Projektauswertung(
        belege=belege,
        je_belegart=je_belegart,
        fakturiert_netto=fakturiert_netto,
        fakturiert_brutto=fakturiert_brutto,
        angeboten_netto=angeboten_netto,
    )


@dataclass(frozen=True)
class Projektstand:
    """Finanzieller Stand eines Projekts, netto, weil die Umsatzsteuer ein
    durchlaufender Posten ist."""

    projekt: Projekt
    #: Summe der Angebote.
    angeboten: Decimal
    #: Summe der Aufträge samt Nachträgen.
    beauftragt: Decimal
    #: Summe der Steuerbelege abzüglich Stornos, **mit** Abschlägen
    #: (gestellte Beträge, Liquidität).
    fakturiert: Decimal
    #: Dasselbe **ohne** Abschläge (abgerechnete Leistung,
    #: Nachkalkulation), weil ein Abschlag eine Anzahlung ist und die
    #: Schlussrechnung die Leistung erneut aufführt; sonst zählte die
    #: Leistung doppelt (dieselbe Regel wie ``abgerechnete_mengen``).
    abgerechnete_leistung: Decimal = Decimal('0.00')

    @property
    def offen(self) -> Decimal:
        """Auftragsbestand (beauftragt, noch nicht berechnet), nie negativ,
        weil ein negativer Wert in der Gesamtsumme andere Projekte
        verrechnete."""
        rest = self.beauftragt - self.fakturiert
        return rest if rest > 0 else Decimal('0.00')

    @property
    def fortschritt(self) -> int:
        """Berechneter Anteil des Auftrags in Prozent, 0 bis 100. Ohne Auftrag
        0; die Anzeige blendet den Balken dann aus."""
        if self.beauftragt <= 0:
            return 0
        anteil = self.fakturiert / self.beauftragt * 100
        return max(0, min(100, int(anteil)))


def projektstaende(*, nur_laufende: bool = True,
                   projekte=None) -> list[Projektstand]:
    """Angeboten, beauftragt und fakturiert für alle Projekte, in zwei
    Abfragen unabhängig von der Zahl der Projekte. ``projekte``
    (Primärschlüssel) schränkt ein.

    Sortiert nach offenem Auftragsbestand, absteigend.
    """
    auswahl = Projekt.objects.select_related('kunde')
    if nur_laufende:
        auswahl = auswahl.filter(abgeschlossen=False)
    if projekte is not None:
        auswahl = auswahl.filter(pk__in=projekte)
    projekte = {p.pk: p for p in auswahl}

    if not projekte:
        return []

    # Gruppiert auch nach Abzugszeile und Art des Vorgängers, weil die
    # abgerechnete Leistung beides braucht (siehe unten).
    summen = (
        Belegposition.objects
        .filter(beleg__projekt__in=projekte)
        .exclude(beleg__status=BelegStatus.ENTWURF)
        .values('beleg__projekt', 'beleg__typ', 'beleg__rechnungsart',
                'beleg__vorgaenger__rechnungsart', 'ist_abzug',
                'ist_abschlagsrest')
        .annotate(netto=Sum(POSITIONSNETTO))
    )

    steuerbelege = BelegTyp.steuerbelege()
    leer = {'angeboten': Decimal('0.00'),
            'beauftragt': Decimal('0.00'),
            'fakturiert': Decimal('0.00'),
            'abgerechnete_leistung': Decimal('0.00')}
    je_projekt: dict[int, dict[str, Decimal]] = {}

    for zeile in summen:
        werte = je_projekt.setdefault(zeile['beleg__projekt'], dict(leer))
        netto = zeile['netto'] or Decimal('0.00')
        typ = zeile['beleg__typ']

        if typ == BelegTyp.ANGEBOT:
            werte['angeboten'] += netto
        elif typ == BelegTyp.AUFTRAG:
            werte['beauftragt'] += netto
        elif typ in steuerbelege:
            # Die Restzeile eines nicht bezahlten Abschlags fordert einen
            # Betrag, den der Abschlag bereits enthält; einmal gezählt
            # (R-174).
            if not zeile['ist_abschlagsrest']:
                werte['fakturiert'] += netto
            # Ohne Abzugszeilen der (Teil-)Schlussrechnung, weil sie
            # Abschläge absetzen, die hier nicht zählen. Regression: Die
            # Leistung war um die Summe der Abschläge zu niedrig, die Marge
            # entsprechend.
            if not _ist_anzahlung(zeile) and not zeile['ist_abzug']:
                werte['abgerechnete_leistung'] += netto

    staende = [
        Projektstand(projekt=projekt, **je_projekt.get(pk, leer))
        for pk, projekt in projekte.items()
    ]

    # Bei Gleichstand nach Nummer, damit die Reihenfolge stabil ist.
    staende.sort(key=lambda s: (-s.offen, s.projekt.nummer))
    return staende


def _ist_anzahlung(zeile) -> bool:
    """``Beleg.ist_anzahlung`` für eine Summenzeile: der Abschlag sowie sein
    Storno und seine Korrektur, die selbst keine Rechnungsart haben;
    maßgeblich ist der Vorgänger. Regression: Das Storno eines Abschlags
    zählte negativ in die Leistung."""
    if zeile['beleg__rechnungsart'] == Rechnungsart.ABSCHLAG:
        return True
    return (zeile['beleg__typ'] in (BelegTyp.STORNO, BelegTyp.GUTSCHRIFT)
            and zeile['beleg__vorgaenger__rechnungsart']
            == Rechnungsart.ABSCHLAG)
