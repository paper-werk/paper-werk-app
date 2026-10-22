"""Eine festgeschriebene Rechnungskorrektur mindert die Forderung (R-182).

Die Rechnung bleibt unverändert; der offene Betrag wird berechnet.
Regression: Eine Rechnung mit Nachlass blieb voll offen und ließ sich über
den vollen Betrag mahnen.

Rechnung im Test: 10 Std zu 100 EUR, 19 %, also 1.190,00 EUR brutto.
"""

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from faktura import facturx, services
from faktura.models import Beleg, BelegStatus, BelegTyp, Kontakt, Rechnungsart
from faktura.services.korrektur import forderungszeile
from faktura.tests.test_pdf import vorgaengerbezug, xml_wert

# Mit Marker legt ``faktura/conftest.py`` die eigene Firma an, ohne die
# kein XML entsteht.
pytestmark = pytest.mark.django_db

HEUTE = timezone.localdate()


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-1000', name='Muster GmbH', strasse='Hauptstraße 1',
        plz='10115', ort='Berlin', zahlungsziel_tage=14,
    )


def _entwurf(kunde, rechnungsart=Rechnungsart.NORMAL):
    beleg = services.beleg_anlegen(
        kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Leistungen')
    beleg.rechnungsart = rechnungsart
    beleg.leistungsdatum = HEUTE - timedelta(days=40)
    beleg.leistungsdatum_bis = HEUTE - timedelta(days=31)
    beleg.save()
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Beratung', menge=Decimal('10'),
        einzelpreis=Decimal('100.00'), steuersatz='19.00', einheit='Std',
    )
    return beleg


@pytest.fixture
def rechnung(kunde):
    """Rechnung, festgeschrieben vor 30 Tagen, seit 16 Tagen fällig."""
    return services.beleg_festschreiben(
        beleg_id=_entwurf(kunde).pk, belegdatum=HEUTE - timedelta(days=30))


def _nachlass(rechnung, netto, festschreiben=True):
    korrektur = services.rechnungskorrektur_erstellen(
        beleg_id=rechnung.pk, betrag_netto=Decimal(netto), grund='Mangel')
    if festschreiben:
        korrektur = services.beleg_festschreiben(beleg_id=korrektur.pk)
    return korrektur


def _zahlung(rechnung, betrag):
    return services.zahlung_verbuchen(
        beleg_id=rechnung.pk, datum=HEUTE, betrag=Decimal(betrag))


class TestOffenerBetrag:
    def test_festgeschriebener_nachlass_mindert(self, rechnung):
        _nachlass(rechnung, '100.00')

        assert services.nachlass(rechnung) == Decimal('119.00')
        assert services.offener_betrag(rechnung) == Decimal('1071.00')

    def test_ein_entwurf_mindert_nicht(self, rechnung):
        """Ein Entwurf mindert nicht, weil der Kunde ihn nicht erhalten
        hat."""
        _nachlass(rechnung, '100.00', festschreiben=False)

        assert services.nachlass(rechnung) == Decimal('0.00')
        assert services.offener_betrag(rechnung) == Decimal('1190.00')

    def test_nachlass_und_zahlung_zusammen(self, rechnung):
        _nachlass(rechnung, '100.00')
        _zahlung(rechnung, '500.00')

        assert services.offener_betrag(rechnung) == Decimal('571.00')

    def test_mehrere_nachlaesse_zaehlen_zusammen(self, rechnung):
        _nachlass(rechnung, '100.00')
        _nachlass(rechnung, '200.00')

        assert services.nachlass(rechnung) == Decimal('357.00')
        assert services.offener_betrag(rechnung) == Decimal('833.00')

    def test_voller_nachlass_gleicht_aus(self, rechnung):
        _nachlass(rechnung, '1000.00')

        assert services.offener_betrag(rechnung) == Decimal('0.00')
        assert services.zahlungsstand(rechnung) == services.ZAHLUNGSSTAND_BEZAHLT

    def test_nachlass_nach_voller_zahlung_bleibt_bei_null(self, rechnung):
        """Ein Nachlass nach voller Zahlung ergibt ein Guthaben; der offene
        Betrag wird nie negativ."""
        _zahlung(rechnung, '1190.00')
        _nachlass(rechnung, '100.00')

        assert services.offener_betrag(rechnung) == Decimal('0.00')


class TestOffenePosten:
    """Offene Posten liefern denselben Betrag wie die einzelne Rechnung,
    auch über die Summenabfrage der ersten Stufe."""

    def test_gemindert_wie_einzeln(self, rechnung):
        _nachlass(rechnung, '100.00')

        posten = services.offene_posten().posten

        assert [p.beleg.pk for p in posten] == [rechnung.pk]
        assert posten[0].offen == Decimal('1071.00')
        assert posten[0].offen == services.offener_betrag(rechnung)

    def test_voller_nachlass_faellt_heraus(self, rechnung):
        _nachlass(rechnung, '1000.00')

        assert services.offene_posten().posten == []

    def test_nachlass_einer_anderen_rechnung_mindert_nicht(self, kunde,
                                                           rechnung):
        andere = services.beleg_festschreiben(beleg_id=_entwurf(kunde).pk)
        _nachlass(andere, '100.00')

        offen = {p.beleg.pk: p.offen for p in services.offene_posten().posten}

        assert offen == {rechnung.pk: Decimal('1190.00'),
                         andere.pk: Decimal('1071.00')}


class TestZahlung:
    def test_mehr_als_der_rest_wird_abgelehnt(self, rechnung):
        _nachlass(rechnung, '100.00')

        with pytest.raises(services.UngueltigerBetrag, match='1071'):
            _zahlung(rechnung, '1190.00')

    def test_der_rest_gleicht_aus(self, rechnung):
        _nachlass(rechnung, '100.00')
        _zahlung(rechnung, '1071.00')

        assert services.offener_betrag(rechnung) == Decimal('0.00')


class TestMahnung:
    def test_gemahnt_wird_der_rest(self, rechnung):
        _nachlass(rechnung, '100.00')
        _zahlung(rechnung, '500.00')

        mahnung = services.mahnung_erstellen(beleg_id=rechnung.pk, stufe=1)

        zeile = forderungszeile(mahnung)
        assert zeile.einzelpreis == Decimal('571.00')
        assert 'Rechnungsbetrag 1.190,00 EUR' in zeile.bezeichnung
        assert 'Nachlass 119,00 EUR' in zeile.bezeichnung
        assert 'bereits bezahlt 500,00 EUR' in zeile.bezeichnung

    def test_ohne_zahlung_steht_kein_bezahlt_da(self, rechnung):
        _nachlass(rechnung, '100.00')

        mahnung = services.mahnung_erstellen(beleg_id=rechnung.pk, stufe=1)

        zeile = forderungszeile(mahnung)
        assert zeile.einzelpreis == Decimal('1071.00')
        assert 'bereits bezahlt' not in zeile.bezeichnung

    def test_nach_vollem_nachlass_keine_mahnung(self, rechnung):
        _nachlass(rechnung, '1000.00')

        with pytest.raises(services.FalscherStatus):
            services.mahnung_erstellen(beleg_id=rechnung.pk, stufe=1)

    def test_nachlass_nach_dem_mahnentwurf_sperrt_den_versand(self, rechnung):
        """Ein Nachlass nach dem Mahnentwurf sperrt dessen Festschreiben, weil
        die Mahnung den alten Betrag fordert."""
        mahnung = services.mahnung_erstellen(beleg_id=rechnung.pk, stufe=1)
        _nachlass(rechnung, '100.00')

        with pytest.raises(services.UngueltigerBetrag):
            services.beleg_festschreiben(beleg_id=mahnung.pk)


class TestGrenzen:
    def test_nicht_ueber_den_rechnungsbetrag(self, rechnung):
        with pytest.raises(services.UngueltigerBetrag):
            _nachlass(rechnung, '1000.01')

        assert not rechnung.nachfolger.filter(
            typ=BelegTyp.GUTSCHRIFT).exists()

    def test_nicht_ueber_den_rest_nach_frueheren_nachlaessen(self, rechnung):
        _nachlass(rechnung, '600.00')

        with pytest.raises(services.UngueltigerBetrag):
            _nachlass(rechnung, '400.01')

    def test_ein_geaenderter_entwurf_wird_beim_festschreiben_geprueft(
            self, rechnung):
        korrektur = _nachlass(rechnung, '100.00', festschreiben=False)
        zeile = korrektur.positionen.get()
        zeile.einzelpreis = Decimal('-2000.00')
        zeile.save()

        with pytest.raises(services.UngueltigerBetrag):
            services.beleg_festschreiben(beleg_id=korrektur.pk)

    def test_kein_nachlass_auf_einen_abschlag(self, kunde):
        abschlag = services.beleg_festschreiben(
            beleg_id=_entwurf(kunde, Rechnungsart.ABSCHLAG).pk)

        with pytest.raises(services.FalscherStatus, match='Abschlag'):
            _nachlass(abschlag, '100.00')


class TestStorno:
    def test_nach_einem_nachlass_gesperrt(self, rechnung):
        """Nach einem Nachlass ist das Storno der Rechnung gesperrt, weil der
        Nachlass sonst zusätzlich zum vollen Storno zählte."""
        _nachlass(rechnung, '100.00')

        with pytest.raises(services.FalscherStatus, match='Nachlass'):
            services.rechnung_korrigieren(beleg_id=rechnung.pk)

        rechnung.refresh_from_db()
        assert rechnung.status == BelegStatus.FESTGESCHRIEBEN

    def test_ein_nachlassentwurf_sperrt_nicht(self, rechnung):
        _nachlass(rechnung, '100.00', festschreiben=False)

        services.rechnung_korrigieren(beleg_id=rechnung.pk)

        rechnung.refresh_from_db()
        assert rechnung.status == BelegStatus.STORNIERT

    def test_der_entwurf_laesst_sich_danach_nicht_festschreiben(self,
                                                                rechnung):
        korrektur = _nachlass(rechnung, '100.00', festschreiben=False)
        services.rechnung_korrigieren(beleg_id=rechnung.pk)

        with pytest.raises(services.FalscherStatus):
            services.beleg_festschreiben(beleg_id=korrektur.pk)


class TestNachlassStornieren:
    """Zuerst der Nachlass, dann die Rechnung, je Beleg ein eigenes Storno
    (entscheidungen.md, „Rechnungskorrektur und Nachlass“)."""

    def test_das_storno_hebt_den_nachlass_auf(self, rechnung):
        korrektur = _nachlass(rechnung, '100.00')

        storno = services.nachlass_stornieren(beleg_id=korrektur.pk)

        korrektur.refresh_from_db()
        assert storno.typ == BelegTyp.STORNO
        assert storno.status == BelegStatus.FESTGESCHRIEBEN
        assert storno.vorgaenger_id == korrektur.pk
        assert services.belegsummen(storno).brutto == Decimal('119.00')
        assert korrektur.status == BelegStatus.STORNIERT

    def test_die_forderung_steht_wieder_voll(self, rechnung):
        korrektur = _nachlass(rechnung, '100.00')

        services.nachlass_stornieren(beleg_id=korrektur.pk)

        assert services.nachlass(rechnung) == Decimal('0.00')
        assert services.offener_betrag(rechnung) == Decimal('1190.00')

    def test_danach_laesst_sich_die_rechnung_stornieren(self, rechnung):
        korrektur = _nachlass(rechnung, '100.00')
        services.nachlass_stornieren(beleg_id=korrektur.pk)

        services.rechnung_korrigieren(beleg_id=rechnung.pk)

        rechnung.refresh_from_db()
        assert rechnung.status == BelegStatus.STORNIERT
        assert services.offene_posten().posten == []

    def test_die_kette_geht_auf_null(self, rechnung):
        """Rechnung, Nachlass und beide Stornos ergeben zusammen 0
        fakturiert, wie in den Umsatzauswertungen (alles außer
        Entwürfen)."""
        korrektur = _nachlass(rechnung, '100.00')
        services.nachlass_stornieren(beleg_id=korrektur.pk)
        services.rechnung_korrigieren(beleg_id=rechnung.pk)

        belege = Beleg.objects.filter(
            typ__in=BelegTyp.steuerbelege()).exclude(
            status=BelegStatus.ENTWURF)
        assert belege.count() == 4
        assert sum(services.belegsummen(b).brutto
                   for b in belege) == Decimal('0.00')

    def test_e_rechnung_als_korrigierte_rechnung(self, rechnung):
        """Das Storno des Nachlasses ist im XML eine korrigierte Rechnung
        (384), weil 381 die positiven Beträge umkehrte."""
        korrektur = _nachlass(rechnung, '100.00')
        storno = services.nachlass_stornieren(beleg_id=korrektur.pk)
        storno_rechnung, _ = services.rechnung_korrigieren(
            beleg_id=rechnung.pk)

        assert facturx.typcode(storno) == '384'
        assert facturx.typcode(korrektur) == '381'
        assert facturx.typcode(storno_rechnung) == '381'

    def test_das_xml_fordert_positiv(self, rechnung):
        """Die Beträge im XML sind positiv und passen zum Typ."""
        korrektur = _nachlass(rechnung, '100.00')
        storno = services.nachlass_stornieren(beleg_id=korrektur.pk)

        xml = facturx.xml_erzeugen(storno).decode()

        assert xml_wert(xml, 'TypeCode') == '384'
        assert Decimal(xml_wert(xml, 'GrandTotalAmount')) == Decimal('119.00')

    def test_das_xml_verweist_auf_die_korrektur(self, rechnung):
        """BG-3 nennt die berichtigte Rechnungskorrektur, nicht die
        Rechnung; BR-DE-26 verlangt BG-3 bei 384."""
        korrektur = _nachlass(rechnung, '100.00')
        storno = services.nachlass_stornieren(beleg_id=korrektur.pk)

        xml = facturx.xml_erzeugen(storno).decode()

        assert vorgaengerbezug(xml) == (
            korrektur.nummer, korrektur.belegdatum.strftime('%Y%m%d'))

    def test_der_kopftext_schreibt_nicht_gut(self, rechnung):
        korrektur = _nachlass(rechnung, '100.00')

        storno = services.nachlass_stornieren(beleg_id=korrektur.pk)

        assert 'schreiben wir Ihnen gut' not in storno.kopftext
        assert f'Rechnungskorrektur {korrektur.nummer}' in storno.kopftext
        assert rechnung.nummer in storno.kopftext

    def test_ein_entwurf_wird_nicht_storniert(self, rechnung):
        korrektur = _nachlass(rechnung, '100.00', festschreiben=False)

        with pytest.raises(services.FalscherStatus):
            services.nachlass_stornieren(beleg_id=korrektur.pk)

    def test_nicht_zweimal(self, rechnung):
        korrektur = _nachlass(rechnung, '100.00')
        services.nachlass_stornieren(beleg_id=korrektur.pk)

        with pytest.raises(services.FalscherStatus):
            services.nachlass_stornieren(beleg_id=korrektur.pk)

    def test_die_sperrmeldung_nennt_den_weg(self, rechnung):
        _nachlass(rechnung, '100.00')

        with pytest.raises(services.FalscherStatus,
                           match='Nachlass stornieren'):
            services.rechnung_korrigieren(beleg_id=rechnung.pk)


class TestOberflaeche:
    def test_am_abschlag_gibt_es_keinen_nachlass(self, buero, kunde):
        abschlag = services.beleg_festschreiben(
            beleg_id=_entwurf(kunde, Rechnungsart.ABSCHLAG).pk)

        antwort = buero.get(reverse(
            'admin:faktura_abschlagsrechnung_detail_nachlass',
            args=[abschlag.pk]))

        assert antwort.status_code == 403

    def test_an_der_rechnung_schon(self, buero, rechnung):
        antwort = buero.get(reverse(
            'admin:faktura_rechnung_detail_nachlass', args=[rechnung.pk]))

        assert antwort.status_code == 200
        assert re.search(r'davon offen\s+1\.?190,00', antwort.content.decode())

    def test_guthaben_wird_gemeldet(self, buero, rechnung):
        _zahlung(rechnung, '1190.00')

        antwort = buero.post(
            reverse('admin:faktura_rechnung_changelist'),
            {'action': 'action_nachlass',
             '_selected_action': [str(rechnung.pk)],
             'anwenden': '1', 'betrag_netto': '100,00',
             'grund': 'Mangel', 'steuersatz': '19.00'},
            follow=True,
        )

        meldungen = [str(m) for m in antwort.context['messages']]
        assert any('119,00' in m and 'zu viel bezahlt' in m
                   for m in meldungen)

    def test_der_zahlungsreiter_nennt_den_nachlass(self, buero, rechnung):
        _nachlass(rechnung, '100.00')

        html = buero.get(reverse(
            'admin:faktura_rechnung_change', args=[rechnung.pk])
        ).content.decode()

        assert 'mindern die Forderung um <strong>119,00' in html
        assert 'Offen: <strong>1.071,00' in html

    def test_nachlass_stornieren_ueber_den_knopf(self, buero, rechnung):
        korrektur = _nachlass(rechnung, '100.00')
        adresse = reverse(
            'admin:faktura_rechnungskorrektur_detail_nachlass_stornieren',
            args=[korrektur.pk])

        dialog = buero.get(adresse).content.decode()
        buero.post(adresse, {'_form_submitted': 'on'})

        assert 'schicken Sie ihm' in dialog
        korrektur.refresh_from_db()
        assert korrektur.status == BelegStatus.STORNIERT
        assert korrektur.nachfolger.get().typ == BelegTyp.STORNO

    def test_die_liste_zeigt_den_geminderten_rest(self, buero, rechnung):
        """Die Liste zeigt den geminderten Rest über ``nachlaesse_vorladen``,
        ohne Einzelabfrage."""
        _nachlass(rechnung, '100.00')

        html = buero.get(
            reverse('admin:faktura_rechnung_changelist')).content.decode()

        assert '1.071,00' in html
