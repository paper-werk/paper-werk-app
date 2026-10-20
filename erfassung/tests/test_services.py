"""Fachliche Regeln der Leistungserfassung (``erfassung/services``)."""

from datetime import time, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from erfassung import services
from erfassung.models import Erfassungszeile
from faktura.models import Projekt


@pytest.mark.django_db
class TestZeileErfassen:

    def test_legt_eine_zeile_an(self, projekt, zeitleistung, mitarbeiter):
        zeile = services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            von=time(7, 0), bis=time(14, 15),
            beschreibung='Fundament geschalt',
        )

        assert zeile.pk is not None
        assert zeile.projekt == projekt
        assert zeile.leistung == zeitleistung
        assert zeile.benutzer == mitarbeiter
        assert zeile.datum == timezone.localdate()

    def test_die_dauer_ergibt_sich_aus_von_und_bis(
        self, projekt, zeitleistung, mitarbeiter
    ):
        """Die Dauer wird aus von und bis berechnet und gespeichert, damit
        Summen und Sortierung in der Datenbank laufen."""
        zeile = services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            von=time(7, 0), bis=time(14, 15), beschreibung='Arbeit',
        )

        assert zeile.dauer_minuten == 435
        assert zeile.dauer == '7:15'

    @pytest.mark.parametrize('von, bis', [
        (None, None),
        (time(7, 0), None),
        (None, time(14, 15)),
    ])
    def test_eine_zeitleistung_ohne_dauer_wird_abgelehnt(
        self, projekt, zeitleistung, mitarbeiter, von, bis
    ):
        """Eine Zeitleistung ohne vollständige Uhrzeiten wird abgelehnt.

        Alle drei Fälle ergeben die Dauer null und damit eine Zeile ohne
        Umfang.
        """
        with pytest.raises(ValidationError) as fehler:
            services.zeile_erfassen(
                projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
                von=von, bis=bis, beschreibung='Arbeit',
            )

        assert 'von' in fehler.value.message_dict

    def test_die_endzeit_muss_nach_der_anfangszeit_liegen(
        self, projekt, zeitleistung, mitarbeiter
    ):
        """bis muss nach von liegen.

        Eine Schicht über Mitternacht wird als zwei Zeilen erfasst, eine je
        Tag.
        """
        with pytest.raises(ValidationError):
            services.zeile_erfassen(
                projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
                von=time(22, 0), bis=time(2, 0), beschreibung='Nachtschicht',
            )

    def test_ohne_person_geht_es_nicht(self, projekt, zeitleistung):
        with pytest.raises(services.PersonFehlt):
            services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
                projekt=projekt, leistung=zeitleistung, benutzer=None,
                beschreibung='Arbeit',
            )

    def test_nicht_in_die_zukunft(self, projekt, zeitleistung, mitarbeiter):
        """Ein Datum in der Zukunft wird abgelehnt, vor allem gegen
        Tippfehler im Jahr."""
        with pytest.raises(ValidationError):
            services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
                projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
                beschreibung='Arbeit',
                datum=timezone.localdate() + timedelta(days=1),
            )

    def test_gestern_geht(self, projekt, zeitleistung, mitarbeiter):
        """Gegenprobe: Vergangene Tage sind erlaubt."""
        zeile = services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Arbeit',
            datum=timezone.localdate() - timedelta(days=1),
        )

        assert zeile.pk is not None


@pytest.mark.django_db
class TestDieGrundlageEinerZeile:
    """Genau eine Grundlage je Zeile.

    Regelfall ist die Auftragsposition, die Katalogposition die Ausnahme.
    Beide zugleich ergäben zwei Preise, keine eine Zeile ohne
    Abrechnungsgrundlage.
    """

    def test_auf_eine_auftragsposition_kontieren(self, projekt,
                                                 auftragsposition, mitarbeiter):
        zeile = services.zeile_erfassen(
            projekt=projekt, auftragsposition=auftragsposition,
            benutzer=mitarbeiter, von=time(8, 0), bis=time(12, 0),
            beschreibung='Entwurfsplanung',
        )

        assert zeile.leistung_id is None
        assert zeile.grundlage == auftragsposition
        assert zeile.leistungsbezeichnung == 'Planung Lph 1-4'
        assert zeile.einheit == 'Std'
        assert zeile.ist_zeitleistung

    def test_der_preis_kommt_aus_dem_vertrag(self, projekt, auftragsposition,
                                             mitarbeiter):
        """Mit Auftragsposition kommt der Preis aus dem Auftrag, also aus dem
        vereinbarten Vertrag."""
        zeile = services.zeile_erfassen(
            projekt=projekt, auftragsposition=auftragsposition,
            benutzer=mitarbeiter, von=time(8, 0), bis=time(12, 0),
            beschreibung='Entwurfsplanung',
        )

        assert zeile.einzelpreis == Decimal('95.00')

    def test_beides_zugleich_geht_nicht(self, projekt, auftragsposition,
                                        zeitleistung, mitarbeiter):
        with pytest.raises(ValidationError) as fehler:
            services.zeile_erfassen(
                projekt=projekt, auftragsposition=auftragsposition,
                leistung=zeitleistung, benutzer=mitarbeiter,
                von=time(8, 0), bis=time(12, 0), beschreibung='Beides',
            )

        assert 'leistung' in fehler.value.error_dict

    def test_keines_von_beiden_geht_auch_nicht(self, projekt, mitarbeiter):
        with pytest.raises(ValidationError) as fehler:
            services.zeile_erfassen(
                projekt=projekt, benutzer=mitarbeiter,
                von=time(8, 0), bis=time(12, 0), beschreibung='Nichts',
            )

        # Fehler am Feld Leistung, weil die Auftragsposition optional ist und
        # ein Projekt ohne Auftrag keine hat.
        assert list(fehler.value.error_dict) == ['leistung']

    def test_ein_auftrag_eines_fremden_vorhabens_geht_nicht(
        self, projekt, auftragsposition, kunde, mitarbeiter
    ):
        """Eine Auftragsposition eines anderen Vorhabens wird abgelehnt, damit
        die Leistung nicht auf die Rechnung eines anderen Kunden gelangt."""
        anderes = Projekt.objects.create(
            nummer='2026-099', bezeichnung='Ganz woanders', kunde=kunde)

        with pytest.raises(ValidationError) as fehler:
            services.zeile_erfassen(
                projekt=anderes, auftragsposition=auftragsposition,
                benutzer=mitarbeiter, von=time(8, 0), bis=time(12, 0),
                beschreibung='Falsches Vorhaben',
            )

        assert 'auftragsposition' in fehler.value.error_dict

    def test_die_uebernahme_traegt_den_bezug_auf_die_rechnung(
        self, projekt, auftragsposition, mitarbeiter
    ):
        """Nach der Übernahme verweist die Rechnungsposition auf die
        Auftragsposition."""
        services.zeile_erfassen(
            projekt=projekt, auftragsposition=auftragsposition,
            benutzer=mitarbeiter, von=time(8, 0), bis=time(12, 0),
            beschreibung='Entwurfsplanung',
        )

        beleg, _ = services.in_rechnung_uebernehmen(
            zeilen=Erfassungszeile.objects.all())

        position = beleg.positionen.get()
        assert position.auftragsposition == auftragsposition
        assert position.einzelpreis == Decimal('95.00')
        assert position.menge == Decimal('4')

    def test_katalog_und_auftrag_landen_nicht_in_einem_topf(
        self, projekt, auftragsposition, zeitleistung, mitarbeiter
    ):
        """Auftrags- und Katalogposition mit gleicher ID ergeben getrennte
        Positionen.

        Mit der ID allein als Gruppierungsschlüssel entstünde eine Position
        mit dem Preis der einen und den Stunden beider.
        """
        services.zeile_erfassen(
            projekt=projekt, auftragsposition=auftragsposition,
            benutzer=mitarbeiter, von=time(8, 0), bis=time(10, 0),
            beschreibung='Auf den Auftrag',
        )
        services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            von=time(10, 0), bis=time(12, 0), beschreibung='Aus dem Katalog',
        )

        vorschau = services.abrechnungsvorschau(Erfassungszeile.objects.all())

        assert len(vorschau.positionen) == 2


@pytest.mark.django_db
class TestDieLeistungMussKontierbarSein:
    """Nur kontierbare Katalogpositionen sind wählbar.

    Der Katalog dient Angeboten und Erfassung. Das Kennzeichen blendet
    Positionen wie "Baustelleneinrichtung pauschal" in der Erfassung aus.
    """

    def test_eine_gesperrte_leistung_wird_abgewiesen(
        self, projekt, nur_fuer_angebote, mitarbeiter
    ):
        with pytest.raises(services.LeistungNichtKontierbar):
            services.zeile_erfassen(
                projekt=projekt, leistung=nur_fuer_angebote,
                benutzer=mitarbeiter, beschreibung='Arbeit',
            )

    def test_eine_freigegebene_geht(self, projekt, zeitleistung, mitarbeiter):
        """Gegenprobe: Eine kontierbare Position ist wählbar."""
        zeile = services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Arbeit',
        )

        assert zeile.pk is not None

    def test_auch_beim_umhaengen(self, projekt, zeitleistung,
                                 nur_fuer_angebote, mitarbeiter):
        """Auch beim Ändern auf eine nicht kontierbare Leistung wird
        abgelehnt."""
        zeile = services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Arbeit',
        )

        with pytest.raises(services.LeistungNichtKontierbar):
            services.zeile_aendern(zeile_id=zeile.pk, leistung=nur_fuer_angebote)


@pytest.mark.django_db
class TestMengenleistungen:
    """Mengenleistungen wie Anfahrt, Material und Pauschalen."""

    def test_die_menge_wird_uebernommen(
        self, projekt, mengenleistung, mitarbeiter
    ):
        zeile = services.zeile_erfassen(
            projekt=projekt, leistung=mengenleistung, benutzer=mitarbeiter,
            menge=Decimal('23'), beschreibung='Hin und zurück',
        )

        assert zeile.menge == Decimal('23.000')
        assert zeile.dauer_minuten == 0

    def test_bei_einer_zeitleistung_bleibt_die_menge_leer(
        self, projekt, zeitleistung, mitarbeiter
    ):
        """Bei einer Zeitleistung bleibt die Menge NULL, auch wenn eine
        übergeben wird.

        NULL bedeutet keine Menge; eine gespeicherte 1 sähe wie eine Angabe
        aus.
        """
        zeile = services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            menge=Decimal('99'), von=time(8, 0), bis=time(9, 0),
            beschreibung='Arbeit',
        )

        assert zeile.menge is None
        assert zeile.dauer_minuten == 60

    def test_eine_pauschale_hat_immer_die_menge_eins(
        self, projekt, kunde, mitarbeiter
    ):
        """Eine Pauschale hat immer Menge eins."""
        from faktura.models import Katalogposition, Leistungsart
        pauschale = Katalogposition.objects.create(
            bezeichnung='Anfahrtspauschale', einheit='pausch',
            einzelpreis=Decimal('35.00'), art=Leistungsart.PAUSCHALE,
        )

        zeile = services.zeile_erfassen(
            projekt=projekt, leistung=pauschale, benutzer=mitarbeiter,
            beschreibung='Fahrt',
        )

        assert zeile.menge == Decimal('1.000')

    def test_eine_mengenleistung_ohne_angabe_wird_abgelehnt(
        self, projekt, mengenleistung, mitarbeiter
    ):
        """Eine Mengenleistung ohne Menge wird abgelehnt.

        Eine Anfahrt ohne Kilometer lässt sich nicht abrechnen; die
        Abrechnung übergeht solche Zeilen (siehe test_uebernehmen).
        """
        with pytest.raises(ValidationError) as fehler:
            services.zeile_erfassen(
                projekt=projekt, leistung=mengenleistung, benutzer=mitarbeiter,
                beschreibung='Anfahrt, km nachtragen',
            )

        assert 'menge' in fehler.value.message_dict

    def test_menge_null_ist_keine_angabe(
        self, projekt, mengenleistung, mitarbeiter
    ):
        """Menge null gilt als fehlende Angabe."""
        with pytest.raises(ValidationError):
            services.zeile_erfassen(
                projekt=projekt, leistung=mengenleistung, benutzer=mitarbeiter,
                menge=Decimal('0'), beschreibung='Anfahrt',
            )

    def test_eine_pauschale_braucht_weder_zeit_noch_menge(
        self, projekt, pauschalleistung, mitarbeiter
    ):
        """Eine Pauschale braucht weder Zeit noch Menge.

        Deshalb wird nach Art geprüft; eine Regel "eines von beiden muss
        gesetzt sein" lehnte Pauschalen ab.
        """
        zeile = services.zeile_erfassen(
            projekt=projekt, leistung=pauschalleistung, benutzer=mitarbeiter,
            beschreibung='Kleinmaterial',
        )

        assert zeile.menge == Decimal('1.000')


@pytest.mark.django_db
class TestAbgeschlossenesProjekt:
    """Auf ein abgeschlossenes Projekt wird nicht kontiert, weil es
    abgerechnet ist."""

    def test_neu_erfassen_geht_nicht(
        self, abgeschlossenes_projekt, zeitleistung, mitarbeiter
    ):
        with pytest.raises(services.ProjektAbgeschlossen):
            services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
                projekt=abgeschlossenes_projekt, leistung=zeitleistung,
                benutzer=mitarbeiter, beschreibung='Nachzügler',
            )

    def test_eine_alte_zeile_bleibt_aenderbar(
        self, projekt, zeitleistung, mitarbeiter
    ):
        """Zeilen eines später abgeschlossenen Projekts bleiben änderbar.

        Deshalb prüft der Service die Regel und nicht ``clean()``, das sonst
        jede Zeile des Projekts unspeicherbar machte.
        """
        zeile = services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Tippfehler',
        )
        projekt.abgeschlossen = True
        projekt.save()

        geaendert = services.zeile_aendern(
            zeile_id=zeile.pk, beschreibung='So war es richtig',
        )

        assert geaendert.beschreibung == 'So war es richtig'
        assert geaendert.projekt == projekt

    def test_umbuchen_auf_ein_abgeschlossenes_geht_nicht(
        self, projekt, abgeschlossenes_projekt, zeitleistung, mitarbeiter
    ):
        zeile = services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Arbeit',
        )

        with pytest.raises(services.ProjektAbgeschlossen):
            services.zeile_aendern(
                zeile_id=zeile.pk, projekt=abgeschlossenes_projekt,
            )


@pytest.mark.django_db
class TestZeileAendern:

    def test_die_uhrzeiten_lassen_sich_korrigieren(
        self, projekt, zeitleistung, mitarbeiter
    ):
        """Nach Änderung der Uhrzeiten wird die Dauer neu berechnet."""
        zeile = services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            von=time(8, 0), bis=time(9, 0), beschreibung='Arbeit',
        )

        geaendert = services.zeile_aendern(zeile_id=zeile.pk, bis=time(10, 15))

        assert geaendert.dauer_minuten == 135

    def test_auch_beim_aendern_gilt_die_datumsregel(
        self, projekt, zeitleistung, mitarbeiter
    ):
        """Beim Ändern gilt dieselbe Datumsregel wie beim Anlegen."""
        zeile = services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Arbeit',
        )

        with pytest.raises(ValidationError):
            services.zeile_aendern(
                zeile_id=zeile.pk,
                datum=timezone.localdate() + timedelta(days=7),
            )


@pytest.mark.django_db
class TestDieDatenbankHaeltDieselbeRegel:
    """CheckConstraints der Datenbank.

    Geprüft mit ``update()`` unter Umgehung von Modell und Service, damit
    die Constraints selbst getestet werden.
    """

    def test_mehr_als_ein_tag_geht_nicht_durch(
        self, projekt, zeitleistung, mitarbeiter
    ):
        zeile = services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Arbeit',
        )

        with pytest.raises(IntegrityError), transaction.atomic():
            Erfassungszeile.objects.filter(pk=zeile.pk).update(dauer_minuten=1441)

    def test_null_ist_erlaubt(self, projekt, mengenleistung, mitarbeiter):
        """Gegenprobe: Dauer null ist erlaubt, etwa bei Zeilen ohne
        Uhrzeiten."""
        zeile = services.zeile_erfassen(
            projekt=projekt, leistung=mengenleistung, benutzer=mitarbeiter,
            menge=Decimal('23'), beschreibung='Anfahrt',
        )

        assert zeile.dauer_minuten == 0


@pytest.mark.django_db
class TestZeitsumme:

    def test_summiert_in_minuten(self, projekt, zeitleistung, mitarbeiter):
        for von, bis in [(time(8, 0), time(9, 30)), (time(13, 0), time(13, 45))]:
            services.zeile_erfassen(
                projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
                von=von, bis=bis, beschreibung='Arbeit',
            )

        assert services.zeitsumme(Erfassungszeile.objects.all()) == 90 + 45

    def test_wird_nicht_aufgerundet(self, projekt, zeitleistung, mitarbeiter):
        """Die Zeitsumme ist ungerundet; auf die Viertelstunde gerundet wird
        erst beim Übernehmen in die Rechnung."""
        services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            von=time(8, 0), bis=time(8, 20), beschreibung='Arbeit',
        )

        assert services.zeitsumme(Erfassungszeile.objects.all()) == 20

    def test_mengenzeilen_tragen_nichts_bei(
        self, projekt, mengenleistung, mitarbeiter
    ):
        """Mengenzeilen zählen nicht zur Zeitsumme."""
        services.zeile_erfassen(
            projekt=projekt, leistung=mengenleistung, benutzer=mitarbeiter,
            menge=Decimal('23'), beschreibung='Anfahrt',
        )

        assert services.zeitsumme(Erfassungszeile.objects.all()) == 0


@pytest.mark.django_db
class TestOffeneLeistung:
    """Wert der nicht abgerechneten Leistung, angezeigt auf der Startseite."""

    def test_ohne_zeilen_ist_nichts_offen(self, projekt):
        assert services.offene_leistung_je_projekt() == {}
        assert services.offene_leistung_gesamt() == Decimal('0.00')

    def test_eine_zeitzeile_zaehlt_mit_ihrem_katalogpreis(
        self, projekt, zeitleistung, mitarbeiter
    ):
        """Drei Stunden Montage zu 68,00 EUR."""
        services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            von=time(9, 0), bis=time(12, 0), beschreibung='Montage',
        )

        assert services.offene_leistung_gesamt() == Decimal('204.00')

    def test_gerechnet_wird_wie_bei_der_abrechnung(
        self, projekt, zeitleistung, mitarbeiter
    ):
        """Gerundet wird wie bei der Abrechnung.

        Zwölf Zeilen zu 20 Minuten sind 240 Minuten; je Leistung auf die
        Viertelstunde gerundet vier Stunden, je Zeile gerundet sechs. Der
        Wert muss mit der späteren Rechnung übereinstimmen.
        """
        for stunde in range(12):
            services.zeile_erfassen(
                projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
                von=time(6 + stunde, 0), bis=time(6 + stunde, 20),
                beschreibung='Kurzeinsatz',
            )

        # 4 Stunden zu 68,00, nicht 6 Stunden zu 68,00 (408,00).
        assert services.offene_leistung_gesamt() == Decimal('272.00')

    def test_nicht_abrechenbares_bleibt_draussen(
        self, projekt, zeitleistung, mitarbeiter
    ):
        """Nicht abrechenbare Leistung zählt nicht zum offenen Wert."""
        zeile = services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            von=time(9, 0), bis=time(12, 0), beschreibung='Kulanz',
        )
        Erfassungszeile.objects.filter(pk=zeile.pk).update(abrechenbar=False)

        assert services.offene_leistung_gesamt() == Decimal('0.00')

    def test_zwei_projekte_werden_getrennt_gefuehrt(
        self, projekt, abgeschlossenes_projekt, zeitleistung, mitarbeiter
    ):
        """Zwei Projekte werden getrennt geführt, weil die Startseite je
        Projekt eine Zeile zeigt und abrechnungsvorschau() bei mehreren
        Vorhaben MehrereProjekte wirft."""
        services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            von=time(9, 0), bis=time(10, 0), beschreibung='Montage',
        )
        # Der Service lehnt das abgeschlossene Projekt ab; die Zeile wird
        # deshalb direkt angelegt, wie Altdaten.
        Erfassungszeile.objects.create(
            projekt=abgeschlossenes_projekt, leistung=zeitleistung,
            benutzer=mitarbeiter, von=time(9, 0), bis=time(11, 0),
            dauer_minuten=120,
        )

        offen = services.offene_leistung_je_projekt()

        assert offen[projekt.pk] == Decimal('68.00')
        assert offen[abgeschlossenes_projekt.pk] == Decimal('136.00')
