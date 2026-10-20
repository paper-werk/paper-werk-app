"""Interner Kostensatz je Person mit Gültigkeitsbeginn.

Geprüft wird:

1. Alte Stunden werden mit dem damals gültigen Satz bewertet.
2. Ein fehlender Satz ergibt ``None`` und keine Null.
"""

from datetime import date, time
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError

from erfassung import services
from erfassung.models import Kostensatz


@pytest.fixture
def saetze(mitarbeiter):
    """Zwei Sätze derselben Person, vor und nach einer Lohnerhöhung."""
    Kostensatz.objects.create(
        benutzer=mitarbeiter, gueltig_ab=date(2026, 1, 1),
        satz=Decimal('45.00'))
    Kostensatz.objects.create(
        benutzer=mitarbeiter, gueltig_ab=date(2026, 7, 1),
        satz=Decimal('50.00'))
    return mitarbeiter


def _stunden(projekt, leistung, benutzer, tag, von, bis, **rest):
    return services.zeile_erfassen(
        projekt=projekt, leistung=leistung, benutzer=benutzer,
        beschreibung='Arbeit', datum=tag, von=von, bis=bis, **rest)


# ── Gültiger Satz ────────────────────────────────────────────────────────────

class TestDerZeitpunkt:

    def test_der_juengste_satz_vor_dem_tag_gewinnt(self, saetze):
        verlauf = Kostensatz.verlauf()

        assert Kostensatz.satz_am(
            verlauf, saetze.pk, date(2026, 6, 30)) == Decimal('45.00')
        assert Kostensatz.satz_am(
            verlauf, saetze.pk, date(2026, 7, 1)) == Decimal('50.00')
        assert Kostensatz.satz_am(
            verlauf, saetze.pk, date(2026, 12, 31)) == Decimal('50.00')

    def test_vor_dem_ersten_satz_gibt_es_keinen(self, saetze):
        """Vor dem ersten Satz ist das Ergebnis ``None``."""
        verlauf = Kostensatz.verlauf()

        assert Kostensatz.satz_am(verlauf, saetze.pk, date(2025, 12, 31)) is None

    def test_eine_person_ohne_satz_hat_keinen(self, kollege):
        assert Kostensatz.satz_am(Kostensatz.verlauf(), kollege.pk,
                                  date(2026, 8, 1)) is None

    def test_zweimal_derselbe_tag_geht_nicht(self, mitarbeiter):
        Kostensatz.objects.create(
            benutzer=mitarbeiter, gueltig_ab=date(2026, 1, 1),
            satz=Decimal('45.00'))

        with pytest.raises(IntegrityError):
            Kostensatz.objects.create(
                benutzer=mitarbeiter, gueltig_ab=date(2026, 1, 1),
                satz=Decimal('48.00'))

    def test_ein_negativer_satz_wird_abgewiesen(self, mitarbeiter):
        satz = Kostensatz(benutzer=mitarbeiter, gueltig_ab=date(2026, 1, 1),
                          satz=Decimal('-5.00'))

        with pytest.raises(ValidationError) as fehler:
            satz.full_clean()

        assert 'satz' in fehler.value.error_dict


# ── Personalkosten je Projekt ────────────────────────────────────────────────

class TestDiePersonalkosten:

    def test_stunden_mal_satz(self, projekt, zeitleistung, saetze):
        _stunden(projekt, zeitleistung, saetze, date(2026, 8, 3),
                 time(8, 0), time(12, 0))

        kosten = services.personalkosten_je_projekt()

        # Vier Stunden zu 50,00, Satz ab Juli.
        assert kosten.je_projekt[projekt.pk] == Decimal('200.00')
        assert kosten.vollstaendig

    def test_die_lohnrunde_wirkt_nicht_rueckwaerts(
            self, projekt, zeitleistung, saetze):
        """Stunden im Juni behalten den Satz vor der Lohnerhöhung."""
        _stunden(projekt, zeitleistung, saetze, date(2026, 6, 15),
                 time(8, 0), time(12, 0))
        _stunden(projekt, zeitleistung, saetze, date(2026, 8, 3),
                 time(8, 0), time(12, 0))

        kosten = services.personalkosten_je_projekt()

        # 4 × 45,00 + 4 × 50,00
        assert kosten.je_projekt[projekt.pk] == Decimal('380.00')

    def test_gerechnet_wird_mit_der_echten_zeit_nicht_mit_der_gerundeten(
            self, projekt, zeitleistung, saetze):
        """Kosten beruhen auf der ungerundeten Zeit; nur die Abrechnung rundet
        auf die Viertelstunde."""
        _stunden(projekt, zeitleistung, saetze, date(2026, 8, 3),
                 time(8, 0), time(8, 20))

        kosten = services.personalkosten_je_projekt()

        # 20/60 × 50,00 = 16,67, nicht 25,00 (eine halbe Stunde).
        assert kosten.je_projekt[projekt.pk] == Decimal('16.67')

    def test_nicht_abrechenbare_stunden_kosten_trotzdem(
            self, projekt, zeitleistung, saetze):
        """Nicht abrechenbare Stunden zählen als Kosten, damit Nacharbeit das
        Ergebnis senkt."""
        zeile = _stunden(projekt, zeitleistung, saetze, date(2026, 8, 3),
                         time(8, 0), time(12, 0))
        zeile.abrechenbar = False
        zeile.save()

        kosten = services.personalkosten_je_projekt()

        assert kosten.je_projekt[projekt.pk] == Decimal('200.00')

    def test_mengenleistungen_sind_kein_lohn(
            self, projekt, mengenleistung, saetze):
        """Mengenleistungen wie eine Anfahrt über 23 km zählen nicht als
        Lohn."""
        services.zeile_erfassen(
            projekt=projekt, leistung=mengenleistung, benutzer=saetze,
            beschreibung='Anfahrt', datum=date(2026, 8, 3),
            menge=Decimal('23'))

        kosten = services.personalkosten_je_projekt()

        assert projekt.pk not in kosten.je_projekt

    def test_fehlende_saetze_werden_benannt_statt_genullt(
            self, projekt, zeitleistung, kollege):
        _stunden(projekt, zeitleistung, kollege, date(2026, 8, 3),
                 time(8, 0), time(12, 0))

        kosten = services.personalkosten_je_projekt()

        assert not kosten.vollstaendig
        assert kosten.ohne_satz == {kollege.pk}
        assert kosten.minuten_ohne_satz == 240
        assert projekt.pk not in kosten.je_projekt

    def test_abgeschlossene_vorhaben_bleiben_draussen(
            self, projekt, zeitleistung, saetze):
        """Abgeschlossene Vorhaben fehlen im Ergebnis. Die Zeilen entstehen
        vor dem Abschluss, weil der Service danach nichts mehr annimmt."""
        _stunden(projekt, zeitleistung, saetze, date(2026, 8, 3),
                 time(8, 0), time(12, 0))
        projekt.abgeschlossen = True
        projekt.save()

        assert services.personalkosten_je_projekt().je_projekt == {}
        assert projekt.pk in services.personalkosten_je_projekt(
            nur_laufende=False).je_projekt
