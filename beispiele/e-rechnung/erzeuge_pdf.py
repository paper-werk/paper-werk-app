"""Erzeugt ``isartal-4713-als-pdf.pdf`` neu.

Werkzeug außerhalb der Anwendung. Es liegt hier, weil die PDF-Datei
daneben binär ist und nur so reproduzierbar; der Test auf ihren Inhalt
setzt sie voraus.

Erzeugt wie die eigenen Rechnungen: WeasyPrint setzt die Seite als
PDF/A-3b, ``drafthorse`` bettet das XML ein. Die Daten kommen aus
``isartal-4711-regelfall.xml`` mit eigener Nummer und eigenem Datum, damit
sich beide Dateien nacheinander hochladen lassen, ohne "bereits erfasst".

Aufruf aus dem Wurzelverzeichnis des Projekts::

    uv run python beispiele/e-rechnung/erzeuge_pdf.py

Braucht GTK für WeasyPrint, siehe ``faktura/pdf.py``.
"""

import os
import re
import sys
from pathlib import Path

import django

BASIS = Path(__file__).resolve().parent
QUELLE = BASIS / 'isartal-4711-regelfall.xml'
ZIEL = BASIS / 'isartal-4713-als-pdf.pdf'

sys.path.insert(0, str(BASIS.parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'paperwerk.settings.dev')
django.setup()

# Nach django.setup(), weil faktura.pdf beim Import das GTK-Verzeichnis
# registriert und dafür die Settings liest.
from drafthorse.pdf import attach_xml  # noqa: E402

from erfassung import erechnung  # noqa: E402
from faktura import pdf as faktura_pdf  # noqa: E402

SEITE = """
<style>
  @page { size: A4; margin: 22mm 20mm; }
  body { font-family: "Segoe UI", sans-serif; font-size: 10pt; color: #111; }
  .absender { font-size: 7.5pt; color: #666; border-bottom: .5pt solid #bbb;
              padding-bottom: 2mm; margin-bottom: 14mm; }
  h1 { font-size: 15pt; margin: 0 0 1mm 0; }
  .kopf { display: flex; justify-content: space-between; margin-bottom: 10mm; }
  .kopf dl { margin: 0; font-size: 9pt; }
  .kopf dt { color: #666; }
  .kopf dd { margin: 0 0 1.5mm 0; }
  table { width: 100%; border-collapse: collapse; margin-top: 6mm; }
  th { text-align: left; font-size: 8pt; text-transform: uppercase;
       letter-spacing: .04em; color: #666; border-bottom: .8pt solid #333;
       padding-bottom: 1.5mm; }
  td { padding: 2mm 0; border-bottom: .3pt solid #ddd;
       font-variant-numeric: tabular-nums; }
  .r { text-align: right; }
  tfoot td { border: 0; padding: 1mm 0; }
  tfoot .summe td { border-top: .8pt solid #333; font-weight: 600;
                    padding-top: 2mm; }
  .fuss { margin-top: 16mm; font-size: 8pt; color: #666;
          border-top: .5pt solid #bbb; padding-top: 3mm; }
  .hinweis { margin-top: 8mm; font-size: 8pt; color: #444;
             background: #f4f4f2; padding: 3mm 4mm; }
</style>

<div class="absender">
  Bodenlabor Isartal GmbH &middot; Laborweg 4 &middot; 84032 Altdorf
</div>

<div class="kopf">
  <div>
    <h1>Rechnung</h1>
    <div style="font-size:9pt;color:#666">Nr. BLI-2026-4713</div>
    <div style="margin-top:8mm;font-size:9.5pt;line-height:1.5">
      Ingenieurb&uuml;ro Muster GmbH<br>
      Altstadt 1<br>
      84028 Landshut
    </div>
  </div>
  <dl>
    <dt>Rechnungsdatum</dt><dd>02.09.2026</dd>
    <dt>Leistungsdatum</dt><dd>31.07.2026</dd>
    <dt>Ihre Bestellung</dt><dd>BST-2026-0099</dd>
    <dt>Leitweg-ID</dt><dd>04011000-12345-67</dd>
    <dt>USt-IdNr.</dt><dd>DE812345678</dd>
  </dl>
</div>

<p style="font-size:9.5pt">Analytik Bodenproben, Charge 14/26</p>

<table>
  <thead>
    <tr>
      <th>Pos.</th><th>Leistung</th>
      <th class="r">Menge</th><th>Einheit</th>
      <th class="r">Einzelpreis</th><th class="r">Betrag</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>1</td><td>Paket B: Schwermetalle nach LAGA</td>
      <td class="r">8</td><td>Stk</td>
      <td class="r">42,50 &euro;</td><td class="r">340,00 &euro;</td>
    </tr>
    <tr>
      <td>2</td><td>Probenahme vor Ort</td>
      <td class="r">3,5</td><td>Std</td>
      <td class="r">95,00 &euro;</td><td class="r">332,50 &euro;</td>
    </tr>
  </tbody>
  <tfoot>
    <tr><td colspan="5" class="r">Summe netto</td>
        <td class="r">672,50 &euro;</td></tr>
    <tr><td colspan="5" class="r">zzgl. 19 % USt</td>
        <td class="r">127,78 &euro;</td></tr>
    <tr class="summe"><td colspan="5" class="r">Rechnungsbetrag</td>
        <td class="r">800,28 &euro;</td></tr>
  </tfoot>
</table>

<p style="margin-top:8mm;font-size:9pt">
  Zahlbar innerhalb 30 Tagen ohne Abzug bis zum 02.10.2026 auf
  IBAN DE02 1203 0000 0000 2020 51.
</p>

<div class="hinweis">
  <strong>Beispieldatei.</strong> Erfundene Rechnung eines erfundenen Labors
  &ndash; zum Ausprobieren von &bdquo;E-Rechnung einlesen&ldquo; in
  paper-werk. In diesem PDF steckt das Factur-X-XML (EN&nbsp;16931) als
  Anhang <em>factur-x.xml</em>; genau daraus liest die Anwendung.
</div>

<div class="fuss">
  Bodenlabor Isartal GmbH &middot; Laborweg 4, 84032 Altdorf &middot;
  USt-IdNr. DE812345678 &middot; Sparkasse Landshut &middot;
  IBAN DE02 1203 0000 0000 2020 51
</div>
"""


def xml_fuer_das_pdf() -> bytes:
    """XML des Regelfalls mit eigener Nummer und eigenem Datum.

    Ohne den Kommentar am Anfang des XML-Beispiels, weil er nur im Editor
    nützt.
    """
    xml = QUELLE.read_bytes()
    xml = xml.replace(b'BLI-2026-4711', b'BLI-2026-4713')
    xml = xml.replace(b'>20260812<', b'>20260902<')
    xml = xml.replace(b'Charge 12/26', b'Charge 14/26')
    return re.sub(rb'<!--.*?-->\n', b'', xml, count=1, flags=re.S)


def main() -> None:
    seite = faktura_pdf.weasyprint.HTML(string=SEITE).write_pdf(
        pdf_variant='pdf/a-3b')
    fertig = attach_xml(seite, xml_fuer_das_pdf(), level='EN 16931')
    ZIEL.write_bytes(fertig)

    # Gegenprobe mit dem eigenen Parser, damit das Beispiel lesbar ist.
    gelesen = erechnung.lesen(fertig)
    print(f'{ZIEL.name}: {len(fertig)} Bytes')
    print(f'  gelesen: {gelesen.nummer}, {gelesen.datum}, '
          f'{gelesen.betrag_netto} EUR, {len(gelesen.positionen)} Positionen, '
          f'aus_pdf={gelesen.aus_pdf}')


if __name__ == '__main__':
    main()
