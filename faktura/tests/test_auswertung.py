"""Tests der Auswertung über alle Projekte (Zahlen der Startseite).

Eigene Datei, weil diese Funktionen in SQL summieren, während faktura sonst
in Python rechnet (``belegsummen``). Die Tests prüfen, dass beide Wege
dasselbe Ergebnis liefern.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from faktura import services
from faktura.models import Beleg, BelegTyp, Kontakt, Projekt


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-2000',
        name='Bauherr GmbH',
        strasse='Werkstraße 5',
        plz='80331',
        ort='München',
    )


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(
        nummer='2026-100', bezeichnung='Halle Nord', kunde=kunde)


@pytest.fixture
def beleg_mit_summe(db):
    """Legt einen festgeschriebenen Beleg über einen Nettobetrag an.

    Festgeschrieben, weil die Auswertung Entwürfe ausschließt.
    """
    def herstellen(*, projekt, typ, netto, tage_zurueck=0):
        beleg = services.beleg_anlegen(projekt=projekt, typ=typ)
        beleg.leistungsdatum = timezone.localdate()
        beleg.belegdatum = timezone.localdate() - timedelta(days=tage_zurueck)
        beleg.save()
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Leistung', menge=Decimal('1'),
            einzelpreis=Decimal(netto), steuersatz='19.00',
        )
        festgeschrieben = services.beleg_festschreiben(beleg_id=beleg.pk)
        # beleg_festschreiben setzt das Belegdatum auf heute. Für den
        # Monatsverlauf wird es über update() zurückdatiert, weil save() am
        # festgeschriebenen Beleg keine Änderung zulässt.
        if tage_zurueck:
            Beleg.objects.filter(pk=festgeschrieben.pk).update(
                belegdatum=timezone.localdate() - timedelta(days=tage_zurueck))
        return Beleg.objects.get(pk=festgeschrieben.pk)

    return herstellen


@pytest.mark.django_db
class TestProjektstaende:

    def test_angeboten_beauftragt_und_fakturiert_stehen_getrennt(
        self, projekt, beleg_mit_summe
    ):
        beleg_mit_summe(projekt=projekt, typ=BelegTyp.ANGEBOT, netto='10000.00')
        beleg_mit_summe(projekt=projekt, typ=BelegTyp.AUFTRAG,
                        netto='9000.00')
        beleg_mit_summe(projekt=projekt, typ=BelegTyp.RECHNUNG, netto='4000.00')

        stand = services.projektstaende()[0]

        assert stand.angeboten == Decimal('10000.00')
        assert stand.beauftragt == Decimal('9000.00')
        assert stand.fakturiert == Decimal('4000.00')
        assert stand.offen == Decimal('5000.00')

    def test_dieselbe_summe_wie_die_projektakte(self, projekt, beleg_mit_summe):
        """projektstaende() (SQL) liefert dieselbe Summe wie projektakte()
        (Python über belegsummen()).

        Sonst zeigten Startseite und Projektakte verschiedene Beträge. Mit
        Beträgen, bei denen eine falsche Rundungsregel auffällt.
        """
        for netto in ('1234.57', '987.65', '0.03'):
            beleg_mit_summe(projekt=projekt, typ=BelegTyp.RECHNUNG, netto=netto)

        akte = services.projektakte(projekt)
        stand = services.projektstaende()[0]

        assert stand.fakturiert == akte.fakturiert_netto

    def test_ein_entwurf_zaehlt_nicht_mit(self, projekt, beleg_mit_summe):
        """Ein Entwurf zählt nicht, weil sich die Auswertung sonst beim
        Verwerfen rückwirkend änderte."""
        beleg_mit_summe(projekt=projekt, typ=BelegTyp.RECHNUNG, netto='1000.00')

        entwurf = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.RECHNUNG)
        services.position_hinzufuegen(
            beleg=entwurf, bezeichnung='Noch nicht', menge=Decimal('1'),
            einzelpreis=Decimal('5000.00'), steuersatz='19.00',
        )

        assert services.projektstaende()[0].fakturiert == Decimal('1000.00')

    def test_eine_stornorechnung_zieht_ab(self, projekt, beleg_mit_summe):
        """Stornopositionen sind negativ und mindern die Summe, wie in
        projektakte()."""
        rechnung = beleg_mit_summe(projekt=projekt, typ=BelegTyp.RECHNUNG,
                                   netto='2000.00')

        # rechnung_korrigieren schreibt das Storno sofort fest; die neue
        # Rechnung bleibt Entwurf und zählt nicht.
        services.rechnung_korrigieren(beleg_id=rechnung.pk)

        assert Beleg.objects.filter(typ=BelegTyp.STORNO).exists()
        assert services.projektstaende()[0].fakturiert == Decimal('0.00')

    def test_mehr_berechnet_als_beauftragt_ergibt_keinen_negativen_bestand(
        self, projekt, beleg_mit_summe
    ):
        """Mehr berechnet als beauftragt (Nachträge ohne Auftrag) ergibt
        Auftragsbestand 0.

        Ein negativer Wert verringerte in der Gesamtsumme die offenen
        Beträge anderer Projekte.
        """
        beleg_mit_summe(projekt=projekt, typ=BelegTyp.AUFTRAG,
                        netto='1000.00')
        beleg_mit_summe(projekt=projekt, typ=BelegTyp.RECHNUNG, netto='1500.00')

        assert services.projektstaende()[0].offen == Decimal('0.00')

    def test_abgeschlossene_projekte_bleiben_draussen(self, projekt, kunde,
                                                      beleg_mit_summe):
        erledigt = Projekt.objects.create(
            nummer='2025-001', bezeichnung='Altbau', kunde=kunde,
            abgeschlossen=True)
        beleg_mit_summe(projekt=erledigt, typ=BelegTyp.RECHNUNG, netto='500.00')
        beleg_mit_summe(projekt=projekt, typ=BelegTyp.RECHNUNG, netto='500.00')

        nummern = [s.projekt.nummer for s in services.projektstaende()]

        assert nummern == ['2026-100']
        assert len(services.projektstaende(nur_laufende=False)) == 2

    def test_ein_projekt_ohne_belege_steht_mit_null_da(self, projekt):
        """Ein Projekt ohne Belege erscheint mit 0."""
        stand = services.projektstaende()[0]

        assert stand.projekt == projekt
        assert stand.fakturiert == Decimal('0.00')

    def test_ohne_auftrag_gibt_es_keinen_fortschritt(self, projekt,
                                                     beleg_mit_summe):
        """Ohne Auftrag fehlt der Nenner; der Fortschritt ist unbekannt, und
        die Anzeige blendet den Balken aus."""
        beleg_mit_summe(projekt=projekt, typ=BelegTyp.RECHNUNG, netto='800.00')

        assert services.projektstaende()[0].fortschritt == 0

    def test_der_fortschritt_zaehlt_in_prozent(self, projekt, beleg_mit_summe):
        beleg_mit_summe(projekt=projekt, typ=BelegTyp.AUFTRAG,
                        netto='1000.00')
        beleg_mit_summe(projekt=projekt, typ=BelegTyp.RECHNUNG, netto='250.00')

        assert services.projektstaende()[0].fortschritt == 25


@pytest.mark.django_db
class TestFakturaverlauf:

    def test_der_verlauf_hat_so_viele_monate_wie_verlangt(self):
        assert len(services.fakturaverlauf(monate=12)) == 12
        assert len(services.fakturaverlauf(monate=3)) == 3

    def test_der_letzte_monat_ist_der_laufende(self):
        heute = timezone.localdate()

        letzter = services.fakturaverlauf(monate=6)[-1]

        assert (letzter.jahr, letzter.monat) == (heute.year, heute.month)

    def test_monate_ohne_belege_stehen_mit_null_da(self):
        """Monate ohne Belege erscheinen mit 0, weil eine Lücke im Diagramm als
        "keine Angabe" erschiene."""
        verlauf = services.fakturaverlauf(monate=6)

        assert all(m.netto == Decimal('0.00') for m in verlauf)

    def test_eine_rechnung_landet_in_ihrem_monat(self, projekt,
                                                 beleg_mit_summe):
        beleg_mit_summe(projekt=projekt, typ=BelegTyp.RECHNUNG, netto='700.00')

        letzter = services.fakturaverlauf(monate=12)[-1]

        assert letzter.netto == Decimal('700.00')

    def test_ein_angebot_landet_nicht_im_verlauf(self, projekt,
                                                 beleg_mit_summe):
        """Ein Angebot zählt nicht zum Verlauf, weil es nichts berechnet."""
        beleg_mit_summe(projekt=projekt, typ=BelegTyp.ANGEBOT, netto='9000.00')

        assert services.fakturaverlauf(monate=12)[-1].netto == Decimal('0.00')


@pytest.mark.django_db
class TestFakturiertImJahr:

    def test_summiert_das_laufende_jahr(self, projekt, beleg_mit_summe):
        beleg_mit_summe(projekt=projekt, typ=BelegTyp.RECHNUNG, netto='300.00')
        beleg_mit_summe(projekt=projekt, typ=BelegTyp.RECHNUNG, netto='200.50')

        assert services.fakturiert_im_jahr() == Decimal('500.50')

    def test_ein_jahr_ohne_belege_ergibt_null_und_nicht_None(self):
        """Ein Jahr ohne Belege ergibt 0, weil ``Coalesce`` das None von
        ``Sum`` ersetzt, das auf der Startseite einen TypeError auslöste."""
        assert services.fakturiert_im_jahr(1999) == Decimal('0.00')


@pytest.mark.django_db
class TestGemahnteRechnungen:

    def test_ohne_mahnung_steht_dort_nichts(self, projekt, beleg_mit_summe):
        beleg_mit_summe(projekt=projekt, typ=BelegTyp.RECHNUNG, netto='1000.00')

        stand = services.gemahnte_rechnungen()

        assert stand.anzahl == 0
        assert stand.brutto == Decimal('0.00')

    def test_eine_gemahnte_rechnung_zaehlt_brutto(self, kunde, ueberfaellig):
        """Eine gemahnte Rechnung zählt brutto, weil der Bruttobetrag gefordert
        wird."""
        rechnung = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)
        rechnung.leistungsdatum = timezone.localdate()
        rechnung.save()
        services.position_hinzufuegen(
            beleg=rechnung, bezeichnung='Leistung', menge=Decimal('1'),
            einzelpreis=Decimal('1000.00'), steuersatz='19.00',
        )
        festgeschrieben = ueberfaellig(rechnung)
        services.mahnung_erstellen(beleg_id=festgeschrieben.pk, stufe=1)

        stand = services.gemahnte_rechnungen()

        assert stand.anzahl == 1
        assert stand.brutto == Decimal('1190.00')

    def test_zwei_mahnstufen_zaehlen_die_rechnung_einmal(self, kunde,
                                                         ueberfaellig):
        """Eine zweimal gemahnte Rechnung zählt einmal (``distinct()``)."""
        rechnung = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)
        rechnung.leistungsdatum = timezone.localdate()
        rechnung.save()
        services.position_hinzufuegen(
            beleg=rechnung, bezeichnung='Leistung', menge=Decimal('1'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00',
        )
        festgeschrieben = ueberfaellig(rechnung)
        services.mahnung_erstellen(beleg_id=festgeschrieben.pk, stufe=1)
        services.mahnung_erstellen(beleg_id=festgeschrieben.pk, stufe=2)

        assert services.gemahnte_rechnungen().anzahl == 1


@pytest.mark.django_db
class TestEntwuerfeInDerAkte:
    """Entwürfe erscheinen in der Liste der Projektakte, nicht in den
    Summen.

    Regression: Eine nicht festgeschriebene Abschlagsrechnung fehlte in der
    Projektakte.
    """

    def _entwurf(self, projekt, netto='5000.00'):
        entwurf = services.beleg_anlegen(projekt=projekt,
                                         typ=BelegTyp.RECHNUNG)
        services.position_hinzufuegen(
            beleg=entwurf, bezeichnung='Abschlag in Arbeit',
            menge=Decimal('1'), einzelpreis=Decimal(netto),
            steuersatz='19.00',
        )
        return entwurf

    def test_ohne_schalter_bleibt_er_draussen(self, projekt, beleg_mit_summe):
        """Default ``mit_entwuerfen=False``, auf den sich die API stützt."""
        beleg_mit_summe(projekt=projekt, typ=BelegTyp.RECHNUNG, netto='1000.00')
        entwurf = self._entwurf(projekt)

        akte = services.projektakte(projekt)

        assert entwurf not in akte.belege

    def test_mit_schalter_steht_er_in_der_liste(self, projekt,
                                                beleg_mit_summe):
        beleg_mit_summe(projekt=projekt, typ=BelegTyp.RECHNUNG, netto='1000.00')
        entwurf = self._entwurf(projekt)

        akte = services.projektakte(projekt, mit_entwuerfen=True)

        assert entwurf in akte.belege

    def test_und_zaehlt_trotzdem_in_keiner_summe(self, projekt,
                                                 beleg_mit_summe):
        """``mit_entwuerfen`` ändert nur die Liste, nicht die Summen."""
        beleg_mit_summe(projekt=projekt, typ=BelegTyp.RECHNUNG, netto='1000.00')
        self._entwurf(projekt, netto='5000.00')

        mit = services.projektakte(projekt, mit_entwuerfen=True)
        ohne = services.projektakte(projekt)

        assert mit.fakturiert_netto == ohne.fakturiert_netto == Decimal('1000.00')
        assert mit.je_belegart == ohne.je_belegart
