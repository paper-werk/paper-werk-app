"""Fachszenarien: Fälle mit unabhängig gerechneten Sollwerten durchspielen.

Je Falldatei ein Test. Er führt die Schritte über die Masken aus
(``aktionen``), vergleicht nach jedem Schritt die Sollwerte (``istwerte``)
und am Ende die Prüfpunkte (``pruefpunkte``).

Befunde:

* Fehler: Istwert entspricht keiner noch möglichen Variante, oder ein
  Prüfpunkt gilt nicht. Der Test schlägt fehl.
* Lücke: Paper-Werk kann den Schritt nicht abbilden. Ist der Schritt
  nicht ausführbar, endet der Fall dort; sonst läuft er weiter, und
  spätere Sollwertabweichungen heißen "Abweichung nach Lücke". Beides
  lässt den Test nicht fehlschlagen.
* Nicht geprüft: Sollwert oder Prüfpunkt, den der Treiber nicht auswertet.

Die Befundliste steht in der Ausgabe von pytest und mit
``PAPERWERK_FACHSZENARIEN_AUSGABE`` zusätzlich als Markdown-Datei.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from faktura.models import Beleg

from . import aktionen, istwerte, maske, pruefpunkte
from .fall import Fall, betrag, dateien, ist_variantentabelle, vergleichen

BEFUNDE: list[Befund] = []


@dataclass
class Befund:
    fall: str
    schritt: int | str
    klasse: str
    text: str

    def zeile(self) -> str:
        return f'| {self.fall} | {self.schritt} | {self.klasse} | {self.text} |'


def _vergleichen(lauf, befunde, schritt, beleg):
    for name, soll in schritt.get('soll', {}).items():
        grundname = name.removesuffix('_hoechstens')
        ermitteln = istwerte.ISTWERTE.get(grundname)
        if ermitteln is None:
            befunde.append(Befund(lauf.fall.nummer, schritt['nr'], 'nicht geprüft',
                                  f'Sollwert {name}'))
            continue
        try:
            ist = ermitteln(lauf, beleg, schritt)
        except (KeyError, AttributeError, Beleg.DoesNotExist) as fehler:
            befunde.append(Befund(lauf.fall.nummer, schritt['nr'], 'nicht geprüft',
                                  f'Sollwert {name}: {fehler!r}'))
            continue
        if grundname != name:
            if ist > betrag(soll):
                befunde.append(Befund(lauf.fall.nummer, schritt['nr'], 'Fehler',
                                      f'{name}: ist {ist}, höchstens {soll}'))
            continue
        if isinstance(ist, dict):
            # Je Kunde.
            for schluessel, teil in soll.items():
                _ein_vergleich(lauf, befunde, schritt, f'{name}[{schluessel}]',
                               teil, ist.get(schluessel))
        else:
            _ein_vergleich(lauf, befunde, schritt, name, soll, ist)


def _ein_vergleich(lauf, befunde, schritt, name, soll, ist):
    if not isinstance(soll, (str, dict)) or (isinstance(soll, dict)
                                             and not ist_variantentabelle(soll)):
        befunde.append(Befund(lauf.fall.nummer, schritt['nr'], 'nicht geprüft',
                              f'Sollwert {name}: Form {soll!r}'))
        return
    ergebnis = vergleichen(soll, ist, lauf.bindung)
    if ergebnis.passt is False:
        # Nach einer Lücke weicht der Fall vom Katalog ab, ohne dass
        # Paper-Werk falsch rechnet; Prüfpunkte bleiben Fehler.
        klasse = ('Abweichung nach Lücke'
                  if any(b.klasse == 'Lücke' for b in befunde) else 'Fehler')
        befunde.append(Befund(lauf.fall.nummer, schritt['nr'], klasse,
                              f'{name}: ist {ist}, soll {ergebnis.soll}'))


def _pruefen(lauf, befunde, tabelle, nr):
    for punkt in lauf.fall.pruefpunkte:
        regel = punkt['regel']
        if regel not in tabelle:
            continue
        try:
            gilt = tabelle[regel](lauf)
        except (KeyError, AttributeError, Beleg.DoesNotExist) as fehler:
            befunde.append(Befund(lauf.fall.nummer, nr, 'nicht geprüft',
                                  f'Prüfpunkt: {punkt["text"]} ({fehler!r})'))
            continue
        if not gilt:
            befunde.append(Befund(lauf.fall.nummer, nr, 'Fehler',
                                  f'Prüfpunkt: {punkt["text"]}'))


def _nicht_ausgewertet(lauf, befunde):
    bekannt = {**pruefpunkte.JE_SCHRITT, **pruefpunkte.AM_ENDE}
    for punkt in lauf.fall.pruefpunkte:
        if punkt['regel'] not in bekannt:
            befunde.append(Befund(lauf.fall.nummer, 'Ende', 'nicht geprüft',
                                  f'Prüfpunkt: {punkt["text"]}'))


@pytest.mark.django_db
@pytest.mark.parametrize('pfad', dateien(), ids=lambda p: p.stem)
def test_fall(pfad: Path, buero, uhr):
    fall = Fall.lesen(pfad)
    lauf = aktionen.Lauf(fall=fall, client=buero, uhr=uhr, bindung=fall.bindung())
    befunde: list[Befund] = []
    aktionen.einrichten(lauf)

    abgebrochen = False
    for schritt in fall.schritte:
        try:
            beleg = aktionen.ausfuehren(lauf, schritt)
        except aktionen.Luecke as luecke:
            befunde.append(Befund(fall.nummer, schritt['nr'], 'Lücke', str(luecke)))
            abgebrochen = True
            break
        except (maske.MaskeAbgelehnt, maske.FeldFehlt, ValueError) as fehler:
            befunde.append(Befund(fall.nummer, schritt['nr'], 'Lücke',
                                  f'{schritt["aktion"]}: {fehler}'))
            abgebrochen = True
            break
        befunde.extend(Befund(fall.nummer, schritt['nr'], 'Lücke', text)
                       for text in lauf.luecken)
        lauf.luecken.clear()
        _vergleichen(lauf, befunde, schritt, beleg)
        _pruefen(lauf, befunde, pruefpunkte.JE_SCHRITT, schritt['nr'])

    if not abgebrochen:
        _pruefen(lauf, befunde, pruefpunkte.AM_ENDE, 'Ende')
    _nicht_ausgewertet(lauf, befunde)
    befunde.append(Befund(fall.nummer, 'Ende', 'Varianten', str(lauf.bindung)))
    BEFUNDE.extend(befunde)
    _ausgeben(fall, befunde)

    fehler = [b for b in befunde if b.klasse == 'Fehler']
    assert not fehler, '\n'.join(b.zeile() for b in befunde)


def _ausgeben(fall, befunde):
    ziel = os.environ.get('PAPERWERK_FACHSZENARIEN_AUSGABE')
    text = '\n'.join([
        f'## Fall {fall.nummer}: {fall.titel}', '',
        '| Fall | Schritt | Klasse | Befund |', '|---|---|---|---|',
        *(b.zeile() for b in befunde), ''])
    print('\n' + text)
    if ziel:
        Path(ziel).mkdir(parents=True, exist_ok=True)
        (Path(ziel) / f'{fall.pfad.stem}.md').write_text(text, encoding='utf-8')
