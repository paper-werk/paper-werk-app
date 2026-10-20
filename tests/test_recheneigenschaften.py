"""Property-based Tests (Hypothesis) der Rechenregeln.

``test_controlling.py`` und ``test_auswertung.py`` prüfen Beispiele mit
Sollwerten (120 Stunden zu 89,50 EUR ergeben 10.740). Hier stehen Regeln
für alle Werte: "Der Auftragsbestand ist nie negativ", "netto plus Steuer
ergibt brutto", "die aufgerundete Zeit liegt nie unter der geleisteten".
Hypothesis erzeugt Werte über den ganzen Bereich (null, negativ, drei
Nachkommastellen, sehr groß) und meldet das kleinste Gegenbeispiel.

Ohne Datenbank: geprüft werden die Dataclasses aus ``auswertung.py`` und
``controlling.py`` und die Berechnungsfunktionen, die dafür ohne Projekt
befüllbar sind. Abgleiche gegen die Datenbank stehen in
``test_rechenabgleich.py``.

**Die Nummern R-xxx** verweisen auf ``docs/rechenregister.md``.
Dort steht zu jedem Wert, wo er berechnet und angezeigt wird.
"""

from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace

import pytest
from hypothesis import assume, example, given
from hypothesis import strategies as st

from auswertung.controlling import (
    Deckungsbeitrag,
    Kundenstruktur,
    Reichweite,
    Stundenertrag,
    kundenstruktur,
)
from auswertung.ergebnisse import Projektergebnis
from erfassung.services import Abrechnungsposition, aufgerundete_stunden
from faktura.services import Kundenumsatz, Projektstand, positionssumme

CENT = Decimal('0.01')


# ══════════════════════════════════════════════════════════════════════════
# Wertebereiche
# ══════════════════════════════════════════════════════════════════════════
#
# Weit gefasst in beide Richtungen, weil Stornopositionen negative Beträge
# haben. Die Obergrenzen entsprechen den Feldern: menge decimal(10,3),
# einzelpreis decimal(12,2).

GELD = st.decimals(min_value=Decimal('-999999.99'), max_value=Decimal('999999.99'),
                   places=2, allow_nan=False, allow_infinity=False)
GELD_POSITIV = st.decimals(min_value=Decimal('0'), max_value=Decimal('999999.99'),
                           places=2, allow_nan=False, allow_infinity=False)
MENGE = st.decimals(min_value=Decimal('-9999.999'), max_value=Decimal('9999.999'),
                    places=3, allow_nan=False, allow_infinity=False)
PREIS = st.decimals(min_value=Decimal('-99999.99'), max_value=Decimal('99999.99'),
                    places=2, allow_nan=False, allow_infinity=False)
#: Beträge ohne gültigen Nenner, für "ohne Auftrag", "ohne Stunden",
#: "ohne Umsatz". Als eigene Strategie, weil ``assume`` fast alle
#: erzeugten Werte verwürfe.
GELD_OHNE_WERT = st.decimals(min_value=Decimal('-999999.99'), max_value=Decimal('0'),
                             places=2, allow_nan=False, allow_infinity=False)
MINUTEN = st.integers(min_value=0, max_value=500_000)


def stand(*, beauftragt=Decimal('0.00'), fakturiert=Decimal('0.00'),
          angeboten=Decimal('0.00'), abgerechnet=Decimal('0.00')):
    """Projektstand ohne Projekt.

    ``projekt`` bleibt None, weil es nur für Sortierung und Anzeige dient
    und ein angelegtes Projekt eine Datenbank verlangte.
    """
    return Projektstand(projekt=None, angeboten=angeboten,
                        beauftragt=beauftragt, fakturiert=fakturiert,
                        abgerechnete_leistung=abgerechnet)


def ergebnis(*, beauftragt=Decimal('0.00'), abgerechnet=Decimal('0.00'),
             offene_leistung=Decimal('0.00'),
             offene_fremdleistung=Decimal('0.00'),
             personalkosten=Decimal('0.00'), fremdkosten=Decimal('0.00')):
    """Projektergebnis aus Zahlen."""
    return Projektergebnis(
        stand=stand(beauftragt=beauftragt, fakturiert=abgerechnet,
                    abgerechnet=abgerechnet),
        offene_leistung=offene_leistung,
        offene_fremdleistung=offene_fremdleistung,
        personalkosten=personalkosten,
        fremdkosten=fremdkosten,
    )


# ══════════════════════════════════════════════════════════════════════════
# R-001: Positionsnetto
# ══════════════════════════════════════════════════════════════════════════
#
# Grundlage aller Summen.


class TestDasPositionsnetto:

    @given(menge=MENGE, preis=PREIS)
    def test_hat_immer_genau_zwei_nachkommastellen(self, menge, preis):
        """Immer genau zwei Nachkommastellen.

        ``as_tuple().exponent`` ist -2 bei Quantisierung auf Cent, auch bei
        runden Beträgen, bei denen ``normalize()`` die Nullen entfernte.
        """
        assert positionssumme(menge=menge, einzelpreis=preis).as_tuple().exponent == -2

    @given(menge=MENGE, preis=PREIS)
    def test_weicht_nie_um_mehr_als_einen_halben_cent_ab(self, menge, preis):
        """Abweichung vom exakten Wert höchstens ein halber Cent."""
        exakt = menge * preis
        assert abs(positionssumme(menge=menge, einzelpreis=preis) - exakt) <= Decimal('0.005')

    @given(menge=MENGE, preis=PREIS)
    def test_kehrt_sich_mit_dem_vorzeichen_um(self, menge, preis):
        """Mit umgekehrtem Vorzeichen ergibt sich der negierte Betrag auf den
        Cent.

        Voraussetzung dafür, dass ein Storno die Rechnung genau aufhebt;
        Runden der Hälfte nach oben ergäbe bei negativen Beträgen einen
        anderen Cent.
        """
        assert (positionssumme(menge=-menge, einzelpreis=preis)
                == -positionssumme(menge=menge, einzelpreis=preis))

    @given(menge=MENGE, preis=PREIS)
    @example(menge=Decimal('0.25'), preis=Decimal('78.50'))
    @example(menge=Decimal('0.75'), preis=Decimal('89.50'))
    def test_rundet_die_haelfte_von_der_null_weg(self, menge, preis):
        """Kaufmännische Rundung, die Hälfte von der Null weg.

        Python rundet ohne Modus zum geraden Nachbarn (``ROUND_HALF_EVEN``):
        0,125 EUR ergäbe 0,12, auf der Rechnung 0,13.

        Die beiden ``@example`` sind die Fälle aus dem Rechenregister (Regeln
        für Änderungen), eine Viertelstunde zu einem Satz mit halben Euro,
        weil Hypothesis sie nicht zuverlässig erzeugt.
        """
        assert (positionssumme(menge=menge, einzelpreis=preis)
                == (menge * preis).quantize(CENT, rounding=ROUND_HALF_UP))


# ══════════════════════════════════════════════════════════════════════════
# R-037: Aufrundung auf die Viertelstunde
# ══════════════════════════════════════════════════════════════════════════


class TestDieAufgerundeteZeit:

    @given(minuten=MINUTEN)
    def test_liegt_nie_unter_der_geleisteten_zeit(self, minuten):
        """Nie unter der geleisteten Zeit."""
        assert aufgerundete_stunden(minuten) >= Decimal(minuten) / 60

    @given(minuten=MINUTEN)
    def test_liegt_nie_mehr_als_eine_viertelstunde_darueber(self, minuten):
        """Höchstens eine Viertelstunde über der geleisteten Zeit.

        Ohne diese Regel bestünde auch eine Aufrundung auf volle Stunden.
        """
        assert aufgerundete_stunden(minuten) - Decimal(minuten) / 60 < Decimal('0.25')

    @given(minuten=MINUTEN)
    def test_ist_immer_ein_viertel(self, minuten):
        """Immer ein Vielfaches von 0,25."""
        assert aufgerundete_stunden(minuten) % Decimal('0.25') == 0

    @given(a=MINUTEN, b=MINUTEN)
    def test_waechst_mit_der_zeit(self, a, b):
        """Monoton: Mehr Minuten ergeben nie weniger Stunden.

        Geprüft, weil ganzzahlige Division mit negativen Zahlen abweicht.
        """
        assume(a <= b)
        assert aufgerundete_stunden(a) <= aufgerundete_stunden(b)


# ══════════════════════════════════════════════════════════════════════════
# R-025, R-026: Belegstand eines Projekts
# ══════════════════════════════════════════════════════════════════════════


class TestDerProjektstand:

    @given(beauftragt=GELD, fakturiert=GELD)
    def test_der_auftragsbestand_ist_nie_negativ(self, beauftragt, fakturiert):
        """Der Auftragsbestand ist nie negativ.

        Bei Berechnung über das Beauftragte verringerte ein negativer Wert
        in der Gesamtsumme die Bestände anderer Projekte.
        """
        assert stand(beauftragt=beauftragt, fakturiert=fakturiert).offen >= 0

    @given(beauftragt=GELD, fakturiert=GELD)
    def test_der_fortschritt_bleibt_zwischen_null_und_hundert(
            self, beauftragt, fakturiert):
        """Der Fortschritt liegt zwischen 0 und 100, anders als die
        Ausschöpfung (R-077), weil er als Balkenbreite dient."""
        assert 0 <= stand(beauftragt=beauftragt, fakturiert=fakturiert).fortschritt <= 100

    @given(beauftragt=GELD_OHNE_WERT, fakturiert=GELD)
    def test_ohne_auftrag_gibt_es_keinen_fortschritt(self, beauftragt, fakturiert):
        """Ohne Auftrag kein Fortschritt (None), und der Balken entfällt.

        Mit eigener Strategie, weil ``assume`` fast alle erzeugten Werte
        verwürfe und Hypothesis die Strategie als fehlerhaft meldete.
        """
        assert stand(beauftragt=beauftragt, fakturiert=fakturiert).fortschritt == 0


# ══════════════════════════════════════════════════════════════════════════
# R-071 bis R-079: Ergebnis eines Projekts
# ══════════════════════════════════════════════════════════════════════════


class TestDasProjektergebnis:

    @given(abgerechnet=GELD, eigene=GELD, fremde=GELD)
    def test_der_leistungswert_ist_die_summe_seiner_drei_teile(
            self, abgerechnet, eigene, fremde):
        """Leistungswert gleich abgerechnete plus offene Leistung.

        Ohne Abschläge (R-024). Regression: Ein Abschlag erhöhte den
        Leistungswert, ohne die offene Leistung zu mindern.
        """
        e = ergebnis(abgerechnet=abgerechnet, offene_leistung=eigene,
                     offene_fremdleistung=fremde)
        assert e.leistungswert == abgerechnet + eigene + fremde

    @given(abgerechnet=GELD, eigene=GELD, personal=GELD, fremd=GELD)
    def test_das_ergebnis_ist_leistungswert_minus_beider_kosten(
            self, abgerechnet, eigene, personal, fremd):
        e = ergebnis(abgerechnet=abgerechnet, offene_leistung=eigene,
                     personalkosten=personal, fremdkosten=fremd)
        assert e.ergebnis == e.leistungswert - personal - fremd

    @given(beauftragt=GELD, abgerechnet=GELD, eigene=GELD)
    def test_die_ueberschreitung_ist_nie_negativ(self, beauftragt, abgerechnet, eigene):
        """Die Überschreitung ist nie negativ; weniger Leistung als beauftragt
        ergibt 0."""
        assert ergebnis(beauftragt=beauftragt, abgerechnet=abgerechnet,
                        offene_leistung=eigene).ueberschreitung >= 0

    @given(beauftragt=GELD, abgerechnet=GELD, eigene=GELD)
    def test_ueberzogen_heisst_ueberschreitung(self, beauftragt, abgerechnet, eigene):
        """``ueberzogen`` ist genau dann wahr, wenn eine Überschreitung
        besteht, damit Karte und Balkenfarbe übereinstimmen."""
        e = ergebnis(beauftragt=beauftragt, abgerechnet=abgerechnet,
                     offene_leistung=eigene)
        assert e.ist_ueberzogen == (e.ueberschreitung > 0)

    @given(abgerechnet=GELD, eigene=GELD, personal=GELD)
    def test_die_marge_ist_unbestimmt_ohne_leistungswert(
            self, abgerechnet, eigene, personal):
        """Ohne Leistungswert ist die Marge None, nicht 0."""
        e = ergebnis(abgerechnet=abgerechnet, offene_leistung=eigene,
                     personalkosten=personal)
        assert (e.marge is None) == (e.leistungswert <= 0)

    @given(beauftragt=GELD, abgerechnet=GELD, eigene=GELD)
    def test_die_ausschoepfung_ist_unbestimmt_ohne_auftrag(
            self, beauftragt, abgerechnet, eigene):
        """R-077: Ohne Auftrag ist die Ausschöpfung None."""
        e = ergebnis(beauftragt=beauftragt, abgerechnet=abgerechnet,
                     offene_leistung=eigene)
        assert (e.ausschoepfung is None) == (e.beauftragt <= 0)

    @given(beauftragt=GELD_POSITIV, abgerechnet=GELD_POSITIV, eigene=GELD_POSITIV)
    def test_die_ausschoepfung_ist_ausdruecklich_nicht_gedeckelt(
            self, beauftragt, abgerechnet, eigene):
        """Die Ausschöpfung ist nicht auf 100 begrenzt.

        Werte über 100 % sind die Aussage der Kennzahl; die Begrenzung als
        Balkenbreite erfolgt in der Anzeige (R-116).

        Geprüft an der Formel, nicht an "größer als 100", weil 1,02 EUR
        Leistung auf 1,01 EUR Auftrag 100,99 % ergeben.
        """
        assume(beauftragt > 0)
        e = ergebnis(beauftragt=beauftragt, abgerechnet=abgerechnet,
                     offene_leistung=eigene)
        assert e.ausschoepfung == int(e.leistungswert / beauftragt * 100)

    @given(beauftragt=GELD_POSITIV, eigene=GELD_POSITIV)
    def test_die_ausschoepfung_steigt_ueber_hundert(self, beauftragt, eigene):
        """Doppelte Leistung ergibt 200 %."""
        assume(beauftragt > 0)
        e = ergebnis(beauftragt=beauftragt, offene_leistung=beauftragt * 2)
        assert e.ausschoepfung == 200

    @given(abgerechnet=GELD, personal=GELD)
    def test_traegt_heisst_ergebnis_nicht_negativ(self, abgerechnet, personal):
        e = ergebnis(abgerechnet=abgerechnet, personalkosten=personal)
        assert e.traegt == (e.ergebnis >= 0)


# ══════════════════════════════════════════════════════════════════════════
# R-091 bis R-094: Deckungsbeitragsstaffel
# ══════════════════════════════════════════════════════════════════════════


class TestDieDeckungsbeitragsstaffel:

    @given(wert=GELD, fremd=GELD, personal=GELD)
    def test_die_staffel_rechnet_von_oben_nach_unten_durch(self, wert, fremd, personal):
        db = Deckungsbeitrag(leistungswert=wert, fremdkosten=fremd,
                             personalkosten=personal)
        assert db.db1 == wert - fremd
        assert db.db2 == wert - fremd - personal

    @given(wert=GELD, fremd=GELD, personal=GELD)
    def test_der_wasserfall_geht_auf(self, wert, fremd, personal):
        """Jede Stufe des Wasserfalls folgt aus der vorigen.

        Leistungswert minus Zukauf ergibt DB I, DB I minus eigene Arbeit
        ergibt DB II.
        """
        stufen = Deckungsbeitrag(leistungswert=wert, fremdkosten=fremd,
                                 personalkosten=personal).stufen
        betraege = [s['betrag'] for s in stufen]
        assert betraege[0] + betraege[1] == betraege[2]
        assert betraege[2] + betraege[3] == betraege[4]

    @given(wert=GELD, fremd=GELD, personal=GELD)
    def test_die_abzuege_sind_negativ(self, wert, fremd, personal):
        """Abzüge sind negativ, damit sie im Diagramm nach unten zeigen."""
        stufen = Deckungsbeitrag(leistungswert=wert, fremdkosten=fremd,
                                 personalkosten=personal).stufen
        abzuege = [s for s in stufen if s['art'] == 'abzug']
        assert abzuege[0]['betrag'] == -fremd
        assert abzuege[1]['betrag'] == -personal

    @given(wert=GELD_OHNE_WERT, fremd=GELD, personal=GELD)
    def test_ohne_leistungswert_gibt_es_keine_quote(self, wert, fremd, personal):
        db = Deckungsbeitrag(leistungswert=wert, fremdkosten=fremd,
                             personalkosten=personal)
        assert db.db1_quote is None
        assert db.db2_quote is None


# ══════════════════════════════════════════════════════════════════════════
# R-087 bis R-090: Ertrag je Stunde
# ══════════════════════════════════════════════════════════════════════════


class TestDerStundenertrag:

    @given(leistung=GELD, stunden=GELD_OHNE_WERT, kosten=GELD)
    def test_ohne_stunden_ist_der_satz_unbestimmt(self, leistung, stunden, kosten):
        """Ohne Stunden ist der Satz None, nicht 0."""
        e = Stundenertrag(eigenleistung=leistung, stunden=stunden,
                          personalkosten=kosten)
        assert e.erloes_je_stunde is None
        assert e.kosten_je_stunde is None
        assert e.deckung_je_stunde is None

    @given(leistung=GELD, stunden=GELD_POSITIV, kosten=GELD)
    def test_die_deckung_ist_die_differenz_der_beiden_saetze(
            self, leistung, stunden, kosten):
        assume(stunden > 0)
        e = Stundenertrag(eigenleistung=leistung, stunden=stunden,
                          personalkosten=kosten)
        assert e.deckung_je_stunde == e.erloes_je_stunde - e.kosten_je_stunde

    @given(leistung=GELD, stunden=GELD_POSITIV, kosten=GELD)
    def test_der_faktor_braucht_lohnkosten(self, leistung, stunden, kosten):
        """Ohne Lohnkosten ist der Faktor None."""
        e = Stundenertrag(eigenleistung=leistung, stunden=stunden,
                          personalkosten=kosten)
        assert (e.faktor is None) == (kosten <= 0 or stunden <= 0)


# ══════════════════════════════════════════════════════════════════════════
# R-096: Auftragsreichweite
# ══════════════════════════════════════════════════════════════════════════


class TestDieReichweite:

    @given(bestand=GELD, leistung=GELD)
    def test_ohne_monatsleistung_gibt_es_keine_reichweite(self, bestand, leistung):
        """Ohne Monatsleistung ist die Reichweite None, nicht 0."""
        r = Reichweite(auftragsbestand=bestand, monatsleistung=leistung,
                       monate_grundlage=3)
        assert (r.monate is None) == (leistung <= 0)

    @given(bestand=GELD, leistung=GELD)
    def test_knapp_heisst_unter_einem_monat(self, bestand, leistung):
        """``knapp`` ist genau dann wahr, wenn die Reichweite unter einem Monat
        liegt."""
        r = Reichweite(auftragsbestand=bestand, monatsleistung=leistung,
                       monate_grundlage=3)
        assert r.ist_knapp == (r.monate is not None and r.monate < 1)


# ══════════════════════════════════════════════════════════════════════════
# R-098 bis R-101: Verteilung des Umsatzes auf Auftraggeber
# ══════════════════════════════════════════════════════════════════════════
#
# ``kundenstruktur`` liest die Datenbank über ``umsatz_je_kunde``; hier wird
# die Abfrage ersetzt, weil nur die Verteilung einer Liste von Umsätzen
# geprüft wird. Den Abgleich mit der Abfrage prüft test_rechenabgleich.py.


def _struktur(betraege) -> Kundenstruktur:
    """Kundenstruktur aus vorgegebenen Umsätzen, absteigend sortiert."""
    umsaetze = [
        Kundenumsatz(kunde=SimpleNamespace(__str__=lambda s, n=i: f'Kunde {n}'),
                     netto=betrag, belege=1)
        for i, betrag in enumerate(sorted(betraege, reverse=True))
    ]
    from unittest.mock import patch
    with patch('auswertung.controlling.faktura_services.umsatz_je_kunde',
               return_value=umsaetze):
        return kundenstruktur()


class TestDieKundenstruktur:

    @given(betraege=st.lists(GELD_POSITIV, min_size=1, max_size=12))
    def test_die_summenlinie_steigt(self, betraege):
        """Die Summenlinie der ABC-Analyse ist monoton steigend."""
        kumuliert = [z.kumuliert for z in _struktur(betraege).zeilen]
        assert kumuliert == sorted(kumuliert)

    @given(betraege=st.lists(GELD_POSITIV, min_size=1, max_size=12))
    def test_kein_anteil_liegt_ueber_hundert(self, betraege):
        struktur = _struktur(betraege)
        assert all(0 <= z.anteil <= 100 for z in struktur.zeilen)
        assert 0 <= struktur.anteil_top3 <= 100

    @given(betraege=st.lists(GELD_POSITIV, min_size=1, max_size=12))
    def test_die_gesamtsumme_ist_die_summe_der_kunden(self, betraege):
        struktur = _struktur(betraege)
        assert struktur.gesamt == sum(betraege)

    @given(betraege=st.lists(GELD_POSITIV, min_size=4, max_size=12))
    def test_der_groesste_steht_vorn(self, betraege):
        """Der größte Kunde steht vorn, weil die Reihenfolge das Klumpenrisiko
        zeigt."""
        struktur = _struktur(betraege)
        assume(struktur.gesamt > 0)
        assert struktur.groesster.netto == max(betraege)


# ══════════════════════════════════════════════════════════════════════════
# Rundung der Vorschau gegen Rundung der Rechnung
# ══════════════════════════════════════════════════════════════════════════


#: Stundensatz und Menge, bei denen zwei Rundungsverfahren abweichen.
#
# Satz mit halben Euro und Menge in Viertelstunden, der Regelfall bei
# Zeitleistungen; 13 von 30 geprüften Kombinationen weichen ab.
RUNDUNGSFAELLE = [
    (Decimal('0.25'), Decimal('78.50'), Decimal('19.63')),
    (Decimal('0.75'), Decimal('89.50'), Decimal('67.13')),
    (Decimal('1.25'), Decimal('110.50'), Decimal('138.13')),
    (Decimal('7.25'), Decimal('62.50'), Decimal('453.13')),
]


@pytest.mark.parametrize(('menge', 'preis', 'erwartet'), RUNDUNGSFAELLE)
def test_die_vorschau_rundet_wie_die_rechnung(menge, preis, erwartet):
    """Die Vorschau rundet wie die Rechnung.

    Aus ``Abrechnungsposition.summe`` entsteht "Erfasst, nicht berechnet"
    auf Startseite, Projektakte, Auftragsakte und Liegenliste; die Rechnung
    rechnet über ``positionssumme``. Regression: Die Vorschau wich ab, weil
    die Rundungsregel an mehreren Stellen stand. Sie steht jetzt nur in
    ``core/rechnen.py``.
    """
    position = Abrechnungsposition(
        grundlage=SimpleNamespace(einzelpreis=preis, bezeichnung='Leistung',
                                  einheit='Std', steuersatz='19'),
        zeilen=[], menge=menge, minuten=0)

    assert position.summe == erwartet
    assert position.summe == positionssumme(menge=menge, einzelpreis=preis)
