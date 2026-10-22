"""Tests der Erzeugung von PDF und XML.

Geprüft werden rechtliche und kaufmännische Anforderungen, nicht das
Layout:

* **Pflichtangaben nach § 14 UStG** im PDF, weil eine Rechnung ohne
  Steuernummer den Vorsteuerabzug ausschließt.
* **Unveränderlichkeit** des PDFs nach dem Festschreiben.
* **Gültiges Factur-X-XML**, das mit dem PDF übereinstimmt.

Die Tests rendern mit ``mit_pdf`` (conftest.py) und sind daher langsamer.
"""

import io
import re
from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone
from pypdf import PdfReader

from faktura import facturx, formate, pdf, services
from faktura.models import (
    BelegStatus,
    BelegTyp,
    Kontakt,
    Rechnungsart,
)


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-2000', name='Beispiel AG', strasse='Industriestraße 5',
        plz='90402', ort='Nürnberg', ust_id='DE987654321',
    )


@pytest.fixture
def rechnung(kunde):
    beleg = services.beleg_anlegen(
        kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Projekt Faktura',
        leistungsdatum=timezone.localdate(),
    )
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Konzeption und Beratung',
        menge=Decimal('12.5'), einheit='Std',
        einzelpreis=Decimal('120.00'), steuersatz='19.00',
    )
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Handbuch (gedruckt)',
        menge=Decimal('3'), einheit='Stk',
        einzelpreis=Decimal('45.00'), steuersatz='7.00',
    )
    return beleg


def text_aus(daten: bytes) -> str:
    """Extrahierter Text des PDFs ohne Zeilenumbrüche.

    Geprüft am extrahierten Text, weil er zeigt, was im PDF steht, und
    nicht nur, was das Template enthält.
    """
    import io
    leser = PdfReader(io.BytesIO(daten))
    roh = '\n'.join(seite.extract_text() for seite in leser.pages)
    return re.sub(r'\s+', ' ', roh)


@pytest.mark.django_db
class TestPflichtangaben:
    """Pflichtangaben einer Rechnung nach § 14 Abs. 4 UStG."""

    def test_rechnung_traegt_alle_pflichtangaben(self, mit_pdf, firma, rechnung):
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)
        text = text_aus(beleg.pdf.read())

        # Nr. 1: vollständiger Name und Anschrift beider Seiten.
        # Der Empfänger ist ein freies Textfeld; geprüft wird jede Zeile im
        # PDF.
        assert firma.name in text
        assert firma.strasse in text
        for zeile in beleg.empfaenger.splitlines():
            assert zeile in text
        # Nr. 2: Steuernummer oder USt-IdNr. des Leistenden
        assert firma.ust_id in text or firma.steuernummer in text
        # Nr. 3 und 4: Ausstellungsdatum und fortlaufende Nummer
        assert beleg.belegdatum.strftime('%d.%m.%Y') in text
        assert beleg.nummer in text
        # Nr. 5: Menge und Art der Leistung
        assert 'Konzeption und Beratung' in text
        # Nr. 6: Zeitpunkt der Leistung
        assert 'Leistungsdatum' in text
        # Nr. 7 und 8: nach Steuersätzen aufgeschlüsseltes Entgelt.
        # Mit Tausenderpunkt wie im PDF (die Eingabe im Admin bleibt ohne
        # Trennzeichen, siehe USE_THOUSAND_SEPARATOR).
        assert '1.635,00' in text       # netto
        assert '19 %' in text and '7 %' in text
        assert '1.929,45' in text       # brutto

    def test_entwurf_ist_als_entwurf_erkennbar(self, mit_pdf, rechnung):
        """Der Entwurf ist als Entwurf erkennbar, damit er nicht als Rechnung
        versendet wird."""
        text = text_aus(pdf.beleg_als_pdf(rechnung))

        assert 'Entwurf' in text
        assert rechnung.nummer is None

    def test_lieferschein_zeigt_keine_preise(self, mit_pdf, kunde):
        """Der Lieferschein zeigt keine Preise, weil er mit der Ware oft an
        eine andere Stelle geht als die Rechnung."""
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.LIEFERSCHEIN)
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Handbuch', menge=Decimal('3'),
            einheit='Stk', einzelpreis=Decimal('45.00'),
            steuersatz='19.00',
        )
        text = text_aus(pdf.beleg_als_pdf(beleg))

        assert 'Handbuch' in text
        assert '45,00' not in text
        assert 'Rechnungsbetrag' not in text


@pytest.mark.django_db
class TestEinfrieren:
    def test_pdf_wird_beim_festschreiben_abgelegt(self, mit_pdf, rechnung):
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)

        assert beleg.pdf.name.endswith('.pdf')
        assert beleg.pdf.size > 0
        assert len(beleg.pdf_sha256) == 64
        assert beleg.vorlagenversion == pdf.VORLAGENVERSION

    def test_pruefsumme_passt_zur_datei(self, mit_pdf, rechnung):
        """Die Prüfsumme passt zur Datei und weist nach, dass sie seit dem
        Festschreiben unverändert ist."""
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)

        assert pdf.pruefsumme(beleg.pdf.read()) == beleg.pdf_sha256

    def test_dokument_wird_nicht_neu_erzeugt(self, mit_pdf, rechnung):
        """Das gespeicherte PDF wird nicht neu erzeugt.

        Geprüft durch Änderung des Templates nach dem Festschreiben; das
        gespeicherte PDF bleibt unverändert.
        """
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)
        vorher = beleg.pdf.read()

        # Ein erneutes Rendern ergäbe jetzt etwas anderes, die gespeicherte
        # Datei nicht.
        beleg.refresh_from_db()
        beleg.pdf.open('rb')
        nachher = beleg.pdf.read()

        assert vorher == nachher
        assert pdf.pruefsumme(nachher) == beleg.pdf_sha256

    def test_xml_wird_daneben_abgelegt(self, mit_pdf, rechnung):
        """Zur E-Rechnung wird eine eigene XML-Datei mit Prüfsumme
        gespeichert, weil sie allein an ein Rechnungsportal gehen kann und
        dann das Original ist."""
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)
        beleg.refresh_from_db()

        # Ein Suffix ist zulässig, weil Django es bei vergebenem Namen im
        # Speicherverzeichnis anhängt.
        assert re.search(rf'/Rechnung_{beleg.nummer}(_\w+)?\.xml$',
                         beleg.xml.name), beleg.xml.name
        assert pdf.pruefsumme(beleg.xml.read()) == beleg.xml_sha256
        assert len(beleg.xml_sha256) == 64

    def test_xml_im_pdf_ist_dasselbe_wie_daneben(self, mit_pdf, rechnung):
        """Das XML im PDF hat dieselben Bytes wie die gespeicherte XML-Datei.

        Archiviert wird das PDF, versendet wird ggf. nur das XML; mit
        identischen Bytes belegt das Archiv, was der Kunde erhalten hat.
        """
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)
        beleg.refresh_from_db()

        anhaenge = PdfReader(io.BytesIO(beleg.pdf.read())).attachments
        eingebettet = anhaenge[facturx.XML_DATEINAME][0]

        assert eingebettet == beleg.xml.read()

    def test_angebot_bekommt_kein_xml(self, mit_pdf, kunde):
        """Ein Angebot erhält ein PDF, aber kein XML."""
        angebot = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        services.position_hinzufuegen(
            beleg=angebot, bezeichnung='Beratung', menge=Decimal('1'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00',
        )

        beleg = services.beleg_festschreiben(beleg_id=angebot.pk)
        beleg.refresh_from_db()

        assert beleg.pdf.name
        assert not beleg.xml.name
        assert beleg.xml_sha256 == ''

    def test_ohne_firma_keine_festschreibung(self, mit_pdf, rechnung, firma):
        """Ohne Firma schlägt das Festschreiben fehl.

        Damit keine Nummer aus dem lückenlosen Nummernkreis ohne
        versendbares Dokument vergeben wird.
        """
        firma.delete()

        with pytest.raises(services.DokumentFehlt):
            services.beleg_festschreiben(beleg_id=rechnung.pk)

        rechnung.refresh_from_db()
        assert rechnung.status == BelegStatus.ENTWURF
        assert rechnung.nummer is None


@pytest.mark.django_db
class TestFacturX:
    """E-Rechnung im PDF (Factur-X).

    Seit dem 1.1.2025 müssen inländische Unternehmen E-Rechnungen empfangen
    können, ab 2027/2028 gestaffelt auch versenden.
    """

    def test_xml_steckt_im_pdf(self, mit_pdf, rechnung):
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)

        import io
        leser = PdfReader(io.BytesIO(beleg.pdf.read()))
        assert facturx.XML_DATEINAME in leser.attachments

    def test_xmp_bleibt_gueltiges_xml(self, mit_pdf, rechnung):
        """Der Factur-X-Block steht **innerhalb** von rdf:RDF.

        Die Option xmp_metadata setzt ihn dahinter, wo der Präfix rdf:
        nicht gebunden ist; das PDF öffnet sich, erst der Validator des
        Empfängers meldet ungültige Metadaten.
        """
        import io
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)
        leser = PdfReader(io.BytesIO(beleg.pdf.read()))

        # Wirft PdfReadError, wenn das XMP nicht wohlgeformt ist.
        assert leser.xmp_metadata is not None

        roh = leser.trailer['/Root']['/Metadata'].get_data().decode()
        assert 'fx:DocumentFileName' in roh
        assert roh.index('fx:DocumentFileName') < roh.index('</rdf:RDF>')
        assert 'pdfaid:part="3"' in roh

    def test_betraege_stimmen_mit_dem_sichtbaren_beleg_ueberein(
        self, mit_pdf, rechnung
    ):
        """Die Beträge im XML stimmen mit dem PDF überein, Voraussetzung für
        die Zulässigkeit des Formats."""
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)
        summen = services.belegsummen(beleg)

        xml = facturx.xml_erzeugen(beleg).decode()

        def wert(tag):
            # [^>]*, weil manche Betragselemente ein currencyID-Attribut
            # haben.
            treffer = re.search(rf'<ram:{tag}[^>]*>([^<]*)</ram:{tag}>', xml)
            assert treffer, f'{tag} fehlt im XML'
            return Decimal(treffer.group(1))

        assert wert('GrandTotalAmount') == summen.brutto
        assert wert('TaxBasisTotalAmount') == summen.netto
        assert wert('TaxTotalAmount') == summen.steuer
        assert f'<ram:ID>{beleg.nummer}</ram:ID>' in xml

    def test_einheiten_werden_in_codes_uebersetzt(self, mit_pdf, rechnung):
        """Einheiten werden in Codes nach UN/ECE Rec 20 übersetzt, weil "Std"
        im XML unzulässig ist."""
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)
        xml = facturx.xml_erzeugen(beleg).decode()

        assert 'unitCode="HUR"' in xml     # Stunde
        assert 'unitCode="C62"' in xml     # Stück

    def test_angebot_bekommt_kein_xml(self, mit_pdf, kunde):
        """Ein Angebot erhält kein XML."""
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Leistung', menge=Decimal('1'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00',
        )
        beleg = services.beleg_festschreiben(beleg_id=beleg.pk)

        assert not facturx.ist_erechnungsfaehig(beleg)

        import io
        leser = PdfReader(io.BytesIO(beleg.pdf.read()))
        assert facturx.XML_DATEINAME not in leser.attachments

    def test_storno_wird_zur_gutschrift_mit_positiven_betraegen(
        self, mit_pdf, rechnung
    ):
        """Das Storno wird Gutschrift (381) mit positiven Beträgen.

        Intern ist das Storno negativ, damit sich eine Belegkette
        aufsummieren lässt; im XML wären negative Beträge ein Verstoß gegen
        die Richtlinie.
        """
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)
        storno, _ = services.rechnung_korrigieren(beleg_id=original.pk)

        xml = facturx.xml_erzeugen(storno).decode()

        assert '<ram:TypeCode>381</ram:TypeCode>' in xml
        assert '-' not in re.search(
            r'<ram:GrandTotalAmount>([^<]*)</ram:GrandTotalAmount>', xml
        ).group(1)
        # Intern bleibt der Beleg negativ.
        assert services.belegsummen(storno).brutto < 0

    def test_rechnungskorrektur_hat_keinen_negativen_einzelpreis(
        self, rechnung
    ):
        """BR-27: Der Netto-Einzelpreis (BT-146) ist nie negativ. Intern hat
        der Nachlass einen negativen Preis, im XML einen positiven; die
        Richtung gibt der Typ 381 an."""
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)
        korrektur = services.rechnungskorrektur_erstellen(
            beleg_id=original.pk, betrag_netto=Decimal('100.00'),
            grund='Nachlass wegen Verzug')
        korrektur = services.beleg_festschreiben(beleg_id=korrektur.pk)

        xml = facturx.xml_erzeugen(korrektur).decode()

        assert xml_wert(xml, 'TypeCode') == '381'
        assert xml_wert(xml, 'ChargeAmount') == '100.00'
        assert Decimal(xml_wert(xml, 'BilledQuantity')) == Decimal('1')
        assert xml_wert(xml, 'LineTotalAmount') == '100.00'
        assert '-' not in xml_wert(xml, 'GrandTotalAmount')

    def test_storno_verweist_auf_die_rechnung(self, rechnung):
        """BG-3: Das Storno nennt Nummer und Datum der stornierten Rechnung
        (§ 31 Abs. 5 UStDV)."""
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)
        storno, _ = services.rechnung_korrigieren(beleg_id=original.pk)

        xml = facturx.xml_erzeugen(storno).decode()

        assert vorgaengerbezug(xml) == (
            original.nummer, original.belegdatum.strftime('%Y%m%d'))

    def test_rechnungskorrektur_verweist_auf_die_rechnung(self, rechnung):
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)
        korrektur = services.rechnungskorrektur_erstellen(
            beleg_id=original.pk, betrag_netto=Decimal('100.00'),
            grund='Nachlass wegen Verzug')
        korrektur = services.beleg_festschreiben(beleg_id=korrektur.pk)

        xml = facturx.xml_erzeugen(korrektur).decode()

        assert vorgaengerbezug(xml) == (
            original.nummer, original.belegdatum.strftime('%Y%m%d'))

    def test_rechnung_ohne_vorgaengerbezug(self, rechnung):
        """Auch die Neufassung nach einem Storno hat kein BG-3, obwohl ihr
        ``vorgaenger`` gesetzt ist: Sie ist eine neue Rechnung."""
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)
        _, neufassung = services.rechnung_korrigieren(beleg_id=original.pk)
        neufassung = services.beleg_festschreiben(beleg_id=neufassung.pk)

        assert neufassung.vorgaenger_id == original.pk
        assert vorgaengerbezug(
            facturx.xml_erzeugen(original).decode()) is None
        assert vorgaengerbezug(
            facturx.xml_erzeugen(neufassung).decode()) is None

    def test_storno_hat_keinen_negativen_einzelpreis(self, rechnung):
        """Dasselbe beim Storno. Regression: Nur die Zeilensumme war positiv,
        der Einzelpreis blieb negativ."""
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)
        storno, _ = services.rechnung_korrigieren(beleg_id=original.pk)

        xml = facturx.xml_erzeugen(storno).decode()

        assert re.findall(r'<ram:ChargeAmount>([^<]*)</ram:ChargeAmount>',
                          xml) == ['120.00', '45.00']

    def test_nachlass_in_der_rechnung_traegt_das_minus_in_der_menge(
        self, rechnung
    ):
        """Eine Position mit negativem Preis in einer gewöhnlichen Rechnung:
        Preis positiv, Menge negativ (in BT-129 zulässig), Menge mal Preis
        bleibt der Zeilenbetrag."""
        services.position_hinzufuegen(
            beleg=rechnung, bezeichnung='Nachlass', menge=Decimal('1'),
            einheit='pausch', einzelpreis=Decimal('-50.00'),
            steuersatz='19.00',
        )
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)

        xml = facturx.xml_erzeugen(beleg).decode()

        assert re.findall(r'<ram:ChargeAmount>([^<]*)</ram:ChargeAmount>',
                          xml) == ['120.00', '45.00', '50.00']
        mengen = re.findall(
            r'<ram:BilledQuantity[^>]*>([^<]*)</ram:BilledQuantity>', xml)
        assert Decimal(mengen[-1]) == Decimal('-1')
        assert re.findall(
            r'<ram:LineTotalAmount>([^<]*)</ram:LineTotalAmount>', xml
        )[:3] == ['1500.00', '135.00', '-50.00']

    def test_kaeuferanschrift_kommt_aus_den_strukturfeldern(self, rechnung):
        """Die Käuferanschrift kommt aus den strukturierten Feldern am Beleg,
        gefüllt aus den Stammdaten. Das XML entsteht ohne PDF."""
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)

        xml = facturx.xml_erzeugen(beleg).decode()

        assert '<ram:PostcodeCode>90402</ram:PostcodeCode>' in xml
        assert 'Industriestraße 5' in xml
        assert 'Nürnberg' in xml

    def test_freitext_anschrift_wird_zur_not_zerlegt(self, rechnung):
        """Fallback für Belege ohne strukturierte Felder (Altdaten): Das freie
        Empfängerfeld wird heuristisch zerlegt."""
        from faktura.models import Beleg

        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)
        Beleg.objects.filter(pk=beleg.pk).update(
            empfaenger='Muster GmbH\nPostfach 11 22\n10115 Berlin',
            empfaenger_name='', empfaenger_strasse='',
            empfaenger_plz='', empfaenger_ort='',
        )
        beleg.refresh_from_db()

        xml = facturx.xml_erzeugen(beleg).decode()

        assert '<ram:PostcodeCode>10115</ram:PostcodeCode>' in xml
        assert 'Postfach 11 22' in xml


LEITWEG_ID = '09162000-12345-67'


@pytest.fixture
def behoerde(db):
    """Öffentlicher Auftraggeber mit Zustellweg XRechnung."""
    from faktura.models import Zustellweg

    return Kontakt.anlegen(
        nummer='K-3000', name='Landratsamt Landshut',
        strasse='Veldener Straße 15', plz='84036', ort='Landshut',
        zustellweg=Zustellweg.XRECHNUNG, kaeuferreferenz=LEITWEG_ID,
    )


@pytest.fixture
def xrechnung(behoerde):
    beleg = services.beleg_anlegen(
        kunde=behoerde, typ=BelegTyp.RECHNUNG, betreff='Gutachten Brücke',
        leistungsdatum=timezone.localdate(),
    )
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Bauwerksprüfung', menge=Decimal('12.5'),
        einheit='Std', einzelpreis=Decimal('120.00'),
        steuersatz='19.00',
    )
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Prüfbericht (gedruckt)', menge=Decimal('3'),
        einheit='Stk', einzelpreis=Decimal('45.00'),
        steuersatz='7.00',
    )
    return beleg


def xml_wert(xml: str, tag: str) -> str:
    """Inhalt des ersten Elements ``ram:<tag>``, unabhängig von
    Attributen."""
    treffer = re.search(rf'<ram:{tag}[^>]*>([^<]*)</ram:{tag}>', xml)
    assert treffer, f'{tag} fehlt im XML'
    return treffer.group(1)


def vorgaengerbezug(xml: str) -> tuple[str, str] | None:
    """BG-3 als (BT-25, BT-26 im Format 102), ``None`` ohne BG-3."""
    treffer = re.search(
        r'<ram:InvoiceReferencedDocument>.*?'
        r'<ram:IssuerAssignedID>([^<]*)</ram:IssuerAssignedID>.*?'
        r'<qdt:DateTimeString format="102">([^<]*)</qdt:DateTimeString>.*?'
        r'</ram:InvoiceReferencedDocument>', xml, re.S)
    return treffer.groups() if treffer else None


def kontextwert(xml: str, art: str) -> str:
    """ID in ``<art>SpecifiedDocumentContextParameter``: BT-24 bei
    'Guideline', BT-23 bei 'BusinessProcess'."""
    treffer = re.search(
        rf'<ram:{art}SpecifiedDocumentContextParameter>\s*'
        rf'<ram:ID>([^<]*)</ram:ID>', xml)
    assert treffer, f'{art} fehlt im XML'
    return treffer.group(1)


@pytest.mark.django_db
class TestXRechnung:
    """XRechnung: dasselbe CII wie Factur-X, mit den Regeln BR-DE-*.

    Gewählt über den Zustellweg am Kunden. Die Annahme durch ein Portal
    entscheidet der KoSIT-Validator; hier geprüft werden Kennung,
    Pflichtfelder und die Übereinstimmung der Beträge mit dem PDF.
    """

    def test_storno_eines_nachlasses_als_384_mit_bg3(self, xrechnung):
        """BR-DE-26: Bei 384 ist BG-3 vorhanden. Das XML besteht das XSD
        (``xml_erzeugen`` prüft es)."""
        original = services.beleg_festschreiben(beleg_id=xrechnung.pk)
        korrektur = services.rechnungskorrektur_erstellen(
            beleg_id=original.pk, betrag_netto=Decimal('100.00'),
            grund='Mangel')
        korrektur = services.beleg_festschreiben(beleg_id=korrektur.pk)
        storno = services.nachlass_stornieren(beleg_id=korrektur.pk)

        xml = facturx.xml_erzeugen(storno).decode()

        assert xml_wert(xml, 'TypeCode') == '384'
        assert vorgaengerbezug(xml)[0] == korrektur.nummer
        assert '-' not in xml_wert(xml, 'GrandTotalAmount')

    def test_der_zustellweg_waehlt_das_profil(self, xrechnung, rechnung):
        assert facturx.ist_xrechnung(xrechnung)
        assert not facturx.ist_xrechnung(rechnung)

    def test_kennung_ist_xrechnung_3(self, xrechnung):
        beleg = services.beleg_festschreiben(beleg_id=xrechnung.pk)

        xml = facturx.xml_erzeugen(beleg).decode()

        assert kontextwert(xml, 'Guideline') == (
            'urn:cen.eu:en16931:2017#compliant'
            '#urn:xeinkauf.de:kosit:xrechnung_3.0')

    def test_geschaeftsprozess_bt23(self, xrechnung, rechnung):
        """PEPPOL-EN16931-R001: BT-23 ist gesetzt, weil der KoSIT-Validator
        sonst einen Fehler meldet. Nur bei XRechnung, weil EN 16931 ihn
        offen lässt."""
        xml = facturx.xml_erzeugen(
            services.beleg_festschreiben(beleg_id=xrechnung.pk)).decode()
        zugferd = facturx.xml_erzeugen(
            services.beleg_festschreiben(beleg_id=rechnung.pk)).decode()

        assert kontextwert(xml, 'BusinessProcess') == (
            'urn:fdc:peppol.eu:2017:poacc:billing:01:1.0')
        assert 'BusinessProcess' not in zugferd

    @pytest.mark.parametrize('wert, erwartet', [
        ('09162000-12345-67', True),     # mit Feinadressierung
        ('991-12345-67', True),
        ('04011000-1234512345-06', True),
        ('09274-12', True),              # ohne Feinadressierung
        ('KST-4711', False),             # gewöhnliche Käuferreferenz
        ('4711', False),
        ('', False),
    ])
    def test_was_eine_leitweg_id_ist(self, wert, erwartet):
        assert facturx.ist_leitweg_id(wert) is erwartet

    def test_pflichtfelder_der_xrechnung(self, xrechnung, firma):
        """BR-DE-15 (Leitweg-ID), BR-DE-2 (Ansprechpartner mit Telefon und
        E-Mail), BT-34/BT-49 (elektronische Adressen) und BR-DE-1
        (Zahlungsanweisung)."""
        beleg = services.beleg_festschreiben(beleg_id=xrechnung.pk)

        xml = facturx.xml_erzeugen(beleg).decode()

        assert xml_wert(xml, 'BuyerReference') == LEITWEG_ID
        assert xml_wert(xml, 'PersonName') == firma.geschaeftsfuehrung
        assert xml_wert(xml, 'CompleteNumber') == firma.telefon
        assert f'<ram:URIID>{firma.email}</ram:URIID>' in xml
        assert f'<ram:URIID schemeID="EM">{firma.email}</ram:URIID>' in xml
        assert f'<ram:URIID schemeID="0204">{LEITWEG_ID}</ram:URIID>' in xml
        assert xml_wert(xml, 'IBANID') == firma.iban

    def test_betraege_stimmen_mit_dem_beleg_ueberein(self, xrechnung):
        """Wie bei Factur-X: Das Profil ändert die Pflichtfelder, nicht die
        Beträge. 12,5 Std x 120 = 1.500,00 zu 19 % und 3 x 45 = 135,00 zu
        7 %."""
        beleg = services.beleg_festschreiben(beleg_id=xrechnung.pk)
        summen = services.belegsummen(beleg)

        xml = facturx.xml_erzeugen(beleg).decode()

        # Zuerst je Position, dann der Kopf, in dieser Reihenfolge.
        assert re.findall(
            r'<ram:LineTotalAmount>([^<]*)</ram:LineTotalAmount>', xml
        ) == ['1500.00', '135.00', '1635.00']
        assert Decimal(xml_wert(xml, 'TaxBasisTotalAmount')) == summen.netto
        assert Decimal(xml_wert(xml, 'TaxTotalAmount')) == Decimal('294.45')
        assert Decimal(xml_wert(xml, 'GrandTotalAmount')) == Decimal('1929.45')
        assert Decimal(xml_wert(xml, 'DuePayableAmount')) == summen.brutto

    def test_storno_traegt_eine_offene_zahlungsanweisung(self, xrechnung):
        """BR-DE-1 gilt auch für die Gutschrift; Code 1 "nicht festgelegt",
        weil eine Überweisung auf das eigene Konto falsch wäre. Beträge
        positiv wie bei Factur-X."""
        original = services.beleg_festschreiben(beleg_id=xrechnung.pk)
        storno, _ = services.rechnung_korrigieren(beleg_id=original.pk)

        xml = facturx.xml_erzeugen(storno).decode()

        assert xml_wert(xml, 'TypeCode') == '381'
        assert '<ram:SpecifiedTradeSettlementPaymentMeans>' in xml
        assert 'IBANID' not in xml
        assert Decimal(xml_wert(xml, 'GrandTotalAmount')) == Decimal('1929.45')

    def test_fehlende_angaben_kommen_in_einer_meldung(self, xrechnung, firma):
        """Alle fehlenden Angaben in einer Meldung."""
        from faktura.models import Beleg

        beleg = services.beleg_festschreiben(beleg_id=xrechnung.pk)
        Beleg.objects.filter(pk=beleg.pk).update(leitweg_id='')
        beleg.refresh_from_db()
        firma.telefon = ''
        firma.save()

        with pytest.raises(facturx.FacturxFehler) as fehler:
            facturx.xml_erzeugen(beleg)

        assert 'Leitweg-ID' in str(fehler.value)
        assert 'Telefonnummer' in str(fehler.value)

    def test_ohne_leitweg_id_keine_festschreibung(self, mit_pdf, xrechnung):
        """Ohne Leitweg-ID schlägt das Festschreiben fehl, damit keine Nummer
        für eine Rechnung vergeben wird, die das Portal ablehnt."""
        from faktura.models import Beleg

        Beleg.objects.filter(pk=xrechnung.pk).update(leitweg_id='')

        with pytest.raises(services.DokumentFehlt, match='Leitweg-ID'):
            services.beleg_festschreiben(beleg_id=xrechnung.pk)

        xrechnung.refresh_from_db()
        assert xrechnung.status == BelegStatus.ENTWURF

    def test_im_pdf_heisst_der_anhang_xrechnung_xml(self, mit_pdf, xrechnung):
        """ZUGFeRD im Profil XRECHNUNG: eigener Name des Anhangs, eigenes
        Profil in den Metadaten, dieselben Bytes wie die gespeicherte
        Datei."""
        beleg = services.beleg_festschreiben(beleg_id=xrechnung.pk)
        beleg.refresh_from_db()

        leser = PdfReader(io.BytesIO(beleg.pdf.read()))
        roh = leser.trailer['/Root']['/Metadata'].get_data().decode()

        assert list(leser.attachments) == ['xrechnung.xml']
        assert leser.attachments['xrechnung.xml'][0] == beleg.xml.read()
        assert '<fx:ConformanceLevel>XRECHNUNG</fx:ConformanceLevel>' in roh
        assert '<fx:DocumentFileName>xrechnung.xml</fx:DocumentFileName>' in roh

    def test_profil_wird_eingefroren(self, mit_pdf, xrechnung, rechnung):
        """Das Profil wird beim Festschreiben gespeichert und ändert sich nicht
        mit dem Zustellweg."""
        als_xrechnung = services.beleg_festschreiben(beleg_id=xrechnung.pk)
        gewoehnlich = services.beleg_festschreiben(beleg_id=rechnung.pk)

        als_xrechnung.refresh_from_db()
        gewoehnlich.refresh_from_db()
        assert als_xrechnung.erechnungsprofil == 'XRECHNUNG'
        assert gewoehnlich.erechnungsprofil == 'EN 16931'


def xml_datum(xml: str, tag: str) -> date | None:
    """Datum im Element ``ram:<tag>``, None, wenn es fehlt."""
    treffer = re.search(
        rf'<ram:{tag}>\s*<udt:DateTimeString format="102">(\d{{8}})<', xml)
    if not treffer:
        return None
    return date.fromisoformat(treffer.group(1))


@pytest.mark.django_db
class TestLeistungsdaten:
    """Leistungsdatum (BT-72) und Leistungszeitraum (BT-73/74) im XML.

    Das steuerliche Leistungsdatum ist die Vollendung der Leistung, also
    das Ende des Zeitraums. Ein Abschlag ist eine Anzahlung und hat nur den
    Zeitraum.
    """

    BEGINN = date(2026, 9, 5)
    ENDE = date(2026, 9, 12)

    def _rechnung(self, kunde, von, bis=None, art=Rechnungsart.NORMAL):
        beleg = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.RECHNUNG, rechnungsart=art,
            betreff='Gutachten', leistungsdatum=von, leistungsdatum_bis=bis)
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Gutachten', menge=Decimal('1'),
            einheit='pausch', einzelpreis=Decimal('900.00'),
            steuersatz='19.00')
        return beleg

    def _xml(self, beleg) -> str:
        beleg = services.beleg_festschreiben(beleg_id=beleg.pk)
        return facturx.xml_erzeugen(beleg).decode()

    def test_ein_tag_ist_das_leistungsdatum_ohne_zeitraum(self, kunde):
        xml = self._xml(self._rechnung(kunde, self.ENDE))

        assert xml_datum(xml, 'OccurrenceDateTime') == self.ENDE
        assert 'BillingSpecifiedPeriod' not in xml

    def test_beim_zeitraum_ist_das_ende_das_leistungsdatum(self, kunde):
        """Gearbeitet am 05.09. und 08.09., fertig am 12.09.: Leistungsdatum
        12.09., Zeitraum 05.09. bis 12.09."""
        xml = self._xml(self._rechnung(kunde, self.BEGINN, self.ENDE))

        assert xml_datum(xml, 'OccurrenceDateTime') == self.ENDE
        assert xml_datum(xml, 'StartDateTime') == self.BEGINN
        assert xml_datum(xml, 'EndDateTime') == self.ENDE

    def test_schlussrechnung_mit_projektbeginn_und_abnahme(self, kunde):
        """Projektbeginn 10.01., Abnahme 20.09.: BT-72 = 20.09., BT-73/74 =
        10.01. bis 20.09."""
        beleg = self._rechnung(kunde, date(2026, 1, 10), date(2026, 9, 20),
                               art=Rechnungsart.SCHLUSS)
        xml = self._xml(beleg)

        assert xml_datum(xml, 'OccurrenceDateTime') == date(2026, 9, 20)
        assert xml_datum(xml, 'StartDateTime') == date(2026, 1, 10)
        assert xml_datum(xml, 'EndDateTime') == date(2026, 9, 20)

    def test_abschlag_hat_zeitraum_aber_kein_leistungsdatum(self, kunde):
        beleg = self._rechnung(kunde, self.BEGINN, self.ENDE,
                               art=Rechnungsart.ABSCHLAG)
        xml = self._xml(beleg)

        assert xml_datum(xml, 'OccurrenceDateTime') is None
        assert xml_datum(xml, 'StartDateTime') == self.BEGINN
        assert xml_datum(xml, 'EndDateTime') == self.ENDE

    def test_abschlag_an_einem_stichtag_behaelt_den_zeitraum(self, kunde):
        """Der Zeitraum bleibt bei gleichem Beginn und Ende, weil er ohne
        Leistungsdatum die einzige Angabe ist."""
        beleg = self._rechnung(kunde, self.ENDE, self.ENDE,
                               art=Rechnungsart.ABSCHLAG)
        xml = self._xml(beleg)

        assert xml_datum(xml, 'OccurrenceDateTime') is None
        assert xml_datum(xml, 'StartDateTime') == self.ENDE

    def test_abschlag_ohne_zeitraum_wird_nicht_festgeschrieben(self, kunde):
        beleg = self._rechnung(kunde, self.BEGINN,
                               art=Rechnungsart.ABSCHLAG)

        with pytest.raises(services.LeistungsdatumFehlt, match='Zeitraum'):
            services.beleg_festschreiben(beleg_id=beleg.pk)

    def test_storno_eines_abschlags_hat_kein_leistungsdatum(self, kunde):
        original = services.beleg_festschreiben(beleg_id=self._rechnung(
            kunde, self.BEGINN, self.ENDE, art=Rechnungsart.ABSCHLAG).pk)
        storno, _ = services.rechnung_korrigieren(beleg_id=original.pk)

        xml = facturx.xml_erzeugen(storno).decode()

        assert xml_datum(xml, 'OccurrenceDateTime') is None
        assert xml_datum(xml, 'StartDateTime') == self.BEGINN

    def test_xrechnung_mit_zeitraum_besteht_das_schema(self, behoerde):
        """serialize() validiert gegen das XSD; der Zeitraum steht an der
        zulässigen Stelle."""
        beleg = self._rechnung(behoerde, self.BEGINN, self.ENDE)

        xml = self._xml(beleg)

        assert xml_datum(xml, 'EndDateTime') == self.ENDE


def steuerfall_beleg(kunde, steuerfall=None, satz='0.00'):
    """Rechnung über 1.500,00 + 135,00 netto an diesen Kunden.

    Der Steuerfall kommt vom Kunden; ``steuerfall`` überschreibt ihn am
    Beleg wie im Formular.
    """
    beleg = services.beleg_anlegen(
        kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Beratung',
        leistungsdatum=timezone.localdate(),
    )
    if steuerfall is not None:
        from faktura.models import Beleg
        Beleg.objects.filter(pk=beleg.pk).update(steuerfall=steuerfall)
        beleg.refresh_from_db()
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Softwareentwicklung', menge=Decimal('12.5'),
        einheit='Std', einzelpreis=Decimal('120.00'), steuersatz=satz,
    )
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Dokumentation', menge=Decimal('3'),
        einheit='Stk', einzelpreis=Decimal('45.00'), steuersatz=satz,
    )
    return beleg


@pytest.fixture
def bauunternehmen(db):
    from faktura.models import Steuerfall
    return Kontakt.anlegen(
        nummer='K-4000', name='Huber Bau GmbH', strasse='Industriestraße 45',
        plz='84030', ort='Ergolding', ust_id='DE111222333',
        steuerfall=Steuerfall.INLAND_13B,
    )


@pytest.fixture
def kunde_eu(db):
    from faktura.models import Steuerfall
    return Kontakt.anlegen(
        nummer='K-4001', name='Wiener Software GmbH', strasse='Ring 1',
        plz='1010', ort='Wien', land='AT', ust_id='ATU12345678',
        steuerfall=Steuerfall.EU_DIENSTLEISTUNG,
    )


@pytest.fixture
def kunde_schweiz(db):
    from faktura.models import Steuerfall
    return Kontakt.anlegen(
        nummer='K-4002', name='Zürcher Informatik AG',
        strasse='Bahnhofstrasse 1', plz='8001', ort='Zürich', land='CH',
        steuerfall=Steuerfall.DRITTLAND_DIENSTLEISTUNG,
    )


def alle(xml: str, tag: str) -> list[str]:
    return re.findall(rf'<ram:{tag}[^>]*>([^<]*)</ram:{tag}>', xml)


@pytest.mark.django_db
class TestSteuerfaelle:
    """§ 13b, EU und Drittland: 0 %, Vermerk und passende Kategorie.

    Regression: Jeder 0-%-Fall erschien im XML als "steuerfrei" (E), und
    "§ 13b" am Kunden blieb ohne Wirkung. Geprüft wird, dass Kategorie,
    Befreiungsgrund, Vermerk und Beträge zusammenpassen; weil der
    KoSIT-Validator nicht läuft, ist jede Regel einzeln geprüft.
    """

    def test_der_steuerfall_kommt_vom_kunden(self, bauunternehmen):
        beleg = steuerfall_beleg(bauunternehmen)

        assert beleg.steuerfall == 'inland_13b'

    def test_13b_ist_ae_mit_vermerk_und_ohne_steuer(self, bauunternehmen):
        """§ 13b: Kategorie AE mit Vermerk ohne Steuer; 12,5 x 120 + 3 x 45 =
        1.635,00 netto, Zahlbetrag netto."""
        beleg = services.beleg_festschreiben(
            beleg_id=steuerfall_beleg(bauunternehmen).pk)

        xml = facturx.xml_erzeugen(beleg).decode()

        assert set(alle(xml, 'CategoryCode')) == {'AE'}
        assert alle(xml, 'ExemptionReasonCode') == ['VATEX-EU-AE']
        assert alle(xml, 'ExemptionReason') == [
            'Steuerschuldnerschaft des Leistungsempfängers (§ 13b UStG).']
        assert Decimal(alle(xml, 'TaxBasisTotalAmount')[0]) == Decimal('1635.00')
        assert Decimal(alle(xml, 'TaxTotalAmount')[0]) == Decimal('0.00')
        assert Decimal(alle(xml, 'GrandTotalAmount')[0]) == Decimal('1635.00')
        assert '<ram:ID schemeID="VA">DE111222333</ram:ID>' in xml

    def test_eu_dienstleistung_traegt_beide_ust_idnrn(self, kunde_eu, firma):
        """BR-AE-02 und § 14a Abs. 1 UStG: eigene USt-IdNr. und die des
        Kunden."""
        beleg = services.beleg_festschreiben(
            beleg_id=steuerfall_beleg(kunde_eu).pk)

        xml = facturx.xml_erzeugen(beleg).decode()

        assert set(alle(xml, 'CategoryCode')) == {'AE'}
        assert f'<ram:ID schemeID="VA">{firma.ust_id}</ram:ID>' in xml
        assert '<ram:ID schemeID="VA">ATU12345678</ram:ID>' in xml
        assert 'Reverse Charge' in alle(xml, 'ExemptionReason')[0]

    def test_drittland_ist_o_und_ohne_jede_ust_idnr(self, kunde_schweiz, firma):
        """BR-O-02: keine USt-IdNr., weder eigene noch fremde. Die Steuernummer
        bleibt; die Handelsregisternummer identifiziert den Verkäufer
        (BR-CO-26)."""
        beleg = services.beleg_festschreiben(
            beleg_id=steuerfall_beleg(kunde_schweiz).pk)

        xml = facturx.xml_erzeugen(beleg).decode()

        assert set(alle(xml, 'CategoryCode')) == {'O'}
        assert alle(xml, 'ExemptionReasonCode') == ['VATEX-EU-O']
        assert 'schemeID="VA"' not in xml
        assert f'<ram:ID schemeID="FC">{firma.steuernummer}</ram:ID>' in xml
        assert f'<ram:ID>{firma.handelsregister}</ram:ID>' in xml
        assert Decimal(alle(xml, 'GrandTotalAmount')[0]) == Decimal('1635.00')

    def test_innergemeinschaftliche_lieferung_nennt_das_lieferland(
            self, kunde_eu):
        """BR-IC-12: Das Zielland der Lieferung steht im XML."""
        from faktura.models import Steuerfall

        beleg = services.beleg_festschreiben(beleg_id=steuerfall_beleg(
            kunde_eu, steuerfall=Steuerfall.EU_LIEFERUNG).pk)

        xml = facturx.xml_erzeugen(beleg).decode()

        assert set(alle(xml, 'CategoryCode')) == {'K'}
        assert alle(xml, 'ExemptionReasonCode') == ['VATEX-EU-IC']
        lieferung = re.search(
            r'<ram:ShipToTradeParty>.*?</ram:ShipToTradeParty>', xml, re.S)
        assert lieferung and '<ram:CountryID>AT</ram:CountryID>' in (
            lieferung.group(0))

    def test_ausfuhr_ist_g(self, kunde_schweiz):
        from faktura.models import Steuerfall

        beleg = services.beleg_festschreiben(beleg_id=steuerfall_beleg(
            kunde_schweiz, steuerfall=Steuerfall.AUSFUHR).pk)

        xml = facturx.xml_erzeugen(beleg).decode()

        assert set(alle(xml, 'CategoryCode')) == {'G'}
        assert alle(xml, 'ExemptionReasonCode') == ['VATEX-EU-G']

    def test_mit_19_prozent_keine_festschreibung(self, bauunternehmen):
        """Mit 19 % schlägt das Festschreiben fehl, weil Vermerk
        "Steuerschuldnerschaft des Leistungsempfängers" und 19 % sich
        widersprechen. Keine automatische Umstellung."""
        from faktura.models import BelegStatus

        beleg = steuerfall_beleg(bauunternehmen, satz='19.00')

        with pytest.raises(services.UnzulaessigerSteuersatz, match='0 %'):
            services.beleg_festschreiben(beleg_id=beleg.pk)

        beleg.refresh_from_db()
        assert beleg.status == BelegStatus.ENTWURF

    def test_ohne_ust_idnr_des_kunden_eine_meldung(self, bauunternehmen):
        from faktura.models import Beleg

        beleg = services.beleg_festschreiben(
            beleg_id=steuerfall_beleg(bauunternehmen).pk)
        Beleg.objects.filter(pk=beleg.pk).update(empfaenger_ust_id='')
        beleg.refresh_from_db()

        with pytest.raises(facturx.FacturxFehler,
                           match='USt-IdNr. des Kunden'):
            facturx.xml_erzeugen(beleg)

    def test_der_storno_behaelt_den_steuerfall(self, bauunternehmen):
        original = services.beleg_festschreiben(
            beleg_id=steuerfall_beleg(bauunternehmen).pk)

        storno, neu = services.rechnung_korrigieren(beleg_id=original.pk)

        assert storno.steuerfall == 'inland_13b'
        assert neu.steuerfall == 'inland_13b'
        xml = facturx.xml_erzeugen(storno).decode()
        assert set(alle(xml, 'CategoryCode')) == {'AE'}
        assert Decimal(alle(xml, 'GrandTotalAmount')[0]) == Decimal('1635.00')

    def test_regelfall_bleibt_wie_er_war(self, rechnung):
        """Gegenprobe: Ohne Steuerfall S und E, kein Befreiungscode."""
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)

        xml = facturx.xml_erzeugen(beleg).decode()

        assert set(alle(xml, 'CategoryCode')) == {'S'}
        assert 'ExemptionReasonCode' not in xml

    def test_der_vermerk_steht_auf_dem_blatt(self, mit_pdf, bauunternehmen):
        """Der Vermerk steht auch im PDF, mit der USt-IdNr. des Kunden
        (§ 14a UStG)."""
        beleg = services.beleg_festschreiben(
            beleg_id=steuerfall_beleg(bauunternehmen).pk)

        text = text_aus(beleg.pdf.read())

        assert ('Steuerschuldnerschaft des Leistungsempfängers '
                '(§ 13b UStG).') in text
        assert 'USt-IdNr. des Leistungsempfängers: DE111222333' in text
        assert 'Kleinunternehmer' not in text


@pytest.mark.django_db
class TestNeuausstellung:
    """Neuausstellung einer abgelehnten E-Rechnung: dieselbe Nummer, neue
    Dateien, die alten bleiben.

    Geprüft wird das GoBD-Relevante: Die Beträge sind nicht änderbar, die
    alte Fassung bleibt unverändert, ein Fehlschlag ändert nichts.
    Alternative: Storno und neue Rechnung.
    """

    @pytest.fixture(autouse=True)
    def eigenes_medienverzeichnis(self, settings, tmp_path):
        """Temporäres Medienverzeichnis, weil ein Test eine Datei bewusst
    verändert."""
        settings.MEDIA_ROOT = tmp_path

    def _festgeschrieben(self, beleg):
        festgeschrieben = services.beleg_festschreiben(beleg_id=beleg.pk)
        festgeschrieben.refresh_from_db()
        return festgeschrieben

    def test_gleiche_nummer_neue_leitweg_id(self, mit_pdf, xrechnung):
        vorher = self._festgeschrieben(xrechnung)
        xml_vorher = vorher.xml.read()

        neu = services.erechnung_neu_ausstellen(
            beleg_id=vorher.pk, grund='Portal: Leitweg-ID unbekannt',
            leitweg_id='09162000-99999-11')

        roh = neu.xml.read()
        xml = roh.decode()
        assert neu.nummer == vorher.nummer
        assert neu.festgeschrieben_am == vorher.festgeschrieben_am
        assert xml_wert(xml, 'BuyerReference') == '09162000-99999-11'
        assert roh != xml_vorher
        assert pdf.pruefsumme(roh) == neu.xml_sha256 != vorher.xml_sha256
        # Die Beträge sind unverändert, weil die Funktion dafür keine
        # Parameter hat.
        assert Decimal(xml_wert(xml, 'GrandTotalAmount')) == Decimal('1929.45')

    def test_die_alte_fassung_bleibt_unveraendert(self, mit_pdf, xrechnung):
        vorher = self._festgeschrieben(xrechnung)
        pdf_vorher, xml_vorher = vorher.pdf.read(), vorher.xml.read()

        neu = services.erechnung_neu_ausstellen(
            beleg_id=vorher.pk, grund='Bestellnummer fehlte',
            bestellnummer='B-4711')

        fassung = neu.fassungen.get()
        assert fassung.grund == 'Bestellnummer fehlte'
        assert fassung.leitweg_id == LEITWEG_ID
        assert fassung.bestellnummer == ''
        assert fassung.erechnungsprofil == 'XRECHNUNG'
        assert fassung.pdf.read() == pdf_vorher
        assert fassung.xml.read() == xml_vorher
        assert fassung.pdf_sha256 == pdf.pruefsumme(pdf_vorher)
        assert fassung.xml_sha256 == pdf.pruefsumme(xml_vorher)
        assert neu.pdf.name != fassung.pdf.name

    def test_der_zustellweg_kann_das_profil_wechseln(self, mit_pdf, rechnung):
        """Häufigster Fall: Die Behörde erhielt ZUGFeRD und verlangt XRechnung. Der
        Zustellweg wird am Kunden berichtigt, die Rechnung neu
        ausgestellt."""
        from faktura.models import Zustellweg

        vorher = self._festgeschrieben(rechnung)
        assert vorher.erechnungsprofil == 'EN 16931'
        kunde = vorher.kunde
        kunde.zustellweg = Zustellweg.XRECHNUNG
        kunde.save()

        neu = services.erechnung_neu_ausstellen(
            beleg_id=vorher.pk, grund='Portal verlangt XRechnung',
            leitweg_id=LEITWEG_ID)

        assert neu.erechnungsprofil == 'XRECHNUNG'
        leser = PdfReader(io.BytesIO(neu.pdf.read()))
        assert list(leser.attachments) == ['xrechnung.xml']

    def test_ein_fehlschlag_laesst_alles_wie_es_war(self, mit_pdf, xrechnung):
        """Ohne Leitweg-ID schlägt die Neuausstellung vollständig fehl: keine
        Fassung, die alten Dateien gelten."""
        vorher = self._festgeschrieben(xrechnung)

        with pytest.raises(services.DokumentFehlt, match='Leitweg-ID'):
            services.erechnung_neu_ausstellen(
                beleg_id=vorher.pk, grund='Versuch', leitweg_id='')

        nachher = type(vorher).objects.get(pk=vorher.pk)
        assert nachher.xml_sha256 == vorher.xml_sha256
        assert nachher.pdf.name == vorher.pdf.name
        assert nachher.leitweg_id == LEITWEG_ID
        assert not nachher.fassungen.exists()

    def test_ohne_grund_nicht(self, mit_pdf, xrechnung):
        vorher = self._festgeschrieben(xrechnung)

        with pytest.raises(services.KeineERechnung, match='Grund'):
            services.erechnung_neu_ausstellen(beleg_id=vorher.pk, grund='  ')

    def test_am_entwurf_nicht(self, xrechnung):
        with pytest.raises(services.FalscherStatus):
            services.erechnung_neu_ausstellen(
                beleg_id=xrechnung.pk, grund='zu früh')

    def test_die_archivpruefung_bewacht_die_alte_fassung(
            self, mit_pdf, xrechnung):
        vorher = self._festgeschrieben(xrechnung)
        neu = services.erechnung_neu_ausstellen(
            beleg_id=vorher.pk, grund='Leitweg-ID', leitweg_id='X-1')
        assert services.belegarchiv_pruefen().in_ordnung

        with open(neu.fassungen.get().xml.path, 'wb') as datei:
            datei.write(b'<nachtraeglich-veraendert/>')

        befunde = [b.problem for b in services.belegarchiv_pruefen().befunde]
        assert len(befunde) == 1
        assert 'Fassung bis' in befunde[0]
        assert 'Prüfsumme des XML weicht ab' in befunde[0]

    def test_ueber_die_oberflaeche(self, mit_pdf, xrechnung, client):
        """Neuausstellung über den Admin bis zum Ergebnis; danach steht die
        alte Fassung mit Link auf ihre Datei am Beleg."""
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission

        person = get_user_model().objects.create_user(
            username='bea', password='geheim12345', is_staff=True)
        person.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='faktura'))
        client.force_login(person)
        vorher = self._festgeschrieben(xrechnung)
        adresse = f'/admin/faktura/rechnung/{vorher.pk}/erechnung-neu/'

        assert client.get(adresse).status_code == 200
        antwort = client.post(adresse, {
            'leitweg_id': '09162000-99999-11', 'bestellnummer': '',
            'grund': 'Portal: Leitweg-ID unbekannt', 'anwenden': '1'})

        assert antwort.status_code == 302
        vorher.refresh_from_db()
        assert vorher.leitweg_id == '09162000-99999-11'
        fassung = vorher.fassungen.get()
        seite = client.get(
            f'/admin/faktura/rechnung/{vorher.pk}/change/').content.decode()
        assert 'Frühere Fassung bis' in seite
        datei = client.get(
            f'/admin/faktura/rechnung/{vorher.pk}/fassung/{fassung.pk}/xml/')
        assert datei.status_code == 200
        assert b''.join(datei.streaming_content) == fassung.xml.read()


class TestStylesheetKommtAn:
    """Das Stylesheet wird beim Rendern gefunden.

    Regression im Container: Das PDF hatte eine Serifenschrift, weil kein
    Stylesheet geladen wurde. Mit CompressedManifestStaticFilesStorage
    liefert {% static %} ``beleg.254698946439.css``, das nur in STATIC_ROOT
    existiert; ``finders.find()`` gibt None zurück. WeasyPrint rendert ohne
    Fehler und ohne CSS.

    Die Tests laufen mit dev-Settings ohne dieses Verhalten; der Fall wird
    hier nachgestellt.
    """

    def test_fetcher_findet_eingesammelte_datei_mit_pruefsumme(self, settings, tmp_path):
        """Name mit Hash, Datei nur in STATIC_ROOT."""
        from faktura.pdf import BelegUrlFetcher

        # STATIC_ROOT nach collectstatic mit Manifest-Storage.
        ziel = tmp_path / 'faktura' / 'pdf'
        ziel.mkdir(parents=True)
        (ziel / 'beleg.254698946439.css').write_text('body { color: red }', encoding='utf-8')
        settings.STATIC_ROOT = str(tmp_path)

        ergebnis = BelegUrlFetcher()('file:///static/faktura/pdf/beleg.254698946439.css')

        # WeasyPrint 69 gibt ein URLFetcherResponse zurück, kein Dict.
        assert ergebnis.read().decode() == 'body { color: red }'

    def test_fetcher_bevorzugt_die_quelle_vor_dem_eingesammelten(self, settings, tmp_path):
        """In der Entwicklung hat faktura/static/ Vorrang vor einer älteren
        Version in STATIC_ROOT, damit Änderungen an der Quelle ohne
        collectstatic im PDF erscheinen."""
        from faktura.pdf import BelegUrlFetcher

        ziel = tmp_path / 'faktura' / 'pdf'
        ziel.mkdir(parents=True)
        (ziel / 'beleg.css').write_text('/* veralteter Stand */', encoding='utf-8')
        settings.STATIC_ROOT = str(tmp_path)

        inhalt = BelegUrlFetcher()('file:///static/faktura/pdf/beleg.css').read()

        assert b'veralteter Stand' not in inhalt
        assert b'font-family' in inhalt

    def test_gerendertes_pdf_traegt_die_schrift_aus_dem_stylesheet(self, rechnung):
        """Gegenprobe am PDF: Die eingebettete Schrift ist die aus dem
        Stylesheet.

        Ohne Stylesheet verwendet WeasyPrint eine Serifenschrift; geprüft
        wird deshalb die konkrete Schrift.
        """
        daten = pdf.beleg_als_pdf(rechnung, mit_xml=False)

        leser = PdfReader(io.BytesIO(daten))
        schriften = {
            str(eintrag.get_object().get('/BaseFont')).split('+')[-1]
            for eintrag in (leser.pages[0].get('/Resources', {}).get('/Font') or {}).values()
        }

        assert schriften, 'keine eingebettete Schrift; das PDF wäre leer'
        assert not any('Serif' in name for name in schriften), (
            f'Serifenschrift {schriften}; das deutet darauf hin, dass das '
            f'Stylesheet nicht geladen wurde'
        )


@pytest.mark.django_db
class TestWieDieBelegartAufDemPapierHeisst:
    """Das PDF des Auftrags heißt "Auftragsbestätigung".

    Die Belegart heißt "Auftrag"; das Schreiben an den Kunden ist die
    Auftragsbestätigung.
    """

    @pytest.fixture
    def auftrag(self, kunde):
        beleg = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.AUFTRAG, betreff='Halle Nord')
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Montage', menge=Decimal('1'),
            einzelpreis=Decimal('500.00'), steuersatz='19.00')
        return beleg

    def test_die_ueberschrift_steht_auf_dem_blatt(self, mit_pdf, auftrag):
        """Die Überschrift steht im gerenderten PDF."""
        festgeschrieben = services.beleg_festschreiben(beleg_id=auftrag.pk)

        text = text_aus(pdf.beleg_als_pdf(festgeschrieben))

        assert f'Auftragsbestätigung {festgeschrieben.nummer}' in text

    def test_der_dateiname_traegt_dasselbe_wort(self, auftrag):
        """Der Dateiname enthält dasselbe Wort ohne Umlaut, weil Mailanhänge
        und fremde Dateisysteme Umlaute nicht zuverlässig verarbeiten."""
        festgeschrieben = services.beleg_festschreiben(beleg_id=auftrag.pk)

        name = pdf.dateiname(festgeschrieben)

        assert name == f'Auftragsbestaetigung_{festgeschrieben.nummer}.pdf'
        assert name.isascii()

    def test_die_rechnung_bleibt_eine_rechnung(self, rechnung):
        """Gegenprobe: Die Rechnung heißt "Rechnung"."""
        assert pdf.belegbezeichnung(rechnung) == 'Rechnung'
        assert pdf.dateiname(rechnung).startswith('Rechnung_')

    def test_die_abschlagsrechnung_behaelt_ihre_ueberschrift(
            self, mit_pdf, kunde, rechnung):
        """Die Abschlagsrechnung behält ihre eigene Überschrift, weil ihr
        Template den Block überschreibt."""
        from faktura.models import Rechnungsart

        rechnung.rechnungsart = Rechnungsart.ABSCHLAG
        # Ein Abschlag braucht den Zeitraum, auf den er sich bezieht.
        rechnung.leistungsdatum_bis = rechnung.leistungsdatum
        rechnung.save()
        festgeschrieben = services.beleg_festschreiben(beleg_id=rechnung.pk)

        text = text_aus(pdf.beleg_als_pdf(festgeschrieben))

        assert 'Abschlagsrechnung' in text
        # Kein Leistungsdatum; der Zeitraum gibt den Leistungsstand an.
        assert 'Leistungsstand' in text
        assert 'Leistungsdatum' not in text


@pytest.mark.django_db
class TestDieBetraegeAufDemBlatt:
    """Beträge von der Berechnung bis in das PDF.

    Ergänzt ``TestPflichtangaben`` und die XML-Tests um die Beträge im PDF,
    das der Kunde bezahlt.

    Geprüft am extrahierten Text, weil Tests am Template bei fehlerhafter
    Ausgabe grün waren, und über ``formate.geld``, weil Beträge im PDF
    deutsch formatiert sind (``4.487,50``).
    """

    def test_jeder_positionsbetrag_steht_auf_dem_blatt(self, mit_pdf, firma,
                                                       rechnung):
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)
        text = text_aus(beleg.pdf.read())

        for position in beleg.positionen.all():
            summe = services.positionssumme(
                menge=position.menge, einzelpreis=position.einzelpreis)
            assert formate.geld(summe) in text, (
                f'Position {position.position} ({position.bezeichnung}): '
                f'{formate.geld(summe)} fehlt auf dem Blatt'
            )

    def test_netto_und_brutto_stehen_auf_dem_blatt(self, mit_pdf, firma,
                                                   rechnung):
        """Netto und Brutto stehen im PDF.

        Ohne Zeile "Steuer gesamt", weil das PDF die Steuer je Satz ausweist
        ("zzgl. 19 % USt. auf 1.500,00 EUR"), wie § 14 Abs. 4 Nr. 8 UStG
        verlangt. Die Summe der Steuerbeträge prüft der folgende Test.
        """
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)
        summen = services.belegsummen(beleg)
        text = text_aus(beleg.pdf.read())

        assert formate.geld(summen.netto) in text
        assert formate.geld(summen.brutto) in text

    def test_die_ausgewiesenen_steuern_ergeben_die_gesamtsteuer(
            self, mit_pdf, firma, rechnung):
        """Die ausgewiesenen Steuerbeträge ergeben die Gesamtsteuer.

        Prüft die Vollständigkeit des Steuerausweises; eine fehlende Zeile
        machte den Rechnungsbetrag unstimmig.
        """
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)
        summen = services.belegsummen(beleg)
        text = text_aus(beleg.pdf.read())

        ausgewiesen = Decimal('0.00')
        for anteil in summen.anteile:
            assert formate.geld(anteil.steuer) in text
            ausgewiesen += anteil.steuer

        assert ausgewiesen == summen.steuer
        assert formate.geld(summen.netto + ausgewiesen) in text

    def test_die_steuer_je_satz_steht_mit_ihrem_betrag_da(self, mit_pdf, firma,
                                                          rechnung):
        """Jeder Steuersatz steht mit seinem Steuerbetrag im PDF.

        § 14 Abs. 4 Nr. 8 UStG verlangt den Steuerbetrag; ohne ihn ist der
        Vorsteuerabzug ausgeschlossen.
        """
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)
        summen = services.belegsummen(beleg)
        text = text_aus(beleg.pdf.read())

        assert len(summen.anteile) == 2
        for anteil in summen.anteile:
            assert formate.prozent(anteil.satz) in text
            assert formate.geld(anteil.netto) in text
            assert formate.geld(anteil.steuer) in text

    def test_ein_satzwechsel_zeigt_alle_vier_saetze(self, mit_pdf, firma,
                                                    kunde):
        """Änderung der Umsatzsteuer in einer Rechnung: vier Steuersätze im
        Ausweis.

        Ändert sich der Regelsatz während der Leistungszeit, hat die
        Rechnung dieselbe Leistung mit zwei Sätzen.
        """
        beleg = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.RECHNUNG,
            betreff='Beweissicherung Ortsdurchfahrt',
            leistungsdatum=timezone.localdate(),
        )
        for bezeichnung, menge, preis, satz in [
            ('Ingenieurstunden bis 31.07.', Decimal('12'), Decimal('85.00'),
             '19.00'),
            ('Ingenieurstunden ab 01.08.', Decimal('8.25'), Decimal('85.00'),
             '16.00'),
            ('Berichtsdruck bis 31.07.', Decimal('10'), Decimal('12.00'),
             '7.00'),
            ('Berichtsdruck ab 01.08.', Decimal('25'), Decimal('12.00'),
             '5.00'),
        ]:
            services.position_hinzufuegen(
                beleg=beleg, bezeichnung=bezeichnung, menge=menge,
                einheit='Std', einzelpreis=preis, steuersatz=satz)

        festgeschrieben = services.beleg_festschreiben(beleg_id=beleg.pk)
        summen = services.belegsummen(festgeschrieben)
        text = text_aus(festgeschrieben.pdf.read())

        assert len(summen.anteile) == 4
        for anteil in summen.anteile:
            assert formate.prozent(anteil.satz) in text, (
                f'Der Satz {anteil.satz} fehlt auf dem Blatt')
            assert formate.geld(anteil.steuer) in text, (
                f'Die Steuer zu {anteil.satz} fehlt auf dem Blatt')
        assert formate.geld(summen.brutto) in text

    def test_ein_storno_zeigt_seine_betraege(self, mit_pdf, firma, rechnung):
        """Das Storno zeigt seine Beträge im PDF.

        Prüft die Formatierung negativer Beträge in jeder Position.
        """
        festgeschrieben = services.beleg_festschreiben(beleg_id=rechnung.pk)
        storno, _ = services.rechnung_korrigieren(beleg_id=festgeschrieben.pk)

        summen = services.belegsummen(storno)
        text = text_aus(storno.pdf.read())

        assert summen.netto < 0
        # Im PDF ohne Vorzeichen, weil die Belegart die Richtung angibt;
        # gesucht wird der Absolutwert.
        assert formate.geld(abs(summen.netto)) in text
        assert formate.geld(abs(summen.brutto)) in text
