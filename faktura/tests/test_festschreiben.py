"""Festschreiben, Unveränderlichkeit und Wiedereröffnen von Belegen."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from faktura import services
from faktura.models import (
    Beleg,
    BelegNichtAenderbar,
    Belegposition,
    BelegStatus,
    BelegTyp,
)


@pytest.mark.django_db
class TestFestschreiben:
    def test_entwurf_hat_keine_nummer(self, rechnung):
        assert rechnung.nummer is None
        assert rechnung.status == BelegStatus.ENTWURF

    def test_nummer_entsteht_erst_beim_festschreiben(self, rechnung):
        festgeschrieben = services.beleg_festschreiben(beleg_id=rechnung.pk)

        assert festgeschrieben.nummer is not None
        assert festgeschrieben.status == BelegStatus.FESTGESCHRIEBEN
        assert festgeschrieben.belegdatum is not None

    def test_verworfener_entwurf_hinterlaesst_keine_luecke(self, kunde):
        """Ein verworfener Entwurf hinterlässt keine Lücke, weil die Nummer
        erst beim Festschreiben vergeben wird."""
        entwurf1 = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        services.position_hinzufuegen(
            beleg=entwurf1, bezeichnung='A', menge=Decimal('1'),
            einzelpreis=Decimal('10.00'), steuersatz='19.00',
        )
        erste = services.beleg_festschreiben(beleg_id=entwurf1.pk)

        # Entwurf anlegen und verwerfen.
        entwurf2 = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        entwurf2.delete()

        entwurf3 = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        services.position_hinzufuegen(
            beleg=entwurf3, bezeichnung='C', menge=Decimal('1'),
            einzelpreis=Decimal('10.00'), steuersatz='19.00',
        )
        zweite = services.beleg_festschreiben(beleg_id=entwurf3.pk)

        laufend_1 = int(erste.nummer.split('-')[-1])
        laufend_2 = int(zweite.nummer.split('-')[-1])
        assert laufend_2 == laufend_1 + 1

    def test_ohne_positionen_nicht_moeglich(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)
        beleg.leistungsdatum = timezone.localdate()
        beleg.save()

        with pytest.raises(services.BelegOhnePositionen):
            services.beleg_festschreiben(beleg_id=beleg.pk)

    def test_rechnung_ohne_leistungsdatum_nicht_moeglich(self, kunde):
        """§ 14 Abs. 4 Nr. 6 UStG: ohne Leistungsdatum kein Festschreiben."""
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='X', menge=Decimal('1'),
            einzelpreis=Decimal('10.00'), steuersatz='19.00',
        )

        with pytest.raises(services.LeistungsdatumFehlt):
            services.beleg_festschreiben(beleg_id=beleg.pk)

    def test_rechnung_ohne_empfaenger_nicht_moeglich(self, rechnung):
        """§ 14 Abs. 4 Nr. 1 UStG: Das freie Empfängerfeld darf im Entwurf leer
        sein, beim Festschreiben nicht."""
        rechnung.empfaenger = ''
        rechnung.save()

        with pytest.raises(services.EmpfaengerFehlt):
            services.beleg_festschreiben(beleg_id=rechnung.pk)

    def test_angebot_braucht_kein_leistungsdatum(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='X', menge=Decimal('1'),
            einzelpreis=Decimal('10.00'), steuersatz='19.00',
        )

        assert services.beleg_festschreiben(beleg_id=beleg.pk).nummer is not None

    def test_zweimal_festschreiben_wird_abgelehnt(self, rechnung):
        services.beleg_festschreiben(beleg_id=rechnung.pk)

        with pytest.raises(services.FalscherStatus):
            services.beleg_festschreiben(beleg_id=rechnung.pk)

    def test_getrennte_nummernkreise(self, kunde):
        """Angebote und Rechnungen zählen unabhängig voneinander."""
        angebot = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        services.position_hinzufuegen(
            beleg=angebot, bezeichnung='X', menge=Decimal('1'),
            einzelpreis=Decimal('10.00'), steuersatz='19.00',
        )
        a = services.beleg_festschreiben(beleg_id=angebot.pk)
        r = services.beleg_festschreiben(beleg_id=self._rechnung(kunde).pk)

        assert a.nummer.startswith('AN-')
        assert r.nummer.startswith('RE-')
        assert a.nummer.endswith('0001')
        assert r.nummer.endswith('0001')

    def _rechnung(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)
        beleg.leistungsdatum = timezone.localdate()
        beleg.save()
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='X', menge=Decimal('1'),
            einzelpreis=Decimal('10.00'), steuersatz='19.00',
        )
        return beleg


@pytest.mark.django_db
class TestFestschreibenProtokolliertDenBenutzer:
    """GoBD: Zum Zeitpunkt der Festschreibung wird der Benutzer gespeichert."""

    @pytest.fixture
    def sachbearbeiterin(self, db):
        return get_user_model().objects.create_user(
            username='meier', password='geheim12345'
        )

    def test_benutzer_wird_am_beleg_vermerkt(self, rechnung, sachbearbeiterin):
        festgeschrieben = services.beleg_festschreiben(
            beleg_id=rechnung.pk, benutzer=sachbearbeiterin
        )

        assert festgeschrieben.festgeschrieben_von == sachbearbeiterin

    def test_ohne_benutzer_bleibt_das_feld_leer(self, rechnung):
        """Ohne Benutzer (Shell, Import, Seed) bleibt das Feld leer."""
        festgeschrieben = services.beleg_festschreiben(beleg_id=rechnung.pk)

        assert festgeschrieben.festgeschrieben_von is None

    def test_storno_traegt_den_stornierenden_benutzer(
        self, rechnung, sachbearbeiterin
    ):
        """Das Storno erhält den stornierenden Benutzer; über die Belegkette
        ist es der Ausgangsrechnung zugeordnet."""
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)

        storno, _ = services.rechnung_korrigieren(
            beleg_id=original.pk, benutzer=sachbearbeiterin
        )

        assert storno.festgeschrieben_von == sachbearbeiterin

    def test_benutzer_mit_festgeschriebenen_belegen_ist_nicht_loeschbar(
        self, rechnung, sachbearbeiterin
    ):
        """on_delete=PROTECT, weil das Löschen des Kontos den Nachweis
        entfernte; Konten werden deaktiviert."""
        from django.db.models import ProtectedError

        services.beleg_festschreiben(
            beleg_id=rechnung.pk, benutzer=sachbearbeiterin
        )

        with pytest.raises(ProtectedError):
            sachbearbeiterin.delete()


@pytest.mark.django_db
class TestUnveraenderlichkeit:
    """Festgeschriebene Belege sind unveränderlich, auch über das Modell."""

    def test_beleg_kann_nicht_geaendert_werden(self, rechnung):
        services.beleg_festschreiben(beleg_id=rechnung.pk)
        rechnung.refresh_from_db()

        rechnung.betreff = 'Nachträglich geändert'
        with pytest.raises(BelegNichtAenderbar):
            rechnung.save()

    def test_beleg_kann_nicht_geloescht_werden(self, rechnung):
        services.beleg_festschreiben(beleg_id=rechnung.pk)
        rechnung.refresh_from_db()

        with pytest.raises(BelegNichtAenderbar):
            rechnung.delete()

    def test_position_kann_nicht_hinzugefuegt_werden(self, rechnung):
        services.beleg_festschreiben(beleg_id=rechnung.pk)
        rechnung.refresh_from_db()

        with pytest.raises(BelegNichtAenderbar):
            services.position_hinzufuegen(
                beleg=rechnung, bezeichnung='Heimlich', menge=Decimal('1'),
                einzelpreis=Decimal('999.00'), steuersatz='19.00',
            )

    def test_vorhandene_position_kann_nicht_geaendert_werden(self, rechnung):
        services.beleg_festschreiben(beleg_id=rechnung.pk)
        position = rechnung.positionen.first()

        position.einzelpreis = Decimal('1.00')
        with pytest.raises(BelegNichtAenderbar):
            position.save()

    def test_entwurf_bleibt_aenderbar(self, rechnung):
        rechnung.betreff = 'Noch änderbar'
        rechnung.save()

        assert Beleg.objects.get(pk=rechnung.pk).betreff == 'Noch änderbar'


@pytest.mark.django_db
class TestWiedereroeffnen:
    """Wiedereröffnen setzt einen festgeschriebenen Beleg in den Entwurf
    zurück.

    Ohne dritten Zustand, damit Listen, Auswertungen und Sperren keine
    Sonderfälle brauchen. Verworfen: ein Zustand "festgeschrieben und
    offen".

    Nur bei Angebot und Auftrag; Rechnungen sind Buchungsbelege.
    """

    def test_angebot_wird_wieder_entwurf(self, angebot):
        services.beleg_festschreiben(beleg_id=angebot.pk)

        beleg = services.beleg_wiedereroeffnen(beleg_id=angebot.pk)

        assert beleg.ist_entwurf
        assert beleg.ist_aenderbar

    def test_die_nummer_bleibt(self, angebot):
        """Die Nummer bleibt, weil sie vergeben und dem Kunden bekannt ist.

        Ein Entwurf mit Nummer ist der einzige Sonderfall und durch einen
        Constraint abgesichert, damit kein Skript ihn erzeugt.
        """
        festgeschrieben = services.beleg_festschreiben(beleg_id=angebot.pk)
        nummer = festgeschrieben.nummer

        beleg = services.beleg_wiedereroeffnen(beleg_id=angebot.pk)

        assert beleg.nummer == nummer

    def test_der_beleg_laesst_sich_danach_aendern(self, angebot):
        services.beleg_festschreiben(beleg_id=angebot.pk)
        beleg = services.beleg_wiedereroeffnen(beleg_id=angebot.pk)

        beleg.betreff = 'Nach dem Telefonat angepasst'
        beleg.save()
        position = beleg.positionen.first()
        position.einzelpreis = Decimal('90.00')
        position.save()

        assert Beleg.objects.get(pk=angebot.pk).betreff.endswith('angepasst')
        assert beleg.positionen.first().einzelpreis == Decimal('90.00')

    def test_die_spur_bleibt_am_beleg(self, angebot, bearbeiterin):
        """``geaendert_am/-von`` bleibt gesetzt, weil die GoBD verlangen, dass
        Änderungen erkennbar bleiben."""
        services.beleg_festschreiben(beleg_id=angebot.pk)

        beleg = services.beleg_wiedereroeffnen(
            beleg_id=angebot.pk, benutzer=bearbeiterin)

        assert beleg.ist_geaendert
        assert beleg.geaendert_am is not None
        assert beleg.geaendert_von == bearbeiterin

    def test_die_spur_ueberlebt_das_erneute_festschreiben(self, angebot):
        services.beleg_festschreiben(beleg_id=angebot.pk)
        services.beleg_wiedereroeffnen(beleg_id=angebot.pk)

        beleg = services.beleg_festschreiben(beleg_id=angebot.pk)

        assert beleg.ist_geaendert

    def test_rechnung_bleibt_zu(self, rechnung):
        services.beleg_festschreiben(beleg_id=rechnung.pk)

        with pytest.raises(services.WiedereroeffnenGesperrt):
            services.beleg_wiedereroeffnen(beleg_id=rechnung.pk)

    def test_lieferschein_bleibt_zu(self, kunde):
        """Der Lieferschein lässt sich nicht wiedereröffnen.

        Weil das Leistungsdatum der Rechnung auf ihm beruht; ein
        Umdatieren verschöbe rückwirkend eine steuerliche Angabe.
        """
        beleg = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.LIEFERSCHEIN, betreff='Lieferung KW 36'
        )
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Material', menge=Decimal('3'),
            einzelpreis=Decimal('0.00'), steuersatz='0.00', einheit='Stk',
        )
        services.beleg_festschreiben(beleg_id=beleg.pk)

        with pytest.raises(services.WiedereroeffnenGesperrt):
            services.beleg_wiedereroeffnen(beleg_id=beleg.pk)

    def test_ein_entwurf_laesst_sich_nicht_oeffnen(self, angebot):
        with pytest.raises(services.FalscherStatus):
            services.beleg_wiedereroeffnen(beleg_id=angebot.pk)

    def test_er_laesst_sich_nicht_loeschen(self, angebot):
        """Ein wiedereröffneter Beleg lässt sich nicht löschen.

        Er ist ein Entwurf mit Nummer; sein Löschen hinterließe eine Lücke
        im Nummernkreis.
        """
        services.beleg_festschreiben(beleg_id=angebot.pk)
        beleg = services.beleg_wiedereroeffnen(beleg_id=angebot.pk)

        with pytest.raises(BelegNichtAenderbar):
            beleg.delete()

    def test_ein_frischer_entwurf_bleibt_loeschbar(self, angebot):
        """Gegenprobe: Ein Entwurf ohne Nummer bleibt löschbar."""
        angebot.delete()

        assert not Beleg.objects.filter(pk=angebot.pk).exists()


@pytest.mark.django_db
class TestErneutFestschreiben:
    """Erneutes Festschreiben über ``beleg_festschreiben`` wie bei jedem
    Entwurf."""

    def test_die_nummer_wird_kein_zweites_mal_gezogen(self, angebot, kunde):
        """Das erneute Festschreiben vergibt keine zweite Nummer.

        Sonst entstünde eine Lücke im Nummernkreis.
        """
        erst = services.beleg_festschreiben(beleg_id=angebot.pk)
        services.beleg_wiedereroeffnen(beleg_id=angebot.pk)
        wieder = services.beleg_festschreiben(beleg_id=angebot.pk)

        assert wieder.nummer == erst.nummer

        weiteres = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.ANGEBOT, betreff='Zweites Angebot'
        )
        services.position_hinzufuegen(
            beleg=weiteres, bezeichnung='Planung', menge=Decimal('1'),
            einzelpreis=Decimal('95.00'), steuersatz='19.00',
        )
        zweiter = services.beleg_festschreiben(beleg_id=weiteres.pk)

        laufend = lambda n: int(n.rsplit('-', 1)[1])  # noqa: E731
        assert laufend(zweiter.nummer) == laufend(erst.nummer) + 1

    def test_ohne_wiedereroeffnen_bleibt_es_beim_fehler(self, rechnung):
        services.beleg_festschreiben(beleg_id=rechnung.pk)

        with pytest.raises(services.FalscherStatus):
            services.beleg_festschreiben(beleg_id=rechnung.pk)


@pytest.mark.django_db
class TestDatenbankregeln:
    """Constraints in der Datenbank für die Regeln des Codes."""

    def test_positionsnummer_ist_je_beleg_eindeutig(self, kunde):
        from django.db import IntegrityError

        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        Belegposition.objects.create(
            beleg=beleg, position=10, bezeichnung='A',
            menge=Decimal('1'), einzelpreis=Decimal('1.00'),
            steuersatz='19.00',
        )

        with pytest.raises(IntegrityError):
            Belegposition.objects.create(
                beleg=beleg, position=10, bezeichnung='B',
                menge=Decimal('1'), einzelpreis=Decimal('1.00'),
                steuersatz='19.00',
            )
