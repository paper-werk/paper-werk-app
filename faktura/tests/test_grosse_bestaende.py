"""Optimierte Berechnungen für große Datenbestände.

Der Lasttest (zehn Jahre Daten) zeigte die Kosten beim Laden aller Belege
als Objekte. Die optimierten Implementierungen rechnen anders; jeder Test
prüft **das Ergebnis gegen die alte Regel als Referenz**, auf den Cent und
mit Beträgen, bei denen die Rundung zählt.

Dazu Tests, dass die Zahl der SQL-Abfragen einer Liste nicht mit der Zahl
ihrer Zeilen wächst.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from faktura import services
from faktura.models import (
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Kontakt,
    Projekt,
    Zahlung,
    Zahlungszuordnung,
)

pytestmark = pytest.mark.django_db

HEUTE = timezone.localdate()


@pytest.fixture
def kunde(db):
    return Kontakt.objects.create(nummer='K-7000', name='Stadt Beispiel')


@pytest.fixture
def anderer_kunde(db):
    return Kontakt.objects.create(nummer='K-7001', name='Gemeinde Nebenan')


def _beleg(*, kunde=None, projekt=None, positionen, nummer,
           typ=BelegTyp.RECHNUNG, status=BelegStatus.FESTGESCHRIEBEN,
           faellig_vor_tagen=10):
    """Beleg mit beliebigen Positionen, am Modell festgeschrieben, wie in
    ``test_listen.py``."""
    beleg = Beleg.objects.create(typ=typ, kunde=kunde, projekt=projekt)
    for nr, (menge, preis, satz) in enumerate(positionen, start=1):
        Belegposition.objects.create(
            beleg=beleg, position=nr * 10, bezeichnung=f'Position {nr}',
            menge=Decimal(menge), einheit='Std',
            einzelpreis=Decimal(preis), steuersatz=satz)
    if status == BelegStatus.ENTWURF:
        # Festgeschrieben mit Nummer und Datum, wie der Constraint
        # verlangt.
        return beleg
    beleg.status = status
    beleg.nummer = nummer
    beleg.belegdatum = HEUTE - timedelta(days=40)
    beleg.faellig_am = HEUTE - timedelta(days=faellig_vor_tagen)
    beleg.save()
    return beleg


def _zahlen(kunde, beleg, betrag, skonto='0.00'):
    zahlung = Zahlung.objects.create(datum=HEUTE, betrag=Decimal(betrag),
                                     kunde=kunde)
    Zahlungszuordnung.objects.create(
        zahlung=zahlung, beleg=beleg, betrag=Decimal(betrag),
        skonto=Decimal(skonto))


@pytest.fixture
def bestand(kunde, anderer_kunde):
    """Datenbestand mit allen Fällen, die "offen" bestimmen.

    Beträge, bei denen die Rundung zählt: dreistellige Mengen, ungerade
    Preise, zwei Steuersätze auf einem Beleg, weil die Steuer je Satz auf
    die Nettosumme gerechnet wird.
    """
    krumm = [('0.333', '3.33', '19.00'),
             ('2.125', '19.99', '19.00'),
             ('7.777', '1.11', '7.00')]
    b = {}
    b['offen'] = _beleg(kunde=kunde, positionen=krumm, nummer='RE-1')
    b['teilbezahlt'] = _beleg(kunde=kunde, positionen=[
        ('1', '1000.00', '19.00')], nummer='RE-2')
    _zahlen(kunde, b['teilbezahlt'], '500.00')
    b['bezahlt'] = _beleg(kunde=kunde, positionen=[
        ('1', '1000.00', '19.00')], nummer='RE-3')
    _zahlen(kunde, b['bezahlt'], '1190.00')
    b['mit_skonto'] = _beleg(kunde=kunde, positionen=[
        ('1', '1000.00', '19.00')], nummer='RE-4')
    _zahlen(kunde, b['mit_skonto'], '1166.20', skonto='23.80')
    b['einen_cent_offen'] = _beleg(kunde=kunde, positionen=krumm,
                                   nummer='RE-5')
    brutto = services.belegsummen(b['einen_cent_offen']).brutto
    _zahlen(kunde, b['einen_cent_offen'], str(brutto - Decimal('0.01')))
    b['ueberzahlt'] = _beleg(kunde=kunde, positionen=[
        ('1', '100.00', '19.00')], nummer='RE-6')
    _zahlen(kunde, b['ueberzahlt'], '200.00')
    b['ohne_positionen'] = _beleg(kunde=kunde, positionen=[], nummer='RE-7')
    b['steuerfrei'] = _beleg(kunde=kunde, positionen=[
        ('3', '33.33', '0.00')], nummer='RE-8')
    b['noch_nicht_faellig'] = _beleg(kunde=kunde, positionen=krumm,
                                     nummer='RE-9', faellig_vor_tagen=-14)
    b['storniert'] = _beleg(kunde=kunde, positionen=krumm, nummer='RE-10',
                            status=BelegStatus.STORNIERT)
    b['entwurf'] = _beleg(kunde=kunde, positionen=krumm, nummer='',
                          status=BelegStatus.ENTWURF)
    b['angebot'] = _beleg(kunde=kunde, positionen=krumm, nummer='AN-1',
                          typ=BelegTyp.ANGEBOT)
    projekt = Projekt.objects.create(nummer='2026-700', bezeichnung='Vorhaben',
                                     kunde=anderer_kunde)
    b['fremd'] = _beleg(projekt=projekt, positionen=krumm, nummer='RE-11')
    return b


def _alte_regel(belege=None):
    """Referenzimplementierung der offenen Posten: jede festgeschriebene
    Rechnung berechnen und die ausgeglichenen auslassen."""
    rechnungen = Beleg.objects.filter(typ=BelegTyp.RECHNUNG,
                                      status=BelegStatus.FESTGESCHRIEBEN)
    if belege is not None:
        rechnungen = rechnungen.filter(pk__in=belege)
    posten = []
    for r in rechnungen:
        brutto = services.belegsummen(r).brutto
        zuordnungen = list(r.zahlungszuordnungen.all())
        bezahlt = sum((z.betrag for z in zuordnungen), Decimal('0.00'))
        offen = brutto - sum((z.ausgleich for z in zuordnungen),
                             Decimal('0.00'))
        if offen > 0:
            posten.append((r.pk, brutto, bezahlt, offen,
                           (HEUTE - r.faellig_am).days))
    posten.sort(key=lambda p: (-(p[4] or 0), Beleg.objects.get(pk=p[0]).nummer))
    return posten


def _als_tupel(stand):
    return [(p.beleg.pk, p.brutto, p.bezahlt, p.offen, p.tage_ueberfaellig)
            for p in stand.posten]


class TestBruttosummen:

    def test_jeder_beleg_auf_den_cent_wie_belegsummen(self, bestand):
        brutto = services.bruttosummen(Beleg.objects.all())

        for beleg in Beleg.objects.all():
            assert brutto.get(beleg.pk, Decimal('0.00')) == (
                services.belegsummen(beleg).brutto), beleg.nummer

    def test_ein_beleg_ohne_positionen_fehlt(self, bestand):
        assert bestand['ohne_positionen'].pk not in services.bruttosummen(
            Beleg.objects.all())


class TestOffenePosten:
    """R-149: zweistufige Berechnung gegen die Referenz."""

    def test_dieselben_posten_mit_denselben_betraegen(self, bestand):
        assert _als_tupel(services.offene_posten()) == _alte_regel()

    def test_der_bestand_prueft_wirklich_etwas(self, bestand):
        """Gegenprobe: Offen sind genau die erwarteten, damit der Vergleich
        nicht zwei leere Listen betrifft."""
        offen = {p.beleg.pk for p in services.offene_posten().posten}

        erwartet = {bestand[n].pk for n in (
            'offen', 'teilbezahlt', 'einen_cent_offen', 'steuerfrei',
            'noch_nicht_faellig', 'fremd')}
        assert offen == erwartet

    def test_eingeschraenkt_auf_die_belege_eines_kunden(self, bestand, kunde):
        belege = Beleg.objects.filter(kunde=kunde)

        assert _als_tupel(services.offene_posten(belege=belege)) == (
            _alte_regel(belege))
        assert bestand['fremd'].pk not in {
            p.beleg.pk for p in services.offene_posten(belege=belege).posten}

    def test_ohne_rechnungen_ist_nichts_offen(self, db):
        assert services.offene_posten().posten == []


class TestAbfragenDerListen:
    """Die Zahl der Abfragen einer Liste ist unabhängig von der Zahl ihrer
    Zeilen."""

    def _abfragen(self, client, url):
        with CaptureQueriesContext(connection) as abfragen:
            antwort = client.get(url)
        assert antwort.status_code == 200
        return len(abfragen.captured_queries)

    @pytest.mark.parametrize('liste', ['rechnung', 'angebot'])
    def test_doppelt_so_viele_belege_gleich_viele_abfragen(
            self, verwaltung, kunde, liste):
        typ = BelegTyp.RECHNUNG if liste == 'rechnung' else BelegTyp.ANGEBOT
        positionen = [('2', '50.00', '19.00'),
                      ('1', '10.00', '7.00')]
        url = reverse(f'admin:faktura_{liste}_changelist')

        for i in range(3):
            _beleg(kunde=kunde, positionen=positionen, nummer=f'X-{i}', typ=typ)
        wenige = self._abfragen(verwaltung, url)
        for i in range(3, 9):
            _beleg(kunde=kunde, positionen=positionen, nummer=f'X-{i}', typ=typ)
        viele = self._abfragen(verwaltung, url)

        assert viele == wenige


class TestKundenUndProjekteAlsSuchfeld:
    """Die Filter für Kunde und Projekt laden keine Choices vor, sondern
    suchen bei Eingabe. Geprüft wird, dass der Parameter filtert und die
    Abfrage des Suchfelds den Kunden findet."""

    def test_die_belegliste_laedt_keine_kunden_vor(self, verwaltung, kunde):
        for i in range(30):
            Kontakt.objects.create(nummer=f'K-8{i:03d}', name=f'Vorladekunde {i}')

        inhalt = verwaltung.get(
            reverse('admin:faktura_rechnung_changelist')).content.decode()

        assert 'Vorladekunde' not in inhalt
        assert 'data-ajax--url' in inhalt

    def test_kunde_filtert_auch_ueber_das_projekt(self, verwaltung, kunde,
                                                    anderer_kunde):
        projekt = Projekt.objects.create(nummer='2026-701', bezeichnung='V',
                                         kunde=kunde)
        positionen = [('1', '10.00', '19.00')]
        direkt = _beleg(kunde=kunde, positionen=positionen, nummer='RE-D')
        ueber_projekt = _beleg(projekt=projekt, positionen=positionen,
                               nummer='RE-P')
        fremd = _beleg(kunde=anderer_kunde, positionen=positionen,
                       nummer='RE-F')

        antwort = verwaltung.get(reverse('admin:faktura_rechnung_changelist'),
                                 {'kunde': kunde.pk})

        gezeigt = {b.pk for b in antwort.context['cl'].result_list}
        assert gezeigt == {direkt.pk, ueber_projekt.pk}
        assert fremd.pk not in gezeigt

    def test_das_suchfeld_findet_den_kunden(self, verwaltung, kunde):
        antwort = verwaltung.get(reverse('admin:autocomplete'), {
            'app_label': 'faktura', 'model_name': 'beleg',
            'field_name': 'kunde', 'term': 'Beispiel'})

        assert antwort.status_code == 200
        assert [r['id'] for r in antwort.json()['results']] == [str(kunde.pk)]

    def test_das_projektfeld_findet_das_projekt(self, verwaltung, kunde):
        projekt = Projekt.objects.create(nummer='2026-702',
                                         bezeichnung='Kita Nord', kunde=kunde)

        antwort = verwaltung.get(reverse('admin:autocomplete'), {
            'app_label': 'faktura', 'model_name': 'beleg',
            'field_name': 'projekt', 'term': '2026-702'})

        assert antwort.status_code == 200
        assert [r['id'] for r in antwort.json()['results']] == [str(projekt.pk)]
