"""Einlesen von E-Rechnungen vom XML bis zur Maske.

* **Parser** (``erechnung.lesen``): ein vollständiges CII-Dokument und jede
  Art ungeeigneter Datei.
* **Service** (``services.eingangsrechnung_aus_xml``): angelegte Datensätze
  und Ablehnungen.
* **Maske:** Upload einer echten Datei über den Client, weil ein Test, der
  nur den Button im HTML findet, eine defekte View nicht erkennt.
"""

import re
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse
from drafthorse.pdf import attach_xml
from pypdf import PdfWriter

from erfassung import erechnung
from erfassung.models import Eingangsrechnung, Fremdleistung
from erfassung.services import RechnungBereitsErfasst, eingangsrechnung_aus_xml
from faktura.models import Kontakt

#: Beispieldateien, die auch für manuelle Tests dienen.
BEISPIELE = Path(__file__).resolve().parents[2] / 'beispiele' / 'e-rechnung'

# ══════════════════════════════════════════════════════════════════════════
# Testdokument
#
# Ein Template mit Platzhaltern, weil sich die Fälle nur in einer Zeile
# unterscheiden (Typcode, Währung, Positionen); vier fast gleiche Dateien
# liefen bei Änderungen auseinander.
# ══════════════════════════════════════════════════════════════════════════

POSITIONEN = """
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:AssociatedDocumentLineDocument><ram:LineID>1</ram:LineID>
      </ram:AssociatedDocumentLineDocument>
      <ram:SpecifiedTradeProduct>
        <ram:Name>Paket B: Schwermetalle nach LAGA</ram:Name>
      </ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement>
        <ram:NetPriceProductTradePrice>
          <ram:ChargeAmount>42.50</ram:ChargeAmount>
        </ram:NetPriceProductTradePrice>
      </ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery>
        <ram:BilledQuantity unitCode="C62">8</ram:BilledQuantity>
      </ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement>
        <ram:SpecifiedTradeSettlementLineMonetarySummation>
          <ram:LineTotalAmount>340.00</ram:LineTotalAmount>
        </ram:SpecifiedTradeSettlementLineMonetarySummation>
      </ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:AssociatedDocumentLineDocument><ram:LineID>2</ram:LineID>
      </ram:AssociatedDocumentLineDocument>
      <ram:SpecifiedTradeProduct>
        <ram:Name>Probenahme vor Ort</ram:Name>
      </ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement>
        <ram:NetPriceProductTradePrice>
          <ram:ChargeAmount>95.00</ram:ChargeAmount>
        </ram:NetPriceProductTradePrice>
      </ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery>
        <ram:BilledQuantity unitCode="HUR">3.5</ram:BilledQuantity>
      </ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement>
        <ram:SpecifiedTradeSettlementLineMonetarySummation>
          <ram:LineTotalAmount>332.50</ram:LineTotalAmount>
        </ram:SpecifiedTradeSettlementLineMonetarySummation>
      </ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>
"""

VORLAGE = """<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
    xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
    xmlns:ram="urn:un:unece:uncefact:data:standard:\
ReusableAggregateBusinessInformationEntity:100"
    xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocumentContext>
    <ram:GuidelineSpecifiedDocumentContextParameter>
      <ram:ID>urn:cen.eu:en16931:2017</ram:ID>
    </ram:GuidelineSpecifiedDocumentContextParameter>
  </rsm:ExchangedDocumentContext>
  <rsm:ExchangedDocument>
    <ram:ID>{nummer}</ram:ID>
    <ram:TypeCode>{typ}</ram:TypeCode>
    <ram:IssueDateTime>
      <udt:DateTimeString format="102">20260812</udt:DateTimeString>
    </ram:IssueDateTime>
    <ram:IncludedNote>
      <ram:Content>Analytik Bodenproben, Charge 12/26</ram:Content>
    </ram:IncludedNote>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
{positionen}
    <ram:ApplicableHeaderTradeAgreement>
      <ram:BuyerReference>04011000-12345-67</ram:BuyerReference>
      <ram:SellerTradeParty>
        <ram:Name>{lieferant}</ram:Name>
        <ram:PostalTradeAddress>
          <ram:PostcodeCode>84032</ram:PostcodeCode>
          <ram:LineOne>Laborweg 4</ram:LineOne>
          <ram:CityName>Altdorf</ram:CityName>
          <ram:CountryID>DE</ram:CountryID>
        </ram:PostalTradeAddress>
        <ram:SpecifiedTaxRegistration>
          <ram:ID schemeID="VA">DE812345678</ram:ID>
        </ram:SpecifiedTaxRegistration>
      </ram:SellerTradeParty>
      <ram:BuyerTradeParty>
        <ram:Name>Ingenieurbüro Muster GmbH</ram:Name>
      </ram:BuyerTradeParty>
      <ram:BuyerOrderReferencedDocument>
        <ram:IssuerAssignedID>BST-2026-0099</ram:IssuerAssignedID>
      </ram:BuyerOrderReferencedDocument>
{projekt}
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeDelivery>
      <ram:ActualDeliverySupplyChainEvent>
        <ram:OccurrenceDateTime>
          <udt:DateTimeString format="102">20260731</udt:DateTimeString>
        </ram:OccurrenceDateTime>
      </ram:ActualDeliverySupplyChainEvent>
    </ram:ApplicableHeaderTradeDelivery>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>{waehrung}</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradeSettlementPaymentMeans>
        <ram:TypeCode>58</ram:TypeCode>
        <ram:PayeePartyCreditorFinancialAccount>
          <ram:IBANID>DE02120300000000202051</ram:IBANID>
        </ram:PayeePartyCreditorFinancialAccount>
      </ram:SpecifiedTradeSettlementPaymentMeans>
      <ram:ApplicableTradeTax>
        <ram:CalculatedAmount>127.78</ram:CalculatedAmount>
        <ram:TypeCode>VAT</ram:TypeCode>
        <ram:BasisAmount>672.50</ram:BasisAmount>
        <ram:CategoryCode>S</ram:CategoryCode>
        <ram:RateApplicablePercent>19.00</ram:RateApplicablePercent>
      </ram:ApplicableTradeTax>
      <ram:SpecifiedTradePaymentTerms>
        <ram:Description>Zahlbar innerhalb 30 Tagen ohne Abzug.</ram:Description>
        <ram:DueDateDateTime>
          <udt:DateTimeString format="102">20260911</udt:DateTimeString>
        </ram:DueDateDateTime>
      </ram:SpecifiedTradePaymentTerms>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:LineTotalAmount>672.50</ram:LineTotalAmount>
        <ram:TaxBasisTotalAmount>{netto}</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="EUR">127.78</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>800.28</ram:GrandTotalAmount>
        <ram:DuePayableAmount>800.28</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
"""


def cii(**abweichend) -> bytes:
    """CII-Dokument, das in einem Punkt vom Regelfall abweicht."""
    werte = {
        'nummer': 'BLI-2026-4711',
        'typ': '380',
        'waehrung': 'EUR',
        'netto': '672.50',
        'lieferant': 'Bodenlabor Isartal GmbH',
        'positionen': POSITIONEN,
        'projekt': '',
    }
    werte.update(abweichend)
    return VORLAGE.format(**werte).encode('utf-8')


def projektreferenz(kennung: str) -> str:
    """BT-11 im Kopf der Vereinbarung."""
    return (f'      <ram:SpecifiedProcuringProject>\n'
            f'        <ram:ID>{kennung}</ram:ID>\n'
            f'        <ram:Name>Bauvorhaben</ram:Name>\n'
            f'      </ram:SpecifiedProcuringProject>')


def zeile(name: str, menge: str, einheit: str, preis: str, *,
          betrag: str | None = None, basis: str | None = None) -> str:
    """Rechnungszeile, wahlweise mit Preisbasismenge (BT-149) und mit oder
    ohne Zeilenbetrag (BT-131)."""
    basismenge = (f'<ram:BasisQuantity unitCode="{einheit}">{basis}'
                  f'</ram:BasisQuantity>' if basis else '')
    summe = (f'<ram:SpecifiedTradeSettlementLineMonetarySummation>'
             f'<ram:LineTotalAmount>{betrag}</ram:LineTotalAmount>'
             f'</ram:SpecifiedTradeSettlementLineMonetarySummation>'
             if betrag else '')
    return f"""
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:AssociatedDocumentLineDocument><ram:LineID>1</ram:LineID>
      </ram:AssociatedDocumentLineDocument>
      <ram:SpecifiedTradeProduct><ram:Name>{name}</ram:Name>
      </ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement>
        <ram:NetPriceProductTradePrice>
          <ram:ChargeAmount>{preis}</ram:ChargeAmount>{basismenge}
        </ram:NetPriceProductTradePrice>
      </ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery>
        <ram:BilledQuantity unitCode="{einheit}">{menge}</ram:BilledQuantity>
      </ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement>{summe}</ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>"""


def leeres_pdf() -> bytes:
    """Gültiges PDF ohne Anhang, wie ein Scan."""
    schreiber = PdfWriter()
    schreiber.add_blank_page(width=595, height=842)
    strom = BytesIO()
    schreiber.write(strom)
    return strom.getvalue()


def pdf_mit_xml(xml: bytes | None = None) -> bytes:
    """ZUGFeRD-PDF, erzeugt wie die eigenen Rechnungen.

    Mit ``drafthorse.pdf.attach_xml``, das auch die Factur-X-Kennzeichnung
    setzt (``/AF``, XMP); ein von Hand gebautes PDF prüfte nur das eigene
    Format. Ohne WeasyPrint, weil GTK nötig wäre und jeder Test eine halbe
    Sekunde dauerte; geprüft wird nur der Anhang.
    """
    return attach_xml(leeres_pdf(), xml if xml is not None else cii(),
                      level='EN 16931')


def pdf_mit_anhang(inhalt: bytes, name: str) -> bytes:
    """PDF mit beliebig benanntem Anhang, erzeugt mit pypdf.

    ``attach_xml`` parst das XML für die Factur-X-Kennzeichnung und bettet
    nur gültiges CII ein. Für Anhänge unter fremdem Namen oder ohne
    CII-Inhalt braucht es pypdf direkt, wie bei fremden Erzeugern.
    """
    schreiber = PdfWriter()
    schreiber.add_blank_page(width=595, height=842)
    schreiber.add_attachment(name, inhalt)
    strom = BytesIO()
    schreiber.write(strom)
    return strom.getvalue()


# ══════════════════════════════════════════════════════════════════════════
# Parser
# ══════════════════════════════════════════════════════════════════════════

class TestLesen:
    def test_der_kopf_kommt_vollstaendig(self):
        gelesen = erechnung.lesen(cii())

        assert gelesen.nummer == 'BLI-2026-4711'
        assert gelesen.datum.isoformat() == '2026-08-12'
        assert gelesen.lieferant == 'Bodenlabor Isartal GmbH'
        assert gelesen.betrag_netto == Decimal('672.50')

    def test_der_betrag_ist_bt_109_und_nicht_die_zeilensumme(self):
        """Der Betrag ist BT-109, nicht die Zeilensumme BT-106.

        Mit einem Abschlag auf Belegebene weichen beide ab. Gegen BT-109
        (Steuerbasis) wird die Zuordnung geprüft.
        """
        gelesen = erechnung.lesen(cii(netto='650.00'))

        assert gelesen.betrag_netto == Decimal('650.00')
        assert gelesen.positionssumme == Decimal('672.50')

    def test_die_positionen_kommen_mit_uebersetzter_einheit(self):
        gelesen = erechnung.lesen(cii())

        erste, zweite = gelesen.positionen
        assert erste.bezeichnung == 'Paket B: Schwermetalle nach LAGA'
        assert erste.menge == Decimal('8')
        assert erste.einheit == 'Stk', 'C62 muss zu unserer Schreibweise werden'
        assert erste.einzelpreis == Decimal('42.50')
        assert zweite.einheit == 'Std', 'HUR ist die Stunde'
        assert zweite.menge == Decimal('3.5')

    def test_was_kein_feld_hat_steht_in_sonstiges(self):
        sonstiges = erechnung.lesen(cii()).sonstiges

        assert sonstiges['Bruttobetrag'] == '800.28'
        assert sonstiges['Umsatzsteuer'] == '127.78'
        assert sonstiges['Fällig am'] == '11.09.2026'
        assert sonstiges['Leistungsdatum'] == '31.07.2026'
        assert sonstiges['IBAN'] == 'DE02120300000000202051'
        assert sonstiges['USt-IdNr.'] == 'DE812345678'
        assert sonstiges['Bestellnummer'] == 'BST-2026-0099'
        assert sonstiges['Leitweg-ID'] == '04011000-12345-67'
        assert sonstiges['Steuersaetze'] == '19,00 %'
        assert 'Bodenproben' in sonstiges['Anmerkungen']

    def test_leere_angaben_stehen_nicht_in_sonstiges(self):
        """Leere Angaben fehlen in ``sonstiges``."""
        sonstiges = erechnung.lesen(cii()).sonstiges

        assert 'Steuernummer' not in sonstiges, \
            'Das Dokument trägt nur eine USt-IdNr., keine Steuernummer'
        assert all(wert for wert in sonstiges.values())


class TestZeilenbetragUndPreisbasis:
    """Fälle, in denen Menge mal Preis nicht der Zeilenbetrag ist."""

    def test_der_zeilenbetrag_schlaegt_menge_mal_preis(self):
        """10 zu 50,00 abzüglich 10 % auf der Zeile ergeben 450."""
        gelesen = erechnung.lesen(cii(
            positionen=zeile('Klemmen', '10', 'C62', '50.00', betrag='450.00'),
            netto='450.00'))

        [position] = gelesen.positionen
        assert position.einzelpreis == Decimal('50.0000')
        assert position.betrag == Decimal('450.00')
        assert gelesen.positionssumme == Decimal('450.00')

    def test_die_preisbasismenge_wird_heruntergerechnet(self):
        """0,85 € je 100 m ergeben 0,0085 € je Meter; 250 m sind 2,13 (2,125
        kaufmännisch gerundet)."""
        gelesen = erechnung.lesen(cii(
            positionen=zeile('NYM-J 3x1,5', '250', 'MTR', '0.85',
                             basis='100', betrag='2.13'),
            netto='2.13'))

        [position] = gelesen.positionen
        assert position.einzelpreis == Decimal('0.0085')
        assert position.betrag == Decimal('2.13')
        assert position.einheit == 'm'

    def test_ohne_zeilenbetrag_gilt_menge_mal_preis(self):
        """Ohne BT-131, das manche Erzeuger trotz Pflicht weglassen, gilt
        Menge mal Preis."""
        gelesen = erechnung.lesen(cii(
            positionen=zeile('Klemmen', '3', 'C62', '12.345'),
            netto='37.04'))

        [position] = gelesen.positionen
        assert position.betrag == Decimal('37.04')

    def test_die_fremdleistung_bekommt_den_zeilenbetrag(self, db, projekt):
        rechnung, _ = eingangsrechnung_aus_xml(
            daten=cii(positionen=zeile('Klemmen', '10', 'C62', '50.00',
                                       betrag='450.00'),
                      netto='450.00'),
            projekt=projekt)

        position = rechnung.positionen.get()
        assert position.einkaufspreis == Decimal('50.00')
        assert position.einkauf_netto == Decimal('450.00')
        assert rechnung.ist_vollstaendig, \
            'Mit Menge mal Preis stünden hier 50 € zu viel verteilt'

    def test_der_meterpreis_kommt_vierstellig_an(self, db, projekt):
        rechnung, _ = eingangsrechnung_aus_xml(
            daten=cii(positionen=zeile('NYM-J 3x1,5', '250', 'MTR', '0.85',
                                       basis='100', betrag='2.13'),
                      netto='2.13'),
            projekt=projekt)

        position = rechnung.positionen.get()
        assert position.einkaufspreis == Decimal('0.0085')
        assert position.einkauf_netto == Decimal('2.13')


class TestProjektreferenz:
    """Projektreferenz BT-11: Ohne Auswahl im Formular gilt das passende
    laufende Projekt."""

    def test_sie_wird_gelesen(self):
        gelesen = erechnung.lesen(cii(projekt=projektreferenz('2026-042')))

        assert gelesen.projektreferenz == '2026-042'
        assert gelesen.sonstiges['Projektreferenz'] == '2026-042'

    def test_ohne_sie_bleibt_sie_leer(self):
        gelesen = erechnung.lesen(cii())

        assert gelesen.projektreferenz == ''
        assert 'Projektreferenz' not in gelesen.sonstiges

    def test_die_nummer_selbst(self, db, projekt):
        from erfassung.services import projekt_aus_referenz

        assert projekt_aus_referenz('2026-042') == projekt
        assert projekt_aus_referenz(' 2026-042 ') == projekt

    def test_die_nummer_im_text(self, db, projekt):
        from erfassung.services import projekt_aus_referenz

        assert projekt_aus_referenz('BV Halle Nord, Projekt 2026-042') \
            == projekt

    def test_eine_laengere_nummer_ist_eine_andere(self, db, projekt):
        """Nur ganze Wörter zählen: 2026-0421 ist nicht 2026-042."""
        from erfassung.services import projekt_aus_referenz

        assert projekt_aus_referenz('Projekt 2026-0421') is None
        assert projekt_aus_referenz('X2026-042') is None

    def test_zwei_nummern_im_text_entscheidet_der_mensch(self, db, projekt,
                                                         kunde):
        from erfassung.services import projekt_aus_referenz
        from faktura.models import Projekt

        Projekt.objects.create(nummer='2026-043', bezeichnung='Halle Süd',
                               kunde=kunde)

        assert projekt_aus_referenz('2026-042 und 2026-043') is None

    def test_ein_abgeschlossenes_projekt_kommt_nicht_in_frage(
            self, db, abgeschlossenes_projekt):
        from erfassung.services import projekt_aus_referenz

        assert projekt_aus_referenz(abgeschlossenes_projekt.nummer) is None

    def test_unbekannt_und_leer_ergeben_nichts(self, db, projekt):
        from erfassung.services import projekt_aus_referenz

        assert projekt_aus_referenz('BV Irgendwo') is None
        assert projekt_aus_referenz('') is None

    def test_ohne_gewaehltes_projekt_wird_sie_genommen(self, db, projekt):
        rechnung, _ = eingangsrechnung_aus_xml(
            daten=cii(projekt=projektreferenz('2026-042')))

        assert rechnung.positionen.count() == 2
        assert all(p.projekt == projekt for p in rechnung.positionen.all())

    def test_die_wahl_des_menschen_schlaegt_sie(self, db, projekt, kunde):
        from faktura.models import Projekt

        anderes = Projekt.objects.create(
            nummer='2026-043', bezeichnung='Halle Süd', kunde=kunde)
        rechnung, _ = eingangsrechnung_aus_xml(
            daten=cii(projekt=projektreferenz('2026-042')), projekt=anderes)

        assert all(p.projekt == anderes for p in rechnung.positionen.all())


class TestDrafthorseFalle:
    """Verhalten von drafthorse bei ``TaxTotalAmount``.

    ``MonetarySummation`` definiert zwei Felder mit dem XML-Tag
    ``TaxTotalAmount``; beim Parsen überschreibt das später definierte das
    frühere im Tag-Index, ``tax_total`` bleibt leer. ``_umsatzsteuer`` liest
    deshalb die Steuerzeilen.

    Der Test prüft das Verhalten der Bibliothek und schlägt fehl, sobald
    drafthorse es korrigiert; dann lässt sich der Workaround entfernen.
    """

    def test_tax_total_bleibt_beim_parsen_leer(self):
        from drafthorse.models.document import Document

        doc = Document.parse(cii(), strict=False)
        summen = doc.trade.settlement.monetary_summation

        assert summen.tax_total._amount == '', (
            'drafthorse liest TaxTotalAmount nun doch in tax_total; '
            'der Umweg in erechnung._umsatzsteuer kann geprüft werden')
        assert list(summen.tax_total_other_currency.children), \
            'Der Wert landet stattdessen im Mehrwaehrungsfeld'

    def test_wir_lesen_die_umsatzsteuer_trotzdem(self):
        assert erechnung.lesen(cii()).sonstiges['Umsatzsteuer'] == '127.78'


class TestAbgewiesen:
    """Ablehnung von Dateien, die keine CII-Rechnung sind.

    Jeder Fall hat eine eigene Meldung, die sagt, was zu tun ist.
    """

    def test_ein_pdf_ohne_eingebettete_daten(self):
        """Ein PDF ohne eingebettete Daten, etwa ein Scan.

        Die Meldung erklärt, dass ein PDF ohne XML vorliegt; PDFs mit XML
        werden unterstützt.
        """
        with pytest.raises(erechnung.ERechnungFehler) as fehler:
            erechnung.lesen(leeres_pdf())

        text = str(fehler.value)
        assert 'keine E-Rechnung' in text
        assert 'XML' in text and 'im' in text

    def test_kaputte_pdf_daten(self):
        with pytest.raises(erechnung.ERechnungFehler) as fehler:
            erechnung.lesen(b'%PDF-1.7\nab hier nur Unsinn')

        assert 'PDF' in str(fehler.value)

    def test_eine_ubl_rechnung(self):
        ubl = (b'<?xml version="1.0"?>'
               b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:'
               b'xsd:Invoice-2"><ID>R-1</ID></Invoice>')

        with pytest.raises(erechnung.ERechnungFehler) as fehler:
            erechnung.lesen(ubl)

        assert 'UBL' in str(fehler.value)
        assert 'CII' in str(fehler.value)

    def test_eine_gutschrift(self):
        with pytest.raises(erechnung.ERechnungFehler) as fehler:
            erechnung.lesen(cii(typ='381'))

        assert 'Gutschrift' in str(fehler.value)

    def test_eine_fremdwaehrung(self):
        """Eine Rechnung in Franken wird abgelehnt."""
        with pytest.raises(erechnung.ERechnungFehler) as fehler:
            erechnung.lesen(cii(waehrung='CHF'))

        assert 'CHF' in str(fehler.value)

    def test_kaputtes_xml(self):
        with pytest.raises(erechnung.ERechnungFehler):
            erechnung.lesen(b'<rsm:CrossIndustryInvoice><nicht zu')

    def test_eine_leere_datei(self):
        with pytest.raises(erechnung.ERechnungFehler):
            erechnung.lesen(b'')

    def test_ohne_rechnungsnummer(self):
        with pytest.raises(erechnung.ERechnungFehler) as fehler:
            erechnung.lesen(cii(nummer=''))

        assert 'BT-1' in str(fehler.value)


class TestAusPdf:
    """Extraktion des XML aus dem PDF.

    Eine E-Rechnung nach Factur-X ist ein PDF mit eingebettetem XML, der
    häufigste Fall; reines XML ist die Ausnahme.
    """

    def test_dasselbe_ergebnis_wie_aus_dem_xml(self):
        """Aus PDF und XML ergeben sich dieselben Werte.

        Verglichen werden die Werte, weil sich die Objekte in ``aus_pdf``
        unterscheiden.
        """
        aus_xml = erechnung.lesen(cii())
        aus_pdf = erechnung.lesen(pdf_mit_xml())

        assert aus_pdf.nummer == aus_xml.nummer
        assert aus_pdf.datum == aus_xml.datum
        assert aus_pdf.lieferant == aus_xml.lieferant
        assert aus_pdf.betrag_netto == aus_xml.betrag_netto
        assert aus_pdf.positionen == aus_xml.positionen
        assert aus_pdf.sonstiges == aus_xml.sonstiges

    def test_die_herkunft_wird_vermerkt(self):
        assert erechnung.lesen(pdf_mit_xml()).aus_pdf is True
        assert erechnung.lesen(cii()).aus_pdf is False

    def test_die_notiz_sagt_woher_die_zahlen_kommen(self):
        gelesen = erechnung.lesen(pdf_mit_xml())

        notiz = erechnung.notiz_bauen(gelesen, 'rechnung.pdf')
        assert 'rechnung.pdf' in notiz
        assert 'XML aus dem PDF geholt' in notiz

    @pytest.mark.parametrize('name', [
        'ZUGFeRD-invoice.xml',   # ZUGFeRD 1.0
        'zugferd-invoice.xml',   # derselbe Name in Kleinschreibung
        'xrechnung.xml',
        'Rechnung_2026_4711.xml',  # abweichender Name
    ])
    def test_andere_anhangsnamen(self, name):
        """Auch Anhänge mit anderem Namen als ``factur-x.xml`` werden
        gelesen; ob es eine Rechnung ist, zeigt das Parsen."""
        gelesen = erechnung.lesen(pdf_mit_anhang(cii(), name))

        assert gelesen.nummer == 'BLI-2026-4711'

    def test_der_vorgeschriebene_name_gewinnt(self):
        """Bei mehreren Anhängen hat der vorgeschriebene Name Vorrang.

        Etwa bei einem Lieferschein als zweitem Anhang. Ohne feste
        Reihenfolge hinge das Ergebnis von der Sortierung in pypdf ab.
        """
        schreiber = PdfWriter()
        schreiber.add_blank_page(width=595, height=842)
        schreiber.add_attachment('anlage.xml', cii(nummer='FALSCH-1'))
        schreiber.add_attachment('factur-x.xml', cii(nummer='RICHTIG-1'))
        schreiber.add_attachment('zugferd-invoice.xml', cii(nummer='FALSCH-2'))
        strom = BytesIO()
        schreiber.write(strom)

        assert erechnung.lesen(strom.getvalue()).nummer == 'RICHTIG-1'

    def test_ein_pdf_mit_ubl_darin_bekommt_die_ubl_meldung(self):
        """Ein PDF mit UBL erhält die Meldung zu UBL, weil der Anhang wie
        eine Datei geprüft wird."""
        ubl = (b'<?xml version="1.0"?>'
               b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:'
               b'xsd:Invoice-2"><ID>R-1</ID></Invoice>')

        with pytest.raises(erechnung.ERechnungFehler) as fehler:
            erechnung.lesen(pdf_mit_anhang(ubl, 'xrechnung.xml'))

        assert 'UBL' in str(fehler.value)

    def test_ein_pdf_mit_gutschrift_darin(self):
        with pytest.raises(erechnung.ERechnungFehler) as fehler:
            erechnung.lesen(pdf_mit_xml(cii(typ='381')))

        assert 'Gutschrift' in str(fehler.value)

    def test_bis_in_die_datenbank(self, db, projekt):
        rechnung, gelesen = eingangsrechnung_aus_xml(
            daten=pdf_mit_xml(), dateiname='isartal.pdf', projekt=projekt)

        assert rechnung.positionen.count() == 2
        assert rechnung.betrag_netto == Decimal('672.50')
        assert 'XML aus dem PDF geholt' in rechnung.notiz
        assert gelesen.aus_pdf is True


class TestBeispieldateien:
    """Dateien aus ``beispiele/e-rechnung/`` unverändert.

    Die Dateien dienen manuellen Tests und Vorführungen. Geprüft wird, dass
    sie die Werte liefern, die die README des Ordners nennt.
    """

    def test_der_ordner_ist_vollstaendig(self):
        """Schlägt fehl, wenn eine Datei umbenannt oder gelöscht wird, damit
        die Tabelle in der README angepasst wird."""
        vorhanden = sorted(p.name for p in BEISPIELE.iterdir()
                           if p.suffix in ('.xml', '.pdf'))

        assert vorhanden == [
            'abgewiesen-fremdwaehrung.xml',
            'abgewiesen-gutschrift.xml',
            'abgewiesen-ubl-syntax.xml',
            'ingsoft-4801-ohne-positionen.xml',
            'isartal-4711-regelfall.xml',
            'isartal-4712-mit-abschlag.xml',
            'isartal-4713-als-pdf.pdf',
            'ladetechnik-3402-wallbox.xml',
            'wittmann-880366-material.xml',
        ]

    def test_das_beispiel_pdf(self):
        """Das Beispiel-PDF, das sich als einzige Datei nicht von Hand
        prüfen lässt."""
        gelesen = erechnung.lesen(
            (BEISPIELE / 'isartal-4713-als-pdf.pdf').read_bytes())

        assert gelesen.aus_pdf is True
        assert gelesen.nummer == 'BLI-2026-4713'
        assert gelesen.betrag_netto == Decimal('672.50')
        assert len(gelesen.positionen) == 2

    def test_das_beispiel_pdf_zeigt_die_rechnung_auch_dem_menschen(self):
        """Das Beispiel-PDF zeigt die Rechnung auch als Seite."""
        from pypdf import PdfReader

        seite = PdfReader(
            BEISPIELE / 'isartal-4713-als-pdf.pdf').pages[0].extract_text()

        assert 'BLI-2026-4713' in seite
        assert 'Bodenlabor Isartal' in seite
        assert '800,28' in seite, 'Der Rechnungsbetrag muss sichtbar sein'
        assert 'Beispieldatei' in seite, \
            'Sie darf nicht mit einem echten Beleg verwechselt werden'

    def test_der_regelfall(self):
        gelesen = erechnung.lesen(
            (BEISPIELE / 'isartal-4711-regelfall.xml').read_bytes())

        assert gelesen.nummer == 'BLI-2026-4711'
        assert gelesen.lieferant == 'Bodenlabor Isartal GmbH'
        assert gelesen.betrag_netto == Decimal('672.50')
        assert [p.einheit for p in gelesen.positionen] == ['Stk', 'Std']
        assert gelesen.positionssumme == gelesen.betrag_netto, \
            'Der Regelfall geht auf; sonst zeigt er nicht, was er soll'

    def test_der_abschlag_laesst_die_summen_auseinandergehen(self):
        """Die Datei mit Abschlag zeigt den Unterschied von BT-109 und
        BT-106."""
        gelesen = erechnung.lesen(
            (BEISPIELE / 'isartal-4712-mit-abschlag.xml').read_bytes())

        assert gelesen.betrag_netto == Decimal('647.50')
        assert gelesen.positionssumme == Decimal('672.50')

    def test_die_rechnung_ohne_positionen(self):
        gelesen = erechnung.lesen(
            (BEISPIELE / 'ingsoft-4801-ohne-positionen.xml').read_bytes())

        assert gelesen.positionen == []
        assert gelesen.betrag_netto == Decimal('1200.00')
        assert gelesen.lieferant == 'Ingsoft Tragwerksplanung GbR', \
            'Ein zweiter Lieferant; sonst zeigt die Datei das Anlegen nicht'
        assert gelesen.sonstiges['Steuernummer'] == '244/128/50324', \
            'Die einzige Datei mit FC statt VA; der andere Zweig'

    # ── Dateien für den Elektrobetrieb ─────────────────────────────────────
    #
    # Neben den Laborrechnungen, weil die Demobestände Handwerksbetrieb und
    # Ingenieurbüro jeweils passende Belege brauchen.

    def test_der_sammelbeleg_des_grosshaendlers(self):
        """Sammelbeleg eines Großhändlers mit vielen Kleinteilen und drei
        Einheiten. MTR wird zu "m"; der Meter kommt in den Laborrechnungen
        nicht vor."""
        gelesen = erechnung.lesen(
            (BEISPIELE / 'wittmann-880366-material.xml').read_bytes())

        assert gelesen.nummer == 'WI-880366'
        assert gelesen.lieferant == 'Elektro-Großhandel Wittmann KG'
        assert gelesen.betrag_netto == Decimal('1524.00')
        assert [p.einheit for p in gelesen.positionen] == \
            ['m', 'Stk', 'Stk', 'Stk']
        assert gelesen.positionssumme == gelesen.betrag_netto, \
            'Der Sammelbeleg geht auf; sonst zeigt er nicht, was er soll'

    def test_die_wallboxrechnung(self):
        """Rechnung mit wenigen Zeilen und hohem Betrag, Gegenfall zum
        Sammelbeleg."""
        gelesen = erechnung.lesen(
            (BEISPIELE / 'ladetechnik-3402-wallbox.xml').read_bytes())

        assert gelesen.nummer == 'LS-2026-3402'
        assert gelesen.lieferant == 'Ladetechnik Süd GmbH'
        assert gelesen.betrag_netto == Decimal('2212.00')
        assert len(gelesen.positionen) == 2

    def test_die_seriennummern_gehen_nicht_verloren(self):
        """Seriennummern aus den Anmerkungen gelangen über ``sonstiges`` in
        die Notiz; sie werden für Anmeldung beim Netzbetreiber und
        Garantiefälle gebraucht."""
        gelesen = erechnung.lesen(
            (BEISPIELE / 'ladetechnik-3402-wallbox.xml').read_bytes())

        assert 'WB-11-2026-40871' in gelesen.sonstiges.get('Anmerkungen', '')

    def test_die_elektrodateien_nennen_ihren_kaeufer(self):
        """Die Dateien nennen als Käufer den Demobestand
        ``elektro-hofmeister`` (in ``paper-werk``)."""
        for name in ('wittmann-880366-material.xml',
                     'ladetechnik-3402-wallbox.xml'):
            text = (BEISPIELE / name).read_text(encoding='utf-8')
            assert 'Elektro Hofmeister e.K.' in text, name

    def test_die_lieferantennamen_tragen_ihre_umlaute(self):
        """Lieferantennamen enthalten Umlaute, keine ASCII-Umschreibung.

        Weicht der Name um einen Umlaut vom Demobestand ab, legt
        ``lieferant_finden`` einen zweiten Lieferanten an. Bei ß fällt das
        nicht auf, weil ``casefold()`` ß auf ss abbildet; bei ü gibt es keine
        solche Regel.

        Der Demobestand liegt als JSON in ``paper-werk`` und wird
        dort geprüft (``05-lieferanten.json``); hier wird die Seite der
        Beispieldateien geprüft.
        """
        for datei, lieferant in (
                ('wittmann-880366-material.xml',
                 'Elektro-Großhandel Wittmann KG'),
                ('ladetechnik-3402-wallbox.xml', 'Ladetechnik Süd GmbH')):
            text = (BEISPIELE / datei).read_text(encoding='utf-8')
            assert lieferant in text, f'{datei} nennt {lieferant} nicht'

    def test_die_rechnungsnummern_sind_alle_verschieden(self):
        """Alle Rechnungsnummern sind verschieden, damit ein Upload mehrerer
        Dateien nicht "bereits erfasst" meldet."""
        nummern = {
            erechnung.lesen((BEISPIELE / name).read_bytes()).nummer
            for name in ('isartal-4711-regelfall.xml',
                         'isartal-4712-mit-abschlag.xml',
                         'isartal-4713-als-pdf.pdf',
                         'ingsoft-4801-ohne-positionen.xml')
        }

        assert len(nummern) == 4

    @pytest.mark.parametrize('datei, erwartet', [
        ('abgewiesen-gutschrift.xml', 'Gutschrift'),
        ('abgewiesen-ubl-syntax.xml', 'UBL'),
        ('abgewiesen-fremdwaehrung.xml', 'CHF'),
    ])
    def test_was_abgewiesen_wird(self, datei, erwartet):
        with pytest.raises(erechnung.ERechnungFehler) as fehler:
            erechnung.lesen((BEISPIELE / datei).read_bytes())

        assert erwartet in str(fehler.value)

    def test_der_regelfall_laeuft_bis_in_die_datenbank(self, db, projekt):
        """Die Datei durchläuft Parser und Service bis in die Datenbank."""
        rechnung, _ = eingangsrechnung_aus_xml(
            daten=(BEISPIELE / 'isartal-4711-regelfall.xml').read_bytes(),
            dateiname='isartal-4711-regelfall.xml',
            projekt=projekt,
        )

        assert rechnung.positionen.count() == 2
        assert rechnung.rest == Decimal('0.00')


# ══════════════════════════════════════════════════════════════════════════
# Service
# ══════════════════════════════════════════════════════════════════════════

class TestDienst:
    def test_die_rechnung_entsteht_mit_lieferant(self, db):
        rechnung, _ = eingangsrechnung_aus_xml(daten=cii())

        assert rechnung.nummer == 'BLI-2026-4711'
        assert rechnung.betrag_netto == Decimal('672.50')
        assert rechnung.lieferant.name == 'Bodenlabor Isartal GmbH'
        assert rechnung.paperless_id is None, \
            'Es liegt kein Dokument im Archiv, auf das verwiesen werden könnte'

    def test_der_neue_lieferant_traegt_einen_vermerk(self, db):
        rechnung, _ = eingangsrechnung_aus_xml(daten=cii())

        assert 'E-Rechnung' in rechnung.lieferant.notiz, \
            'Wer aufräumt, muss sehen, welcher Weg den Lieferanten anlegte'

    def test_ein_bekannter_lieferant_wird_wiederverwendet(self, db):
        vorhanden = Kontakt.objects.create(
            ist_kunde=False, ist_lieferant=True, name='bodenlabor isartal gmbh')

        rechnung, _ = eingangsrechnung_aus_xml(daten=cii())

        assert rechnung.lieferant == vorhanden, \
            'Groß- und Kleinschreibung darf keinen zweiten Lieferanten machen'
        assert Kontakt.objects.filter(ist_lieferant=True).count() == 1

    def test_die_notiz_traegt_was_kein_feld_hat(self, db):
        rechnung, _ = eingangsrechnung_aus_xml(
            daten=cii(), dateiname='isartal.xml')

        assert 'isartal.xml' in rechnung.notiz
        assert 'IBAN: DE02120300000000202051' in rechnung.notiz
        assert 'Fällig am: 11.09.2026' in rechnung.notiz

    def test_ohne_projekt_entsteht_nur_der_kopf(self, db):
        rechnung, _ = eingangsrechnung_aus_xml(daten=cii())

        assert rechnung.positionen.count() == 0
        assert rechnung.rest == Decimal('672.50'), \
            'Was nicht zugeordnet ist, steht als Rest da'

    def test_mit_projekt_entstehen_alle_positionen(self, db, projekt):
        rechnung, _ = eingangsrechnung_aus_xml(daten=cii(), projekt=projekt)

        positionen = list(rechnung.positionen.order_by('pk'))
        assert len(positionen) == 2, \
            'Die Zeilen des Dokuments, nicht eine Summenzeile'
        assert positionen[0].bezeichnung == 'Paket B: Schwermetalle nach LAGA'
        assert positionen[0].einkaufspreis == Decimal('42.50')
        assert positionen[0].menge == Decimal('8')
        assert all(p.projekt == projekt for p in positionen)
        assert rechnung.rest == Decimal('0.00')

    def test_jede_zeile_traegt_ihren_betrag(self, db, projekt):
        """Jede Zeile trägt ihren Einkaufsbetrag: 8 x 42,50 = 340,00."""
        rechnung, _ = eingangsrechnung_aus_xml(daten=cii(), projekt=projekt)

        erste = rechnung.positionen.order_by('pk').first()
        assert erste.einkauf_netto == Decimal('340.00')

    def test_ohne_zeilen_entsteht_eine_summenzeile(self, db, projekt):
        """Ohne Zeilen entsteht eine Summenzeile, damit bei gewähltem
        Vorhaben kein voller Rest offen bleibt."""
        rechnung, _ = eingangsrechnung_aus_xml(
            daten=cii(positionen=''), projekt=projekt)

        eine = rechnung.positionen.get()
        assert eine.einkaufspreis == Decimal('672.50')
        assert rechnung.rest == Decimal('0.00')

    def test_dieselbe_rechnung_ein_zweites_mal(self, db):
        eingangsrechnung_aus_xml(daten=cii())

        with pytest.raises(RechnungBereitsErfasst) as fehler:
            eingangsrechnung_aus_xml(daten=cii())

        assert 'BLI-2026-4711' in str(fehler.value)
        assert Eingangsrechnung.objects.count() == 1

    def test_eine_kaputte_datei_legt_nichts_an(self, db):
        with pytest.raises(erechnung.ERechnungFehler):
            eingangsrechnung_aus_xml(daten=cii(waehrung='CHF'))

        assert not Eingangsrechnung.objects.exists()
        assert not Kontakt.objects.filter(ist_lieferant=True).exists(), \
            'Auch der Lieferant darf dabei nicht entstehen'


# ══════════════════════════════════════════════════════════════════════════
# Maske
#
# Über den Client mit einer echten Datei, siehe Modul-Docstring.
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def als_leitung(client, kollege):
    kollege.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='erfassung'))
    kollege.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='faktura',
        codename__in=['view_projekt', 'change_projekt']))
    client.force_login(kollege)
    return client


ADRESSE = 'admin:erfassung_eingangsrechnung_liste_erechnung'


def hochladen(client, daten: bytes, name='rechnung.xml', **felder):
    datei = BytesIO(daten)
    datei.name = name
    return client.post(reverse(ADRESSE), {'datei': datei, **felder})


def meldungen(antwort) -> list[str]:
    return [str(m) for m in antwort.wsgi_request._messages]


class TestMaske:
    def test_die_maske_laesst_sich_oeffnen(self, als_leitung):
        antwort = als_leitung.get(reverse(ADRESSE))

        assert antwort.status_code == 200
        inhalt = antwort.content.decode()
        assert 'enctype="multipart/form-data"' in inhalt, \
            'Ohne das kommt die Datei gar nicht erst an'
        assert 'name="datei"' in inhalt
        assert 'name="projekt"' in inhalt

    def test_der_knopf_steht_ueber_der_liste(self, als_leitung):
        """Der Button über der Liste verlinkt auf die URL der View."""
        antwort = als_leitung.get(
            reverse('admin:erfassung_eingangsrechnung_changelist'))

        assert reverse(ADRESSE) in antwort.content.decode()

    def test_hochladen_legt_die_rechnung_an(self, als_leitung, projekt):
        antwort = hochladen(als_leitung, cii(), projekt=projekt.pk)

        rechnung = Eingangsrechnung.objects.get()
        assert antwort.status_code == 302
        assert antwort.url == reverse(
            'admin:erfassung_eingangsrechnung_change', args=[rechnung.pk]), \
            'Der Weg endet dort, wo verteilt wird'
        assert rechnung.betrag_netto == Decimal('672.50')
        assert rechnung.positionen.count() == 2
        assert Fremdleistung.objects.filter(projekt=projekt).count() == 2

    def test_ohne_projekt_geht_es_auch(self, als_leitung):
        antwort = hochladen(als_leitung, cii(), projekt='')

        assert antwort.status_code == 302
        assert Eingangsrechnung.objects.get().positionen.count() == 0

    def test_die_projektreferenz_wird_genannt(self, als_leitung, projekt):
        """Ohne Auswahl meldet die Maske, dass das Projekt aus der
        Projektreferenz stammt und wo es zu ändern ist."""
        antwort = hochladen(als_leitung,
                            cii(projekt=projektreferenz('2026-042')),
                            projekt='')

        text = ' '.join(meldungen(antwort))
        assert 'aus der Projektreferenz' in text
        assert '2026-042' in text
        assert Fremdleistung.objects.filter(projekt=projekt).count() == 2

    def test_eine_unpassende_projektreferenz_wird_genannt(self, als_leitung):
        antwort = hochladen(als_leitung,
                            cii(projekt=projektreferenz('BV Irgendwo')),
                            projekt='')

        text = ' '.join(meldungen(antwort))
        assert 'passt zu keinem' in text
        assert Eingangsrechnung.objects.get().positionen.count() == 0

    def test_die_meldung_sagt_was_gelesen_wurde(self, als_leitung, projekt):
        antwort = hochladen(als_leitung, cii(), projekt=projekt.pk)

        text = ' '.join(meldungen(antwort))
        assert 'BLI-2026-4711' in text
        assert '2 Positionen' in text

    def test_eine_abweichung_wird_gemeldet(self, als_leitung, projekt):
        """Eine Abweichung durch Zu- oder Abschlag auf Belegebene wird
        gemeldet."""
        antwort = hochladen(als_leitung, cii(netto='650.00'),
                            projekt=projekt.pk)

        text = ' '.join(meldungen(antwort))
        assert 'Abweichung' in text
        assert '22,50' in text or '22.50' in text

    def test_ein_zugferd_pdf_wird_eingelesen(self, als_leitung, projekt):
        """Ein ZUGFeRD-PDF wird eingelesen."""
        antwort = hochladen(als_leitung, pdf_mit_xml(),
                            name='rechnung.pdf', projekt=projekt.pk)

        rechnung = Eingangsrechnung.objects.get()
        assert antwort.status_code == 302
        assert rechnung.positionen.count() == 2
        assert 'XML aus dem PDF geholt' in ' '.join(meldungen(antwort))
        assert 'rechnung.pdf' in rechnung.notiz

    def test_ein_pdf_ohne_daten_wird_erklaert_und_nicht_gespeichert(
            self, als_leitung):
        antwort = hochladen(als_leitung, leeres_pdf(), name='scan.pdf')

        assert antwort.status_code == 200, 'Die Maske kommt zurück'
        assert not Eingangsrechnung.objects.exists()
        assert 'keine E-Rechnung' in ' '.join(meldungen(antwort))

    def test_die_maske_bietet_beide_formate_an(self, als_leitung):
        """``accept`` erlaubt XML und PDF; sonst blendete der Dateidialog
        PDFs aus."""
        inhalt = als_leitung.get(reverse(ADRESSE)).content.decode()

        assert 'accept=".pdf,.xml' in inhalt

    def test_zweimal_dieselbe_datei(self, als_leitung):
        hochladen(als_leitung, cii())
        antwort = hochladen(als_leitung, cii())

        assert Eingangsrechnung.objects.count() == 1
        assert 'bereits erfasst' in ' '.join(meldungen(antwort))

    def test_eine_zu_grosse_datei(self, als_leitung):
        """Eine Datei über der Höchstgröße wird abgelehnt."""
        antwort = hochladen(als_leitung, b'<x/>' * 3_000_000)

        assert antwort.status_code == 200
        assert not Eingangsrechnung.objects.exists()
        assert re.search(r'MB groß', antwort.content.decode()), \
            'Der Fehler gehört an das Feld, nicht in eine Meldung'

    def test_abgeschlossene_vorhaben_stehen_nicht_zur_wahl(
            self, als_leitung, projekt, abgeschlossenes_projekt):
        antwort = als_leitung.get(reverse(ADRESSE))

        inhalt = antwort.content.decode()
        assert f'value="{projekt.pk}"' in inhalt
        assert f'value="{abgeschlossenes_projekt.pk}"' not in inhalt, \
            'Auf ein abgeschlossenes Projekt wird nicht mehr kontiert'

    def test_wer_nur_sehen_darf_kommt_nicht_hinein(self, client, mitarbeiter):
        """Ohne ``add_eingangsrechnung`` kein Zugang zum Upload.

        Das Konto hat alle anderen Rechte der App, weil ein Konto ohne
        Rechte schon am Login des Admin scheiterte und die Prüfung der View
        nicht erreichte.
        """
        mitarbeiter.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='erfassung',
        ).exclude(codename='add_eingangsrechnung'))
        client.force_login(mitarbeiter)

        antwort = client.get(reverse(ADRESSE))

        assert antwort.status_code == 403
        assert not Eingangsrechnung.objects.exists()

    def test_und_kann_auch_nicht_hochladen(self, client, mitarbeiter):
        """Auch ein direkter POST auf die URL wird abgelehnt."""
        mitarbeiter.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='erfassung',
        ).exclude(codename='add_eingangsrechnung'))
        client.force_login(mitarbeiter)

        antwort = hochladen(client, cii())

        assert antwort.status_code == 403
        assert not Eingangsrechnung.objects.exists()
