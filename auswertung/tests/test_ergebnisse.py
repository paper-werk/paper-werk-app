"""Projektergebnis über faktura und erfassung (auswertung/ergebnisse.py).

Geprüft wird, dass keine der vier Quellen fehlt und keine doppelt zählt:

    fakturiert            was der Kunde bekommen hat        (faktura)
    offene Leistung       eigene Stunden, noch ohne Beleg   (erfassung)
    offene Fremdleistung  Zugekauftes, noch ohne Beleg      (erfassung)
    Kosten                Stunden mal Satz + Einkauf        (erfassung)
"""

from datetime import date, time
from decimal import Decimal

import pytest

from auswertung import ergebnisse
from erfassung import services as erfassung_services
from erfassung.models import Eingangsrechnung, Fremdleistung, Kostensatz
from faktura.models import (
    BelegStatus,
    Katalogposition,
    Kontakt,
    Leistungsart,
    Projekt,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def kunde(db):
    return Kontakt.objects.create(nummer='K-9000', name='Stadt Altdorf')


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(
        nummer='2026-042', bezeichnung='Schadstofferkundung Turnhalle',
        kunde=kunde)


@pytest.fixture
def ingenieurstunde(db):
    return Katalogposition.objects.create(
        bezeichnung='Ingenieurstunde', einheit='Std',
        einzelpreis=Decimal('95.00'), kontierbar=True, art=Leistungsart.ZEIT)


@pytest.fixture
def person(django_user_model):
    mensch = django_user_model.objects.create_user(
        username='bach', password='geheim12345', is_staff=True)
    Kostensatz.objects.create(
        benutzer=mensch, gueltig_ab=date(2026, 1, 1), satz=Decimal('55.00'))
    return mensch


@pytest.fixture
def labor(db):
    return Kontakt.objects.create(ist_kunde=False, ist_lieferant=True, name='ISARTAL')


def _stunden(projekt, leistung, person, von, bis):
    return erfassung_services.zeile_erfassen(
        projekt=projekt, leistung=leistung, benutzer=person,
        beschreibung='Probenahme', datum=date(2026, 8, 10), von=von, bis=bis)


def _laborkosten(labor, projekt, *, einkauf, menge=Decimal('1'),
                 auftragsposition=None):
    """Fremdleistung mit Einkaufspreis; der Verkaufspreis entsteht beim
    Übernehmen in die Rechnung."""
    rechnung = Eingangsrechnung.objects.create(
        lieferant=labor, nummer=f'RE-{einkauf}-{menge}',
        datum=date(2026, 8, 12), betrag_netto=einkauf * menge)
    return Fremdleistung.objects.create(
        rechnung=rechnung, projekt=projekt, bezeichnung='Analysenpaket',
        einheit='Stk', menge=menge, einkaufspreis=einkauf,
        auftragsposition=auftragsposition)


def _laborauftrag(projekt):
    """Auftrag über 4 Analysen zu 145,00, festgeschrieben wie ``_auftrag``."""
    from faktura.models import Beleg, Belegposition, BelegTyp
    beleg = Beleg.objects.create(typ=BelegTyp.AUFTRAG, projekt=projekt)
    position = Belegposition.objects.create(
        beleg=beleg, position=10, bezeichnung='Analysenpaket LAGA',
        menge=Decimal('4'), einheit='Stk', einzelpreis=Decimal('145.00'))
    beleg.status = BelegStatus.FESTGESCHRIEBEN
    beleg.nummer = f'AB-{projekt.nummer}-L'
    beleg.belegdatum = date(2026, 7, 1)
    beleg.save()
    return position


def _auftrag(projekt, betrag):
    """Festgeschriebener Auftrag über diesen Betrag.

    Direkt am Modell festgeschrieben, Begründung bei
    test_abgerechnetes_zaehlt_einmal_und_nicht_zweimal.
    """
    from faktura.models import Beleg, Belegposition, BelegTyp
    # Entwurf, Position, dann festschreiben, weil das Modell Positionen an
    # festgeschriebenen Belegen ablehnt.
    beleg = Beleg.objects.create(
        typ=BelegTyp.AUFTRAG, projekt=projekt)
    Belegposition.objects.create(
        beleg=beleg, position=10, bezeichnung='Pauschalhonorar',
        menge=Decimal('1'), einheit='pausch', einzelpreis=betrag)
    beleg.status = BelegStatus.FESTGESCHRIEBEN
    beleg.nummer = f'AB-{projekt.nummer}'
    beleg.belegdatum = date(2026, 7, 1)
    beleg.save()
    return beleg


def _ergebnis(projekt):
    return ergebnisse.projektergebnisse().je_projekt()[projekt.pk]


def _rechnung(projekt, betrag, *, art, nummer):
    """Festgeschriebene Rechnung, normal oder als Abschlag, wie ``_auftrag``."""
    from faktura.models import Beleg, Belegposition, BelegTyp, Rechnungsart

    beleg = Beleg.objects.create(
        typ=BelegTyp.RECHNUNG, projekt=projekt,
        rechnungsart=art or Rechnungsart.NORMAL)
    Belegposition.objects.create(
        beleg=beleg, position=10, bezeichnung='Teilleistung',
        menge=Decimal('1'), einheit='pausch', einzelpreis=betrag)
    beleg.status = BelegStatus.FESTGESCHRIEBEN
    beleg.nummer = nummer
    beleg.belegdatum = date(2026, 8, 1)
    beleg.save()
    return beleg


class TestDerAbschlagZaehltNichtDoppelt:
    """Ein Abschlag zählt nicht doppelt im Leistungswert.

    Regression: ``leistungswert`` war ``fakturiert + nicht_abgerechnet``. Ein
    Abschlag erhöht ``fakturiert``, rechnet aber keine Erfassungszeilen ab
    (``abgerechnet_in`` bleibt leer); dieselbe Leistung zählte als Forderung
    und als offene Leistung. Im Demobestand ergab das 60 Prozent Marge,
    richtig waren 41.

    Dieselbe Regel gilt in ``faktura/services.py`` für das Mengenkontingent.
    """

    def test_ein_abschlag_erhoeht_den_leistungswert_nicht(
            self, projekt, ingenieurstunde, person):
        """Zehn Stunden und ein Abschlag: Der Leistungswert bleibt der Wert
        der zehn Stunden."""
        from faktura.models import Rechnungsart

        _auftrag(projekt, Decimal('10000.00'))
        _stunden(projekt, ingenieurstunde, person,
                 time(8, 0), time(18, 0))
        ohne_abschlag = _ergebnis(projekt).leistungswert

        _rechnung(projekt, Decimal('600.00'),
                  art=Rechnungsart.ABSCHLAG, nummer='AR-1')

        assert _ergebnis(projekt).leistungswert == ohne_abschlag

    def test_der_abschlag_steht_trotzdem_im_fakturierten(
            self, projekt, ingenieurstunde, person):
        """Gegenprobe: Der Abschlag zählt im Fakturierten als Forderung."""
        from faktura.models import Rechnungsart

        _auftrag(projekt, Decimal('10000.00'))
        _rechnung(projekt, Decimal('600.00'),
                  art=Rechnungsart.ABSCHLAG, nummer='AR-1')

        ergebnis = _ergebnis(projekt)
        assert ergebnis.fakturiert == Decimal('600.00')
        assert ergebnis.abgerechnete_leistung == Decimal('0.00')

    def test_eine_gewoehnliche_rechnung_zaehlt_weiterhin(
            self, projekt, ingenieurstunde, person):
        """Eine gewöhnliche Rechnung rechnet die Leistung ab und zählt."""
        from faktura.models import Rechnungsart

        _auftrag(projekt, Decimal('10000.00'))
        _rechnung(projekt, Decimal('600.00'),
                  art=Rechnungsart.NORMAL, nummer='RE-1')

        ergebnis = _ergebnis(projekt)
        assert ergebnis.abgerechnete_leistung == Decimal('600.00')
        assert ergebnis.leistungswert == Decimal('600.00')

    @pytest.mark.parametrize('art', ['schluss', 'teilschluss'])
    def test_die_absetzung_mindert_die_leistung_nicht(self, projekt, art):
        """Die Absetzung des Abschlags in der Schlussrechnung mindert die
        Leistung nicht.

        Die Schlussrechnung führt die volle Leistung auf und setzt den
        Abschlag mit einer negativen Zeile ab. Weil der Abschlag nicht zählt,
        darf auch die Absetzung nicht zählen.
        """
        from faktura.models import Rechnungsart

        _auftrag(projekt, Decimal('10000.00'))
        abschlag = _rechnung(projekt, Decimal('600.00'),
                             art=Rechnungsart.ABSCHLAG, nummer='AR-1')
        _schlussrechnung(projekt, Decimal('1000.00'), art=art,
                         absetzen=abschlag)

        ergebnis = _ergebnis(projekt)
        assert ergebnis.abgerechnete_leistung == Decimal('1000.00')
        assert ergebnis.leistungswert == Decimal('1000.00')
        # Fakturiert ist der Gesamtbetrag an den Kunden.
        assert ergebnis.fakturiert == Decimal('1000.00')

    def test_das_storno_eines_abschlags_mindert_die_leistung_nicht(
            self, projekt):
        """Das Storno eines Abschlags mindert die Leistung nicht.

        Das Storno hat keine Rechnungsart; maßgeblich ist der Vorgänger.
        """
        from faktura.models import Rechnungsart

        _auftrag(projekt, Decimal('10000.00'))
        abschlag = _rechnung(projekt, Decimal('600.00'),
                             art=Rechnungsart.ABSCHLAG, nummer='AR-1')
        _storno(abschlag, nummer='ST-1')

        ergebnis = _ergebnis(projekt)
        assert ergebnis.abgerechnete_leistung == Decimal('0.00')
        assert ergebnis.fakturiert == Decimal('0.00')

    def test_das_storno_einer_rechnung_mindert_die_leistung_weiterhin(
            self, projekt):
        """Gegenprobe: Das Storno einer gewöhnlichen Rechnung mindert die
        Leistung."""
        from faktura.models import Rechnungsart

        _auftrag(projekt, Decimal('10000.00'))
        rechnung = _rechnung(projekt, Decimal('600.00'),
                             art=Rechnungsart.NORMAL, nummer='RE-1')
        _storno(rechnung, nummer='ST-1')

        assert _ergebnis(projekt).abgerechnete_leistung == Decimal('0.00')


def _schlussrechnung(projekt, betrag, *, art, absetzen):
    """Festgeschriebene (Teil-)Schlussrechnung über die volle Leistung mit
    Abzugszeile wie aus ``abschlaege_absetzen``, festgeschrieben wie
    ``_auftrag``."""
    from faktura.models import Beleg, Belegposition, BelegTyp

    beleg = Beleg.objects.create(typ=BelegTyp.RECHNUNG, projekt=projekt,
                                 rechnungsart=art)
    Belegposition.objects.create(
        beleg=beleg, position=10, bezeichnung='Leistung', menge=Decimal('1'),
        einheit='pausch', einzelpreis=betrag)
    quelle = absetzen.positionen.get()
    Belegposition.objects.create(
        beleg=beleg, position=20, bezeichnung=f'Abschlag {absetzen.nummer}',
        menge=quelle.menge, einheit=quelle.einheit,
        einzelpreis=-quelle.einzelpreis, ist_abzug=True,
        abgesetzte_position=quelle)
    beleg.status = BelegStatus.FESTGESCHRIEBEN
    beleg.nummer = 'SR-1'
    beleg.belegdatum = date(2026, 9, 1)
    beleg.save()
    return beleg


def _storno(beleg, *, nummer):
    """Festgeschriebenes Storno mit gespiegelter Position; der Vorgänger ist
    danach storniert, wie nach ``beleg_stornieren``."""
    from faktura.models import Beleg, Belegposition, BelegTyp

    storno = Beleg.objects.create(typ=BelegTyp.STORNO,
                                  projekt=beleg.projekt, vorgaenger=beleg)
    for p in beleg.positionen.all():
        Belegposition.objects.create(
            beleg=storno, position=p.position, bezeichnung=p.bezeichnung,
            menge=p.menge, einheit=p.einheit, einzelpreis=-p.einzelpreis,
            ist_abzug=p.ist_abzug)
    storno.status = BelegStatus.FESTGESCHRIEBEN
    storno.nummer = nummer
    storno.belegdatum = date(2026, 8, 15)
    storno.save()
    Beleg.objects.filter(pk=beleg.pk).update(status=BelegStatus.STORNIERT)
    return storno


# ── Quellen ──────────────────────────────────────────────────────────────────

class TestWasZaehlt:

    def test_ein_leeres_vorhaben_ist_bei_null(self, projekt):
        ergebnis = _ergebnis(projekt)

        assert ergebnis.leistungswert == Decimal('0.00')
        assert ergebnis.kosten == Decimal('0.00')
        assert ergebnis.ergebnis == Decimal('0.00')
        assert ergebnis.marge is None

    def test_erfasste_stunden_zaehlen_als_erloes_auch_ohne_rechnung(
            self, projekt, ingenieurstunde, person):
        """Erfasste Stunden zählen als Erlös, auch ohne Rechnung."""
        _stunden(projekt, ingenieurstunde, person, time(8, 0), time(12, 0))

        ergebnis = _ergebnis(projekt)

        # 4 Std zu 95,00 Erlös, 4 Std zu 55,00 Kosten.
        assert ergebnis.offene_leistung == Decimal('380.00')
        assert ergebnis.personalkosten == Decimal('220.00')
        assert ergebnis.ergebnis == Decimal('160.00')
        assert ergebnis.marge == 42

    def test_offenes_labor_zaehlt_im_einkauf(self, projekt, labor):
        """Nicht abgerechnete Laborleistung zählt zum Einkaufspreis als
        Untergrenze; die Spanne entsteht an der Rechnung."""
        _laborkosten(labor, projekt, einkauf=Decimal('96.00'),
                     menge=Decimal('4'))

        ergebnis = _ergebnis(projekt)

        assert ergebnis.offene_fremdleistung == Decimal('384.00')
        assert ergebnis.fremdkosten == Decimal('384.00')
        assert ergebnis.ergebnis == Decimal('0.00')

    def test_die_spanne_des_labors_kommt_mit_der_rechnung(
            self, projekt, labor):
        """Mit Auftragsposition gilt beim Übernehmen der Vertragspreis:
        4 x 145,00 = 580,00 fakturiert gegen 384,00 Einkauf. Der
        Leistungswert steigt um den Aufschlag."""
        _laborkosten(labor, projekt, einkauf=Decimal('96.00'),
                     menge=Decimal('4'),
                     auftragsposition=_laborauftrag(projekt))
        vorher = _ergebnis(projekt)

        beleg, _ = erfassung_services.in_rechnung_uebernehmen(
            zeilen=[], fremdleistungen=Fremdleistung.objects.all())
        beleg.status = BelegStatus.FESTGESCHRIEBEN
        beleg.nummer = '2026-0002'
        beleg.save()

        nachher = _ergebnis(projekt)
        assert vorher.leistungswert == Decimal('384.00')
        assert nachher.fakturiert == Decimal('580.00')
        assert nachher.offene_fremdleistung == Decimal('0.00')
        assert nachher.fremdkosten == Decimal('384.00')
        assert nachher.ergebnis == Decimal('196.00')

    def test_was_wir_selbst_tragen_zieht_das_ergebnis_herunter(
            self, projekt, labor):
        """Nicht weiterberechnete Fremdleistung zählt als Kosten ohne Erlös."""
        position = _laborkosten(labor, projekt, einkauf=Decimal('200.00'))
        position.weiterberechenbar = False
        position.save()

        ergebnis = _ergebnis(projekt)

        assert ergebnis.offene_fremdleistung == Decimal('0.00')
        assert ergebnis.fremdkosten == Decimal('200.00')
        assert ergebnis.ergebnis == Decimal('-200.00')
        assert not ergebnis.traegt

    def test_der_entwurf_laesst_die_leistung_offen(self, projekt, labor):
        """Leistung auf einem Rechnungsentwurf bleibt offen.

        Als abgerechnet fiele sie aus beiden Summen: aus dem Offenen, weil
        ein Beleg daran hängt, und aus dem Fakturierten, weil Entwürfe dort
        nicht zählen.
        """
        _laborkosten(labor, projekt, einkauf=Decimal('96.00'),
                     menge=Decimal('4'))
        vorher = _ergebnis(projekt).leistungswert

        erfassung_services.in_rechnung_uebernehmen(
            zeilen=[], fremdleistungen=Fremdleistung.objects.all())

        nachher = _ergebnis(projekt)
        assert nachher.leistungswert == vorher == Decimal('384.00')
        assert nachher.offene_fremdleistung == Decimal('384.00')
        assert nachher.fakturiert == Decimal('0.00')

    def test_abgerechnetes_zaehlt_einmal_und_nicht_zweimal(
            self, projekt, labor):
        """Abgerechnete Leistung zählt einmal.

        Nach dem Festschreiben steht die Laborleistung in ``fakturiert`` und
        nicht mehr als offen; der Leistungswert ist vor und nach dem
        Abrechnen gleich.

        Festgeschrieben wird direkt am Modell, weil der Service Firma,
        Anschrift, Leistungsdatum, Nummernkreis und PDF voraussetzt, die mit
        dem Projektergebnis nichts zu tun haben (wie in
        erfassung/conftest.py).
        """
        _laborkosten(labor, projekt, einkauf=Decimal('96.00'),
                     menge=Decimal('4'))
        vorher = _ergebnis(projekt).leistungswert

        beleg, _ = erfassung_services.in_rechnung_uebernehmen(
            zeilen=[], fremdleistungen=Fremdleistung.objects.all())
        beleg.status = BelegStatus.FESTGESCHRIEBEN
        beleg.nummer = '2026-0001'
        beleg.save()

        nachher = _ergebnis(projekt)
        # Ohne Auftragsposition weiterberechnet: Rechnungsbetrag gleich
        # Einkauf.
        assert nachher.leistungswert == vorher == Decimal('384.00')
        assert nachher.fakturiert == Decimal('384.00')
        assert nachher.offene_fremdleistung == Decimal('0.00')
        assert nachher.ergebnis == Decimal('0.00')


# ── Stunden ohne Kostensatz ──────────────────────────────────────────────────

class TestOhneKostensatz:

    def test_die_uebersicht_sagt_wenn_die_zahlen_zu_gut_sind(
            self, projekt, ingenieurstunde, django_user_model):
        namenlos = django_user_model.objects.create_user(
            username='ohnesatz', password='geheim12345')
        _stunden(projekt, ingenieurstunde, namenlos, time(8, 0), time(12, 0))

        uebersicht = ergebnisse.projektergebnisse()

        assert not uebersicht.vollstaendig
        assert uebersicht.ohne_kostensatz == {namenlos.pk}
        assert uebersicht.minuten_ohne_satz == 240
        # Erlös ohne Kosten; deshalb der Hinweis.
        assert uebersicht.je_projekt()[projekt.pk].ergebnis == Decimal('380.00')


# ── Übersicht ────────────────────────────────────────────────────────────────

class TestDieReihenfolge:

    @pytest.fixture
    def zwei_vorhaben(self, kunde, labor, ingenieurstunde, person):
        gut = Projekt.objects.create(
            nummer='2026-001', bezeichnung='Läuft', kunde=kunde)
        schlecht = Projekt.objects.create(
            nummer='2026-002', bezeichnung='Läuft nicht', kunde=kunde)
        _stunden(gut, ingenieurstunde, person, time(8, 0), time(12, 0))
        position = _laborkosten(labor, schlecht, einkauf=Decimal('500.00'))
        position.weiterberechenbar = False
        position.save()
        return gut, schlecht

    def test_die_vorgabe_ordnet_nach_auftragsbestand(self, zwei_vorhaben):
        """Dieselbe Reihenfolge wie projektstaende."""
        uebersicht = ergebnisse.projektergebnisse()

        assert [z.projekt.nummer for z in uebersicht.zeilen] == [
            '2026-001', '2026-002']

    def test_nach_ergebnis_steht_das_schlechteste_oben(self, zwei_vorhaben):
        uebersicht = ergebnisse.projektergebnisse()

        zeilen = uebersicht.nach_ergebnis()

        assert zeilen[0].projekt.nummer == '2026-002'
        assert zeilen[0].ergebnis == Decimal('-500.00')

    def test_die_summen_zaehlen_alle_vorhaben(self, zwei_vorhaben):
        uebersicht = ergebnisse.projektergebnisse()

        assert uebersicht.ergebnis == Decimal('-340.00')
        assert uebersicht.kosten == Decimal('720.00')
        assert uebersicht.nicht_abgerechnet == Decimal('380.00')


class TestDasEinzelneVorhaben:

    def test_projektergebnis_findet_auch_abgeschlossene(
            self, projekt, ingenieurstunde, person):
        _stunden(projekt, ingenieurstunde, person, time(8, 0), time(12, 0))
        projekt.abgeschlossen = True
        projekt.save()

        assert ergebnisse.projektergebnisse().zeilen == []
        assert ergebnisse.projektergebnis(projekt).ergebnis == Decimal('160.00')


# ── Überschreitung ───────────────────────────────────────────────────────────

class TestDieUeberschreitung:
    """Leistung über den Auftragswert hinaus.

    Der Leistungswert bewertet jede Stunde zum Katalogpreis; bei einem
    Pauschalauftrag zahlt der Kunde nur den Auftragswert. Die
    Überschreitung wird angezeigt und nicht verrechnet, weil die Vertragsart
    nicht erfasst ist.
    """

    def test_ohne_auftrag_gibt_es_nichts_zu_ueberschreiten(
            self, projekt, ingenieurstunde, person):
        _stunden(projekt, ingenieurstunde, person, time(8, 0), time(12, 0))

        ergebnis = _ergebnis(projekt)

        assert ergebnis.beauftragt == Decimal('0.00')
        assert ergebnis.ueberschreitung == Decimal('0.00')
        assert not ergebnis.ist_ueberzogen

    def test_im_rahmen_des_auftrags_steht_keine_warnung(
            self, projekt, ingenieurstunde, person):
        _auftrag(projekt, Decimal('1000.00'))
        _stunden(projekt, ingenieurstunde, person, time(8, 0), time(12, 0))

        ergebnis = _ergebnis(projekt)

        assert ergebnis.leistungswert == Decimal('380.00')
        assert not ergebnis.ist_ueberzogen

    def test_darueber_hinaus_wird_es_benannt(
            self, projekt, ingenieurstunde, person):
        _auftrag(projekt, Decimal('200.00'))
        _stunden(projekt, ingenieurstunde, person, time(8, 0), time(12, 0))

        ergebnis = _ergebnis(projekt)

        # 380,00 geleistet, 200,00 beauftragt.
        assert ergebnis.ueberschreitung == Decimal('180.00')
        assert ergebnis.ist_ueberzogen
        # Das Ergebnis bleibt unverändert.
        assert ergebnis.ergebnis == Decimal('160.00')

    def test_die_uebersicht_summiert_und_zaehlt_auf(
            self, projekt, ingenieurstunde, person):
        _auftrag(projekt, Decimal('200.00'))
        _stunden(projekt, ingenieurstunde, person, time(8, 0), time(12, 0))

        uebersicht = ergebnisse.projektergebnisse()

        assert uebersicht.ueberschreitung == Decimal('180.00')
        assert [z.projekt for z in uebersicht.ueberzogene] == [projekt]


class TestEinProjektWieInDerUebersicht:
    """``projektergebnis`` rechnet nur das eine Projekt und liefert dieselben
    Zahlen wie die Übersicht."""

    def test_jedes_projekt_wie_seine_zeile_in_der_uebersicht(
            self, kunde, projekt, ingenieurstunde, person, labor):
        anderes = Projekt.objects.create(
            nummer='2026-043', bezeichnung='Baugrund Kita', kunde=kunde)
        for vorhaben, betrag in ((projekt, Decimal('8000.00')),
                                 (anderes, Decimal('3000.00'))):
            _auftrag(vorhaben, betrag)
            _stunden(vorhaben, ingenieurstunde, person, time(8), time(11, 37))
            _laborkosten(labor, vorhaben, einkauf=Decimal('87.50'),
                         menge=Decimal('3') if vorhaben == projekt
                         else Decimal('2'))
        anderes.abgeschlossen = True
        anderes.save(update_fields=['abgeschlossen'])

        uebersicht = ergebnisse.projektergebnisse(nur_laufende=False)

        for vorhaben in (projekt, anderes):
            assert ergebnisse.projektergebnis(vorhaben) == (
                uebersicht.je_projekt()[vorhaben.pk])
