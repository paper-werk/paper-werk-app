"""Einlesen der Fachszenarien und Auflösen der Varianten.

Ein Fall liegt als TOML-Datei vor (Schema in der README des Katalogs).
Beträge stehen dort als Zeichenkette und werden hier zu ``Decimal``.

Ein Sollwert ist entweder ein fester Betrag oder eine Variantentabelle je
Regelfrage, in TOML ``{ R2.A = "45062.86", R2.B = "42029.25" }``, was
``tomllib`` zu ``{'R2': {'A': ..., 'B': ...}}`` liest. Daneben gibt es
Tabellen je Kunde (``{ HOLDING = "0.00", PG = {...} }``), deren Werte
wiederum Variantentabellen sein können.

``Bindung`` hält je Regelfrage die Varianten, die nach den bisherigen
Schritten noch möglich sind. Jeder Vergleich schränkt sie ein; ist eine
Menge leer, entspricht der Fall keiner zulässigen Variante.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

#: Umgebungsvariable mit dem Ordner der Fälle. Die Fälle liegen außerhalb
#: des Repos, bis sie veröffentlicht werden.
UMGEBUNG = 'PAPERWERK_FACHSZENARIEN'

REGELFRAGE = re.compile(r'^R\d+$')
VARIANTE = re.compile(r'^[A-Z]$')


def ordner() -> Path | None:
    """Ordner der Fälle aus ``PAPERWERK_FACHSZENARIEN`` oder None."""
    pfad = os.environ.get(UMGEBUNG)
    if not pfad:
        return None
    return Path(pfad)


def dateien() -> list[Path]:
    """Alle Falldateien, nach Nummer sortiert; leer ohne Ordner."""
    basis = ordner()
    if basis is None or not basis.is_dir():
        return []
    return sorted(basis.glob('[0-9][0-9]-*.toml'))


def betrag(text) -> Decimal:
    """Betrag aus der Zeichenkette der TOML-Datei."""
    try:
        return Decimal(str(text))
    except InvalidOperation as fehler:
        raise ValueError(f'Kein Betrag: {text!r}') from fehler


def ist_variantentabelle(wert) -> bool:
    """``{'R2': {'A': ..., 'B': ...}}``: nur Schlüssel ``R<n>`` mit
    Tabellen aus Schlüsseln ``A``, ``B``, ..."""
    return (
        isinstance(wert, dict) and bool(wert)
        and all(REGELFRAGE.match(k) and isinstance(v, dict)
                and v and all(VARIANTE.match(x) for x in v)
                for k, v in wert.items())
    )


@dataclass
class Bindung:
    """Noch mögliche Varianten je Regelfrage."""

    moeglich: dict[str, set[str]] = field(default_factory=dict)

    def kopie(self) -> Bindung:
        return Bindung({k: set(v) for k, v in self.moeglich.items()})

    def erlaubt(self, regelfrage: str, variante: str) -> bool:
        offen = self.moeglich.get(regelfrage)
        # Unbekannte Regelfrage oder ohne gesammelte Varianten: offen.
        return not offen or variante in offen

    def einschraenken(self, regelfrage: str, varianten: set[str]) -> None:
        bisher = self.moeglich.get(regelfrage) or set(varianten)
        self.moeglich[regelfrage] = bisher & varianten

    def gewaehlt(self, regelfrage: str) -> str | None:
        """Die eine verbliebene Variante oder None."""
        offen = self.moeglich.get(regelfrage) or set()
        return next(iter(offen)) if len(offen) == 1 else None

    def __str__(self) -> str:
        return ', '.join(f'{k}: {"/".join(sorted(v)) or "-"}'
                         for k, v in sorted(self.moeglich.items()))


def varianten_sammeln(daten, gefunden: dict[str, set[str]]) -> None:
    """Sammelt alle Regelfragen und Varianten, die in Variantentabellen
    vorkommen, rekursiv über den ganzen Fall."""
    if ist_variantentabelle(daten):
        for frage, tabelle in daten.items():
            gefunden.setdefault(frage, set()).update(tabelle)
            for wert in tabelle.values():
                varianten_sammeln(wert, gefunden)
    elif isinstance(daten, dict):
        for wert in daten.values():
            varianten_sammeln(wert, gefunden)
    elif isinstance(daten, list):
        for wert in daten:
            varianten_sammeln(wert, gefunden)


@dataclass
class Vergleich:
    """Ergebnis eines Soll-Ist-Vergleichs.

    ``passt``: True, False oder None (kein Sollwert in den noch möglichen
    Varianten, nur Prüfpunkte).
    """

    passt: bool | None
    soll: str


def vergleichen(soll, ist: Decimal, bindung: Bindung) -> Vergleich:
    """Vergleicht und schränkt ``bindung`` ein.

    Fester Betrag: muss gleich sein. Variantentabelle: der Istwert muss
    einer noch möglichen Variante entsprechen; die passenden bleiben
    möglich. Varianten ohne Wert für den Istwert gelten weiter als möglich,
    weil der Fall dort nichts festlegt.
    """
    if not ist_variantentabelle(soll):
        wert = betrag(soll)
        return Vergleich(ist == wert, f'{wert}')

    # Eine Regelfrage je Tabelle; mehrere wären mehrdeutig.
    (frage, tabelle), = soll.items()
    passend, beschreibung = set(), []
    for variante, wert in sorted(tabelle.items()):
        if not bindung.erlaubt(frage, variante):
            continue
        if isinstance(wert, str) and not _ist_betrag(wert):
            continue
        teil = vergleichen(wert, ist, bindung.kopie())
        beschreibung.append(f'{frage}.{variante} = {teil.soll}')
        if teil.passt:
            passend.add(variante)
    if not beschreibung:
        return Vergleich(None, f'{frage}: keine Variante mit Wert')
    if passend:
        bindung.einschraenken(frage, passend)
    return Vergleich(bool(passend), '; '.join(beschreibung))


def aufloesen(wert, bindung: Bindung):
    """Eingabewert eines Schritts für die gewählte Variante.

    Ist die Variante noch offen und unterscheiden sich die Werte, ist der
    Schritt nicht eindeutig ausführbar: ``ValueError``.
    """
    if not ist_variantentabelle(wert):
        return wert
    (frage, tabelle), = wert.items()
    kandidaten = {v: w for v, w in tabelle.items()
                  if bindung.erlaubt(frage, v)}
    werte = {repr(w) for w in kandidaten.values()}
    if len(werte) == 1:
        return aufloesen(next(iter(kandidaten.values())), bindung)
    raise ValueError(
        f'Eingabe hängt von {frage} ab, Variante noch offen: {kandidaten}')


def _ist_betrag(text: str) -> bool:
    try:
        Decimal(text)
    except InvalidOperation:
        return False
    return True


@dataclass
class Fall:
    """Ein eingelesener Fall."""

    pfad: Path
    daten: dict

    @classmethod
    def lesen(cls, pfad: Path) -> Fall:
        with pfad.open('rb') as datei:
            daten = tomllib.load(datei)
        fall = cls(pfad, daten)
        fall.schema_pruefen()
        return fall

    @property
    def nummer(self) -> str:
        return self.daten['fall']['nummer']

    @property
    def titel(self) -> str:
        return self.daten['fall']['titel']

    @property
    def steuersatz(self) -> str:
        return self.daten['fall']['steuersatz']

    @property
    def schritte(self) -> list[dict]:
        return self.daten.get('schritt', [])

    @property
    def pruefpunkte(self) -> list[dict]:
        return self.daten.get('pruefpunkt', [])

    def liste(self, name: str) -> list[dict]:
        return self.daten.get(name, [])

    def bindung(self) -> Bindung:
        gefunden: dict[str, set[str]] = {}
        varianten_sammeln(self.daten, gefunden)
        for frage in self.daten['fall'].get('regelfragen', {}):
            gefunden.setdefault(frage, set())
        return Bindung(gefunden)

    def schema_pruefen(self) -> None:
        """Bricht bei einem Fehler in der Datenform ab, bevor ein Lauf ihn
        als Befund an Paper-Werk meldet."""
        fehler = []
        if not {'nummer', 'titel', 'steuersatz'} <= set(self.daten.get('fall', {})):
            fehler.append('[fall] braucht nummer, titel, steuersatz')
        nummern = [s.get('nr') for s in self.schritte]
        if nummern != sorted(nummern) or len(set(nummern)) != len(nummern):
            fehler.append(f'Schrittnummern nicht aufsteigend: {nummern}')
        for schritt in self.schritte:
            for pflicht in ('nr', 'datum', 'aktion'):
                if pflicht not in schritt:
                    fehler.append(f'Schritt {schritt.get("nr")}: {pflicht} fehlt')
        for liste in ('leistung', 'stundensatz', 'fremdleistung'):
            kennungen = [e['kennung'] for e in self.liste(liste)]
            if len(set(kennungen)) != len(kennungen):
                fehler.append(f'[[{liste}]]: Kennung doppelt')
        if fehler:
            raise ValueError(f'{self.pfad.name}: ' + '; '.join(fehler))
