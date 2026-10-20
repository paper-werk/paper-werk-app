"""Leistungsnachweis als PDF.

Anders als ein Beleg hat der Nachweis keine Nummer, wird nicht gespeichert
und hat keine Prüfsumme; jeder Aufruf erzeugt ihn aus dem aktuellen Stand.
Festgeschrieben wird nur bei der Übernahme in eine Rechnung.

Das gilt auch für den Nachweis zur Rechnung (``zur_rechnung_als_pdf``), der
bei Ansicht und Versand neu erzeugt wird. Nach dem Festschreiben der
Rechnung sind seine Zeilen gesperrt, der Inhalt bleibt gleich.

Die PDF-Erzeugung kommt aus ``faktura/pdf.py``: Einrichtung von WeasyPrint
(unter Windows die DLL-Suchpfade), ``BelegUrlFetcher`` und mit ``beleg.css``
die Seitengeometrie nach DIN 5008. Briefkopf, Fußzeile und Anschriftfeld
sind Teiltemplates von dort, damit Änderungen an den Firmendaten auch hier
gelten.
"""

from django.template.loader import render_to_string
from django.utils import timezone

VORLAGE = 'erfassung/nachweis/basis.html'

#: Version des Templates, wie ``faktura.pdf.VORLAGENVERSION``, klein in der
#: Fußzeile, damit sich ältere Ausdrucke zuordnen lassen.
#:
#: Wird nicht gespeichert, weil es keinen Datensatz zum Nachweis gibt.
VORLAGENVERSION = 'v1'


def nachweis_als_html(aufstellung, *, erzeugt_von=None,
                      mit_uhrzeit=True) -> str:
    """Nachweis als HTML.

    ``mit_uhrzeit=False`` ergibt die kompakte Fassung ohne die Spalten Von
    und Bis; die Dauer bleibt.

    Eigene Funktion wie beim Beleg, um das Layout im Browser ohne PDF-Lauf
    zu entwickeln.
    """
    from faktura.models import Firma

    kunde = aufstellung.kunde
    return render_to_string(VORLAGE, {
        'a': aufstellung,
        'firma': Firma.aktuelle(),
        'anschrift': kunde.anschriftfeld if kunde else '',
        'erzeugt_am': timezone.localtime(),
        'erzeugt_von': erzeugt_von,
        'mit_uhrzeit': mit_uhrzeit,
        'vorlagenversion': VORLAGENVERSION,
    })


def nachweis_als_pdf(aufstellung, *, erzeugt_von=None,
                     mit_uhrzeit=True) -> bytes:
    """Nachweis als PDF.

    Ohne PDF/A und eingebettetes XML: PDF/A dient der zehnjährigen
    Aufbewahrung von Belegen, Factur-X der maschinellen Verarbeitung von
    Rechnungen; ein Nachweis wird unterschrieben und zurückgeschickt.

    Der Import steht in der Funktion, weil ``faktura.pdf`` beim Import unter
    Windows die DLL-Suchpfade für WeasyPrint einrichtet. Auf Modulebene
    sortierte isort ``import weasyprint`` vor den Import von ``faktura``,
    und die Einrichtung käme zu spät.
    """
    from django.conf import settings

    from faktura.pdf import BelegUrlFetcher, weasyprint

    html = weasyprint.HTML(
        string=nachweis_als_html(aufstellung, erzeugt_von=erzeugt_von,
                                 mit_uhrzeit=mit_uhrzeit),
        base_url=str(settings.BASE_DIR),
        url_fetcher=BelegUrlFetcher(),
    )
    return html.write_pdf()


def zur_rechnung_als_pdf(beleg) -> bytes:
    """Nachweis zur Rechnung, registriert als Anlage in
    ``ZeitenConfig.ready()``. Immer kompakt, ohne Von und Bis."""
    from .services import nachweis_zur_rechnung

    return nachweis_als_pdf(nachweis_zur_rechnung(beleg), mit_uhrzeit=False)


def dateiname(aufstellung) -> str:
    """Dateiname aus Projekt und Zeitraum, soweit eindeutig.

    Bei Zeilen aus mehreren Vorhaben nur der Zeitraum, damit der Name kein
    Projekt nennt, das nur für einen Teil gilt.
    """
    teile = ['Leistungsnachweis']
    if aufstellung.projekt is not None:
        teile.append(aufstellung.projekt.nummer)
    if aufstellung.von and aufstellung.bis:
        if aufstellung.von == aufstellung.bis:
            teile.append(f'{aufstellung.von:%Y-%m-%d}')
        else:
            teile.append(f'{aufstellung.von:%Y-%m-%d}_bis_{aufstellung.bis:%Y-%m-%d}')
    return '_'.join(teile).replace(' ', '_').replace('/', '-') + '.pdf'


__all__ = ['VORLAGENVERSION', 'dateiname', 'nachweis_als_html',
           'nachweis_als_pdf', 'zur_rechnung_als_pdf']
