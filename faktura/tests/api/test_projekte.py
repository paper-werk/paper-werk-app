"""Was am Projektendpunkt gelten muss.

Der Prüfmaßstab ist die Gegenrichtung: Ein Dokument fällt ins Archiv, eine
Texterkennung liest es, und die Frage lautet "zu welchem Vorhaben gehört
das?". Der Endpunkt taugt genau so weit, wie er diese Frage **ehrlich**
beantwortet, einschließlich der Fälle, in denen er es nicht sicher weiß.
"""

from datetime import date
from decimal import Decimal

import pytest

from faktura import services
from faktura.models import BelegTyp, Kontakt, Projekt

pytestmark = pytest.mark.django_db


def _beleg(projekt, typ, betrag, *, festschreiben=True):
    """Ein Beleg am Projekt, mit genau einer Position."""
    felder = {}
    if typ in BelegTyp.steuerbelege():
        felder['leistungsdatum'] = date(2026, 8, 1)

    beleg = services.beleg_anlegen(typ=typ, projekt=projekt, **felder)
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Leistung', menge=Decimal('1.000'),
        einheit='Pausch', einzelpreis=Decimal(betrag), steuersatz='19.00',
    )
    if festschreiben:
        return services.beleg_festschreiben(beleg_id=beleg.pk)
    return beleg


# ---------------------------------------------------------------------------
# Nachschlagen
# ---------------------------------------------------------------------------

class TestNachschlagen:

    def test_ohne_leserecht_nichts(self, client_ohne_rechte, projekt):
        assert client_ohne_rechte.get('/api/v1/projekte/').status_code == 403

    def test_die_adresse_geht_ueber_die_fachliche_nummer(self, client, projekt):
        """Anders als bei Belegen: Dort gibt es Entwürfe ohne Nummer. Ein
        Projekt hat immer eine."""
        daten = client.get('/api/v1/projekte/2026-042/').json()

        assert daten['bezeichnung'] == 'Halle Nord'
        assert daten['kunde'] == 'K-1024'
        assert daten['kunde_name'] == 'Bauherr Nord GmbH'

    def test_eine_nummer_mit_punkt_bleibt_erreichbar(self, client, kunde):
        """Djangos Standardmuster für Adressteile schließt den Punkt aus. Eine
        von Hand vergebene Projektnummer darf aber so aussehen."""
        Projekt.objects.create(nummer='2026.042', bezeichnung='Punktprojekt', kunde=kunde)

        assert client.get('/api/v1/projekte/2026.042/').status_code == 200

    def test_abgeschlossene_lassen_sich_aussortieren(self, client, kunde, projekt):
        Projekt.objects.create(
            nummer='2025-001', bezeichnung='Altbau', kunde=kunde, abgeschlossen=True)

        offen = client.get('/api/v1/projekte/', {'abgeschlossen': 'false'}).json()

        assert [p['nummer'] for p in offen['results']] == ['2026-042']


# ---------------------------------------------------------------------------
# Auflösen: der Endpunkt, an dem die Zuordnung gut oder schlecht wird
# ---------------------------------------------------------------------------

class TestAufloesen:

    def _suche(self, client, text, **weitere):
        return client.get('/api/v1/projekte/aufloesen/', {'q': text, **weitere}).json()

    def test_die_genaue_nummer_ist_eindeutig(self, client, projekt):
        ergebnis = self._suche(client, '2026-042')

        assert ergebnis['eindeutig'] is True
        assert ergebnis['treffer'][0]['nummer'] == '2026-042'
        assert ergebnis['treffer'][0]['guete'] == 'exakt'

    def test_eine_laengere_nummer_verwaessert_den_treffer_nicht(
            self, client, kunde, projekt):
        """Der Fall, an dem eine naive Teilstringsuche scheitert: "2026-0421"
        enthält "2026-042". Ohne Vorrang der genauen Übereinstimmung würde aus
        einem sicheren Fund ein mehrdeutiger."""
        Projekt.objects.create(nummer='2026-0421', bezeichnung='Nebenan', kunde=kunde)

        ergebnis = self._suche(client, '2026-042')

        assert ergebnis['eindeutig'] is True
        assert ergebnis['treffer'][0]['nummer'] == '2026-042'

    def test_findet_die_nummer_mitten_im_satz(self, client, projekt):
        """Der Fall, für den es diesen Endpunkt gibt, und der beim ersten
        Durchspielen gegen echte Daten leer ausging.

        Aus einer Texterkennung kommt kein Schlüsselwort, sondern ein Satz.
        ``icontains`` fragt aber, ob die *Nummer* den Suchtext enthält, genau
        die falsche Richtung."""
        ergebnis = self._suche(client, 'Rechnung vom 14.08. Projekt 2026-042 Abschlag')

        assert ergebnis['eindeutig'] is True
        assert ergebnis['treffer'][0]['nummer'] == '2026-042'
        assert ergebnis['treffer'][0]['guete'] == 'exakt'

    def test_im_satz_schlaegt_nur_die_ganze_nummer_an(self, client, kunde, projekt):
        """An Wortgrenzen: "2026-042" darf nicht in "2026-0421" anschlagen,
        sonst wäre jede längere Nummer ein Fehltreffer."""
        Projekt.objects.create(nummer='2026-0421', bezeichnung='Nebenan', kunde=kunde)

        ergebnis = self._suche(client, 'Beleg zu Vorhaben 2026-0421 anbei')

        assert [t['nummer'] for t in ergebnis['treffer']] == ['2026-0421']

    def test_zwei_nummern_im_satz_sind_mehrdeutig(self, client, kunde, projekt):
        """Dann muss ein Mensch entscheiden, nicht der erste Fund gewinnen."""
        Projekt.objects.create(nummer='2026-043', bezeichnung='Halle Süd', kunde=kunde)

        ergebnis = self._suche(client, 'betrifft 2026-042 und 2026-043')

        assert ergebnis['eindeutig'] is False
        assert len(ergebnis['treffer']) == 2

    def test_sehr_kurze_nummern_werden_im_satz_nicht_gesucht(self, client, kunde):
        """Eine Nummer "12" fände sich in jedem Datum und jedem Betrag. Über
        den vollständigen Suchtext bleibt sie auflösbar."""
        Projekt.objects.create(nummer='12', bezeichnung='Kurz', kunde=kunde)

        assert self._suche(client, 'Rechnung vom 12.08.2026')['treffer'] == []
        assert self._suche(client, '12')['eindeutig'] is True

    def test_findet_ueber_die_bezeichnung(self, client, projekt):
        ergebnis = self._suche(client, 'Halle Nord')

        assert ergebnis['eindeutig'] is True
        assert ergebnis['treffer'][0]['fundstelle'] == 'bezeichnung'
        assert ergebnis['treffer'][0]['guete'] == 'teilweise'

    def test_findet_ueber_den_kundennamen(self, client, projekt):
        ergebnis = self._suche(client, 'Bauherr Nord')

        assert ergebnis['treffer'][0]['fundstelle'] == 'kunde'

    def test_mehrdeutigkeit_wird_ausgesprochen(self, client, kunde, projekt):
        """Der wichtigste Test hier. Eine Suche, die bei Mehrdeutigkeit den
        ersten Treffer liefert, erzeugt falsch zugeordnete Fremdrechnungen -
        und die fallen niemandem auf, weil das Ergebnis plausibel aussieht."""
        Projekt.objects.create(nummer='2026-043', bezeichnung='Halle Süd', kunde=kunde)

        ergebnis = self._suche(client, 'Halle')

        assert ergebnis['eindeutig'] is False
        assert len(ergebnis['treffer']) == 2

    def test_kein_treffer_ist_auch_eine_antwort(self, client, projekt):
        ergebnis = self._suche(client, 'Gibtsnicht')

        assert ergebnis['eindeutig'] is False
        assert ergebnis['treffer'] == []

    def test_jedes_projekt_erscheint_nur_einmal(self, client, kunde):
        """Ein Text, der auf Nummer *und* Bezeichnung passt, darf nicht zwei
        Treffer erzeugen, sonst wäre das Ergebnis mehrdeutig, obwohl es
        dasselbe Vorhaben ist."""
        Projekt.objects.create(nummer='HALLE-1', bezeichnung='Halle Nord', kunde=kunde)

        ergebnis = self._suche(client, 'Halle')

        assert len(ergebnis['treffer']) == 1

    def test_abgeschlossene_sind_standardmaessig_dabei(self, client, kunde):
        """Die Schlussrechnung eines Lieferanten trifft oft erst ein, wenn das
        Vorhaben abgehakt ist. Sie gehört trotzdem dorthin."""
        Projekt.objects.create(
            nummer='2025-001', bezeichnung='Altbau', kunde=kunde, abgeschlossen=True)

        ergebnis = self._suche(client, '2025-001')

        assert ergebnis['eindeutig'] is True
        assert ergebnis['treffer'][0]['abgeschlossen'] is True

    def test_auf_wunsch_bleiben_sie_draussen(self, client, kunde):
        Projekt.objects.create(
            nummer='2025-001', bezeichnung='Altbau', kunde=kunde, abgeschlossen=True)

        ergebnis = self._suche(client, '2025-001', nur_offene='true')

        assert ergebnis['treffer'] == []

    def test_ohne_suchtext_eine_klare_ansage(self, client, projekt):
        antwort = client.get('/api/v1/projekte/aufloesen/', {'q': '   '})

        assert antwort.status_code == 400

    def test_grossschreibung_spielt_keine_rolle(self, client, projekt):
        """Was aus einer Texterkennung kommt, ist in der Schreibweise nicht
        verlässlich."""
        assert self._suche(client, 'halle nord')['eindeutig'] is True
        assert self._suche(client, '2026-042')['eindeutig'] is True


# ---------------------------------------------------------------------------
# Die Projektakte
# ---------------------------------------------------------------------------

class TestProjektakte:

    def test_sammelt_die_belege_des_vorhabens(self, client, firma, projekt):
        _beleg(projekt, BelegTyp.ANGEBOT, '1000.00')
        _beleg(projekt, BelegTyp.RECHNUNG, '800.00')

        akte = client.get('/api/v1/projekte/2026-042/akte/').json()

        assert len(akte['belege']) == 2
        assert akte['projekt']['bezeichnung'] == 'Halle Nord'

    def test_trennt_angebotenes_von_berechnetem(self, client, firma, projekt):
        _beleg(projekt, BelegTyp.ANGEBOT, '1000.00')
        _beleg(projekt, BelegTyp.RECHNUNG, '800.00')

        akte = client.get('/api/v1/projekte/2026-042/akte/').json()

        assert akte['angeboten_netto'] == '1000.00'
        assert akte['fakturiert_netto'] == '800.00'
        assert akte['fakturiert_brutto'] == '952.00'

    def test_zaehlt_je_belegart(self, client, firma, projekt):
        _beleg(projekt, BelegTyp.RECHNUNG, '100.00')
        _beleg(projekt, BelegTyp.RECHNUNG, '200.00')

        je_art = client.get('/api/v1/projekte/2026-042/akte/').json()['je_belegart']

        assert je_art['rechnung']['anzahl'] == 2
        assert je_art['rechnung']['netto'] == '300.00'

    def test_eine_mahnung_zaehlt_nicht_als_umsatz(self, client, firma, projekt):
        """Sie fordert eine bereits berechnete Leistung erneut an. Mitgezählt
        stünde jede gemahnte Rechnung doppelt in der Summe."""
        _beleg(projekt, BelegTyp.RECHNUNG, '1000.00')
        _beleg(projekt, BelegTyp.MAHNUNG, '5.00')

        akte = client.get('/api/v1/projekte/2026-042/akte/').json()

        assert akte['fakturiert_netto'] == '1000.00'
        assert 'mahnung' in akte['je_belegart']

    def test_ein_storno_rechnet_sich_heraus(self, client, firma, projekt):
        """Seine Positionen tragen negative Beträge. Die Summe über alle
        Steuerbelege ergibt damit den tatsächlichen Fakturastand."""
        rechnung = _beleg(projekt, BelegTyp.RECHNUNG, '1000.00')
        services.rechnung_korrigieren(beleg_id=rechnung.pk)

        akte = client.get('/api/v1/projekte/2026-042/akte/').json()

        assert akte['fakturiert_netto'] == '0.00'

    def test_entwuerfe_bleiben_draussen(self, client, firma, projekt):
        """Ein Entwurf ist eine Absicht, kein Beleg. Eine Auswertung, die ihn
        mitzählt, ändert sich rückwirkend, ohne dass jemand etwas gebucht hat."""
        _beleg(projekt, BelegTyp.RECHNUNG, '500.00')
        _beleg(projekt, BelegTyp.ANGEBOT, '9999.00', festschreiben=False)

        akte = client.get('/api/v1/projekte/2026-042/akte/').json()

        assert len(akte['belege']) == 1
        assert akte['angeboten_netto'] == '0.00'

    def test_ein_leeres_projekt_liefert_nullen(self, client, projekt):
        akte = client.get('/api/v1/projekte/2026-042/akte/').json()

        assert akte['belege'] == []
        assert akte['fakturiert_netto'] == '0.00'
        assert akte['je_belegart'] == {}

    def test_fremde_belege_bleiben_draussen(self, client, firma, projekt, kunde):
        """Ein Beleg, der nur am selben Kunden hängt, gehört nicht in die Akte
        dieses Vorhabens."""
        _beleg(projekt, BelegTyp.RECHNUNG, '100.00')
        anderer = services.beleg_anlegen(
            typ=BelegTyp.RECHNUNG, kunde=kunde, leistungsdatum=date(2026, 8, 1))
        services.position_hinzufuegen(
            beleg=anderer, bezeichnung='Sonst', menge=Decimal('1.000'),
            einheit='Stk', einzelpreis=Decimal('999.00'), steuersatz='19.00')
        services.beleg_festschreiben(beleg_id=anderer.pk)

        akte = client.get('/api/v1/projekte/2026-042/akte/').json()

        assert akte['fakturiert_netto'] == '100.00'


# ---------------------------------------------------------------------------
# Kunden
# ---------------------------------------------------------------------------

class TestKunden:

    def test_ohne_leserecht_nichts(self, client_ohne_rechte, kunde):
        assert client_ohne_rechte.get('/api/v1/kunden/').status_code == 403

    def test_ueber_die_kundennummer_erreichbar(self, client, kunde):
        daten = client.get('/api/v1/kunden/K-1024/').json()

        assert daten['name'] == 'Bauherr Nord GmbH'
        assert daten['ort'] == 'Hamburg'

    def test_bringt_die_anschrift_fertig_gesetzt_mit(self, client, kunde):
        """Wer sie in Paperless als Korrespondent anlegt, soll sie nicht aus
        Einzelfeldern zusammenbauen müssen, und dabei anders formatieren als
        der Beleg."""
        anschrift = client.get('/api/v1/kunden/K-1024/').json()['anschrift']

        assert 'Bauherr Nord GmbH' in anschrift
        assert 'Hamburg' in anschrift

    def test_suche_ueber_den_namen(self, client, kunde):
        Kontakt.objects.create(nummer='K-2048', name='Ganz anders GmbH')

        treffer = client.get('/api/v1/kunden/', {'search': 'Bauherr'}).json()

        assert treffer['count'] == 1

    def test_aendern_bleibt_verschlossen(self, client, kunde):
        """Stammdaten pflegt das Büro im Admin. Eine Schnittstelle, über die
        ein Automatisierungslauf Kundenadressen ändern kann, löst kein Problem,
        das jemand hat."""
        antwort = client.patch('/api/v1/kunden/K-1024/', {'name': 'Neu'}, format='json')

        assert antwort.status_code in (403, 405)
