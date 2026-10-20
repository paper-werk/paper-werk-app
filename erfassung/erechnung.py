"""Einlesen von E-Rechnungen, Gegenstück zu ``faktura/facturx.py``.

``facturx.py`` erzeugt CII-XML nach EN 16931, dieses Modul liest es aus
Rechnungen von Lieferanten, als reines XML oder eingebettet in ein PDF
(ZUGFeRD/Factur-X).

Lesen und Schreiben verwenden dieselbe Bibliothek (``drafthorse``):

* Die Feldnamen folgen der Norm;
  ``settlement.monetary_summation.tax_basis_total`` ist BT-109. Eigene
  XPath-Ausdrücke wären eine zweite Auslegung, deren Abweichungen von der
  Norm schwer zu finden sind.
* Datumsformate (``format="102"``), Dezimaltypen, Einheitencodes und
  Namespaces pflegt die Bibliothek, auch bei neuen Fassungen des Formats.

Nur CII. XRechnung erlaubt auch UBL; ein zweiter Leseweg ohne Bedarf
entfällt. Eine UBL-Datei wird mit einer Meldung abgelehnt (``_SYNTAX_UBL``).

Das Modul validiert nicht gegen die Norm, es liest die vorhandenen Werte.
Der Benutzer sieht sie im Formular, bevor gespeichert wird.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from io import BytesIO

from drafthorse.models.document import Document

from core import rechnen
from core.exceptions import FachlicherFehler

#: Rechnung nach UN/EDIFACT 1001, der einzige unterstützte Typ.
#
# 381 (Gutschrift) wird abgelehnt, weil ``Eingangsrechnung`` keine
# Gutschriften abbildet; ein negativer Betrag in "Rechnungsbetrag netto"
# fiele erst in der Projektauswertung auf.
TYP_RECHNUNG = '380'

#: Dateinamen des eingebetteten XML in einem PDF, in dieser Reihenfolge.
#
# ``factur-x.xml`` schreibt Factur-X vor; diese Anwendung verwendet ihn auch
# (``facturx.XML_DATEINAME``). Die beiden anderen stammen aus älteren
# Erzeugern, etwa ZUGFeRD 1.0.
#
# Kleingeschrieben, weil der Vergleich ohne Groß- und Kleinschreibung
# erfolgt ("ZUGFeRD-invoice.xml").
PDF_ANHANG_NAMEN = (
    'factur-x.xml',
    'zugferd-invoice.xml',
    'xrechnung.xml',
)

#: Wurzelelement einer UBL-Rechnung, um sie mit Meldung abzulehnen.
_SYNTAX_UBL = '{urn:oasis:names:specification:ubl:schema:xsd:Invoice-2}Invoice'
_SYNTAX_UBL_GUTSCHRIFT = (
    '{urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2}CreditNote')

#: Nachkommastellen eines Einkaufspreises, wie ``Fremdleistung.einkaufspreis``.
VIER_STELLEN = Decimal('0.0001')

#: Einheitencodes nach UN/ECE Recommendation 20 und ihre Schreibweise.
#
# Eigene Tabelle, weil in ``facturx.EINHEIT_CODE`` mehrere Schreibweisen auf
# denselben Code zeigen ('stk', 'stck', 'st' und 'pauschal' auf C62); eine
# Umkehrung hinge von der Reihenfolge des Dicts ab. Hier steht je Code die
# Schreibweise dieser Anwendung.
EINHEIT_KLARTEXT = {
    'C62': 'Stk',
    'HUR': 'Std',
    'DAY': 'Tag',
    'KMT': 'km',
    'MTR': 'm',
    'MTK': 'm2',
    'MTQ': 'm3',
    'KGM': 'kg',
    'LTR': 'l',
}


class ERechnungFehler(FachlicherFehler):
    """Die Datei lässt sich nicht als Eingangsrechnung lesen.

    Erbt von ``FachlicherFehler`` wie ``FacturxFehler``, damit sie im Admin
    zu einer Meldung und in der API zu einer 4xx-Antwort wird.
    """


@dataclass(frozen=True)
class GelesenePosition:
    """Zeile aus dem XML, noch ohne Vorhaben.

    Entspricht ``Fremdleistung`` bis auf das Vorhaben, das nicht im
    Dokument steht und beim Hochladen gewählt wird.
    """

    bezeichnung: str
    menge: Decimal
    einheit: str
    #: Preis je Einheit auf vier Stellen, bei einer Preisbasismenge
    #: (BT-149, "0,85 € je 100 m") bereits umgerechnet.
    einzelpreis: Decimal
    #: Zeilenbetrag (BT-131), maßgeblich vor Menge mal Preis, weil er
    #: Rabatte und Zuschläge der Zeile enthält.
    betrag: Decimal


@dataclass(frozen=True)
class GeleseneRechnung:
    """Ergebnis des Einlesens.

    Die ersten vier Felder sind die von ``Eingangsrechnung``. ``sonstiges``
    enthält weitere Angaben ohne eigenes Feld (Bruttobetrag, Umsatzsteuer,
    Fälligkeit, IBAN, Anschrift); sie werden als Text in die Notiz
    übernommen, weil die Datei selbst nicht gespeichert wird.
    """

    nummer: str
    datum: date
    lieferant: str
    betrag_netto: Decimal
    positionen: list[GelesenePosition] = field(default_factory=list)
    sonstiges: dict[str, str] = field(default_factory=dict)
    #: Projektreferenz (BT-11), leer ohne Angabe des Lieferanten. Daraus wird
    #: beim Hochladen das Projekt vorgeschlagen.
    projektreferenz: str = ''
    #: Ob das XML aus einem PDF stammt.
    #
    # Steht in der Notiz, damit die Herkunft der Werte nachvollziehbar ist.
    aus_pdf: bool = False
    #: Bruttobetrag (BT-112), nur zur Information; gerechnet wird netto.
    betrag_brutto: Decimal | None = None
    #: Fälligkeit (BT-9) aus der ersten Zahlungsbedingung.
    faellig_am: date | None = None

    @property
    def positionssumme(self) -> Decimal:
        """Summe der Zeilenbeträge (BT-131) zum Abgleich mit dem Kopfbetrag.

        Verbindlich bleibt der Kopfbetrag (BT-109), wie bei einer von Hand
        erfassten Rechnung; die Summe dient der Anzeige von Abweichungen.
        """
        return sum((p.betrag for p in self.positionen), Decimal('0.00'))


def ist_pdf(daten: bytes) -> bool:
    """Ob die Datei ein PDF ist, anhand der ersten fünf Bytes.

    Die Dateiendung wird nicht ausgewertet, weil sie nicht zum Inhalt
    passen muss.
    """
    return daten.lstrip()[:5] == b'%PDF-'


def lesen(daten: bytes) -> GeleseneRechnung:
    """Liest eine E-Rechnung als XML oder als PDF mit eingebettetem XML.

    Wirft ``ERechnungFehler`` bei ungültigem XML, PDF ohne eingebettete
    Daten, UBL, Gutschrift, Fremdwährung oder fehlenden Pflichtangaben.
    """
    aus_pdf = ist_pdf(daten)
    doc = _parsen(daten)
    _typ_pruefen(doc)
    _waehrung_pruefen(doc)

    return GeleseneRechnung(
        aus_pdf=aus_pdf,
        nummer=_pflicht(_text(doc.header.id), 'die Rechnungsnummer (BT-1)'),
        datum=_pflicht(_zahl(doc.header.issue_date_time),
                       'das Rechnungsdatum (BT-2)'),
        lieferant=_pflicht(_text(doc.trade.agreement.seller.name),
                           'der Name des Lieferanten (BT-27)'),
        betrag_netto=_betrag_netto(doc),
        positionen=_positionen(doc),
        sonstiges=_sonstiges(doc),
        projektreferenz=_text(
            doc.trade.agreement.procuring_project_type.id),
        betrag_brutto=_brutto(doc),
        faellig_am=_faellig_am(doc),
    )


def enthaelt_erechnung(daten: bytes) -> bool:
    """Ob die Datei eine E-Rechnung enthält, ohne sie zu lesen.

    Vorprüfung für das Archiv: Ein PDF ohne XML ist dort der Regelfall und
    geht über die Texterkennung. Ob das XML lesbar ist, prüft ``lesen``.
    Ein PDF, das sich nicht öffnen lässt, gilt als keine E-Rechnung.
    """
    if not daten or not daten.strip():
        return False
    if not ist_pdf(daten):
        return daten.lstrip()[:1] == b'<'
    try:
        return _xml_anhang(daten) is not None
    except ERechnungFehler:
        return False


# ══════════════════════════════════════════════════════════════════════════
# Zugriff auf die Werte
#
# drafthorse hat keine öffentliche API zum Lesen; die Bibliothek ist auf
# das Schreiben ausgelegt. Die Werte liegen je nach Elementtyp unter
# ``_value`` (DecimalElement, DateTimeElement, StringElement), ``_amount``
# (CurrencyElement, QuantityElement) oder ``_text`` (IDElement).
#
# ``str()`` scheidet aus, weil ``DecimalElement.__str__`` ein Decimal
# zurückgibt und Python "TypeError: __str__ returned non-string" wirft. Der
# Zugriff ist deshalb in den beiden Hilfsfunktionen gekapselt.
# ══════════════════════════════════════════════════════════════════════════

def _roh(element):
    """Wert eines drafthorse-Elements oder ``None``.

    Leere Elemente enthalten je nach Typ ``None`` oder ``''``; beides wird
    zu ``None``.
    """
    if element is None:
        return None
    for name in ('_value', '_amount', '_text'):
        wert = getattr(element, name, None)
        if wert is not None and wert != '':
            return wert
    return None


def _text(element) -> str:
    wert = _roh(element)
    return str(wert).strip() if wert is not None else ''


def _zahl(element):
    """Decimal oder date aus dem Element, unverändert."""
    return _roh(element)


def _pflicht(wert, was: str):
    if not wert:
        raise ERechnungFehler(
            f'In der Datei fehlt {was}. Ohne diese Angabe lässt sich '
            f'daraus keine Eingangsrechnung machen.')
    return wert


# ══════════════════════════════════════════════════════════════════════════
# Einzelschritte
# ══════════════════════════════════════════════════════════════════════════

def _parsen(daten: bytes) -> Document:
    """Parst die Bytes zu einem Dokument oder wirft ``ERechnungFehler``.

    Mit ``strict=False``, weil fremde Erzeuger Elemente schreiben, die
    drafthorse nicht kennt (Profilerweiterungen, Extended-Felder, eigene
    Referenzen); mit ``strict=True`` wirft die Bibliothek dafür einen
    TypeError.
    """
    if not daten or not daten.strip():
        raise ERechnungFehler('Die Datei ist leer.')

    # Ein PDF ist der Regelfall: Eine E-Rechnung nach Factur-X ist ein PDF
    # mit eingebettetem XML, das hier extrahiert wird.
    if ist_pdf(daten):
        daten = _xml_aus_pdf(daten)

    try:
        wurzel_tag = _wurzel_tag(daten)
    except Exception as fehler:
        raise ERechnungFehler(
            f'Die Datei lässt sich nicht als XML lesen: {fehler}'
        ) from fehler

    if wurzel_tag in (_SYNTAX_UBL, _SYNTAX_UBL_GUTSCHRIFT):
        raise ERechnungFehler(
            'Das ist eine E-Rechnung in der UBL-Syntax. Gelesen wird hier '
            'nur die CII-Syntax (UN/CEFACT), dieselbe, die auch in einem '
            'ZUGFeRD-PDF steckt. Viele Erzeuger können beides ausgeben; '
            'bitte den Lieferanten um die CII-Fassung bitten.')

    try:
        return Document.parse(daten, strict=False)
    except Exception as fehler:
        raise ERechnungFehler(
            f'Die Datei ist keine E-Rechnung in der CII-Syntax: {fehler}'
        ) from fehler


def _xml_aus_pdf(daten: bytes) -> bytes:
    """Extrahiert das eingebettete XML aus einem ZUGFeRD- oder Factur-X-PDF.

    Mit pypdf, weil das ``pdf``-Modul von drafthorse XML nur anhängen kann
    (``attach_xml``). pypdf ist ohnehin eine Abhängigkeit von drafthorse.

    Gesucht wird zuerst unter den vorgeschriebenen Namen (``factur-x.xml``),
    danach in jedem Anhang, der mit XML beginnt, weil manche Erzeuger andere
    Namen verwenden; ob es eine Rechnung ist, zeigt das Parsen.

    Ob das XML CII oder UBL ist, prüft danach ``_parsen``, damit ein PDF mit
    UBL dieselbe Meldung erhält wie eine UBL-Datei.
    """
    xml = _xml_anhang(daten)
    if xml is not None:
        return xml

    raise ERechnungFehler(
        'In diesem PDF steckt keine E-Rechnung. Ein gewöhnliches PDF, auch '
        'ein eingescanntes oder ein sauber gesetztes, trägt nur das Bild '
        'der Rechnung; bei einer E-Rechnung liegen die Daten als XML *im* '
        'PDF. Diese hier gehört von Hand erfasst oder über das Archiv '
        'übernommen.')


def _xml_anhang(daten: bytes) -> bytes | None:
    """XML-Anhang eines PDFs oder ``None``.

    Wirft ``ERechnungFehler`` nur, wenn sich das PDF nicht öffnen lässt.
    """
    from pypdf import PdfReader

    try:
        anhaenge = PdfReader(BytesIO(daten)).attachments
    except Exception as fehler:
        raise ERechnungFehler(
            f'Das PDF lässt sich nicht öffnen: {fehler}') from fehler

    # Ein Name kann mehrfach vorkommen, pypdf liefert je Name eine Liste;
    # verwendet wird der erste nicht leere Eintrag.
    nach_namen = {name.lower(): inhalte for name, inhalte in anhaenge.items()}

    for name in PDF_ANHANG_NAMEN:
        for inhalt in nach_namen.get(name, []):
            if inhalt:
                return inhalt

    for inhalte in anhaenge.values():
        for inhalt in inhalte:
            if inhalt and inhalt.lstrip()[:1] == b'<':
                return inhalt

    return None


def _wurzel_tag(daten: bytes) -> str:
    """Wurzelelement zur Unterscheidung von CII und UBL.

    Mit lxml, weil drafthorse damit parst; eine zweite XML-Bibliothek
    könnte Kodierung und Namespaces anders behandeln.
    """
    from lxml import etree

    return etree.fromstring(daten).tag


def _typ_pruefen(doc: Document) -> None:
    typ = _text(doc.header.type_code)
    if typ == TYP_RECHNUNG:
        return
    if typ in ('381', '384', '389'):
        raise ERechnungFehler(
            f'Das Dokument ist keine Rechnung, sondern eine Gutschrift oder '
            f'Korrektur (Typ {typ}). Solche Belege werden hier von Hand '
            f'erfasst; eine Eingangsrechnung kennt nur den Rechnungsfall.')
    raise ERechnungFehler(
        f'Unbekannte Dokumentenart "{typ}". Eingelesen wird nur die '
        f'Rechnung (Typ {TYP_RECHNUNG}).')


def _waehrung_pruefen(doc: Document) -> None:
    """Lehnt Rechnungen in anderer Währung als Euro ab.

    Das Modell hat kein Währungsfeld und rechnet in Euro; ohne Prüfung
    würden 800 Franken zu 800 Euro.
    """
    waehrung = _text(doc.trade.settlement.currency_code).upper()
    if waehrung and waehrung != 'EUR':
        raise ERechnungFehler(
            f'Die Rechnung ist in {waehrung} ausgestellt. Dieses Programm '
            f'rechnet in Euro; eine Fremdwaehrungsrechnung gehört '
            f'umgerechnet und von Hand erfasst.')


def _betrag_netto(doc: Document) -> Decimal:
    """Nettobetrag aus BT-109, ersatzweise BT-106.

    BT-109 (``TaxBasisTotalAmount``) ist die Bemessungsgrundlage der Steuer
    einschließlich Zu- und Abschlägen auf Dokumentebene und entspricht dem
    Betrag von ``Eingangsrechnung``. BT-106 (``LineTotalAmount``, Summe der
    Zeilen) gilt nur, wenn BT-109 fehlt; beide weichen bei Skonto oder
    Versandpauschale voneinander ab.
    """
    summen = doc.trade.settlement.monetary_summation
    betrag = _zahl(summen.tax_basis_total)
    if betrag is None:
        betrag = _zahl(summen.line_total)
    if betrag is None:
        raise ERechnungFehler(
            'In der Datei steht kein Nettobetrag (BT-109 oder BT-106). '
            'Ohne ihn fehlt die Größe, gegen die dieses Programm die '
            'Zuordnung prüft.')
    return rechnen.auf_cent(betrag)


def _brutto(doc: Document) -> Decimal | None:
    """BT-112 auf Cent gerundet oder ``None``, wenn er fehlt."""
    betrag = _zahl(doc.trade.settlement.monetary_summation.grand_total)
    return rechnen.auf_cent(betrag) if betrag is not None else None


def _faellig_am(doc: Document) -> date | None:
    """BT-9 aus der ersten Zahlungsbedingung, die eine Fälligkeit nennt."""
    for bedingung in doc.trade.settlement.terms.children:
        faellig = _zahl(bedingung.due)
        if faellig:
            return faellig
    return None


def _positionen(doc: Document) -> list[GelesenePosition]:
    """Zeilen des Dokuments ohne unvollständige.

    Übergangen wird eine Zeile ohne Menge oder Preis, weil daraus keine
    ``Fremdleistung`` entstehen kann. Die Rechnung wird trotzdem
    übernommen; der Kopfbetrag bleibt, und der Rest steht offen.

    Zwei Fälle, in denen Menge mal Preis falsch wäre:

    * Die Preisbasismenge (BT-149): "0,85 € je 100 m" heißt 0,0085 € je
      Meter. Der Preis wird deshalb durch die Basismenge geteilt.
    * Rabatt oder Zuschlag auf der Zeile (BT-136, BT-141): 10 zu 50,00
      abzüglich 10 % sind 450,00. Maßgeblich ist deshalb der Zeilenbetrag
      (BT-131); fehlt er, gilt Menge mal Preis.
    """
    gelesen = []
    for zeile in doc.trade.items.children:
        menge = _zahl(zeile.delivery.billed_quantity)
        preis = _zahl(zeile.agreement.net.amount)
        if menge is None or preis is None:
            continue
        menge = Decimal(menge)
        basis = _zahl(zeile.agreement.net.basis_quantity)
        if basis:
            preis = Decimal(preis) / Decimal(basis)
        einzelpreis = rechnen.auf_stufe(preis, VIER_STELLEN)
        betrag = _zahl(zeile.settlement.monetary_summation.total_amount)
        code = getattr(zeile.delivery.billed_quantity, '_unit_code', '') or ''
        gelesen.append(GelesenePosition(
            bezeichnung=_text(zeile.product.name) or 'Ohne Bezeichnung',
            menge=menge,
            einheit=EINHEIT_KLARTEXT.get(code.upper(), code),
            einzelpreis=einzelpreis,
            betrag=(rechnen.auf_cent(betrag) if betrag is not None
                    else rechnen.auf_cent(menge * einzelpreis)),
        ))
    return gelesen


def _sonstiges(doc: Document) -> dict[str, str]:
    """Angaben des Dokuments ohne eigenes Feld.

    Reihenfolge: Beträge (für die Zahlung gesucht), Fristen, Stammdaten des
    Lieferanten, Referenzen. Leere Angaben entfallen.
    """
    handel = doc.trade
    summen = handel.settlement.monetary_summation
    verkaeufer = handel.agreement.seller

    eintraege: dict[str, str] = {}

    def merken(bezeichnung: str, wert) -> None:
        if wert is None or wert == '':
            return
        eintraege[bezeichnung] = (
            f'{wert:.2f}' if isinstance(wert, Decimal)
            else wert.strftime('%d.%m.%Y') if isinstance(wert, date)
            else str(wert)
        )

    merken('Bruttobetrag', _zahl(summen.grand_total))
    merken('Umsatzsteuer', _umsatzsteuer(doc))
    merken('Zahlbetrag', _zahl(summen.due_amount))
    merken('Steuersaetze', _steuersaetze(doc))

    merken('Leistungsdatum', _zahl(handel.delivery.event.occurrence))
    for bedingung in handel.settlement.terms.children:
        merken('Fällig am', _zahl(bedingung.due))
        merken('Zahlungsbedingungen', _text(bedingung.description))

    merken('IBAN', _iban(doc))
    merken('Anschrift', _anschrift(verkaeufer))
    merken('USt-IdNr.', _steuerkennung(verkaeufer, 'VA'))
    merken('Steuernummer', _steuerkennung(verkaeufer, 'FC'))

    merken('Bestellnummer',
           _text(handel.agreement.buyer_order.issuer_assigned_id))
    merken('Projektreferenz',
           _text(handel.agreement.procuring_project_type.id))
    merken('Leitweg-ID', _text(handel.agreement.buyer_reference))
    merken('Anmerkungen', ' | '.join(
        t for t in (_text(n.content) for n in doc.header.notes.children) if t))

    return eintraege


def _umsatzsteuer(doc: Document) -> Decimal | None:
    """Umsatzsteuer als Summe der Steuerzeilen (BT-117).

    ``tax_total`` ist beim Lesen leer: ``MonetarySummation`` definiert zwei
    Felder mit dem XML-Tag ``TaxTotalAmount``, ``tax_total``
    (CurrencyField) und ``tax_total_other_currency`` (MultiCurrencyField
    für Fremdwährung im Profil Extended). ``Element.from_etree`` baut einen
    Index nach Tag, in dem das später definierte Feld das frühere
    überschreibt; der Wert landet in ``tax_total_other_currency``.

    Geprüft mit drafthorse 2025.2 (``test_erechnung.py``). Die Summe der
    Steuerzeilen hängt nicht von dieser Reihenfolge ab und gilt auch bei
    mehreren Steuersätzen.
    """
    zeilen = [_zahl(st.calculated_amount)
              for st in doc.trade.settlement.trade_tax.children]
    vorhanden = [Decimal(z) for z in zeilen if z is not None]
    if not vorhanden:
        return None
    return rechnen.auf_cent(sum(vorhanden, Decimal('0.00')))


def _steuersaetze(doc: Document) -> str:
    """Steuersätze als Text, etwa "19,00 %" oder "7,00 % / 19,00 %"."""
    saetze = {_zahl(st.rate_applicable_percent)
              for st in doc.trade.settlement.trade_tax.children}
    vorhanden = sorted(Decimal(s) for s in saetze if s is not None)
    return ' / '.join(f'{s:.2f} %'.replace('.', ',') for s in vorhanden)


def _iban(doc: Document) -> str:
    for mittel in doc.trade.settlement.payment_means.children:
        iban = _text(mittel.payee_account.iban)
        if iban:
            return iban
    return ''


def _anschrift(partei) -> str:
    """Anschrift in einer Zeile für die Notiz."""
    adresse = partei.address
    teile = [
        _text(adresse.line_one),
        ' '.join(t for t in (_text(adresse.postcode),
                             _text(adresse.city_name)) if t),
        _text(adresse.country_id),
    ]
    return ', '.join(t for t in teile if t)


def _steuerkennung(partei, schema: str) -> str:
    """USt-IdNr. (VA) oder Steuernummer (FC), mit denselben Scheme-IDs wie
    ``facturx._steuerkennung``."""
    for eintrag in partei.tax_registrations.children:
        if getattr(eintrag.id, '_scheme_id', '') == schema:
            return _text(eintrag.id)
    return ''


def notiz_bauen(gelesen: GeleseneRechnung, dateiname: str = '') -> str:
    """Text der Notiz aus ``sonstiges``.

    Als Klartext, weil die Notiz für Menschen ist; maschinell verarbeitete
    Angaben bräuchten ein eigenes Feld.
    """
    herkunft = [t for t in (dateiname,
                            'XML aus dem PDF geholt' if gelesen.aus_pdf else '')
                if t]
    kopf = 'Aus E-Rechnung eingelesen'
    if herkunft:
        kopf += f' ({", ".join(herkunft)})'
    zeilen = [f'{kopf}:']
    zeilen += [f'{name}: {wert}' for name, wert in gelesen.sonstiges.items()]
    return '\n'.join(zeilen)
