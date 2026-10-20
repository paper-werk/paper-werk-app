"""Relative Zeiträume (``erfassung/zeitraum.py``), ohne Datenbank.

``heute`` ist Parameter der Umrechnung, damit sich Monatsenden,
Jahreswechsel, Schaltjahr und Quartalsgrenzen prüfen lassen.
"""

from datetime import date, timedelta

import pytest

from erfassung.zeitraum import AUSWAHLBAR, Zeitraum, zeitraum_grenzen


def grenzen(schluessel, heute, **rest):
    return zeitraum_grenzen(schluessel, heute, **rest)


class TestDieObereGrenzeIstAusschliesslich:
    """Die obere Grenze ist ausschließlich: ``(1.8., 1.9.)`` ist der August.

    Wie Djangos Datumsfilter (``__gte``/``__lt``). Alle weiteren Tests
    beruhen darauf.
    """

    def test_ein_monat_endet_am_ersten_des_naechsten(self):
        assert grenzen(Zeitraum.DIESER_MONAT, date(2026, 8, 24)) == (
            date(2026, 8, 1), date(2026, 9, 1))

    def test_heute_ist_ein_tag(self):
        assert grenzen(Zeitraum.HEUTE, date(2026, 8, 24)) == (
            date(2026, 8, 24), date(2026, 8, 25))


class TestMonate:

    def test_letzter_monat(self):
        assert grenzen(Zeitraum.LETZTER_MONAT, date(2026, 8, 24)) == (
            date(2026, 7, 1), date(2026, 8, 1))

    def test_letzter_monat_ueber_den_jahreswechsel(self):
        """Letzter Monat über den Jahreswechsel."""
        assert grenzen(Zeitraum.LETZTER_MONAT, date(2026, 1, 15)) == (
            date(2025, 12, 1), date(2026, 1, 1))

    def test_dieser_monat_im_dezember(self):
        assert grenzen(Zeitraum.DIESER_MONAT, date(2026, 12, 31)) == (
            date(2026, 12, 1), date(2027, 1, 1))

    def test_der_letzte_tag_eines_monats_gehoert_noch_dazu(self):
        """Gegenprobe zur ausschließlichen Grenze: Der 28. Februar liegt im
        Februar, der 1. März nicht."""
        von, bis = grenzen(Zeitraum.DIESER_MONAT, date(2026, 2, 10))
        assert von <= date(2026, 2, 28) < bis
        assert not von <= date(2026, 3, 1) < bis

    def test_schaltjahr(self):
        """Der 29. Februar 2028 gehört zum Februar."""
        von, bis = grenzen(Zeitraum.DIESER_MONAT, date(2028, 2, 1))
        assert (von, bis) == (date(2028, 2, 1), date(2028, 3, 1))
        assert von <= date(2028, 2, 29) < bis


class TestQuartale:
    """Quartale, die Djangos Datumsfilter nicht anbietet."""

    @pytest.mark.parametrize('heute, erwartet', [
        (date(2026, 1, 1), (date(2026, 1, 1), date(2026, 4, 1))),
        (date(2026, 3, 31), (date(2026, 1, 1), date(2026, 4, 1))),
        (date(2026, 4, 1), (date(2026, 4, 1), date(2026, 7, 1))),
        (date(2026, 8, 24), (date(2026, 7, 1), date(2026, 10, 1))),
        (date(2026, 12, 31), (date(2026, 10, 1), date(2027, 1, 1))),
    ])
    def test_dieses_quartal(self, heute, erwartet):
        assert grenzen(Zeitraum.DIESES_QUARTAL, heute) == erwartet

    @pytest.mark.parametrize('heute, erwartet', [
        (date(2026, 8, 24), (date(2026, 4, 1), date(2026, 7, 1))),
        (date(2026, 5, 2), (date(2026, 1, 1), date(2026, 4, 1))),
        # Mit replace(month=...) schlüge dieser Fall fehl.
        (date(2026, 2, 14), (date(2025, 10, 1), date(2026, 1, 1))),
    ])
    def test_letztes_quartal(self, heute, erwartet):
        assert grenzen(Zeitraum.LETZTES_QUARTAL, heute) == erwartet

    def test_die_vier_quartale_decken_das_jahr_lueckenlos(self):
        """Über alle 365 Tage liegt jeder Tag in genau einem Quartal, und
        jedes Quartal endet, wo das nächste beginnt."""
        tag = date(2026, 1, 1)
        while tag.year == 2026:
            von, bis = grenzen(Zeitraum.DIESES_QUARTAL, tag)
            assert von <= tag < bis
            # Der Tag vor dem Beginn gehört ins vorige Quartal.
            assert grenzen(Zeitraum.DIESES_QUARTAL, von - timedelta(days=1))[1] == von
            tag += timedelta(days=1)


class TestWochen:
    """Die Woche beginnt am Montag (ISO 8601)."""

    def test_diese_woche_von_montag_bis_montag(self):
        # Der 24.08.2026 ist ein Montag.
        assert grenzen(Zeitraum.DIESE_WOCHE, date(2026, 8, 24)) == (
            date(2026, 8, 24), date(2026, 8, 31))

    def test_am_sonntag_gilt_noch_dieselbe_woche(self):
        """Der Sonntag ist der letzte Tag der Woche; mit ``weekday()`` leicht
        falsch berechnet."""
        assert grenzen(Zeitraum.DIESE_WOCHE, date(2026, 8, 30)) == (
            date(2026, 8, 24), date(2026, 8, 31))

    def test_letzte_woche(self):
        assert grenzen(Zeitraum.LETZTE_WOCHE, date(2026, 8, 26)) == (
            date(2026, 8, 17), date(2026, 8, 24))


class TestJahre:

    def test_dieses_jahr(self):
        assert grenzen(Zeitraum.DIESES_JAHR, date(2026, 8, 24)) == (
            date(2026, 1, 1), date(2027, 1, 1))

    def test_letztes_jahr(self):
        assert grenzen(Zeitraum.LETZTES_JAHR, date(2026, 1, 1)) == (
            date(2025, 1, 1), date(2026, 1, 1))


class TestTagesspannen:

    def test_letzte_sieben_tage_sind_sieben_tage(self):
        """"Letzte 7 Tage" umfasst sieben Tage.

        Abweichend von Djangos Filter, der "today - 7 Tage bis morgen" und
        damit acht Tage liefert (django/contrib/admin/filters.py).
        """
        von, bis = grenzen(Zeitraum.LETZTE_7_TAGE, date(2026, 8, 24))
        assert (von, bis) == (date(2026, 8, 18), date(2026, 8, 25))
        assert (bis - von).days == 7

    def test_letzte_dreissig_tage_sind_dreissig_tage(self):
        von, bis = grenzen(Zeitraum.LETZTE_30_TAGE, date(2026, 8, 24))
        assert (bis - von).days == 30

    def test_heute_gehoert_dazu(self):
        """Gegenprobe: Heute gehört zu "letzte 7 Tage"."""
        heute = date(2026, 8, 24)
        von, bis = grenzen(Zeitraum.LETZTE_7_TAGE, heute)
        assert von <= heute < bis


class TestFesterZeitraum:
    """Fester Zeitraum mit zwei eingegebenen Daten."""

    def test_das_bis_wird_auf_die_ausschliessliche_grenze_umgerechnet(self):
        """Das eingegebene "bis" gilt einschließlich und wird hier auf die
        ausschließliche Grenze umgerechnet, damit Aufrufer es nicht selbst
        tun."""
        assert grenzen(Zeitraum.FEST, date(2026, 8, 24),
                       von=date(2026, 8, 1), bis=date(2026, 8, 31)) == (
            date(2026, 8, 1), date(2026, 9, 1))

    def test_ohne_bis_gibt_es_keine_obere_grenze(self):
        assert grenzen(Zeitraum.FEST, date(2026, 8, 24),
                       von=date(2026, 8, 1), bis=None) == (
            date(2026, 8, 1), None)

    def test_heute_spielt_keine_rolle(self):
        """Ein fester Zeitraum hängt nicht von ``heute`` ab."""
        fest = {'von': date(2026, 1, 1), 'bis': date(2026, 1, 31)}
        assert (grenzen(Zeitraum.FEST, date(2026, 8, 24), **fest)
                == grenzen(Zeitraum.FEST, date(2031, 1, 1), **fest))


class TestAlles:

    def test_keine_grenzen(self):
        assert grenzen(Zeitraum.ALLES, date(2026, 8, 24)) == (None, None)


class TestVollstaendigkeit:

    def test_jeder_schluessel_hat_eine_regel(self):
        """Jeder Schlüssel der Auswahl hat eine Regel in ``_REGELN``.

        ``_REGELN`` ist deshalb ein Dict und keine if-Kette.
        """
        for schluessel in Zeitraum:
            von, bis = grenzen(schluessel, date(2026, 8, 24),
                               von=date(2026, 1, 1), bis=date(2026, 1, 31))
            assert von is None or isinstance(von, date)
            assert bis is None or isinstance(bis, date)

    def test_ein_unbekannter_schluessel_scheitert_laut(self):
        """Ein unbekannter Schlüssel wirft eine Ausnahme.

        Er kann aus einer getippten URL oder einer späteren Version stammen.
        Als "keine Grenze" zeigte ein Bericht mehr als gewählt.
        """
        with pytest.raises(ValueError):
            grenzen('vorletztes_quartal', date(2026, 8, 24))

    def test_die_auswahlliste_laesst_genau_zwei_weg(self):
        assert Zeitraum.ALLES not in AUSWAHLBAR
        assert Zeitraum.FEST not in AUSWAHLBAR
        assert len(AUSWAHLBAR) == len(Zeitraum) - 2

    def test_jede_auswahl_kommt_ohne_zusatzangaben_aus(self):
        """Jede Auswahl der Filterleiste lässt sich allein aus ``heute``
        berechnen, weil die Leiste keine Datumsfelder hat."""
        for schluessel in AUSWAHLBAR:
            grenzen(schluessel, date(2026, 8, 24))

    def test_anfang_liegt_nie_hinter_dem_ende(self):
        """Der Beginn liegt nie nach dem Ende, über alle Regeln und ein Jahr an
        Stichtagen.

        Ein umgekehrter Zeitraum lieferte ohne Fehlermeldung null Zeilen.
        """
        for schluessel in AUSWAHLBAR:
            tag = date(2026, 1, 1)
            while tag.year == 2026:
                von, bis = grenzen(schluessel, tag)
                assert von < bis, f'{schluessel} am {tag}'
                tag += timedelta(days=17)
