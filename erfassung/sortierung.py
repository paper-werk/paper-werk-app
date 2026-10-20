"""Benannte Sortierungen für die Erfassung.

Djangos Spaltenköpfe sortieren mehrstufig in umgekehrter Klickreihenfolge:
Der zuletzt angeklickte Kopf wird erster Schlüssel
(``admin_list.result_headers``). Für "Projekt, Datum, Uhrzeit" müsste man
"Uhrzeit, Datum, Projekt" klicken. Die Sortierungen sind deshalb benannt.
Freie Feldlisten entfallen, weil sie eine eigene Abfragesyntax wären; eine
neue Sortierung ist eine Zeile in diesem Modul.
"""

from django.db import models
from django.db.models import Case, F, IntegerField, Value, When

from faktura.models import Leistungsart


class Sortierung(models.TextChoices):
    NEUESTE = 'neueste', 'Neueste zuerst'
    NACHWEIS = 'nachweis', 'Nachweis: Projekt, Art, Datum'
    TAGEBUCH = 'tagebuch', 'Tagebuch: Projekt, Datum, Art'
    PERSON = 'person', 'Person, dann Datum'
    LEISTUNG = 'leistung', 'Leistung, dann Datum'


def _artrang():
    """Rang der Leistungsart: Pauschale, Menge, Zeit.

    Fachliche Festlegung: Auf einem Kundenbericht stehen erst Pauschalen und
    Mengen, dann Stunden, wie auf einer Rechnung. Alphabetisch ergäbe sich
    Menge, Pauschale, Zeit.

    Als ``Case``, weil die Reihenfolge zur Darstellung gehört. Verworfen:
    eine Rangspalte am Katalog, die bei jeder neuen Art zu pflegen wäre.
    """
    return Case(
        When(leistung__art=Leistungsart.PAUSCHALE, then=Value(0)),
        When(leistung__art=Leistungsart.MENGE, then=Value(1)),
        default=Value(2),
        output_field=IntegerField(),
    )


def _person():
    # Nachname, Vorname, dann Benutzername. Personen ohne gepflegten Namen
    # sortieren mit leerem String.
    return ['benutzer__last_name', 'benutzer__first_name', 'benutzer__username']


def _datum():
    return F('datum').asc()


def _uhrzeit():
    """Uhrzeit mit ``nulls_first``, damit eine Anfahrt ohne Uhrzeiten am
    Anfang des Tages steht."""
    return F('von').asc(nulls_first=True)


#: Nach Datum wird immer mit Uhrzeit sortiert.
#
# Die Bausteine sind Funktionen, aus denen jede Sortierung zusammengesetzt
# wird, damit jede Regel nur eine Definition hat. Eine Liste ``_TAG``
# daneben führte zu einer zweiten Definition in ``TAGEBUCH``, die die Tests
# nicht abdeckten.
def _tag():
    return [_datum(), _uhrzeit()]


def _tag_rueckwaerts():
    return [F('datum').desc(), F('von').desc(nulls_last=True)]


def ordnung(schluessel: str) -> list:
    """Sortierung als Liste für ``order_by()``.

    Ein unbekannter Schlüssel wirft ``ValueError``, wie beim Zeitraum, weil
    eine falsche Sortierung auf einem Nachweis nicht auffiele.
    """
    regel = _REGELN.get(schluessel)
    if regel is None:
        raise ValueError(f'Unbekannte Sortierung: {schluessel!r}')
    return regel()


_REGELN = {
    # Vorgabe der Liste: zuletzt Erfasstes oben.
    Sortierung.NEUESTE:
        lambda: _tag_rueckwaerts(),
    # Kundenbericht: je Vorhaben zuerst Pauschalen und Mengen, dann Stunden.
    Sortierung.NACHWEIS:
        lambda: ['projekt__nummer', _artrang().asc(), *_tag()],
    # Je Tag zuerst Pauschalen, dann Stunden, für den zeitlichen Verlauf. Der
    # Artrang liegt zwischen Datum und Uhrzeit, deshalb die Bausteine einzeln
    # und nicht _tag().
    Sortierung.TAGEBUCH:
        lambda: ['projekt__nummer', _datum(), _artrang().asc(), _uhrzeit()],
    Sortierung.PERSON:
        lambda: [*_person(), *_tag()],
    Sortierung.LEISTUNG:
        lambda: ['leistung__bezeichnung', *_tag()],
}


__all__ = ['Sortierung', 'ordnung']
