"""Controlling-Seite.

Die Startseite zeigt den aktuellen Stand: fünf Zahlen, einen Verlauf, die
Projekte mit dem größten offenen Bestand. Die Controlling-Seite zeigt die
Entwicklung, etwa ob mehr Aufträge eingehen als abgearbeitet werden, wie
sich der Ertrag je Stunde entwickelt und wie stark der Betrieb von
einzelnen Auftraggebern abhängt.

Die Seite hat fünf Blöcke:

    Stundenertrag und Faktor
    Auftragseingang gegen Umsatz
    Landkarte der Projekte (Ausschöpfung gegen Marge)
    Altersstruktur der nicht abgerechneten Leistung
    Kundenstruktur und Auslastung

Das Modul rechnet nicht selbst. Alle Werte kommen aus einem Aufruf von
``controlling.lage()``; hier werden sie ausgewählt, geordnet und beschriftet,
wie in ``dashboard.py``.

Umgesetzt als eigene View, weil die Seite zu keinem Modell gehört.
"""

import json
from decimal import Decimal

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.urls import reverse

from faktura.formate import euro, faktor, geld, menge

from . import controlling, darstellung

NULL = Decimal('0.00')

#: Recht für die Auswertungen. Begründung an ``Beleg.Meta.permissions``:
#: ``view_rechnung`` erlaubt das Ansehen von Rechnungen und ist für
#: Auswertungen zu weit gefasst.
RECHT = 'faktura.controlling_ansehen'

#: Zusätzliches Recht für die Aufteilung der Zeit je Person.
#
# Umsatz, Auftragsbestand und Marge sind Betriebszahlen. Wie viel ein
# einzelner Mitarbeiter nicht abrechenbar gebucht hat, ist eine
# Leistungsbewertung und in einem Betrieb mit Betriebsrat
# mitbestimmungspflichtig. Verwendet wird das bestehende Recht
# ``view_kostensatz``, das nur "Leistungserfassung Leitung" hat.
RECHT_PERSONEN = 'erfassung.view_kostensatz'

#: Anzahl der einzeln aufgeführten Kunden; der Rest wird zusammengefasst.
#
# Acht Zeilen lassen sich auf einen Blick erfassen. Kleinere Kunden sind
# für die Frage der Abhängigkeit ohne Belang.
KUNDEN_EINZELN = 8

#: Höchstzahl der Projekte in der Landkarte.
#
# Mit mehr als dreißig Blasen ist das Streudiagramm nicht mehr lesbar.
# Ausgewählt wird nach Leistungswert.
PROJEKTE_IN_DER_KARTE = 30


def controllingseite(request):
    """Controlling-Seite, Recht ``faktura.controlling_ansehen``.

    Dasselbe Recht wie für die Zahlen der Startseite, weil die Seite
    Kostensätze, Margen und die Abhängigkeit von einzelnen Kunden zeigt.
    Ohne das Recht ist die ganze Seite gesperrt; Startseite und Projektakte
    zeigen dann einen Teil ohne Beträge, hier bestünde alles aus Beträgen.
    """
    if not request.user.has_perm(RECHT):
        raise PermissionDenied

    lage = controlling.lage()

    zusammenhang = {
        **admin.site.each_context(request),
        'title': 'Controlling',
        'hilfe_anker': 'controlling',
        'lage': lage,
        'kennzahlen': _kennzahlen(lage),
        'staffel': lage.deckungsbeitrag,
        'wasserfall': darstellung.wasserfall(lage.deckungsbeitrag),
        'verlauf_daten': _verlaufsdaten(lage),
        'karte_daten': _kartendaten(lage),
        'karte_optionen': _kartenoptionen(),
        'karte_zeilen': _kartenzeilen(lage),
        'altersklassen': _altersklassen(lage),
        'kunden': _kundenzeilen(lage),
        'auslastung': (_auslastungszeilen(lage)
                       if request.user.has_perm(RECHT_PERSONEN) else []),
        'projekte_url': reverse('admin:faktura_projekt_changelist'),
        'liegengeblieben_url': reverse('liegengeblieben'),
    }
    return render(request, 'admin/controlling.html', zusammenhang)


# ══════════════════════════════════════════════════════════════════════════
# Kennzahlen
# ══════════════════════════════════════════════════════════════════════════


def _kennzahlen(lage) -> list[dict]:
    """Vier Karten mit Verhältniszahlen.

    Fakturiert, Auftragsbestand und Ergebnis stehen auf der Startseite und
    werden hier nicht wiederholt.
    """
    ertrag = lage.stundenertrag
    karten = []

    if ertrag.erloes_je_stunde is not None:
        karten.append({
            'titel': 'Effektiver Stundensatz',
            'wert': euro(ertrag.erloes_je_stunde),
            'hinweis': _stundenhinweis(lage),
            'icon': 'speed',
        })

    karten.append({
        'titel': 'Auftragsreichweite',
        # menge() formatiert mit Dezimalkomma ("4,3").
        'wert': (f'{menge(lage.reichweite.monate)} Monate'
                 if lage.reichweite.monate is not None else 'kein Maßstab'),
        'hinweis': _reichweitenhinweis(lage.reichweite),
        'icon': 'schedule',
        'warnung': lage.reichweite.ist_knapp,
    })

    karten.append({
        'titel': 'Auftragseingang zu Umsatz',
        'wert': (f'{lage.eingang_gegen_umsatz} %'
                 if lage.eingang_gegen_umsatz is not None else 'kein Maßstab'),
        'hinweis': _richtungshinweis(lage),
        'icon': 'swap_vert',
    })

    quote = lage.deckungsbeitrag.db2_quote
    karten.append({
        'titel': 'Deckungsbeitrag II',
        'wert': f'{quote} %' if quote is not None else 'kein Maßstab',
        'hinweis': (f'{geld(lage.deckungsbeitrag.db2)} € nach Zukauf und '
                    f'eigener Arbeit. Miete, Geräte und Verwaltung sind '
                    f'darin noch nicht abgezogen.'),
        'icon': 'account_balance',
        'warnung': quote is not None and quote < 0,
    })
    return karten


def _stundenhinweis(lage) -> str:
    """Hinweis unter dem Stundensatz.

    Enthält den Vorbehalt, wenn Stunden ohne Kostensatz gebucht sind; der
    Faktor ist dann um deren Lohn zu hoch.
    """
    ertrag = lage.stundenertrag
    if ertrag.faktor is None:
        return (f'{menge(ertrag.stunden)} Std geleistet. Ohne Kostensätze lässt '
                f'sich kein Faktor bilden.')
    satz = (f'Faktor {faktor(ertrag.faktor)} auf {geld(ertrag.kosten_je_stunde)} € '
            f'Kostensatz.')
    if not lage.vollstaendig:
        zahl = len(lage.uebersicht.ohne_kostensatz)
        return (f'{satz} Zu hoch: {zahl} Person'
                f'{"" if zahl == 1 else "en"} ohne Kostensatz.')
    return f'{satz} Aus {menge(ertrag.stunden)} geleisteten Stunden.'


def _reichweitenhinweis(reichweite) -> str:
    if reichweite.monate is None:
        return ('Noch kein abgeschlossener Monat mit Umsatz; ohne Nenner '
                'gibt es keine Reichweite.')
    grundlage = (f'Bestand {geld(reichweite.auftragsbestand)} € gegen '
                 f'{geld(reichweite.monatsleistung)} € Monatsleistung '
                 f'(letzte {reichweite.monate_grundlage} Monate).')
    if reichweite.ist_knapp:
        return f'Unter einem Monat Vorlauf. {grundlage}'
    return grundlage


def _richtungshinweis(lage) -> str:
    """Book-to-Bill als Satz in Alltagssprache."""
    verhaeltnis = lage.eingang_gegen_umsatz
    if verhaeltnis is None:
        return 'Noch kein Umsatz im Zeitraum, kein Verhältnis zu bilden.'
    richtung = ('Es kommt mehr herein, als abgearbeitet wird.'
                if verhaeltnis >= 100
                else 'Der Betrieb lebt von seinem Polster.')
    return (f'{richtung} {geld(lage.auftragseingang_summe)} € neue Aufträge '
            f'gegen {geld(lage.umsatz_summe)} € Umsatz.')


# ══════════════════════════════════════════════════════════════════════════
# Auftragseingang gegen Umsatz
# ══════════════════════════════════════════════════════════════════════════


def _verlaufsdaten(lage) -> str:
    """Auftragseingang und Umsatz in einem Diagramm.

    Zwei Reihen mit zwei Achsen legen einen Zusammenhang nahe, den die
    Daten nicht enthalten. Beide Reihen haben hier dieselbe Einheit (Euro
    netto je Monat) und eine gemeinsame Achse; liegt der Eingang über dem
    Umsatz, wächst der Bestand.

    Auftragseingang als Balken, weil Aufträge einzeln eingehen; Umsatz als
    Linie, weil er laufend entsteht.
    """
    return json.dumps({
        'labels': [m.beschriftung for m in lage.umsatzverlauf],
        'datasets': [
            {
                'type': 'bar',
                'label': 'Auftragseingang',
                'data': [float(m.netto) for m in lage.auftragseingang],
                'backgroundColor': 'var(--pw-reihe-2)',
                'borderColor': 'var(--pw-reihe-2)',
                'borderRadius': 4,
                'order': 2,
            },
            {
                'type': 'line',
                'label': 'Fakturiert',
                'data': [float(m.netto) for m in lage.umsatzverlauf],
                'backgroundColor': 'var(--pw-reihe-1)',
                'borderColor': 'var(--pw-reihe-1)',
                'borderWidth': 2,
                'pointRadius': 0,
                'tension': 0.25,
                'order': 1,
                'displayYAxis': True,
                'suffixYAxis': '€',
            },
        ],
    })


# ══════════════════════════════════════════════════════════════════════════
# Landkarte der Projekte
# ══════════════════════════════════════════════════════════════════════════


def _kartendaten(lage) -> str | None:
    """Jedes Projekt als Blase: Ausschöpfung gegen Marge.

    Projekte rechts unten (viel geleistet, wenig verdient) sind mit ihrer
    Größe auf einen Blick erkennbar.

        waagerecht   Ausschöpfung: wie viel des Auftrags geleistet ist
        senkrecht    Marge: was davon übrig bleibt
        Größe        Leistungswert

    Zwei Farben: eine für Projekte über ihrem Auftragswert, eine für die
    übrigen. Eine Farbe je Projekt wäre ab wenigen Blasen nicht mehr zu
    unterscheiden.

    Den Tooltip setzt das Skript in
    ``auswertung/templates/admin/controlling.html``. Chart.js erwartet dafür
    eine Callback-Funktion, Unfold übergibt die Optionen aber als JSON
    (``JSON.parse``), das keine Funktionen enthalten kann. Der
    Standardtooltip zeigt ``(21, 35, 12.6999)``: zwei Achsenwerte und den
    Radius in Pixeln, ohne Projektnamen.

    ``None``, wenn kein Projekt einen Auftrag hat, weil dann die Werte der
    waagerechten Achse fehlen.
    """
    zeilen = [z for z in lage.uebersicht.zeilen
              if z.ausschoepfung is not None and z.marge is not None]
    if not zeilen:
        return None

    zeilen = sorted(zeilen, key=lambda z: -z.leistungswert)
    zeilen = zeilen[:PROJEKTE_IN_DER_KARTE]
    groesster = max((z.leistungswert for z in zeilen), default=NULL)

    def blase(zeile) -> dict:
        return {
            'x': min(200, zeile.ausschoepfung),
            'y': max(-100, min(100, zeile.marge)),
            # Radius proportional zur Wurzel des Werts, damit die Fläche
            # proportional zum Wert ist. Bei linearem Radius hätte der
            # doppelte Wert die vierfache Fläche.
            'r': float(_blasenradius(zeile.leistungswert, groesster)),
            # Inhalt des Tooltips, fertig formatiert, damit Tausenderpunkt
            # und Dezimalkomma nur in Python festgelegt sind.
            'nummer': zeile.projekt.nummer,
            'bezeichnung': zeile.projekt.bezeichnung,
            'kunde': str(zeile.projekt.kunde),
            'wert': euro(zeile.leistungswert),
            'ergebnis': euro(zeile.ergebnis),
        }

    traegt = [z for z in zeilen if not z.ist_ueberzogen]
    ueberzogen = [z for z in zeilen if z.ist_ueberzogen]

    datensaetze = []
    if traegt:
        datensaetze.append({
            'label': 'Im Rahmen',
            'data': [blase(z) for z in traegt],
            'backgroundColor': 'var(--pw-reihe-1)',
            'borderColor': 'var(--pw-reihe-1)',
        })
    if ueberzogen:
        datensaetze.append({
            'label': 'Über dem Auftrag',
            'data': [blase(z) for z in ueberzogen],
            'backgroundColor': 'var(--pw-warnung)',
            'borderColor': 'var(--pw-warnung)',
        })

    return json.dumps({'datasets': datensaetze})


def _blasenradius(wert: Decimal, groesster: Decimal) -> Decimal:
    """Radius zwischen 5 und 24 Pixeln, nach der Wurzel des Werts."""
    if groesster <= 0:
        return Decimal('8')
    anteil = max(Decimal('0'), wert) / groesster
    return Decimal('5') + Decimal(str(float(anteil) ** 0.5)) * Decimal('19')


def _kartenoptionen() -> str:
    """Achsen der Landkarte mit Beschriftung und Nulllinien.

    Eigene Optionen, weil Unfolds Vorgaben für Zeitreihen gedacht sind: Sie
    blenden die senkrechte Beschriftung aus, solange kein Datensatz
    ``displayYAxis`` setzt, und haben keine Prozentformatierung.
    """
    achse = {
        'ticks': {'color': '#9ca3af'},
        'grid': {'display': True, 'tickWidth': 0},
    }
    # ensure_ascii=False, damit Umlaute im Achsentitel im HTML lesbar
    # bleiben und nicht als \u-Escapes erscheinen.
    return json.dumps({
        'animation': False,
        'responsive': True,
        'maintainAspectRatio': False,
        'plugins': {
            'legend': {
                'display': True,
                'position': 'top',
                'align': 'end',
                'labels': {'boxHeight': 5, 'boxWidth': 5, 'color': '#9ca3af',
                           'pointStyle': 'circle', 'usePointStyle': True},
            },
        },
        'scales': {
            'x': {**achse, 'title': {'display': True, 'color': '#9ca3af',
                                     'text': 'Ausschöpfung des Auftrags in %'}},
            'y': {**achse, 'title': {'display': True, 'color': '#9ca3af',
                                     'text': 'Marge in %'}},
        },
    }, ensure_ascii=False)


def _kartenzeilen(lage) -> list[dict]:
    """Die Projekte der Landkarte als Tabelle.

    Für Barrierefreiheit, Ausdruck und das Ablesen einzelner Zahlen. Die
    Tabelle verlinkt außerdem auf die Projekte; die Blasen sind nicht
    anklickbar.
    """
    zeilen = sorted(
        (z for z in lage.uebersicht.zeilen),
        key=lambda z: (z.marge if z.marge is not None else 999,
                       z.projekt.nummer),
    )
    return [
        {
            'nummer': z.projekt.nummer,
            'bezeichnung': z.projekt.bezeichnung,
            'kunde': str(z.projekt.kunde),
            'url': reverse('projektakte', args=[z.projekt.pk]),
            'leistungswert': euro(z.leistungswert),
            'ergebnis': euro(z.ergebnis),
            'marge': '' if z.marge is None else f'{z.marge} %',
            'ausschoepfung': ('' if z.ausschoepfung is None
                              else f'{z.ausschoepfung} %'),
            'traegt': z.traegt,
            'ist_ueberzogen': z.ist_ueberzogen,
        }
        for z in zeilen
    ]


# ══════════════════════════════════════════════════════════════════════════
# Altersstruktur, Kunden, Auslastung
# ══════════════════════════════════════════════════════════════════════════


def _altersklassen(lage) -> list[dict]:
    """Nicht abgerechnete Leistung nach Alter.

    Ein Balken je Altersklasse in einer Farbe, mit dem Alter dunkler werdend,
    weil die Klassen geordnet sind. Verschiedene Farben legten
    unterschiedliche Kategorien nahe.
    """
    gesamt = lage.offene_leistung_gesamt
    stufen = ['bg-primary-300 dark:bg-primary-800',
              'bg-primary-400 dark:bg-primary-700',
              'bg-primary-500 dark:bg-primary-600',
              'bg-primary-700 dark:bg-primary-500']

    return [
        {
            'beschriftung': klasse.beschriftung,
            'betrag': euro(klasse.betrag),
            'anteil': (int(klasse.betrag / gesamt * 100) if gesamt > 0 else 0),
            'breite': (f'{min(Decimal("100"), klasse.betrag / gesamt * 100):.1f}'
                       if gesamt > 0 else '0.0'),
            'klasse': stufen[min(nummer, len(stufen) - 1)],
            # Die älteste Klasse wird hervorgehoben.
            'hervorgehoben': klasse.bis_tagen is None and klasse.betrag > 0,
        }
        for nummer, klasse in enumerate(lage.altersklassen)
    ]


def _kundenzeilen(lage) -> list[dict]:
    """Die größten Auftraggeber, der Rest in einer Sammelzeile.

    Die Sammelzeile sorgt dafür, dass sich die Anteile zu 100 Prozent
    addieren.
    """
    zeilen = lage.kunden.zeilen
    if not zeilen:
        return []

    kopf = zeilen[:KUNDEN_EINZELN]
    rest = zeilen[KUNDEN_EINZELN:]

    ausgabe = [
        {
            'name': z.name,
            'betrag': euro(z.netto),
            'anteil': z.anteil,
            'breite': f'{min(100, z.anteil):.1f}',
            'ist_klumpen': z.ist_klumpen,
            'ist_rest': False,
        }
        for z in kopf
    ]

    if rest:
        summe = sum((z.netto for z in rest), NULL)
        anteil = (int(summe / lage.kunden.gesamt * 100)
                  if lage.kunden.gesamt > 0 else 0)
        ausgabe.append({
            'name': f'{len(rest)} weitere',
            'betrag': euro(summe),
            'anteil': anteil,
            'breite': f'{min(100, anteil):.1f}',
            'ist_klumpen': False,
            'ist_rest': True,
        })
    return ausgabe


def _auslastungszeilen(lage) -> list[dict]:
    """Aufteilung der Zeit je Person als gestapelter Balken.

    Ein Balken mit drei Abschnitten, weil die Anteile an der Gesamtzeit
    gezeigt werden; die Länge des Balkens ist die Gesamtzeit.
    """
    zeilen = []
    for person in lage.auslastung:
        gesamt = person.minuten_gesamt or 1
        zeilen.append({
            'name': person.name,
            'stunden': person.stunden_gesamt,
            'quote': person.quote,
            'abschnitte': [
                {
                    'titel': 'Abgerechnet',
                    'breite': f'{person.minuten_abgerechnet / gesamt * 100:.1f}',
                    'farbe': 'var(--pw-reihe-1)',
                    'stunden': round(person.minuten_abgerechnet / 60, 1),
                },
                {
                    'titel': 'Offen',
                    'breite': f'{person.minuten_offen / gesamt * 100:.1f}',
                    'farbe': 'var(--pw-reihe-3)',
                    'stunden': round(person.minuten_offen / 60, 1),
                },
                {
                    'titel': 'Nicht abrechenbar',
                    'breite': (f'{person.minuten_nicht_abrechenbar / gesamt * 100:.1f}'),
                    'farbe': 'var(--pw-gedaempft)',
                    'stunden': round(person.minuten_nicht_abrechenbar / 60, 1),
                },
            ],
        })
    return zeilen
