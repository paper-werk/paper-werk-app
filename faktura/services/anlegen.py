"""Belege anlegen, mit Stammdaten füllen, kopieren und umwandeln.

Die Stammdaten werden einmal beim Anlegen kopiert; danach ist der Beleg
von ihnen unabhängig.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from core import erweiterungen

from ..models import (
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Kontakt,
    Projekt,
    Rechnungsart,
    Zeilenart,
)
from ..positionsnummer import naechste_nummern
from .fehler import FalscherStatus, UngueltigerBetrag
from .zuschlaege import zuschlaege_nachrechnen


def anschriftgeber(beleg: Beleg) -> Kontakt | None:
    """Kunde, aus dem die Anschrift des Belegs stammt: der Kunde selbst oder
    der des Projekts, sonst None (Anschrift von Hand).

    Einzige Implementierung, weil verstreute
    ``beleg.kunde or beleg.projekt.kunde`` voneinander abwichen.
    """
    if beleg.kunde_id:
        return beleg.kunde
    if beleg.projekt_id:
        return beleg.projekt.kunde
    return None


@transaction.atomic
def beleg_anlegen(
    *, kunde: Kontakt | None = None, projekt: Projekt | None = None, typ: str,
    betreff: str = '', **felder
) -> Beleg:
    """Legt einen Entwurf an und kopiert die Stammdaten hinein.

    Kunde oder Projekt oder keins (dann Anschrift von Hand). Eine Rechnung
    ohne Art wird eine gewöhnliche.
    """
    if typ == BelegTyp.RECHNUNG:
        felder.setdefault('rechnungsart', Rechnungsart.NORMAL)

    beleg = Beleg(
        kunde=kunde,
        projekt=projekt,
        typ=typ,
        status=BelegStatus.ENTWURF,
        betreff=betreff,
        **felder,
    )
    beleg.full_clean(exclude=['nummer'], validate_unique=False)

    quelle = anschriftgeber(beleg)
    if quelle is not None:
        stammdaten_uebernehmen(beleg=beleg, kunde=quelle)
    beleg.save()
    return beleg


def stammdatenwerte(kunde: Kontakt) -> dict:
    """Werte des Kunden für einen neuen Beleg, nach Feldname am Beleg.

    Einzige Liste dafür: Service, Übernahme im Admin und der JSON-Endpunkt
    für JavaScript lesen sie. Eine explizite Zuordnung, weil Feldnamen
    abweichen (``kaeuferreferenz`` wird ``leitweg_id``).

    Die Anschrift ist die Rechnungsanschrift, als Freitext und strukturiert,
    weil zwei verschiedene Anschriften auf einem Beleg der Widerspruch wären,
    vor dem ``empfaenger_abweichungen`` warnt. Der Hauptansprechpartner wird
    als Verweis und "z. Hd."-Zeile übernommen, seine E-Mail hat Vorrang.
    """
    person = kunde.standardansprechpartner
    anschrift = kunde.rechnungsanschrift
    return {
        'empfaenger': kunde.anschriftfeld_fuer(person),
        'ansprechpartner': person,
        'empfaenger_name': (kunde.rechnungsempfaenger.name
                            if kunde.rechnungsempfaenger_id else kunde.name),
        'empfaenger_strasse': anschrift.strasse if anschrift else '',
        'empfaenger_plz': anschrift.plz if anschrift else '',
        'empfaenger_ort': anschrift.ort if anschrift else '',
        'empfaenger_land': anschrift.land if anschrift else 'DE',
        'empfaenger_ust_id': kunde.ust_id,
        'empfaenger_email': (person.email if person and person.email
                             else kunde.email),
        'zahlungsziel_tage': kunde.zahlungsziel_tage,
        'leitweg_id': kunde.kaeuferreferenz,
        'steuerfall': kunde.steuerfall,
    }


def stammdaten_uebernehmen(
    *, beleg: Beleg, kunde: Kontakt, ausser: Iterable[str] = ()
) -> None:
    """Kopiert Anschrift und Konditionen des Kunden in den Beleg, auch für
    Belege aus dem Formular des Admins.

    ``ausser`` enthält die vom Benutzer geänderten Felder
    (``form.changed_data``), die erhalten bleiben. Eine Regel "nur leere
    Felder" wurde verworfen, weil Felder mit Default (Zahlungsziel 14, Land
    'DE') nie leer sind und das Zahlungsziel des Kunden nie übernommen
    würde.

    Ändert nur die Instanz; der Aufrufer speichert.
    """
    angefasst = set(ausser)
    for name, wert in stammdatenwerte(kunde).items():
        if name in angefasst:
            continue
        setattr(beleg, name, wert)


#: Strukturierte Anschriftsfelder mit ihrer Bezeichnung in der Meldung.
#: Ohne Land, weil "DE" im Anschriftfeld eines Inlandsbelegs fehlt.
ANSCHRIFTSFELDER = [
    ('empfaenger_name', 'Name'),
    ('empfaenger_strasse', 'Straße'),
    ('empfaenger_plz', 'PLZ'),
    ('empfaenger_ort', 'Ort'),
]


def _vergleichsform(text: str) -> str:
    """Normalisiert auf Kleinschreibung und einfache Leerzeichen."""
    return ' '.join(text.split()).casefold()


def empfaenger_abweichungen(beleg: Beleg) -> list[str]:
    """Vergleicht die strukturierte Anschrift (XML) mit dem freien
    Empfängerfeld (PDF).

    Beide sollen dieselbe Anschrift enthalten; erzwungen wird es nicht. Die
    Regel ist bewusst einfach: Jede gefüllte strukturierte Angabe muss im
    freien Text vorkommen, Zusätze im Text sind erlaubt. Ändert nichts und
    liefert nur Befunde, leer, wenn alles passt.
    """
    # Ein leeres Empfängerfeld gehört zu einem unfertigen Entwurf; das
    # Festschreiben meldet es.
    if not beleg.empfaenger.strip():
        return []

    text = _vergleichsform(beleg.empfaenger)
    befunde = []

    for feldname, bezeichnung in ANSCHRIFTSFELDER:
        wert = (getattr(beleg, feldname) or '').strip()
        if not wert:
            continue
        if _vergleichsform(wert) not in text:
            befunde.append(f'{bezeichnung} "{wert}" steht nicht im Empfängerfeld')

    # Ohne strukturierte Anschrift zerlegt facturx.py den Freitext
    # heuristisch, was nur bei gewöhnlichen deutschen Anschriften
    # zuverlässig ist.
    if not (beleg.empfaenger_name or '').strip():
        befunde.append('für die E-Rechnung fehlt der Name')

    return befunde


def position_hinzufuegen(
    *, beleg: Beleg, bezeichnung: str, menge: Decimal, einzelpreis: Decimal,
    steuersatz: str, einheit: str = 'Stk', position: str | int | None = None,
    langtext: str = '', art: str = '', auftragsposition=None,
    ist_abzug: bool = False, leistung_von=None, leistung_bis=None,
    abgesetzte_position=None, ist_abschlagsrest: bool = False,
    optional: bool = False, zeilenart: str = Zeilenart.LEISTUNG,
    zuschlag_prozent: Decimal | None = None, zuschlag_auf: str = '',
) -> Belegposition:
    """Fügt eine Position an. Ohne Nummer bei ganzen Zahlen die höchste plus
    10, damit Positionen dazwischen passen; sonst die nächste nach
    ``positionsnummer.naechste_nummern``.

    ``optional`` nur an Angebot und Auftrag. Die Menge wird hier nicht
    validiert; im Formular verlangt ``Belegposition.clean`` mindestens
    0,001, an einer optionalen Position auch 0.

    ``zeilenart``: Titel und Text ohne Menge und Preis, der Zuschlag mit
    ``zuschlag_prozent`` und ``zuschlag_auf``; sein Betrag wird berechnet,
    ``einzelpreis`` wird ignoriert. Jede neue Zeile berechnet die Zuschläge
    des Belegs neu."""
    if optional and beleg.typ not in BelegTyp.mit_optionen():
        raise UngueltigerBetrag(
            f'Optionale Positionen gibt es nur in Angebot und Auftrag, '
            f'nicht in {beleg.get_typ_display()}.')
    if position is None:
        vergeben = list(beleg.positionen.values_list('position', flat=True))
        if all(n.isdigit() for n in vergeben):
            position = max((int(n) for n in vergeben), default=0) + 10
        else:
            (position,) = naechste_nummern(vergeben, 1)

    neu = Belegposition.objects.create(
        beleg=beleg,
        position=position,
        bezeichnung=bezeichnung,
        langtext=langtext,
        menge=menge,
        einheit=einheit,
        einzelpreis=einzelpreis,
        steuersatz=steuersatz,
        art=art,
        auftragsposition=auftragsposition,
        ist_abzug=ist_abzug,
        leistung_von=leistung_von,
        leistung_bis=leistung_bis,
        abgesetzte_position=abgesetzte_position,
        ist_abschlagsrest=ist_abschlagsrest,
        optional=optional,
        zeilenart=zeilenart,
        zuschlag_prozent=zuschlag_prozent,
        zuschlag_auf=zuschlag_auf,
    )
    if zuschlaege_nachrechnen(beleg) and zeilenart == Zeilenart.ZUSCHLAG:
        neu.refresh_from_db()
    return neu


@transaction.atomic
def nachtrag_anlegen(*, beleg_id: int) -> Beleg:
    """Legt einen Nachtrag zu einem festgeschriebenen Hauptauftrag als
    leeren Entwurf an.

    Ohne Positionen, weil ein Nachtrag nur Zusätzliches enthält und eine
    Kopie die Auftragssumme verdoppelte. Zuordnung und Stammdaten wie bei
    jedem Beleg über ``beleg_anlegen``.
    """
    haupt = Beleg.objects.get(pk=beleg_id)

    if haupt.typ != BelegTyp.AUFTRAG:
        raise FalscherStatus(
            f'{haupt} ist kein Auftrag; ein Nachtrag gehört zu einem '
            f'Auftrag.'
        )
    if haupt.ist_nachtrag:
        raise FalscherStatus(
            f'{haupt} ist selbst ein Nachtrag. Nachträge zeigen alle auf '
            f'denselben Hauptauftrag; legen Sie den nächsten dort an.'
        )
    if haupt.status != BelegStatus.FESTGESCHRIEBEN:
        raise FalscherStatus(
            f'{haupt} ist noch ein Entwurf. Solange der Auftrag nicht steht, '
            f'wird er geändert und nicht nachgetragen.'
        )

    nummer = haupt.nachtraege.count() + 1
    nachtrag = beleg_anlegen(
        projekt=haupt.projekt,
        kunde=haupt.kunde if haupt.projekt_id is None else None,
        typ=BelegTyp.AUFTRAG,
        betreff=f'{nummer}. Nachtrag zu {haupt.nummer}',
    )
    nachtrag.nachtrag_zu = haupt
    nachtrag.save(update_fields=['nachtrag_zu'])
    return nachtrag


def beleg_umwandeln(*, beleg_id: int, neuer_typ: str) -> Beleg:
    """Wandelt um (Angebot, Auftrag, Rechnung): kopiert, ändert den Typ und
    setzt den Vorgänger."""
    original = Beleg.objects.get(pk=beleg_id)

    if original.status != BelegStatus.FESTGESCHRIEBEN:
        raise FalscherStatus(
            f'Nur festgeschriebene Belege werden umgewandelt. {original} hat '
            f'den Status "{original.get_status_display()}".'
        )

    return _beleg_kopieren(
        original, typ=neuer_typ, vorgaenger=original, betreff=original.betreff
    )


@dataclass(frozen=True)
class Duplikat:
    """Ergebnis von ``beleg_duplizieren`` mit den nicht übernommenen
    Positionen."""

    beleg: Beleg
    #: Nicht übernommene Positionen aus Fremdleistungen.
    ohne_fremdleistungen: int = 0


#: Duplizierbare Belegarten. Ohne Schlussrechnung, weil ein Duplikat die
#: Abschläge ein zweites Mal absetzte.
DUPLIZIERBAR = {
    (BelegTyp.ANGEBOT, ''),
    (BelegTyp.RECHNUNG, Rechnungsart.NORMAL),
    (BelegTyp.RECHNUNG, Rechnungsart.ABSCHLAG),
}


@transaction.atomic
def beleg_duplizieren(*, beleg_id: int) -> Duplikat:
    """Neuer Beleg derselben Art mit Inhalt und Positionen als Entwurf,
    unabhängig vom Zustand des Originals.

    Für ein weiteres Angebot an einen anderen Kunden, die Neuauflage eines
    alten oder die nächste Rechnung gleichen Inhalts. Die Nummer vergibt das
    Festschreiben.

    **Vorgänger** ist der Vorgänger des Originals, damit die Kopie neben dem
    Original steht: Eine Rechnung aus einem Auftrag bleibt in dessen Akte,
    ein Angebot ohne Vorgänger bleibt ohne. Ein Verweis auf das Original
    verhinderte über ``PROTECT`` dessen Löschung.

    **Bei Rechnungen:**

    * Positionen aus der **Leistungserfassung** werden als gewöhnliche
      Positionen ohne Bezug zu den Zeiten übernommen, weil der Bezug an der
      Zeile liegt (``Erfassungszeile.abgerechnet_in``) und eine Zeile nur
      auf einer Rechnung abgerechnet ist.
    * Positionen aus **Fremdleistungen** werden nicht übernommen, weil eine
      Eingangsposition einmal weiterberechnet wird.
    * Der Bezug zur **Auftragsposition** wird übernommen; beim
      Festschreiben prüft ``_pruefe_mengen``, ob mehr abgerechnet wird als
      beauftragt.
    """
    original = Beleg.objects.get(pk=beleg_id)
    if (original.typ, original.rechnungsart) not in DUPLIZIERBAR:
        raise FalscherStatus(
            f'{original} lässt sich nicht duplizieren; das geht bei '
            f'Angeboten, Rechnungen und Abschlagsrechnungen.'
        )

    positionen = list(original.positionen.all())
    ohne_fremd = [p for p in positionen
                  if not erweiterungen.hat_besonderen_bezug(p)]

    kopie = _beleg_kopieren(
        original, typ=original.typ, vorgaenger=original.vorgaenger,
        betreff=original.betreff,
        rechnungsart=original.rechnungsart or None,
        positionen=ohne_fremd,
        mit_auftragsbezug=True,
    )
    # Felder, die _beleg_kopieren für das Umwandeln auslässt, die beim
    # Duplikat aber übernommen werden, weil es an dieselbe Person geht.
    kopie.ansprechpartner = original.ansprechpartner
    kopie.empfaenger_email = original.empfaenger_email
    kopie.save(update_fields=['ansprechpartner', 'empfaenger_email'])
    return Duplikat(beleg=kopie,
                    ohne_fremdleistungen=len(positionen) - len(ohne_fremd))


def _beleg_kopieren(
    original: Beleg, *, typ: str, vorgaenger: Beleg | None, betreff: str,
    vorzeichen: Decimal = Decimal('1'),
    rechnungsart: str | None = None,
    positionen: Iterable[Belegposition] | None = None,
    mit_auftragsbezug: bool = False,
) -> Beleg:
    """Entwurf mit Empfängerdaten und Positionen aus dem Original, ohne
    Rückgriff auf die aktuellen Stammdaten.

    Ohne Rechnungsart, weil sie von der Zielart abhängt: Ein Storno hat
    keine, eine Rechnung aus einem Angebot ist eine gewöhnliche.

    ``positionen``: nur diese Positionen. ``mit_auftragsbezug``: auch
    ``auftragsposition``, nur beim Duplizieren, siehe unten.

    **Optionale Positionen** nur in Belegarten mit optionalen Positionen
    (Angebot, Auftrag). Rechnung und Lieferschein enthalten nur Erbrachtes;
    eine abgerufene Option wird wie jede Leistung abgerechnet.
    """
    if positionen is None:
        positionen = original.positionen.all()
    if typ not in BelegTyp.mit_optionen():
        positionen = [p for p in positionen if not p.optional]
    if typ == BelegTyp.RECHNUNG and rechnungsart is None:
        rechnungsart = Rechnungsart.NORMAL

    kopie = Beleg.objects.create(
        kunde=original.kunde,
        projekt=original.projekt,
        typ=typ,
        rechnungsart=rechnungsart or '',
        status=BelegStatus.ENTWURF,
        vorgaenger=vorgaenger,
        betreff=betreff,
        empfaenger=original.empfaenger,
        empfaenger_name=original.empfaenger_name,
        empfaenger_strasse=original.empfaenger_strasse,
        empfaenger_plz=original.empfaenger_plz,
        empfaenger_ort=original.empfaenger_ort,
        empfaenger_land=original.empfaenger_land,
        empfaenger_ust_id=original.empfaenger_ust_id,
        zahlungsziel_tage=original.zahlungsziel_tage,
        kopftext=original.kopftext,
        fusstext=original.fusstext,
        leitweg_id=original.leitweg_id,
        bestellnummer=original.bestellnummer,
        steuerfall=original.steuerfall,
        leistungsdatum=original.leistungsdatum,
        leistungsdatum_bis=original.leistungsdatum_bis,
        # Leer bei Angebot und Auftrag; dann setzt save() einen Wert.
        steuerliches_leistungsdatum=original.steuerliches_leistungsdatum,
    )

    Belegposition.objects.bulk_create([
        Belegposition(
            beleg=kopie,
            position=p.position,
            # Sortierschlüssel explizit, weil bulk_create kein save()
            # aufruft.
            sortierung=p.sortierung,
            bezeichnung=p.bezeichnung,
            langtext=p.langtext,
            menge=p.menge,
            einheit=p.einheit,
            # Beim Storno negativ, weil die Stornorechnung die Rechnung
            # aufhebt.
            einzelpreis=p.einzelpreis * vorzeichen,
            steuersatz=p.steuersatz,
            # Mit Art, damit auf eine aus einem Angebot entstandene
            # Auftragsposition kontiert werden kann.
            art=p.art,
            ist_abzug=p.ist_abzug,
            # Auch im Storno, wo die Restzeile die der Rechnung aufhebt;
            # beide zählen nicht zum Umsatz (R-174).
            ist_abschlagsrest=p.ist_abschlagsrest,
            leistung_von=p.leistung_von,
            leistung_bis=p.leistung_bis,
            optional=p.optional,
            zeilenart=p.zeilenart,
            zuschlag_prozent=p.zuschlag_prozent,
            zuschlag_auf=p.zuschlag_auf,
            # Der Verweis der Absetzung nur in eine neue Rechnung
            # (Korrekturentwurf), die den Abschlag weiter absetzt. Ein Storno
            # spiegelt die Absetzung; mit Verweis zählte es selbst als
            # Absetzung.
            abgesetzte_position=(p.abgesetzte_position
                                 if typ == BelegTyp.RECHNUNG else None),
            # Ohne ``auftragsposition``, weil eine Stornoposition eine
            # positive Menge hat und sonst ein zweites Mal gegen das
            # Kontingent zählte. Beim Duplizieren mit, damit die Kopie
            # gegen das Kontingent zählt.
            auftragsposition=p.auftragsposition if mit_auftragsbezug else None,
        )
        for p in positionen
    ])
    # In der Rechnung bezieht sich der Zuschlag auf ihre Positionen, ohne
    # die nicht übernommenen optionalen.
    zuschlaege_nachrechnen(kopie)

    return kopie
