"""Übernahme von Eingangsrechnungen aus Paperless.

Das Dokument liegt im Archiv, ein Benutzer hat die erkannten Felder in der
Inbox geprüft, n8n sendet die Werte. Geprüft werden die Regeln des
Service:

1. Eine wiederholte Übernahme ist ein Update.
2. Von Hand geänderte Positionen bleiben unverändert.
3. Ohne Projekt wird die Rechnung mit offenem Rest übernommen; eine falsche
   Projektnummer ist ein Fehler.
4. Ist die Rechnung weiterberechnet, ändert eine Übernahme nichts, damit
   die Kalkulation eines Belegs beim Kunden unverändert bleibt.
"""

from datetime import date
from decimal import Decimal

import pytest

from erfassung import services
from erfassung.models import Eingangsrechnung, Fremdleistung
from faktura import services as faktura_services
from faktura.models import Belegposition, BelegTyp, Kontakt, Projekt

pytestmark = pytest.mark.django_db


@pytest.fixture
def projekt(db):
    kunde = Kontakt.objects.create(nummer='K-1000', name='Stadt Musterstadt')
    return Projekt.objects.create(
        nummer='2026-042', bezeichnung='Turnhalle', kunde=kunde)


def _uebertragen(**abweichend):
    """Übernahme mit den Werten, die n8n sendet."""
    daten = {
        'paperless_id': 463,
        'lieferant': 'Bodenlabor Isartal GmbH',
        'nummer': 'AL-2026-08777',
        'datum': date(2026, 8, 28),
        'betrag_netto': Decimal('1758.00'),
        'projekt': '2026-042',
    }
    return services.eingangsrechnung_aus_archiv(**{**daten, **abweichend})


class TestDerErsteUebertrag:

    def test_die_rechnung_entsteht_mit_kennung_und_position(self, projekt):
        rechnung, neu = _uebertragen()

        assert neu
        assert rechnung.paperless_id == 463
        assert rechnung.betrag_netto == Decimal('1758.00')
        # Eine Position über den vollen Betrag, Rest null.
        assert rechnung.positionen.count() == 1
        assert rechnung.rest == Decimal('0.00')
        assert rechnung.positionen.first().projekt == projekt

    def test_kein_pdf_aber_ein_weg_ins_archiv(self, projekt, settings):
        """Das PDF wird nicht gespeichert; die Rechnung verweist auf das
        Dokument in Paperless."""
        settings.PAPERLESS_ANSICHT_URL = 'http://archiv.example'

        rechnung, _ = _uebertragen()

        assert rechnung.kommt_aus_dem_archiv
        assert rechnung.archiv_adresse == (
            'http://archiv.example/documents/463/details')

    def test_ein_unbekannter_lieferant_wird_angelegt_und_gekennzeichnet(
            self, projekt):
        """Ein unbekannter Lieferant wird angelegt und gekennzeichnet, damit
        Dubletten wie "ISARTAL" und "Isartal GmbH" auffallen."""
        rechnung, _ = _uebertragen()

        assert rechnung.lieferant.name == 'Bodenlabor Isartal GmbH'
        assert 'Automatisch aus dem Archiv' in rechnung.lieferant.notiz

    def test_ein_bekannter_lieferant_wird_wiederverwendet(self, projekt):
        """Ein bekannter Lieferant wird auch bei anderer Groß- und
        Kleinschreibung gefunden."""
        vorhanden = Kontakt.objects.create(
            ist_kunde=False, ist_lieferant=True, name='Bodenlabor Isartal GmbH')

        rechnung, _ = _uebertragen(lieferant='bodenlabor isartal gmbh')

        assert rechnung.lieferant == vorhanden
        assert Kontakt.objects.filter(ist_lieferant=True).count() == 1

    def test_ohne_lieferant_geht_gar_nichts(self, projekt):
        with pytest.raises(services.LieferantFehlt):
            _uebertragen(lieferant='')


class TestDerZweiteUebertrag:
    """Eine wiederholte Übernahme ist ein Update."""

    def test_dieselbe_rechnung_statt_einer_zweiten(self, projekt):
        erste, _ = _uebertragen()

        zweite, neu = _uebertragen(betrag_netto=Decimal('1800.00'))

        assert not neu
        assert zweite.pk == erste.pk
        assert Eingangsrechnung.objects.count() == 1

    def test_der_kopf_wird_aktualisiert(self, projekt):
        """Ein in Paperless korrigierter Betrag wird übernommen."""
        _uebertragen()

        rechnung, _ = _uebertragen(betrag_netto=Decimal('1800.00'),
                                   nummer='AL-2026-08777-A')

        assert rechnung.betrag_netto == Decimal('1800.00')
        assert rechnung.nummer == 'AL-2026-08777-A'

    def test_die_eine_position_zieht_mit(self, projekt):
        """Die von der Übernahme erzeugte Position folgt dem neuen Betrag."""
        _uebertragen()

        rechnung, _ = _uebertragen(betrag_netto=Decimal('1800.00'))

        assert rechnung.positionen.first().einkaufspreis == Decimal('1800.00')
        assert rechnung.rest == Decimal('0.00')

    def test_eine_aufgeteilte_rechnung_bleibt_unberuehrt(self, projekt):
        """Eine von Hand auf mehrere Vorhaben verteilte Rechnung bleibt
        unverändert."""
        rechnung, _ = _uebertragen()
        rechnung.positionen.all().delete()
        for anteil in (Decimal('1000.00'), Decimal('758.00')):
            Fremdleistung.objects.create(
                rechnung=rechnung, projekt=projekt, bezeichnung='Teil',
                menge=Decimal('1'), einkaufspreis=anteil)

        wieder, _ = _uebertragen(betrag_netto=Decimal('1800.00'))

        assert wieder.positionen.count() == 2
        assert sorted(p.einkaufspreis for p in wieder.positionen.all()) == [
            Decimal('758.00'), Decimal('1000.00')]

    def test_eine_umkontierte_position_bleibt_unberuehrt(self, projekt):
        """Eine umkontierte Position bleibt unverändert."""
        rechnung, _ = _uebertragen()
        anderes = Projekt.objects.create(
            nummer='2026-099', bezeichnung='Anderswo', kunde=projekt.kunde)
        position = rechnung.positionen.first()
        position.projekt = anderes
        position.save()

        wieder, _ = _uebertragen(betrag_netto=Decimal('1800.00'))

        assert wieder.positionen.first().projekt == anderes
        assert wieder.positionen.first().einkaufspreis == Decimal('1758.00')


class TestDasProjekt:

    def test_ohne_projekt_kommt_sie_trotzdem_an(self, projekt):
        """Ohne Projekt wird die Rechnung mit offenem Rest übernommen und
        erscheint in der Arbeitsliste."""
        rechnung, neu = _uebertragen(projekt='')

        assert neu
        assert rechnung.positionen.count() == 0
        assert rechnung.rest == Decimal('1758.00')

    def test_eine_unbekannte_nummer_ist_ein_fehler(self, projekt):
        """Eine unbekannte Projektnummer ist ein Fehler."""
        with pytest.raises(services.ProjektUnbekannt):
            _uebertragen(projekt='2099-999')

        assert not Eingangsrechnung.objects.exists()


class TestDieSperre:
    """Weiterberechnete Rechnungen ändert die Übernahme nicht."""

    def _weiterberechnen(self, rechnung, projekt):
        beleg = faktura_services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG)
        position = Belegposition.objects.create(
            beleg=beleg, position=10, bezeichnung='Labor',
            menge=Decimal('1'), einzelpreis=Decimal('1758.00'))
        fremd = rechnung.positionen.first()
        fremd.abgerechnet_in = position
        fremd.save()
        return beleg

    def test_ein_zweiter_uebertrag_wird_abgewiesen(self, projekt):
        rechnung, _ = _uebertragen()
        self._weiterberechnen(rechnung, projekt)

        with pytest.raises(services.UebertragGesperrt) as fehler:
            _uebertragen(betrag_netto=Decimal('9999.00'))

        # Die Meldung nennt den sperrenden Beleg.
        assert 'weiterberechnet' in str(fehler.value)

    def test_und_nichts_hat_sich_geaendert(self, projekt):
        """Nichts ist geändert, weil vor dem Speichern geprüft wird."""
        rechnung, _ = _uebertragen()
        self._weiterberechnen(rechnung, projekt)

        with pytest.raises(services.UebertragGesperrt):
            _uebertragen(betrag_netto=Decimal('9999.00'))

        rechnung.refresh_from_db()
        assert rechnung.betrag_netto == Decimal('1758.00')

    def test_schon_der_entwurf_sperrt(self, projekt):
        """Schon ein Entwurf sperrt, wie bei der Erfassungszeile."""
        rechnung, _ = _uebertragen()
        beleg = self._weiterberechnen(rechnung, projekt)
        assert beleg.ist_entwurf

        with pytest.raises(services.UebertragGesperrt):
            _uebertragen(betrag_netto=Decimal('9999.00'))


class TestDieSchnittstelle:
    """Endpunkt der Archiv-Anbindung; die Regeln prüfen die Tests oben."""

    def _daten(self, **abweichend):
        return {'paperless_id': 463, 'lieferant': 'Bodenlabor Isartal GmbH',
                'nummer': 'AL-2026-08777', 'datum': '2026-08-28',
                'betrag_netto': '1758.00', 'projekt': '2026-042',
                **abweichend}

    def test_der_erste_uebertrag_gibt_201(self, dienst, projekt):
        antwort = dienst.post('/api/v1/eingangsrechnungen/', self._daten(),
                              format='json')

        assert antwort.status_code == 201
        assert antwort.json()['paperless_id'] == 463
        assert antwort.json()['projekte'] == ['2026-042']

    def test_der_zweite_gibt_200_und_ist_kein_fehler(self, dienst, projekt):
        """Eine wiederholte Übernahme antwortet mit 200."""
        dienst.post('/api/v1/eingangsrechnungen/', self._daten(),
                    format='json')

        antwort = dienst.post('/api/v1/eingangsrechnungen/',
                              self._daten(betrag_netto='1800.00'),
                              format='json')

        assert antwort.status_code == 200
        assert antwort.json()['betrag_netto'] == '1800.00'

    def test_eine_unbekannte_projektnummer_gibt_400(self, dienst, projekt):
        antwort = dienst.post('/api/v1/eingangsrechnungen/',
                              self._daten(projekt='2099-999'), format='json')

        assert antwort.status_code == 400

    def test_ein_workflow_kann_vorher_nachfragen(self, dienst, projekt):
        """Mit ``?paperless_id=`` prüft ein Workflow, ob ein Dokument
        übernommen ist."""
        dienst.post('/api/v1/eingangsrechnungen/', self._daten(),
                    format='json')

        antwort = dienst.get('/api/v1/eingangsrechnungen/?paperless_id=463')

        assert antwort.status_code == 200
        gefunden = antwort.json()
        eintraege = gefunden['results'] if 'results' in gefunden else gefunden
        assert len(eintraege) == 1

    def test_ohne_recht_kein_uebertrag(self, db, projekt):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        person = get_user_model().objects.create_user(
            username='fremd', password='geheim12345')
        client = APIClient()
        client.force_authenticate(person)

        antwort = client.post('/api/v1/eingangsrechnungen/', self._daten(),
                              format='json')

        assert antwort.status_code == 403
