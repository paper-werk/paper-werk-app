"""Offene Posten und Zahlungseingänge.

Eine Zahlung ändert den Beleg nicht; "bezahlt" wird aus den Zuordnungen
berechnet. Offene Beträge sind brutto, weil der Kunde die Umsatzsteuer
mitüberweist.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Prefetch, Sum
from django.utils import timezone

from ..models import (
    Beleg,
    BelegStatus,
    BelegTyp,
    Rechnungsart,
    Zahlung,
    Zahlungsart,
    Zahlungszuordnung,
)
from .abschlaege import ganz_abgerechnete, uebernommener_rest
from .anlegen import anschriftgeber
from .fehler import FalscherStatus, UngueltigerBetrag
from .summen import belegsummen, bruttosummen


def nachlaesse(rechnungen) -> dict[int, Decimal]:
    """Brutto der festgeschriebenen Rechnungskorrekturen je Rechnung, als
    positiver Betrag (R-182). ``rechnungen``: Queryset oder Primärschlüssel.

    Die Korrektur verweist über ``vorgaenger`` auf ihre Rechnung und
    entsteht nur über ``rechnungskorrektur_erstellen``. Entwürfe zählen
    nicht, weil der Kunde sie nicht erhalten hat.
    """
    korrekturen = Beleg.objects.filter(
        typ=BelegTyp.GUTSCHRIFT, status=BelegStatus.FESTGESCHRIEBEN,
        vorgaenger__in=rechnungen)
    rechnung_zu = dict(korrekturen.values_list('pk', 'vorgaenger_id'))
    ergebnis: dict[int, Decimal] = {}
    for pk, brutto in bruttosummen(korrekturen).items():
        rechnung = rechnung_zu[pk]
        ergebnis[rechnung] = ergebnis.get(rechnung, Decimal('0.00')) - brutto
    return ergebnis


#: ``to_attr`` des Prefetch der festgeschriebenen Korrekturen je Rechnung
#: (``nachlaesse_vorladen``).
NACHLAESSE_VORGELADEN = '_pw_nachlaesse'


def nachlaesse_vorladen():
    """``Prefetch`` für Listen: festgeschriebene Korrekturen mit Positionen
    je Rechnung. Ohne ihn stellte ``nachlass`` eine Abfrage je Zeile
    (``test_grosse_bestaende``)."""
    return Prefetch(
        'nachfolger',
        queryset=Beleg.objects.filter(
            typ=BelegTyp.GUTSCHRIFT, status=BelegStatus.FESTGESCHRIEBEN,
        ).prefetch_related('positionen'),
        to_attr=NACHLAESSE_VORGELADEN)


def nachlass(rechnung: Beleg) -> Decimal:
    """``nachlaesse`` für eine Rechnung; verwendet ``nachlaesse_vorladen``,
    wenn gesetzt."""
    vorgeladen = getattr(rechnung, NACHLAESSE_VORGELADEN, None)
    if vorgeladen is not None:
        return -sum((belegsummen(k).brutto for k in vorgeladen),
                    Decimal('0.00'))
    return nachlaesse([rechnung.pk]).get(rechnung.pk, Decimal('0.00'))


def offener_betrag(beleg: Beleg, ausser: int | None = None) -> Decimal:
    """Offener Betrag der Rechnung, brutto, nie negativ.

    0 für alles außer festgeschriebenen Rechnungen, weil gemischte Listen
    danach fragen. ``ausser`` schließt eine Zuordnung aus
    (``Zahlungszuordnung.clean``, damit eine Zeile sich nicht selbst
    zählt).

    Ein Abschlag, den eine festgeschriebene Schlussrechnung vollständig
    absetzt, hat nichts mehr offen, weil sie den Rest fordert (R-174).
    Setzt bisher nur eine Teilschlussrechnung einen Teil ab, mindert ihre
    Restzeile den offenen Betrag.

    Festgeschriebene Rechnungskorrekturen mindern die Forderung (R-182).
    """
    if beleg.typ != BelegTyp.RECHNUNG:
        return Decimal('0.00')
    if beleg.status != BelegStatus.FESTGESCHRIEBEN:
        return Decimal('0.00')
    ist_abschlag = beleg.rechnungsart == Rechnungsart.ABSCHLAG
    if ist_abschlag and beleg.pk in ganz_abgerechnete([beleg.pk]):
        return Decimal('0.00')

    zuordnungen = beleg.zahlungszuordnungen.all()
    if ausser is not None:
        zuordnungen = zuordnungen.exclude(pk=ausser)
    ausgeglichen = sum((z.ausgleich for z in zuordnungen), Decimal('0.00'))

    rest = belegsummen(beleg).brutto - ausgeglichen - nachlass(beleg)
    if ist_abschlag:
        rest -= uebernommener_rest(beleg)
    return rest if rest > 0 else Decimal('0.00')


def tage_ueber_frist(beleg: Beleg, stichtag: date | None = None) -> int | None:
    """Tage nach Fälligkeit, **negativ vor Fälligkeit**. ``None`` ohne
    ``faellig_am``. Dieselbe Regel wie ``OffenerPosten.tage_ueberfaellig``
    (R-150) für einen Beleg."""
    if beleg.faellig_am is None:
        return None
    return ((stichtag or timezone.localdate()) - beleg.faellig_am).days


#: Zahlungsstände einer Rechnung in den Listen (R-176). Leer bei Entwurf,
#: Storno und anderen Belegarten, für die der Zustand (Schloss-Symbol)
#: angezeigt wird.
ZAHLUNGSSTAND_OFFEN = 'offen'
ZAHLUNGSSTAND_UEBER_FRIST = 'ueber_frist'
ZAHLUNGSSTAND_BEZAHLT = 'bezahlt'
ZAHLUNGSSTAND_ABGERECHNET = 'abgerechnet'

#: Labels der Stände in Liste und Akte.
ZAHLUNGSSTAND_TEXT = {
    ZAHLUNGSSTAND_OFFEN: 'offen',
    ZAHLUNGSSTAND_UEBER_FRIST: 'über Frist',
    ZAHLUNGSSTAND_BEZAHLT: 'bezahlt',
    ZAHLUNGSSTAND_ABGERECHNET: 'abgerechnet',
}


def zahlungsstand(beleg: Beleg, stichtag: date | None = None,
                  offen: Decimal | None = None) -> str:
    """Offen, über der Frist, bezahlt oder abgerechnet (R-176).

    **Abgerechnet** ist ein Abschlag, den eine festgeschriebene
    Schlussrechnung vollständig absetzt: Offen ist nichts mehr (R-147), weil
    die Schlussrechnung den Rest fordert; bezahlt ist er damit nicht.
    Regression: Die Liste zeigte solche Abschläge als "bezahlt".

    ``offen`` übernimmt einen bereits berechneten ``offener_betrag``, damit
    eine Liste ihn je Zeile nur einmal berechnet.
    """
    if beleg.typ != BelegTyp.RECHNUNG or beleg.status != BelegStatus.FESTGESCHRIEBEN:
        return ''
    if offen is None:
        offen = offener_betrag(beleg)
    if offen <= 0:
        if (beleg.rechnungsart == Rechnungsart.ABSCHLAG
                and beleg.pk in ganz_abgerechnete([beleg.pk])):
            return ZAHLUNGSSTAND_ABGERECHNET
        return ZAHLUNGSSTAND_BEZAHLT
    if (tage_ueber_frist(beleg, stichtag) or 0) > 0:
        return ZAHLUNGSSTAND_UEBER_FRIST
    return ZAHLUNGSSTAND_OFFEN


@dataclass(frozen=True)
class OffenerPosten:
    """Nicht ausgeglichene Rechnung."""

    beleg: Beleg
    brutto: Decimal
    bezahlt: Decimal
    offen: Decimal
    #: Tage nach Fälligkeit, **negativ vor Fälligkeit**. None ohne
    #: ``faellig_am`` (Altdaten).
    tage_ueberfaellig: int | None

    @property
    def ist_ueberfaellig(self) -> bool:
        return (self.tage_ueberfaellig or 0) > 0


@dataclass(frozen=True)
class Postenstand:
    """Summenzeile der offenen Posten."""

    posten: list[OffenerPosten]

    @property
    def anzahl(self) -> int:
        return len(self.posten)

    @property
    def offen(self) -> Decimal:
        return sum((p.offen for p in self.posten), Decimal('0.00'))

    @property
    def ueberfaellig(self) -> list[OffenerPosten]:
        return [p for p in self.posten if p.ist_ueberfaellig]

    @property
    def offen_ueberfaellig(self) -> Decimal:
        return sum((p.offen for p in self.ueberfaellig), Decimal('0.00'))


def offene_posten(stichtag=None, *, belege=None) -> Postenstand:
    """Festgeschriebene Rechnungen mit offenem Betrag, älteste Fälligkeit
    zuerst. ``belege`` schränkt die Menge ein, etwa auf einen Kunden.

    Ohne stornierte; eine festgeschriebene Rechnungskorrektur mindert die
    Forderung ihrer Rechnung (R-182).

    Zweistufig, damit die Laufzeit nicht mit dem Datenbestand wächst: Zwei
    Summenabfragen bestimmen die offenen Rechnungen (``bruttosummen``
    gegen die Summe der Zuordnungen), dann werden nur diese geladen und mit
    ``belegsummen`` berechnet. Verworfen: alle Rechnungen als Objekte laden,
    was bei zehn Jahren Daten 1,4 s auf der Startseite kostete (Lasttest).
    """
    stichtag = stichtag or timezone.localdate()

    alle = Beleg.objects.filter(typ=BelegTyp.RECHNUNG,
                                status=BelegStatus.FESTGESCHRIEBEN)
    if belege is not None:
        alle = alle.filter(pk__in=belege)

    brutto = bruttosummen(alle)
    ausgeglichen = dict(
        Zahlungszuordnung.objects
        .filter(beleg__in=alle)
        .values('beleg_id')
        .annotate(summe=Sum(F('betrag') + F('skonto') + F('kuerzung')))
        .values_list('beleg_id', 'summe')
    )
    gemindert = nachlaesse(alle)
    offen = [pk for pk, wert in brutto.items()
             if wert - ausgeglichen.get(pk, Decimal('0.00'))
             - gemindert.get(pk, Decimal('0.00')) > 0]
    # Ohne Abschläge, deren Forderung mit der Schlussrechnung erloschen
    # ist, weil der Betrag sonst doppelt offen wäre (R-174).
    erloschen = ganz_abgerechnete(offen)
    offen = [pk for pk in offen if pk not in erloschen]

    rechnungen = list(
        Beleg.objects
        .filter(pk__in=offen)
        .select_related('kunde', 'projekt')
        .prefetch_related('positionen', 'zahlungszuordnungen')
    )
    if not rechnungen:
        return Postenstand(posten=[])

    posten = []
    for rechnung in rechnungen:
        brutto = belegsummen(rechnung).brutto
        zuordnungen = list(rechnung.zahlungszuordnungen.all())
        bezahlt = sum((z.betrag for z in zuordnungen), Decimal('0.00'))
        ausgeglichen = sum((z.ausgleich for z in zuordnungen), Decimal('0.00'))
        offen = brutto - ausgeglichen - gemindert.get(rechnung.pk,
                                                      Decimal('0.00'))
        if rechnung.rechnungsart == Rechnungsart.ABSCHLAG:
            offen -= uebernommener_rest(rechnung)
        if offen <= 0:
            continue
        posten.append(OffenerPosten(
            beleg=rechnung,
            brutto=brutto,
            bezahlt=bezahlt,
            offen=offen,
            tage_ueberfaellig=((stichtag - rechnung.faellig_am).days
                               if rechnung.faellig_am else None),
        ))

    posten.sort(key=lambda p: (-(p.tage_ueberfaellig or 0), p.beleg.nummer or ''))
    return Postenstand(posten=posten)


@transaction.atomic
def zahlung_verbuchen(*, beleg_id: int, datum: date, betrag: Decimal,
                      skonto: Decimal = Decimal('0.00'),
                      kuerzung: Decimal = Decimal('0.00'),
                      zahlungsart: str = Zahlungsart.UEBERWEISUNG,
                      verwendungszweck: str = '',
                      notiz: str = '') -> Zahlung:
    """Erfasst einen Zahlungseingang auf genau einer Rechnung, den
    häufigsten Fall. Sammelüberweisungen verteilt die Zahlungsmaske.

    ``betrag`` ist gezahlt, ``skonto`` erlassen; zusammen gleichen sie die
    Forderung aus. Skonto wird nicht berechnet, weil der Kontoauszug zeigt,
    ob die Frist eingehalten ist. ``kuerzung`` nur beim Abschlag: der nicht
    anerkannte, später geforderte Teil. Zahlung und Zuordnung entstehen in
    einer Transaktion.
    """
    beleg = Beleg.objects.select_related('kunde', 'projekt__kunde').get(
        pk=beleg_id)

    if beleg.typ != BelegTyp.RECHNUNG:
        raise FalscherStatus(
            f'{beleg}: Ein Zahlungseingang gehört auf eine Rechnung, '
            f'nicht auf ein Dokument der Art "{beleg.get_typ_display()}".')
    if beleg.status != BelegStatus.FESTGESCHRIEBEN:
        raise FalscherStatus(
            f'{beleg}: Ein Zahlungseingang setzt eine festgeschriebene '
            f'Rechnung voraus. Diese steht auf '
            f'"{beleg.get_status_display()}".')
    if betrag + skonto <= 0:
        raise UngueltigerBetrag(
            'Betrag und Skonto ergeben zusammen null; dann ist nichts zu '
            'vermerken.')

    kunde = anschriftgeber(beleg)
    zahlung = Zahlung(
        datum=datum,
        betrag=betrag,
        zahlungsart=zahlungsart,
        kunde=kunde,
        # Name als Text, damit er mit dem Kontoauszug vergleichbar bleibt,
        # auch nach einer Umbenennung des Kunden.
        zahlername=kunde.name if kunde else beleg.empfaenger_kurz,
        verwendungszweck=verwendungszweck or (beleg.nummer or ''),
        notiz=notiz,
    )
    zahlung.full_clean()
    zahlung.save()

    zuordnung = Zahlungszuordnung(
        zahlung=zahlung, beleg=beleg, betrag=betrag, skonto=skonto,
        kuerzung=kuerzung)
    try:
        # Validiert wird im Modell; hier wird nur der Exception-Typ
        # übersetzt.
        zuordnung.full_clean()
    except ValidationError as fehler:
        raise UngueltigerBetrag(' '.join(fehler.messages)) from fehler
    zuordnung.save()

    return zahlung
