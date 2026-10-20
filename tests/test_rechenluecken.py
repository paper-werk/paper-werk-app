"""Tests der Kennzahlen, die im Rechenregister ohne Test standen.

Das Rechenregister (`docs/rechenregister.md`) führt jeden angezeigten Wert
mit Prüfstatus. Die Tests hier decken die Einträge ohne Test ab, vor allem:

* **Umsatz je Kunde** (R-031/R-032), Grundlage von Kundenstruktur,
  Klumpenanteil und ABC-Analyse der Controlling-Seite.
* **Ältester offener Posten** (R-059), der Wert hinter "liegt seit 96
  Tagen" in der Liegenliste.

Dazu die Abschlagsnummer, "60 von 100 Std abgerechnet" an der
Auftragsposition und der Aufwand je Person in der Akte.
"""

from datetime import date, time, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from auswertung import controlling
from erfassung import services as erfassung_services
from erfassung.models import Eingangsrechnung, Fremdleistung
from faktura import formate
from faktura import services as faktura_services
from faktura.models import (
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Katalogposition,
    Kontakt,
    Leistungsart,
    Projekt,
    Rechnungsart,
)
from faktura.templatetags import faktura_extras

HEUTE = timezone.localdate()


@pytest.fixture
def kunde(db):
    return Kontakt.objects.create(nummer='K-6001', name='Stadtwerke Beispiel')


@pytest.fixture
def zweiter_kunde(db):
    return Kontakt.objects.create(nummer='K-6002', name='Landratsamt Beispiel')


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(
        nummer='2026-600', bezeichnung='Lückenvorhaben', kunde=kunde)


@pytest.fixture
def stunde(db):
    return Katalogposition.objects.create(
        bezeichnung='Ingenieurstunde', einheit='Std',
        einzelpreis=Decimal('90.00'), art=Leistungsart.ZEIT,
        steuersatz='19.00',
    )


@pytest.fixture
def anfahrt(db):
    return Katalogposition.objects.create(
        bezeichnung='Anfahrt', einheit='km',
        einzelpreis=Decimal('0.80'), art=Leistungsart.MENGE,
        steuersatz='19.00',
    )


@pytest.fixture
def person(django_user_model):
    return django_user_model.objects.create(
        username='l.ueckert', first_name='Lena', last_name='Ückert')


def rechnung(*, projekt=None, kunde=None, betrag, nummer,
             typ=BelegTyp.RECHNUNG, belegdatum=None,
             rechnungsart=Rechnungsart.NORMAL,
             status=BelegStatus.FESTGESCHRIEBEN, menge=Decimal('1'),
             einheit='pausch'):
    """Beleg mit einer Position."""
    beleg = Beleg.objects.create(typ=typ, projekt=projekt, kunde=kunde,
                                 empfaenger='Empfänger')
    if typ == BelegTyp.RECHNUNG:
        beleg.rechnungsart = rechnungsart
    Belegposition.objects.create(
        beleg=beleg, position=10, bezeichnung='Leistung', menge=menge,
        einheit=einheit, einzelpreis=Decimal(betrag),
        steuersatz=Decimal('19.00'))
    beleg.status = status
    if status != BelegStatus.ENTWURF:
        beleg.nummer = nummer
    beleg.belegdatum = belegdatum or HEUTE
    beleg.save()
    return beleg


def erfassen(projekt, leistung, person, *, minuten=0, menge=None, datum=None):
    ende = 8 * 60 + minuten
    return erfassung_services.zeile_erfassen(
        projekt=projekt, leistung=leistung, benutzer=person,
        beschreibung='', datum=datum or HEUTE,
        von=time(8, 0) if minuten else None,
        bis=time(ende // 60, ende % 60) if minuten else None,
        menge=menge,
    )


# ══════════════════════════════════════════════════════════════════════════
# R-031, R-032: Umsatz je Kunde
# ══════════════════════════════════════════════════════════════════════════


class TestDerUmsatzJeKunde:
    """Umsatz je Kunde, Grundlage der Kundenstruktur (R-098 bis R-101)."""

    def test_er_summiert_je_auftraggeber(self, projekt, kunde, zweiter_kunde):
        rechnung(projekt=projekt, betrag='10000.00', nummer='RE-1')
        rechnung(projekt=projekt, betrag='5000.00', nummer='RE-2')
        rechnung(kunde=zweiter_kunde, betrag='3000.00', nummer='RE-3')

        # ``name`` kommt aus ``str(kunde)`` mit Kundennummer, wie in der
        # Kundenzeile des Controllings.
        umsaetze = {u.kunde.name: u
                    for u in faktura_services.umsatz_je_kunde()}

        assert umsaetze['Stadtwerke Beispiel'].netto == Decimal('15000.00')
        assert umsaetze['Landratsamt Beispiel'].netto == Decimal('3000.00')

    def test_der_groesste_steht_vorn(self, projekt, kunde, zweiter_kunde):
        """Der größte Kunde steht vorn."""
        rechnung(kunde=zweiter_kunde, betrag='3000.00', nummer='RE-1')
        rechnung(projekt=projekt, betrag='10000.00', nummer='RE-2')

        assert [u.kunde.name for u in faktura_services.umsatz_je_kunde()] == [
            'Stadtwerke Beispiel', 'Landratsamt Beispiel']

    def test_er_zaehlt_die_belege_dahinter(self, projekt, kunde):
        """Gezählt werden Belege, nicht Positionen (``distinct`` auf den
        Beleg)."""
        rechnung(projekt=projekt, betrag='100.00', nummer='RE-1')
        rechnung(projekt=projekt, betrag='200.00', nummer='RE-2')

        assert faktura_services.umsatz_je_kunde()[0].belege == 2

    def test_der_kunde_kommt_ersatzweise_vom_projekt(self, projekt, kunde):
        """Der Kunde kommt ersatzweise vom Projekt.

        Eine Rechnung hat Kunde oder Projekt (Constraint); ohne Rückgriff
        auf das Projekt fiele jede Projektrechnung in "Ohne Kunden".
        """
        rechnung(projekt=projekt, betrag='4000.00', nummer='RE-1')

        assert faktura_services.umsatz_je_kunde()[0].kunde == kunde

    def test_ohne_kunden_und_ohne_projekt_sammelt_eine_eigene_zeile(self, db):
        """Belege ohne Kunde und Projekt erscheinen in einer eigenen Zeile."""
        rechnung(betrag='700.00', nummer='RE-1')

        zeile = faktura_services.umsatz_je_kunde()[0]
        assert zeile.name == 'Ohne Kunden'
        assert zeile.netto == Decimal('700.00')

    def test_ein_entwurf_zaehlt_nicht(self, projekt, kunde):
        rechnung(projekt=projekt, betrag='1000.00', nummer='RE-1')
        rechnung(projekt=projekt, betrag='9999.00', nummer='',
                 status=BelegStatus.ENTWURF)

        assert faktura_services.umsatz_je_kunde()[0].netto == Decimal('1000.00')

    def test_ein_angebot_zaehlt_nicht(self, projekt, kunde):
        """Nur Steuerbelege; ein Angebot zählt nicht."""
        rechnung(projekt=projekt, betrag='1000.00', nummer='RE-1')
        rechnung(projekt=projekt, betrag='50000.00', nummer='AN-1',
                 typ=BelegTyp.ANGEBOT)

        assert faktura_services.umsatz_je_kunde()[0].netto == Decimal('1000.00')

    def test_der_zeitraum_grenzt_ein(self, projekt, kunde):
        """Der Zeitraum grenzt ein; ohne Angabe das laufende Kalenderjahr."""
        rechnung(projekt=projekt, betrag='1000.00', nummer='RE-1',
                 belegdatum=HEUTE)
        rechnung(projekt=projekt, betrag='2000.00', nummer='RE-2',
                 belegdatum=date(HEUTE.year - 1, 6, 15))

        assert faktura_services.umsatz_je_kunde()[0].netto == Decimal('1000.00')
        alles = faktura_services.umsatz_je_kunde(
            seit=date(HEUTE.year - 1, 1, 1))
        assert alles[0].netto == Decimal('3000.00')

    def test_ein_storno_mindert(self, projekt, kunde):
        """Stornopositionen sind negativ und mindern den Umsatz."""
        rechnung(projekt=projekt, betrag='5000.00', nummer='RE-1')
        rechnung(projekt=projekt, betrag='-5000.00', nummer='ST-1',
                 typ=BelegTyp.STORNO)

        assert faktura_services.umsatz_je_kunde()[0].netto == Decimal('0.00')


# ══════════════════════════════════════════════════════════════════════════
# R-059: Alter des ältesten offenen Postens
# ══════════════════════════════════════════════════════════════════════════


class TestDerAeltesteOffenePosten:

    def test_er_nimmt_die_aelteste_erfassungszeile(self, projekt, stunde, person):
        erfassen(projekt, stunde, person, minuten=60,
                 datum=HEUTE - timedelta(days=10))
        erfassen(projekt, stunde, person, minuten=60,
                 datum=HEUTE - timedelta(days=96))

        seit = erfassung_services.aeltester_offener_posten_je_projekt()
        assert seit[projekt.pk] == HEUTE - timedelta(days=96)

    def test_eine_fremdleistung_kann_aelter_sein(self, projekt, stunde, person):
        """Aus beiden Quellen gilt das frühere Datum: Eine Laborrechnung vom
        Februar ist der älteste Posten, auch wenn die erste Stunde im Mai
        erfasst wurde."""
        erfassen(projekt, stunde, person, minuten=60,
                 datum=HEUTE - timedelta(days=30))

        labor = Kontakt.objects.create(ist_kunde=False, ist_lieferant=True, name='Labor Beispiel')
        eingang = Eingangsrechnung.objects.create(
            lieferant=labor, nummer='L-1', datum=HEUTE - timedelta(days=200),
            betrag_netto=Decimal('500.00'))
        Fremdleistung.objects.create(
            rechnung=eingang, projekt=projekt, bezeichnung='Analyse',
            einheit='Stk', menge=Decimal('5'),
            einkaufspreis=Decimal('100.00'), weiterberechenbar=True)

        seit = erfassung_services.aeltester_offener_posten_je_projekt()
        assert seit[projekt.pk] == HEUTE - timedelta(days=200)

    def test_ein_projekt_ohne_offenes_fehlt(self, projekt, db):
        """Ein Projekt ohne Offenes fehlt im Ergebnis."""
        assert erfassung_services.aeltester_offener_posten_je_projekt() == {}


# ══════════════════════════════════════════════════════════════════════════
# R-060 bis R-063: Aufwand eines Projekts
# ══════════════════════════════════════════════════════════════════════════


class TestDerAufwandJeMonat:

    def test_die_monate_ohne_erfassung_stehen_mit_null(self, projekt, stunde,
                                                       person):
        """Monate ohne Erfassung erscheinen mit 0, weil eine Lücke im Diagramm
        als "keine Angabe" erschiene."""
        erfassen(projekt, stunde, person, minuten=120)

        verlauf = erfassung_services.aufwand_je_monat(projekt, monate=6)

        assert len(verlauf) == 6
        assert verlauf[-1].minuten == 120
        assert all(m.minuten == 0 for m in verlauf[:-1])

    def test_der_letzte_monat_ist_der_laufende(self, projekt, stunde, person):
        erfassen(projekt, stunde, person, minuten=60)

        letzter = erfassung_services.aufwand_je_monat(projekt)[-1]

        assert (letzter.jahr, letzter.monat) == (HEUTE.year, HEUTE.month)
        assert letzter.beschriftung == f'{HEUTE.month:02d}/{HEUTE.year}'

    def test_alle_zeilen_zaehlen(self, projekt, stunde, person):
        """Alle Zeilen zählen, auch nicht abrechenbare und abgerechnete, weil
        der Aufwand die Arbeitszeit zeigt."""
        zeile = erfassen(projekt, stunde, person, minuten=60)
        zeile.abrechenbar = False
        zeile.save()

        assert erfassung_services.aufwand_je_monat(projekt)[-1].minuten == 60

    def test_die_stunden_fuers_diagramm(self, projekt, stunde, person):
        """R-061: einzige Stelle, an der eine Dauer als float entsteht, für das
        Diagramm."""
        erfassen(projekt, stunde, person, minuten=90)

        assert erfassung_services.aufwand_je_monat(projekt)[-1].stunden == 1.5


class TestDerAufwandJePerson:

    def test_er_summiert_je_person(self, projekt, stunde, person,
                                   django_user_model):
        zweite = django_user_model.objects.create(
            username='m.mueller', first_name='Marc', last_name='Müller')
        erfassen(projekt, stunde, person, minuten=120)
        erfassen(projekt, stunde, person, minuten=60)
        erfassen(projekt, stunde, zweite, minuten=30)

        zeilen = {z.name: z for z in
                  erfassung_services.aufwand_je_person(projekt)}

        assert zeilen['Lena Ückert'].minuten == 180
        assert zeilen['Lena Ückert'].zeilen == 2
        assert zeilen['Marc Müller'].minuten == 30

    def test_die_meiste_zeit_steht_oben(self, projekt, stunde, person,
                                        django_user_model):
        zweite = django_user_model.objects.create(username='m.mueller')
        erfassen(projekt, stunde, zweite, minuten=300)
        erfassen(projekt, stunde, person, minuten=60)

        assert erfassung_services.aufwand_je_person(projekt)[0].minuten == 300

    def test_ein_auftrag_engt_ein(self, projekt, stunde, person):
        """Ein Auftrag schränkt auf seine Zeilen ein (für die
        Auftragsakte)."""
        auftrag = rechnung(projekt=projekt, betrag='10000.00', nummer='AB-1',
                           typ=BelegTyp.AUFTRAG, menge=Decimal('100'),
                           einheit='Std')
        erfassen(projekt, stunde, person, minuten=120)

        auf_dem_auftrag = erfassung_services.zeile_erfassen(
            projekt=projekt, auftragsposition=auftrag.positionen.first(),
            benutzer=person, beschreibung='', datum=HEUTE,
            menge=Decimal('3'))
        assert auf_dem_auftrag.pk

        alle = erfassung_services.aufwand_je_person(projekt)
        nur_auftrag = erfassung_services.aufwand_je_person(
            projekt, auftrag=auftrag)

        assert alle[0].zeilen == 2
        assert nur_auftrag[0].zeilen == 1


class TestDerAufwandJeLeistung:

    def test_zeitleistungen_tragen_ihre_dauer(self, projekt, stunde, person):
        erfassen(projekt, stunde, person, minuten=120)
        erfassen(projekt, stunde, person, minuten=45)

        zeile = erfassung_services.aufwand_je_leistung(projekt)[0]

        assert zeile.name == 'Ingenieurstunde'
        assert zeile.minuten == 165
        assert zeile.menge is None
        assert zeile.einheit == 'Std'

    def test_mengenleistungen_tragen_ihre_menge(self, projekt, anfahrt, person):
        """Mengenleistungen mit ihrer Menge, ohne Aufrundung auf die
        Viertelstunde, weil die Leistung gezeigt wird."""
        erfassen(projekt, anfahrt, person, menge=Decimal('23'))
        erfassen(projekt, anfahrt, person, menge=Decimal('18.5'))

        zeile = erfassung_services.aufwand_je_leistung(projekt)[0]

        assert zeile.menge == Decimal('41.5')
        assert zeile.einheit == 'km'
        assert zeile.umfang == '41.5 km'

    def test_zwei_leistungen_bleiben_getrennt(self, projekt, stunde, anfahrt,
                                              person):
        """Leistungen mit verschiedener Einheit (23 km, 4 Std) bleiben
        getrennt."""
        erfassen(projekt, stunde, person, minuten=240)
        erfassen(projekt, anfahrt, person, menge=Decimal('23'))

        assert len(erfassung_services.aufwand_je_leistung(projekt)) == 2


# ══════════════════════════════════════════════════════════════════════════
# R-095, R-106: Kennzahlen des Controllings
# ══════════════════════════════════════════════════════════════════════════


class TestDieMonatsleistung:
    """Monatsleistung als Nenner der Reichweite, ohne den laufenden
    Monat."""

    def verlauf(self, *betraege):
        return [faktura_services.Monatssumme(jahr=2026, monat=nr + 1,
                                             netto=Decimal(betrag))
                for nr, betrag in enumerate(betraege)]

    def test_der_laufende_monat_bleibt_draussen(self):
        """Der laufende Monat zählt nicht, weil er unvollständig ist, den
        Durchschnitt senkte und die Reichweite zu günstig zeigte.
        """
        # Drei abgeschlossene Monate zu je 30.000, der laufende mit 1.000.
        gemittelt = controlling._monatsleistung(
            self.verlauf('30000', '30000', '30000', '1000'))

        assert gemittelt == Decimal('30000.00')

    def test_gemittelt_wird_ueber_drei_monate(self):
        """Gemittelt über drei Monate, damit ein Großauftrag geglättet wird und
        Entwicklungen sichtbar bleiben."""
        gemittelt = controlling._monatsleistung(
            self.verlauf('99999', '10000', '20000', '30000', '0'))

        assert gemittelt == Decimal('20000.00')

    def test_ohne_abgeschlossenen_monat_gibt_es_nichts_zu_mitteln(self):
        assert controlling._monatsleistung(self.verlauf('5000')) == Decimal('0.00')
        assert controlling._monatsleistung([]) == Decimal('0.00')


class TestDasLangeLiegengebliebene:
    """R-106: Betrag der seit mehr als 90 Tagen liegenden Leistungen."""

    def test_es_ist_die_summe_der_klassen_ohne_obere_grenze(self, projekt,
                                                            stunde, person):
        for alter in (5, 45, 200, 300):
            erfassen(projekt, stunde, person, minuten=60,
                     datum=HEUTE - timedelta(days=alter))

        lage = controlling.lage()

        # Zwei Zeilen zu je einer Stunde zu 90 EUR, älter als 90 Tage.
        assert lage.alt_liegengeblieben == Decimal('180.00')
        assert lage.offene_leistung_gesamt == Decimal('360.00')

    def test_ohne_altes_ist_es_null(self, projekt, stunde, person):
        erfassen(projekt, stunde, person, minuten=60, datum=HEUTE)

        assert controlling.lage().alt_liegengeblieben == Decimal('0.00')


# ══════════════════════════════════════════════════════════════════════════
# R-007, R-011, R-012, R-135: weitere angezeigte Werte
# ══════════════════════════════════════════════════════════════════════════


class TestDieKleinenAuskuenfte:

    def test_der_steuersatz_als_zahl(self, projekt):
        """R-007: Steuersatz aus dem gespeicherten Text als Faktor."""
        beleg = rechnung(projekt=projekt, betrag='100.00', nummer='RE-1')

        assert beleg.positionen.first().steuersatz_dezimal == Decimal('19.00')

    def test_der_abrechnungsstand_einer_auftragsposition(self, projekt):
        """R-011: "60 von 100 Std abgerechnet" an der Auftragsposition."""
        auftrag = rechnung(projekt=projekt, betrag='90.00', nummer='AB-1',
                           typ=BelegTyp.AUFTRAG, menge=Decimal('100'),
                           einheit='Std')
        position = auftrag.positionen.first()

        beleg = Beleg.objects.create(typ=BelegTyp.RECHNUNG, projekt=projekt,
                                     empfaenger='Empfänger')
        beleg.rechnungsart = Rechnungsart.NORMAL
        Belegposition.objects.create(
            beleg=beleg, position=10, bezeichnung='Leistung',
            menge=Decimal('60'), einheit='Std', einzelpreis=Decimal('90.00'),
            steuersatz=Decimal('19.00'), auftragsposition=position)
        beleg.status = BelegStatus.FESTGESCHRIEBEN
        beleg.nummer = 'RE-1'
        beleg.belegdatum = HEUTE
        beleg.save()

        assert position.abrechnungsstand == '60 von 100 Std abgerechnet'

    def test_an_einer_rechnungszeile_bedeutet_er_nichts(self, projekt):
        """An einer Rechnungszeile ist der Abrechnungsstand leer, nicht 0."""
        beleg = rechnung(projekt=projekt, betrag='100.00', nummer='RE-1')

        assert beleg.positionen.first().abrechnungsstand == ''

    def test_die_abschlagsnummer_zaehlt_je_vorhaben(self, projekt):
        """R-012: "2. Abschlagsrechnung", gezählt je Projekt nach
        Belegdatum."""
        erster = rechnung(projekt=projekt, betrag='3000.00', nummer='AR-1',
                          rechnungsart=Rechnungsart.ABSCHLAG,
                          belegdatum=HEUTE - timedelta(days=30))
        zweiter = rechnung(projekt=projekt, betrag='4000.00', nummer='AR-2',
                           rechnungsart=Rechnungsart.ABSCHLAG)

        assert erster.abschlagsnummer == 1
        assert zweiter.abschlagsnummer == 2
        assert zweiter.rechnungsbezeichnung == '2. Abschlagsrechnung'

    def test_eine_gewoehnliche_rechnung_hat_keine(self, projekt):
        beleg = rechnung(projekt=projekt, betrag='1000.00', nummer='RE-1')

        assert beleg.abschlagsnummer is None

    def test_ein_entwurf_zaehlt_mit(self, projekt):
        """Entwürfe zählen mit; nach Löschen eines Entwurfs rückt der andere
        auf."""
        rechnung(projekt=projekt, betrag='3000.00', nummer='AR-1',
                 rechnungsart=Rechnungsart.ABSCHLAG,
                 belegdatum=HEUTE - timedelta(days=30))
        entwurf = rechnung(projekt=projekt, betrag='4000.00', nummer='',
                           rechnungsart=Rechnungsart.ABSCHLAG,
                           status=BelegStatus.ENTWURF)

        assert entwurf.abschlagsnummer == 2

    def test_die_zeilensumme_in_der_vorlage(self, projekt):
        """R-135: Der Template-Filter ruft R-001 auf und rechnet nicht selbst.

        Geprüft an einer Menge, bei der eine Multiplikation ohne Rundung
        0,335 ergäbe, die Rechnung 0,34.
        """
        beleg = rechnung(projekt=projekt, betrag='1.00', nummer='RE-1',
                         menge=Decimal('0.335'))
        position = beleg.positionen.first()

        assert faktura_extras.zeilensumme(position) == Decimal('0.34')
        assert faktura_extras.zeilensumme(position) == (
            faktura_services.positionssumme(menge=position.menge,
                                            einzelpreis=position.einzelpreis))


# ══════════════════════════════════════════════════════════════════════════
# R-132 bis R-134: Zahlenformate
# ══════════════════════════════════════════════════════════════════════════
#
# Geprüft in faktura/tests/test_lokalisierung.py; hier nur, dass die Formatierung
# einen korrekt berechneten Wert nicht verändert.


class TestDieAnzeigeVerfaelschtNicht:

    def test_geld_rundet_kaufmaennisch(self):
        """``geld`` rundet kaufmännisch. Regression: Die Anzeige rundete zum
        geraden Nachbarn und wich bei drei Stellen von der Rechnung ab."""
        assert formate.geld(Decimal('0.125')) == '0,13'
        assert formate.geld(Decimal('67.125')) == '67,13'

    def test_geld_schreibt_deutsch_mit_tausenderpunkt(self):
        assert formate.geld(Decimal('4487.50')) == '4.487,50'

    def test_eine_menge_behaelt_ihre_stellen(self):
        """Eine Menge behält ihre Stellen ohne nachlaufende Nullen (``10``,
        ``1,5``)."""
        assert formate.menge(Decimal('10.000')) == '10'
        assert formate.menge(Decimal('1.500')) == '1,5'
        assert formate.menge(Decimal('0.335')) == '0,335'
