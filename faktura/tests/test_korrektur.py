"""Rechnungskorrektur und Belegkette."""

from decimal import Decimal

import pytest

from faktura import services
from faktura.models import (
    BelegStatus,
    BelegTyp,
)


@pytest.mark.django_db
class TestRechnungKorrigieren:
    def test_erzeugt_storno_und_neuen_entwurf(self, rechnung):
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)

        storno, entwurf = services.rechnung_korrigieren(beleg_id=original.pk)

        assert storno.typ == BelegTyp.STORNO
        assert storno.status == BelegStatus.FESTGESCHRIEBEN
        assert storno.nummer is not None
        assert entwurf.status == BelegStatus.ENTWURF
        assert entwurf.nummer is None

    def test_original_wird_als_storniert_markiert(self, rechnung):
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)

        services.rechnung_korrigieren(beleg_id=original.pk)

        original.refresh_from_db()
        assert original.status == BelegStatus.STORNIERT

    def test_storno_hebt_den_betrag_auf(self, rechnung):
        """Original plus Storno ergibt 0."""
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)
        summe_original = services.belegsummen(original).brutto

        storno, _ = services.rechnung_korrigieren(beleg_id=original.pk)

        assert services.belegsummen(storno).brutto == -summe_original
        assert summe_original + services.belegsummen(storno).brutto == Decimal('0.00')

    def test_storno_bekommt_eigene_nummer_aus_dem_rechnungskreis(self, rechnung):
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)

        storno, _ = services.rechnung_korrigieren(beleg_id=original.pk)

        assert storno.nummer.startswith('RE-')
        assert storno.nummer != original.nummer

    def test_neuer_entwurf_hat_dieselben_positionen(self, rechnung):
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)

        _, entwurf = services.rechnung_korrigieren(beleg_id=original.pk)

        assert entwurf.positionen.count() == original.positionen.count()
        assert services.belegsummen(entwurf).brutto == services.belegsummen(original).brutto

    def test_entwurf_kann_nicht_storniert_werden(self, rechnung):
        with pytest.raises(services.FalscherStatus):
            services.rechnung_korrigieren(beleg_id=rechnung.pk)

    def test_kette_bleibt_nachvollziehbar(self, rechnung):
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)

        storno, entwurf = services.rechnung_korrigieren(beleg_id=original.pk)

        assert storno.vorgaenger_id == original.pk
        assert entwurf.vorgaenger_id == original.pk


@pytest.mark.django_db
class TestBelegkette:
    def test_angebot_wird_zur_rechnung(self, kunde):
        angebot = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        services.position_hinzufuegen(
            beleg=angebot, bezeichnung='Leistung', menge=Decimal('2'),
            einzelpreis=Decimal('500.00'), steuersatz='19.00',
        )
        services.beleg_festschreiben(beleg_id=angebot.pk)

        rechnung = services.beleg_umwandeln(
            beleg_id=angebot.pk, neuer_typ=BelegTyp.RECHNUNG
        )

        assert rechnung.typ == BelegTyp.RECHNUNG
        assert rechnung.status == BelegStatus.ENTWURF
        assert rechnung.vorgaenger_id == angebot.pk
        assert services.belegsummen(rechnung).brutto == services.belegsummen(angebot).brutto


@pytest.mark.django_db
class TestRechnungskorrektur:
    """Rechnungskorrektur als nachträglicher Nachlass.

    Das Storno hebt die Rechnung vollständig auf; die Korrektur lässt sie
    bestehen und mindert das Entgelt (§ 17 UStG).
    """

    def test_original_bleibt_bestehen(self, rechnung):
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)

        services.rechnungskorrektur_erstellen(
            beleg_id=original.pk, betrag_netto=Decimal('100.00'), grund='Kulanz'
        )

        original.refresh_from_db()
        # Anders als beim Storno nicht storniert.
        assert original.status == BelegStatus.FESTGESCHRIEBEN

    def test_betrag_wird_negativ_gefuehrt(self, rechnung):
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)

        korrektur = services.rechnungskorrektur_erstellen(
            beleg_id=original.pk, betrag_netto=Decimal('100.00'), grund='Kulanz'
        )

        summen = services.belegsummen(korrektur)
        assert summen.netto == Decimal('-100.00')
        assert summen.brutto == Decimal('-119.00')

    def test_negativer_eingabebetrag_wird_abgelehnt(self, rechnung):
        """Ein negativer Betrag wird abgelehnt, weil das Vorzeichen sich sonst
        aufhöbe und die Forderung stiege."""
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)

        with pytest.raises(services.UngueltigerBetrag):
            services.rechnungskorrektur_erstellen(
                beleg_id=original.pk, betrag_netto=Decimal('-100.00'), grund='Kulanz'
            )

    def test_bezug_zur_rechnung_bleibt_erhalten(self, rechnung):
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)

        korrektur = services.rechnungskorrektur_erstellen(
            beleg_id=original.pk, betrag_netto=Decimal('50.00'), grund='Reklamation'
        )

        assert korrektur.vorgaenger_id == original.pk

    def test_nummer_kommt_aus_dem_rechnungskreis(self, rechnung):
        """Die Korrektur erhält eine Nummer aus dem Nummernkreis der Rechnung,
        weil sie steuerlich eine Rechnung ist."""
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)
        korrektur = services.rechnungskorrektur_erstellen(
            beleg_id=original.pk, betrag_netto=Decimal('50.00'), grund='Reklamation'
        )

        festgeschrieben = services.beleg_festschreiben(beleg_id=korrektur.pk)

        assert festgeschrieben.nummer.startswith('RE-')


@pytest.mark.django_db
class TestKorrekturNurZuEinerRechnung:
    """Eine Rechnungskorrektur nur zu einer Rechnung.

    Weil Rechnung, Storno und Korrektur einen Nummernkreis teilen und eine
    Korrektur zu einem Storno sonst eine Nummer für einen fachlich
    unzulässigen Vorgang verbrauchte.
    """

    def test_zu_einem_storno_geht_es_nicht(self, rechnung):
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)
        storno, _ = services.rechnung_korrigieren(beleg_id=original.pk)

        with pytest.raises(services.FalscherStatus):
            services.rechnungskorrektur_erstellen(
                beleg_id=storno.pk,
                betrag_netto=Decimal('50.00'),
                grund='Versehen',
            )

    def test_zu_einer_rechnung_geht_es(self, rechnung):
        """Gegenprobe."""
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)

        korrektur = services.rechnungskorrektur_erstellen(
            beleg_id=original.pk,
            betrag_netto=Decimal('50.00'),
            grund='Reklamation',
        )

        assert korrektur.typ == BelegTyp.GUTSCHRIFT

    def test_die_korrektur_erbt_leitweg_und_bestellnummer(self, rechnung):
        """Die Korrektur übernimmt Leitweg-ID und Bestellnummer, weil ein
        öffentlicher Auftraggeber sie darüber der Rechnung zuordnet."""
        rechnung.leitweg_id = '991-12345-67'
        rechnung.bestellnummer = 'BST-4711'
        rechnung.save()
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)

        korrektur = services.rechnungskorrektur_erstellen(
            beleg_id=original.pk,
            betrag_netto=Decimal('50.00'),
            grund='Reklamation',
        )

        assert korrektur.leitweg_id == '991-12345-67'
        assert korrektur.bestellnummer == 'BST-4711'
