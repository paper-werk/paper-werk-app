"""Summen, Steuer und Mengenregel der Belege."""

from decimal import Decimal

import pytest
from django.utils import timezone

from faktura import services
from faktura.models import (
    BelegStatus,
    BelegTyp,
    Projekt,
)

# --------------------------------------------------------------------------


class TestPositionssumme:
    """Berechnung ohne Datenbank."""

    @pytest.mark.parametrize(
        'menge,preis,erwartet',
        [
            ('10', '100.00', '1000.00'),
            ('1.5', '99.99', '149.99'),      # 149.985 -> kaufmännisch auf
            ('3', '0.335', '1.01'),          # 1.005 -> aufgerundet
            ('0.333', '100.00', '33.30'),
        ],
    )
    def test_kaufmaennische_rundung(self, menge, preis, erwartet):
        summe = services.positionssumme(
            menge=Decimal(menge), einzelpreis=Decimal(preis)
        )

        assert summe == Decimal(erwartet)
        assert summe.as_tuple().exponent == -2


@pytest.mark.django_db
class TestBelegsummen:
    def test_gemischte_steuersaetze_werden_getrennt_ausgewiesen(self, kunde):
        """Gemischte Steuersätze werden getrennt ausgewiesen, wie § 14 UStG
        verlangt."""
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Beratung', menge=Decimal('10'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00',
        )
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Fachbuch', menge=Decimal('2'),
            einzelpreis=Decimal('50.00'), steuersatz='7.00',
        )

        summen = services.belegsummen(beleg)

        assert len(summen.anteile) == 2
        voll, ermaessigt = summen.anteile          # absteigend sortiert
        assert (voll.netto, voll.steuer) == (Decimal('1000.00'), Decimal('190.00'))
        assert (ermaessigt.netto, ermaessigt.steuer) == (Decimal('100.00'), Decimal('7.00'))
        assert summen.netto == Decimal('1100.00')
        assert summen.steuer == Decimal('197.00')
        assert summen.brutto == Decimal('1297.00')

    def test_steuer_auf_die_summe_nicht_je_position(self, kunde):
        """Die Steuer wird auf die Summe je Satz gerechnet, nicht je Position.

        Drei Positionen zu je 0,05 EUR netto: je Position 0,0095, dreimal
        gerundet 0,03; auf die Summe (0,15 * 19 % = 0,0285) ebenfalls 0,03.
        Die Regel ist festgelegt, damit Rechnung und Buchhaltung
        übereinstimmen.
        """
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)
        for i in range(3):
            services.position_hinzufuegen(
                beleg=beleg, bezeichnung=f'Kleinteil {i}', menge=Decimal('1'),
                einzelpreis=Decimal('0.05'), steuersatz='19.00',
            )

        summen = services.belegsummen(beleg)

        assert summen.netto == Decimal('0.15')
        assert summen.steuer == Decimal('0.03')

    def test_leerer_beleg(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)

        summen = services.belegsummen(beleg)

        assert summen.brutto == Decimal('0.00')
        assert summen.anteile == []


# --------------------------------------------------------------------------
# Kleinunternehmer, Korrektur, Duplizieren, Umwandeln, Rechnungsarten
# --------------------------------------------------------------------------


@pytest.mark.django_db
class TestKleinunternehmerWeistKeineSteuerAus:
    """§ 19 UStG: Ein Kleinunternehmer weist keine Umsatzsteuer aus.

    Regression: ``facturx.py`` setzte die Kategorie "steuerbefreit" im XML,
    während die Position mit 19 % rechnete.

    Geprüft beim Festschreiben, weil ein Entwurf änderbar ist und ein
    festgeschriebener Beleg nicht mehr.
    """

    def test_positionen_mit_steuer_verhindern_das_festschreiben(self, rechnung, firma):
        firma.kleinunternehmer = True
        firma.save()

        with pytest.raises(services.UnzulaessigerSteuersatz):
            services.beleg_festschreiben(beleg_id=rechnung.pk)

    def test_der_beleg_bleibt_dabei_entwurf(self, rechnung, firma):
        """Nach Ablehnung bleibt der Beleg Entwurf, ohne Nummer."""
        firma.kleinunternehmer = True
        firma.save()

        with pytest.raises(services.UnzulaessigerSteuersatz):
            services.beleg_festschreiben(beleg_id=rechnung.pk)

        rechnung.refresh_from_db()
        assert rechnung.status == BelegStatus.ENTWURF
        assert rechnung.nummer is None

    def test_steuerfrei_gebucht_geht_durch(self, rechnung, firma):
        """Gegenprobe: Mit 0 % schreibt der Kleinunternehmer fest."""
        firma.kleinunternehmer = True
        firma.save()
        rechnung.positionen.update(steuersatz='0.00')

        festgeschrieben = services.beleg_festschreiben(beleg_id=rechnung.pk)

        assert festgeschrieben.status == BelegStatus.FESTGESCHRIEBEN

    def test_ohne_kleinunternehmer_bleibt_steuer_erlaubt(self, rechnung, firma):
        """Gegenprobe: Ohne Kleinunternehmerregelung bleibt Steuer zulässig."""
        assert firma.kleinunternehmer is False

        festgeschrieben = services.beleg_festschreiben(beleg_id=rechnung.pk)

        assert festgeschrieben.status == BelegStatus.FESTGESCHRIEBEN

    def test_ein_kleinunternehmer_kann_weiter_mahnen(
        self, rechnung, firma, ueberfaellig
    ):
        """Ein Kleinunternehmer kann mahnen, weil die Mahnung ihre Positionen
        steuerfrei anlegt (Mahngebühr ist Schadenersatz). Eine Änderung des
        Steuersatzes der Mahngebühr ließe diesen Test fehlschlagen."""
        original = ueberfaellig(rechnung)
        firma.kleinunternehmer = True
        firma.save()

        mahnung = services.mahnung_erstellen(beleg_id=original.pk, stufe=1)
        festgeschrieben = services.beleg_festschreiben(beleg_id=mahnung.pk)

        assert festgeschrieben.status == BelegStatus.FESTGESCHRIEBEN


@pytest.mark.django_db
class TestDieMengenregel:
    """Über alle Rechnungen nicht mehr abrechnen als beauftragt.

    Das Festschreiben lehnt ab, sofern die Überschreitung nicht bestätigt
    ist; der Entwurf bleibt änderbar.

    Was zählt, bestimmt die Rechnungsart: Ein Abschlag verbraucht nichts,
    weil die Schlussrechnung die Leistung erneut aufführt und ihn
    absetzt.
    """

    @pytest.fixture
    def projekt(self, kunde):
        return Projekt.objects.create(
            nummer='2026-042', bezeichnung='Halle Nord', kunde=kunde)

    @pytest.fixture
    def auftragsposition(self, projekt):
        """Auftragsposition über 10 Stunden, festgeschrieben."""
        auftrag = services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.AUFTRAG, betreff='Hauptauftrag')
        position = services.position_hinzufuegen(
            beleg=auftrag, bezeichnung='Planung', menge=Decimal('10'),
            einheit='Std', einzelpreis=Decimal('95.00'),
            steuersatz='19.00')
        services.beleg_festschreiben(beleg_id=auftrag.pk)
        position.refresh_from_db()
        return position

    def _rechnung(self, projekt, auftragsposition, menge, art=None):
        from faktura.models import Rechnungsart

        beleg = services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG,
            rechnungsart=art or Rechnungsart.NORMAL,
            # Ein Abschlag braucht den Zeitraum; für die anderen ist er
            # optional.
            leistungsdatum=timezone.localdate(),
            leistungsdatum_bis=timezone.localdate())
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Planung', menge=Decimal(menge),
            einheit='Std', einzelpreis=Decimal('95.00'),
            steuersatz='19.00', auftragsposition=auftragsposition)
        return beleg

    def test_teilmengen_gehen_bis_zum_kontingent(self, projekt,
                                                 auftragsposition):
        services.beleg_festschreiben(
            beleg_id=self._rechnung(projekt, auftragsposition, '6').pk)
        services.beleg_festschreiben(
            beleg_id=self._rechnung(projekt, auftragsposition, '4').pk)

        auftragsposition.refresh_from_db()
        assert auftragsposition.abgerechnete_menge == Decimal('10')
        assert auftragsposition.offene_menge == Decimal('0')

    def test_mehr_als_beauftragt_wird_abgewiesen(self, projekt,
                                                 auftragsposition):
        services.beleg_festschreiben(
            beleg_id=self._rechnung(projekt, auftragsposition, '6').pk)
        zuviel = self._rechnung(projekt, auftragsposition, '5')

        with pytest.raises(services.MengeUeberschritten) as fehler:
            services.beleg_festschreiben(beleg_id=zuviel.pk)

        assert fehler.value.http_status == 409
        # Die Meldung nennt die Mengen und damit die Höhe der
        # Überschreitung.
        assert '1 zu viel' in str(fehler.value)

    def test_der_abgewiesene_beleg_bleibt_entwurf(self, projekt,
                                                  auftragsposition):
        """Der abgelehnte Beleg bleibt Entwurf ohne Nummer.

        Die Prüfung steht vor der Vergabe der Nummer; ``django-sequences``
        gäbe sie bei Rollback ebenfalls frei.
        """
        zuviel = self._rechnung(projekt, auftragsposition, '11')

        with pytest.raises(services.MengeUeberschritten):
            services.beleg_festschreiben(beleg_id=zuviel.pk)

        zuviel.refresh_from_db()
        assert zuviel.status == BelegStatus.ENTWURF
        assert zuviel.nummer is None

    def test_ein_abschlag_verbraucht_das_kontingent_nicht(self, projekt,
                                                          auftragsposition):
        """Ein Abschlag verbraucht kein Kontingent.

        Er ist steuerlich eine Anzahlung; die Schlussrechnung führt die
        Leistung erneut auf und setzt ihn ab. Zählte er mit, wäre das
        Kontingent doppelt verbraucht.
        """
        from faktura.models import Rechnungsart

        services.beleg_festschreiben(beleg_id=self._rechnung(
            projekt, auftragsposition, '10', Rechnungsart.ABSCHLAG).pk)

        auftragsposition.refresh_from_db()
        assert auftragsposition.abgerechnete_menge == Decimal('0')
        # Die Schlussrechnung über die volle Menge wird festgeschrieben.
        services.beleg_festschreiben(beleg_id=self._rechnung(
            projekt, auftragsposition, '10', Rechnungsart.SCHLUSS).pk)
        assert auftragsposition.abgerechnete_menge == Decimal('10')

    def test_ein_entwurf_bindet_nichts(self, projekt, auftragsposition):
        """Ein Entwurf verbraucht kein Kontingent, damit ein vergessener
        Entwurf es nicht dauerhaft blockiert."""
        self._rechnung(projekt, auftragsposition, '10')

        auftragsposition.refresh_from_db()
        assert auftragsposition.abgerechnete_menge == Decimal('0')

    def test_eine_stornierte_rechnung_gibt_ihre_menge_frei(
        self, projekt, auftragsposition
    ):
        """Eine stornierte Rechnung gibt ihre Menge frei.

        Die Stornoposition hat einen negativen Preis und eine positive
        Menge; ein Filter über das Vorzeichen zählte sie doppelt. Gefiltert
        wird daher über den Status, und der Auftragsbezug wird beim Kopieren
        nicht übernommen.
        """
        rechnung = self._rechnung(projekt, auftragsposition, '10')
        festgeschrieben = services.beleg_festschreiben(beleg_id=rechnung.pk)
        assert auftragsposition.abgerechnete_menge == Decimal('10')

        services.rechnung_korrigieren(beleg_id=festgeschrieben.pk)

        # Das Original ist STORNIERT; abgerechnete_mengen() zählt nur
        # Festgeschriebenes.
        assert auftragsposition.abgerechnete_menge == Decimal('0')

    def test_ohne_auftragsbezug_prueft_niemand(self, projekt,
                                               auftragsposition):
        """Ohne Auftragsbezug (Regie, Nebenkosten) keine Prüfung."""
        beleg = services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG,
            leistungsdatum=timezone.localdate())
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Regie', menge=Decimal('99'),
            einheit='Std', einzelpreis=Decimal('95.00'),
            steuersatz='19.00')

        services.beleg_festschreiben(beleg_id=beleg.pk)

        assert auftragsposition.abgerechnete_menge == Decimal('0')

    # --- Bestätigung der Überschreitung ---

    def test_mit_bestaetigung_geht_es_ueber_den_auftrag_hinaus(
        self, projekt, auftragsposition
    ):
        """6 + 5 von 10: Mit Bestätigung festgeschrieben und gezählt."""
        services.beleg_festschreiben(
            beleg_id=self._rechnung(projekt, auftragsposition, '6').pk)
        zuviel = self._rechnung(projekt, auftragsposition, '5')

        festgeschrieben = services.beleg_festschreiben(
            beleg_id=zuviel.pk, mengen_bestaetigt=True)

        assert festgeschrieben.status == BelegStatus.FESTGESCHRIEBEN
        assert festgeschrieben.nummer
        assert auftragsposition.abgerechnete_menge == Decimal('11')
        # Nie negativ; die Überschreitung erscheint im Stand, nicht im Rest.
        assert auftragsposition.offene_menge == Decimal('0')

    def test_die_ueberschreitung_steht_im_abrechnungsstand(
        self, projekt, auftragsposition
    ):
        services.beleg_festschreiben(
            beleg_id=self._rechnung(projekt, auftragsposition, '12').pk,
            mengen_bestaetigt=True)

        assert auftragsposition.abrechnungsstand == (
            '12 von 10 Std abgerechnet, 2 mehr als beauftragt')

    def test_im_rahmen_steht_nur_der_stand(self, projekt, auftragsposition):
        services.beleg_festschreiben(
            beleg_id=self._rechnung(projekt, auftragsposition, '4').pk)

        assert auftragsposition.abrechnungsstand == '4 von 10 Std abgerechnet'

    def test_die_ueberschreitungen_mit_zahlen(self, projekt,
                                              auftragsposition):
        """Die Überschreitungen mit bisheriger, aktueller und überschüssiger
        Menge, wie die Versandmaske sie zeigt."""
        services.beleg_festschreiben(
            beleg_id=self._rechnung(projekt, auftragsposition, '6').pk)
        zuviel = self._rechnung(projekt, auftragsposition, '7')

        [ueberschreitung] = services.mengenueberschreitungen(zuviel)

        assert ueberschreitung.auftragsposition == auftragsposition
        assert ueberschreitung.vorher == Decimal('6')
        assert ueberschreitung.hier == Decimal('7')
        assert ueberschreitung.zu_viel == Decimal('3')
        assert '3 zu viel' in str(ueberschreitung)

    def test_zwei_positionen_auf_dieselbe_auftragsposition_zaehlen_zusammen(
        self, projekt, auftragsposition
    ):
        """Zwei Positionen auf dieselbe Auftragsposition zählen zusammen (6 + 5
        = 11), obwohl jede allein im Rahmen läge."""
        beleg = self._rechnung(projekt, auftragsposition, '6')
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Planung, Rest', menge=Decimal('5'),
            einheit='Std', einzelpreis=Decimal('95.00'),
            steuersatz='19.00', auftragsposition=auftragsposition)

        [ueberschreitung] = services.mengenueberschreitungen(beleg)

        assert ueberschreitung.hier == Decimal('11')
        assert ueberschreitung.zu_viel == Decimal('1')

    def test_im_rahmen_gibt_es_nichts_zu_melden(self, projekt,
                                                auftragsposition):
        beleg = self._rechnung(projekt, auftragsposition, '10')

        assert services.mengenueberschreitungen(beleg) == []

    def test_ein_abschlag_ueberschreitet_nichts(self, projekt,
                                                auftragsposition):
        from faktura.models import Rechnungsart

        beleg = self._rechnung(projekt, auftragsposition, '50',
                               Rechnungsart.ABSCHLAG)

        assert services.mengenueberschreitungen(beleg) == []

    def test_die_absage_sagt_wie_es_weitergeht(self, projekt,
                                               auftragsposition):
        zuviel = self._rechnung(projekt, auftragsposition, '11')

        with pytest.raises(services.MengeUeberschritten) as fehler:
            services.beleg_festschreiben(beleg_id=zuviel.pk)

        assert 'bestätigt' in str(fehler.value)

    def test_versenden_reicht_die_bestaetigung_durch(
        self, projekt, auftragsposition
    ):
        """``beleg_versenden`` übergibt die Bestätigung an das Festschreiben."""
        zuviel = self._rechnung(projekt, auftragsposition, '11')

        with pytest.raises(services.MengeUeberschritten):
            services.beleg_versenden(beleg_id=zuviel.pk, an='kunde@example.org')
        zuviel.refresh_from_db()
        assert zuviel.status == BelegStatus.ENTWURF

        versendet = services.beleg_versenden(
            beleg_id=zuviel.pk, an='kunde@example.org',
            mengen_bestaetigt=True)
        assert versendet.status == BelegStatus.FESTGESCHRIEBEN
        assert versendet.versendet_an == 'kunde@example.org'
