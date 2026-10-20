"""Abnahme, Schluss- und Teilschlussrechnung.

Referenzfall: Teilleistung A, Leistungsbeginn 01.09., Teilabnahme 20.12.;
Leistungsdatum 20.12. und der dann gültige Satz. Die später abgenommene
Restleistung ändert das Datum der Teilleistung nicht.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse

from faktura import facturx, services
from faktura.admin.abnahme import AbnahmeForm
from faktura.models import (
    Abnahme,
    Abnahmeart,
    Abnahmestand,
    BelegStatus,
    BelegTyp,
    Kontakt,
    Projekt,
    Rechnungsart,
)
from faktura.tests.test_pdf import xml_datum, xml_wert

TEIL_BEGINN = date(2025, 9, 1)
TEIL_ABNAHME = date(2025, 12, 20)
REST_ABNAHME = date(2026, 3, 10)


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-2000', name='Beispiel AG', strasse='Industriestraße 5',
        plz='90402', ort='Nürnberg', ust_id='DE987654321',
    )


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(
        nummer='2025-017', bezeichnung='Kläranlage Süd', kunde=kunde)


@pytest.fixture
def auftrag(projekt):
    """Zwei Leistungsphasen-Blöcke, getrennt abzunehmen."""
    beleg = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.AUFTRAG,
                                   betreff='Planung Kläranlage')
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Leistungsphasen 1-4', menge=Decimal('1'),
        einheit='pausch', einzelpreis=Decimal('18000.00'),
        steuersatz='19.00')
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Leistungsphasen 5-8', menge=Decimal('1'),
        einheit='pausch', einzelpreis=Decimal('24000.00'),
        steuersatz='19.00')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


@pytest.fixture
def lph_1_4(auftrag):
    return auftrag.positionen.get(position=10)


@pytest.fixture
def teilabnahme(auftrag, lph_1_4):
    abnahme = Abnahme.objects.create(
        auftrag=auftrag, art=Abnahmeart.TEIL,
        bezeichnung='Leistungsphasen 1-4', leistungsbeginn=TEIL_BEGINN,
        leistungsende=TEIL_ABNAHME, abgenommen_am=TEIL_ABNAHME)
    abnahme.positionen.add(lph_1_4)
    return abnahme


@pytest.mark.django_db
class TestAbnahme:

    def test_leistungsdatum_wird_mit_der_abnahme_vorbelegt(self, teilabnahme):
        assert teilabnahme.steuerliches_leistungsdatum == TEIL_ABNAHME

    def test_leistungsdatum_bleibt_ein_eigenes_feld(self, teilabnahme):
        """Eine spätere Korrektur des Abnahmedatums ändert das Leistungsdatum
        nicht."""
        teilabnahme.abgenommen_am = date(2025, 12, 19)
        teilabnahme.save()

        assert teilabnahme.steuerliches_leistungsdatum == TEIL_ABNAHME

    def test_entgelt_ist_die_summe_der_positionen(self, teilabnahme, auftrag):
        """E11; bei der Gesamtabnahme der ganze Auftrag."""
        gesamt = Abnahme.objects.create(auftrag=auftrag,
                                        art=Abnahmeart.GESAMT)

        assert teilabnahme.entgelt_netto == Decimal('18000.00')
        assert gesamt.entgelt_netto == Decimal('42000.00')

    def test_stand(self, teilabnahme, auftrag):
        offen = Abnahme.objects.create(auftrag=auftrag,
                                       art=Abnahmeart.GESAMT)
        assert offen.stand == Abnahmestand.OFFEN
        assert teilabnahme.stand == Abnahmestand.ABGENOMMEN

        rechnung = services.rechnung_aus_abnahme(abnahme_id=teilabnahme.pk)
        services.beleg_festschreiben(beleg_id=rechnung.pk)

        assert teilabnahme.stand == Abnahmestand.ABGERECHNET

    def test_eine_gesamtabnahme_je_auftrag(self, auftrag):
        Abnahme.objects.create(auftrag=auftrag, art=Abnahmeart.GESAMT)

        with pytest.raises(IntegrityError):
            Abnahme.objects.create(auftrag=auftrag, art=Abnahmeart.GESAMT)

    def test_ohne_abnahme_kein_leistungsdatum(self, auftrag):
        abnahme = Abnahme(auftrag=auftrag, art=Abnahmeart.GESAMT,
                          steuerliches_leistungsdatum=REST_ABNAHME)

        with pytest.raises(ValidationError):
            abnahme.full_clean()

    def test_nur_an_einem_festgeschriebenen_auftrag(self, projekt):
        entwurf = services.beleg_anlegen(projekt=projekt,
                                         typ=BelegTyp.AUFTRAG)

        with pytest.raises(ValidationError):
            Abnahme(auftrag=entwurf, art=Abnahmeart.GESAMT).full_clean()


@pytest.mark.django_db
class TestFormular:

    def _formular(self, auftrag, art, positionen, instanz=None):
        return AbnahmeForm(data={
            'auftrag': auftrag.pk, 'art': art,
            'positionen': [p.pk for p in positionen],
        }, instance=instanz)

    def test_teilabnahme_braucht_positionen(self, auftrag):
        formular = self._formular(auftrag, Abnahmeart.TEIL, [])

        assert not formular.is_valid()
        assert 'positionen' in formular.errors

    def test_gesamtabnahme_hat_keine_positionen(self, auftrag, lph_1_4):
        formular = self._formular(auftrag, Abnahmeart.GESAMT, [lph_1_4])

        assert not formular.is_valid()

    def test_eine_position_gehoert_zu_hoechstens_einer_teilabnahme(
            self, auftrag, lph_1_4, teilabnahme):
        formular = self._formular(auftrag, Abnahmeart.TEIL, [lph_1_4])

        assert not formular.is_valid()
        assert 'gehört schon zu' in str(formular.errors['positionen'])


@pytest.mark.django_db
class TestTeilschlussrechnung:

    def test_teilleistung_mit_eigenem_leistungsdatum(self, teilabnahme, lph_1_4):
        """Teilleistung A: 01.09. bis 20.12., abgenommen 20.12.; BT-72 =
        20.12., dazu Zeitraum, Satz und Entgelt aus dem Vertrag."""
        rechnung = services.rechnung_aus_abnahme(abnahme_id=teilabnahme.pk)

        assert rechnung.rechnungsart == Rechnungsart.TEILSCHLUSS
        assert rechnung.steuerliches_leistungsdatum == TEIL_ABNAHME
        position = rechnung.positionen.get()
        assert position.auftragsposition == lph_1_4
        assert position.menge == Decimal('1')
        assert position.einzelpreis == Decimal('18000.00')
        assert position.steuersatz == '19.00'

        rechnung = services.beleg_festschreiben(beleg_id=rechnung.pk)
        xml = facturx.xml_erzeugen(rechnung).decode()
        assert xml_datum(xml, 'OccurrenceDateTime') == TEIL_ABNAHME
        assert xml_datum(xml, 'StartDateTime') == TEIL_BEGINN
        assert xml_datum(xml, 'EndDateTime') == TEIL_ABNAHME
        assert xml_wert(xml, 'RateApplicablePercent') == '19.00'

    def test_verbraucht_das_kontingent(self, teilabnahme, lph_1_4):
        """Die Teilschlussrechnung verbraucht das Kontingent, weil sie anders
        als der Abschlag endgültig ist."""
        rechnung = services.rechnung_aus_abnahme(abnahme_id=teilabnahme.pk)
        services.beleg_festschreiben(beleg_id=rechnung.pk)

        lph_1_4.refresh_from_db()
        assert lph_1_4.offene_menge == Decimal('0')

    def test_die_restleistung_beruehrt_die_teilleistung_nicht(
            self, teilabnahme, auftrag, lph_1_4):
        """Die Restleistung, nach dem Jahreswechsel abgenommen, hat ein eigenes
        Datum; die festgeschriebene Teilschlussrechnung behält ihres."""
        teil = services.beleg_festschreiben(beleg_id=services.
                                            rechnung_aus_abnahme(
                                                abnahme_id=teilabnahme.pk).pk)
        gesamt = Abnahme.objects.create(
            auftrag=auftrag, art=Abnahmeart.GESAMT,
            leistungsbeginn=TEIL_BEGINN, leistungsende=REST_ABNAHME,
            abgenommen_am=REST_ABNAHME)

        schluss = services.rechnung_aus_abnahme(abnahme_id=gesamt.pk)

        assert schluss.rechnungsart == Rechnungsart.SCHLUSS
        assert schluss.steuerliches_leistungsdatum == REST_ABNAHME
        teil.refresh_from_db()
        assert teil.steuerliches_leistungsdatum == TEIL_ABNAHME
        assert lph_1_4.offene_menge == Decimal('0')

    def test_nicht_ohne_teilabnahme(self, projekt):
        """Keine Teilschlussrechnung ohne Teilabnahme, weder über den Service
        noch durch Ändern der Rechnungsart."""
        with pytest.raises(ValidationError):
            services.beleg_anlegen(projekt=projekt, typ=BelegTyp.RECHNUNG,
                                   rechnungsart=Rechnungsart.TEILSCHLUSS)

    def test_nicht_vor_der_abnahme(self, auftrag, lph_1_4):
        abnahme = Abnahme.objects.create(auftrag=auftrag,
                                         art=Abnahmeart.TEIL)
        abnahme.positionen.add(lph_1_4)

        with pytest.raises(services.FalscherStatus):
            services.rechnung_aus_abnahme(abnahme_id=abnahme.pk)

    def test_nur_eine_rechnung_je_abnahme(self, teilabnahme):
        services.rechnung_aus_abnahme(abnahme_id=teilabnahme.pk)

        with pytest.raises(services.FalscherStatus):
            services.rechnung_aus_abnahme(abnahme_id=teilabnahme.pk)

    def test_abgerechnete_abnahme_ist_gesperrt(self, teilabnahme):
        rechnung = services.rechnung_aus_abnahme(abnahme_id=teilabnahme.pk)
        services.beleg_festschreiben(beleg_id=rechnung.pk)
        teilabnahme.abgenommen_am = date(2025, 12, 21)

        with pytest.raises(ValidationError):
            teilabnahme.full_clean()


@pytest.mark.django_db
class TestSchlussrechnung:

    def test_aus_der_gesamtabnahme_ohne_positionen(self, auftrag):
        """Die Schlussrechnung aus der Gesamtabnahme entsteht ohne Positionen;
        die Leistungen kommen über "Erbrachte Leistungen hinzufügen"."""
        gesamt = Abnahme.objects.create(
            auftrag=auftrag, art=Abnahmeart.GESAMT,
            leistungsbeginn=date(2026, 1, 10), leistungsende=date(2026, 9, 20),
            abgenommen_am=date(2026, 9, 20))

        schluss = services.rechnung_aus_abnahme(abnahme_id=gesamt.pk)

        assert schluss.rechnungsart == Rechnungsart.SCHLUSS
        assert schluss.status == BelegStatus.ENTWURF
        assert schluss.steuerliches_leistungsdatum == date(2026, 9, 20)
        assert schluss.leistungsdatum == date(2026, 1, 10)
        assert not schluss.positionen.exists()


@pytest.mark.django_db
class TestMasken:

    def test_die_teilschlussrechnung_traegt_jede_bt_nummer_einmal(
            self, buero, teilabnahme):
        """Jede BT-Nummer erscheint einmal im Label. Regression: "Projekt
        (BT-11) (BT-11)"."""
        from faktura.tests.test_leistungsdaten import ohne_doppelte_bt
        rechnung = services.rechnung_aus_abnahme(abnahme_id=teilabnahme.pk)

        inhalt = buero.get(reverse('admin:faktura_teilschlussrechnung_change',
                                   args=[rechnung.pk])).content.decode()

        assert 'Projekt (BT-11)' in inhalt
        ohne_doppelte_bt(inhalt)

    def test_abnahmen_stehen_im_menue(self, buero):
        inhalt = buero.get(reverse('admin:index')).content.decode()

        assert reverse('admin:faktura_abnahme_changelist') in inhalt

    def test_teilschlussrechnung_hat_kein_hinzufuegen(self, buero):
        antwort = buero.get(
            reverse('admin:faktura_teilschlussrechnung_add'))

        assert antwort.status_code == 403

    def test_rechnung_erzeugen_aus_der_abnahme(self, buero, teilabnahme):
        antwort = buero.get(reverse('admin:faktura_abnahme_detail_rechnung',
                                    args=[teilabnahme.pk]))

        rechnung = teilabnahme.rechnungen.get()
        assert antwort.status_code == 302
        assert rechnung.rechnungsart == Rechnungsart.TEILSCHLUSS
        assert str(rechnung.pk) in antwort['Location']

    @pytest.mark.skipif(
        not apps.is_installed('auswertung'),
        reason='Die Auftragsakte lebt in auswertung; siehe "nur Kern" '
               '(paperwerk/settings/kern.py).')
    def test_die_auftragsakte_zeigt_abnahmen(self, buero, teilabnahme,
                                            auftrag):
        inhalt = buero.get(reverse('auftragsakte', args=[auftrag.pk])
                           ).content.decode()

        assert 'Abnahmen' in inhalt
        assert 'Leistungsphasen 1-4' in inhalt
        assert '20.12.2025' in inhalt
        assert f'?auftrag={auftrag.pk}' in inhalt

    def test_die_maske_schlaegt_den_zeitraum_aus_der_erfassung_vor(
            self, buero, auftrag, lph_1_4):
        from django.contrib.auth import get_user_model

        from erfassung.models import Erfassungszeile
        person = get_user_model().objects.create_user(username='anna')
        for tag in (date(2025, 9, 3), date(2025, 11, 28)):
            Erfassungszeile.objects.create(
                projekt=auftrag.projekt, auftragsposition=lph_1_4,
                benutzer=person, datum=tag, menge=Decimal('1'),
                beschreibung='Planung')

        inhalt = buero.get(reverse('admin:faktura_abnahme_add')
                           + f'?auftrag={auftrag.pk}').content.decode()

        assert '03.09.2025' in inhalt
        assert '28.11.2025' in inhalt


def abschlag(projekt, betrag, auftragsposition=None, tag=date(2025, 11, 3),
             bezahlt=False):
    """Festgeschriebener Abschlag über ``betrag`` netto zu 19 %.
    ``bezahlt``: voll bezahlt, weil die Schlussrechnung ihn sonst als
    Restzeile erneut fordert (R-174) und netto nichts abgesetzt bleibt."""
    beleg = services.beleg_anlegen(
        projekt=projekt, typ=BelegTyp.RECHNUNG,
        rechnungsart=Rechnungsart.ABSCHLAG, betreff='Abschlag',
        leistungsdatum=TEIL_BEGINN, leistungsdatum_bis=tag)
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Abschlag Planung', menge=Decimal('1'),
        einheit='pausch', einzelpreis=Decimal(betrag),
        steuersatz='19.00', auftragsposition=auftragsposition)
    beleg = services.beleg_festschreiben(beleg_id=beleg.pk)
    if bezahlt:
        services.zahlung_verbuchen(
            beleg_id=beleg.pk, datum=tag,
            betrag=services.belegsummen(beleg).brutto)
    return beleg


@pytest.mark.django_db
class TestAbschlaegeAbsetzen:
    """Gestellte Abschläge werden genau einmal in der richtigen Rechnung
    abgesetzt, im XML als BT-113."""

    def test_die_teilschlussrechnung_setzt_den_abschlag_ihrer_teilleistung_ab(
            self, projekt, teilabnahme, lph_1_4):
        auf_teil = abschlag(projekt, '5000.00', auftragsposition=lph_1_4)
        pauschal = abschlag(projekt, '3000.00')

        rechnung = services.rechnung_aus_abnahme(abnahme_id=teilabnahme.pk)

        abzuege = list(rechnung.positionen.filter(ist_abzug=True,
                                                  ist_abschlagsrest=False))
        assert [a.abgesetzte_position.beleg for a in abzuege] == [auf_teil]
        assert pauschal not in [a.abgesetzte_position.beleg for a in abzuege]
        assert abzuege[0].einzelpreis == Decimal('-5000.00')

    def test_die_betraege_im_xml(self, projekt, teilabnahme, lph_1_4):
        """18.000 volle Leistung, 5.000 Abschlag, je 19 %:
        BT-106 18.000,00 / BT-110 3.420,00 / BT-112 21.420,00 /
        BT-113 5.950,00 / BT-115 15.470,00, dazu nur eine Position."""
        abschlag(projekt, '5000.00', auftragsposition=lph_1_4, bezahlt=True)
        rechnung = services.beleg_festschreiben(beleg_id=services.
                                                rechnung_aus_abnahme(
                                                    abnahme_id=teilabnahme.pk
                                                ).pk)

        xml = facturx.xml_erzeugen(rechnung).decode()

        assert xml.count('<ram:IncludedSupplyChainTradeLineItem>') == 1
        assert Decimal(xml_wert(xml, 'TaxBasisTotalAmount')) == Decimal(
            '18000.00')
        assert Decimal(xml_wert(xml, 'TaxTotalAmount')) == Decimal('3420.00')
        assert Decimal(xml_wert(xml, 'GrandTotalAmount')) == Decimal(
            '21420.00')
        assert Decimal(xml_wert(xml, 'TotalPrepaidAmount')) == Decimal(
            '5950.00')
        assert Decimal(xml_wert(xml, 'DuePayableAmount')) == Decimal(
            '15470.00')
        # Zahlbetrag wie im PDF.
        assert services.belegsummen(rechnung).brutto == Decimal('15470.00')

    def test_bt_115_ist_bt_112_minus_bt_113_auf_den_cent(
            self, projekt, auftrag):
        """BR-CO-16 mit Beträgen, bei denen die Steuer je Satz anders rundet
        als je Zeile."""
        abschlag(projekt, '333.33', bezahlt=True)
        abschlag(projekt, '333.33', bezahlt=True)
        gesamt = Abnahme.objects.create(
            auftrag=auftrag, art=Abnahmeart.GESAMT,
            leistungsbeginn=TEIL_BEGINN, leistungsende=REST_ABNAHME,
            abgenommen_am=REST_ABNAHME)
        schluss = services.rechnung_aus_abnahme(abnahme_id=gesamt.pk)
        services.position_hinzufuegen(
            beleg=schluss, bezeichnung='Planung', menge=Decimal('1'),
            einheit='pausch', einzelpreis=Decimal('1000.01'),
            steuersatz='19.00')
        schluss = services.beleg_festschreiben(beleg_id=schluss.pk)

        xml = facturx.xml_erzeugen(schluss).decode()

        grand = Decimal(xml_wert(xml, 'GrandTotalAmount'))
        prepaid = Decimal(xml_wert(xml, 'TotalPrepaidAmount'))
        due = Decimal(xml_wert(xml, 'DuePayableAmount'))
        assert due == grand - prepaid
        assert due == services.belegsummen(schluss).brutto

    def test_die_schlussrechnung_nimmt_den_rest_genau_einmal(
            self, projekt, auftrag, teilabnahme, lph_1_4):
        abschlag(projekt, '5000.00', auftragsposition=lph_1_4)
        pauschal = abschlag(projekt, '3000.00')
        services.beleg_festschreiben(beleg_id=services.rechnung_aus_abnahme(
            abnahme_id=teilabnahme.pk).pk)
        gesamt = Abnahme.objects.create(
            auftrag=auftrag, art=Abnahmeart.GESAMT,
            abgenommen_am=REST_ABNAHME)

        schluss = services.rechnung_aus_abnahme(abnahme_id=gesamt.pk)
        noch_einmal = services.abschlaege_absetzen(beleg_id=schluss.pk)

        abzuege = list(schluss.positionen.filter(ist_abzug=True,
                                                 ist_abschlagsrest=False))
        assert [a.abgesetzte_position.beleg for a in abzuege] == [pauschal]
        assert noch_einmal == []

    def test_die_korrektur_behaelt_die_absetzung_ohne_doppelung(
            self, projekt, auftrag):
        pauschal = abschlag(projekt, '3000.00')
        gesamt = Abnahme.objects.create(
            auftrag=auftrag, art=Abnahmeart.GESAMT,
            abgenommen_am=REST_ABNAHME)
        schluss = services.rechnung_aus_abnahme(abnahme_id=gesamt.pk)
        services.position_hinzufuegen(
            beleg=schluss, bezeichnung='Planung', menge=Decimal('1'),
            einheit='pausch', einzelpreis=Decimal('42000.00'),
            steuersatz='19.00')
        schluss = services.beleg_festschreiben(beleg_id=schluss.pk)

        storno, neu = services.rechnung_korrigieren(beleg_id=schluss.pk)

        # Der neue Entwurf setzt den Abschlag mit Verweis weiter ab; erneutes
        # Absetzen fügt nichts hinzu. Das Storno zählt nicht.
        abzug = neu.positionen.get(ist_abzug=True, ist_abschlagsrest=False)
        assert abzug.abgesetzte_position.beleg == pauschal
        assert services.abschlaege_absetzen(beleg_id=neu.pk) == []
        assert not storno.positionen.filter(
            abgesetzte_position__isnull=False).exists()

    def test_offene_abschlaege_werden_gemeldet(self, projekt, auftrag):
        pauschal = abschlag(projekt, '3000.00')
        gesamt = Abnahme.objects.create(
            auftrag=auftrag, art=Abnahmeart.GESAMT,
            abgenommen_am=REST_ABNAHME)
        schluss = services.rechnung_aus_abnahme(abnahme_id=gesamt.pk)

        assert [o.abschlag for o in services.offene_abgesetzte_abschlaege(
            schluss)] == [pauschal]

        services.zahlung_verbuchen(beleg_id=pauschal.pk, datum=REST_ABNAHME,
                                   betrag=Decimal('3570.00'))

        assert services.offene_abgesetzte_abschlaege(schluss) == []


@pytest.mark.django_db
class TestNichtsDoppelt:
    """Abzugszeilen ohne Verweis verhindern doppelte Absetzung.

    Regression: Eine Teilschlussrechnung bestand nur aus Abzügen, weil die
    Teilleistung mit einer älteren Schlussrechnung abgerechnet war, deren
    Abzugszeilen keinen Verweis hatten; die Abschläge galten als frei und
    wurden ein zweites Mal abgesetzt."""

    def _voll_abgerechnet(self, projekt, lph_1_4):
        beleg = services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG,
            steuerliches_leistungsdatum=TEIL_ABNAHME)
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Leistungsphasen 1-4',
            menge=Decimal('1'), einheit='pausch',
            einzelpreis=Decimal('18000.00'), steuersatz='19.00',
            auftragsposition=lph_1_4)
        return services.beleg_festschreiben(beleg_id=beleg.pk)

    def test_keine_teilschlussrechnung_ohne_offene_menge(
            self, projekt, teilabnahme, lph_1_4):
        self._voll_abgerechnet(projekt, lph_1_4)

        with pytest.raises(services.FalscherStatus,
                           match='vollständig abgerechnet'):
            services.rechnung_aus_abnahme(abnahme_id=teilabnahme.pk)
        assert not teilabnahme.rechnungen.exists()

    def test_die_maske_nimmt_keine_abgerechnete_position(
            self, projekt, auftrag, lph_1_4):
        self._voll_abgerechnet(projekt, lph_1_4)

        formular = AbnahmeForm(data={
            'auftrag': auftrag.pk, 'art': Abnahmeart.TEIL,
            'positionen': [lph_1_4.pk]})

        assert not formular.is_valid()
        assert 'vollständig abgerechnet' in str(formular.errors['positionen'])

    def test_von_hand_abgesetzte_abschlaege_bleiben_abgesetzt(
            self, projekt, auftrag):
        """Altdaten: eine Abzugszeile je Abschlag, nur mit seiner Nummer im
        Text."""
        alt = abschlag(projekt, '3000.00')
        frei = abschlag(projekt, '2000.00', tag=date(2025, 11, 20))
        schluss = services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG,
            rechnungsart=Rechnungsart.SCHLUSS,
            steuerliches_leistungsdatum=REST_ABNAHME)
        services.position_hinzufuegen(
            beleg=schluss, bezeichnung='Planung', menge=Decimal('1'),
            einheit='pausch', einzelpreis=Decimal('1000.00'),
            steuersatz='19.00')
        services.position_hinzufuegen(
            beleg=schluss, bezeichnung=f'1. Abschlagsrechnung {alt.nummer}',
            menge=Decimal('1'), einheit='', einzelpreis=Decimal('-3000.00'),
            steuersatz='19.00', ist_abzug=True)
        services.beleg_festschreiben(beleg_id=schluss.pk)
        gesamt = Abnahme.objects.create(
            auftrag=auftrag, art=Abnahmeart.GESAMT,
            abgenommen_am=REST_ABNAHME)

        neu = services.rechnung_aus_abnahme(abnahme_id=gesamt.pk)

        abgesetzt = [p.abgesetzte_position.beleg
                     for p in neu.positionen.filter(ist_abzug=True,
                                                    ist_abschlagsrest=False)]
        assert abgesetzt == [frei]


@pytest.mark.django_db
class TestKorrigierenBehaeltDieArt:
    """Der neue Entwurf aus "Rechnung korrigieren" behält die Rechnungsart.

    Regression: Er wurde immer eine gewöhnliche Rechnung, auch bei
    Abschlag und Schluss."""

    def test_abschlag_bleibt_abschlag(self, projekt):
        original = abschlag(projekt, '3000.00')

        _, neu = services.rechnung_korrigieren(beleg_id=original.pk)

        assert neu.rechnungsart == Rechnungsart.ABSCHLAG
        assert neu.steuerliches_leistungsdatum is None

    def test_teilschluss_bleibt_teilschluss_mit_abnahme(self, teilabnahme):
        original = services.beleg_festschreiben(beleg_id=services.
                                                rechnung_aus_abnahme(
                                                    abnahme_id=teilabnahme.pk
                                                ).pk)

        _, neu = services.rechnung_korrigieren(beleg_id=original.pk)

        assert neu.rechnungsart == Rechnungsart.TEILSCHLUSS
        assert neu.abnahme == teilabnahme
        neu.full_clean(exclude=['nummer'])
