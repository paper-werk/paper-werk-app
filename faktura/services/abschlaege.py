"""Abschläge in der Schluss- und Teilschlussrechnung absetzen.

**Umfang.** Abgesetzt werden alle gestellten Abschläge (festgeschrieben,
nicht storniert), ohne Schalter. Netto abgesetzt wird nur Vereinnahmtes
(§ 14 Abs. 5 Satz 2 UStG): Unter jeder Absetzung steht der nicht bezahlte
Teil des Abschlags (gekürzt oder offen) als positive Zeile
``ist_abschlagsrest``, die nicht abgesetzt wird. Gefordert wird dieser Rest
mit einem späteren Abschlag (Rest aus AB 1 in AB 2) oder mit dieser
Rechnung. Mit ihrem Festschreiben erlischt die Abschlagsforderung
(``abgerechnet_in``), und der Abschlag ist kein offener Posten mehr.
Beispiel: Abschlag 50.000, bezahlt 40.000; abgesetzt -50.000 und +10.000,
im PDF eine Zeile "gestellt 50.000, bezahlt 40.000 ... -40.000"
(``abzugsblock``). Für nicht voll bezahlte Abschläge zeigt die Versandseite
einen Hinweis (``offene_abgesetzte_abschlaege``).

**Abhängigkeit von Zahlungen.** Der Rest kann sich nach dem Absetzen ändern.
``abschlaege_absetzen`` aktualisiert ihn bei jedem Aufruf, das
Festschreiben lehnt eine veraltete Restzeile ab
(``veraltete_abschlagsreste``).

**Zuordnung.** Eine Abschlagsposition, die auf eine Auftragsposition der
Teilleistung verweist, gehört in deren Teilschlussrechnung. Alle übrigen,
auch Pauschalabschläge ohne Positionsbezug, in die Schlussrechnung.

**Genau einmal.** Jede Abzugszeile verweist auf die abgesetzte
Abschlagsposition (``abgesetzte_position``). Abgesetzt ist, was eine nicht
stornierte Rechnung so referenziert; Entwürfe zählen mit, damit zwei
Entwürfe denselben Abschlag nicht doppelt anrechnen. Nach Storno der
Schlussrechnung ist der Abschlag wieder verfügbar.

**Berechnung** wie jede Position: Menge mal negativer Preis, Steuer je Satz.
Das PDF fasst sie je Abschlag unter den Leistungen zusammen (§ 14 Abs. 5
Satz 2 UStG), die E-Rechnung enthält sie als BT-113 (``facturx``).
"""

import re
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, F, Q

from core import rechnen

from ..models import (
    Abnahmeart,
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Rechnungsart,
    Zeilenart,
)
from .anlegen import position_hinzufuegen
from .fehler import FalscherStatus
from .summen import _summen, belegsummen, positionssumme
from .zuschlaege import zuschlaege_nachrechnen

#: Rechnungsarten, die Abschläge absetzen.
ABSETZENDE = (Rechnungsart.SCHLUSS, Rechnungsart.TEILSCHLUSS)


def anrechenbare_abschlagspositionen(rechnung: Beleg) -> list[Belegposition]:
    """Abschlagspositionen, die diese Rechnung absetzen muss: noch nicht
    abgesetzt und nach E9 ihr zugeordnet."""
    if not rechnung.projekt_id:
        return []
    kandidaten = (
        Belegposition.objects
        .filter(beleg__typ=BelegTyp.RECHNUNG,
                beleg__rechnungsart=Rechnungsart.ABSCHLAG,
                beleg__status=BelegStatus.FESTGESCHRIEBEN,
                beleg__projekt=rechnung.projekt_id,
                ist_abzug=False)
        # Titel und Text haben keinen Betrag.
        .exclude(zeilenart__in=Zeilenart.ohne_betrag())
        .exclude(absetzungen__beleg__status__in=(BelegStatus.ENTWURF,
                                                 BelegStatus.FESTGESCHRIEBEN))
        .exclude(beleg__nummer__in=_von_hand_abgesetzt(rechnung.projekt_id))
        .select_related('beleg')
        .order_by('beleg__belegdatum', 'beleg__pk', 'sortierung')
    )
    teil = (rechnung.abnahme_id is not None
            and rechnung.abnahme.art == Abnahmeart.TEIL)
    if teil:
        return list(kandidaten.filter(
            auftragsposition__in=rechnung.abnahme.positionen.all()))

    # Die Schlussrechnung setzt alle übrigen ab, ausgenommen Positionen
    # einer Teilleistung, deren Teilschlussrechnung noch aussteht und sie
    # selbst absetzt. (``teilabnahmen`` gibt es nur bei der Teilabnahme.)
    return list(kandidaten.exclude(
        auftragsposition__teilabnahmen__isnull=False))


def _von_hand_abgesetzt(projekt_id) -> set[str]:
    """Abschläge, die eine Abzugszeile ohne Verweis bereits absetzt
    (manuell eingetragen oder Altdaten vor ``abgesetzte_position``).
    Erkannt an der Abschlagsnummer im Text der Zeile.

    Nur zur Vermeidung doppelter Absetzung, ohne Zuordnung. Regression:
    Eine neue Teilschluss- oder Schlussrechnung setzte einen Abschlag ein
    zweites Mal ab, den eine ältere Schlussrechnung bereits abgesetzt
    hatte.
    """
    texte = list(
        Belegposition.objects
        .filter(beleg__projekt=projekt_id, ist_abzug=True,
                abgesetzte_position__isnull=True,
                # Ohne Storno, weil es die Absetzung nur spiegelt.
                beleg__typ=BelegTyp.RECHNUNG,
                beleg__status__in=(BelegStatus.ENTWURF,
                                   BelegStatus.FESTGESCHRIEBEN))
        .values_list('bezeichnung', flat=True))
    if not texte:
        return set()
    nummern = (Beleg.objects
               .filter(projekt=projekt_id, typ=BelegTyp.RECHNUNG,
                       rechnungsart=Rechnungsart.ABSCHLAG)
               .exclude(nummer__isnull=True)
               .values_list('nummer', flat=True))
    return {n for n in nummern
            if any(re.search(rf'(?<![\w-]){re.escape(n)}(?![\w-])', text)
                   for text in texte)}


@transaction.atomic
def abschlaege_absetzen(*, beleg_id: int) -> list[Belegposition]:
    """Fügt fehlende Abzugszeilen ein; idempotent."""
    rechnung = Beleg.objects.select_for_update().get(pk=beleg_id)
    if rechnung.status != BelegStatus.ENTWURF:
        raise FalscherStatus(f'{rechnung} ist festgeschrieben.')
    if rechnung.rechnungsart not in ABSETZENDE:
        raise FalscherStatus(
            f'Abschläge setzt die Schluss- bzw. Teilschlussrechnung ab, '
            f'nicht {rechnung}.')

    quellen = anrechenbare_abschlagspositionen(rechnung)
    if rechnung.rechnungsart == Rechnungsart.SCHLUSS:
        _leistung_aus_abschlaegen(rechnung, quellen)

    angelegt = []
    for quelle in quellen:
        abschlag = quelle.beleg
        bezeichnung = (f'{abschlag.rechnungsbezeichnung} {abschlag.nummer} '
                       f'vom {abschlag.belegdatum:%d.%m.%Y}')
        if abschlag.positionen.filter(ist_abzug=False).count() > 1:
            bezeichnung += f': {quelle.bezeichnung}'
        angelegt.append(position_hinzufuegen(
            beleg=rechnung, bezeichnung=bezeichnung,
            menge=quelle.menge, einheit=quelle.einheit,
            einzelpreis=-quelle.einzelpreis, steuersatz=quelle.steuersatz,
            ist_abzug=True, abgesetzte_position=quelle,
        ))
    _reste_abgleichen(rechnung)
    zuschlaege_nachrechnen(rechnung)
    return angelegt


def hat_leistungsbezug(quelle: Belegposition) -> bool:
    """Ob eine Abschlagsposition eine Leistung abrechnet: mit Bezug auf eine
    Auftragsposition, aus dem Katalog (``art``) oder mit erfassten Zeiten
    und Fremdleistungen. Ein frei eingegebener Betrag ("Leistungsstand 1,
    pauschal") fordert nur Geld an; die Leistung wird in der
    Schlussrechnung eingetragen."""
    if quelle.auftragsposition_id or quelle.art:
        return True
    # Über die Reverse Relations der Erfassung, ohne Import, weil faktura
    # nicht von erfassung abhängt.
    return (Belegposition.objects.filter(pk=quelle.pk)
            .filter(Q(erfassung__isnull=False)
                    | Q(fremdleistungen__isnull=False))
            .exists())


def _leistung_aus_abschlaegen(rechnung: Beleg, quellen) -> list[Belegposition]:
    """Positionen der vollen Leistung für die Schlussrechnung (§ 14 Abs. 5
    Satz 2 UStG), auch der bereits mit Abschlägen berechneten. Deren Zeiten
    sind am Abschlag abgerechnet und werden nicht erneut übernommen; ohne
    diesen Schritt bestünde die Schlussrechnung nur aus Abzügen.

    Je Leistung **eine** Position mit der Gesamtmenge (R-179):

    * **Auf eine Auftragsposition, zum Vertragspreis** (6 Analysen, dann
      4): die Summe der Mengen aus allen Abschlägen.
    * **Auf eine Auftragsposition, mit anderem Preis** (Teilbetrag,
      "Leistungsphasen 1-4, 5.000 von 18.000"): die Auftragsposition mit
      offener Menge und Preis, weil die Summe der Teilbeträge nicht die
      Leistung ergibt.
    * **Ohne Auftragsposition**, aber aus Katalog oder Erfassung: die Summe
      der Mengen, zusammengefasst über Bezeichnung, Einheit, Preis, Satz
      und Art.
    * **Frei eingegeben** ("Leistungsstand 1, pauschal"): keine Position,
      weil nur Geld angefordert wurde; die Leistung wird manuell
      eingetragen.
    * **Zuschlag** ("Nebenkosten 3 %"): einmal als Zuschlag, berechnet auf
      die volle Leistung der Schlussrechnung.

    Die Positionsnummer kommt von der Auftragsposition, damit die Ordnung
    eines Leistungsverzeichnisses erhalten bleibt. Abgesetzt wird darunter
    je Abschlagsposition.
    """
    je_auftrag: dict[int, list[Belegposition]] = {}
    frei: dict[tuple, list[Belegposition]] = {}
    zuschlaege: dict[tuple, Belegposition] = {}
    for quelle in quellen:
        if quelle.zeilenart == Zeilenart.ZUSCHLAG:
            # Einmal als Zuschlag, neu berechnet auf die volle Leistung;
            # verworfen: die Summe der Zuschläge aus den Abschlägen.
            zuschlaege.setdefault(
                (quelle.bezeichnung, quelle.zuschlag_prozent,
                 quelle.zuschlag_auf, quelle.steuersatz), quelle)
        elif quelle.auftragsposition_id:
            je_auftrag.setdefault(quelle.auftragsposition_id, []).append(quelle)
        elif hat_leistungsbezug(quelle):
            frei.setdefault((quelle.bezeichnung, quelle.einheit,
                             quelle.einzelpreis, quelle.steuersatz,
                             quelle.art), []).append(quelle)

    zeilen = []
    for gruppe in je_auftrag.values():
        vertrag = gruppe[0].auftragsposition
        zum_vertragspreis = vertrag.optional or all(
            p.einzelpreis == vertrag.einzelpreis and p.einheit == vertrag.einheit
            for p in gruppe)
        if zum_vertragspreis:
            menge = sum((p.menge for p in gruppe), Decimal('0'))
        else:
            menge = vertrag.offene_menge
        if menge:
            zeilen.append((vertrag, gruppe, menge))
    for gruppe in frei.values():
        zeilen.append((gruppe[0], gruppe,
                       sum((p.menge for p in gruppe), Decimal('0'))))

    angelegt = []
    for vorlage, gruppe, menge in zeilen:
        vertrag = vorlage if vorlage.beleg.typ == BelegTyp.AUFTRAG else None
        belegt = set(rechnung.positionen.values_list('position', flat=True))
        wunsch = vertrag.position if vertrag else None
        von = [p.leistung_von for p in gruppe if p.leistung_von]
        bis = [p.leistung_bis for p in gruppe if p.leistung_bis]
        angelegt.append(position_hinzufuegen(
            beleg=rechnung, bezeichnung=vorlage.bezeichnung,
            langtext=vorlage.langtext, menge=menge,
            einheit=vorlage.einheit, einzelpreis=vorlage.einzelpreis,
            steuersatz=vorlage.steuersatz, art=vorlage.art,
            auftragsposition=vertrag,
            position=None if wunsch in belegt else wunsch,
            leistung_von=min(von, default=None),
            leistung_bis=max(bis, default=None),
        ))
    for quelle in zuschlaege.values():
        angelegt.append(position_hinzufuegen(
            beleg=rechnung, bezeichnung=quelle.bezeichnung,
            langtext=quelle.langtext, menge=Decimal('1'),
            einheit=quelle.einheit, einzelpreis=Decimal('0.00'),
            steuersatz=quelle.steuersatz, zeilenart=Zeilenart.ZUSCHLAG,
            zuschlag_prozent=quelle.zuschlag_prozent,
            zuschlag_auf=quelle.zuschlag_auf))
    return angelegt


#: Text der Restzeile in der Maske, direkt unter ihrer Absetzung, die die
#: Abschlagsnummer enthält. Neutral formuliert, weil der Rest mit einem
#: späteren Abschlag oder mit dieser Rechnung gefordert sein kann. Nicht im
#: PDF, siehe ``abzugsblock``.
RESTTEXT = 'davon nicht bezahlt, daher nicht abgesetzt'


@dataclass(frozen=True)
class Abzugszeile:
    """Zeile im Block "Bereits berechnete Abschläge" des PDFs."""

    bezeichnung: str
    steuersatz_dezimal: Decimal
    #: Abgesetzter Betrag, netto und negativ.
    betrag: Decimal


def abzugsblock(positionen) -> list[Abzugszeile]:
    """Abzugszeilen für das PDF, eine je Abschlag mit dem abgesetzten
    Betrag, die Restzeile darin enthalten.

    Je Abschlag, weil oben die Leistung steht und darunter nur, was mit
    welchem Abschlag berechnet ist. Getrennt nach Steuersatz, weil § 14
    Abs. 5 Satz 2 UStG die Steuer je Satz verlangt. Intern bleibt die
    Absetzung je Position, weil daran die Zuordnung zur
    Teilschlussrechnung hängt.

    Das PDF zeigt "gestellt 5.000,00, bezahlt 4.000,00 ... -4.000,00" wie
    eine manuell geschriebene Rechnung; eine zusätzliche positive Zeile
    wurde verworfen. Die Summe der Zeilen ist die Summe der Positionen.
    Eine Zeile ohne Verweis auf ihren Abschlag (manuell eingetragen, im
    Storno) erscheint einzeln.
    """
    # Ohne Eurozeichen, weil die Spaltenüberschrift "EUR" enthält.
    from ..formate import geld

    gruppen: dict[tuple, dict] = {}
    for p in positionen:
        if not p.ist_abzug:
            continue
        betrag = positionssumme(menge=p.menge, einzelpreis=p.einzelpreis)
        if not p.abgesetzte_position_id:
            gruppen[('einzeln', p.pk or id(p))] = {
                'text': p.bezeichnung, 'satz': p.steuersatz_dezimal,
                'gestellt': betrag, 'rest': Decimal('0.00')}
            continue
        abschlag = p.abgesetzte_position.beleg
        gruppe = gruppen.setdefault((abschlag.pk, p.steuersatz), {
            'text': (f'{abschlag.rechnungsbezeichnung} {abschlag.nummer} '
                     f'vom {abschlag.belegdatum:%d.%m.%Y}'),
            'satz': p.steuersatz_dezimal,
            'gestellt': Decimal('0.00'), 'rest': Decimal('0.00')})
        gruppe['rest' if p.ist_abschlagsrest else 'gestellt'] += betrag

    zeilen = []
    for g in gruppen.values():
        text = g['text']
        if g['rest'] and g['gestellt']:
            text += (f', gestellt {geld(-g["gestellt"])}, '
                     f'bezahlt {geld(-g["gestellt"] - g["rest"])}')
        zeilen.append(Abzugszeile(text, g['satz'], g['gestellt'] + g['rest']))
    return zeilen


def vereinnahmt(abschlag: Beleg) -> Decimal:
    """Auf den Abschlag eingegangener Betrag brutto: Zahlung plus Skonto,
    ohne Kürzung, die nur verschoben ist."""
    return sum((z.vereinnahmt for z in abschlag.zahlungszuordnungen.all()),
               Decimal('0.00'))


def abschlagsrest(quelle: Belegposition) -> Decimal:
    """Nicht bezahlter Teil einer Abschlagsposition, netto (R-174).

    Zahlungen gelten für den ganzen Abschlag; sein unbezahlter Anteil am
    Brutto wird auf jede Position gleich angewandt, je Position auf den Cent
    gerundet. Bei einer Position mit einem Satz ohne Rundungsrest
    (59.500 brutto, 47.600 bezahlt: 50.000 x 0,2 = 10.000).
    """
    abschlag = quelle.beleg
    brutto = belegsummen(abschlag).brutto
    if brutto <= 0:
        return Decimal('0.00')
    unbezahlt = brutto - vereinnahmt(abschlag)
    if unbezahlt <= 0:
        return Decimal('0.00')
    netto = positionssumme(menge=quelle.menge, einzelpreis=quelle.einzelpreis)
    return rechnen.auf_cent(netto * unbezahlt / brutto)


def _soll_und_ist(rechnung: Beleg):
    """Je Absetzung der Rechnung (Absetzung, Sollwert des Rests, vorhandene
    Restzeile oder None), dazu die Restzeilen ohne Absetzung."""
    abzuege = list(
        rechnung.positionen
        .filter(ist_abzug=True, ist_abschlagsrest=False,
                abgesetzte_position__isnull=False)
        .select_related('abgesetzte_position__beleg'))
    reste = {p.abgesetzte_position_id: p for p in
             rechnung.positionen.filter(ist_abschlagsrest=True)
             .select_related('abgesetzte_position__beleg')}
    paare = [(abzug, abschlagsrest(abzug.abgesetzte_position),
              reste.pop(abzug.abgesetzte_position_id, None))
             for abzug in abzuege]
    return paare, list(reste.values())


def _reste_abgleichen(rechnung: Beleg) -> None:
    """Legt Restzeilen an, ändert ihren Betrag oder löscht sie, nach dem
    aktuellen Zahlungsstand."""
    paare, verwaiste = _soll_und_ist(rechnung)
    for abzug, soll, vorhanden in paare:
        if soll == 0:
            if vorhanden is not None:
                vorhanden.delete()
        elif vorhanden is None:
            belegt = set(rechnung.positionen.values_list('position', flat=True))
            # Direkt unter der Absetzung ("20.1" sortiert vor "21"); ist die
            # Nummer vergeben, ans Ende.
            nummer = f'{abzug.position}.1'
            position_hinzufuegen(
                beleg=rechnung, bezeichnung=RESTTEXT,
                menge=Decimal('1'), einheit='pausch', einzelpreis=soll,
                steuersatz=abzug.steuersatz,
                position=None if nummer in belegt else nummer,
                ist_abzug=True, ist_abschlagsrest=True,
                abgesetzte_position=abzug.abgesetzte_position)
        elif vorhanden.menge != 1 or vorhanden.einzelpreis != soll:
            vorhanden.menge = Decimal('1')
            vorhanden.einzelpreis = soll
            vorhanden.save()
    for zeile in verwaiste:
        zeile.delete()


def veraltete_abschlagsreste(rechnung: Beleg) -> list[Beleg]:
    """Abschläge, deren Restzeile nicht mehr zu den Zahlungen passt, etwa
    nach einer späteren Zahlung. Leer, wenn alle stimmen."""
    paare, verwaiste = _soll_und_ist(rechnung)
    abweichend = {
        abzug.abgesetzte_position.beleg
        for abzug, soll, vorhanden in paare
        if soll != (positionssumme(menge=vorhanden.menge,
                                   einzelpreis=vorhanden.einzelpreis)
                    if vorhanden is not None else Decimal('0.00'))
    }
    abweichend |= {z.abgesetzte_position.beleg for z in verwaiste
                   if z.abgesetzte_position_id}
    return sorted(abweichend, key=lambda b: (b.belegdatum, b.pk))


#: Absetzung, die den Abschlag ausgleicht: in einer festgeschriebenen
#: Rechnung, ohne Storno (das sie nur spiegelt) und ohne Restzeile.
_ERLEDIGT = Q(positionen__absetzungen__beleg__typ=BelegTyp.RECHNUNG,
              positionen__absetzungen__beleg__status=BelegStatus.FESTGESCHRIEBEN,
              positionen__absetzungen__ist_abschlagsrest=False)


def ganz_abgerechnete(belege) -> set[int]:
    """Abschläge, deren Positionen alle in einer festgeschriebenen Schluss-
    oder Teilschlussrechnung abgesetzt sind und deren Forderung damit
    erloschen ist. Eine Abfrage, für die offenen Posten."""
    return set(
        Beleg.objects
        .filter(pk__in=belege, typ=BelegTyp.RECHNUNG,
                rechnungsart=Rechnungsart.ABSCHLAG)
        .annotate(
            gesamt=Count('positionen', filter=Q(positionen__ist_abzug=False)
                         & ~Q(positionen__zeilenart__in=Zeilenart.ohne_betrag()),
                         distinct=True),
            erledigt=Count('positionen', filter=_ERLEDIGT, distinct=True))
        .filter(gesamt__gt=0, gesamt=F('erledigt'))
        .values_list('pk', flat=True))


def abgerechnet_in(abschlag: Beleg) -> Beleg | None:
    """(Teil-)Schlussrechnung, mit der die Forderung aus diesem Abschlag
    erloschen ist, None, solange eine Position offen ist. Bei mehreren die
    jüngste."""
    if (abschlag.typ != BelegTyp.RECHNUNG
            or abschlag.rechnungsart != Rechnungsart.ABSCHLAG
            or abschlag.pk not in ganz_abgerechnete([abschlag.pk])):
        return None
    return (Beleg.objects
            .filter(typ=BelegTyp.RECHNUNG,
                    status=BelegStatus.FESTGESCHRIEBEN,
                    positionen__abgesetzte_position__beleg=abschlag,
                    positionen__ist_abschlagsrest=False)
            .distinct().order_by('-belegdatum', '-pk').first())


def uebernommener_rest(abschlag: Beleg) -> Decimal:
    """Brutto der Restzeilen festgeschriebener Rechnungen zu diesem
    Abschlag, also der anderweitig geforderte Teil. Relevant, solange der
    Abschlag nicht vollständig abgerechnet ist (Teilschluss vor Schluss)."""
    return _summen(Belegposition.objects.filter(
        abgesetzte_position__beleg=abschlag, ist_abschlagsrest=True,
        beleg__typ=BelegTyp.RECHNUNG,
        beleg__status=BelegStatus.FESTGESCHRIEBEN)).brutto


@dataclass(frozen=True)
class OffenerAbschlag:
    abschlag: Beleg
    offen: Decimal

    def __str__(self) -> str:
        from ..formate import euro
        return (f'{self.abschlag.rechnungsbezeichnung} {self.abschlag.nummer}'
                f': {euro(self.offen)} nicht bezahlt, wird nicht '
                f'abgesetzt')


def offene_abgesetzte_abschlaege(rechnung: Beleg) -> list[OffenerAbschlag]:
    """Abgesetzte, nicht voll bezahlte Abschläge, für den Hinweis vor dem
    Festschreiben. Angegeben ist der nicht vereinnahmte Teil (gekürzt oder
    offen), den die Rechnung mit der Restzeile nicht absetzt (R-174)."""
    abschlaege = {
        p.abgesetzte_position.beleg
        for p in rechnung.positionen.filter(abgesetzte_position__isnull=False)
        .select_related('abgesetzte_position__beleg')
    }
    befund = []
    for abschlag in sorted(abschlaege, key=lambda b: (b.belegdatum, b.pk)):
        offen = belegsummen(abschlag).brutto - vereinnahmt(abschlag)
        if offen > 0:
            befund.append(OffenerAbschlag(abschlag=abschlag, offen=offen))
    return befund
