"""Erfasste Leistung und Fremdleistung in Rechnungen übernehmen.

Drei verschiedene Mengen:

* **Übernehmbar:** abrechenbar und auf keiner Rechnung, auch keinem
  Entwurf, sonst stünde die Zeile doppelt darauf (``abrechnungsvorschau``,
  ``offene_leistungen``).
* **Noch nicht abgerechnet:** auch Zeilen auf einem Entwurf, weil er noch
  nichts fordert (``NOCH_NICHT_ABGERECHNET``, ``entwuerfe_zaehlen=True``).
* **Änderbar:** nur Zeilen auf keiner Rechnung
  (``Erfassungszeile.ist_gesperrt``).

Auf die Viertelstunde gerundet wird die Summe je Leistung, nie die einzelne
Zeile.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from core import rechnen
from faktura.models import (
    Beleg,
    Belegposition,
    BelegStatus,
    Leistungsart,
    Rechnungsart,
)

from ..formate import dauer_zeigen, personenname
from ..models import Erfassungszeile, Fremdleistung, Zustand
from .fehler import MehrereProjekte, NichtsAbzurechnen, ZielUngeeignet

#: Bedingung "noch nicht abgerechnet": an keiner Belegposition oder an
#: einer auf einem Entwurf. Zählte der Entwurf als abgerechnet, fiele die
#: Leistung aus dem Offenen und, weil Entwürfe dort nicht zählen, auch aus
#: dem Fakturierten. ``abgerechnet_in`` zeigt auf die Belegposition.
#:
#: Der Entwurfsteil ist eine Subquery, weil ``abgerechnet_in__beleg`` jede
#: Zeile vor dem Filtern mit Position und Beleg joint; bei 75.000 Zeilen
#: (zehn Jahre) für null Treffer (Lasttest). Die Subquery ermittelt die
#: wenigen Entwurfspositionen einmal.
NOCH_NICHT_ABGERECHNET = (
    Q(abgerechnet_in__isnull=True)
    | Q(abgerechnet_in__in=Belegposition.objects.filter(
        beleg__status=BelegStatus.ENTWURF))
)

#: Rundungsstufe der Zeitsumme.
VIERTELSTUNDE = 15


def aufgerundete_stunden(minuten: int) -> Decimal:
    """Ganze Minuten als Stunden, aufgerundet auf die Viertelstunde.

    Ganzzahlig gerechnet (``-(-m // 15)``), damit das Ergebnis in
    Viertelschritten exakt ist.
    """
    viertel = -(-int(minuten) // VIERTELSTUNDE)
    return Decimal(viertel) / 4


@dataclass(frozen=True)
class Abrechnungsposition:
    """Rechnungsposition aus erfasster Leistung, eine je Grundlage. Die
    Einzelzeilen stehen im Leistungsnachweis.

    ``grundlage`` ist eine Auftrags- oder eine Katalogposition; beide tragen
    Bezeichnung, Einheit, Preis und Steuersatz.
    """

    grundlage: object
    zeilen: list
    menge: Decimal
    minuten: int

    @property
    def bezeichnung(self) -> str:
        return self.grundlage.bezeichnung

    @property
    def einheit(self) -> str:
        return self.grundlage.einheit

    @property
    def einzelpreis(self) -> Decimal:
        return self.grundlage.einzelpreis

    @property
    def steuersatz(self) -> str:
        return self.grundlage.steuersatz

    @property
    def auftragsposition(self) -> Belegposition | None:
        """Die Auftragsposition oder None bei einer Katalogposition.

        Wird beim Übernehmen in die Rechnungsposition übernommen. Erkannt an
        ``beleg_id``, ohne ``isinstance`` und den dafür nötigen Import.
        """
        return self.grundlage if getattr(self.grundlage, 'beleg_id', None) else None

    @property
    def summe(self) -> Decimal:
        return rechnen.auf_cent(self.menge * self.einzelpreis)

    @property
    def rohzeit(self) -> str:
        """Ungerundete Zeit, in der Vorschau neben der gerundeten Menge."""
        return dauer_zeigen(self.minuten)


@dataclass(frozen=True)
class Fremdposition:
    """Rechnungsposition aus weiterberechneten Fremdleistungen.

    Gebildet in ``_fremdpositionen`` zum Preis der Auftragsposition oder wie
    geliefert zum Einkaufspreis; die Fremdleistung hat keinen
    Verkaufspreis.
    """

    bezeichnung: str
    einheit: str
    einzelpreis: Decimal
    steuersatz: str
    menge: Decimal
    zeilen: list
    auftragsposition: Belegposition | None = None
    art: str = ''

    @property
    def summe(self) -> Decimal:
        return rechnen.auf_cent(self.menge * self.einzelpreis)

    @property
    def einkauf(self) -> Decimal:
        """Einkaufspreis der Position, nur für die Vorschau."""
        return sum((z.einkauf_netto for z in self.zeilen), Decimal('0.00'))

    @property
    def spanne(self) -> Decimal:
        return self.summe - self.einkauf


@dataclass(frozen=True)
class Personenzeilen:
    """Zeilen einer Person zu einer Grundlage."""

    person: object
    zeilen: list

    @property
    def name(self) -> str:
        return personenname(self.person)

    @property
    def minuten(self) -> int:
        return sum(z.dauer_minuten for z in self.zeilen)

    @property
    def dauer(self) -> str:
        return dauer_zeigen(self.minuten)

    @property
    def menge(self) -> Decimal:
        return sum((z.menge or Decimal("0") for z in self.zeilen),
                   Decimal("0"))


@dataclass(frozen=True)
class Grundlagengruppe:
    """Zeilen einer Auftrags- oder Katalogposition, nach Personen
    gruppiert. Auf der Rechnung eine Position; die Personen sind eine Ebene
    der Auswahl."""

    grundlage: object
    personen: list

    @property
    def bezeichnung(self) -> str:
        return self.grundlage.bezeichnung

    @property
    def einheit(self) -> str:
        return self.grundlage.einheit

    @property
    def einzelpreis(self) -> Decimal:
        return self.grundlage.einzelpreis

    @property
    def zeilen(self) -> list:
        return [z for p in self.personen for z in p.zeilen]

    @property
    def minuten(self) -> int:
        return sum(p.minuten for p in self.personen)

    @property
    def dauer(self) -> str:
        return dauer_zeigen(self.minuten)

    @property
    def ist_zeit(self) -> bool:
        return bool(self.zeilen) and self.zeilen[0].ist_zeitleistung

    @property
    def menge(self) -> Decimal:
        """Menge auf der Rechnung, gerundet wie in ``abrechnungsvorschau``."""
        if self.ist_zeit:
            return aufgerundete_stunden(self.minuten)
        return sum((p.menge for p in self.personen), Decimal("0"))

    @property
    def summe(self) -> Decimal:
        return rechnen.auf_cent(self.menge * self.einzelpreis)


@dataclass(frozen=True)
class Auftragsgruppe:
    """Offene Zeilen eines Auftrags; ``auftrag`` None für Zeilen auf
    Katalogpositionen ("Ohne Auftrag", in der Auswahl zuletzt)."""

    auftrag: object | None
    gruppen: list

    @property
    def bezeichnung(self) -> str:
        if self.auftrag is None:
            return "Ohne Auftrag"
        return f"{self.auftrag.nummer or 'Entwurf'} · {self.auftrag.betreff}" \
            if self.auftrag.betreff else (self.auftrag.nummer or "Auftrag")

    @property
    def zeilen(self) -> list:
        return [z for g in self.gruppen for z in g.zeilen]

    @property
    def summe(self) -> Decimal:
        return sum((g.summe for g in self.gruppen), Decimal("0.00"))


def offene_leistungen(projekt) -> list:
    """Abrechenbare Leistung des Vorhabens nach Auftrag, Position und
    Person, für die Maske "Erbrachte Leistungen hinzufügen".

    "Offen" wie in ``abrechnungsvorschau``, also ohne Zeilen auf Entwürfen.
    Beide Wege rufen ``in_rechnung_uebernehmen`` auf. Zeilen ohne Auftrag
    stehen am Ende.
    """
    zeilen = (
        Erfassungszeile.objects
        .filter(projekt=projekt)
        .im_zustand(Zustand.OFFEN)
        .select_related('leistung', 'auftragsposition__beleg', 'benutzer')
        .order_by('auftragsposition__beleg__nummer',
                  'auftragsposition__sortierung', 'datum', 'pk')
    )

    # Der Schlüssel enthält das Modell, weil Auftragsposition 7 und
    # Katalogposition 7 verschiedene Datensätze sind.
    nach_auftrag: dict = {}
    for zeile in zeilen:
        if _abzurechnende_menge(zeile) <= 0:
            # Gruppen mit Menge null entfallen, weil die Auswahl nichts
            # bewirkte.
            continue
        auftrag = (zeile.auftragsposition.beleg
                   if zeile.auftragsposition_id else None)
        schluessel = (('auftrag', zeile.auftragsposition_id)
                      if zeile.auftragsposition_id
                      else ('katalog', zeile.leistung_id))
        gruppen = nach_auftrag.setdefault(
            auftrag.pk if auftrag else None, (auftrag, {}))[1]
        personen = gruppen.setdefault(schluessel, (zeile.grundlage, {}))[1]
        personen.setdefault(zeile.benutzer_id,
                            (zeile.benutzer, []))[1].append(zeile)

    ergebnis = [
        Auftragsgruppe(
            auftrag=auftrag,
            gruppen=[
                Grundlagengruppe(
                    grundlage=grundlage,
                    personen=[Personenzeilen(person=person, zeilen=liste)
                              for person, liste in sorted(
                                  personen.values(),
                                  key=lambda p: personenname(p[0]))],
                )
                for grundlage, personen in gruppen.values()
            ],
        )
        for auftrag, gruppen in nach_auftrag.values()
    ]

    ergebnis.sort(key=lambda g: (g.auftrag is None,
                                 g.auftrag.nummer or '' if g.auftrag else ''))
    return ergebnis


@dataclass(frozen=True)
class Uebernahmevorschau:
    """Vorschau der Übernahme, ohne Änderungen."""

    positionen: list
    projekt: object | None
    uebergangen: list
    fremdpositionen: list = field(default_factory=list)

    @property
    def alle_positionen(self) -> list:
        """Positionen aus eigener Leistung, danach aus Fremdleistungen."""
        return [*self.positionen, *self.fremdpositionen]

    @property
    def netto(self) -> Decimal:
        return sum((p.summe for p in self.alle_positionen), Decimal('0'))

    @property
    def fremdkosten(self) -> Decimal:
        """Einkaufspreis der Fremdpositionen."""
        return sum((p.einkauf for p in self.fremdpositionen), Decimal('0.00'))

    @property
    def zeilenzahl(self) -> int:
        return sum(len(p.zeilen) for p in self.alle_positionen)


#: Gründe, aus denen eine Zeile nicht übernommen wird; sie werden je Zeile
#: angezeigt.
GRUND_NICHT_ABRECHENBAR = 'nicht abrechenbar'
GRUND_SCHON_ABGERECHNET = 'bereits abgerechnet'
GRUND_OHNE_UMFANG = 'ohne Zeit und ohne Menge'
GRUND_OHNE_WERT = 'ohne Menge oder ohne Betrag'


@dataclass(frozen=True)
class Fremdleistungsgruppe:
    """Offene Positionen einer Eingangsrechnung für die Auswahlmaske."""

    rechnung: object
    bezeichnung: str
    summe: Decimal
    positionen: list


def offene_fremdleistungen(projekt) -> list[Fremdleistungsgruppe]:
    """Noch nicht weiterberechnete Fremdleistungen des Vorhabens.

    Gegenstück zu ``offene_leistungen``, nach Eingangsrechnung gruppiert,
    weil Lieferant und Nummer sie identifizieren. Nicht abrechenbare
    Positionen entfallen.
    """
    positionen = (
        Fremdleistung.objects
        .filter(projekt=projekt, weiterberechenbar=True,
                abgerechnet_in__isnull=True)
        .select_related('rechnung__lieferant', 'auftragsposition__beleg')
        .order_by('rechnung__datum', 'rechnung__nummer', 'pk')
    )

    nach_rechnung: dict = {}
    for position in positionen:
        gruppe = nach_rechnung.setdefault(position.rechnung_id, [])
        gruppe.append(position)

    ergebnis = []
    for teil in nach_rechnung.values():
        rechnung = teil[0].rechnung
        ergebnis.append(Fremdleistungsgruppe(
            rechnung=rechnung,
            bezeichnung=f'{rechnung.lieferant.name} · {rechnung.nummer}',
            # Zum Einkaufspreis; die Fremdleistung hat keinen Verkaufspreis.
            summe=sum((p.einkauf_netto for p in teil), Decimal('0.00')),
            positionen=teil,
        ))
    return ergebnis


def _liegt_auf_einem_entwurf(posten) -> bool:
    """``NOCH_NICHT_ABGERECHNET`` für ein geladenes Objekt in Python."""
    beleg = getattr(posten.abgerechnet_in, 'beleg', None)
    return beleg is not None and beleg.status == BelegStatus.ENTWURF


def abrechnungsvorschau(zeilen, fremdleistungen=None, *,
                        entwuerfe_zaehlen: bool = False) -> Uebernahmevorschau:
    """Fasst eine Auswahl zu Rechnungspositionen zusammen, ohne zu speichern.

    Gerundet wird je Leistung auf die Summe, nicht je Zeile::

        zwölf Zeilen zu 20 Minuten  = 240 Minuten gearbeitet
        auf die Summe aufgerundet   = 4,00 Std
        je Zeile aufgerundet        = 6,00 Std   <- 50 % mehr, zu Lasten
                                                    des Kunden

    Der Preis kommt aus Katalog oder Auftragsposition mit aktuellem Stand.
    Fremdleistungen desselben Vorhabens stehen in einer eigenen Liste.

    ``entwuerfe_zaehlen`` wählt die Menge (siehe Modul-Docstring): ``False``
    für das Übernehmen, damit Zeilen auf Entwürfen nicht doppelt auf eine
    Rechnung kommen; ``True`` für Auswertungen. Vorgabe ist ``False``, weil
    ein Fehler dort beim Kunden ankäme.
    """
    if hasattr(zeilen, 'select_related'):
        zeilen = zeilen.select_related(
            'leistung', 'auftragsposition', 'projekt',
            'abgerechnet_in__beleg')
    zeilen = list(zeilen)

    uebergangen = []
    brauchbar = []
    for zeile in zeilen:
        if not zeile.abrechenbar:
            uebergangen.append((zeile, GRUND_NICHT_ABRECHENBAR))
        elif zeile.abgerechnet_in_id and not (
                entwuerfe_zaehlen and _liegt_auf_einem_entwurf(zeile)):
            uebergangen.append((zeile, GRUND_SCHON_ABGERECHNET))
        elif _abzurechnende_menge(zeile) <= 0:
            uebergangen.append((zeile, GRUND_OHNE_UMFANG))
        else:
            brauchbar.append(zeile)

    fremd_brauchbar = []
    for position in _als_liste(fremdleistungen):
        if not position.weiterberechenbar:
            uebergangen.append((position, GRUND_NICHT_ABRECHENBAR))
        elif position.abgerechnet_in_id and not (
                entwuerfe_zaehlen and _liegt_auf_einem_entwurf(position)):
            uebergangen.append((position, GRUND_SCHON_ABGERECHNET))
        elif position.menge <= 0 or position.einkauf_netto <= 0:
            # Stünde mit null auf der Rechnung, während die Kosten am
            # Projekt bleiben; deshalb als übergangen gemeldet.
            uebergangen.append((position, GRUND_OHNE_WERT))
        else:
            fremd_brauchbar.append(position)

    projekte = {z.projekt_id: z.projekt for z in brauchbar}
    projekte.update({p.projekt_id: p.projekt for p in fremd_brauchbar})
    if len(projekte) > 1:
        namen = ', '.join(sorted(str(p) for p in projekte.values()))
        raise MehrereProjekte(
            f'Die Auswahl umfasst mehrere Projekte ({namen}). Eine Rechnung '
            f'gehört zu einem davon; bitte getrennt abrechnen.'
        )

    # Der Schlüssel enthält das Modell, damit Auftrags- und Katalogposition
    # mit gleicher ID getrennt bleiben.
    nach_grundlage = {}
    for zeile in brauchbar:
        schluessel = (('auftrag', zeile.auftragsposition_id)
                      if zeile.auftragsposition_id
                      else ('katalog', zeile.leistung_id))
        nach_grundlage.setdefault(schluessel, []).append(zeile)

    positionen = []
    for gruppe in nach_grundlage.values():
        erste = gruppe[0]
        minuten = sum(z.dauer_minuten for z in gruppe)
        if erste.leistungsart == Leistungsart.ZEIT:
            menge = aufgerundete_stunden(minuten)
        else:
            menge = sum((z.menge or Decimal('0') for z in gruppe), Decimal('0'))
        positionen.append(Abrechnungsposition(
            grundlage=erste.grundlage, zeilen=gruppe, menge=menge,
            minuten=minuten))

    positionen.sort(key=lambda p: p.bezeichnung)

    return Uebernahmevorschau(
        positionen=positionen,
        projekt=next(iter(projekte.values())) if len(projekte) == 1 else None,
        uebergangen=uebergangen,
        fremdpositionen=_fremdpositionen(fremd_brauchbar),
    )


def _als_liste(werte) -> list:
    """Wandelt None, QuerySet oder Liste in eine Liste.

    Nur Felder der Fremdleistung, weil ein falscher Name erst im SQL-Compiler
    als FieldError auffiele.
    """
    if werte is None:
        return []
    if hasattr(werte, 'select_related'):
        werte = werte.select_related(
            'projekt', 'auftragsposition__beleg', 'abgerechnet_in__beleg')
    return list(werte)


#: Einheit, wenn Menge mal Preis den Einkaufsbetrag nicht auf den Cent
#: ergibt.
EINHEIT_PAUSCHAL = 'pausch'


def _einheit_passt(auftragsposition, fremdleistung) -> bool:
    """Vergleicht Einheiten ohne Groß- und Kleinschreibung und Leerraum:
    "Stk" und "stk " sind gleich, "Stk" und "pausch" nicht."""
    return (auftragsposition.einheit.strip().casefold()
            == fremdleistung.einheit.strip().casefold())


def _fremdpositionen(positionen) -> list:
    """Fasst Fremdleistungen zu Rechnungspositionen zusammen, auf einem von
    zwei Wegen in dieser Reihenfolge:

    1. **Zum Preis der Auftragsposition**, wenn eine gewählt ist und die
       Einheit passt: Bezeichnung, Einheit, Preis und Steuersatz kommen von
       dort (der Vertrag), die Menge ist die Summe. Je Auftragsposition eine
       Rechnungsposition, wie bei den Stunden.
    2. **Wie geliefert, zum Einkaufspreis**, sonst. Gruppiert nach Bezeichnung,
       Einheit, Preis und Auftragsposition: vierzig Bodenproben desselben
       Pakets werden eine Zeile mit der Menge 40. Eine gewählte
       Auftragsposition bleibt als Bezug stehen, auch wenn ihr Preis wegen
       der Einheit nicht gilt.

    Beim zweiten Weg steht der Einkaufsbetrag auf der Rechnung. Ergibt Menge
    mal Preis ihn nicht auf den Cent (Rabatt auf der Zeile, Preis je 100 m),
    wird die Gruppe eine Pauschale über den Betrag mit der Menge in der
    Bezeichnung. Ein Aufschlag wird danach in der Rechnung gesetzt.
    """
    from faktura.models import steuersatz as steuersatz_tabelle

    gruppen: dict = {}
    for position in positionen:
        auftrag = position.auftragsposition
        if auftrag is not None and _einheit_passt(auftrag, position):
            schluessel = ('auftrag', auftrag.pk)
        else:
            schluessel = ('geliefert', position.bezeichnung, position.einheit,
                          position.einkaufspreis, position.auftragsposition_id)
        gruppen.setdefault(schluessel, []).append(position)

    ergebnis = []
    for schluessel, gruppe in gruppen.items():
        erste = gruppe[0]
        menge = sum((p.menge for p in gruppe), Decimal('0'))

        if schluessel[0] == 'auftrag':
            auftrag = erste.auftragsposition
            ergebnis.append(Fremdposition(
                bezeichnung=auftrag.bezeichnung,
                einheit=auftrag.einheit,
                einzelpreis=auftrag.einzelpreis,
                steuersatz=auftrag.steuersatz,
                menge=menge,
                zeilen=gruppe,
                auftragsposition=auftrag,
                art=auftrag.art,
            ))
            continue

        einkauf = sum((p.einkauf_netto for p in gruppe), Decimal('0.00'))
        preis = rechnen.auf_cent(erste.einkaufspreis)
        if rechnen.auf_cent(menge * preis) == einkauf:
            bezeichnung, einheit = erste.bezeichnung, erste.einheit
        else:
            bezeichnung = (f'{erste.bezeichnung} ({menge.normalize():f} '
                           f'{erste.einheit})'.replace(' )', ')'))
            menge, einheit, preis = Decimal('1'), EINHEIT_PAUSCHAL, einkauf
        ergebnis.append(Fremdposition(
            bezeichnung=bezeichnung,
            einheit=einheit,
            einzelpreis=preis,
            steuersatz=steuersatz_tabelle.vorgabe(),
            menge=menge,
            zeilen=gruppe,
            auftragsposition=erste.auftragsposition,
        ))

    ergebnis.sort(key=lambda p: p.bezeichnung)
    return ergebnis


def _abzurechnende_menge(zeile) -> Decimal:
    if zeile.leistungsart == Leistungsart.ZEIT:
        return Decimal(zeile.dauer_minuten)
    return zeile.menge or Decimal('0')


def _nummer_aus_auftrag(beleg: Beleg, auftragsposition) -> str | None:
    """Positionsnummer der Auftragsposition, damit die Rechnung die Ordnung
    des LV behält.

    ``None``, wenn es keine gibt oder sie auf ``beleg`` bereits vergeben
    ist; dann vergibt ``position_hinzufuegen`` die nächste freie. Wie bei
    der Abnahme.
    """
    if auftragsposition is None:
        return None
    if beleg.positionen.filter(position=auftragsposition.position).exists():
        return None
    return auftragsposition.position


#: Rechnungsarten, die beim Übernehmen neu angelegt werden können. Ohne
#: Teilschlussrechnung, die nur aus einer Teilabnahme entsteht.
NEU_ANLEGBAR = (Rechnungsart.NORMAL, Rechnungsart.ABSCHLAG,
                Rechnungsart.SCHLUSS)


@transaction.atomic
def in_rechnung_uebernehmen(*, zeilen, fremdleistungen=None,
                            beleg: Beleg | None = None,
                            rechnungsart: str = Rechnungsart.NORMAL,
                            ) -> tuple[Beleg, Uebernahmevorschau]:
    """Schreibt die Auswahl als Positionen auf eine Rechnung.

    Ohne ``beleg`` entsteht ein neuer Entwurf zum Vorhaben, in der
    ``rechnungsart`` (gewöhnliche, Abschlags- oder Schlussrechnung), sonst
    werden die Positionen an einen vorhandenen Rechnungsentwurf desselben
    Empfängers gehängt. Gibt ``(beleg, vorschau)`` zurück, damit der
    Aufrufer melden kann, was übergangen wurde.

    Eine neue Schlussrechnung setzt die gestellten Abschläge ab, wie die aus
    einer Abnahme, damit sie den Betrag nicht doppelt fordert (§ 14 Abs. 5
    Satz 2 UStG).
    """
    from faktura.models import BelegTyp
    from faktura.services import (
        abschlaege_absetzen,
        beleg_anlegen,
        position_hinzufuegen,
    )

    if beleg is None and rechnungsart not in NEU_ANLEGBAR:
        raise ZielUngeeignet(
            f'Eine {Rechnungsart(rechnungsart).label} entsteht hier nicht.'
            if rechnungsart in Rechnungsart.values
            else f'Unbekannte Rechnungsart "{rechnungsart}".')

    vorschau = abrechnungsvorschau(zeilen, fremdleistungen)
    if not vorschau.alle_positionen:
        raise NichtsAbzurechnen(
            'In der Auswahl steht nichts, was abgerechnet werden könnte.'
        )

    if beleg is None:
        beleg = beleg_anlegen(
            projekt=vorschau.projekt,
            typ=BelegTyp.RECHNUNG,
            rechnungsart=rechnungsart,
            betreff=f'Leistungen {vorschau.projekt}' if vorschau.projekt else '',
        )
        neu_angelegt = True
    else:
        neu_angelegt = False
        if not beleg.ist_aenderbar:
            raise ZielUngeeignet(
                f'{beleg} ist festgeschrieben und nimmt keine Positionen mehr '
                f'auf.'
            )
        # Auch im Service geprüft, weil ein Angebotsentwurf desselben
        # Vorhabens alle anderen Prüfungen bestünde.
        if beleg.typ != BelegTyp.RECHNUNG:
            raise ZielUngeeignet(
                f'{beleg} ist keine Rechnung. Erfasste Leistung ist erbracht '
                f'und gehört nicht in ein Angebot.'
            )
        if beleg.projekt_id and vorschau.projekt and beleg.projekt_id != vorschau.projekt.pk:
            raise ZielUngeeignet(
                f'{beleg} gehört zu einem anderen Projekt.'
            )
        # Der Empfänger muss übereinstimmen, sonst wäre auch die
        # Sammelrechnung eines anderen Kunden ein Ziel. Ein Beleg mit von Hand
        # eingegebenem Empfänger ist nicht prüfbar und wird abgelehnt.
        ziel_kunde = beleg.kunde_id or (
            beleg.projekt.kunde_id if beleg.projekt_id else None)
        soll_kunde = vorschau.projekt.kunde_id if vorschau.projekt else None
        if ziel_kunde != soll_kunde:
            raise ZielUngeeignet(
                f'{beleg} ist an einen anderen Empfänger gerichtet.'
            )

    # Der Verweis zeigt auf die Belegposition, damit das Löschen einer
    # Position genau ihre Zeilen freigibt. Über update(), weil clean()
    # abgerechnete Zeilen sperrt.
    for position in vorschau.positionen:
        # Der Zeitraum der Position (BT-134/135): erster bis letzter Tag
        # ihrer Tätigkeiten. Die Tage selbst gehen nicht in die Rechnung.
        tage = [z.datum for z in position.zeilen]
        angelegt = position_hinzufuegen(
            beleg=beleg,
            bezeichnung=position.bezeichnung,
            menge=position.menge,
            einheit=position.einheit,
            einzelpreis=position.einzelpreis,
            steuersatz=position.steuersatz,
            auftragsposition=position.auftragsposition,
            position=_nummer_aus_auftrag(beleg, position.auftragsposition),
            leistung_von=min(tage, default=None),
            leistung_bis=max(tage, default=None),
        )
        Erfassungszeile.objects.filter(
            pk__in=[z.pk for z in position.zeilen]
        ).update(abgerechnet_in=angelegt)

    for position in vorschau.fremdpositionen:
        # Wie bei den Stunden erstes bis letztes Leistungsdatum der Gruppe;
        # Fremdleistungen ohne Datum zählen nicht.
        tage = [z.leistungsdatum for z in position.zeilen if z.leistungsdatum]
        angelegt = position_hinzufuegen(
            beleg=beleg,
            bezeichnung=position.bezeichnung,
            menge=position.menge,
            einheit=position.einheit,
            einzelpreis=position.einzelpreis,
            steuersatz=position.steuersatz,
            art=position.art,
            auftragsposition=position.auftragsposition,
            position=_nummer_aus_auftrag(beleg, position.auftragsposition),
            leistung_von=min(tage, default=None),
            leistung_bis=max(tage, default=None),
        )
        Fremdleistung.objects.filter(
            pk__in=[z.pk for z in position.zeilen]
        ).update(abgerechnet_in=angelegt)

    if neu_angelegt and beleg.rechnungsart == Rechnungsart.SCHLUSS:
        abschlaege_absetzen(beleg_id=beleg.pk)

    return beleg, vorschau
