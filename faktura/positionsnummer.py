"""Positionsnummern als Text: sortieren und weiterzählen.

Die Positionsnummer ist freier Text: "10", "15" zum Einfügen oder eine
Ordnungszahl aus dem Leistungsverzeichnis wie "01.01.0010". Weil Text "9"
nach "10" sortiert, hat jede Position einen Sortierschlüssel, in dem jede
Ziffernfolge auf zehn Stellen aufgefüllt ist; danach sortiert die
Datenbank.

Dieselbe Regel zum Weiterzählen gilt für im Browser angefügte Zeilen in
``faktura/static/faktura/js/positionsnummer.js``.
"""

import re

#: Stellenzahl, auf die Ziffernfolgen im Sortierschlüssel aufgefüllt
#: werden.
STELLEN = 10

_ZIFFERN = re.compile(r'\d+')
_LETZTE_ZIFFERN = re.compile(r'(\d+)(\D*)$')


def sortierschluessel(nummer) -> str:
    """Sortierschlüssel: "9" ergibt "0000000009", "01.01.0010" ergibt
    "0000000001.0000000001.0000000010".

    In Kleinbuchstaben, damit "3A" und "3a" nebeneinander stehen."""
    return _ZIFFERN.sub(lambda m: m.group().zfill(STELLEN),
                        str(nummer).strip().lower())


def naechste(vorige: str) -> str:
    """Nummer nach ``vorige``: die letzte Ziffernfolge inkrementiert, in
    derselben Breite; um 10, wenn sie auf 0 endet, sonst um 1.

    "30" ergibt "40", "15" ergibt "16", "01.01.0010" ergibt "01.01.0020",
    "01.09" ergibt "01.10". Ohne Ziffern leer; dann vergibt der Aufrufer.
    """
    treffer = _LETZTE_ZIFFERN.search(vorige.strip())
    if not treffer:
        return ''
    ziffern = treffer.group(1)
    schritt = 10 if ziffern.endswith('0') else 1
    neu = str(int(ziffern) + schritt).zfill(len(ziffern))
    return vorige.strip()[:treffer.start(1)] + neu + treffer.group(2)


def naechste_nummern(vergeben, anzahl: int) -> list[str]:
    """Die nächsten ``anzahl`` Nummern nach der höchsten vergebenen.

    Ohne vergebene Nummern 10, 20, 30. Bei ganzen Zahlen Zehnerschritte,
    solange alle Vielfache von 10 sind, sonst Einerschritte (nach 10, 15
    folgt 16). Nummern ohne Ziffern am Ende ("Zulage") werden übergangen;
    gezählt wird ab der höchsten mit Ziffern. Nie eine vergebene Nummer.
    """
    vergeben = [str(n).strip() for n in vergeben if str(n).strip()]
    belegt = {sortierschluessel(n) for n in vergeben}

    if all(n.isdigit() for n in vergeben):
        schritt = 10 if all(int(n) % 10 == 0 for n in vergeben) else 1
        groesste = max((int(n) for n in vergeben), default=0)
        kandidaten = (str(groesste + schritt * i) for i in range(1, 10_000))
    else:
        zaehlbar = [n for n in vergeben if naechste(n)]
        letzte = max(zaehlbar, key=sortierschluessel, default='0')
        kandidaten = _reihe(letzte)

    ergebnis = []
    for kandidat in kandidaten:
        if len(ergebnis) == anzahl:
            break
        if sortierschluessel(kandidat) not in belegt:
            ergebnis.append(kandidat)
            belegt.add(sortierschluessel(kandidat))
    return ergebnis


def _reihe(start: str):
    nummer = start
    while True:
        nummer = naechste(nummer)
        yield nummer
