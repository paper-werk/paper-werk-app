"""E-Rechnungen aus dem Archiv.

Ein PDF liegt in Paperless. Enthält es XML, ist keine Texterkennung nötig:
n8n ruft ``erechnung_befund`` auf, schreibt die Felder zurück und
kennzeichnet das Dokument. Setzt ein Benutzer "Paper-Werk senden", sendet
n8n die Datei erneut zur Übernahme
(``eingangsrechnung_aus_archiv_erechnung``).

Beispieldateien und Hilfsfunktionen stammen aus ``test_erechnung.py``.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from erfassung import erechnung
from erfassung.models import Eingangsrechnung, Fremdleistung
from erfassung.services import (
    ProjektUnbekannt,
    RechnungBereitsErfasst,
    eingangsrechnung_aus_archiv_erechnung,
    eingangsrechnung_aus_xml,
    erechnung_befund,
)
from erfassung.tests.test_erechnung import (
    cii,
    leeres_pdf,
    pdf_mit_anhang,
    pdf_mit_xml,
    projektreferenz,
)

# ══════════════════════════════════════════════════════════════════════════
# Vorprüfung
# ══════════════════════════════════════════════════════════════════════════


class TestErkennen:
    """``enthaelt_erechnung`` prüft, ohne zu lesen."""

    def test_ein_zugferd_pdf(self):
        assert erechnung.enthaelt_erechnung(pdf_mit_xml())

    def test_ein_gewoehnliches_pdf(self):
        assert not erechnung.enthaelt_erechnung(leeres_pdf())

    def test_nacktes_xml(self):
        assert erechnung.enthaelt_erechnung(cii())

    def test_kaputte_pdf_daten_sind_keine(self):
        assert not erechnung.enthaelt_erechnung(b'%PDF-1.7 kaputt')

    def test_leer(self):
        assert not erechnung.enthaelt_erechnung(b'')


class TestBefund:
    def test_ein_gewoehnliches_pdf_ist_kein_fehler(self, db):
        """Ein PDF ohne XML ist kein Fehler; es folgt die Texterkennung."""
        befund = erechnung_befund(leeres_pdf())

        assert befund.erechnung is False
        assert befund.lesbar is False
        assert befund.felder == {}

    def test_die_felder_tragen_die_namen_aus_paperless(self, db):
        befund = erechnung_befund(pdf_mit_xml())

        assert befund.erechnung and befund.lesbar
        assert befund.lieferant == 'Bodenlabor Isartal GmbH'
        assert befund.felder == {
            'Rechnungsnummer': 'BLI-2026-4711',
            'Rechnungsdatum': '2026-08-12',
            'Nettobetrag': '672.50',
            'Gesamtbetrag': '800.28',
            'Fällig am': '2026-09-11',
        }

    def test_die_projektnummer_nur_wenn_sie_passt(self, db, projekt):
        befund = erechnung_befund(pdf_mit_xml(
            cii(projekt=projektreferenz('BV Halle Nord, 2026-042'))))

        assert befund.felder['Projektnummer'] == '2026-042'
        assert befund.projektreferenz == 'BV Halle Nord, 2026-042'

    def test_eine_unpassende_referenz_fuellt_das_feld_nicht(self, db, projekt):
        """Eine nicht eindeutige Referenz füllt das Feld nicht, weil die
        Nummer bei der Übernahme abgelehnt würde."""
        befund = erechnung_befund(pdf_mit_xml(
            cii(projekt=projektreferenz('2099-999'))))

        assert 'Projektnummer' not in befund.felder
        assert befund.projektreferenz == '2099-999'

    def test_eine_gutschrift_ist_eine_aber_nicht_lesbar(self, db):
        befund = erechnung_befund(pdf_mit_xml(cii(typ='381')))

        assert befund.erechnung is True
        assert befund.lesbar is False
        assert 'Gutschrift' in befund.meldung
        assert befund.felder == {}

    def test_ein_fremder_anhang_ist_nicht_lesbar(self, db):
        befund = erechnung_befund(
            pdf_mit_anhang(b'<kein>CII</kein>', 'daten.xml'))

        assert befund.erechnung is True
        assert befund.lesbar is False

    def test_die_pruefung_legt_nichts_an(self, db):
        erechnung_befund(pdf_mit_xml())

        assert not Eingangsrechnung.objects.exists()


# ══════════════════════════════════════════════════════════════════════════
# Übernahme
# ══════════════════════════════════════════════════════════════════════════

class TestUebernahme:
    def test_die_rechnung_entsteht_mit_verweis_und_positionen(
            self, db, projekt):
        rechnung, neu = eingangsrechnung_aus_archiv_erechnung(
            daten=pdf_mit_xml(), paperless_id=463, projekt='2026-042')

        assert neu is True
        assert rechnung.paperless_id == 463
        assert rechnung.betrag_netto == Decimal('672.50')
        assert rechnung.datum == date(2026, 8, 12)
        assert rechnung.positionen.count() == 2, \
            'Die Zeilen des Dokuments, nicht eine Summenzeile'
        assert rechnung.rest == Decimal('0.00')
        assert 'Archivdokument 463' in rechnung.notiz

    def test_ohne_projekt_entscheidet_die_referenz(self, db, projekt):
        rechnung, _ = eingangsrechnung_aus_archiv_erechnung(
            daten=pdf_mit_xml(cii(projekt=projektreferenz('2026-042'))),
            paperless_id=463)

        assert {p.projekt for p in rechnung.positionen.all()} == {projekt}

    def test_ohne_projekt_und_referenz_nur_der_kopf(self, db):
        rechnung, _ = eingangsrechnung_aus_archiv_erechnung(
            daten=pdf_mit_xml(), paperless_id=463)

        assert rechnung.positionen.count() == 0
        assert rechnung.rest == Decimal('672.50')

    def test_die_nummer_aus_paperless_schlaegt_die_referenz(
            self, db, projekt, kunde):
        from faktura.models import Projekt
        anderes = Projekt.objects.create(
            nummer='2026-043', bezeichnung='Halle Süd', kunde=kunde)

        rechnung, _ = eingangsrechnung_aus_archiv_erechnung(
            daten=pdf_mit_xml(cii(projekt=projektreferenz('2026-042'))),
            paperless_id=463, projekt='2026-043')

        assert {p.projekt for p in rechnung.positionen.all()} == {anderes}

    def test_eine_unbekannte_nummer_ist_ein_fehler(self, db, projekt):
        with pytest.raises(ProjektUnbekannt):
            eingangsrechnung_aus_archiv_erechnung(
                daten=pdf_mit_xml(), paperless_id=463, projekt='2099-999')

        assert not Eingangsrechnung.objects.exists()

    def test_ein_pdf_ohne_xml_ist_ein_fehler(self, db):
        with pytest.raises(erechnung.ERechnungFehler):
            eingangsrechnung_aus_archiv_erechnung(
                daten=leeres_pdf(), paperless_id=463)

    def test_ein_zweiter_uebertrag_aendert_nichts(self, db, projekt):
        eingangsrechnung_aus_archiv_erechnung(
            daten=pdf_mit_xml(), paperless_id=463, projekt='2026-042')

        rechnung, neu = eingangsrechnung_aus_archiv_erechnung(
            daten=pdf_mit_xml(), paperless_id=463, projekt='2026-042')

        assert neu is False
        assert Eingangsrechnung.objects.count() == 1
        assert Fremdleistung.objects.count() == 2, \
            'Die Positionen dürfen sich nicht verdoppeln'

    def test_ein_nachgetragenes_projekt_bringt_die_positionen(
            self, db, projekt):
        """Eine in Paperless nachgetragene Projektnummer führt bei erneuter
        Übernahme zu Positionen."""
        eingangsrechnung_aus_archiv_erechnung(
            daten=pdf_mit_xml(), paperless_id=463)

        rechnung, neu = eingangsrechnung_aus_archiv_erechnung(
            daten=pdf_mit_xml(), paperless_id=463, projekt='2026-042')

        assert neu is False
        assert rechnung.positionen.count() == 2
        assert rechnung.rest == Decimal('0.00')

    def test_eine_hochgeladene_bekommt_ihren_verweis(self, db):
        """Eine bereits hochgeladene Rechnung erhält den Verweis ins Archiv,
        ohne zweiten Datensatz."""
        hochgeladen, _ = eingangsrechnung_aus_xml(daten=cii())

        rechnung, neu = eingangsrechnung_aus_archiv_erechnung(
            daten=pdf_mit_xml(), paperless_id=463)

        assert neu is False
        assert rechnung == hochgeladen
        rechnung.refresh_from_db()
        assert rechnung.paperless_id == 463
        assert Eingangsrechnung.objects.count() == 1

    def test_dasselbe_papier_zweimal_im_archiv(self, db):
        eingangsrechnung_aus_archiv_erechnung(
            daten=pdf_mit_xml(), paperless_id=463)

        with pytest.raises(RechnungBereitsErfasst) as fehler:
            eingangsrechnung_aus_archiv_erechnung(
                daten=pdf_mit_xml(), paperless_id=464)

        assert '463' in str(fehler.value)
        assert Eingangsrechnung.objects.count() == 1


# ══════════════════════════════════════════════════════════════════════════
# Schnittstelle; die Regeln prüfen die Tests oben
# ══════════════════════════════════════════════════════════════════════════

def datei(inhalt: bytes, name='rechnung.pdf') -> SimpleUploadedFile:
    return SimpleUploadedFile(name, inhalt, content_type='application/pdf')


class TestSchnittstelle:
    """Endpunkte der Archiv-Anbindung."""

    PRUEFEN = '/api/v1/eingangsrechnungen/erechnung-pruefen/'
    UEBERNEHMEN = '/api/v1/eingangsrechnungen/erechnung/'

    def test_pruefen_mit_e_rechnung(self, dienst):
        antwort = dienst.post(self.PRUEFEN, {'datei': datei(pdf_mit_xml())},
                              format='multipart')

        assert antwort.status_code == 200
        daten = antwort.json()
        assert daten['erechnung'] is True
        assert daten['lesbar'] is True
        assert daten['felder']['Nettobetrag'] == '672.50'

    def test_pruefen_ohne_e_rechnung_ist_auch_200(self, dienst):
        """Ohne E-Rechnung antwortet die Prüfung mit 200, damit der Workflow
        verzweigen kann."""
        antwort = dienst.post(self.PRUEFEN, {'datei': datei(leeres_pdf())},
                              format='multipart')

        assert antwort.status_code == 200
        assert antwort.json()['erechnung'] is False

    def test_uebernehmen_gibt_201_und_dann_200(self, dienst, projekt):
        erste = dienst.post(self.UEBERNEHMEN, {
            'datei': datei(pdf_mit_xml()), 'paperless_id': 463,
            'projekt': '2026-042'}, format='multipart')
        zweite = dienst.post(self.UEBERNEHMEN, {
            'datei': datei(pdf_mit_xml()), 'paperless_id': 463,
            'projekt': '2026-042'}, format='multipart')

        assert erste.status_code == 201
        assert erste.json()['paperless_id'] == 463
        assert erste.json()['projekte'] == ['2026-042']
        assert zweite.status_code == 200

    def test_ohne_e_rechnung_gibt_400(self, dienst):
        antwort = dienst.post(self.UEBERNEHMEN, {
            'datei': datei(leeres_pdf()), 'paperless_id': 463},
            format='multipart')

        assert antwort.status_code == 400
        assert not Eingangsrechnung.objects.exists()

    def test_ohne_recht_weder_pruefen_noch_uebernehmen(self, db):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        person = get_user_model().objects.create_user(
            username='fremd', password='geheim12345')
        client = APIClient()
        client.force_authenticate(person)

        pruefen = client.post(self.PRUEFEN, {'datei': datei(pdf_mit_xml())},
                              format='multipart')
        uebernehmen = client.post(self.UEBERNEHMEN, {
            'datei': datei(pdf_mit_xml()), 'paperless_id': 463},
            format='multipart')

        assert pruefen.status_code == 403
        assert uebernehmen.status_code == 403
