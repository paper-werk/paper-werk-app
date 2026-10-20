"""Abgleich von Werten, die auf zwei Wegen berechnet werden.

Mehrere Werte werden bewusst zweimal berechnet: eine Belegansicht in Python
über ``belegsummen``, eine Liste über viele Projekte in SQL. Beide müssen
auf den Cent übereinstimmen, sonst zeigen Projektakte und Belegliste
verschiedene Beträge.

Die Tests prüfen Übereinstimmung, nicht Richtigkeit; beide Wege könnten
gleich falsch sein. Sie ergänzen daher die Tests mit Sollwerten in
``test_auswertung.py`` und ``test_controlling.py``.

**Die Nummern R-xxx** verweisen auf ``docs/rechenregister.md``.
"""

from datetime import time, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from auswertung import ergebnisse
from erfassung import services as erfassung_services
from erfassung.models import Kostensatz
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

HEUTE = timezone.localdate()


# ══════════════════════════════════════════════════════════════════════════
# Vorbedingungen
# ══════════════════════════════════════════════════════════════════════════
#
# Wie in test_controlling.py entstehen die Belege am Modell und nicht über
# beleg_festschreiben(), weil für den Abgleich der Zustand zählt, nicht das
# PDF.


@pytest.fixture
def kunde(db):
    return Kontakt.objects.create(nummer='K-7001', name='Landkreis Beispiel')


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(
        nummer='2026-700', bezeichnung='Abgleichvorhaben', kunde=kunde)


@pytest.fixture
def stunde(db):
    return Katalogposition.objects.create(
        bezeichnung='Ingenieurstunde', einheit='Std',
        einzelpreis=Decimal('89.50'), art=Leistungsart.ZEIT,
        steuersatz='19.00',
    )


@pytest.fixture
def firma(db):
    """Eigene Firma, nur für die E-Rechnung.

    ``faktura/conftest.py`` legt sie für Tests in faktura an; diese Datei
    liegt außerhalb und sieht die Fixture nicht. Gebraucht nur für das XML,
    das ohne Steuernummer nicht entsteht.
    """
    from faktura.models import Firma

    return Firma.objects.create(
        name='Werkstatt Amper GmbH', strasse='Musterweg 12', plz='80331',
        ort='München', telefon='089 1234567', email='post@example.de',
        steuernummer='143/815/47110', ust_id='DE123456789',
        bank='Stadtsparkasse', iban='DE02120300000000202051',
        bic='BYLADEM1001', geschaeftsfuehrung='H. Amper',
        registergericht='AG München', handelsregister='HRB 12345',
    )


@pytest.fixture
def person(django_user_model):
    mensch = django_user_model.objects.create(
        username='a.pruefer', first_name='Anne', last_name='Prüfer')
    Kostensatz.objects.create(
        benutzer=mensch, gueltig_ab=HEUTE - timedelta(days=400),
        satz=Decimal('48.00'))
    return mensch


def beleg_mit(typ, *, projekt=None, kunde=None, positionen, nummer='B-1',
              status=BelegStatus.FESTGESCHRIEBEN,
              rechnungsart=Rechnungsart.NORMAL, gegen=None,
              leistungsdatum=None):
    """Beleg mit beliebig vielen Positionen.

    ``positionen`` ist eine Liste aus (Menge, Einzelpreis, Steuersatz),
    damit die Zahlen des Falls im Test sichtbar sind.

    ``gegen`` sind die Auftragspositionen, gegen die abgerechnet wird, in
    derselben Reihenfolge wie ``positionen``.

    Alle Felder, auch das Leistungsdatum, werden vor dem Festschreiben
    gesetzt, weil der Beleg danach unveränderlich ist.
    """
    beleg = Beleg.objects.create(typ=typ, projekt=projekt, kunde=kunde,
                                 empfaenger='Landkreis Beispiel')
    if typ == BelegTyp.RECHNUNG:
        beleg.rechnungsart = rechnungsart
    if leistungsdatum is not None:
        beleg.leistungsdatum = leistungsdatum

    bezuege = list(gegen) if gegen else [None] * len(positionen)
    for nr, ((menge, preis, satz), bezug) in enumerate(
            zip(positionen, bezuege, strict=True), start=1):
        Belegposition.objects.create(
            beleg=beleg, position=nr * 10, bezeichnung=f'Leistung {nr}',
            menge=menge, einheit='Std', einzelpreis=preis, steuersatz=satz,
            auftragsposition=bezug)

    beleg.status = status
    if status != BelegStatus.ENTWURF:
        beleg.nummer = nummer
    beleg.belegdatum = HEUTE
    beleg.save()
    return beleg


def zeit_erfassen(projekt, leistung, person, *, minuten, datum=None,
                  abrechenbar=True):
    """Zeitzeile mit Dauer, ohne Uhrzeiten."""
    ende = 8 * 60 + minuten
    return erfassung_services.zeile_erfassen(
        projekt=projekt, leistung=leistung, benutzer=person,
        beschreibung='', datum=datum or HEUTE,
        von=time(8, 0), bis=time(ende // 60, ende % 60),
        abrechenbar=abrechenbar,
    )


#: Positionen, an denen Rundungsfehler auffallen.
#
# Drei Nachkommastellen in der Menge (Kilogramm, Kilometer, Liter) und
# ungerade Preise; mit 10 Stück zu 100,00 EUR bestünde jede falsche
# Rundungsregel.
KRUMME_POSITIONEN = [
    (Decimal('0.335'), Decimal('1.00'), Decimal('19.00')),
    (Decimal('3.333'), Decimal('7.77'), Decimal('19.00')),
    (Decimal('1.005'), Decimal('99.99'), Decimal('7.00')),
    (Decimal('12.125'), Decimal('3.50'), Decimal('7.00')),
]


# ══════════════════════════════════════════════════════════════════════════
# R-002 bis R-005 gegen R-014/R-015: Python gegen SQL
# ══════════════════════════════════════════════════════════════════════════


class TestDieBelegsummeGegenDieListensumme:
    """``belegsummen`` rechnet je Beleg in Python, ``summe_ueber`` über die
    Menge in SQL; beide stimmen auf den Cent überein (Begründung im
    Docstring von ``summe_ueber``)."""

    def test_ein_beleg_mit_krummen_mengen(self, projekt):
        beleg = beleg_mit(BelegTyp.RECHNUNG, projekt=projekt,
                          positionen=KRUMME_POSITIONEN, nummer='RE-1')

        einzeln = faktura_services.belegsummen(beleg)
        ueber_liste = faktura_services.summe_ueber(
            Beleg.objects.filter(pk=beleg.pk))

        assert ueber_liste.netto == einzeln.netto
        assert ueber_liste.steuer == einzeln.steuer
        assert ueber_liste.brutto == einzeln.brutto

    def test_mehrere_belege_mehrerer_steuersaetze(self, projekt):
        """Mehrere Belege mit mehreren Steuersätzen.

        ``summe_ueber`` gruppiert nach (Beleg, Steuersatz); eine Gruppierung
        über alle Belege wiche um Cent ab.
        """
        belege = [
            beleg_mit(BelegTyp.RECHNUNG, projekt=projekt, nummer=f'RE-{i}',
                      positionen=KRUMME_POSITIONEN)
            for i in range(1, 6)
        ]

        einzeln_netto = sum(
            (faktura_services.belegsummen(b).netto for b in belege),
            Decimal('0.00'))
        einzeln_steuer = sum(
            (faktura_services.belegsummen(b).steuer for b in belege),
            Decimal('0.00'))
        ueber_liste = faktura_services.summe_ueber(Beleg.objects.all())

        assert ueber_liste.netto == einzeln_netto
        assert ueber_liste.steuer == einzeln_steuer

    def test_ein_storno_hebt_die_rechnung_auf(self, projekt):
        """Rechnung und Storno ergeben auf beiden Wegen genau 0."""
        beleg_mit(BelegTyp.RECHNUNG, projekt=projekt, nummer='RE-1',
                  positionen=KRUMME_POSITIONEN)
        beleg_mit(BelegTyp.STORNO, projekt=projekt, nummer='ST-1',
                  positionen=[(-m, p, s) for m, p, s in KRUMME_POSITIONEN])

        summe = faktura_services.summe_ueber(Beleg.objects.all())
        assert summe.netto == Decimal('0.00')
        assert summe.steuer == Decimal('0.00')
        assert summe.brutto == Decimal('0.00')


# ══════════════════════════════════════════════════════════════════════════
# R-018 gegen R-023: Projektakte gegen Übersicht
# ══════════════════════════════════════════════════════════════════════════


class TestDieProjektakteGegenDieUebersicht:
    """``projektakte`` berechnet die Belege eines Projekts in Python,
    ``projektstaende`` summiert alle Projekte in SQL; beide liefern den
    fakturierten Betrag."""

    def test_fakturiert_stimmt_ueber_beide_wege(self, projekt):
        beleg_mit(BelegTyp.RECHNUNG, projekt=projekt, nummer='RE-1',
                  positionen=KRUMME_POSITIONEN)
        beleg_mit(BelegTyp.RECHNUNG, projekt=projekt, nummer='RE-2',
                  positionen=KRUMME_POSITIONEN)

        akte = faktura_services.projektakte(projekt)
        stand = faktura_services.projektstaende()[0]

        assert stand.fakturiert == akte.fakturiert_netto

    def test_ein_entwurf_zaehlt_auf_keinem_der_beiden_wege(self, projekt):
        """Beide Wege schließen Entwürfe aus.

        Sonst änderte sich die Übersicht rückwirkend beim Verwerfen eines
        Entwurfs.
        """
        beleg_mit(BelegTyp.RECHNUNG, projekt=projekt, nummer='RE-1',
                  positionen=KRUMME_POSITIONEN)
        beleg_mit(BelegTyp.RECHNUNG, projekt=projekt,
                  positionen=KRUMME_POSITIONEN, status=BelegStatus.ENTWURF)

        akte = faktura_services.projektakte(projekt, mit_entwuerfen=True)
        stand = faktura_services.projektstaende()[0]
        einer = faktura_services.belegsummen(
            Beleg.objects.get(nummer='RE-1')).netto

        assert akte.fakturiert_netto == einer
        assert stand.fakturiert == einer

    def test_eine_mahnung_erhoeht_keine_der_beiden_summen(self, projekt):
        """Die Mahnung zählt auf keinem Weg, weil sie Berechnetes erneut
        fordert."""
        beleg_mit(BelegTyp.RECHNUNG, projekt=projekt, nummer='RE-1',
                  positionen=KRUMME_POSITIONEN)
        vorher = faktura_services.projektstaende()[0].fakturiert

        beleg_mit(BelegTyp.MAHNUNG, projekt=projekt, nummer='MA-1',
                  positionen=KRUMME_POSITIONEN)

        assert faktura_services.projektstaende()[0].fakturiert == vorher
        assert faktura_services.projektakte(projekt).fakturiert_netto == vorher

    def test_ein_abschlag_zaehlt_fakturiert_aber_nicht_abgerechnet(self, projekt):
        """R-023 gegen R-024: Ein Abschlag zählt als fakturiert, nicht als
        abgerechnet. Regression: Marge 60 % statt 41 %."""
        beleg_mit(BelegTyp.RECHNUNG, projekt=projekt, nummer='AR-1',
                  positionen=[(Decimal('1'), Decimal('5000.00'),
                               Decimal('19.00'))],
                  rechnungsart=Rechnungsart.ABSCHLAG)

        stand = faktura_services.projektstaende()[0]
        assert stand.fakturiert == Decimal('5000.00')
        assert stand.abgerechnete_leistung == Decimal('0.00')


# ══════════════════════════════════════════════════════════════════════════
# R-051 gegen R-068: Altersstaffel gegen Gesamtsumme
# ══════════════════════════════════════════════════════════════════════════


class TestDieAltersstaffelGegenDieGesamtsumme:

    def test_die_faecher_ergeben_zusammen_die_gesamtzahl(
            self, projekt, stunde, person):
        """Die Altersklassen ergeben zusammen die Gesamtzahl.

        Die Aufteilung verteilt anteilig und gibt der letzten Klasse den
        Rundungsrest, damit die Summe stimmt.
        """
        for alter in (5, 20, 45, 75, 120, 200):
            zeit_erfassen(projekt, stunde, person, minuten=20,
                          datum=HEUTE - timedelta(days=alter))

        klassen = erfassung_services.offene_leistung_nach_alter()
        gesamt = erfassung_services.offene_leistung_gesamt()

        assert sum((k.betrag for k in klassen), Decimal('0.00')) == gesamt

    def test_das_gilt_auch_ueber_mehrere_projekte(self, kunde, stunde, person):
        """Auch über mehrere Projekte, weil je Projekt verteilt wird und sich
        Rundungsreste nicht summieren dürfen."""
        for nr in range(4):
            projekt = Projekt.objects.create(
                nummer=f'2026-8{nr:02d}', bezeichnung=f'Vorhaben {nr}',
                kunde=kunde)
            for alter in (10, 50, 100, 190):
                zeit_erfassen(projekt, stunde, person, minuten=20,
                              datum=HEUTE - timedelta(days=alter))

        klassen = erfassung_services.offene_leistung_nach_alter()
        gesamt = erfassung_services.offene_leistung_gesamt()

        assert sum((k.betrag for k in klassen), Decimal('0.00')) == gesamt


# ══════════════════════════════════════════════════════════════════════════
# Auftragsakte gegen Rechnungssumme
# ══════════════════════════════════════════════════════════════════════════


class TestDerBerechneteWertDerAuftragsakte:
    """R-108 gegen R-004: "Abgerechnet" in der Auftragsakte ist die Summe
    der Rechnungen auf diesen Auftrag.

    Die Berechnung steht in ``faktura.services.berechneter_wert`` und ist
    ohne Seitenaufruf prüfbar."""

    @pytest.fixture
    def auftrag_mit_rechnung(self, projekt):
        """Vollständig berechneter Auftrag mit ungeraden Mengen."""
        auftrag = beleg_mit(BelegTyp.AUFTRAG, projekt=projekt, nummer='AB-1',
                            positionen=KRUMME_POSITIONEN)
        rechnung = beleg_mit(BelegTyp.RECHNUNG, projekt=projekt,
                             nummer='RE-1', positionen=KRUMME_POSITIONEN,
                             gegen=list(auftrag.positionen.all()))
        return auftrag, rechnung

    def test_ein_abschlag_zaehlt_nicht_mit(self, projekt):
        """Ein Abschlag zählt nicht, weil er eine Anzahlung ist und die
        Schlussrechnung die Leistung erneut aufführt."""
        auftrag = beleg_mit(BelegTyp.AUFTRAG, projekt=projekt, nummer='AB-1',
                            positionen=[(Decimal('1'), Decimal('10000.00'),
                                         Decimal('19.00'))])
        beleg_mit(BelegTyp.RECHNUNG, projekt=projekt, nummer='AR-1',
                  positionen=[(Decimal('1'), Decimal('4000.00'),
                               Decimal('19.00'))],
                  gegen=list(auftrag.positionen.all()),
                  rechnungsart=Rechnungsart.ABSCHLAG)

        assert faktura_services.berechneter_wert(auftrag) == Decimal('0.00')

    def test_der_berechnete_wert_ist_die_rechnungssumme(
            self, auftrag_mit_rechnung):
        """Der berechnete Wert der Auftragsakte ist die Rechnungssumme.

        Regression: Bei Mengen mit drei Nachkommastellen wichen die Beträge
        ab, weil die Akte ohne Rundung je Position summierte.
        """
        auftrag, rechnung = auftrag_mit_rechnung

        assert (faktura_services.berechneter_wert(auftrag)
                == faktura_services.belegsummen(rechnung).netto)


# ══════════════════════════════════════════════════════════════════════════
# Erfassungszeile auf einem Rechnungsentwurf
# ══════════════════════════════════════════════════════════════════════════


class TestEineZeileAufEinemRechnungsentwurf:
    """Eine Erfassungszeile, die einem Rechnungsentwurf zugeordnet ist.

    Zwischen Anlegen und Festschreiben einer Rechnung behandelten drei
    Stellen eine solche Zeile verschieden (vor der Korrektur):

    * ``NOCH_NICHT_ABGERECHNET`` zählt sie als **offen**, weil ein Entwurf
      kein Beleg ist.
    * ``abrechnungsvorschau`` überging sie als **bereits abgerechnet**,
      weil nur ``abgerechnet_in`` geprüft wurde.
    * ``auslastung_je_person`` zählte sie aus demselben Grund als
      **abgerechnet**.

    Die erste Stelle bestimmt die Auswahl, die zweite die Berechnung;
    zusammen fiel die Leistung weg.
    """

    @pytest.fixture
    def zeile_im_entwurf(self, projekt, stunde, person):
        """Zwei Stunden, einem Rechnungsentwurf zugeordnet."""
        zeile = zeit_erfassen(projekt, stunde, person, minuten=120)
        entwurf = beleg_mit(BelegTyp.RECHNUNG, projekt=projekt,
                            positionen=[(Decimal('2'), Decimal('89.50'),
                                         Decimal('19.00'))],
                            status=BelegStatus.ENTWURF)
        zeile.abgerechnet_in = entwurf.positionen.first()
        zeile.save()
        return zeile

    def test_der_filter_findet_sie(self, zeile_im_entwurf):
        """``NOCH_NICHT_ABGERECHNET`` findet die Zeile."""
        from erfassung.models import Erfassungszeile

        assert Erfassungszeile.objects.filter(
            erfassung_services.NOCH_NICHT_ABGERECHNET, abrechenbar=True
        ).count() == 1

    def test_zum_uebernehmen_bleibt_sie_draussen(self, zeile_im_entwurf):
        """Für die Übernahme bleibt die Zeile ausgeschlossen.

        Sonst stünde sie zweimal auf derselben Rechnung. Ohne
        ``entwuerfe_zaehlen`` (Default, Aufruf aus der Abrechnungsmaske)
        wird sie ausgelassen.
        """
        from erfassung.models import Erfassungszeile

        vorschau = erfassung_services.abrechnungsvorschau(
            list(Erfassungszeile.objects.filter(
                erfassung_services.NOCH_NICHT_ABGERECHNET, abrechenbar=True)))

        assert vorschau.positionen == []
        assert [grund for _, grund in vorschau.uebergangen] == [
            erfassung_services.GRUND_SCHON_ABGERECHNET]

    def test_zur_auswertung_zaehlt_sie_mit(self, zeile_im_entwurf):
        """Mit ``entwuerfe_zaehlen`` zählt die Zeile für die Auswertung."""
        from erfassung.models import Erfassungszeile

        vorschau = erfassung_services.abrechnungsvorschau(
            list(Erfassungszeile.objects.filter(
                erfassung_services.NOCH_NICHT_ABGERECHNET, abrechenbar=True)),
            entwuerfe_zaehlen=True)

        assert len(vorschau.positionen) == 1
        assert vorschau.netto == Decimal('179.00')

    def test_die_offene_leistung_zaehlt_sie_als_offen(self, zeile_im_entwurf):
        """Die offene Leistung zählt die Zeile als offen.

        Regression: Die offene Leistung fiel beim Anlegen des
        Rechnungsentwurfs von 179,00 auf 0,00 (Karte "Noch abzurechnen",
        Projektakte, Liegenliste, Altersstaffel, über R-072 auch Ergebnis,
        Marge, Stundensatz, Deckungsbeitrag). Zwei Stunden zu 89,50 EUR
        ergeben 179,00 EUR.
        """
        assert erfassung_services.offene_leistung_gesamt() == Decimal('179.00')

    def test_die_altersstaffel_zaehlt_sie_ebenfalls(self, zeile_im_entwurf):
        """Die Altersstaffel verwendet denselben Schalter wie die Summe
        darüber."""
        klassen = erfassung_services.offene_leistung_nach_alter()

        assert sum((k.betrag for k in klassen), Decimal('0.00')) == Decimal('179.00')

    def test_die_auslastung_zaehlt_sie_ebenfalls_als_offen(self, zeile_im_entwurf):
        """Die Auslastung zählt die Zeile als offen; beide Filter verwenden
        ``NOCH_NICHT_ABGERECHNET``, einmal negiert. Regression: Dieselbe
        Stunde galt einmal als offen und einmal als verkauft."""
        auslastung = erfassung_services.auslastung_je_person()[0]

        assert auslastung.minuten_offen == 120
        assert auslastung.minuten_abgerechnet == 0

    def test_die_auftragsakte_zaehlt_sie_ebenfalls(self, projekt, person):
        """Die Auftragsakte zählt die Zeile als offen.

        Regression: Die Karte "Erfasst, nicht berechnet" filterte über
        ``Zustand.OFFEN``, der die Zeile im Entwurf ausschließt.
        """
        auftrag = beleg_mit(BelegTyp.AUFTRAG, projekt=projekt, nummer='AB-1',
                            positionen=[(Decimal('10'), Decimal('89.50'),
                                         Decimal('19.00'))])
        auftragsposition = auftrag.positionen.first()

        # Mit Menge, weil bei Kontierung auf eine Auftragsposition deren
        # Einheit gilt; ohne ``art`` an der Belegposition gilt MENGE
        # (``_art_von``). Zwei Stunden ergeben die Menge 2.
        zeile = erfassung_services.zeile_erfassen(
            projekt=projekt, auftragsposition=auftragsposition,
            benutzer=person, beschreibung='', datum=HEUTE,
            menge=Decimal('2'))

        entwurf = beleg_mit(BelegTyp.RECHNUNG, projekt=projekt,
                            positionen=[(Decimal('2'), Decimal('89.50'),
                                         Decimal('19.00'))],
                            gegen=[auftragsposition],
                            status=BelegStatus.ENTWURF)
        zeile.abgerechnet_in = entwurf.positionen.first()
        zeile.save()

        stand = ergebnisse.auftragsstand(auftrag)

        assert stand.nicht_berechnet == Decimal('179.00')


# ══════════════════════════════════════════════════════════════════════════
# R-136: XML gegen Rechnung
# ══════════════════════════════════════════════════════════════════════════


class TestDasXmlGegenDieBelegsumme:

    def test_die_gesamtbetraege_im_xml_sind_die_der_rechnung(self, projekt, firma):
        """Die Gesamtbeträge im XML entsprechen der Rechnung.

        Der Empfänger validiert das XML maschinell und lehnt die Rechnung
        bei Abweichung ab.
        """
        from faktura import facturx

        beleg = beleg_mit(BelegTyp.RECHNUNG, projekt=projekt, nummer='RE-1',
                          positionen=KRUMME_POSITIONEN,
                          leistungsdatum=HEUTE)

        summen = faktura_services.belegsummen(beleg)
        xml = facturx.xml_erzeugen(beleg).decode('utf-8')

        assert f'>{summen.netto}<' in xml
        assert f'>{summen.brutto}<' in xml


# ══════════════════════════════════════════════════════════════════════════
# R-003: Wechsel des Steuersatzes in einer Rechnung
# ══════════════════════════════════════════════════════════════════════════


#: Dieselbe Leistung mit zwei Sätzen bei einer Änderung der Umsatzsteuer.
#
# Im zweiten Halbjahr 2020 lag der Regelsatz bei 16 %. Leistungen über den
# Stichtag hinweg hatten auf einer Rechnung beide Sätze.
#
# Die Aufteilung nach Leistungszeitraum erfolgt manuell; der Satz wird nicht
# nach Datum gewählt, es gilt der Satz an der Position.
SATZWECHSEL = [
    (Decimal('12'), Decimal('85.00'), Decimal('16.00')),   # bis zum Stichtag
    (Decimal('8.25'), Decimal('85.00'), Decimal('19.00')),  # danach
    (Decimal('25'), Decimal('12.00'), Decimal('5.00')),     # Druck, gesenkt
    (Decimal('10'), Decimal('12.00'), Decimal('7.00')),     # Druck, danach
]


class TestEinSatzwechselAufEinerRechnung:
    """Vier Steuersätze auf einem Beleg, zwei davon gesenkt.

    Die Steuer wird je Satz auf dessen Nettosumme gerechnet, damit sich
    Rundungsdifferenzen nicht summieren; mit vier Sätzen viermal.
    """

    @pytest.fixture
    def beleg(self, projekt):
        return beleg_mit(BelegTyp.RECHNUNG, projekt=projekt, nummer='RE-1',
                         positionen=SATZWECHSEL, leistungsdatum=HEUTE)

    def test_jeder_satz_bekommt_seinen_eigenen_anteil(self, beleg):
        summen = faktura_services.belegsummen(beleg)

        saetze = {a.satz for a in summen.anteile}
        assert saetze == {Decimal('19.00'), Decimal('16.00'),
                          Decimal('7.00'), Decimal('5.00')}

    def test_die_anteile_sind_absteigend_sortiert(self, beleg):
        """Die Anteile sind absteigend sortiert, der höchste Satz zuerst."""
        saetze = [a.satz for a in faktura_services.belegsummen(beleg).anteile]

        assert saetze == sorted(saetze, reverse=True)

    def test_netto_und_steuer_gehen_auf(self, beleg):
        summen = faktura_services.belegsummen(beleg)

        assert summen.netto == sum((a.netto for a in summen.anteile),
                                   Decimal('0.00'))
        assert summen.steuer == sum((a.steuer for a in summen.anteile),
                                    Decimal('0.00'))
        assert summen.brutto == summen.netto + summen.steuer

    def test_der_gesenkte_satz_rechnet_wie_jeder_andere(self, beleg):
        """16 % auf 1.020,00 EUR ergeben 163,20 EUR (manuell berechnet)."""
        anteile = {a.satz: a for a in faktura_services.belegsummen(beleg).anteile}

        assert anteile[Decimal('16.00')].netto == Decimal('1020.00')
        assert anteile[Decimal('16.00')].steuer == Decimal('163.20')
        assert anteile[Decimal('5.00')].netto == Decimal('300.00')
        assert anteile[Decimal('5.00')].steuer == Decimal('15.00')

    def test_die_listensumme_kommt_auf_dasselbe(self, beleg):
        """Die Listensumme ergibt dasselbe; SQL gruppiert nach (Beleg, Satz),
        also vier Gruppen für einen Beleg."""
        einzeln = faktura_services.belegsummen(beleg)
        ueber_liste = faktura_services.summe_ueber(
            Beleg.objects.filter(pk=beleg.pk))

        assert ueber_liste.netto == einzeln.netto
        assert ueber_liste.steuer == einzeln.steuer

    def test_das_xml_weist_jeden_satz_getrennt_aus(self, beleg, firma):
        """Das XML weist jeden Satz getrennt aus.

        Factur-X verlangt im Summenblock je Satz ein eigenes
        ``ApplicableTradeTax`` mit Basis, Betrag und Prozentsatz. Gezählt
        wird nur im Summenblock, weil auch jede Position ein solches
        Element enthält (bei vier Positionen und Sätzen acht im
        Dokument).
        """
        from faktura import facturx

        xml = facturx.xml_erzeugen(beleg).decode('utf-8')
        summenblock = xml.split('<ram:ApplicableHeaderTradeSettlement>')[1]

        for satz in ('19.00', '16.00', '7.00', '5.00'):
            assert f'>{satz}<' in summenblock
        assert summenblock.count('<ram:ApplicableTradeTax>') == 4

        # Bemessungsgrundlage je Satz, manuell berechnet.
        for netto in ('1020.00', '701.25', '300.00', '120.00'):
            assert f'<ram:BasisAmount>{netto}</ram:BasisAmount>' in summenblock


class TestDerGespeicherteSatzIstUnveraenderlich:
    """Der gespeicherte Steuersatz ist unveränderlich.

    Der Satz wird an die Position **kopiert**; eine Rechnung vom Juli 2020
    behält 16 %, auch nach Änderungen der Auswahl.
    """

    def test_ein_satz_ausserhalb_der_auswahlliste_rechnet_korrekt(self, projekt):
        """Ein Satz außerhalb der Auswahl wird korrekt berechnet.

        Die Auswahl betrifft nur das Formular; Belege mit einem neuen Satz
        (20 %) werden unabhängig davon berechnet. 20 % auf 1.700,00 EUR
        ergeben 340,00 EUR.
        """
        beleg = beleg_mit(
            BelegTyp.RECHNUNG, projekt=projekt, nummer='RE-1',
            positionen=[(Decimal('20'), Decimal('85.00'), Decimal('20.00'))])

        summen = faktura_services.belegsummen(beleg)

        assert summen.netto == Decimal('1700.00')
        assert summen.steuer == Decimal('340.00')
        assert summen.brutto == Decimal('2040.00')

    def test_der_satz_der_position_gilt_und_nicht_der_des_katalogs(
            self, projekt, stunde):
        """Es gilt der Satz der Position, nicht der des Katalogs.

        Eine Belegposition ist eine Kopie; Änderungen am Katalog ändern
        bestehende Belege nicht.
        """
        beleg = beleg_mit(
            BelegTyp.RECHNUNG, projekt=projekt, nummer='RE-1',
            positionen=[(Decimal('10'), Decimal('85.00'), Decimal('16.00'))])

        stunde.steuersatz = '19.00'
        stunde.save()

        position = beleg.positionen.first()
        assert position.steuersatz_dezimal == Decimal('16.00')
        assert faktura_services.belegsummen(beleg).steuer == Decimal('136.00')


# ══════════════════════════════════════════════════════════════════════════
# Umsatz eines Kunden: Akte gegen Auswertung (S-36 bis S-38)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestDieKundenakteGegenDieAuftraggeberstruktur:
    """Umsatz eines Kunden in Kundenakte und Auswertung.

    ``services.umsatz_je_kunde`` gruppiert in SQL mit ``Coalesce`` vom Beleg
    auf dessen Projekt; die Kundenakte filtert in Python mit
    ``Q(kunde=…) | Q(projekt__kunde=…)``. Im Referenzbetrieb **S-36 bis
    S-38** (Abschnitt F).

    Regression: Die Akte zeigte für einen Kunden mit vierzehn Belegen 0 €,
    die Auswertung den richtigen Wert; die Akte hatte keinen Sollwert, nur
    der Vergleich fand den Fehler. Ursache waren Belege am **Projekt**, an
    denen ``kunde_id`` leer ist (``kunde_oder_projekt_nicht_beides``).
    """

    def _akte(self, kunde) -> Decimal:
        from auswertung import kundenakte
        return kundenakte._zahlen(kunde)['umsatz_netto']

    def _auswertung(self, kunde) -> Decimal:
        zeilen = faktura_services.umsatz_je_kunde()
        return next((z.netto for z in zeilen
                     if z.kunde and z.kunde.pk == kunde.pk), Decimal('0.00'))

    def test_ein_beleg_am_projekt_zaehlt_auf_beiden_wegen(
            self, kunde, projekt):
        beleg_mit(BelegTyp.RECHNUNG, projekt=projekt,
                  positionen=[(Decimal('12.5'), Decimal('89.50'),
                               '19.00')],
                  nummer='RE-800')

        assert self._akte(kunde) == self._auswertung(kunde)
        assert self._akte(kunde) > Decimal('0.00')

    def test_beide_wege_zaehlen_projekt_und_kunde_zusammen(
            self, kunde, projekt):
        """Ein Beleg am Projekt und einer direkt am Kunden; beide Wege zählen
        beide. Mit nur einem Träger ergäbe sich die Hälfte."""
        beleg_mit(BelegTyp.RECHNUNG, projekt=projekt,
                  positionen=[(Decimal('10'), Decimal('100.00'),
                               '19.00')],
                  nummer='RE-801')
        beleg_mit(BelegTyp.RECHNUNG, kunde=kunde,
                  positionen=[(Decimal('4'), Decimal('250.00'),
                               '19.00')],
                  nummer='RE-802')

        assert self._akte(kunde) == Decimal('2000.00')
        assert self._auswertung(kunde) == self._akte(kunde)

    def test_ein_storno_mindert_auf_beiden_wegen(self, kunde, projekt):
        """S-37: Das Storno mindert auf beiden Wegen."""
        beleg_mit(BelegTyp.RECHNUNG, projekt=projekt,
                  positionen=[(Decimal('10'), Decimal('100.00'),
                               '19.00')],
                  nummer='RE-803')
        beleg_mit(BelegTyp.STORNO, projekt=projekt,
                  positionen=[(Decimal('-10'), Decimal('100.00'),
                               '19.00')],
                  nummer='ST-803')

        assert self._akte(kunde) == self._auswertung(kunde)
