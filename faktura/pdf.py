"""Erzeugung der Beleg-PDFs ohne HTTP: Beleg als Eingabe, Bytes als
Ausgabe.

Django-Template, HTML, WeasyPrint, PDF; das Layout ist CSS. Festgelegt:

1. **PDF/A-3b**, weil nur diese Variante das Factur-X-XML einbetten darf.
2. **Die Template-Version wird gespeichert**, damit Abweichungen alter
   Belege nachvollziehbar sind.
3. **Entwürfe haben ein Wasserzeichen.**
"""

import hashlib
import io
import logging
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

# Unter Windows muss das Verzeichnis der Pango-DLLs vor dem Import von
# weasyprint registriert werden, weil Python ab 3.8 dafür PATH ignoriert.
if settings.GTK_BIN_DIR and hasattr(os, 'add_dll_directory'):
    os.add_dll_directory(settings.GTK_BIN_DIR)

import weasyprint  # noqa: E402  (muss nach add_dll_directory stehen, s. o.)

# fontTools warnt bei manchen Windows-Schriften über einen Zeitstempel vor
# 1970; die Schrift wird trotzdem korrekt eingebettet.
logging.getLogger('fontTools').setLevel(logging.ERROR)

#: Version der Templates. Bei jeder sichtbaren Änderung an Template oder
#: CSS inkrementieren; der Wert wird an jedem festgeschriebenen Beleg
#: gespeichert.
#   v1  erste Fassung
#   v2  Logo über .url statt .path, Tausenderpunkt bei Beträgen,
#       Spaltenüberschriften rechtsbündig wie ihre Werte
#   v3  Bezeichnungsspalte breiter (65 statt 54 mm), Umlaute in allen
#       angezeigten Texten
#   v4  Spalten auf ihren breitesten zulässigen Inhalt bemessen
#       (Bezeichnung 80,7 mm), Währung in der Kopfzeile statt in jeder
#       Zeile, box-sizing und table-layout festgelegt
#   v5  Die Terminzeile heißt nach der Belegart: Leistungsdatum nur bei
#       Rechnung, Storno und Korrektur; Ausführung beim Angebot und der
#       Auftragsbestätigung; Lieferdatum beim Lieferschein
#   v6  Projektzeile im Infoblock; die Kundennummer nur noch, wenn der
#       Beleg einem Kunden zugeordnet ist
#   v7  Nummernzeile im Infoblock steht immer über dem Datum (im Entwurf
#       "noch offen"); Logo links oben, 20 mm ab linker und 15 mm ab oberer
#       Blattkante, höchstens 55 mm breit und 14 mm hoch
#   v8  Keine festen Anrede-, Einleitungs- und Grußtexte mehr; vor und nach
#       den Positionen nur Kopf- und Fußtext des Belegs. Erhalten bleiben
#       die gesetzlichen Hinweise (Abschlag § 14, Angebot, Lieferschein,
#       Gutschrift/Storno § 17) und die Einleitungen von Gutschrift, Storno
#       und Mahnung. firma.standard_fusstext wird nicht mehr ausgewertet.
#   v9  Langtext in eigener Zeile über die ganze Breite, von der
#       Bezeichnung bis zum Gesamtpreis; Spalte "Pos." wächst mit langen
#       Nummern wie "01.01.0010"; optionale Positionen
#   v10 Zeilenarten Titel (mit Titelsumme), Text und Zuschlag (mit
#       Rechenweg); Schlussrechnung je Abschlag eine Zeile
VORLAGENVERSION = 'v10'

#: Spalte "Pos.": bis vier Zeichen bestimmt die Überschrift die Breite
#: (beleg.css). Darüber je Zeichen 1,6 mm plus 2,4 mm Padding, höchstens
#: 22 mm; längere Nummern brechen in der Zelle um. Im PDF gemessen:
#: "01.01.0010" ist 15,2 mm breit (acht Ziffern zu 1,8 mm, zwei Punkte zu
#: 0,9 mm).
POS_BREITE_MM = 8.0
POS_JE_ZEICHEN_MM = 1.6
POS_HOECHSTENS_MM = 22.0


def pos_breite(positionen) -> str:
    """Breite der Spalte "Pos." als CSS-Wert, z. B. "21.4mm".

    Als String mit Punkt, weil das Template eine Zahl lokalisiert und
    WeasyPrint "21,4mm" ohne Fehlermeldung verwirft."""
    laengste = max((len(p.position) for p in positionen), default=0)
    breite = min(max(POS_BREITE_MM, 2.4 + POS_JE_ZEICHEN_MM * laengste),
                 POS_HOECHSTENS_MM)
    return f'{breite:.1f}mm'

#: Verzeichnis der Templates; je Belegart eines, mit Fallback auf das
#: Basis-Template.
VORLAGE = 'faktura/pdf/{typ}.html'
VORLAGE_BASIS = 'faktura/pdf/basis.html'


class PdfFehler(Exception):
    """Erzeugung aus fachlichen Gründen nicht möglich."""


def beleg_als_html(beleg, *, entwurf_kennzeichnen: bool = True) -> str:
    """Beleg als HTML, für die Arbeit am Layout im Browser."""
    from django.template.loader import select_template

    from . import services
    from .models import BelegStatus, Firma, Zeilenart

    firma = Firma.aktuelle()
    summen = services.belegsummen(beleg)

    # ``vorlagenname``: Abschlags- und Schlussrechnung haben eigene
    # Templates.
    vorlage = select_template(
        [VORLAGE.format(typ=beleg.vorlagenname), VORLAGE_BASIS])

    # Abzugszeilen stehen unter der Summe; hier getrennt, damit das
    # Basis-Template sie nicht behandeln muss.
    alle = list(beleg.positionen.all())
    positionen = [p for p in alle if not p.ist_abzug]
    # Titelsumme nach der letzten Zeile des Titels, Rechenweg unter dem
    # Zuschlag, als Attribut der Zeile, damit das Template eine Schleife
    # hat (R-180, R-181).
    nach = services.titelsummen(positionen)
    for i, position in enumerate(positionen):
        position.titelabschluesse = nach.get(i, [])
        if position.zeilenart == Zeilenart.ZUSCHLAG:
            position.rechenweg = services.zuschlagsbeschreibung(
                position, positionen)

    return render_to_string(vorlage.template.name, {
        'beleg': beleg,
        'firma': firma,
        'positionen': positionen,
        'pos_breite': pos_breite(positionen),
        # Je Abschlag eine Zeile, die Restzeile darin enthalten (R-174).
        'abzuege': services.abzugsblock(alle),
        'summen': summen,
        'mit_preisen': beleg.ist_wertbeleg,
        'ist_entwurf': beleg.status == BelegStatus.ENTWURF,
        'wasserzeichen': (
            entwurf_kennzeichnen and beleg.status == BelegStatus.ENTWURF
        ),
        'bezeichnung': belegbezeichnung(beleg),
        'erzeugt_am': timezone.localtime(),
        'vorlagenversion': VORLAGENVERSION,
    })


class BelegUrlFetcher(weasyprint.URLFetcher):
    """Löst ``/static/…`` und ``/media/…`` auf lokale Dateien auf.

    WeasyPrint läuft ohne Webserver und hat ``/static/beleg.css`` bereits zu
    ``file:///static/beleg.css`` aufgelöst; ohne diesen Fetcher entstünde das
    PDF ohne Fehlermeldung ohne CSS. Verglichen wird deshalb der Pfad.
    """

    def __call__(self, url):
        from django.contrib.staticfiles import finders

        pfadanteil = unquote(urlsplit(url).path)

        if pfadanteil.startswith(settings.STATIC_URL):
            rest = pfadanteil[len(settings.STATIC_URL):]

            # Zuerst die Quelldatei (Entwicklung), dann collectstatic, weil
            # der Name im Betrieb einen Hash enthält
            # (beleg.254698946439.css) und nur in STATIC_ROOT existiert.
            gefunden = finders.find(rest)

            if not gefunden and settings.STATIC_ROOT:
                eingesammelt = Path(settings.STATIC_ROOT) / rest
                if eingesammelt.is_file():
                    gefunden = str(eingesammelt)

            if gefunden:
                return super().__call__(Path(gefunden).as_uri())

        if settings.MEDIA_URL and pfadanteil.startswith(settings.MEDIA_URL):
            datei = Path(settings.MEDIA_ROOT) / pfadanteil[len(settings.MEDIA_URL):]
            if datei.exists():
                return super().__call__(datei.as_uri())

        return super().__call__(url)


def _xmp_einsetzen(block: bytes):
    """Setzt den Factur-X-Block **innerhalb** von ``<rdf:RDF>`` ein.

    Die Option ``xmp_metadata`` hängt Fragmente hinter ``</rdf:RDF>`` an, wo
    der Präfix ``rdf:`` nicht gebunden ist; das XML ist ungültig, was erst
    der Validator des Empfängers meldet. Ein zweites ``<rdf:RDF>`` erlaubt
    XMP nicht. Deshalb ein ``finisher``, der nach dem Aufbau und vor dem
    Schreiben des PDFs läuft.
    """
    def finisher(document, pdf):
        referenz = pdf.catalog.get('Metadata')
        if referenz is None:            # kein PDF/A, also kein XMP
            return
        nummer = int(referenz.split()[0])
        stream = pdf.objects[nummer]
        inhalt = b''.join(stream.stream)
        stream.stream = [inhalt.replace(b'</rdf:RDF>', block + b'\n</rdf:RDF>')]

    return finisher


def beleg_als_pdf(beleg, *, mit_xml: bool = True,
                  xml: bytes | None = None) -> bytes:
    """Der Beleg als PDF/A-3b, bei Rechnungen mit eingebettetem XML.

    ``mit_xml=False`` für die Vorschau eines Entwurfs. ``xml`` ist ein
    bereits erzeugtes XML, das unverändert eingebettet wird, damit beim
    Festschreiben PDF-Anhang und gespeichertes XML dieselben Bytes haben.
    """
    from .facturx import (
        anhangname,
        ist_erechnungsfaehig,
        xml_erzeugen,
        xmp_metadaten,
    )

    html = weasyprint.HTML(
        string=beleg_als_html(beleg),
        base_url=str(settings.BASE_DIR),
        url_fetcher=BelegUrlFetcher(),
    )

    optionen = {
        'pdf_variant': 'pdf/a-3b',
        'uncompressed_pdf': False,
    }

    if mit_xml and xml is None and ist_erechnungsfaehig(beleg):
        xml = xml_erzeugen(beleg)

    if mit_xml and xml is not None:
        optionen['attachments'] = [weasyprint.Attachment(
            file_obj=io.BytesIO(xml),
            name=anhangname(beleg),
            description='Factur-X/ZUGFeRD Rechnungsdaten nach EN 16931',
            # Von Factur-X vorgeschrieben: dieselbe Rechnung,
            # maschinenlesbar, mit Relationship "Alternative".
            relationship='Alternative',
        )]
        optionen['finisher'] = _xmp_einsetzen(xmp_metadaten(beleg))

    return html.write_pdf(**optionen)


def pruefsumme(daten: bytes) -> str:
    """SHA-256 als Hex-String, Nachweis, dass die Datei seit der
    Festschreibung unverändert ist."""
    return hashlib.sha256(daten).hexdigest()


def belegbezeichnung(beleg) -> str:
    """Bezeichnung der Belegart im PDF, beim Auftrag "Auftragsbestätigung";
    Überschrift und Dateiname verwenden sie."""
    from .models import BelegTyp

    if beleg.typ == BelegTyp.AUFTRAG:
        return 'Auftragsbestätigung'
    return beleg.get_typ_display()


#: Transliteration für den Dateinamen, weil Mailanhänge und fremde
#: Dateisysteme "ae" zuverlässiger verarbeiten als "ä".
DATEINAME_UMSCHRIFT = str.maketrans({
    'ä': 'ae', 'ö': 'oe', 'ü': 'ue',
    'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue', 'ß': 'ss', ' ': '_',
})


def dateiname(beleg, endung: str = 'pdf') -> str:
    """Dateiname des Anhangs. PDF und XML eines Belegs haben denselben
    Stamm."""
    kennung = beleg.nummer or f'entwurf-{beleg.pk}'
    return (f'{belegbezeichnung(beleg)}_{kennung}.{endung}'
            .translate(DATEINAME_UMSCHRIFT))
