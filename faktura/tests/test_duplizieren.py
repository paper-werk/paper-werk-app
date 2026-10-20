"""Duplizieren und Umwandeln von Belegen."""

from datetime import time, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from faktura import services
from faktura.models import (
    Beleg,
    BelegStatus,
    BelegTyp,
    Kontakt,
    Projekt,
    Rechnungsart,
)


@pytest.mark.django_db
class TestAngebotDuplizieren:
    """Duplizieren eines Angebots in jedem Zustand.

    Anders als beim Umwandeln ohne Vorgänger, also ohne Belegkette und ohne
    Sperre am Original.
    """

    @pytest.fixture
    def angebot(self, kunde):
        from faktura.models import Ansprechpartner
        beleg = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.ANGEBOT, betreff='Halle Nord',
            leistungsdatum=timezone.localdate(),
        )
        beleg.ansprechpartner = Ansprechpartner.objects.create(
            kontakt=kunde, nachname='Huber')
        beleg.empfaenger_email = 'einkauf@muster.example'
        beleg.kopftext = 'Wir bieten an:'
        beleg.save()
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Montage', langtext='inkl. Anfahrt',
            menge=Decimal('10'), einheit='Std',
            einzelpreis=Decimal('89.50'), steuersatz='19.00',
        )
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Material', menge=Decimal('0.75'),
            einzelpreis=Decimal('89.50'), steuersatz='7.00',
        )
        return beleg

    def _positionen(self, beleg):
        return list(beleg.positionen.values_list(
            'position', 'bezeichnung', 'langtext', 'menge', 'einheit',
            'einzelpreis', 'steuersatz', 'art', 'ist_abzug'))

    def test_aus_dem_entwurf(self, angebot):
        kopie = services.beleg_duplizieren(beleg_id=angebot.pk).beleg

        assert kopie.pk != angebot.pk
        assert kopie.typ == BelegTyp.ANGEBOT
        assert kopie.status == BelegStatus.ENTWURF
        assert self._positionen(kopie) == self._positionen(angebot)

    def test_aus_dem_festgeschriebenen(self, angebot):
        """Die Kopie eines festgeschriebenen Angebots erhält beim Festschreiben
        eine eigene Nummer."""
        original = services.beleg_festschreiben(beleg_id=angebot.pk)

        kopie = services.beleg_duplizieren(beleg_id=original.pk).beleg

        assert kopie.status == BelegStatus.ENTWURF
        assert not kopie.nummer
        assert self._positionen(kopie) == self._positionen(original)

        kopie = services.beleg_festschreiben(beleg_id=kopie.pk)
        assert kopie.nummer and kopie.nummer != original.nummer

    def test_die_summen_sind_dieselben(self, angebot):
        """Die Summen sind gleich, einschließlich Rundung
        (0,75 x 89,50 = 67,13)."""
        kopie = services.beleg_duplizieren(beleg_id=angebot.pk).beleg

        vorher = services.belegsummen(angebot)
        nachher = services.belegsummen(kopie)
        assert nachher.netto == vorher.netto == Decimal('962.13')
        assert nachher.brutto == vorher.brutto

    def test_kopf_und_empfaenger_kommen_mit(self, angebot):
        kopie = services.beleg_duplizieren(beleg_id=angebot.pk).beleg

        assert kopie.betreff == 'Halle Nord'
        assert kopie.kunde_id == angebot.kunde_id
        assert kopie.ansprechpartner_id == angebot.ansprechpartner_id
        assert kopie.empfaenger == angebot.empfaenger
        assert kopie.empfaenger_email == 'einkauf@muster.example'
        assert kopie.kopftext == 'Wir bieten an:'
        assert kopie.leistungsdatum == angebot.leistungsdatum

    def test_kein_vorgaenger_und_das_original_bleibt_loeschbar(self, angebot):
        """Ohne Vorgänger, weil ``PROTECT`` sonst das Original dauerhaft
        sperrte."""
        kopie = services.beleg_duplizieren(beleg_id=angebot.pk).beleg

        assert kopie.vorgaenger_id is None
        angebot.delete()
        assert Beleg.objects.filter(pk=kopie.pk).exists()

    def test_das_original_bleibt_unberuehrt(self, angebot):
        vorher = self._positionen(angebot)

        services.beleg_duplizieren(beleg_id=angebot.pk)

        angebot.refresh_from_db()
        assert angebot.status == BelegStatus.ENTWURF
        assert self._positionen(angebot) == vorher

    def test_kein_auftrag(self, kunde):
        """Kein Duplizieren des Auftrags, weil er an Kontingenten und
        Nachträgen hängt; dafür gibt es "Nachtrag anlegen"."""
        auftrag = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.AUFTRAG)

        with pytest.raises(services.FalscherStatus):
            services.beleg_duplizieren(beleg_id=auftrag.pk)


@pytest.mark.django_db
class TestRechnungDuplizieren:
    """Duplizieren einer Rechnung wie beim Angebot, mit drei Regeln für die
    Bezüge der Positionen:

    * Positionen aus der Leistungserfassung kommen mit, ohne Bezug zu den
      Zeiten.
    * Positionen aus Fremdleistungen kommen nicht mit.
    * Der Bezug zur Auftragsposition kommt mit; die Prüfung des Kontingents
      greift.
    """

    @pytest.fixture
    def projekt(self, kunde):
        return Projekt.objects.create(nummer='P-1', bezeichnung='Halle',
                                      kunde=kunde)

    @pytest.fixture
    def auftrag(self, projekt):
        beleg = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.AUFTRAG,
                                       betreff='Halle')
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Montage', menge=Decimal('10'),
            einheit='Std', einzelpreis=Decimal('89.50'),
            steuersatz='19.00')
        return services.beleg_festschreiben(beleg_id=beleg.pk)

    def _rechnung(self, auftrag, menge='6', rechnungsart=None):
        rechnung = services.beleg_umwandeln(beleg_id=auftrag.pk,
                                            neuer_typ=BelegTyp.RECHNUNG)
        if rechnungsart:
            rechnung.rechnungsart = rechnungsart
            rechnung.save(update_fields=['rechnungsart'])
        rechnung.leistungsdatum = timezone.localdate()
        rechnung.save(update_fields=['leistungsdatum'])
        # Die Umwandlung kopiert ohne Auftragsbezug; hier wie nach der
        # Übernahme aus der Erfassung mit.
        rechnung.positionen.update(
            auftragsposition=auftrag.positionen.get(), menge=Decimal(menge))
        return rechnung

    def test_die_kopie_ist_eine_rechnung_am_selben_auftrag(self, auftrag):
        rechnung = services.beleg_festschreiben(
            beleg_id=self._rechnung(auftrag).pk)

        kopie = services.beleg_duplizieren(beleg_id=rechnung.pk).beleg

        assert kopie.typ == BelegTyp.RECHNUNG
        assert kopie.rechnungsart == Rechnungsart.NORMAL
        assert kopie.status == BelegStatus.ENTWURF
        assert not kopie.nummer
        # Gleicher Vorgänger wie die alte Rechnung.
        assert kopie.vorgaenger_id == auftrag.pk
        assert not kopie.mahnstufe
        assert not kopie.zahlungszuordnungen.exists()

    def test_die_summen_sind_dieselben(self, auftrag):
        rechnung = self._rechnung(auftrag, menge='0.75')

        kopie = services.beleg_duplizieren(beleg_id=rechnung.pk).beleg

        # 0,75 x 89,50 = 67,125, kaufmännisch 67,13, in beiden.
        assert services.belegsummen(kopie).netto \
            == services.belegsummen(rechnung).netto == Decimal('67.13')
        assert services.belegsummen(kopie).brutto \
            == services.belegsummen(rechnung).brutto

    def test_die_abschlagsrechnung_bleibt_eine(self, auftrag):
        rechnung = self._rechnung(auftrag, rechnungsart=Rechnungsart.ABSCHLAG)

        kopie = services.beleg_duplizieren(beleg_id=rechnung.pk).beleg

        assert kopie.rechnungsart == Rechnungsart.ABSCHLAG

    def test_keine_schlussrechnung(self, auftrag):
        """Keine Schlussrechnung, weil ein Duplikat die Abschläge ein zweites
        Mal absetzte."""
        rechnung = self._rechnung(auftrag, rechnungsart=Rechnungsart.SCHLUSS)

        with pytest.raises(services.FalscherStatus):
            services.beleg_duplizieren(beleg_id=rechnung.pk)

    def test_der_auftragsbezug_kommt_mit(self, auftrag):
        rechnung = self._rechnung(auftrag)

        kopie = services.beleg_duplizieren(beleg_id=rechnung.pk).beleg

        assert kopie.positionen.get().auftragsposition_id \
            == auftrag.positionen.get().pk

    def test_und_schuetzt_das_kontingent(self, auftrag):
        """10 Std beauftragt, 6 abgerechnet: Das Duplikat über weitere 6 lässt
        sich nicht versenden."""
        rechnung = services.beleg_festschreiben(
            beleg_id=self._rechnung(auftrag, menge='6').pk)
        kopie = services.beleg_duplizieren(beleg_id=rechnung.pk).beleg

        with pytest.raises(services.MengeUeberschritten):
            services.beleg_festschreiben(beleg_id=kopie.pk)

    def test_innerhalb_des_kontingents_geht_es(self, auftrag):
        """Gegenprobe: 4 + 4 von 10."""
        rechnung = services.beleg_festschreiben(
            beleg_id=self._rechnung(auftrag, menge='4').pk)
        kopie = services.beleg_duplizieren(beleg_id=rechnung.pk).beleg

        kopie = services.beleg_festschreiben(beleg_id=kopie.pk)

        assert kopie.nummer and kopie.nummer != rechnung.nummer
        assert services.abgerechnete_mengen(
            [auftrag.positionen.get().pk])[auftrag.positionen.get().pk] \
            == Decimal('8')

    def test_erfasste_zeiten_bleiben_an_der_alten_rechnung(
            self, auftrag, projekt):
        """Die Position wird kopiert, die Zeiten bleiben an der alten
        Rechnung."""
        from django.contrib.auth import get_user_model

        from erfassung import services as erfassung_services
        from faktura.models import Katalogposition, Leistungsart
        rechnung = self._rechnung(auftrag)
        leistung = Katalogposition.objects.create(
            bezeichnung='Montage', einheit='Std',
            einzelpreis=Decimal('89.50'), art=Leistungsart.ZEIT)
        person = get_user_model().objects.create_user(username='monteur')
        zeile = erfassung_services.zeile_erfassen(
            projekt=projekt, leistung=leistung, benutzer=person,
            von=time(7, 0), bis=time(13, 0), beschreibung='Montage')
        alte_position = rechnung.positionen.get()
        zeile.abgerechnet_in = alte_position
        zeile.save(update_fields=['abgerechnet_in'])

        kopie = services.beleg_duplizieren(beleg_id=rechnung.pk).beleg

        neue_position = kopie.positionen.get()
        assert neue_position.bezeichnung == 'Montage'
        assert not neue_position.erfassung.exists()
        zeile.refresh_from_db()
        assert zeile.abgerechnet_in_id == alte_position.pk

    def test_fremdleistungen_kommen_nicht_mit(self, auftrag, projekt):
        from erfassung.models import Eingangsrechnung, Fremdleistung
        rechnung = self._rechnung(auftrag)
        labor = Kontakt.objects.create(ist_kunde=False, ist_lieferant=True,
                                       name='Labor')
        eingang = Eingangsrechnung.objects.create(
            lieferant=labor, nummer='L-1', datum=timezone.localdate(),
            betrag_netto=Decimal('100.00'))
        analyse = services.position_hinzufuegen(
            beleg=rechnung, bezeichnung='Analyse', menge=Decimal('1'),
            einzelpreis=Decimal('150.00'), steuersatz='19.00')
        Fremdleistung.objects.create(
            rechnung=eingang, projekt=projekt, bezeichnung='Analyse',
            einkaufspreis=Decimal('100.00'), abgerechnet_in=analyse)

        duplikat = services.beleg_duplizieren(beleg_id=rechnung.pk)

        assert [p.bezeichnung for p in duplikat.beleg.positionen.all()] \
            == ['Montage']
        assert duplikat.ohne_fremdleistungen == 1


@pytest.mark.django_db
class TestUmwandelnNurWasFestgeschriebenIst:
    """Umgewandelt werden nur festgeschriebene Belege.

    Der neue Beleg verweist über ``vorgaenger`` mit ``PROTECT`` auf das
    Original; ein umgewandelter Entwurf wäre sonst dauerhaft nicht
    löschbar.
    """

    def test_ein_entwurf_laesst_sich_nicht_umwandeln(self, kunde):
        angebot = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.ANGEBOT, betreff='Halle Nord'
        )
        services.position_hinzufuegen(
            beleg=angebot, bezeichnung='Montage', menge=Decimal('1'),
            einzelpreis=Decimal('500.00'), steuersatz='19.00',
        )

        with pytest.raises(services.FalscherStatus):
            services.beleg_umwandeln(
                beleg_id=angebot.pk, neuer_typ=BelegTyp.RECHNUNG
            )

    def test_ein_festgeschriebenes_angebot_geht(self, kunde):
        """Gegenprobe."""
        angebot = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.ANGEBOT, betreff='Halle Nord'
        )
        services.position_hinzufuegen(
            beleg=angebot, bezeichnung='Montage', menge=Decimal('1'),
            einzelpreis=Decimal('500.00'), steuersatz='19.00',
        )
        festgeschrieben = services.beleg_festschreiben(beleg_id=angebot.pk)

        neu = services.beleg_umwandeln(
            beleg_id=festgeschrieben.pk, neuer_typ=BelegTyp.RECHNUNG
        )

        assert neu.typ == BelegTyp.RECHNUNG
        assert neu.status == BelegStatus.ENTWURF
        assert neu.vorgaenger_id == festgeschrieben.pk


@pytest.mark.django_db
class TestDerTerminWandertMit:
    """``leistungsdatum`` und ``leistungsdatum_bis`` werden kopiert.

    Am Angebot ist das Feldpaar "Ausführung ab/bis", an der Rechnung das
    Leistungsdatum nach § 14 Abs. 4 Nr. 6 UStG. Ohne Übernahme fehlte der
    Rechnung die Pflichtangabe.
    """

    def test_beim_umwandeln(self, kunde):
        von = timezone.localdate()
        bis = von + timedelta(days=14)
        angebot = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.ANGEBOT, betreff='Halle Nord'
        )
        angebot.leistungsdatum = von
        angebot.leistungsdatum_bis = bis
        angebot.save()
        services.position_hinzufuegen(
            beleg=angebot, bezeichnung='Montage', menge=Decimal('1'),
            einzelpreis=Decimal('500.00'), steuersatz='19.00',
        )
        festgeschrieben = services.beleg_festschreiben(beleg_id=angebot.pk)

        rechnung = services.beleg_umwandeln(
            beleg_id=festgeschrieben.pk, neuer_typ=BelegTyp.RECHNUNG
        )

        assert rechnung.leistungsdatum == von
        assert rechnung.leistungsdatum_bis == bis

    def test_beim_stornieren(self, rechnung):
        """Das Storno hat denselben Leistungszeitraum wie das Original, weil es
        diese Leistung aufhebt."""
        bis = timezone.localdate() + timedelta(days=3)
        rechnung.leistungsdatum_bis = bis
        rechnung.save()
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)

        storno, _ = services.rechnung_korrigieren(beleg_id=original.pk)

        assert storno.leistungsdatum == original.leistungsdatum
        assert storno.leistungsdatum_bis == bis
