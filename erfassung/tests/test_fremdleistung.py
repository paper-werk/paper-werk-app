"""Fremdleistung: Eingangsrechnungen verteilt auf Vorhaben.

Geprüft wird, dass kein Betrag unbemerkt fehlt: Ein nicht zugeordneter Rest
bleibt sichtbar, übergangene Positionen werden gemeldet, und nicht
weiterberechnete Fremdleistung zählt im Projektergebnis.
"""

from datetime import date, time
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError

from erfassung import services
from erfassung.models import Eingangsrechnung, Fremdleistung, Zustand
from faktura.models import (
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Kontakt,
    Leistungsart,
)


@pytest.fixture
def labor(db):
    return Kontakt.objects.create(name='ISARTAL', ist_kunde=False,
                                  ist_lieferant=True,
                                  eigene_kundennummer='K-88')


@pytest.fixture
def laborrechnung(labor):
    """Rechnung über 1.000 EUR netto ohne Positionen."""
    return Eingangsrechnung.objects.create(
        lieferant=labor, nummer='RE-2026-4711', datum=date(2026, 8, 14),
        betrag_netto=Decimal('1000.00'),
    )


@pytest.fixture
def laborposition(projekt):
    """40 Bodenproben zu 145,00 im festgeschriebenen Auftrag.

    Über ``bulk_create`` wie ``auftragsposition`` in der conftest:
    ``Belegposition.save()`` weist Änderungen am festgeschriebenen Beleg ab.
    """
    auftrag = Beleg.objects.create(
        typ=BelegTyp.AUFTRAG, status=BelegStatus.FESTGESCHRIEBEN,
        nummer='AU-2026-0009', projekt=projekt)
    return Belegposition.objects.bulk_create([
        Belegposition(
            beleg=auftrag, position=20, bezeichnung='Bodenprobe LAGA-Paket',
            menge=Decimal('40'), einheit='Stk',
            einzelpreis=Decimal('145.00'), steuersatz='19.00',
            art=Leistungsart.MENGE,
        )
    ])[0]


def _position(rechnung, projekt, **rest):
    rest.setdefault('bezeichnung', 'Paket 4711 Bodenluft')
    rest.setdefault('menge', Decimal('1'))
    rest.setdefault('einkaufspreis', Decimal('96.00'))
    return Fremdleistung.objects.create(
        rechnung=rechnung, projekt=projekt, **rest)


# ── Einkauf ──────────────────────────────────────────────────────────────────

class TestDerEinkauf:
    """Betrag der Fremdleistung ist der Zeilenbetrag des Lieferanten."""

    def test_ohne_betrag_rechnet_er_sich_aus_menge_und_preis(
            self, laborrechnung, projekt):
        position = _position(laborrechnung, projekt, menge=Decimal('3'),
                             einkaufspreis=Decimal('96.00'))

        assert position.einkauf_netto == Decimal('288.00')

    def test_ein_eingetragener_betrag_bleibt(self, laborrechnung, projekt):
        """10 Stück zu 50,00 mit 10 % Rabatt auf der Zeile ergeben 450."""
        position = _position(laborrechnung, projekt, menge=Decimal('10'),
                             einkaufspreis=Decimal('50.00'),
                             einkauf_netto=Decimal('450.00'))

        position.save()
        position.refresh_from_db()
        assert position.einkauf_netto == Decimal('450.00')

    def test_neue_menge_neuer_betrag(self, laborrechnung, projekt):
        """Nach Änderung der Menge ohne Änderung des Betrags wird der Betrag
        neu berechnet."""
        position = _position(laborrechnung, projekt, menge=Decimal('3'),
                             einkaufspreis=Decimal('96.00'))

        position.menge = Decimal('4')
        position.save()

        assert position.einkauf_netto == Decimal('384.00')

    def test_neuer_preis_neuer_betrag(self, laborrechnung, projekt):
        position = _position(laborrechnung, projekt, menge=Decimal('3'),
                             einkaufspreis=Decimal('96.00'))

        position.einkaufspreis = Decimal('100.00')
        position.save()

        assert position.einkauf_netto == Decimal('300.00')

    def test_menge_und_betrag_zusammen_geaendert_gilt_der_betrag(
            self, laborrechnung, projekt):
        position = _position(laborrechnung, projekt, menge=Decimal('3'),
                             einkaufspreis=Decimal('96.00'))

        position.menge = Decimal('4')
        position.einkauf_netto = Decimal('350.00')
        position.save()

        assert position.einkauf_netto == Decimal('350.00')

    def test_ein_geleerter_betrag_wird_neu_gerechnet(
            self, laborrechnung, projekt):
        position = _position(laborrechnung, projekt, menge=Decimal('10'),
                             einkaufspreis=Decimal('50.00'),
                             einkauf_netto=Decimal('450.00'))

        position.einkauf_netto = None
        position.save()

        assert position.einkauf_netto == Decimal('500.00')

    def test_ein_preis_je_hundert_meter_passt_in_vier_stellen(
            self, laborrechnung, projekt):
        """0,85 € je 100 m sind 0,0085 € je Meter; 250 m ergeben 2,125,
        kaufmännisch 2,13."""
        position = _position(laborrechnung, projekt, menge=Decimal('250'),
                             einheit='m', einkaufspreis=Decimal('0.0085'))

        position.refresh_from_db()
        assert position.einkaufspreis == Decimal('0.0085')
        assert position.einkauf_netto == Decimal('2.13')

    def test_was_wir_selbst_tragen_ist_nicht_abrechenbar(
            self, laborrechnung, projekt):
        """Eine Nachanalyse nach eigenem Fehler ist nicht abrechenbar und
        zählt als Kosten (siehe TestDieProjektzahlen)."""
        position = _position(laborrechnung, projekt, weiterberechenbar=False)

        assert position.zustand == Zustand.NICHT_ABRECHENBAR


class TestDieAuftragsposition:
    """Die Auftragsposition ist optional und dient der Zuordnung."""

    def test_ohne_auftragsposition_geht_es(self, laborrechnung, projekt):
        position = _position(laborrechnung, projekt)

        position.full_clean()
        assert position.auftragsposition is None

    def test_eine_des_eigenen_projekts_geht(self, laborrechnung, projekt,
                                            laborposition):
        position = _position(laborrechnung, projekt,
                             auftragsposition=laborposition)

        position.full_clean()

    def test_eine_aus_fremdem_projekt_wird_abgewiesen(
            self, laborrechnung, kunde, laborposition):
        from faktura.models import Projekt
        anderes = Projekt.objects.create(
            nummer='2026-099', bezeichnung='Anderswo', kunde=kunde)
        position = _position(laborrechnung, anderes,
                             auftragsposition=laborposition)

        with pytest.raises(ValidationError) as fehler:
            position.full_clean()

        assert 'auftragsposition' in fehler.value.error_dict


# ── Kopfbetrag und Rest ──────────────────────────────────────────────────────

class TestWasNichtZugeordnetIst:

    def test_eine_frische_rechnung_ist_vollstaendig_offen(self, laborrechnung):
        assert laborrechnung.zugeordnet == Decimal('0.00')
        assert laborrechnung.rest == Decimal('1000.00')
        assert not laborrechnung.ist_vollstaendig

    def test_der_rest_sinkt_mit_jeder_position(self, laborrechnung, projekt):
        _position(laborrechnung, projekt, menge=Decimal('5'),
                  einkaufspreis=Decimal('96.00'))

        assert laborrechnung.zugeordnet == Decimal('480.00')
        assert laborrechnung.rest == Decimal('520.00')

    def test_vollstaendig_heisst_genau_null(self, laborrechnung, projekt):
        _position(laborrechnung, projekt, menge=Decimal('10'),
                  einkaufspreis=Decimal('100.00'))

        assert laborrechnung.rest == Decimal('0.00')
        assert laborrechnung.ist_vollstaendig

    def test_zu_viel_verteilt_ergibt_einen_negativen_rest(
            self, laborrechnung, projekt):
        """Mehr verteilt als gefordert ergibt einen negativen Rest, ohne
        ``max(0, ...)``."""
        _position(laborrechnung, projekt, menge=Decimal('12'),
                  einkaufspreis=Decimal('100.00'))

        assert laborrechnung.rest == Decimal('-200.00')
        assert not laborrechnung.ist_vollstaendig

    def test_dieselbe_rechnung_zweimal_geht_nicht(self, labor):
        Eingangsrechnung.objects.create(
            lieferant=labor, nummer='RE-1', datum=date(2026, 8, 1),
            betrag_netto=Decimal('10.00'))

        with pytest.raises(IntegrityError):
            Eingangsrechnung.objects.create(
                lieferant=labor, nummer='RE-1', datum=date(2026, 8, 2),
                betrag_netto=Decimal('10.00'))

    def test_unvollstaendige_stehen_oben_mit_dem_groessten_rest(
            self, labor, projekt):
        klein = Eingangsrechnung.objects.create(
            lieferant=labor, nummer='RE-klein', datum=date(2026, 8, 1),
            betrag_netto=Decimal('100.00'))
        gross = Eingangsrechnung.objects.create(
            lieferant=labor, nummer='RE-groß', datum=date(2026, 8, 2),
            betrag_netto=Decimal('900.00'))
        erledigt = Eingangsrechnung.objects.create(
            lieferant=labor, nummer='RE-fertig', datum=date(2026, 8, 3),
            betrag_netto=Decimal('50.00'))
        _position(erledigt, projekt, menge=Decimal('1'),
                  einkaufspreis=Decimal('50.00'))

        offen = services.unvollstaendige_eingangsrechnungen()

        assert [r.nummer for r in offen] == [gross.nummer, klein.nummer]


# ── Sperre ───────────────────────────────────────────────────────────────────

class TestDieSperre:

    def test_ein_negativer_einkaufspreis_wird_abgewiesen(
            self, laborrechnung, projekt):
        position = Fremdleistung(
            rechnung=laborrechnung, projekt=projekt, bezeichnung='Rückläufer',
            menge=Decimal('1'), einkaufspreis=Decimal('-10.00'))

        with pytest.raises(ValidationError) as fehler:
            position.full_clean()

        assert 'einkaufspreis' in fehler.value.error_dict

    def test_schon_der_entwurf_sperrt(self, laborrechnung, projekt,
                                      entwurfsposition):
        """Schon ein Entwurf sperrt die Position, wie bei der
        Erfassungszeile."""
        position = _position(laborrechnung, projekt,
                             abgerechnet_in=entwurfsposition)
        position.menge = Decimal('9')

        assert position.ist_gesperrt
        with pytest.raises(ValidationError):
            position.full_clean()

    def test_die_festgeschriebene_rechnung_sperrt(
            self, laborrechnung, projekt, festgeschriebene_position):
        position = _position(laborrechnung, projekt,
                             abgerechnet_in=festgeschriebene_position)
        position.menge = Decimal('9')

        assert position.ist_gesperrt
        with pytest.raises(ValidationError):
            position.full_clean()

    def test_ohne_aenderung_sperrt_sie_nicht(self, laborrechnung, projekt,
                                             festgeschriebene_position):
        """Eine unveränderte gesperrte Position verhindert das Speichern nicht
        (``models.wurde_geaendert``).

        Die Sperre schützt den Wert auf der Rechnung; bleibt er unverändert,
        gibt es nichts zu sperren.
        """
        position = _position(laborrechnung, projekt,
                             abgerechnet_in=festgeschriebene_position)

        assert position.ist_gesperrt
        position.full_clean()


# ── Vorschau ─────────────────────────────────────────────────────────────────

class TestDieAbrechnungsvorschau:

    def test_ohne_fremdleistungen_bleibt_alles_wie_bisher(
            self, projekt, zeitleistung, mitarbeiter):
        """Ohne Fremdleistungen bleibt das Ergebnis unverändert; der zweite
        Parameter ist optional."""
        from erfassung.models import Erfassungszeile
        services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Probenahme', von=time(8, 0), bis=time(12, 0))

        vorschau = services.abrechnungsvorschau(Erfassungszeile.objects.all())

        assert len(vorschau.positionen) == 1
        assert vorschau.fremdpositionen == []
        assert vorschau.netto == Decimal('272.00')

    def test_gleiche_positionen_werden_zu_einer(self, laborrechnung, projekt):
        """Gleiche Positionen ohne Auftragsposition werden zu einer, zum
        Einkaufspreis."""
        for _ in range(3):
            _position(laborrechnung, projekt, menge=Decimal('2'),
                      einkaufspreis=Decimal('96.00'))

        vorschau = services.abrechnungsvorschau(
            [], Fremdleistung.objects.all())

        assert len(vorschau.fremdpositionen) == 1
        position = vorschau.fremdpositionen[0]
        assert position.menge == Decimal('6')
        assert position.einzelpreis == Decimal('96.00')
        assert position.summe == Decimal('576.00')
        assert position.einkauf == Decimal('576.00')
        assert position.spanne == Decimal('0.00')
        assert position.auftragsposition is None

    def test_verschiedene_preise_bleiben_getrennt(self, laborrechnung, projekt):
        """Verschiedene Preise bleiben getrennte Positionen."""
        _position(laborrechnung, projekt, einkaufspreis=Decimal('96.00'))
        _position(laborrechnung, projekt, einkaufspreis=Decimal('98.00'))

        vorschau = services.abrechnungsvorschau(
            [], Fremdleistung.objects.all())

        assert len(vorschau.fremdpositionen) == 2

    def test_rabatt_auf_der_zeile_wird_eine_pauschale_ueber_den_betrag(
            self, laborrechnung, projekt):
        """10 zu 50,00 abzüglich 10 % ergeben eine Pauschale über 450,00;
        die Menge steht in der Bezeichnung."""
        _position(laborrechnung, projekt, bezeichnung='Klemmen',
                  einheit='Stk', menge=Decimal('10'),
                  einkaufspreis=Decimal('50.00'),
                  einkauf_netto=Decimal('450.00'))

        [position] = services.abrechnungsvorschau(
            [], Fremdleistung.objects.all()).fremdpositionen

        assert position.summe == Decimal('450.00')
        assert position.menge == Decimal('1')
        assert position.einheit == 'pausch'
        assert position.bezeichnung == 'Klemmen (10 Stk)'

    def test_ein_meterpreis_unter_einem_cent_wird_eine_pauschale(
            self, laborrechnung, projekt):
        """0,0085 €/m ist kein Cent-Preis; 250 m zu 0,01 ergäben 2,50, der
        Betrag ist 2,13. Deshalb eine Pauschale."""
        _position(laborrechnung, projekt, bezeichnung='NYM-J 3x1,5',
                  einheit='m', menge=Decimal('250'),
                  einkaufspreis=Decimal('0.0085'))

        [position] = services.abrechnungsvorschau(
            [], Fremdleistung.objects.all()).fremdpositionen

        assert position.summe == Decimal('2.13')
        assert position.bezeichnung == 'NYM-J 3x1,5 (250 m)'

    def test_mit_auftragsposition_gilt_der_vertragspreis(
            self, laborrechnung, projekt, laborposition):
        """Bei passender Einheit (Stk zu Stk) kommen Bezeichnung, Einheit,
        Preis und Steuersatz aus dem Auftrag."""
        _position(laborrechnung, projekt, bezeichnung='Paket 4711 LAGA Boden',
                  einheit='Stk', menge=Decimal('12'),
                  einkaufspreis=Decimal('96.00'),
                  auftragsposition=laborposition)

        [position] = services.abrechnungsvorschau(
            [], Fremdleistung.objects.all()).fremdpositionen

        assert position.bezeichnung == 'Bodenprobe LAGA-Paket'
        assert position.einzelpreis == Decimal('145.00')
        assert position.menge == Decimal('12')
        assert position.summe == Decimal('1740.00')
        assert position.einkauf == Decimal('1152.00')
        assert position.spanne == Decimal('588.00')
        assert position.auftragsposition == laborposition
        assert position.art == Leistungsart.MENGE

    def test_je_auftragsposition_eine_zeile(self, laborrechnung, projekt,
                                            laborposition):
        """Zwei Pakete mit verschiedenem Namen auf derselben
        Auftragsposition ergeben eine Rechnungsposition."""
        _position(laborrechnung, projekt, bezeichnung='Paket 4711',
                  einheit='Stk', menge=Decimal('5'),
                  auftragsposition=laborposition)
        _position(laborrechnung, projekt, bezeichnung='Paket 4712',
                  einheit='Stk', menge=Decimal('7'),
                  einkaufspreis=Decimal('90.00'),
                  auftragsposition=laborposition)

        [position] = services.abrechnungsvorschau(
            [], Fremdleistung.objects.all()).fremdpositionen

        assert position.menge == Decimal('12')
        assert position.summe == Decimal('1740.00')
        # 5 x 96 + 7 x 90
        assert position.einkauf == Decimal('1110.00')

    @pytest.mark.parametrize('einheit', ['stk', ' Stk ', 'STK'])
    def test_die_einheit_ohne_schreibweise_verglichen(
            self, laborrechnung, projekt, laborposition, einheit):
        _position(laborrechnung, projekt, einheit=einheit,
                  menge=Decimal('2'), auftragsposition=laborposition)

        [position] = services.abrechnungsvorschau(
            [], Fremdleistung.objects.all()).fremdpositionen

        assert position.einzelpreis == Decimal('145.00')

    def test_passt_die_einheit_nicht_wird_zum_einkauf_durchgereicht(
            self, laborrechnung, projekt, laborposition):
        """Bei abweichender Einheit (Pauschale zu Stück) wird zum
        Einkaufspreis weiterberechnet; der Bezug zur Auftragsposition
        bleibt für die Mengenprüfung."""
        _position(laborrechnung, projekt, bezeichnung='Sammelrechnung Labor',
                  einheit='pausch', menge=Decimal('1'),
                  einkaufspreis=Decimal('1180.00'),
                  auftragsposition=laborposition)

        [position] = services.abrechnungsvorschau(
            [], Fremdleistung.objects.all()).fremdpositionen

        assert position.bezeichnung == 'Sammelrechnung Labor'
        assert position.einzelpreis == Decimal('1180.00')
        assert position.auftragsposition == laborposition

    @pytest.mark.parametrize('feld, wert, grund', [
        ('weiterberechenbar', False, services.GRUND_NICHT_ABRECHENBAR),
        ('menge', Decimal('0'), services.GRUND_OHNE_WERT),
        ('einkaufspreis', Decimal('0'), services.GRUND_OHNE_WERT),
    ])
    def test_uebergangene_werden_benannt_und_nicht_verschwiegen(
            self, laborrechnung, projekt, feld, wert, grund):
        _position(laborrechnung, projekt, **{feld: wert})

        vorschau = services.abrechnungsvorschau(
            [], Fremdleistung.objects.all())

        assert vorschau.fremdpositionen == []
        assert [g for _, g in vorschau.uebergangen] == [grund]

    def test_bereits_abgerechnete_kommen_nicht_zweimal_mit(
            self, laborrechnung, projekt, entwurfsposition):
        _position(laborrechnung, projekt, abgerechnet_in=entwurfsposition)

        vorschau = services.abrechnungsvorschau(
            [], Fremdleistung.objects.all())

        assert [g for _, g in vorschau.uebergangen] == [
            services.GRUND_SCHON_ABGERECHNET]

    def test_zwei_vorhaben_in_einer_rechnung_gehen_nicht(
            self, laborrechnung, projekt, kunde):
        from faktura.models import Projekt
        anderes = Projekt.objects.create(
            nummer='2026-051', bezeichnung='Halle Süd', kunde=kunde)
        _position(laborrechnung, projekt)
        _position(laborrechnung, anderes)

        with pytest.raises(services.MehrereProjekte):
            services.abrechnungsvorschau([], Fremdleistung.objects.all())

    def test_stunde_und_laborkosten_zusammen(
            self, laborrechnung, projekt, zeitleistung, mitarbeiter):
        """Eigene Leistung und Fremdleistung auf einer Rechnung mit einer
        Summe."""
        services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Probenahme', von=time(8, 0), bis=time(12, 0))
        _position(laborrechnung, projekt, menge=Decimal('2'),
                  einkaufspreis=Decimal('96.00'))

        from erfassung.models import Erfassungszeile
        vorschau = services.abrechnungsvorschau(
            Erfassungszeile.objects.all(), Fremdleistung.objects.all())

        assert len(vorschau.positionen) == 1
        assert len(vorschau.fremdpositionen) == 1
        assert len(vorschau.alle_positionen) == 2
        # 4 Std zu 68,00 = 272,00, 2 Proben zu 96,00 weiterberechnet = 192,00
        assert vorschau.netto == Decimal('464.00')
        assert vorschau.fremdkosten == Decimal('192.00')


# ── Übernahme ────────────────────────────────────────────────────────────────

class TestDieUebernahme:

    def test_fremdleistung_wird_zur_belegposition(self, laborrechnung, projekt):
        _position(laborrechnung, projekt, menge=Decimal('2'),
                  einkaufspreis=Decimal('96.00'))

        beleg, ergebnis = services.in_rechnung_uebernehmen(
            zeilen=[], fremdleistungen=Fremdleistung.objects.all())

        assert beleg.typ == BelegTyp.RECHNUNG
        assert beleg.status == BelegStatus.ENTWURF
        assert beleg.projekt == projekt
        position = beleg.positionen.get()
        assert position.menge == Decimal('2')
        assert position.einzelpreis == Decimal('96.00')
        assert position.steuersatz == '19.00'
        assert position.auftragsposition is None

    def test_der_leistungszeitraum_reicht_vom_ersten_bis_zum_letzten_datum(
            self, laborrechnung, projekt):
        """Drei Proben desselben Pakets ergeben eine Position mit dem
        Zeitraum der Probenahmen (BT-134/135); eine ohne Datum zählt
        nicht."""
        for tag in (date(2026, 8, 3), date(2026, 7, 28), None):
            _position(laborrechnung, projekt, leistungsdatum=tag)

        beleg, _ = services.in_rechnung_uebernehmen(
            zeilen=[], fremdleistungen=Fremdleistung.objects.all())

        position = beleg.positionen.get()
        assert position.menge == Decimal('3')
        assert position.leistung_von == date(2026, 7, 28)
        assert position.leistung_bis == date(2026, 8, 3)

    def test_ohne_leistungsdatum_bleibt_der_zeitraum_leer(
            self, laborrechnung, projekt):
        _position(laborrechnung, projekt)

        beleg, _ = services.in_rechnung_uebernehmen(
            zeilen=[], fremdleistungen=Fremdleistung.objects.all())

        position = beleg.positionen.get()
        assert (position.leistung_von, position.leistung_bis) == (None, None)

    def test_mit_auftragsposition_traegt_die_rechnung_den_bezug(
            self, laborrechnung, projekt, laborposition):
        """Die Rechnungsposition verweist auf die Auftragsposition, damit die
        Menge gegen den Auftrag zählt."""
        _position(laborrechnung, projekt, einheit='Stk', menge=Decimal('12'),
                  auftragsposition=laborposition)

        beleg, _ = services.in_rechnung_uebernehmen(
            zeilen=[], fremdleistungen=Fremdleistung.objects.all())

        position = beleg.positionen.get()
        assert position.auftragsposition == laborposition
        assert position.einzelpreis == Decimal('145.00')
        assert position.art == Leistungsart.MENGE

    def test_die_mengenpruefung_sieht_den_einkauf(
            self, laborrechnung, projekt, laborposition):
        """50 Bodenproben bei 40 beauftragten ergeben einen Hinweis beim
        Festschreiben, keine Sperre."""
        from faktura import services as faktura_services

        _position(laborrechnung, projekt, einheit='Stk', menge=Decimal('50'),
                  auftragsposition=laborposition)
        beleg, _ = services.in_rechnung_uebernehmen(
            zeilen=[], fremdleistungen=Fremdleistung.objects.all())

        [ueberschreitung] = faktura_services.mengenueberschreitungen(beleg)
        assert ueberschreitung.zu_viel == Decimal('10')

    def test_der_vermerk_haengt_danach_an_der_position(
            self, laborrechnung, projekt):
        _position(laborrechnung, projekt)

        beleg, _ = services.in_rechnung_uebernehmen(
            zeilen=[], fremdleistungen=Fremdleistung.objects.all())

        position = Fremdleistung.objects.get()
        assert position.abgerechnet_in == beleg.positionen.get()
        assert position.abgerechneter_beleg == beleg
        assert position.zustand == Zustand.ABGERECHNET

    def test_mit_auftragsposition_steht_der_einkauf_auf_keiner_rechnung(
            self, laborrechnung, projekt, laborposition):
        """Mit Vertragspreis erscheint der Einkaufspreis nicht auf der
        Rechnung; ohne Vertragspreis wird zum Einkaufspreis
        weiterberechnet."""
        _position(laborrechnung, projekt, einheit='Stk',
                  einkaufspreis=Decimal('96.00'),
                  auftragsposition=laborposition)

        beleg, _ = services.in_rechnung_uebernehmen(
            zeilen=[], fremdleistungen=Fremdleistung.objects.all())

        preise = [p.einzelpreis for p in beleg.positionen.all()]
        assert Decimal('96.00') not in preise

    def test_beides_landet_auf_demselben_beleg(
            self, laborrechnung, projekt, zeitleistung, mitarbeiter):
        from erfassung.models import Erfassungszeile
        services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Probenahme', von=time(8, 0), bis=time(12, 0))
        _position(laborrechnung, projekt)

        beleg, ergebnis = services.in_rechnung_uebernehmen(
            zeilen=Erfassungszeile.objects.all(),
            fremdleistungen=Fremdleistung.objects.all())

        assert beleg.positionen.count() == 2
        assert Erfassungszeile.objects.get().abgerechneter_beleg == beleg
        assert Fremdleistung.objects.get().abgerechneter_beleg == beleg

    def test_nichts_abzurechnen_bleibt_nichts_abzurechnen(
            self, laborrechnung, projekt):
        _position(laborrechnung, projekt, weiterberechenbar=False)

        with pytest.raises(services.NichtsAbzurechnen):
            services.in_rechnung_uebernehmen(
                zeilen=[], fremdleistungen=Fremdleistung.objects.all())


# ── Projektzahlen ────────────────────────────────────────────────────────────

class TestDieProjektzahlen:

    def test_fremdkosten_zaehlen_alles_was_das_projekt_gekostet_hat(
            self, laborrechnung, projekt, entwurfsposition):
        _position(laborrechnung, projekt, menge=Decimal('2'),
                  einkaufspreis=Decimal('96.00'))
        _position(laborrechnung, projekt, einkaufspreis=Decimal('50.00'),
                  weiterberechenbar=False)
        _position(laborrechnung, projekt, einkaufspreis=Decimal('30.00'),
                  abgerechnet_in=entwurfsposition)

        kosten = services.fremdkosten_je_projekt()

        assert kosten[projekt.pk] == Decimal('272.00')

    def test_offen_ist_was_auf_keiner_gueltigen_rechnung_steht(
            self, laborrechnung, projekt, entwurfsposition,
            festgeschriebene_position):
        """Eine Position auf einem Entwurf zählt als offen, auf einer
        festgeschriebenen Rechnung nicht.

        Offen (hier) und übernehmbar (abrechnungsvorschau) sind verschiedene
        Mengen: Eine Position auf einem Entwurf ist reserviert, aber noch
        nicht berechnet (services.NOCH_NICHT_ABGERECHNET). Bewertet zum
        Einkaufspreis.
        """
        _position(laborrechnung, projekt, einkaufspreis=Decimal('145.00'))
        _position(laborrechnung, projekt, einkaufspreis=Decimal('200.00'),
                  weiterberechenbar=False)
        _position(laborrechnung, projekt, einkaufspreis=Decimal('300.00'),
                  abgerechnet_in=entwurfsposition)
        _position(laborrechnung, projekt, einkaufspreis=Decimal('400.00'),
                  abgerechnet_in=festgeschriebene_position)

        offen = services.offene_fremdleistung_je_projekt()

        assert offen[projekt.pk] == Decimal('445.00')
        assert services.offene_fremdleistung_gesamt() == Decimal('445.00')

    def test_fremdkosten_sind_die_zeilenbetraege(self, laborrechnung,
                                                 projekt):
        """Fremdkosten sind die Zeilenbeträge einschließlich Rabatt."""
        _position(laborrechnung, projekt, menge=Decimal('10'),
                  einkaufspreis=Decimal('50.00'),
                  einkauf_netto=Decimal('450.00'))

        kosten = services.fremdkosten_je_projekt()
        offen = services.offene_fremdleistung_je_projekt()
        assert kosten[projekt.pk] == Decimal('450.00')
        assert offen[projekt.pk] == Decimal('450.00')
        assert laborrechnung.zugeordnet == Decimal('450.00')

    def test_abgeschlossene_vorhaben_bleiben_draussen(
            self, laborrechnung, abgeschlossenes_projekt):
        _position(laborrechnung, abgeschlossenes_projekt,
                  einkaufspreis=Decimal('96.00'))

        assert services.fremdkosten_je_projekt() == {}
        assert abgeschlossenes_projekt.pk in services.fremdkosten_je_projekt(
            nur_laufende=False)
