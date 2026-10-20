"""Controlling-Kennzahlen (auswertung/controlling.py).

Geprüft werden die Werte an von Hand nachgerechneten Fällen und die
Sonderfälle ohne Stunden, ohne Auftrag und ohne Umsatz. Dort muss ``None``
herauskommen und nicht null.
"""

from datetime import time, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from auswertung import controlling
from erfassung import services as erfassung_services
from erfassung.models import Eingangsrechnung, Fremdleistung, Kostensatz
from faktura import services as faktura_services
from faktura.models import (
    BelegStatus,
    BelegTyp,
    Katalogposition,
    Kontakt,
    Leistungsart,
    Projekt,
)

HEUTE = timezone.localdate()


def beleg_festschreiben(typ, *, projekt=None, kunde=None, betrag,
                        nummer='B-1', empfaenger=''):
    """Festgeschriebener Beleg, direkt am Modell gesetzt.

    ``beleg_festschreiben`` erzeugt ein PDF und braucht Firmendaten; für die
    Auswertung zählt nur der Belegzustand, und WeasyPrint kostete je Aufruf
    Zeit.
    """
    from faktura.models import Beleg, Belegposition

    beleg = Beleg.objects.create(typ=typ, projekt=projekt, kunde=kunde,
                                 empfaenger=empfaenger)
    Belegposition.objects.create(
        beleg=beleg, position=10, bezeichnung='Leistung',
        menge=Decimal('1'), einheit='pausch', einzelpreis=Decimal(betrag))
    beleg.status = BelegStatus.FESTGESCHRIEBEN
    beleg.nummer = nummer
    beleg.belegdatum = HEUTE
    beleg.save()
    return beleg


def zeit_erfassen(projekt, leistung, person, *, datum, minuten,
                  abrechenbar=True):
    """Zeitzeile mit Dauer in Minuten.

    ``zeile_erfassen`` erwartet ``von`` und ``bis``; für die Tests zählt nur
    die Dauer, die Startzeit ist fest 8 Uhr.
    """
    ende_minute = 8 * 60 + minuten
    return erfassung_services.zeile_erfassen(
        projekt=projekt, leistung=leistung, benutzer=person,
        beschreibung='', datum=datum,
        von=time(8, 0), bis=time(ende_minute // 60, ende_minute % 60),
        abrechenbar=abrechenbar,
    )



# ══════════════════════════════════════════════════════════════════════════
# Ohne Datenbank: Verhältnisse
# ══════════════════════════════════════════════════════════════════════════


class TestDerStundenertrag:
    """Stundenertrag, geprüft an der Dataclass ohne Datenbank."""

    def test_erloes_und_kosten_je_stunde(self):
        ertrag = controlling.Stundenertrag(
            eigenleistung=Decimal('24000.00'),
            stunden=Decimal('200'),
            personalkosten=Decimal('11000.00'),
        )

        assert ertrag.erloes_je_stunde == Decimal('120.00')
        assert ertrag.kosten_je_stunde == Decimal('55.00')
        assert ertrag.deckung_je_stunde == Decimal('65.00')

    def test_der_faktor_ist_der_multiplikator_auf_den_lohn(self):
        """Faktor ist Erlös durch Kosten je Stunde."""
        ertrag = controlling.Stundenertrag(
            eigenleistung=Decimal('24000.00'),
            stunden=Decimal('200'),
            personalkosten=Decimal('10000.00'),
        )

        assert ertrag.faktor == Decimal('2.40')

    def test_ohne_stunden_ist_der_satz_unbestimmt_und_nicht_null(self):
        """Ohne Stunden ist der Satz ``None``, nicht null."""
        ertrag = controlling.Stundenertrag(
            eigenleistung=Decimal('5000.00'), stunden=Decimal('0'),
            personalkosten=Decimal('0.00'),
        )

        assert ertrag.erloes_je_stunde is None
        assert ertrag.kosten_je_stunde is None
        assert ertrag.deckung_je_stunde is None
        assert ertrag.faktor is None

    def test_ohne_kostensatz_gibt_es_keinen_faktor(self):
        """Personalkosten null bedeuten unbewertete Stunden; der Faktor ist
        dann ``None`` (siehe personalkosten_je_projekt)."""
        ertrag = controlling.Stundenertrag(
            eigenleistung=Decimal('9000.00'), stunden=Decimal('90'),
            personalkosten=Decimal('0.00'),
        )

        assert ertrag.erloes_je_stunde == Decimal('100.00')
        assert ertrag.faktor is None


class TestDieDeckungsbeitragsstaffel:

    @pytest.fixture
    def staffel(self):
        return controlling.Deckungsbeitrag(
            leistungswert=Decimal('100000.00'),
            fremdkosten=Decimal('25000.00'),
            personalkosten=Decimal('45000.00'),
        )

    def test_die_beiden_stufen(self, staffel):
        assert staffel.db1 == Decimal('75000.00')
        assert staffel.db2 == Decimal('30000.00')

    def test_die_quoten(self, staffel):
        assert staffel.db1_quote == 75
        assert staffel.db2_quote == 30

    def test_ohne_leistungswert_gibt_es_keine_quote(self):
        leer = controlling.Deckungsbeitrag(
            leistungswert=Decimal('0.00'), fremdkosten=Decimal('0.00'),
            personalkosten=Decimal('800.00'))

        assert leer.db1_quote is None
        assert leer.db2_quote is None
        # Der Betrag ist definiert und negativ.
        assert leer.db2 == Decimal('-800.00')

    def test_der_wasserfall_traegt_fuenf_stufen_und_endet_im_ergebnis(
            self, staffel):
        stufen = staffel.stufen

        assert [s['titel'] for s in stufen] == [
            'Leistungswert', 'Zugekauft', 'Deckungsbeitrag I',
            'Eigene Arbeit', 'Deckungsbeitrag II']
        assert stufen[-1]['betrag'] == staffel.db2
        # Abzüge sind negativ.
        assert stufen[1]['betrag'] < 0
        assert stufen[3]['betrag'] < 0


class TestDieReichweite:

    def test_bestand_geteilt_durch_monatsleistung(self):
        reichweite = controlling.Reichweite(
            auftragsbestand=Decimal('120000.00'),
            monatsleistung=Decimal('60000.00'),
            monate_grundlage=3,
        )

        assert reichweite.monate == Decimal('2.0')
        assert not reichweite.ist_knapp

    def test_unter_einem_monat_ist_knapp(self):
        """Unter einem Monat Reichweite gilt der Bestand als knapp."""
        reichweite = controlling.Reichweite(
            auftragsbestand=Decimal('20000.00'),
            monatsleistung=Decimal('60000.00'),
            monate_grundlage=3,
        )

        assert reichweite.monate == Decimal('0.3')
        assert reichweite.ist_knapp

    def test_ohne_umsatz_ist_die_reichweite_unbestimmt(self):
        """Ohne Umsatz ist die Reichweite ``None``, nicht null."""
        reichweite = controlling.Reichweite(
            auftragsbestand=Decimal('20000.00'),
            monatsleistung=Decimal('0.00'), monate_grundlage=3)

        assert reichweite.monate is None
        assert not reichweite.ist_knapp


# ══════════════════════════════════════════════════════════════════════════
# Mit Datenbank
# ══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def kunde(db):
    return Kontakt.objects.create(nummer='K-9001', name='Stadt Beispiel')


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(
        nummer='2026-900', bezeichnung='Prüfvorhaben', kunde=kunde)


@pytest.fixture
def stunde(db):
    return Katalogposition.objects.create(
        bezeichnung='Ingenieurstunde', einheit='Std',
        einzelpreis=Decimal('100.00'), art=Leistungsart.ZEIT,
        steuersatz='19.00',
    )


@pytest.fixture
def person(django_user_model):
    mensch = django_user_model.objects.create(
        username='p.ruefer', first_name='Paula', last_name='Rüfer')
    Kostensatz.objects.create(
        benutzer=mensch, gueltig_ab=HEUTE - timedelta(days=400),
        satz=Decimal('50.00'))
    return mensch


class TestDieGeleistetenStunden:

    def test_sie_werden_nicht_aufgerundet(self, projekt, stunde, person):
        """Stunden zählen ungerundet: Drei Zeilen zu 20 Minuten sind eine
        Stunde, während die Abrechnung je Zeile auf 45 Minuten aufrundet."""
        for versatz in range(3):
            zeit_erfassen(
                projekt, stunde, person,
                datum=HEUTE - timedelta(days=versatz), minuten=20)

        stunden = erfassung_services.stunden_je_projekt()

        assert stunden[projekt.pk] == Decimal('1.00')

    def test_ein_vorhaben_ohne_zeit_fehlt_in_der_antwort(self, projekt):
        """Ein Vorhaben ohne Zeit fehlt im Ergebnis; was das bedeutet, legt
        der Aufrufer fest."""
        assert erfassung_services.stunden_je_projekt() == {}

    def test_abgeschlossene_bleiben_auf_wunsch_draussen(
            self, projekt, stunde, person):
        zeit_erfassen(
                projekt, stunde, person,
                datum=HEUTE, minuten=60)
        Projekt.objects.filter(pk=projekt.pk).update(abgeschlossen=True)

        assert erfassung_services.stunden_je_projekt() == {}
        assert erfassung_services.stunden_je_projekt(
            nur_laufende=False)[projekt.pk] == Decimal('1.00')


class TestDieAuslastung:

    def test_die_drei_toepfe_ergeben_die_erfasste_zeit(
            self, projekt, stunde, person):
        """Die drei Kategorien überschneiden sich nicht und ergeben zusammen
        die erfasste Zeit."""
        zeit_erfassen(
                projekt, stunde, person,
                datum=HEUTE, minuten=120)
        zeit_erfassen(
                projekt, stunde, person,
                datum=HEUTE, minuten=60, abrechenbar=False)

        zeilen = erfassung_services.auslastung_je_person()

        assert len(zeilen) == 1
        person_zeile = zeilen[0]
        assert person_zeile.minuten_offen == 120
        assert person_zeile.minuten_nicht_abrechenbar == 60
        assert person_zeile.minuten_gesamt == 180
        assert person_zeile.minuten_verkaufbar == 120

    def test_die_quote_ist_der_verkaufbare_anteil(
            self, projekt, stunde, person):
        zeit_erfassen(
                projekt, stunde, person,
                datum=HEUTE, minuten=180)
        zeit_erfassen(
                projekt, stunde, person,
                datum=HEUTE, minuten=60, abrechenbar=False)

        assert erfassung_services.auslastung_je_person()[0].quote == 75

    def test_ohne_erfasste_zeit_ist_die_quote_unbestimmt(self):
        leer = erfassung_services.Auslastung(
            benutzer_id=1, name='Niemand', minuten_abgerechnet=0,
            minuten_offen=0, minuten_nicht_abrechenbar=0)

        assert leer.quote is None

    def test_der_name_kommt_aus_vor_und_nachname(
            self, projekt, stunde, person):
        zeit_erfassen(
                projekt, stunde, person,
                datum=HEUTE, minuten=60)

        assert 'Rüfer' in erfassung_services.auslastung_je_person()[0].name


class TestDieAltersstruktur:
    """Nicht abgerechnete Leistung nach Altersklassen."""

    def test_die_faecher_summieren_sich_zur_gesamtzahl(
            self, projekt, stunde, person):
        """Die Altersklassen summieren sich zur Gesamtzahl.

        Eine Abrechnungsvorschau je Klasse rundete viermal auf die
        Viertelstunde und ergäbe mehr als die Gesamtzahl; verteilt wird
        deshalb der Gesamtbetrag.
        """
        for tage in (5, 45, 75, 200):
            zeit_erfassen(
                projekt, stunde, person,
                datum=HEUTE - timedelta(days=tage), minuten=50)

        klassen = erfassung_services.offene_leistung_nach_alter()
        gesamt = erfassung_services.offene_leistung_je_projekt()[projekt.pk]

        assert sum(k.betrag for k in klassen) == gesamt

    def test_jedes_fach_bekommt_seinen_posten(self, projekt, stunde, person):
        for tage in (5, 45, 75, 200):
            zeit_erfassen(
                projekt, stunde, person,
                datum=HEUTE - timedelta(days=tage), minuten=60)

        klassen = erfassung_services.offene_leistung_nach_alter()

        assert len(klassen) == 4
        assert all(k.betrag > 0 for k in klassen)

    def test_das_aelteste_fach_ist_offen(self, projekt, stunde, person):
        zeit_erfassen(
                projekt, stunde, person,
                datum=HEUTE - timedelta(days=400), minuten=60)

        klassen = erfassung_services.offene_leistung_nach_alter()

        assert klassen[-1].bis_tagen is None
        assert klassen[-1].betrag == Decimal('100.00')
        assert 'über 90' in klassen[-1].beschriftung

    def test_ohne_offene_leistung_stehen_die_faecher_auf_null(self, db):
        """Ohne offene Leistung stehen alle Klassen auf null und fehlen
        nicht."""
        klassen = erfassung_services.offene_leistung_nach_alter()

        assert len(klassen) == 4
        assert all(k.betrag == Decimal('0.00') for k in klassen)

    def test_ein_negatives_alter_landet_im_juengsten_fach(self):
        """Ein Posten mit negativem Alter landet in der jüngsten Klasse.

        Über die Erfassung kann das nicht entstehen, weil das Modell
        Zukunftsdaten ablehnt. Die Zuordnung behandelt den Fall trotzdem,
        damit keine Zeile aus der Summe fällt, die mit der Startseite
        übereinstimmen muss. Geprüft direkt an der Zuordnung.
        """
        faecher = erfassung_services._faecher((30, 60, 90))

        assert erfassung_services._fachnummer(faecher, -5) == 0
        assert erfassung_services._fachnummer(faecher, 0) == 0
        assert erfassung_services._fachnummer(faecher, 30) == 0
        assert erfassung_services._fachnummer(faecher, 31) == 1
        assert erfassung_services._fachnummer(faecher, 5000) == 3

    def test_die_erfassung_laesst_zukunft_gar_nicht_erst_zu(
            self, projekt, stunde, person):
        """Die Erfassung lehnt Zukunftsdaten ab; deshalb prüft der vorige
        Test direkt an der Zuordnung."""
        from django.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            zeit_erfassen(projekt, stunde, person,
                          datum=HEUTE + timedelta(days=10), minuten=60)


class TestDerAuftragseingang:

    def test_bestaetigte_auftraege_zaehlen_nach_belegdatum(
            self, projekt, kunde):
        beleg_festschreiben(BelegTyp.AUFTRAG, projekt=projekt,
                            betrag='5000.00', nummer='AB-1')

        verlauf = faktura_services.auftragseingang_je_monat(monate=12)

        assert verlauf[-1].netto == Decimal('5000.00')

    def test_ein_entwurf_ist_kein_auftragseingang(self, projekt):
        """Ein Auftragsentwurf zählt nicht als Auftragseingang."""
        beleg = faktura_services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.AUFTRAG,
            betreff='Noch nicht heraus', leistungsdatum=HEUTE)
        faktura_services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Leistung', menge=Decimal('1'),
            einzelpreis=Decimal('5000.00'), steuersatz='19.00')

        verlauf = faktura_services.auftragseingang_je_monat(monate=12)

        assert all(m.netto == Decimal('0.00') for m in verlauf)

    def test_eine_rechnung_ist_kein_auftragseingang(self, projekt):
        """Eine Rechnung zählt nicht als Auftragseingang."""
        beleg_festschreiben(BelegTyp.RECHNUNG, projekt=projekt,
                            betrag='5000.00', nummer='RE-1')

        verlauf = faktura_services.auftragseingang_je_monat(monate=12)

        assert all(m.netto == Decimal('0.00') for m in verlauf)
        # Gegenprobe: Im Umsatz ist sie enthalten.
        assert faktura_services.fakturaverlauf(monate=12)[-1].netto == (
            Decimal('5000.00'))

    def test_der_verlauf_hat_immer_so_viele_monate_wie_verlangt(self, db):
        assert len(faktura_services.auftragseingang_je_monat(monate=6)) == 6


class TestDieKundenstruktur:

    def _rechnung(self, kunde, betrag):
        return beleg_festschreiben(
            BelegTyp.RECHNUNG, kunde=kunde, betrag=betrag,
            nummer=f'RE-{kunde.nummer}')

    def test_der_groesste_steht_oben_und_traegt_seinen_anteil(self, db):
        gross = Kontakt.objects.create(nummer='K-1', name='Großer')
        klein = Kontakt.objects.create(nummer='K-2', name='Kleiner')
        self._rechnung(gross, '75000.00')
        self._rechnung(klein, '25000.00')

        struktur = controlling.kundenstruktur()

        # str(Kunde) beginnt mit der Nummer: "K-1 Großer".
        assert 'Großer' in struktur.groesster.name
        assert struktur.groesster.anteil == 75
        assert struktur.gesamt == Decimal('100000.00')

    def test_die_summenlinie_endet_bei_hundert(self, db):
        for nummer, betrag in [('K-1', '50000'), ('K-2', '30000'),
                               ('K-3', '20000')]:
            self._rechnung(
                Kontakt.objects.create(nummer=nummer, name=f'Kunde {nummer}'),
                betrag)

        struktur = controlling.kundenstruktur()

        assert struktur.zeilen[-1].kumuliert == 100

    def test_ab_dreissig_prozent_ist_es_ein_klumpen(self, db):
        """Ab dreißig Prozent Umsatzanteil gilt ein Kunde als Klumpenrisiko."""
        gross = Kontakt.objects.create(nummer='K-1', name='Großer')
        klein = Kontakt.objects.create(nummer='K-2', name='Kleiner')
        self._rechnung(gross, '40000.00')
        self._rechnung(klein, '60000.00')

        struktur = controlling.kundenstruktur()

        assert len(struktur.klumpen) == 2
        assert all(z.ist_klumpen for z in struktur.klumpen)

    def test_ohne_umsatz_bleibt_die_struktur_leer_statt_zu_brechen(self, db):
        struktur = controlling.kundenstruktur()

        assert struktur.zeilen == []
        assert struktur.gesamt == Decimal('0.00')
        assert struktur.groesster is None
        assert struktur.anteil_top3 == 0

    def test_eine_rechnung_ohne_kunden_verschwindet_nicht(self, db):
        """Rechnungen ohne Kunden erscheinen unter "Ohne Kunden"."""
        beleg_festschreiben(
            BelegTyp.RECHNUNG, betrag='1000.00', nummer='RE-frei',
            empfaenger='Jemand\nWeg 1\n12345 Ort')

        struktur = controlling.kundenstruktur()

        assert struktur.gesamt == Decimal('1000.00')
        assert struktur.zeilen[0].name == 'Ohne Kunden'


class TestDieLage:
    """Gesamtlage und Übereinstimmung der Teilwerte."""

    @pytest.fixture
    def bestand(self, projekt, stunde, person, kunde):
        """Vorhaben mit Auftrag, Stunden und Zukauf."""
        beleg_festschreiben(BelegTyp.AUFTRAG, projekt=projekt,
                            betrag='20000.00', nummer='AB-900')

        for versatz in range(10):
            zeit_erfassen(
                projekt, stunde, person,
                datum=HEUTE - timedelta(days=versatz), minuten=60)

        labor = Kontakt.objects.create(ist_kunde=False, ist_lieferant=True, name='Labor')
        rechnung = Eingangsrechnung.objects.create(
            lieferant=labor, nummer='L-1', datum=HEUTE,
            betrag_netto=Decimal('800.00'))
        Fremdleistung.objects.create(
            rechnung=rechnung, projekt=projekt, bezeichnung='Analyse',
            einheit='Stk', menge=Decimal('8'),
            einkaufspreis=Decimal('100.00'))
        return projekt

    def test_sie_laeuft_und_traegt_alle_teile(self, bestand):
        lage = controlling.lage()

        assert lage.stundenertrag.stunden == Decimal('10.00')
        assert lage.deckungsbeitrag.leistungswert > 0
        assert len(lage.altersklassen) == 4
        assert len(lage.auslastung) == 1
        assert len(lage.auftragseingang) == 12
        assert len(lage.umsatzverlauf) == 12

    def test_der_zukauf_faellt_aus_dem_stundenertrag_heraus(self, bestand):
        """Zukauf zählt nicht zum Stundenertrag, weil für die 800 EUR
        zugekaufte Analytik (offen, zum Einkaufspreis) keine Stunden gebucht
        sind."""
        lage = controlling.lage()

        # Zehn Stunden zu 100 EUR, ohne Laborverkauf.
        assert lage.stundenertrag.eigenleistung == Decimal('1000.00')
        assert lage.stundenertrag.erloes_je_stunde == Decimal('100.00')

    def test_der_faktor_folgt_aus_erloes_und_kostensatz(self, bestand):
        """100 EUR Erlös bei 50 EUR Kostensatz ergeben Faktor zwei."""
        assert controlling.lage().stundenertrag.faktor == Decimal('2.00')

    def test_deckungsbeitrag_zwei_ist_das_ergebnis_der_uebersicht(
            self, bestand):
        """DB II entspricht dem Ergebnis der Übersicht, damit Startseite und
        Controlling denselben Betrag zeigen."""
        lage = controlling.lage()

        assert lage.deckungsbeitrag.db2 == lage.uebersicht.ergebnis

    def test_book_to_bill_ohne_umsatz_ist_unbestimmt(self, bestand):
        """Beauftragt, aber nichts berechnet: Book-to-Bill ist ``None``."""
        lage = controlling.lage()

        assert lage.umsatz_summe == Decimal('0.00')
        assert lage.eingang_gegen_umsatz is None

    def test_die_altersklassen_summieren_sich_zur_offenen_leistung(
            self, bestand):
        lage = controlling.lage()

        assert lage.offene_leistung_gesamt == (
            erfassung_services.offene_leistung_gesamt())

    def test_ohne_jeden_bestand_bricht_nichts(self, db):
        """Leere Datenbank: keine Division durch null."""
        lage = controlling.lage()

        assert lage.stundenertrag.erloes_je_stunde is None
        assert lage.reichweite.monate is None
        assert lage.kunden.zeilen == []
        assert lage.deckungsbeitrag.db2 == Decimal('0.00')
        assert lage.eingang_gegen_umsatz is None


class TestDieProjektsicht:
    """Kennzahlen für ein einzelnes Vorhaben."""

    def test_stundenertrag_und_staffel_passen_zum_ergebnis(
            self, projekt, stunde, person):
        from auswertung import ergebnisse

        for versatz in range(4):
            zeit_erfassen(
                projekt, stunde, person,
                datum=HEUTE - timedelta(days=versatz), minuten=60)

        ergebnis = ergebnisse.projektergebnis(projekt)
        ertrag = controlling.projektertrag(ergebnis)
        staffel = controlling.projektdeckungsbeitrag(ergebnis)

        assert ertrag.stunden == Decimal('4.00')
        assert ertrag.erloes_je_stunde == Decimal('100.00')
        assert staffel.db2 == ergebnis.ergebnis

    def test_ein_abgeschlossenes_vorhaben_behaelt_seine_stunden(
            self, projekt, stunde, person):
        """``projektertrag`` filtert nicht auf laufende Vorhaben, damit
        abgeschlossene ihre Stunden behalten."""
        from auswertung import ergebnisse

        zeit_erfassen(
                projekt, stunde, person,
                datum=HEUTE, minuten=120)
        Projekt.objects.filter(pk=projekt.pk).update(abgeschlossen=True)
        projekt.refresh_from_db()

        ergebnis = ergebnisse.projektergebnis(projekt)

        assert controlling.projektertrag(ergebnis).stunden == Decimal('2.00')
