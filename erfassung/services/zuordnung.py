"""Zuordnung von Fremdleistungen zu Auftragspositionen.

* ``auftragsposition_zum_fremdschluessel``: die Leistungsposition der
  festgeschriebenen Aufträge des Projekts mit diesem Fremdschlüssel
  (``Belegposition.fremdschluessel``). Nur bei genau einem Treffer, weil
  gleichartige Positionen (je Geschoss, je Bauteil) denselben Schlüssel
  tragen und die Auftragsposition beim Übernehmen den Verkaufspreis
  bestimmt.
* ``ueber_fremdschluessel_zuordnen``: wendet das auf Fremdleistungen ohne
  Position an; für Importe und als Aktion in der Liste.
* ``auftragsposition_setzen``: von Hand für eine Auswahl eines Projekts.

Geändert werden nur Fremdleistungen, die auf keiner Rechnung stehen, auch
auf keinem Entwurf (``Fremdleistung.ist_gesperrt``), und nur in laufenden
Projekten.
"""

from dataclasses import dataclass

from django.db import transaction

from faktura.models import (
    Belegposition,
    BelegStatus,
    BelegTyp,
    Projekt,
    Zeilenart,
)

from .fehler import MehrereProjekte, ProjektAbgeschlossen, ZielUngeeignet


def zuordenbare_positionen(projekt: Projekt):
    """Leistungspositionen der festgeschriebenen Aufträge des Projekts; die
    Auswahl der Einzelmaske (``AuftragspositionFeld``) für ein Projekt."""
    return Belegposition.objects.filter(
        beleg__projekt=projekt,
        beleg__typ=BelegTyp.AUFTRAG,
        beleg__status=BelegStatus.FESTGESCHRIEBEN,
        zeilenart=Zeilenart.LEISTUNG,
    )


def auftragsposition_zum_fremdschluessel(
        projekt: Projekt | None, schluessel: str) -> Belegposition | None:
    """Die eine Auftragsposition des Projekts mit diesem Fremdschlüssel;
    ``None`` bei keinem oder mehreren Treffern und in abgeschlossenen
    Projekten."""
    schluessel = (schluessel or '').strip()
    if not schluessel or projekt is None or projekt.abgeschlossen:
        return None
    treffer = list(zuordenbare_positionen(projekt)
                   .filter(fremdschluessel=schluessel)[:2])
    return treffer[0] if len(treffer) == 1 else None


@dataclass
class Zuordnungsbefund:
    """Ergebnis einer Zuordnung, für die Meldung im Admin."""

    geaendert: int = 0
    #: Auf einer Rechnung oder einem Entwurf; nicht geändert.
    gesperrt: int = 0
    #: Nur über den Fremdschlüssel: kein oder kein eindeutiger Treffer.
    ohne_treffer: int = 0


@transaction.atomic
def ueber_fremdschluessel_zuordnen(fremdleistungen) -> Zuordnungsbefund:
    """Setzt an Fremdleistungen ohne Auftragsposition die Position zum
    Fremdschlüssel. Eine vorhandene Position bleibt, auch eine von Hand
    gesetzte."""
    befund = Zuordnungsbefund()
    for fremdleistung in (fremdleistungen.filter(auftragsposition__isnull=True)
                          .select_related('projekt')):
        if fremdleistung.ist_gesperrt:
            befund.gesperrt += 1
            continue
        position = auftragsposition_zum_fremdschluessel(
            fremdleistung.projekt, fremdleistung.fremdschluessel)
        if position is None:
            befund.ohne_treffer += 1
            continue
        fremdleistung.auftragsposition = position
        fremdleistung.save(update_fields=['auftragsposition'])
        befund.geaendert += 1
    return befund


@transaction.atomic
def auftragsposition_setzen(fremdleistungen,
                            position: Belegposition | None) -> Zuordnungsbefund:
    """Setzt die Auftragsposition einer Auswahl; ``None`` entfernt sie.

    Die Auswahl gehört zu genau einem laufenden Projekt, die Position zu
    einem festgeschriebenen Auftrag desselben Projekts (wie
    ``Fremdleistung.clean``). Gesperrte Fremdleistungen werden übersprungen
    und gezählt.
    """
    liste = list(fremdleistungen.select_related('projekt'))
    projekte = {f.projekt for f in liste}
    if len(projekte) > 1:
        raise MehrereProjekte(
            'Die Auswahl enthält Fremdleistungen mehrerer Projekte. Die '
            'Auftragsposition gehört zu einem Projekt; bitte nach Projekt '
            'filtern.')
    befund = Zuordnungsbefund()
    if not liste:
        return befund
    (projekt,) = projekte
    if projekt.abgeschlossen:
        raise ProjektAbgeschlossen(
            f'Projekt {projekt.nummer} ist abgeschlossen; die Zuordnung '
            f'lässt sich nicht mehr ändern.')
    if (position is not None and not zuordenbare_positionen(projekt)
            .filter(pk=position.pk).exists()):
        raise ZielUngeeignet(
            f'{position} ist keine Leistungsposition eines festgeschriebenen '
            f'Auftrags von Projekt {projekt.nummer}.')

    for fremdleistung in liste:
        if fremdleistung.ist_gesperrt:
            befund.gesperrt += 1
            continue
        if fremdleistung.auftragsposition_id == (position.pk if position
                                                 else None):
            continue
        fremdleistung.auftragsposition = position
        fremdleistung.save(update_fields=['auftragsposition'])
        befund.geaendert += 1
    return befund
