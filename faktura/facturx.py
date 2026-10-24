"""Erzeugung des XML nach EN 16931 für Factur-X und XRechnung.

Eine E-Rechnung nach Factur-X (in Deutschland ZUGFeRD) ist ein PDF mit
eingebettetem XML nach EN 16931. Seite und XML müssen denselben Inhalt
haben; das ist Voraussetzung für die Zulässigkeit des Formats.

Rechtlicher Hintergrund: Seit dem 1. Januar 2025 müssen inländische
Unternehmen E-Rechnungen **empfangen** können. Die Pflicht, sie auch zu
**versenden**, greift gestaffelt ab 2027 (Vorjahresumsatz über 800.000 EUR)
und ab 2028 für alle.

Das XML entsteht mit ``drafthorse``, weil EN 16931 mehrere hundert Felder mit
Abhängigkeiten hat; die Bibliothek bildet die Struktur ab und validiert
gegen das amtliche XSD.

Nicht geprüft werden die Schematron-Regeln von EN 16931 (BR-*, BR-CO-*),
die fachliche Zusammenhänge über das Schema hinaus prüfen. Ein öffentlicher
Validierungsdienst ist in der Dokumentation der Templates genannt.
"""

import io
import re
from decimal import Decimal

from django.conf import settings
from drafthorse.models.accounting import ApplicableTradeTax
from drafthorse.models.document import Document
from drafthorse.models.note import IncludedNote
from drafthorse.models.party import TaxRegistration
from drafthorse.models.payment import PaymentMeans, PaymentTerms
from drafthorse.models.tradelines import LineItem

from core import rechnen
from core.exceptions import FachlicherFehler

from . import services
from . import steuerfall as steuerfall_modul
from .models import STEUERFREI, BelegStatus, BelegTyp, Firma, Zeilenart

#: Dateiname des Anhangs, von Factur-X vorgeschrieben; daran erkennen
#: Leseprogramme das XML.
XML_DATEINAME = 'factur-x.xml'

#: Kennung des Profils. EN 16931 ("Comfort") deckt alle Pflichtangaben der
#: Richtlinie ab.
PROFIL = 'urn:cen.eu:en16931:2017'
PROFIL_NAME = 'EN 16931'

# --- XRechnung ---
#
# XRechnung ist die deutsche CIUS von EN 16931 in derselben CII-Syntax.
# Abweichend sind die Kennung und einige Pflichtfelder (Regeln BR-DE-*),
# die EN 16931 offen lässt.
#
# Gewählt über den Zustellweg am Kunden (ist_xrechnung()). Öffentliche
# Auftraggeber verlangen sie; ihre Rechnungsportale nehmen oft nur das XML
# an.
PROFIL_XRECHNUNG = ('urn:cen.eu:en16931:2017#compliant'
                    '#urn:xeinkauf.de:kosit:xrechnung_3.0')
PROFIL_NAME_XRECHNUNG = 'XRECHNUNG'
#: Name des Anhangs im Profil XRECHNUNG, von ZUGFeRD vorgeschrieben; daran
#: erkennen Leseprogramme das Profil.
XML_DATEINAME_XRECHNUNG = 'xrechnung.xml'
#: BT-23, der Geschäftsprozess. EN 16931 lässt ihn offen, der
#: KoSIT-Prüfer verlangt ihn bei XRechnung (PEPPOL-EN16931-R001). Der Wert
#: ist der Standardprozess "Rechnung" aus Peppol BIS Billing 3.0.
GESCHAEFTSPROZESS_XRECHNUNG = 'urn:fdc:peppol.eu:2017:poacc:billing:01:1.0'

#: Aufbau einer Leitweg-ID: Grobadressierung (2 bis 12 Ziffern), optional
#: Feinadressierung (bis 30 Zeichen), Prüfziffer (2 Ziffern), getrennt durch
#: Bindestriche. Die Prüfziffer wird nicht berechnet, weil das Muster nur
#: eine Leitweg-ID von einer gewöhnlichen Käuferreferenz ("KST-4711")
#: unterscheidet.
LEITWEG_ID_MUSTER = re.compile(r'\d{2,12}(-[A-Za-z0-9]{1,30})?-\d{2}')

#: Schema der elektronischen Adresse (BT-34/BT-49) nach der EAS-Liste.
#: 'EM' ist eine E-Mail-Adresse, '0204' eine Leitweg-ID.
ADRESSSCHEMA_EMAIL = 'EM'
ADRESSSCHEMA_LEITWEG = '0204'

#: Dokumentenarten nach UN/EDIFACT 1001.
#:
#: Storno und Rechnungskorrektur sind beide Gutschriften (381), weil die
#: Richtlinie für beide Vorgänge einen Code hat; der Unterschied steht im
#: Belegtext.
TYP_CODE = {
    BelegTyp.RECHNUNG: '380',
    BelegTyp.STORNO: '381',
    BelegTyp.GUTSCHRIFT: '381',
}

#: Corrected invoice, für das Storno einer Rechnungskorrektur.
TYPCODE_KORRIGIERT = '384'

#: Belegtypen, die im XML auf ihren Vorgänger verweisen (BG-3).
GEGENBELEGE = (BelegTyp.STORNO, BelegTyp.GUTSCHRIFT)

def typcode(beleg) -> str:
    """BT-3 des Belegs. Bei Rechnungen aus der Zuordnung von Rechnungsart zu
    Code in den Settings (``ERECHNUNG_TYPCODE``); die Fachlogik kennt nur
    die Rechnungsart."""
    if beleg.typ == BelegTyp.RECHNUNG:
        return settings.ERECHNUNG_TYPCODE.get(beleg.rechnungsart,
                                              TYP_CODE[beleg.typ])
    # Das Storno einer Rechnungskorrektur berichtigt die Korrektur und stellt
    # die Forderung wieder her, mit positiven Beträgen: korrigierte Rechnung
    # (384). Mit 381 kehrte ``vorzeichen`` die Beträge im XML um
    # (entscheidungen.md, „Rechnungskorrektur und Nachlass“).
    if (beleg.typ == BelegTyp.STORNO and beleg.vorgaenger_id
            and beleg.vorgaenger.typ == BelegTyp.GUTSCHRIFT):
        return TYPCODE_KORRIGIERT
    return TYP_CODE[beleg.typ]


#: Zuordnung von Belegfeldern zu BT-Nummern für die Beschriftung
#: "Feldname (BT-xxx)" in den Masken der Steuerbelege. Nur Felder, die
#: ``xml_erzeugen`` schreibt; neue Felder dort hier ergänzen.
BT_BELEG = {
    'rechnungsart': 'BT-3',
    'belegdatum': 'BT-2',
    'leitweg_id': 'BT-10',
    'projekt': 'BT-11',
    'bestellnummer': 'BT-13',
    'betreff': 'BT-22',
    'empfaenger_name': 'BT-44',
    'empfaenger_ust_id': 'BT-48',
    'empfaenger_strasse': 'BT-50',
    'empfaenger_ort': 'BT-52',
    'empfaenger_plz': 'BT-53',
    'empfaenger_land': 'BT-55',
    'steuerliches_leistungsdatum': 'BT-72',
    'leistungsdatum': 'BT-73',
    'leistungsdatum_bis': 'BT-74',
}
BT_POSITION = {
    'leistung_von': 'BT-134',
    'leistung_bis': 'BT-135',
    'menge': 'BT-129',
    'einheit': 'BT-130',
    'einzelpreis': 'BT-146',
    'steuersatz': 'BT-152',
    'bezeichnung': 'BT-153',
}


def mit_bt(beschriftung: str, feldname: str, tabelle: dict) -> str:
    """Ergänzt die BT-Nummer ("Menge" wird "Menge (BT-129)"); unverändert,
    wenn das Feld nicht in die E-Rechnung geht."""
    nummer = tabelle.get(feldname)
    return f'{beschriftung} ({nummer})' if nummer else beschriftung


#: Einheiten nach UN/ECE Recommendation 20, weil Freitext wie "Stk" im XML
#: unzulässig ist.
EINHEIT_CODE = {
    'stk': 'C62',    # Stück
    'stck': 'C62',
    'st': 'C62',
    'std': 'HUR',    # Stunde
    'h': 'HUR',
    'tag': 'DAY',
    'tage': 'DAY',
    'km': 'KMT',
    'm': 'MTR',
    'm2': 'MTK',
    'm3': 'MTQ',
    'kg': 'KGM',
    'l': 'LTR',
    'pauschal': 'C62',
}
EINHEIT_STANDARD = 'C62'

#: Steuerkategorien nach UNTDID 5305.
KATEGORIE_STANDARD = 'S'      # Regelbesteuerung
KATEGORIE_BEFREIT = 'E'       # steuerbefreit, Grund ist anzugeben

#: Zahlungsart 58 = SEPA-Überweisung.
ZAHLUNGSART_UEBERWEISUNG = '58'
#: Zahlungsart 1 = nicht festgelegt, für Gutschriften in der XRechnung.
#: BR-DE-1 verlangt immer eine Zahlungsanweisung; bei einer Gutschrift zahlt
#: aber der Aussteller, eine Überweisung auf sein Konto wäre falsch.
ZAHLUNGSART_OFFEN = '1'


class FacturxFehler(FachlicherFehler):
    """Das XML lässt sich nicht erzeugen, meist wegen fehlender Stammdaten.

    Erbt von FachlicherFehler, damit
    core.exception_handler.api_exception_handler ihn in eine 4xx-Antwort
    übersetzt.
    """


def ist_erechnungsfaehig(beleg) -> bool:
    """Ob zu diesem Beleg ein Factur-X-XML gehört.

    Nur Steuerbelege mit Nummer: Ein Angebot ist keine Rechnung, und ein
    Entwurf hat keine Nummer, die das XML braucht.
    """
    return (
        beleg.typ in TYP_CODE
        and beleg.status != BelegStatus.ENTWURF
        and bool(beleg.nummer)
    )


def ist_xrechnung(beleg) -> bool:
    """Ob der Beleg als XRechnung entsteht; maßgeblich ist der Zustellweg
    des Kunden.

    Beim Festschreiben mit dem XML gespeichert (``Beleg.erechnungsprofil``).
    Ohne Kunden (Anschrift von Hand) nie.
    """
    from .models import Zustellweg

    kunde = kunde_des_belegs(beleg)
    return kunde is not None and kunde.zustellweg == Zustellweg.XRECHNUNG


def kunde_des_belegs(beleg):
    """Kunde, dessen Zustellweg gilt, direkt am Beleg oder über das Projekt.
    None bei einer Anschrift von Hand."""
    return beleg.kunde or (beleg.projekt.kunde if beleg.projekt_id else None)


def profilname(beleg) -> str:
    """Name des Profils in den PDF-Metadaten und am Beleg."""
    return PROFIL_NAME_XRECHNUNG if ist_xrechnung(beleg) else PROFIL_NAME


def anhangname(beleg) -> str:
    """Name des XML-Anhangs im PDF, je nach Profil vorgeschrieben."""
    return XML_DATEINAME_XRECHNUNG if ist_xrechnung(beleg) else XML_DATEINAME


def ist_leitweg_id(wert: str) -> bool:
    """Ob die Käuferreferenz die Form einer Leitweg-ID hat."""
    return bool(LEITWEG_ID_MUSTER.fullmatch((wert or '').strip()))


def zustellweg_warnung(beleg) -> str:
    """Warnung bei voraussichtlich falschem Profil, leer, wenn alles passt.

    * **Vor dem Festschreiben:** Der Beleg hat eine Leitweg-ID, der Kunde
      aber nicht den Zustellweg XRechnung. Leitweg-IDs haben öffentliche
      Auftraggeber, die meist nur XRechnung annehmen; es entstünde ein
      ZUGFeRD-PDF, das das Portal ablehnt.
    * **Nach dem Festschreiben:** Das gespeicherte Profil passt nicht mehr
      zum Zustellweg, weil der Kunde umgestellt wurde. Die Rechnung bleibt
      unverändert, bis sie neu ausgestellt wird.

    Nur eine Warnung, weil manche Behörden ZUGFeRD annehmen.
    """
    if beleg.typ not in TYP_CODE:
        return ''

    if beleg.xml:
        ausgestellt = beleg.erechnungsprofil == PROFIL_NAME_XRECHNUNG
        heute = ist_xrechnung(beleg)
        if ausgestellt == heute:
            return ''
        if heute:
            return ('Diese Rechnung wurde als PDF mit eingebetteter '
                    'E-Rechnung (ZUGFeRD) ausgestellt, der Kunde steht '
                    'inzwischen auf XRechnung. Damit sie als XRechnung '
                    'hinausgeht: „E-Rechnung neu ausstellen“.')
        return ('Diese Rechnung wurde als XRechnung ausgestellt, der Kunde '
                'steht inzwischen nicht mehr auf XRechnung. Damit sie als '
                'PDF hinausgeht: „E-Rechnung neu ausstellen“.')

    if beleg.ist_aenderbar and ist_leitweg_id(beleg.leitweg_id) \
            and not ist_xrechnung(beleg):
        return (f'Die Käuferreferenz {beleg.leitweg_id} ist eine '
                f'Leitweg-ID, also ein öffentlicher Auftraggeber. Der Kunde '
                f'steht aber nicht auf XRechnung, die Rechnung entstünde als '
                f'ZUGFeRD-PDF und würde von einem Rechnungsportal meist '
                f'abgewiesen. Vorher am Kunden den Zustellweg auf '
                f'„XRechnung“ stellen.')
    return ''


def einheit_code(einheit: str) -> str:
    return EINHEIT_CODE.get((einheit or '').strip().lower(), EINHEIT_STANDARD)


def _anschrift_zerlegen(empfaenger: str) -> tuple[str, str, str, str]:
    """Zerlegt das freie Empfängerfeld in (Name, Straße, PLZ, Ort).

    Heuristik nach deutschem Anschriftenmuster: erste Zeile Name, letzte
    Zeile "PLZ Ort", was dazwischen liegt wird zur Straßenzeile
    zusammengezogen. Beginnt die letzte Zeile nicht mit Ziffern, gilt sie
    als Ort ohne PLZ.

    Nur Fallback für Belege ohne strukturierte Felder (empfaenger_name usw.),
    die sonst beim Anlegen aus den Stammdaten kommen.
    """
    zeilen = [z.strip() for z in empfaenger.splitlines() if z.strip()]
    if not zeilen:
        return '', '', '', ''

    name = zeilen[0]
    strasse, plz, ort = '', '', ''

    if len(zeilen) > 1:
        letzte = zeilen[-1]
        teile = letzte.split(maxsplit=1)
        if teile and teile[0].isdigit():
            plz = teile[0]
            ort = teile[1] if len(teile) > 1 else ''
        else:
            ort = letzte
        strasse = ', '.join(zeilen[1:-1])

    return name, strasse, plz, ort


def xml_erzeugen(beleg) -> bytes:
    """Erzeugt das Factur-X-XML und prüft es gegen das amtliche XSD."""
    firma = Firma.aktuelle()
    if firma is None:
        raise FacturxFehler(
            'Für die E-Rechnung fehlen die eigenen Firmendaten. '
            'Bitte unter "Firma" anlegen.'
        )
    if not (firma.ust_id or firma.steuernummer):
        raise FacturxFehler(
            'Für die E-Rechnung wird die USt-IdNr. oder die Steuernummer '
            'der eigenen Firma gebraucht (§ 14 Abs. 4 Nr. 2 UStG).'
        )
    if not (beleg.steuerliches_leistungsdatum or beleg.leistungszeitraum):
        raise FacturxFehler(
            'Für die E-Rechnung wird das Leistungsdatum gebraucht '
            '(§ 14 Abs. 4 Nr. 6 UStG).'
        )

    xrechnung = ist_xrechnung(beleg)
    if xrechnung:
        _xrechnung_pruefen(beleg, firma)
    regel = steuerfall_modul.regel(beleg.steuerfall)
    if regel:
        _steuerfall_pruefen(beleg, firma, regel)

    summen = services.belegsummen(beleg)
    # Volle Leistung ohne abgesetzte Abschläge, die im XML als BT-113 stehen.
    # Ohne Abzugszeilen gleich ``summen``.
    voll = services.leistungssummen(beleg)

    # Gutschriften mit positiven Beträgen, weil der Dokumenttyp 381 die
    # Richtung angibt. Intern sind Storno und Korrektur negativ, damit sich
    # eine Belegkette aufsummieren lässt.
    vorzeichen = -1 if typcode(beleg) == '381' else 1

    def betrag(wert: Decimal) -> Decimal:
        return rechnen.auf_cent(wert * vorzeichen)

    doc = Document()
    doc.context.guideline_parameter.id = (
        PROFIL_XRECHNUNG if xrechnung else PROFIL)
    if xrechnung:
        doc.context.business_parameter.id = GESCHAEFTSPROZESS_XRECHNUNG

    doc.header.id = beleg.nummer
    doc.header.type_code = typcode(beleg)
    doc.header.issue_date_time = beleg.belegdatum

    if beleg.betreff:
        notiz = IncludedNote()
        notiz.content = beleg.betreff
        doc.header.notes.add(notiz)

    # --- Verkäufer ---
    verkaeufer = doc.trade.agreement.seller
    verkaeufer.name = firma.name
    verkaeufer.address.line_one = firma.strasse
    verkaeufer.address.postcode = firma.plz
    verkaeufer.address.city_name = firma.ort
    verkaeufer.address.country_id = firma.land

    if xrechnung:
        # BR-DE-2: Ansprechpartner mit Telefon und E-Mail (BG-6). Dazu BT-34,
        # die elektronische Adresse des Verkäufers, seit XRechnung 3.0
        # Pflicht.
        verkaeufer.contact.person_name = firma.geschaeftsfuehrung or firma.name
        verkaeufer.contact.telephone.number = firma.telefon
        verkaeufer.contact.email.address = firma.email
        verkaeufer.electronic_address.uri_ID = (ADRESSSCHEMA_EMAIL, firma.email)

    # Bei "nicht steuerbar" keine USt-IdNr. im XML (BR-O-02); die
    # Steuernummer bleibt.
    ohne_ust_id = bool(regel and regel.ohne_ust_id)
    if firma.ust_id and not ohne_ust_id:
        _steuerkennung(verkaeufer, 'VA', firma.ust_id)
    if firma.steuernummer:
        _steuerkennung(verkaeufer, 'FC', firma.steuernummer)
    if ohne_ust_id:
        # BR-CO-26: Ohne USt-IdNr. über die Handelsregisternummer (BT-30),
        # sonst eine Kennung (BT-29). _steuerfall_pruefen stellt sicher, dass
        # eines vorhanden ist.
        if firma.handelsregister:
            verkaeufer.legal_organization.id = firma.handelsregister
        else:
            verkaeufer.id = firma.steuernummer

    # --- Käufer ---
    # Zuerst die strukturierten Felder, beim Anlegen aus den Stammdaten
    # kopiert. Nur wenn sie leer sind (Altdaten), wird das freie
    # Empfängerfeld heuristisch zerlegt.
    if beleg.empfaenger_name:
        name, strasse, plz, ort = (
            beleg.empfaenger_name, beleg.empfaenger_strasse,
            beleg.empfaenger_plz, beleg.empfaenger_ort,
        )
    else:
        name, strasse, plz, ort = _anschrift_zerlegen(beleg.empfaenger)
    kaeufer = doc.trade.agreement.buyer
    kaeufer.name = name
    kaeufer.address.line_one = strasse
    kaeufer.address.postcode = plz
    kaeufer.address.city_name = ort
    kaeufer.address.country_id = beleg.empfaenger_land or 'DE'
    if beleg.empfaenger_ust_id and not ohne_ust_id:
        _steuerkennung(kaeufer, 'VA', beleg.empfaenger_ust_id)
    if xrechnung:
        # BT-49, seit XRechnung 3.0 Pflicht. Die Leitweg-ID, weil sie bei
        # jeder XRechnung vorhanden ist (BR-DE-15) und das Rechnungsportal
        # darüber zustellt.
        kaeufer.electronic_address.uri_ID = (
            ADRESSSCHEMA_LEITWEG, beleg.leitweg_id)

    # Bei öffentlichen Auftraggebern ist die Leitweg-ID die Referenz, ohne
    # die die Rechnung im Rechnungseingangsportal nicht zugeordnet wird.
    if beleg.leitweg_id:
        doc.trade.agreement.buyer_reference = beleg.leitweg_id
    if beleg.bestellnummer:
        doc.trade.agreement.buyer_order.issuer_assigned_id = beleg.bestellnummer

    # BT-11 "Project reference", über die der Empfänger die Belege eines
    # Vorhabens zuordnet. Nummer als ID, Bezeichnung als Name.
    if beleg.projekt_id:
        projekt = doc.trade.agreement.procuring_project_type
        projekt.id = beleg.projekt.nummer
        projekt.name = beleg.projekt.bezeichnung

    # BG-3 "Preceding invoice reference": Storno und Rechnungskorrektur
    # verweisen auf den berichtigten Beleg (§ 31 Abs. 5 UStDV; bei 384
    # BR-DE-26). Bei XRechnung ist das XML das Original, der Verweis im
    # Betreff genügt dort nicht. Im CII höchstens einmal.
    if beleg.typ in GEGENBELEGE and beleg.vorgaenger_id:
        bezug = doc.trade.settlement.invoice_referenced_document
        bezug.issuer_assigned_id = beleg.vorgaenger.nummer
        bezug.issue_date_time = beleg.vorgaenger.belegdatum

    # --- Leistungsdatum und -zeitraum ---
    # BT-72 ist das Ende, nicht der Beginn; beim Abschlag fehlt es. Die
    # Regeln stehen an ``Beleg.steuerliches_leistungsdatum``.
    leistungsdatum = beleg.steuerliches_leistungsdatum
    if leistungsdatum:
        doc.trade.delivery.event.occurrence = leistungsdatum
    zeitraum = beleg.leistungszeitraum
    if zeitraum:
        # BG-14, BT-73/74.
        doc.trade.settlement.period.start, doc.trade.settlement.period.end = (
            zeitraum)
    if regel and regel.mit_lieferland:
        # BR-IC-12: Bei innergemeinschaftlicher Lieferung das Zielland. Eine
        # Lieferanschrift ist nicht erfasst; verwendet wird das Land des
        # Empfängers.
        doc.trade.delivery.ship_to.address.country_id = (
            beleg.empfaenger_land or 'DE')

    # --- Positionen ---
    # Ohne Titel und Text, weil eine Position Menge und Preis braucht und
    # sie null betrügen. Der Zuschlag ist eine gewöhnliche Position (Menge 1,
    # sein Betrag).
    leistungen = [p for p in beleg.positionen.all()
                  if not p.ist_abzug
                  and p.zeilenart not in Zeilenart.ohne_betrag()]
    # Ab dem 2. Abschlag dieselben Zeilen wie im PDF: Leistungsstand und je
    # Vorgänger eine negative Zeile, weil der Bildteil keine abweichende
    # Leistungsbeschreibung enthalten darf (R-185). Ihre Summe je Satz ist
    # das Netto des Abschlags, BT-113 bleibt leer.
    kumuliert = services.kumulierter_abschlag(beleg)
    if kumuliert is not None:
        leistungen = kumuliert.xml_zeilen()
    for nummer, position in enumerate(leistungen, start=1):
        zeile = LineItem()
        # BT-126: die Nummer wie im PDF, bei einem Leistungsverzeichnis die
        # Ordnungszahl ("01.01.0010").
        zeile.document.line_id = position.position or str(nummer)
        zeile.product.name = position.bezeichnung
        # BR-27: Der Einzelpreis (BT-146) ist nie negativ. Bei der Gutschrift
        # macht das Vorzeichen des Belegs ihn positiv; ein dann noch
        # negativer Wert (Nachlass als Position) trägt das Minus in der Menge
        # (BT-129), wo es erlaubt ist; Menge mal Preis bleibt der
        # Zeilenbetrag.
        preis = position.einzelpreis * vorzeichen
        menge = position.menge
        if preis < 0:
            preis, menge = -preis, -menge
        zeile.agreement.net.amount = preis
        zeile.delivery.billed_quantity = (menge, einheit_code(position.einheit))
        kategorie, satz = _kategorie(position.steuersatz_dezimal, firma, regel)
        zeile.settlement.trade_tax.type_code = 'VAT'
        zeile.settlement.trade_tax.category_code = kategorie
        zeile.settlement.trade_tax.rate_applicable_percent = satz
        if position.leistung_von and position.leistung_bis:
            # BG-26, BT-134/135: der Zeitraum dieser Position.
            zeile.settlement.period.start = position.leistung_von
            zeile.settlement.period.end = position.leistung_bis
        zeile.settlement.monetary_summation.total_amount = betrag(
            services.positionssumme(
                menge=position.menge, einzelpreis=position.einzelpreis
            )
        )
        doc.trade.items.add(zeile)

    # --- Steuern je Satz ---
    doc.trade.settlement.currency_code = 'EUR'
    for anteil in voll.anteile:
        kategorie, satz = _kategorie(anteil.satz, firma, regel)
        steuer = ApplicableTradeTax()
        steuer.calculated_amount = betrag(anteil.steuer)
        steuer.type_code = 'VAT'
        steuer.basis_amount = betrag(anteil.netto)
        steuer.category_code = kategorie
        steuer.rate_applicable_percent = satz
        if regel:
            # Befreiungsgrund und Code wie im PDF (BT-120, BT-121), Pflicht bei
            # AE, K, G und O (BR-AE-10, BR-IC-10, BR-G-10, BR-O-10).
            steuer.exemption_reason = regel.vermerk
            steuer.exemption_reason_code = regel.befreiungscode
        elif kategorie == KATEGORIE_BEFREIT:
            steuer.exemption_reason = _befreiungsgrund(firma)
        doc.trade.settlement.trade_tax.add(steuer)

    # --- Zahlungsbedingungen ---
    if firma.iban and beleg.typ == BelegTyp.RECHNUNG:
        mittel = PaymentMeans()
        mittel.type_code = ZAHLUNGSART_UEBERWEISUNG
        mittel.payee_account.iban = firma.iban
        if firma.bic:
            mittel.payee_institution.bic = firma.bic
        doc.trade.settlement.payment_means.add(mittel)
    elif xrechnung:
        # BR-DE-1: Eine XRechnung hat immer eine Zahlungsanweisung (BG-16),
        # auch die Gutschrift. Dort zahlt der Aussteller, deshalb "nicht
        # festgelegt" und keine Überweisung auf das eigene Konto.
        mittel = PaymentMeans()
        mittel.type_code = ZAHLUNGSART_OFFEN
        doc.trade.settlement.payment_means.add(mittel)

    if beleg.faellig_am:
        bedingung = PaymentTerms()
        bedingung.due = beleg.faellig_am
        doc.trade.settlement.terms.add(bedingung)

    # --- Summen ---
    gesamt = doc.trade.settlement.monetary_summation
    gesamt.line_total = betrag(voll.netto)
    gesamt.tax_basis_total = betrag(voll.netto)
    gesamt.tax_total = (betrag(voll.steuer), 'EUR')
    gesamt.grand_total = betrag(voll.brutto)
    if voll.brutto != summen.brutto:
        # BT-113: abgesetzte Abschläge brutto, als Differenz, damit BR-CO-16
        # (BT-115 = BT-112 minus BT-113) auf den Cent stimmt; die Steuer wird
        # je Satz auf die Summe gerechnet.
        gesamt.prepaid_total = betrag(voll.brutto) - betrag(summen.brutto)
    # BT-115: Zahlbetrag, derselbe wie im PDF und in den offenen Posten.
    gesamt.due_amount = betrag(summen.brutto)

    # serialize() validiert gegen das XSD und wirft bei Verstößen.
    return doc.serialize(schema='FACTUR-X_EN16931')


def xml_und_metadaten(beleg) -> tuple["io.BytesIO", bytes]:
    """Liefert das XML als Datenstrom und die zugehörigen XMP-Metadaten.

    Ohne die XMP-Erweiterung ist das PDF kein Factur-X; Leseprogramme
    entscheiden anhand dieser Metadaten, ob sie nach einem XML suchen.

    Das Einbetten als ``Attachment`` erfolgt in pdf.py, damit dieses Modul
    nicht von WeasyPrint abhängt.
    """
    return io.BytesIO(xml_erzeugen(beleg)), xmp_metadaten(beleg)


def xmp_metadaten(beleg=None) -> bytes:
    """Die Factur-X-Erweiterung für die XMP-Metadaten des PDF.

    Der Block ist im Standard vorgegeben. Er kennzeichnet das PDF als
    Factur-X und nennt Dateinamen und Profil des XML.

    Ohne ``beleg`` das Profil EN 16931, mit Beleg das Ergebnis von
    ``ist_xrechnung``. Name und Profil müssen zum Anhang passen.
    """
    dateiname = anhangname(beleg) if beleg is not None else XML_DATEINAME
    profil = profilname(beleg) if beleg is not None else PROFIL_NAME
    return f'''<rdf:Description rdf:about=""
        xmlns:fx="urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#">
      <fx:DocumentType>INVOICE</fx:DocumentType>
      <fx:DocumentFileName>{dateiname}</fx:DocumentFileName>
      <fx:Version>1.0</fx:Version>
      <fx:ConformanceLevel>{profil}</fx:ConformanceLevel>
    </rdf:Description>'''.encode()


def _xrechnung_pruefen(beleg, firma) -> None:
    """Prüft die Pflichtangaben einer XRechnung über EN 16931 hinaus
    (Regeln BR-DE-*).

    Alle fehlenden Angaben in einer Meldung, damit sie in einem Durchgang
    ergänzt werden können. Geprüft wird nur auf Vorhandensein, nicht auf
    Richtigkeit der Werte.
    """
    fehlt = []
    if not beleg.leitweg_id:
        fehlt.append('die Leitweg-ID (Käuferreferenz) am Beleg')
    if not firma.telefon:
        fehlt.append('die Telefonnummer der eigenen Firma')
    if not firma.email:
        fehlt.append('die E-Mail-Adresse der eigenen Firma')
    if beleg.typ == BelegTyp.RECHNUNG and not firma.iban:
        fehlt.append('die IBAN der eigenen Firma')
    if not (firma.plz and firma.ort):
        fehlt.append('PLZ und Ort der eigenen Firma')
    if not (beleg.empfaenger_plz and beleg.empfaenger_ort):
        fehlt.append('PLZ und Ort des Empfängers')
    if fehlt:
        raise FacturxFehler(
            'Der Kunde bekommt seine Rechnungen als XRechnung, dafür fehlen: '
            + ', '.join(fehlt) + '.'
        )


def _steuerfall_pruefen(beleg, firma, regel) -> None:
    """Prüft die Angaben, die ein Steuerfall verlangt, in einer Meldung.

    Die USt-IdNrn. sind bei Reverse Charge und innergemeinschaftlicher
    Lieferung Pflicht auf der Rechnung (§ 14a UStG) und im XML (BR-AE-02,
    BR-IC-02, BR-G-02). Bei "nicht steuerbar" darf die eigene nicht ins XML;
    dann muss der Verkäufer anders erkennbar sein (BR-CO-26).

    Die Steuersätze prüft auch ``beleg_festschreiben``. Hier erneut, weil
    das XML auch ohne Festschreiben entsteht (Vorschau, Tests) und 19 % unter
    "Reverse Charge" widersprüchlich wären.
    """
    fehlt = []
    if regel.braucht_eigene_ust_id and not firma.ust_id:
        fehlt.append('die USt-IdNr. der eigenen Firma')
    if regel.braucht_kunden_ust_id and not beleg.empfaenger_ust_id:
        fehlt.append('die USt-IdNr. des Kunden am Beleg')
    if regel.ohne_ust_id and not (firma.handelsregister or firma.steuernummer):
        fehlt.append('die Steuernummer oder Handelsregisternummer der '
                     'eigenen Firma')
    if beleg.positionen.exclude(steuersatz=STEUERFREI).exists():
        fehlt.append('0 % an allen Positionen')
    if fehlt:
        raise FacturxFehler(
            f'Für den Steuerfall „{beleg.get_steuerfall_display()}“ fehlen: '
            + ', '.join(fehlt) + '.'
        )


# --------------------------------------------------------------------------
# Kleinteile
# --------------------------------------------------------------------------

def _steuerkennung(partei, schema: str, wert: str) -> None:
    """Hängt eine Steuernummer an eine Partei.

    ``VA`` ist die Umsatzsteuer-Identifikationsnummer, ``FC`` die nationale
    Steuernummer. Beide dürfen nebeneinander stehen.
    """
    kennung = TaxRegistration()
    kennung.id = (schema, wert)
    partei.tax_registrations.add(kennung)


def _kategorie(satz: Decimal, firma, regel=None) -> tuple[str, Decimal]:
    """Steuerkategorie und Satz für das XML.

    Der Steuerfall hat Vorrang: § 13b und die EU-Dienstleistung sind 'AE',
    die innergemeinschaftliche Lieferung 'K', die Ausfuhr 'G', das nicht
    Steuerbare 'O', jeweils mit 0 %. Er geht auch der Kleinunternehmerregelung
    vor, weil er am Beleg gewählt ist und die Kleinunternehmerregelung
    allgemein gilt.

    Ohne Steuerfall bedeutet ein Satz von 0 steuerfreie Leistung oder
    Kleinunternehmer; die Kategorie ist in beiden Fällen 'E', der Grund
    verschieden.
    """
    if regel:
        return regel.kategorie, Decimal('0.00')
    if satz == 0 or firma.kleinunternehmer:
        return KATEGORIE_BEFREIT, Decimal('0.00')
    return KATEGORIE_STANDARD, satz


def _befreiungsgrund(firma) -> str:
    if firma.kleinunternehmer:
        return ('Kein Ausweis von Umsatzsteuer, da Kleinunternehmer '
                'gemäß § 19 UStG.')
    return 'Steuerfreie Leistung.'
