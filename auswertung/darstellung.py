"""Gemeinsame Darstellungen mehrerer Seiten: Monatsverlauf, Spitzenmonat,
Deckungsbeitragsstaffel.

Berechnet werden nur Balkenbreiten und Beschriftungen, keine Kennzahlen.
"""

from decimal import ROUND_CEILING, Decimal

from django.utils.formats import number_format

from faktura import formate


def spitzenmonat(verlauf, wert, anzeige) -> str:
    """Stärkster Monat als Text, etwa "Januar 2026 mit 110.290,00 €".

    Bei zwölf schmalen Säulen ist der Monat nicht ablesbar. Leer, solange
    kein Monat über null liegt.
    """
    if not verlauf:
        return ''
    spitze = max(verlauf, key=wert)
    if wert(spitze) <= 0:
        return ''
    return f'{formate.monat(spitze.jahr, spitze.monat)} mit {anzeige(wert(spitze))}'


def saeulen(verlauf, wert, anzeige, achse) -> dict:
    """Monatsverlauf als Säulen in HTML für Startseite und Projektakte.

    Eine Tabelle mit Höhen in Prozent, wie die Staffel unten; lesbar ohne
    JavaScript und mit deutschen Zahlenformaten. Verworfen: Unfolds
    Chart.js-Diagramm, weil Unfolds app.js die Achse fest als
    ``${value} €`` ohne Tausenderpunkt beschriftet und das nicht
    konfigurierbar ist.

    ``wert`` liest den Wert eines Monats, ``anzeige`` formatiert ihn für
    Tooltip und Spitzenwert, ``achse`` beschriftet einen Achsenschritt.
    Berechnet werden die Obergrenze der Achse (ein runder Wert über dem
    höchsten Monat) und die Höhe jeder Säule.
    """
    werte = [Decimal(str(wert(m))) for m in verlauf]
    hoechster = max(werte, default=0)
    schritt = _runder_schritt(hoechster / 3) if hoechster > 0 else 1
    # Explizit aufrunden: ``-(-a // b)`` rundet bei Decimal zur Null hin und
    # ergab 20.000 für einen Monat mit 29.899.
    oben = schritt * max(1, (hoechster / schritt).to_integral_value(ROUND_CEILING))
    spitze = werte.index(hoechster) if hoechster > 0 else None

    def hoehe(zahl) -> str:
        """Höhe 0 bis 100 mit Dezimalpunkt für das style-Attribut."""
        return f'{max(0, min(100, float(zahl) / float(oben) * 100)):.1f}'

    return {
        'achse': [{'text': achse(schritt * i), 'hoehe': hoehe(schritt * i)}
                  for i in range(int(oben // schritt) + 1)],
        'saeulen': [{
            'monat': m.beschriftung,
            # Zweistellige Jahreszahl ("11/25"), weil sich die Beschriftungen
            # unter zwölf schmalen Säulen sonst berühren.
            'kurz': f'{m.beschriftung[:3]}{m.beschriftung[-2:]}',
            'hoehe': hoehe(w),
            'text': anzeige(w),
            'spitze': i == spitze,
        } for i, (m, w) in enumerate(zip(verlauf, werte, strict=True))],
    }


def euro_glatt(wert) -> str:
    """Betrag ohne Nachkommastellen ("20.000 €") für Achsenschritte."""
    return f'{number_format(wert, decimal_pos=0, force_grouping=True)} €'


def _runder_schritt(roh) -> Decimal:
    """Kleinster runder Achsenschritt ab ``roh``: 1, 2, 2,5 oder 5 mal einer
    Zehnerpotenz. 9.966 wird 10.000, 3,2 wird 5."""
    roh = Decimal(str(roh))
    potenz = Decimal(1)
    while potenz * 10 <= roh:
        potenz *= 10
    while potenz > roh and potenz > Decimal('0.001'):
        potenz /= 10
    for faktor in (1, 2, Decimal('2.5'), 5, 10):
        if potenz * faktor >= roh:
            return potenz * faktor
    return potenz * 10


def wasserfall(staffel) -> list[dict]:
    """Deckungsbeitragsstaffel als Tabelle mit Balken für Projektakte und
    Controlling-Seite.

    Jede Stufe erhält Startpunkt und Breite in Prozent; der Abzug beginnt,
    wo der Rest endet. Verworfen: ein Wasserfall in Chart.js (gestapelter
    Balken mit unsichtbarem Sockel), weil er bei negativen Werten falsch
    zeichnet.
    """
    # Bezugswert ist der größere Wert, damit die Staffel auch erscheint, wenn
    # gearbeitet, aber noch nichts berechnet wurde.
    bezug = max(staffel.leistungswert,
                staffel.fremdkosten + staffel.personalkosten)
    if bezug <= 0:
        return []

    def anteil(betrag) -> str:
        """Anteil 0 bis 100 als String mit Dezimalpunkt.

        Das Template formatierte einen float lokalisiert als "12,5", und
        ``left: 12,5%`` ist kein gültiges CSS.
        """
        begrenzt = min(Decimal('100'), max(
            Decimal('0'), abs(betrag) / bezug * 100))
        return f'{begrenzt:.1f}'

    return [
        {
            'titel': stufe['titel'],
            'betrag': stufe['betrag'],
            'art': stufe['art'],
            'start': anteil(stufe['sockel']),
            'breite': anteil(stufe['betrag']),
            'farbe': _stufenfarbe(stufe),
        }
        for stufe in staffel.stufen
    ]


def _stufenfarbe(stufe) -> str:
    """Farbe einer Stufe: Abzüge in der Farbe ihrer Kostenart, Rot nur bei
    negativem Rest."""
    if stufe['betrag'] < 0 and stufe['art'] == 'abzug':
        return ('var(--pw-reihe-2)' if stufe['titel'] == 'Zugekauft'
                else 'var(--pw-reihe-1)')
    if stufe['art'] == 'ergebnis':
        return ('var(--pw-reihe-3)' if stufe['betrag'] > 0
                else 'var(--pw-warnung)')
    if stufe['art'] == 'zwischensumme':
        return 'var(--pw-reihe-3)'
    return 'var(--pw-gedaempft)'
