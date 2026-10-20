"""Zeilen erfassen und ändern, Zeit zusammenfassen.

Die erfassende Person wird als User übergeben, nicht als Request. Zeiten
bleiben ungerundet; auf die Viertelstunde gerundet wird bei der Abrechnung.
"""

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum

from faktura.models import Katalogposition, Leistungsart, Projekt

from ..formate import dauer_zeigen
from ..models import Erfassungszeile, Fremdleistung
from .fehler import (
    LeistungNichtKontierbar,
    PersonFehlt,
    ProjektAbgeschlossen,
    ZeileAbgerechnet,
)


@transaction.atomic
def zeile_erfassen(*, projekt: Projekt, benutzer, beschreibung: str,
                   leistung: Katalogposition | None = None,
                   auftragsposition=None,
                   datum=None, von=None, bis=None,
                   menge=None, abrechenbar: bool = True) -> Erfassungszeile:
    """Erfasst eine Leistung auf ein Projekt.

    Grundlage ist eine Auftragsposition oder eine Katalogleistung, nie
    beides (``Erfassungszeile._pruefe_grundlage``). ``von`` und ``bis`` sind
    optional; fehlt eines, ist die Dauer null und die Zeile kann später
    ergänzt werden. Abgeschlossene Projekte werden abgelehnt.
    """
    if benutzer is None or not getattr(benutzer, 'pk', None):
        raise PersonFehlt(
            'Zu einer Erfassungszeile gehört die Person, die gearbeitet hat.'
        )

    if projekt.abgeschlossen:
        raise ProjektAbgeschlossen(
            f'{projekt} ist abgeschlossen. Darauf wird nichts mehr kontiert.'
        )

    # Die Freigabe zur Kontierung gibt es nur im Katalog; eine
    # Auftragsposition gilt durch den Auftrag als freigegeben.
    if leistung is not None:
        _leistung_pruefen(leistung)

    zeile = Erfassungszeile(
        projekt=projekt,
        leistung=leistung,
        auftragsposition=auftragsposition,
        benutzer=benutzer,
        beschreibung=beschreibung,
        von=von,
        bis=bis,
        menge=_menge(_art_von(leistung, auftragsposition), menge),
        abrechenbar=abrechenbar,
    )
    if datum is not None:
        zeile.datum = datum

    # full_clean(), weil die Regeln zu Datum und Uhrzeiten in clean() stehen
    # und hier wie im Formular gelten.
    zeile.full_clean()
    zeile.save()
    return zeile


@transaction.atomic
def zeile_aendern(*, zeile_id: int, **felder) -> Erfassungszeile:
    """Ändert eine Erfassungszeile.

    Eine Zeile darf ihr inzwischen abgeschlossenes Projekt behalten;
    abgelehnt wird nur der Wechsel auf ein abgeschlossenes. Eine Zeile auf
    einer Rechnung ist gesperrt; die Regel steht am Modell
    (``ist_gesperrt``) und wird hier wiederholt, damit der Konflikt eine 409
    ergibt und keine Feldmeldung.
    """
    zeile = Erfassungszeile.objects.select_for_update().get(pk=zeile_id)

    if zeile.ist_gesperrt:
        raise ZeileAbgerechnet(
            f'Dieser Eintrag steht auf {zeile.abgerechneter_beleg} und kann '
            f'nicht geändert werden. Zum Ändern ggf. '
            f'Position aus der Rechnung nehmen.'
        )

    if (neues := felder.get('projekt')) is not None:
        if neues.pk != zeile.projekt_id and neues.abgeschlossen:
            raise ProjektAbgeschlossen(
                f'{neues} ist abgeschlossen und kommt für eine Umbuchung '
                f'nicht in Frage.'
            )

    if (neue := felder.get('leistung')) is not None:
        _leistung_pruefen(neue)

    for name, wert in felder.items():
        setattr(zeile, name, wert)

    zeile.full_clean()
    zeile.save()
    return zeile


def zeitsumme(zeilen) -> int:
    """Die erfasste Zeit in ganzen Minuten, ungerundet.

    Nimmt ein QuerySet (dann rechnet die Datenbank) oder eine Liste.
    """
    if hasattr(zeilen, 'aggregate'):
        return zeilen.aggregate(summe=Sum('dauer_minuten'))['summe'] or 0
    return sum(z.dauer_minuten for z in zeilen)


@dataclass(frozen=True)
class Mengensumme:
    """Menge mit Einheit, etwa 184 km oder 2 Stk, je Einheit getrennt."""

    einheit: str
    menge: Decimal


@dataclass(frozen=True)
class Zeitaufstellung:
    """Inhalt eines Leistungsnachweises, ohne HTML und ohne Preise."""

    zeilen: list
    von: date | None
    bis: date | None
    minuten: int
    minuten_ohne_berechnung: int
    mengen: list
    projekt: object | None
    kunde: object | None
    #: Nur am Nachweis zur Rechnung (``nachweis_zur_rechnung``).
    fremdleistungen: list = field(default_factory=list)
    beleg: object | None = None

    @property
    def zeitsumme(self) -> str:
        return dauer_zeigen(self.minuten)

    @property
    def summe_ohne_berechnung(self) -> str:
        return dauer_zeigen(self.minuten_ohne_berechnung)

    @property
    def hat_unberechnetes(self) -> bool:
        return self.minuten_ohne_berechnung > 0


def zeitaufstellung(zeilen) -> Zeitaufstellung:
    """Fasst eine Auswahl von Zeilen zu einem Leistungsnachweis zusammen.

    Die Reihenfolge des Aufrufers bleibt erhalten. Ohne Preise und ohne
    Rundung, weil der Kunde die geleisteten Stunden bestätigt. Projekt und
    Kunde nur, wenn sie für alle Zeilen gleich sind.
    """
    if hasattr(zeilen, 'select_related'):
        zeilen = zeilen.select_related(
            'leistung', 'auftragsposition', 'projekt__kunde', 'benutzer')
    zeilen = list(zeilen)

    daten = [z.datum for z in zeilen]
    mengen = {}
    for zeile in zeilen:
        if zeile.ist_zeitleistung or zeile.menge is None:
            continue
        einheit = zeile.einheit
        mengen[einheit] = mengen.get(einheit, Decimal('0')) + zeile.menge

    projekte = {z.projekt_id: z.projekt for z in zeilen}
    kunden = {z.projekt.kunde_id: z.projekt.kunde for z in zeilen}

    return Zeitaufstellung(
        zeilen=zeilen,
        von=min(daten) if daten else None,
        bis=max(daten) if daten else None,
        minuten=sum(z.dauer_minuten for z in zeilen),
        # Nicht abrechenbare Zeit wird gesondert ausgewiesen, damit Kulanz
        # für den Kunden sichtbar ist.
        minuten_ohne_berechnung=sum(
            z.dauer_minuten for z in zeilen if not z.abrechenbar),
        mengen=[Mengensumme(einheit, menge)
                for einheit, menge in sorted(mengen.items())],
        projekt=next(iter(projekte.values())) if len(projekte) == 1 else None,
        kunde=next(iter(kunden.values())) if len(kunden) == 1 else None,
    )


def nachweis_zur_rechnung(beleg) -> Zeitaufstellung:
    """Leistungsnachweis als Anlage einer Rechnung: Erfassungszeilen und
    weiterberechnete Fremdleistungen auf Positionen des Belegs, nach Datum.

    Projekt und Anschrift kommen vom Beleg, der Zeitraum umfasst beide
    Quellen. Die Stundensumme enthält nur Zeitleistungen, weil eine
    Pauschale als Stück abgerechnet wird und die darauf gebuchte Zeit
    Aufwand ist.
    """
    from faktura.services import anschriftgeber

    zeilen = (Erfassungszeile.objects.filter(abgerechnet_in__beleg=beleg)
              .order_by('datum', 'von', 'pk'))
    fremd = list(
        Fremdleistung.objects.filter(abgerechnet_in__beleg=beleg)
        .select_related('rechnung__lieferant')
        .order_by(F('leistungsdatum').asc(nulls_last=True), 'pk'))
    a = zeitaufstellung(zeilen)
    tage = [t for t in (a.von, a.bis, *(f.leistungsdatum for f in fremd)) if t]
    zeit = [z for z in a.zeilen if z.ist_zeitleistung]
    return replace(
        a, fremdleistungen=fremd, beleg=beleg,
        minuten=sum(z.dauer_minuten for z in zeit),
        minuten_ohne_berechnung=sum(
            z.dauer_minuten for z in zeit if not z.abrechenbar),
        projekt=beleg.projekt if beleg.projekt_id else a.projekt,
        kunde=anschriftgeber(beleg) or a.kunde,
        von=min(tage, default=None), bis=max(tage, default=None))


def hat_nachweis(beleg) -> bool:
    """Ob zur Rechnung etwas nachzuweisen ist."""
    return (Erfassungszeile.objects.filter(abgerechnet_in__beleg=beleg).exists()
            or Fremdleistung.objects.filter(
                abgerechnet_in__beleg=beleg).exists())


def _leistung_pruefen(leistung: Katalogposition) -> None:
    if not leistung.kontierbar:
        raise LeistungNichtKontierbar(
            f'"{leistung}" ist im Katalog nicht für die Erfassung '
            f'freigegeben.'
        )


def _art_von(leistung, auftragsposition) -> str:
    """Leistungsart der gewählten Grundlage, vor dem Speichern. Ohne Art gilt
    MENGE, wie am Modell."""
    grundlage = auftragsposition or leistung
    if grundlage is None:
        return Leistungsart.MENGE
    return getattr(grundlage, 'art', '') or Leistungsart.MENGE


def _menge(art: str, menge):
    """Menge passend zur Art: bei Zeit keine (die Dauer steht separat), bei
    Pauschale eins, bei Menge der angegebene Wert oder keiner."""
    if art == Leistungsart.ZEIT:
        return None
    if art == Leistungsart.PAUSCHALE:
        return Decimal('1')
    return Decimal(str(menge)) if menge is not None else None
