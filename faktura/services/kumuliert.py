"""Kumulierte Darstellung der Abschlagsrechnung.

Ab dem zweiten Abschlag eines Projekts zeigen PDF, E-Rechnung und Maske den
Leistungsstand bis zum Stichtag, darunter die bereits berechneten Abschläge
und als Abschlagsbetrag die Differenz (R-183 bis R-186).

**Gespeichert wird nur der Zuwachs.** Die Positionen eines Abschlags sind,
was er neu berechnet; seine Belegsumme ist der Abschlagsbetrag. Kumuliert
wird ausschließlich bei der Ausgabe. Schlussrechnung, Absetzung, offene
Posten und Mahnwesen rechnen deshalb unverändert mit den Positionen.

**Abgezogen werden die gestellten Abschläge**, nicht die bezahlten. Ein
offener Abschlag bleibt ein eigener offener Posten; zöge der nächste nur
das Bezahlte ab, stünde dieselbe Forderung in zwei Rechnungen.

**Identität auf den Cent.** Der Betrag einer kumulierten Zeile ist die
Summe der gerundeten Positionsnetti ihrer Gruppe (R-001), nicht Gesamtmenge
mal Preis. Damit gilt je Steuersatz: Summe der kumulierten Zeilen minus
Vorgänger gleich Netto des Abschlags, und die Steuer darauf ist dieselbe
wie in ``belegsummen``. Ergibt Gesamtmenge mal Preis einen anderen Betrag,
steht die Zeile als Menge 1, pausch.

**PDF und XML zeigen dieselben Zeilen**, weil der Bildteil einer hybriden
E-Rechnung keine abweichende Leistungsbeschreibung enthalten darf
(Abschn. 14.4 Abs. 4a UStAE).

**Nicht bei Teilabnahmen.** In einem Projekt mit Teilabnahme bleibt der
Abschlag in der einfachen Form, weil die Zuordnung der Abschläge zu
Teilschlussrechnungen (R-165) sonst auch die kumulierte Sicht beträfe.

Verworfen: der kumulierte Stand als Positionen des Abschlags mit den
Vorgängern als Abzugszeilen. Schlussrechnung, Restzeilen und
``ganz_abgerechnete`` setzen voraus, dass eine Abzugszeile den abgesetzten
Abschlag abrechnet; ein Abschlag darf seinen Vorgänger aber nicht abrechnen.
"""

from dataclasses import dataclass
from decimal import Decimal

from ..models import (
    Abnahme,
    Abnahmeart,
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Rechnungsart,
    Zeilenart,
)
from .abschlaege import Abzugszeile
from .summen import positionssumme

#: Einheit einer Zeile, deren Betrag nicht Menge mal Preis ist, und der
#: Vorgängerzeilen im XML.
PAUSCHAL = 'pausch'


@dataclass(frozen=True)
class KumulierterAbschlag:
    """Kumulierte Sicht eines Abschlags.

    ``positionen`` sind ungespeicherte ``Belegposition``-Instanzen, damit
    PDF-Template und XML sie wie gespeicherte verarbeiten. ``abzuege`` je
    Vorgänger und Steuersatz, netto und negativ.
    """

    positionen: list[Belegposition]
    abzuege: list[Abzugszeile]
    vorgaenger: list[Beleg]

    def xml_zeilen(self) -> list[Belegposition]:
        """Die Zeilen der E-Rechnung: die kumulierten Positionen, dann je
        Vorgänger und Satz eine Zeile mit negativem Betrag (Menge 1,
        negativer Preis; das Minus kommt im XML in die Menge, BR-27)."""
        return self.positionen + [
            Belegposition(position='', bezeichnung=abzug.bezeichnung,
                          menge=Decimal('1'), einheit=PAUSCHAL,
                          einzelpreis=abzug.betrag,
                          steuersatz=str(abzug.steuersatz_dezimal))
            for abzug in self.abzuege
        ]


def ist_kumulierbar(beleg: Beleg) -> bool:
    """Ob der Beleg ein Abschlag ist, für den die kumulierte Sicht gilt,
    unabhängig davon, ob es schon Vorgänger gibt."""
    return (beleg.typ == BelegTyp.RECHNUNG
            and beleg.rechnungsart == Rechnungsart.ABSCHLAG
            and beleg.projekt_id is not None
            and not Abnahme.objects.filter(
                auftrag__projekt_id=beleg.projekt_id,
                art=Abnahmeart.TEIL).exists())


def vorgaenger_abschlaege(beleg: Beleg) -> list[Beleg]:
    """Festgeschriebene, nicht stornierte Abschläge des Projekts vor diesem,
    in der Reihenfolge von ``Beleg.abschlagsnummer`` (Belegdatum, pk)."""
    geschwister = list(
        Beleg.objects
        .filter(projekt_id=beleg.projekt_id, typ=BelegTyp.RECHNUNG,
                rechnungsart=Rechnungsart.ABSCHLAG)
        .order_by('belegdatum', 'pk'))
    davor = []
    for b in geschwister:
        if b.pk == beleg.pk:
            break
        if b.status == BelegStatus.FESTGESCHRIEBEN:
            davor.append(b)
    else:
        # Beleg nicht in der Liste (ungespeichert): keine Vorgänger.
        return []
    return davor


def kumulierter_abschlag(beleg: Beleg) -> KumulierterAbschlag | None:
    """Kumulierte Sicht, None für den ersten Abschlag und alle anderen
    Belege; dann gilt die gewöhnliche Darstellung."""
    if not ist_kumulierbar(beleg):
        return None
    vorgaenger = vorgaenger_abschlaege(beleg)
    if not vorgaenger:
        return None

    abzuege = []
    for v in vorgaenger:
        text = (f'{v.rechnungsbezeichnung} {v.nummer} '
                f'vom {v.belegdatum:%d.%m.%Y}')
        for satz, netto in _netto_je_satz(_berechnete(v)).items():
            abzuege.append(Abzugszeile(text, Decimal(satz), -netto))

    quellen = [p for b in [*vorgaenger, beleg] for p in _berechnete(b)]
    return KumulierterAbschlag(positionen=_kumulieren(beleg, quellen),
                               abzuege=abzuege, vorgaenger=vorgaenger)


def _berechnete(beleg: Beleg) -> list[Belegposition]:
    """Positionen mit Betrag, die zur Summe zählen (ohne Titel, Text und
    optionale, R-178)."""
    return [p for p in beleg.positionen
            .select_related('auftragsposition__beleg').all()
            if p.zeilenart not in Zeilenart.ohne_betrag()
            and not p.optional and not p.ist_abzug]


def _netto_je_satz(positionen) -> dict[str, Decimal]:
    """Netto je Steuersatz, je Position gerundet wie ``belegsummen``."""
    summen: dict[str, Decimal] = {}
    for p in positionen:
        summen[p.steuersatz] = summen.get(p.steuersatz, Decimal('0.00')) + (
            positionssumme(menge=p.menge, einzelpreis=p.einzelpreis))
    return summen


def _schluessel(p: Belegposition) -> tuple:
    """Gruppe einer Position in der kumulierten Sicht: je Auftragsposition
    und Satz, sonst nach Bezeichnung, Einheit, Satz und Art; ein Zuschlag
    nach Bezeichnung, Prozentsatz, Bezug und Satz.

    Anders als R-179 ohne den Preis, damit "Nebenkosten 3 %" aus zwei
    Abschlägen mit verschiedenen Beträgen eine Zeile ergibt."""
    if p.zeilenart == Zeilenart.ZUSCHLAG:
        return ('zuschlag', p.bezeichnung, p.zuschlag_prozent,
                p.zuschlag_auf, p.steuersatz)
    if p.auftragsposition_id:
        return ('auftrag', p.auftragsposition_id, p.steuersatz)
    return ('frei', p.bezeichnung, p.einheit, p.steuersatz, p.art)


def _kumulieren(beleg: Beleg, quellen) -> list[Belegposition]:
    """Je Gruppe eine ungespeicherte Position. Reihenfolge: Positionen mit
    Auftragsposition nach deren Ordnung, dann die übrigen in der Reihenfolge
    ihres ersten Auftretens, Zuschläge zuletzt."""
    gruppen: dict[tuple, list[Belegposition]] = {}
    for p in quellen:
        gruppen.setdefault(_schluessel(p), []).append(p)

    def ordnung(eintrag):
        schluessel, gruppe = eintrag
        rang = {'auftrag': 0, 'frei': 1, 'zuschlag': 2}[schluessel[0]]
        if rang == 0:
            vertrag = gruppe[0].auftragsposition
            return (0, vertrag.beleg_id, vertrag.sortierung, vertrag.pk)
        return (rang,)

    zeilen = []
    for schluessel, gruppe in sorted(gruppen.items(), key=ordnung):
        zeile = _zeile(beleg, schluessel[0], gruppe)
        if zeile is not None:
            zeilen.append(zeile)
    return zeilen


def _zeile(beleg: Beleg, art: str, gruppe) -> Belegposition | None:
    """Kumulierte Position einer Gruppe; None, wenn sie nichts enthält."""
    netto = sum((positionssumme(menge=p.menge, einzelpreis=p.einzelpreis)
                 for p in gruppe), Decimal('0.00'))
    menge = sum((p.menge for p in gruppe), Decimal('0'))
    if not netto and not menge:
        return None

    vorlage = gruppe[0]
    vertrag = vorlage.auftragsposition if art == 'auftrag' else None
    quelle = vertrag or vorlage
    preise = {(p.einzelpreis, p.einheit) for p in gruppe}
    if (art != 'zuschlag' and len(preise) == 1
            and positionssumme(menge=menge,
                               einzelpreis=vorlage.einzelpreis) == netto):
        menge, einheit, preis = menge, vorlage.einheit, vorlage.einzelpreis
    else:
        # Teilbeträge zu verschiedenen Preisen, ein Zuschlag oder eine
        # Rundungsdifferenz: der Betrag als Pauschale.
        menge, einheit, preis = Decimal('1'), PAUSCHAL, netto

    von = [p.leistung_von for p in gruppe if p.leistung_von]
    bis = [p.leistung_bis for p in gruppe if p.leistung_bis]
    return Belegposition(
        beleg=beleg,
        position=vertrag.position if vertrag else '',
        bezeichnung=quelle.bezeichnung,
        langtext=quelle.langtext,
        menge=menge, einheit=einheit, einzelpreis=preis,
        steuersatz=vorlage.steuersatz,
        art=vorlage.art,
        auftragsposition=vertrag,
        leistung_von=min(von, default=None),
        leistung_bis=max(bis, default=None),
    )
