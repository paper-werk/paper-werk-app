"""Die drei Zustände einer Erfassungszeile.

Nicht abrechenbar, abrechenbar und offen, abgerechnet (wie in clockodo).
Festgeschrieben wird nur bei der Übernahme in eine Rechnung.
"""

from datetime import time

import pytest
from django.core.exceptions import ValidationError

from erfassung import services
from erfassung.models import Erfassungszeile, Zustand


@pytest.fixture
def zeile(projekt, zeitleistung, mitarbeiter):
    return services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
        projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
        beschreibung='Arbeit',
    )


@pytest.mark.django_db
class TestDerZustandWirdAbgeleitet:
    """Der Zustand wird aus zwei Feldern abgeleitet, ohne Statusfeld."""

    def test_neu_erfasst_ist_offen(self, zeile):
        assert zeile.zustand == Zustand.OFFEN

    def test_ohne_abrechenbar_ist_sie_nicht_abrechenbar(self, zeile):
        zeile.abrechenbar = False

        assert zeile.zustand == Zustand.NICHT_ABRECHENBAR

    def test_mit_position_ist_sie_abgerechnet(self, zeile, entwurfsposition):
        zeile.abgerechnet_in = entwurfsposition

        assert zeile.zustand == Zustand.ABGERECHNET

    def test_nicht_abrechenbar_gewinnt(self, zeile, festgeschriebene_position):
        """"Nicht abrechenbar" hat Vorrang, auch wenn ein Beleg verweist.

        Der Fall entsteht im Betrieb nicht; das Ergebnis ist trotzdem
        festgelegt.
        """
        zeile.abrechenbar = False
        zeile.abgerechnet_in = festgeschriebene_position

        assert zeile.zustand == Zustand.NICHT_ABRECHENBAR


@pytest.mark.django_db
class TestDieAbfrageSagtDasselbeWieDieEigenschaft:
    """``zustand`` (Python) und ``im_zustand`` (SQL) stimmen überein.

    Die Regel ist zweimal formuliert; die Tests vergleichen beide über
    denselben Bestand.
    """

    @pytest.fixture
    def bestand(self, projekt, zeitleistung, mitarbeiter,
                entwurfsposition, festgeschriebene_position):
        """Alle vier Kombinationen der beiden Felder."""
        for abrechenbar, beleg in (
            (True, None),
            (False, None),
            (True, entwurfsposition),
            (True, festgeschriebene_position),
            (False, festgeschriebene_position),
        ):
            zeile = services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
                projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
                beschreibung='Arbeit', abrechenbar=abrechenbar,
            )
            if beleg is not None:
                # Direkt gesetzt, weil die Sperre in clean() ein full_clean()
                # hier scheitern ließe.
                Erfassungszeile.objects.filter(pk=zeile.pk).update(
                    abgerechnet_in=beleg)
        return Erfassungszeile.objects.all()

    @pytest.mark.parametrize('zustand', list(Zustand))
    def test_beide_wege_finden_dieselben_zeilen(self, bestand, zustand):
        ueber_sql = set(bestand.im_zustand(zustand).values_list('pk', flat=True))
        ueber_python = {z.pk for z in bestand if z.zustand == zustand}

        assert ueber_sql == ueber_python

    def test_die_drei_zustaende_decken_den_bestand_lueckenlos(self, bestand):
        """Jede Zeile liegt in genau einem der drei Zustände."""
        gefunden = []
        for zustand in Zustand:
            gefunden += list(bestand.im_zustand(zustand).values_list('pk', flat=True))

        assert sorted(gefunden) == sorted(bestand.values_list('pk', flat=True))

    def test_ein_unbekannter_zustand_scheitert_laut(self, bestand):
        """Ein unbekannter Zustand wirft eine Ausnahme, damit ein Filter nicht
        alle Zeilen zeigt."""
        with pytest.raises(ValueError):
            bestand.im_zustand('vielleicht')


@pytest.mark.django_db
class TestJedeRechnungSperrt:
    """Jede Rechnung sperrt ihre Zeilen, auch ein Entwurf.

    Entwürfe gehen zur Prüfung an den Auftraggeber, bei Abschlagsrechnungen
    regelmäßig; was geprüft wird, darf sich nicht ändern. Freigegeben wird
    eine Zeile, indem ihre Position aus der Rechnung entfernt wird.
    """

    def _anhaengen(self, zeile, position):
        Erfassungszeile.objects.filter(pk=zeile.pk).update(
            abgerechnet_in=position)
        return Erfassungszeile.objects.get(pk=zeile.pk)

    def test_schon_im_entwurf_ist_sie_gesperrt(self, zeile, entwurfsposition):
        """Schon im Entwurf ist die Zeile gesperrt."""
        assert self._anhaengen(zeile, entwurfsposition).ist_gesperrt

    def test_festgeschrieben_ist_sie_gesperrt(self, zeile,
                                              festgeschriebene_position):
        assert self._anhaengen(zeile, festgeschriebene_position).ist_gesperrt

    def test_aus_der_rechnung_genommen_ist_sie_wieder_offen(
        self, zeile, entwurfsposition
    ):
        """Nach Entfernen der Position aus der Rechnung ist die Zeile offen.

        Entfernt wird eine einzelne Position; weil der Verweis auf die
        Position zeigt, gibt sie genau ihre Zeilen frei.
        """
        gesperrt = self._anhaengen(zeile, entwurfsposition)
        assert gesperrt.ist_gesperrt

        entwurfsposition.delete()

        wieder_frei = Erfassungszeile.objects.get(pk=zeile.pk)
        assert wieder_frei.abgerechnet_in_id is None
        assert not wieder_frei.ist_gesperrt
        assert wieder_frei.zustand == Zustand.OFFEN
        wieder_frei.full_clean()

    def test_ohne_beleg_ist_nichts_gesperrt(self, zeile):
        assert not zeile.ist_gesperrt

    def test_der_service_weist_die_aenderung_ab(self, zeile,
                                                festgeschriebene_position):
        """Der Service lehnt die Änderung mit 409 ab, weil der Zustand und
        nicht die Eingabe das Problem ist."""
        gesperrt = self._anhaengen(zeile, festgeschriebene_position)

        with pytest.raises(services.ZeileAbgerechnet) as fehler:
            services.zeile_aendern(zeile_id=gesperrt.pk, beschreibung='Anders')

        assert fehler.value.http_status == 409

    def test_auch_im_entwurf_weist_der_service_ab(self, zeile,
                                                  entwurfsposition):
        """Auch im Entwurf lehnt der Service die Änderung ab, wie das Modell.

        Den Weg aus der Sperre prüft
        ``test_aus_der_rechnung_genommen_ist_sie_wieder_offen``.
        """
        gesperrt = self._anhaengen(zeile, entwurfsposition)

        with pytest.raises(services.ZeileAbgerechnet):
            services.zeile_aendern(zeile_id=gesperrt.pk, beschreibung='Anders')

    def test_auch_das_formular_kommt_nicht_daran_vorbei(
        self, zeile, festgeschriebene_position
    ):
        """Auch das Formular lehnt die Änderung ab, weil die Sperre in
        ``clean()`` steht und der Admin nicht über den Service speichert."""
        gesperrt = self._anhaengen(zeile, festgeschriebene_position)
        gesperrt.beschreibung = 'Anders'

        with pytest.raises(ValidationError):
            gesperrt.full_clean()


@pytest.mark.django_db
class TestAbrechenbarIstEineEntscheidung:

    def test_der_normalfall_ist_abrechenbar(self, zeile):
        """Vorgabe ist abrechenbar; nicht abrechenbar ist eine bewusste
        Entscheidung."""
        assert zeile.abrechenbar is True

    def test_der_service_nimmt_die_ausnahme_entgegen(
        self, projekt, zeitleistung, mitarbeiter
    ):
        zeile = services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Gewährleistung', abrechenbar=False,
        )

        assert zeile.zustand == Zustand.NICHT_ABRECHENBAR

    def test_nicht_abrechenbare_zeit_bleibt_in_der_summe(
        self, projekt, zeitleistung, mitarbeiter
    ):
        """Nicht abrechenbare Zeit zählt in der Zeitsumme, weil sie geleistet
        ist und Kosten verursacht."""
        from datetime import time

        services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Gewährleistung', abrechenbar=False,
            von=time(8, 0), bis=time(10, 0),
        )

        assert services.zeitsumme(Erfassungszeile.objects.all()) == 120
