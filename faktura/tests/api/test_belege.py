"""Was am Belegendpunkt gelten muss.

Der Prüfmaßstab ist der Ablauf, für den es ihn gibt: Ein
Archivierungslauf fragt nach dem Zuwachs, holt das Dokument, legt es ab und
meldet zurück. Jeder Test hier gehört zu einem Schritt davon.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Permission
from django.db import IntegrityError, transaction
from django.utils import timezone

from faktura import services
from faktura.models import Beleg, BelegStatus, BelegTyp, Rechnungsart

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Zugang
# ---------------------------------------------------------------------------

class TestZugang:

    def test_ohne_leserecht_keine_belege(self, client_ohne_rechte, rechnung):
        """Die Regel aus Etappe 0, hier an einem echten Endpunkt."""
        assert client_ohne_rechte.get('/api/v1/belege/').status_code == 403

    def test_mit_leserecht_sichtbar(self, client, rechnung):
        assert client.get('/api/v1/belege/').status_code == 200

    def test_anlegen_bleibt_verschlossen(self, client, leser, kunde):
        """Kein generisches Schreiben: Nummernvergabe, Transaktion und
        Festschreibungsregeln laufen über services.py und sonst nirgends.

        Geprüft wird ausdrücklich mit jemandem, der ``add_beleg`` **besitzt**.
        Ohne das Recht käme eine 403, und die sagte nur "dir fehlt etwas" -
        nicht "diesen Weg gibt es hier gar nicht". Die 405 ist die stärkere
        Aussage: Auch wer dürfte, kann nicht."""
        leser.user_permissions.add(Permission.objects.get(
            content_type__app_label='faktura', codename='add_beleg'))

        antwort = client.post('/api/v1/belege/', {'typ': 'rechnung'}, format='json')

        assert antwort.status_code == 405


# ---------------------------------------------------------------------------
# Die Liste: was ein Archivierungslauf braucht
# ---------------------------------------------------------------------------

class TestListe:

    def test_traegt_die_fachlichen_nummern_statt_der_schluessel(self, client, rechnung):
        """Das Archiv kennt "K-1024", nicht die Zeilennummer 17."""
        eintrag = client.get('/api/v1/belege/').json()['results'][0]

        assert eintrag['kunde'] == 'K-1024'
        assert eintrag['kunde_name'] == 'Bauherr Nord GmbH'
        assert eintrag['nummer'] == rechnung.nummer

    def test_nennt_das_projekt_wenn_eines_dranhaengt(self, client, firma, projekt):
        beleg = services.beleg_anlegen(
            typ=BelegTyp.RECHNUNG, projekt=projekt, leistungsdatum=date(2026, 8, 1))
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Rohbau', menge=Decimal('1.000'),
            einheit='Pausch', einzelpreis=Decimal('100.00'),
            steuersatz='19.00',
        )
        services.beleg_festschreiben(beleg_id=beleg.pk)

        eintrag = client.get('/api/v1/belege/').json()['results'][0]

        assert eintrag['projekt'] == '2026-042'
        assert eintrag['projekt_bezeichnung'] == 'Halle Nord'

    def test_summen_kommen_als_zeichenkette(self, client, rechnung):
        """Eine JSON-Zahl würde in JavaScript zum float. Fundstück 5."""
        summen = client.get('/api/v1/belege/').json()['results'][0]['summen']

        assert summen['netto'] == '2500.00'
        assert summen['steuer'] == '475.00'
        assert summen['brutto'] == '2975.00'
        assert isinstance(summen['brutto'], str)

    def test_summen_stimmen_mit_dem_service_ueberein(self, client, rechnung):
        """Kein zweiter Rechenweg in der Web-Schicht, sonst gehen Rechnung und
        Auskunft über sie irgendwann um einen Cent auseinander."""
        erwartet = services.belegsummen(rechnung)
        summen = client.get('/api/v1/belege/').json()['results'][0]['summen']

        assert summen['brutto'] == str(erwartet.brutto)

    def test_steuer_wird_je_satz_ausgewiesen(self, client, rechnung):
        anteile = client.get('/api/v1/belege/').json()['results'][0]['summen']['nach_steuersatz']

        assert anteile == [{'satz': '19.00', 'netto': '2500.00', 'steuer': '475.00'}]

    def test_sagt_ob_der_betrag_eine_aussage_ist(self, client, firma, kunde):
        """Ein Lieferschein weist keinen Wert aus. Admin und PDF blenden
        seine Preise aus. Die Schnittstelle liefert die Summen trotzdem, sagt
        aber dazu, dass sie hier keine Aussage sind. Wer sie ungeprüft als
        Betrag an ein Archivdokument schriebe, hielte am Lieferschein einen
        Wert fest, den es dort nicht geben soll."""
        lieferschein = services.beleg_anlegen(typ=BelegTyp.LIEFERSCHEIN, kunde=kunde)
        services.position_hinzufuegen(
            beleg=lieferschein, bezeichnung='Ware', menge=Decimal('1.000'),
            einheit='Stk', einzelpreis=Decimal('10.00'), steuersatz='19.00')

        eintraege = {b['typ_kennung']: b for b in client.get('/api/v1/belege/').json()['results']}

        assert eintraege['lieferschein']['ist_wertbeleg'] is False

    def test_bei_einer_rechnung_ist_er_eine(self, client, rechnung):
        eintrag = client.get('/api/v1/belege/').json()['results'][0]

        assert eintrag['ist_wertbeleg'] is True

    def test_holt_die_positionen_nicht_einzeln_nach(
            self, client, firma, kunde, django_assert_max_num_queries):
        """Die Summen entstehen aus den Positionen. Ohne Vorablesen kostet
        jeder weitere Beleg eine zusätzliche Abfrage, und das fällt erst beim
        ersten Jahreslauf auf."""
        for _ in range(5):
            beleg = services.beleg_anlegen(
                typ=BelegTyp.RECHNUNG, kunde=kunde,
                leistungsdatum=date(2026, 8, 1))
            services.position_hinzufuegen(
                beleg=beleg, bezeichnung='Posten', menge=Decimal('1.000'),
                einheit='Stk', einzelpreis=Decimal('10.00'),
                steuersatz='19.00',
            )
            services.beleg_festschreiben(beleg_id=beleg.pk)

        # Anmeldung, Rechte, Zählung, Belege, Positionen, mehr nicht.
        with django_assert_max_num_queries(8):
            antwort = client.get('/api/v1/belege/')

        assert len(antwort.json()['results']) == 5


# ---------------------------------------------------------------------------
# Filter: der Zuwachs seit dem letzten Lauf
# ---------------------------------------------------------------------------

class TestFilter:

    def test_zuwachs_seit_einem_zeitpunkt(self, client, firma, kunde, rechnung):
        """Der wichtigste Filter überhaupt: Ohne ihn läuft jeder Export über
        den gesamten Bestand statt über das Neue."""
        grenze = timezone.now()

        spaeter = services.beleg_anlegen(
            typ=BelegTyp.RECHNUNG, kunde=kunde, leistungsdatum=date(2026, 8, 1))
        services.position_hinzufuegen(
            beleg=spaeter, bezeichnung='Neu', menge=Decimal('1.000'),
            einheit='Stk', einzelpreis=Decimal('50.00'),
            steuersatz='19.00',
        )
        services.beleg_festschreiben(beleg_id=spaeter.pk)

        treffer = client.get(
            '/api/v1/belege/', {'festgeschrieben_ab': grenze.isoformat()},
        ).json()['results']

        assert [t['id'] for t in treffer] == [spaeter.pk]

    def test_der_zeitstempel_darf_eine_zeitzone_tragen(self, client, rechnung):
        """Was ein Ablaufwerkzeug sich merkt, ist ein ISO-8601-Zeitstempel mit
        Zeitzone. Der gewöhnliche DateTimeFilter versteht davon nur einen Teil
        und wirft den Rest still weg."""
        antwort = client.get(
            '/api/v1/belege/', {'festgeschrieben_ab': '2020-01-01T00:00:00+02:00'})

        assert antwort.status_code == 200
        assert antwort.json()['count'] == 1

    # --- Der Weg des XML zum Steuerberater (seit 2026-09-23) -------------

    def test_vom_archivdokument_zum_beleg(self, client, rechnung):
        """Der Ablauf startet beim Dokument in Paperless und kennt nur
        dessen Nummer."""
        services.archivierung_vermerken(beleg_id=rechnung.pk, paperless_id=4711)

        treffer = client.get(
            '/api/v1/belege/', {'paperless_id': 4711}).json()['results']
        daneben = client.get(
            '/api/v1/belege/', {'paperless_id': 4712}).json()['results']

        assert [t['id'] for t in treffer] == [rechnung.pk]
        assert daneben == []

    def test_das_profil_steht_in_der_liste(self, client, rechnung_mit_xml):
        """Daran entscheidet der Ablauf, ob das XML mit muss, ohne jeden
        Beleg einzeln abzurufen."""
        treffer = client.get('/api/v1/belege/').json()['results']

        assert treffer[0]['erechnungsprofil'] == 'EN 16931'

    def test_nach_profil_filtern(self, client, rechnung_mit_xml):
        from faktura.models import Beleg

        Beleg.objects.filter(pk=rechnung_mit_xml.pk).update(
            erechnungsprofil='XRECHNUNG')

        xrechnung = client.get(
            '/api/v1/belege/', {'erechnungsprofil': 'xrechnung'}).json()
        en16931 = client.get(
            '/api/v1/belege/', {'erechnungsprofil': 'EN 16931'}).json()

        assert xrechnung['count'] == 1
        assert en16931['count'] == 0

    def test_nach_abgelegtem_xml_filtern(self, client, rechnung_mit_xml):
        mit = client.get('/api/v1/belege/', {'mit_xml': 'true'}).json()
        ohne = client.get('/api/v1/belege/', {'mit_xml': 'false'}).json()

        assert mit['count'] == 1
        assert ohne['count'] == 0

    def test_die_pruefsumme_gehoert_zur_ausgelieferten_datei(
            self, client, rechnung_mit_xml):
        """Wer das XML weiterreicht, kann es gegen die Auskunft prüfen -
        und nur dann taugt die Prüfsumme als Nachweis."""
        import hashlib

        auskunft = client.get(f'/api/v1/belege/{rechnung_mit_xml.pk}/').json()
        datei = client.get(f'/api/v1/belege/{rechnung_mit_xml.pk}/xml/')

        assert auskunft['xml_sha256'] == hashlib.sha256(
            b''.join(datei.streaming_content)).hexdigest()

    def test_was_noch_nicht_im_archiv_liegt(self, client, rechnung):
        offen = client.get('/api/v1/belege/', {'archiviert': 'false'}).json()
        abgelegt = client.get('/api/v1/belege/', {'archiviert': 'true'}).json()

        assert offen['count'] == 1
        assert abgelegt['count'] == 0

    def test_nach_der_ablage_dreht_sich_das_um(self, client, rechnung):
        services.archivierung_vermerken(beleg_id=rechnung.pk, paperless_id=4711)

        assert client.get('/api/v1/belege/', {'archiviert': 'false'}).json()['count'] == 0
        assert client.get('/api/v1/belege/', {'archiviert': 'true'}).json()['count'] == 1

    def test_nach_kundennummer(self, client, rechnung):
        assert client.get('/api/v1/belege/', {'kunde': 'K-1024'}).json()['count'] == 1
        assert client.get('/api/v1/belege/', {'kunde': 'K-9999'}).json()['count'] == 0

    def test_nach_projektnummer(self, client, firma, projekt):
        beleg = services.beleg_anlegen(
            typ=BelegTyp.RECHNUNG, projekt=projekt, leistungsdatum=date(2026, 8, 1))

        assert client.get('/api/v1/belege/', {'projekt': '2026-042'}).json()['count'] == 1
        assert beleg.projekt == projekt

    def test_nach_belegart(self, client, rechnung, entwurf):
        assert client.get('/api/v1/belege/', {'typ': 'rechnung'}).json()['count'] == 1
        assert client.get('/api/v1/belege/', {'typ': 'angebot'}).json()['count'] == 1

    def test_nach_belegnummer(self, client, rechnung):
        treffer = client.get('/api/v1/belege/', {'nummer': rechnung.nummer}).json()

        assert treffer['count'] == 1


# ---------------------------------------------------------------------------
# Einzelauskunft
# ---------------------------------------------------------------------------

class TestEinzelauskunft:

    def test_traegt_die_positionen(self, client, entwurf):
        daten = client.get(f'/api/v1/belege/{entwurf.pk}/').json()

        assert [p['bezeichnung'] for p in daten['positionen']] == ['Planung', 'Fahrtkosten']

    def test_jede_position_bringt_ihre_summe_mit(self, client, entwurf):
        """Dieses System rundet je Position und summiert danach. Wer selbst
        nachrechnet, ohne das zu wissen, kommt auf einen anderen Betrag."""
        erste = client.get(f'/api/v1/belege/{entwurf.pk}/').json()['positionen'][0]

        assert erste['summe'] == '950.00'

    def test_ein_entwurf_ist_auffindbar(self, client, entwurf):
        """Entwürfe haben keine Nummer, deshalb geht die Adresse hier über die
        Datenbank-ID und nicht über die Belegnummer."""
        daten = client.get(f'/api/v1/belege/{entwurf.pk}/').json()

        assert daten['nummer'] is None
        assert daten['status_kennung'] == BelegStatus.ENTWURF


# ---------------------------------------------------------------------------
# Das Dokument
# ---------------------------------------------------------------------------

class TestDokument:

    def test_liefert_die_gespeicherte_datei(self, client, rechnung_mit_pdf):
        """Nicht neu gerendert: Sonst sähe eine Rechnung von 2026 nach dem
        nächsten Umbau der Vorlage anders aus als die, die der Kunde bekam."""
        antwort = client.get(f'/api/v1/belege/{rechnung_mit_pdf.pk}/pdf/')

        assert antwort.status_code == 200
        assert antwort['Content-Type'] == 'application/pdf'
        assert b''.join(antwort.streaming_content) == b'%PDF-1.4 Attrappe'

    def test_der_dateiname_ist_sprechend(self, client, rechnung_mit_pdf):
        antwort = client.get(f'/api/v1/belege/{rechnung_mit_pdf.pk}/pdf/')

        assert rechnung_mit_pdf.nummer in antwort['Content-Disposition']

    def test_ein_entwurf_bekommt_keine_vorschau(self, client, entwurf):
        """404 und nicht ein frisch gerendertes PDF: Eine Vorschau in einem
        Archivsystem wäre ein Beleg, der keiner ist."""
        assert client.get(f'/api/v1/belege/{entwurf.pk}/pdf/').status_code == 404

    def test_fehlende_datei_ergibt_404_statt_500(self, client, rechnung_mit_pdf):
        """Der Vermerk steht, die Datei fehlt: nach einem unvollständigen
        Restore oder einem beherzten Aufräumen im Ablageverzeichnis. Genau
        diesen Fall soll ``pruefe_belegarchiv`` aufspüren; die Schnittstelle
        darf ihn nicht als unbehandelten Serverfehler beantworten. Ein
        Archivierungslauf sieht bei 500 einen kaputten Dienst, bei 404 einen
        fehlenden Beleg. Nur das zweite stimmt."""
        rechnung_mit_pdf.pdf.storage.delete(rechnung_mit_pdf.pdf.name)

        antwort = client.get(f'/api/v1/belege/{rechnung_mit_pdf.pk}/pdf/')

        assert antwort.status_code == 404

    def test_das_xml_gibt_es_zur_rechnung(self, client, rechnung_mit_xml):
        """Die abgelegte Datei, byte-gleich, nicht neu erzeugt. Seit das XML
        allein an ein Rechnungsportal gehen kann, ist es dort das Original,
        und über diesen Weg holt es der Ablauf zum Steuerberater."""
        antwort = client.get(f'/api/v1/belege/{rechnung_mit_xml.pk}/xml/')

        assert antwort.status_code == 200
        assert antwort['Content-Type'] == 'application/xml'
        assert b''.join(antwort.streaming_content) == (
            b'<rsm:CrossIndustryInvoice>abgelegt</rsm:CrossIndustryInvoice>')
        assert (f'Rechnung_{rechnung_mit_xml.nummer}.xml'
                in antwort['Content-Disposition'])

    def test_ohne_abgelegtes_xml_kein_neues(self, client, rechnung):
        """Früher entstand das XML hier im Zugriff. Ein neu erzeugtes hinge
        an den Stammdaten von heute statt an denen vom Tag der Rechnung -
        lieber 404 als eine Rechnung, die so nie verschickt wurde."""
        assert client.get(f'/api/v1/belege/{rechnung.pk}/xml/').status_code == 404

    def test_fehlende_xml_datei_ergibt_404_statt_500(self, client, rechnung_mit_xml):
        rechnung_mit_xml.xml.storage.delete(rechnung_mit_xml.xml.name)

        antwort = client.get(f'/api/v1/belege/{rechnung_mit_xml.pk}/xml/')

        assert antwort.status_code == 404

    def test_zum_angebot_gibt_es_keines(self, client, entwurf):
        """Ein Angebot ist keine Rechnung. Ein Factur-X-XML dazu wäre im
        Postfach des Empfängers ein Blindgänger."""
        assert client.get(f'/api/v1/belege/{entwurf.pk}/xml/').status_code == 404


# ---------------------------------------------------------------------------
# Der Archivvermerk
# ---------------------------------------------------------------------------

class TestArchivvermerk:

    def _melden(self, client, beleg, paperless_id):
        return client.post(
            f'/api/v1/belege/{beleg.pk}/archiviert/',
            {'paperless_document_id': paperless_id}, format='json',
        )

    def test_leserecht_allein_genuegt_nicht(self, client, rechnung):
        """Der Vermerk ist eine Schreiboperation und verlangt ein eigenes
        Recht, nicht das Recht, Belege zu ändern."""
        assert self._melden(client, rechnung, 4711).status_code == 403

    def test_mit_dem_eigenen_recht_geht_es(self, client, darf_archivieren, rechnung):
        antwort = self._melden(client, rechnung, 4711)

        assert antwort.status_code == 200
        rechnung.refresh_from_db()
        assert rechnung.paperless_id == 4711

    def test_haelt_den_zeitpunkt_fest(self, client, darf_archivieren, rechnung):
        """Die ID allein sagt "ist archiviert". Für eine Nachfrage des Prüfers
        ist das Wann die eigentliche Auskunft."""
        self._melden(client, rechnung, 4711)

        rechnung.refresh_from_db()
        assert rechnung.archiviert_am is not None

    def test_die_antwort_zeigt_den_neuen_stand(self, client, darf_archivieren, rechnung):
        daten = self._melden(client, rechnung, 4711).json()

        assert daten['archiviert'] is True
        assert daten['paperless_id'] == 4711

    def test_derselbe_vermerk_darf_wiederholt_werden(
            self, client, darf_archivieren, rechnung):
        """Ein abgebrochener und erneut gestarteter Lauf darf nicht scheitern."""
        self._melden(client, rechnung, 4711)

        assert self._melden(client, rechnung, 4711).status_code == 200

    def test_ein_abweichender_vermerk_wird_abgelehnt(
            self, client, darf_archivieren, rechnung):
        """Das hieße, derselbe Beleg läge zweimal im Archiv. Eine Auskunft,
        die niemand verschlucken sollte."""
        self._melden(client, rechnung, 4711)

        antwort = self._melden(client, rechnung, 4712)

        assert antwort.status_code == 409
        assert '4711' in antwort.json()['detail']

    def test_ein_entwurf_kann_nicht_archiviert_werden(
            self, client, darf_archivieren, entwurf):
        """Er hat kein Dokument, und was noch änderbar ist, gehört nicht in
        ein Archiv."""
        antwort = self._melden(client, entwurf, 4711)

        assert antwort.status_code == 409

    def test_der_beleg_selbst_bleibt_unberuehrt(
            self, client, darf_archivieren, rechnung):
        """Der Vermerk sagt, wo die Kopie liegt. Er ist keine Änderung am
        Beleg. Deshalb darf er auch nach dem Festschreiben gesetzt werden,
        ohne den Schutz aus Beleg.save() auszuhebeln."""
        vorher = services.belegsummen(rechnung).brutto

        self._melden(client, rechnung, 4711)

        rechnung.refresh_from_db()
        assert rechnung.status == BelegStatus.FESTGESCHRIEBEN
        assert services.belegsummen(rechnung).brutto == vorher

    def test_eine_archivnummer_gehoert_zu_genau_einem_beleg(
            self, client, darf_archivieren, rechnung, firma, kunde):
        """Die Datenbank hält das fest, nicht nur der Anwendungscode."""
        zweite = services.beleg_anlegen(
            typ=BelegTyp.RECHNUNG, kunde=kunde, leistungsdatum=date(2026, 8, 1))
        services.position_hinzufuegen(
            beleg=zweite, bezeichnung='Posten', menge=Decimal('1.000'),
            einheit='Stk', einzelpreis=Decimal('10.00'),
            steuersatz='19.00',
        )
        services.beleg_festschreiben(beleg_id=zweite.pk)

        self._melden(client, rechnung, 4711)

        # Am Modell vorbei geschrieben: Geprüft werden soll die Regel in der
        # Datenbank, nicht die im Service. Fundstück 53: Wer die Wirksamkeit
        # einer Datenbankregel prüfen will, muss sie dort angreifen, wo die
        # Datenbank sie herhat.
        with pytest.raises(IntegrityError), transaction.atomic():
            Beleg.objects.filter(pk=zweite.pk).update(paperless_id=4711)

    def test_eine_fehlende_angabe_wird_bemaengelt(self, client, darf_archivieren, rechnung):
        antwort = client.post(
            f'/api/v1/belege/{rechnung.pk}/archiviert/', {}, format='json')

        assert antwort.status_code == 400


# ---------------------------------------------------------------------------
# Festschreiben
# ---------------------------------------------------------------------------

class TestFestschreiben:
    """Derselbe Vorgang wie die Admin-Aktion, über dieselbe Servicefunktion.

    Geprüft wird hier nicht, ob das Festschreiben stimmt. Das steht in
    ``faktura/tests/test_festschreiben.py`` und ist dort gründlicher. Geprüft wird, dass
    die Schnittstelle **denselben** Weg nimmt und dabei nichts unterschlägt,
    was der Admin mitliefert: den Benutzer und den Protokolleintrag.
    """

    def _festschreiben(self, client, beleg):
        return client.post(f'/api/v1/belege/{beleg.pk}/festschreiben/', format='json')

    def test_leserecht_allein_genuegt_nicht(self, client, entwurf):
        assert self._festschreiben(client, entwurf).status_code == 403

    def test_der_dienstzugang_darf_es_nicht(self, client, leser, entwurf):
        """Auch mit allen Leserechten und dem Archivrecht nicht. Festschreiben
        ist ein Geschäftsvorgang mit rechtlicher Wirkung, kein Datenabgleich."""
        leser.user_permissions.add(Permission.objects.get(
            content_type__app_label='faktura', codename='archivieren_beleg'))

        assert self._festschreiben(client, entwurf).status_code == 403

    def test_mit_aenderungsrecht_geht_es(self, client, darf_aendern, entwurf):
        antwort = self._festschreiben(client, entwurf)

        assert antwort.status_code == 200
        entwurf.refresh_from_db()
        assert entwurf.status == BelegStatus.FESTGESCHRIEBEN

    def test_die_nummer_kommt_aus_dem_nummernkreis(self, client, darf_aendern, entwurf):
        daten = self._festschreiben(client, entwurf).json()

        assert daten['nummer'] is not None
        assert daten['nummer'].startswith('AN-')

    def test_haelt_fest_wer_es_war(self, client, darf_aendern, entwurf):
        """Das "Wer" am Beleg ist eine GoBD-Angabe. Über die Schnittstelle darf
        sie nicht wegfallen, nur weil kein Formular im Spiel war."""
        self._festschreiben(client, entwurf)

        entwurf.refresh_from_db()
        assert entwurf.festgeschrieben_von == darf_aendern

    def test_landet_im_aenderungsprotokoll(self, client, darf_aendern, entwurf):
        """Weder Admin-Aktionen noch die Schnittstelle protokollieren von
        allein. Ohne den Eintrag liefe ausgerechnet der wichtigste Vorgang des
        Systems am Nachweis vorbei."""
        self._festschreiben(client, entwurf)

        eintrag = LogEntry.objects.filter(object_id=str(entwurf.pk)).first()

        assert eintrag is not None
        assert 'Festgeschrieben' in eintrag.change_message
        assert eintrag.user == darf_aendern

    def test_das_protokoll_haengt_am_proxy_nicht_am_basismodell(
            self, client, darf_aendern, entwurf):
        """Sonst erschiene der Eintrag im "Verlauf" des Angebots nie. Er wäre
        da und trotzdem unauffindbar."""
        self._festschreiben(client, entwurf)

        eintrag = LogEntry.objects.filter(object_id=str(entwurf.pk)).first()

        assert eintrag.content_type.model == 'angebot'

    def test_das_protokoll_trifft_den_proxy_der_rechnungsart(
            self, client, darf_aendern, kunde, firma):
        """Rechnungsarten teilen sich ``typ``; ohne ``rechnungsart`` ergibt
        ``proxy_fuer`` den Proxy ``Rechnung``, dessen Manager einen Abschlag
        nicht findet, und ``log_actions`` schreibt nichts."""
        abschlag = services.beleg_anlegen(
            typ=BelegTyp.RECHNUNG, rechnungsart=Rechnungsart.ABSCHLAG,
            kunde=kunde, betreff='Abschlag',
            leistungsdatum=date(2026, 1, 1), leistungsdatum_bis=date(2026, 1, 31))
        services.position_hinzufuegen(
            beleg=abschlag, bezeichnung='Leistungsstand', menge=Decimal('1'),
            einheit='pausch', einzelpreis=Decimal('1000.00'), steuersatz='19.00')

        assert self._festschreiben(client, abschlag).status_code == 200
        eintrag = LogEntry.objects.get(object_id=str(abschlag.pk))

        assert eintrag.content_type.model == 'abschlagsrechnung'

    def test_zweimal_festschreiben_geht_nicht(self, client, darf_aendern, rechnung):
        antwort = self._festschreiben(client, rechnung)

        assert antwort.status_code == 409

    def test_meldet_widerspruechliche_empfaengerangaben(
            self, client, darf_aendern, firma, kunde):
        """Der Admin zeigt an dieser Stelle eine Warnung. Über die
        Schnittstelle gibt es niemanden, dem man sie anzeigen könnte, also
        reist sie in der Antwort mit.

        Der Beleg trägt die Anschrift zweimal: als freien Text für den
        Ausdruck und zerlegt für das eingebettete XML. Laufen beide
        auseinander, steht auf dem Papier ein anderer Empfänger als im
        maschinell gelesenen Teil, und niemand sieht es.
        """
        beleg = services.beleg_anlegen(
            typ=BelegTyp.RECHNUNG, kunde=kunde, leistungsdatum=date(2026, 8, 1))
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='P', menge=Decimal('1.000'),
            einheit='Stk', einzelpreis=Decimal('10.00'), steuersatz='19.00')
        # Der Ausdruck nennt jemand anderen als die E-Rechnungsfelder.
        Beleg.objects.filter(pk=beleg.pk).update(
            empfaenger='Ganz andere GmbH\nAnderstraße 9\n99999 Anderswo')

        daten = self._festschreiben(client, beleg).json()

        assert daten['hinweise'], 'der Widerspruch blieb unerwaehnt'
        assert any('Bauherr Nord' in h for h in daten['hinweise'])

    def test_ohne_widerspruch_bleibt_die_liste_leer(
            self, client, darf_aendern, entwurf):
        """Eine Warnung, die immer erscheint, wird zu Recht ignoriert."""
        assert self._festschreiben(client, entwurf).json()['hinweise'] == []

    def test_ein_beleg_ohne_positionen_wird_abgelehnt(
            self, client, darf_aendern, firma, kunde):
        """Der fachliche Fehler aus dem Service wird zur erklärenden Antwort,
        nicht zum Serverfehler. Dafür sorgt der Handler in core."""
        leer = services.beleg_anlegen(typ=BelegTyp.ANGEBOT, kunde=kunde)

        antwort = self._festschreiben(client, leer)

        assert antwort.status_code == 400
        assert 'Positionen' in antwort.json()['detail']

    @pytest.fixture
    def zuviel(self, firma, kunde):
        """10 Std beauftragt, die Rechnung fordert 12."""
        from faktura.models import Projekt

        projekt = Projekt.objects.create(
            nummer='2026-078', bezeichnung='Halle West', kunde=kunde)
        auftrag = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.AUFTRAG)
        position = services.position_hinzufuegen(
            beleg=auftrag, bezeichnung='Planung', menge=Decimal('10'),
            einheit='Std', einzelpreis=Decimal('95.00'),
            steuersatz='19.00')
        services.beleg_festschreiben(beleg_id=auftrag.pk)

        rechnung = services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG,
            leistungsdatum=date(2026, 8, 1))
        services.position_hinzufuegen(
            beleg=rechnung, bezeichnung='Planung', menge=Decimal('12'),
            einheit='Std', einzelpreis=Decimal('95.00'),
            steuersatz='19.00', auftragsposition=position)
        return rechnung

    def test_mehr_als_beauftragt_ohne_bestaetigung_ist_409(
            self, client, darf_aendern, zuviel):
        """Ein Automat schreibt nicht ungefragt über den Auftrag hinaus."""
        antwort = self._festschreiben(client, zuviel)

        assert antwort.status_code == 409
        assert '2 zu viel' in antwort.json()['detail']
        zuviel.refresh_from_db()
        assert zuviel.status == BelegStatus.ENTWURF

    def test_mit_bestaetigung_geht_es(self, client, darf_aendern, zuviel):
        antwort = client.post(f'/api/v1/belege/{zuviel.pk}/festschreiben/',
                              {'mengen_bestaetigt': True}, format='json')

        assert antwort.status_code == 200
        zuviel.refresh_from_db()
        assert zuviel.status == BelegStatus.FESTGESCHRIEBEN
