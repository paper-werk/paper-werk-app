"""Archivierung ohne Paperless.

Kein Test spricht mit Paperless. Geprüft werden die gesendeten Felder, das
Parsen der Antworten und vor allem, **wann nicht hochgeladen wird**, weil
Paperless dieselbe Datei zweimal als zwei Dokumente annimmt (geprüft) und
nur diese Regeln Duplikate verhindern.
"""

import json
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.utils import timezone

from faktura import archiv, services
from faktura.models import Beleg, BelegTyp, Kontakt, Projekt


@pytest.fixture(autouse=True)
def eigenes_medienverzeichnis(settings, tmp_path):
    """Testdokumente in einem temporären Verzeichnis, nicht in media/."""
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture(autouse=True)
def leerer_zwischenspeicher():
    """Leert den Cache der aufgelösten IDs.

    Der Cache lebt im Prozess über einen Testfall hinaus; ohne Leeren hinge
    ein Test von den IDs eines vorherigen ab, was erst beim Einzellauf
    auffiele.
    """
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def eingerichtet(settings):
    """Settings mit eingeschalteter Archivierung."""
    settings.PAPERLESS_URL = 'http://archiv.invalid'
    settings.PAPERLESS_TOKEN = 'geheim'
    settings.PAPERLESS_ARCHIVIERUNG = True
    settings.PAPERLESS_TIMEOUT = 1
    settings.PAPERLESS_WARTEZEIT = 0
    settings.PAPERLESS_SPEICHERPFAD = 'Buchführung'
    return settings


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-1000', name='Muster GmbH', strasse='Hauptstraße 1',
        plz='10115', ort='Berlin',
    )


@pytest.fixture
def rechnung(kunde):
    beleg = services.beleg_anlegen(
        kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Leistungen Januar'
    )
    beleg.leistungsdatum = timezone.localdate()
    beleg.save()
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Beratung', menge=Decimal('10'),
        einzelpreis=Decimal('100.00'), steuersatz='19.00', einheit='Std',
    )
    return beleg


@pytest.fixture
def festgeschrieben(rechnung):
    """Festgeschriebener Beleg mit Dokument.

    Das PDF wird gesetzt, nicht gerendert, weil für die Archivierung nur
    das Vorhandensein zählt.
    """
    beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)
    beleg.pdf.save('probe.pdf', ContentFile(b'%PDF-Testdokument'), save=False)
    Beleg.objects.filter(pk=beleg.pk).update(pdf=beleg.pdf.name)
    return Beleg.objects.get(pk=beleg.pk)


#: Feste IDs der Custom Fields für die Assertions.
_FELD = {'Rechnungsnummer': 81, 'Projektnummer': 82,
         'Gesamtbetrag': 83, 'Fällig am': 84}


def _nummern():
    """Ersetzt die Auflösung der Namen durch feste IDs.

    Typ 71, Pfad 72, Korrespondent 73, Custom Fields nach ``_FELD``, damit
    die Zuordnung der Werte ohne Mock der HTTP-Ebene prüfbar ist.
    """
    def aufloesen(bereich, name, *, anlegen=False):
        return {'document_types': 71, 'storage_paths': 72,
                'correspondents': 73}.get(bereich) or _FELD.get(name)
    return aufloesen


def _antwort(nutzlast, status=200):
    """Minimaler Mock einer ``requests``-Response."""
    antwort = Mock()
    antwort.json.return_value = nutzlast
    antwort.status_code = status
    antwort.text = str(nutzlast)
    antwort.raise_for_status.return_value = None
    return antwort


class TestIstEingerichtet:
    """``ist_eingerichtet`` prüft Schalter, URL und Token."""

    def test_alles_gesetzt(self, eingerichtet):
        assert archiv.ist_eingerichtet()

    def test_schalter_aus_genuegt(self, eingerichtet):
        eingerichtet.PAPERLESS_ARCHIVIERUNG = False
        assert not archiv.ist_eingerichtet()

    def test_ohne_adresse_nicht(self, eingerichtet):
        """Ohne URL nicht eingerichtet, weil sonst jedes Festschreiben bei
        leerer URL fehlschlüge.
        """
        eingerichtet.PAPERLESS_URL = ''
        assert not archiv.ist_eingerichtet()

    def test_ohne_schluessel_nicht(self, eingerichtet):
        eingerichtet.PAPERLESS_TOKEN = ''
        assert not archiv.ist_eingerichtet()


@pytest.mark.django_db
class TestHochladen:
    """Gesendete Daten des Uploads."""

    def test_alles_geht_in_einem_aufruf_hinaus(self, eingerichtet, festgeschrieben):
        """Titel, Datum, Typ, Pfad, Korrespondent und Custom Fields in einem
        POST.

        Verworfen: Upload und anschließendes PATCH, weil die Dokumentnummer
        zu diesem Zeitpunkt fehlt.
        """
        with patch('faktura.archiv.nummer_fuer', side_effect=_nummern()):
            with patch('faktura.archiv.requests') as netz:
                netz.post.return_value = _antwort('aufgabe-1')
                netz.RequestException = Exception

                aufgabe = archiv.hochladen(festgeschrieben)

        assert aufgabe == 'aufgabe-1'
        assert netz.post.call_count == 1

        felder = netz.post.call_args.kwargs['data']
        assert festgeschrieben.nummer in felder['title']
        # Belegdatum, weil der Speicherpfad nach created_year sortiert und
        # eine Rechnung vom 30.12., hochgeladen am 2.1., ins alte Jahr
        # gehört.
        assert felder['created'] == festgeschrieben.belegdatum.isoformat()
        assert felder['document_type'] == '71'
        assert felder['storage_path'] == '72'
        assert felder['correspondent'] == '73'
        assert netz.post.call_args.kwargs['files']['document'][2] == 'application/pdf'

        zusatz = json.loads(felder['custom_fields'])
        assert zusatz[str(_FELD['Rechnungsnummer'])] == festgeschrieben.nummer
        assert zusatz[str(_FELD['Gesamtbetrag'])] == 'EUR1190.00'
        assert zusatz[str(_FELD['Fällig am'])] == festgeschrieben.faellig_am.isoformat()

    def test_korrespondent_wird_angelegt_wenn_er_fehlt(
        self, eingerichtet, festgeschrieben
    ):
        """Ein fehlender Korrespondent wird angelegt.

        Weil der Kundenstamm in Django wächst; manuell anzulegende
        Korrespondenten führten unbemerkt zu Belegen ohne Korrespondent.
        Dokumenttyp und Speicherpfad richtet das Setup ein.
        """
        with patch('faktura.archiv.requests') as netz:
            netz.get.return_value = _antwort({'results': []})
            netz.post.side_effect = [_antwort({'id': 55}), _antwort('aufgabe-1')]
            netz.RequestException = Exception

            archiv.hochladen(festgeschrieben)

        angelegt = netz.post.call_args_list[0]
        assert angelegt.args[0].endswith('/api/correspondents/')
        assert angelegt.kwargs['json'] == {'name': festgeschrieben.kunde.name}
        assert netz.post.call_args_list[1].kwargs['data']['correspondent'] == '55'

    def test_projektbeleg_findet_seinen_kunden(self, eingerichtet, kunde):
        """Ein Projektbeleg erhält den Kunden des Projekts als Korrespondent.

        Wegen ``kunde_oder_projekt_nicht_beides`` ist ``beleg.kunde`` am
        Projektbeleg leer. Regression: Er wurde ohne Korrespondent und ohne
        Kundennamen im Titel archiviert.
        """
        projekt = Projekt.objects.create(
            nummer='2026-099', bezeichnung='Halle Nord', kunde=kunde)
        beleg = services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG, betreff='Planung')
        beleg.leistungsdatum = timezone.localdate()
        beleg.save()
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Planung', menge=Decimal('4'),
            einzelpreis=Decimal('150.00'), steuersatz='19.00', einheit='Std')
        beleg = services.beleg_festschreiben(beleg_id=beleg.pk)
        beleg.pdf.save('probe.pdf', ContentFile(b'%PDF-Test'), save=False)
        Beleg.objects.filter(pk=beleg.pk).update(pdf=beleg.pdf.name)
        beleg = Beleg.objects.get(pk=beleg.pk)

        with patch('faktura.archiv.nummer_fuer', side_effect=_nummern()):
            with patch('faktura.archiv.requests') as netz:
                netz.post.return_value = _antwort('aufgabe-1')
                netz.RequestException = Exception

                archiv.hochladen(beleg)

        felder = netz.post.call_args.kwargs['data']
        assert felder['correspondent'] == '73'
        assert kunde.name in felder['title']
        zusatz = json.loads(felder['custom_fields'])
        assert zusatz[str(_FELD['Projektnummer'])] == '2026-099'

    def test_lieferschein_bekommt_keinen_betrag(self, eingerichtet, kunde):
        """Der Lieferschein erhält kein Custom Field mit Betrag.

        Admin und PDF zeigen beim Lieferschein keine Preise; ein Betrag am
        Archivdokument machte ihn dort sichtbar.
        """
        beleg = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.LIEFERSCHEIN, betreff='Lieferung')
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Kabel', menge=Decimal('5'),
            einzelpreis=Decimal('12.00'), steuersatz='19.00', einheit='m')
        beleg = services.beleg_festschreiben(beleg_id=beleg.pk)
        beleg.pdf.save('probe.pdf', ContentFile(b'%PDF-Test'), save=False)
        Beleg.objects.filter(pk=beleg.pk).update(pdf=beleg.pdf.name)
        beleg = Beleg.objects.get(pk=beleg.pk)

        with patch('faktura.archiv.nummer_fuer', side_effect=_nummern()):
            with patch('faktura.archiv.requests') as netz:
                netz.post.return_value = _antwort('aufgabe-1')
                netz.RequestException = Exception

                archiv.hochladen(beleg)

        zusatz = json.loads(netz.post.call_args.kwargs['data']['custom_fields'])
        assert str(_FELD['Gesamtbetrag']) not in zusatz
        assert zusatz[str(_FELD['Rechnungsnummer'])] == beleg.nummer

    def test_fehlendes_ziel_verhindert_die_ablage_nicht(
        self, eingerichtet, festgeschrieben
    ):
        """Ein nicht vorhandener Speicherpfad lässt das Feld weg, ohne den
        Upload zu verhindern."""
        with patch('faktura.archiv.nummer_fuer', return_value=None):
            with patch('faktura.archiv.requests') as netz:
                netz.post.return_value = _antwort('aufgabe-2')
                netz.RequestException = Exception

                archiv.hochladen(festgeschrieben)

        felder = netz.post.call_args.kwargs['data']
        assert 'document_type' not in felder
        assert 'storage_path' not in felder
        assert 'custom_fields' not in felder
        # Der Titel bleibt, weil er keine Abfrage braucht und danach im
        # Archiv gesucht wird.
        assert felder['title']

    def test_ohne_pdf_kein_upload(self, eingerichtet, rechnung):
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)

        with pytest.raises(archiv.ArchivFehler, match='kein Dokument'):
            archiv.hochladen(beleg)

    def test_antwort_ohne_aufgabennummer(self, eingerichtet, festgeschrieben):
        """Eine Antwort ohne Task-ID ist ein Fehler.

        Sonst stünde eine leere Task-ID am Beleg, und der nächste Lauf
        hielte ihn für nicht hochgeladen.
        """
        with patch('faktura.archiv.nummer_fuer', return_value=None):
            with patch('faktura.archiv.requests') as netz:
                netz.post.return_value = _antwort({'irgendwas': 'anderes'})
                netz.RequestException = Exception

                with pytest.raises(archiv.ArchivFehler, match='Aufgabennummer'):
                    archiv.hochladen(festgeschrieben)


@pytest.mark.django_db
class TestDokumentAdresse:
    """URL des Archivdokuments für den Browser."""

    def test_ohne_vermerk_kein_verweis(self, eingerichtet, festgeschrieben):
        assert archiv.dokument_adresse(festgeschrieben) == ''

    def test_verweis_auf_das_dokument(self, eingerichtet, festgeschrieben):
        eingerichtet.PAPERLESS_ANSICHT_URL = 'http://archiv.example'
        services.archivierung_vermerken(beleg_id=festgeschrieben.pk, paperless_id=42)
        beleg = Beleg.objects.get(pk=festgeschrieben.pk)

        assert archiv.dokument_adresse(beleg) == (
            'http://archiv.example/documents/42/details')

    def test_ansichtsadresse_schlaegt_die_dienstadresse(
        self, eingerichtet, festgeschrieben
    ):
        """``PAPERLESS_ANSICHT_URL`` hat Vorrang vor ``PAPERLESS_URL``.

        ``PAPERLESS_URL`` ist die URL aus Sicht des Servers
        (``http://paperless:8000``), nur im Compose-Netz auflösbar; ein Link
        darauf funktioniert im Browser nicht.
        """
        eingerichtet.PAPERLESS_URL = 'http://paperless:8000'
        eingerichtet.PAPERLESS_ANSICHT_URL = 'http://paper-werk.example:8005'
        services.archivierung_vermerken(beleg_id=festgeschrieben.pk, paperless_id=7)
        beleg = Beleg.objects.get(pk=festgeschrieben.pk)

        assert archiv.dokument_adresse(beleg).startswith(
            'http://paper-werk.example:8005/')

    def test_ohne_ansichtsadresse_die_dienstadresse(
        self, eingerichtet, festgeschrieben
    ):
        """Ohne Ansichts-URL gilt ``PAPERLESS_URL``, die bei runserver
        identisch ist."""
        eingerichtet.PAPERLESS_URL = 'http://localhost:8005'
        eingerichtet.PAPERLESS_ANSICHT_URL = ''
        services.archivierung_vermerken(beleg_id=festgeschrieben.pk, paperless_id=7)
        beleg = Beleg.objects.get(pk=festgeschrieben.pk)

        assert archiv.dokument_adresse(beleg) == (
            'http://localhost:8005/documents/7/details')


class TestAufgabeAbfragen:
    """Parsen der Antwort von ``/api/tasks/``."""

    def _mit(self, nutzlast):
        with patch('faktura.archiv.requests') as netz:
            netz.get.return_value = _antwort(nutzlast)
            netz.RequestException = Exception
            return archiv.aufgabe_abfragen('aufgabe-1')

    def test_dokumentnummer_aus_result_data(self, eingerichtet):
        zustand, nummer, _ = self._mit({'results': [{
            'status': 'success',
            'result_data': {'document_id': 42},
            'related_document_ids': [42],
            # Das alte Feld bleibt null, obwohl der Task erfolgreich war;
            # danach geprüft, erschiene ein Erfolg als Fehlschlag (an einer
            # laufenden Instanz geprüft).
            'related_document': None,
        }]})

        assert (zustand, nummer) == ('success', 42)

    def test_zweite_quelle_wenn_result_data_fehlt(self, eingerichtet):
        zustand, nummer, _ = self._mit({'results': [{
            'status': 'success', 'related_document_ids': [7],
        }]})

        assert (zustand, nummer) == ('success', 7)

    def test_erfolg_ohne_nummer_gilt_als_fehlschlag(self, eingerichtet):
        """Erfolg ohne Dokumentnummer gilt als Fehlschlag, damit keine
        ``paperless_id`` None gespeichert wird."""
        zustand, nummer, meldung = self._mit({'results': [{'status': 'success'}]})

        assert zustand == 'failure'
        assert nummer is None
        assert 'keine Dokumentnummer' in meldung

    def test_ablehnung_mit_grund(self, eingerichtet):
        zustand, _, meldung = self._mit({'results': [{
            'status': 'failure', 'result': 'Datei unlesbar',
        }]})

        assert zustand == 'failure'
        assert 'Datei unlesbar' in meldung

    def test_noch_in_arbeit(self, eingerichtet):
        zustand, nummer, _ = self._mit({'results': [{'status': 'pending'}]})

        assert (zustand, nummer) == ('pending', None)

    def test_leere_liste_heisst_unbekannt(self, eingerichtet):
        """Eine leere Liste ergibt ``unbekannt``, nicht gescheitert (Regel in
        services)."""
        zustand, _, _ = self._mit({'results': []})

        assert zustand == 'unbekannt'

    def test_alte_fassung_ohne_seitenaufteilung(self, eingerichtet):
        """Ältere Paperless-Versionen antworten ohne Pagination mit einer
        Liste."""
        zustand, nummer, _ = self._mit([{
            'status': 'success', 'result_data': {'document_id': 5},
        }])

        assert (zustand, nummer) == ('success', 5)


@pytest.mark.django_db
class TestBelegArchivieren:
    """Bedingungen für den Upload."""

    def test_ablauf_bis_zum_vermerk(self, eingerichtet, festgeschrieben):
        with patch('faktura.archiv.hochladen', return_value='aufgabe-1') as upload, \
             patch('faktura.archiv.aufgabe_abfragen',
                   return_value=('success', 99, '')):
            beleg = services.beleg_archivieren(beleg_id=festgeschrieben.pk)

        assert upload.call_count == 1
        assert beleg.paperless_id == 99
        assert beleg.archiviert_am is not None
        # Die Task-ID wird geleert, weil sie sonst einen offenen Task
        # anzeigte.
        assert beleg.paperless_task_id == ''

    def test_bereits_archiviert_laedt_nicht_erneut(
        self, eingerichtet, festgeschrieben
    ):
        services.archivierung_vermerken(beleg_id=festgeschrieben.pk, paperless_id=4711)

        with patch('faktura.archiv.hochladen') as upload:
            services.beleg_archivieren(beleg_id=festgeschrieben.pk)

        assert upload.call_count == 0

    def test_offene_aufgabe_laedt_nicht_erneut(self, eingerichtet, festgeschrieben):
        """Mit offener Task-ID wird der Status abgefragt und nicht erneut
        hochgeladen, weil Paperless sonst ein zweites Dokument anlegt
        (geprüft)."""
        Beleg.objects.filter(pk=festgeschrieben.pk).update(paperless_task_id='läuft')

        with patch('faktura.archiv.hochladen') as upload, \
             patch('faktura.archiv.aufgabe_abfragen',
                   return_value=('success', 12, '')) as frage:
            beleg = services.beleg_archivieren(beleg_id=festgeschrieben.pk)

        assert upload.call_count == 0
        assert frage.call_args.args == ('läuft',)
        assert beleg.paperless_id == 12

    def test_unbekannte_aufgabe_laedt_nicht_erneut(
        self, eingerichtet, festgeschrieben
    ):
        """Ein unbekannter Task löst keinen erneuten Upload aus.

        Paperless löscht alte Tasks; das Dokument kann vorhanden sein, und
        ein zweiter Upload legte es doppelt ab.
        """
        Beleg.objects.filter(pk=festgeschrieben.pk).update(paperless_task_id='alt')

        with patch('faktura.archiv.hochladen') as upload, \
             patch('faktura.archiv.aufgabe_abfragen',
                   return_value=('unbekannt', None, 'weg')):
            beleg = services.beleg_archivieren(beleg_id=festgeschrieben.pk)

        assert upload.call_count == 0
        assert beleg.paperless_id is None
        # Die Task-ID bleibt, weil nur sie die manuelle Klärung des Uploads
        # erlaubt.
        assert beleg.paperless_task_id == 'alt'

    def test_ablehnung_gibt_die_aufgabe_frei(self, eingerichtet, festgeschrieben):
        """Nach einem fehlgeschlagenen Task wird die Task-ID freigegeben, weil
        nur dann ein neuer Upload sicher ist."""
        with patch('faktura.archiv.hochladen', return_value='aufgabe-1'), \
             patch('faktura.archiv.aufgabe_abfragen',
                   return_value=('failure', None, 'Datei unlesbar')):
            with pytest.raises(services.ArchivFehler, match='Datei unlesbar'):
                services.beleg_archivieren(beleg_id=festgeschrieben.pk)

        beleg = Beleg.objects.get(pk=festgeschrieben.pk)
        assert beleg.paperless_task_id == ''
        assert beleg.paperless_id is None

    def test_wartezeit_abgelaufen_haelt_die_aufgabe_fest(
        self, eingerichtet, festgeschrieben
    ):
        """Nach Ablauf der Wartezeit bleibt die Task-ID für den nächsten Lauf
        gesetzt, ohne Fehler."""
        with patch('faktura.archiv.hochladen', return_value='aufgabe-1'), \
             patch('faktura.archiv.aufgabe_abfragen',
                   return_value=('started', None, '')):
            beleg = services.beleg_archivieren(beleg_id=festgeschrieben.pk)

        assert beleg.paperless_id is None
        assert beleg.paperless_task_id == 'aufgabe-1'

    def test_ohne_einrichtung_geschieht_nichts(self, settings, festgeschrieben):
        settings.PAPERLESS_ARCHIVIERUNG = False

        with patch('faktura.archiv.hochladen') as upload:
            services.beleg_archivieren(beleg_id=festgeschrieben.pk)

        assert upload.call_count == 0

    def test_entwurf_gehoert_nicht_ins_archiv(self, eingerichtet, rechnung):
        with pytest.raises(services.FalscherStatus, match='Entwurf'):
            services.beleg_archivieren(beleg_id=rechnung.pk)

    def test_ohne_warten_wird_nicht_gefragt(self, eingerichtet, festgeschrieben):
        """Mit ``warten=False`` keine Statusabfrage, für den Lauf über viele
        Belege."""
        with patch('faktura.archiv.hochladen', return_value='aufgabe-1'), \
             patch('faktura.archiv.aufgabe_abfragen') as frage:
            beleg = services.beleg_archivieren(
                beleg_id=festgeschrieben.pk, warten=False)

        assert frage.call_count == 0
        assert beleg.paperless_task_id == 'aufgabe-1'


@pytest.mark.django_db
class TestFestschreibenLoestAus:
    """Archivierung als Folge des Festschreibens."""

    def test_festschreiben_archiviert(
        self, eingerichtet, mit_pdf, rechnung, settings,
        django_capture_on_commit_callbacks
    ):
        """Das Festschreiben archiviert nach dem Commit.

        Mit ``django_capture_on_commit_callbacks``, weil im Test kein Commit
        stattfindet und on_commit-Callbacks sonst nie laufen.

        Die Setting wird im Test gesetzt, damit das Ergebnis nicht von der
        ``.env`` der Entwicklungsumgebung abhängt.
        """
        settings.PAPERLESS_WARTEN_BEIM_FESTSCHREIBEN = False
        with patch('faktura.services.archivierung.beleg_archivieren') as archivieren:
            with django_capture_on_commit_callbacks(execute=True):
                services.beleg_festschreiben(beleg_id=rechnung.pk)

        assert archivieren.call_args.kwargs == {
            'beleg_id': rechnung.pk, 'warten': False}

    def test_das_festschreiben_wartet_nicht_auf_das_archiv(
        self, eingerichtet, mit_pdf, rechnung, settings,
        django_capture_on_commit_callbacks
    ):
        """Das Festschreiben wartet standardmäßig nicht auf das Archiv.

        Regression: Das Festschreiben dauerte Sekunden. Das PDF kostet etwa
        280 ms (gemessen, auch mit PDF/A-3b und XML); die Wartezeit kam aus
        ``_aufgabe_aufloesen``, das mit ``time.sleep(1)`` bis zu
        PAPERLESS_WARTEZEIT Sekunden auf die Dokumentnummer wartete. Der
        on_commit-Callback läuft im Request, nach dem Commit und vor der
        Response.
        """
        settings.PAPERLESS_WARTEN_BEIM_FESTSCHREIBEN = False
        with patch('faktura.services.archivierung.beleg_archivieren') as archivieren:
            with django_capture_on_commit_callbacks(execute=True):
                services.beleg_festschreiben(beleg_id=rechnung.pk)

        assert archivieren.call_args.kwargs['warten'] is False

    def test_wer_warten_will_kann_es_einschalten(
        self, eingerichtet, mit_pdf, rechnung, settings,
        django_capture_on_commit_callbacks
    ):
        """``PAPERLESS_WARTEN_BEIM_FESTSCHREIBEN`` aktiviert das Warten, für
        Installationen ohne regelmäßigen ``belege_archivieren``, bei denen
        sonst die Dokumentnummer fehlt."""
        settings.PAPERLESS_WARTEN_BEIM_FESTSCHREIBEN = True

        with patch('faktura.services.archivierung.beleg_archivieren') as archivieren:
            with django_capture_on_commit_callbacks(execute=True):
                services.beleg_festschreiben(beleg_id=rechnung.pk)

        assert archivieren.call_args.kwargs['warten'] is True

    def test_ein_totes_archiv_verhindert_keine_rechnung(
        self, eingerichtet, mit_pdf, rechnung, django_capture_on_commit_callbacks
    ):
        """Ein nicht erreichbares Archiv verhindert das Festschreiben nicht,
        weil die Archivierung nur eine Kopie ist."""
        with patch('faktura.services.archivierung.beleg_archivieren',
                   side_effect=archiv.ArchivFehler('Archiv antwortet nicht')):
            with django_capture_on_commit_callbacks(execute=True):
                beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)

        assert beleg.nummer
        assert not beleg.ist_entwurf
        assert beleg.paperless_id is None

    def test_ohne_pdf_kein_archivierungsversuch(
        self, eingerichtet, rechnung, django_capture_on_commit_callbacks
    ):
        """Ohne PDF kein Archivierungsversuch.

        Deshalb archivieren die übrigen Tests nicht, weil conftest das
        Rendern abschaltet.
        """
        with patch('faktura.services.archivierung.beleg_archivieren') as archivieren:
            with django_capture_on_commit_callbacks(execute=True):
                services.beleg_festschreiben(beleg_id=rechnung.pk)

        assert archivieren.call_count == 0


class TestDasArchivBeimWiedereroeffnen:
    """Archivdokument beim Wiedereröffnen.

    Das Wiedereröffnen entfernt den Archivverweis; beim nächsten
    Festschreiben wird die neue Fassung als eigenes Dokument archiviert.
    In Paperless liegen dann zwei Dokumente mit demselben Titel, die dort
    über Dokumentversionen zusammengeführt werden.

    Verworfen: den Verweis behalten, weil er auf eine überholte Fassung
    zeigte.
    """

    @pytest.fixture
    def angebot(self, kunde):
        beleg = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.ANGEBOT, betreff='Halle Nord')
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Montage', menge=Decimal('10'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00')
        return beleg

    @pytest.fixture
    def abgelegt(self, angebot):
        """Festgeschriebenes, archiviertes Angebot, Fassung 1."""
        services.beleg_festschreiben(beleg_id=angebot.pk)
        services.archivierung_vermerken(beleg_id=angebot.pk, paperless_id=99)
        return Beleg.objects.get(pk=angebot.pk)

    def test_die_neue_fassung_bekommt_ein_eigenes_dokument(
        self, eingerichtet, mit_pdf, abgelegt, settings,
        django_capture_on_commit_callbacks
    ):
        settings.PAPERLESS_WARTEN_BEIM_FESTSCHREIBEN = True
        services.beleg_wiedereroeffnen(beleg_id=abgelegt.pk)

        with patch('faktura.archiv.hochladen',
                   return_value='aufgabe-2') as upload, \
             patch('faktura.archiv.aufgabe_abfragen',
                   return_value=('success', 100, '')):
            with django_capture_on_commit_callbacks(execute=True):
                services.beleg_festschreiben(beleg_id=abgelegt.pk)

        beleg = Beleg.objects.get(pk=abgelegt.pk)
        assert upload.call_count == 1
        # Das alte Dokument 99 bleibt in Paperless; kein Verweis mehr
        # darauf.
        assert beleg.paperless_id == 100

    def test_der_verweis_wird_geloest_auch_ohne_archiv(
        self, mit_pdf, abgelegt
    ):
        """Der Verweis wird auch ohne eingerichtetes Archiv entfernt.

        Sonst zeigte er auf eine überholte Fassung, während
        ``pruefe_belegarchiv`` und die Archivspalte "abgelegt" meldeten.
        ``belege_archivieren`` findet den Beleg über die leere
        ``paperless_id``.
        """
        beleg = services.beleg_wiedereroeffnen(beleg_id=abgelegt.pk)

        assert beleg.paperless_id is None
        assert beleg.archiviert_am is None

    def test_eine_offene_aufgabe_gehoert_zur_alten_fassung(
        self, mit_pdf, angebot
    ):
        """Eine offene Task-ID wird beim Wiedereröffnen entfernt.

        Sonst speicherte ``beleg_archivieren`` die Dokumentnummer der ersten
        Fassung; die zweite würde nie archiviert, und der Beleg erschiene
        archiviert.
        """
        services.beleg_festschreiben(beleg_id=angebot.pk)
        Beleg.objects.filter(pk=angebot.pk).update(paperless_task_id='läuft')

        services.beleg_wiedereroeffnen(beleg_id=angebot.pk)

        assert Beleg.objects.get(pk=angebot.pk).paperless_task_id == ''

    def test_das_dokument_wird_neu_erzeugt(self, mit_pdf, abgelegt):
        """Das Dokument wird neu erzeugt.

        Geprüft an der Prüfsumme, weil nur die Änderung zählt; den Inhalt
        prüfen die PDF-Tests.
        """
        vorher = abgelegt.pdf_sha256
        beleg = services.beleg_wiedereroeffnen(beleg_id=abgelegt.pk)
        beleg.betreff = 'Halle Nord, zweiter Anlauf'
        beleg.save()
        services.beleg_festschreiben(beleg_id=abgelegt.pk)

        assert Beleg.objects.get(pk=abgelegt.pk).pdf_sha256 != vorher
