"""Versand von Belegen per E-Mail einschließlich Festschreiben.

Versendet wird immer die gespeicherte Datei, nie ein neu gerendertes PDF,
weil das versendete Dokument der Beleg ist.
"""

from collections.abc import Iterable

from django.conf import settings
from django.core.mail import EmailMessage, mailers
from django.db.models import TextChoices
from django.utils import timezone

from ..models import Beleg, Firma
from .anlagen import anlage_dateiname, anlage_pdf, anlagenquellen
from .fehler import EmpfaengeradresseFehlt, VersandFehlgeschlagen
from .festschreiben import _dokument_einfrieren, beleg_festschreiben


def absenderadresse() -> str:
    """Absenderadresse.

    ``DEFAULT_FROM_EMAIL`` hat Vorrang vor der Firmenadresse, weil manche
    SMTP-Server nur einen bestimmten Absender akzeptieren.
    """
    if eingestellt := getattr(settings, 'DEFAULT_FROM_EMAIL', ''):
        return eingestellt
    firma = Firma.objects.first()
    return firma.email if firma else ''


def versand_geht_hinaus() -> bool:
    """Ob eine Mail tatsächlich versendet wird.

    Damit der Admin nicht "versendet" meldet, wenn nur das Console-Backend
    konfiguriert ist. Geprüft wird das Backend, weil ``dev.py`` es
    unabhängig von ``EMAIL_HOST`` setzt.
    """
    backend = mailers.settings.get('default', {}).get('BACKEND', '')
    return 'console' not in backend and 'locmem' not in backend         and 'dummy' not in backend


class Versandanhang(TextChoices):
    """Die eine versendete Datei, per Mail wie beim Download.

    Das Format folgt aus dem Beleg: XRechnung als XML, alles andere als PDF,
    bei Rechnungen mit eingebetteter E-Rechnung (ZUGFeRD).

    Verworfen: eine Auswahl aus PDF, XML oder beidem. Ein einzelnes XML gilt
    in Deutschland als XRechnung; das EN-16931-XML eines ZUGFeRD-Kunden fiel
    im Validator des Empfängers durch, und "beides" erzeugte zwei
    E-Rechnungen mit derselben Nummer im selben Posteingang.
    """

    PDF = 'pdf', 'PDF'
    XML = 'xml', 'XRechnung (XML)'


def versandformat(beleg: Beleg) -> Versandanhang:
    """Versandformat des Belegs, siehe ``Versandanhang``.

    Am festgeschriebenen Beleg gilt das gespeicherte Profil, weil die
    gespeicherte Datei versendet wird; am Entwurf das Profil, mit dem er
    festgeschrieben wird.
    """
    from .. import facturx

    if beleg.xml:
        if beleg.erechnungsprofil == facturx.PROFIL_NAME_XRECHNUNG:
            return Versandanhang.XML
        return Versandanhang.PDF
    if (beleg.ist_aenderbar and beleg.typ in facturx.TYP_CODE
            and facturx.ist_xrechnung(beleg)):
        return Versandanhang.XML
    return Versandanhang.PDF


def beleg_versenden(
    *, beleg_id: int, an: str = '', betreff: str = '', nachricht: str = '',
    benutzer=None, mengen_bestaetigt: bool = False,
    anlagen: Iterable[str] = (),
) -> Beleg:
    """Schreibt fest und versendet, in dieser Reihenfolge, damit beim Kunden
    keine Rechnung liegt, die im System fehlt.

    Schlägt der Versand fehl, bleibt der Beleg gültig und ``versendet_am``
    leer. Ein bereits festgeschriebener Beleg wird nur versendet; so lässt
    sich ein Versand wiederholen.

    ``an`` überschreibt die Adresse am Beleg. ``versendet_am/-an`` speichert
    nur den ersten Versand; weitere stehen im Verlauf (Admin).
    ``mengen_bestaetigt`` wird an das Festschreiben übergeben. Den Anhang
    bestimmt ``versandformat`` nach dem Festschreiben, also nach dem
    gespeicherten Profil. ``anlagen`` enthält die Arten der zusätzlichen
    PDF-Anlagen (``anlagenquellen``).
    """
    beleg = Beleg.objects.get(pk=beleg_id)

    empfaenger = (an or beleg.empfaenger_email).strip()
    if not empfaenger:
        raise EmpfaengeradresseFehlt(
            f'Für {beleg} ist keine E-Mail-Adresse hinterlegt. Tragen Sie '
            f'sie am Beleg ein oder in den Stammdaten des Kunden; dann '
            f'steht sie beim nächsten Beleg von allein da.'
        )

    # Eingabefehler vor dem Festschreiben melden, weil danach die Nummer
    # vergeben ist.
    if beleg.ist_aenderbar:
        beleg = beleg_festschreiben(beleg_id=beleg_id, benutzer=benutzer,
                                    mengen_bestaetigt=mengen_bestaetigt)

    _post_hinaus(beleg, empfaenger, betreff, nachricht, anlagen)

    zeitpunkt = timezone.now()

    # Nur beim ersten Versand, weil die Felder ihn nachweisen.
    if beleg.versendet_am is None:
        Beleg.objects.filter(pk=beleg.pk).update(
            versendet_am=zeitpunkt, versendet_an=empfaenger,
        )
        beleg.versendet_am = zeitpunkt
        beleg.versendet_an = empfaenger
    return beleg


def _post_hinaus(beleg: Beleg, an: str, betreff: str, nachricht: str,
                 anlagen: Iterable[str] = ()) -> None:
    """Sendet die Mail mit der gespeicherten Datei als Anhang, PDF oder
    XRechnung, nie beides.

    Fehlt das PDF (etwa bei einem importierten Beleg), wird es einmal
    erzeugt.
    """
    if not beleg.pdf:
        _dokument_einfrieren(beleg)
    anhang = versandformat(beleg)

    absender = absenderadresse()
    kopie = []
    if getattr(settings, 'FAKTURA_VERSAND_KOPIE', True):
        firma = Firma.objects.first()
        # Keine Kopie an den Absender, weil sie im Postausgang liegt.
        if firma and firma.email and firma.email != absender:
            kopie = [firma.email]
        elif absender:
            kopie = [absender]

    post = EmailMessage(
        subject=betreff or f'{beleg.get_typ_display()} {beleg.nummer}',
        body=nachricht,
        from_email=absender or None,
        to=[an],
        bcc=kopie,
    )
    if anhang == Versandanhang.PDF:
        beleg.pdf.open('rb')
        try:
            post.attach(f'{beleg.nummer}.pdf', beleg.pdf.read(),
                        'application/pdf')
        finally:
            beleg.pdf.close()
    else:
        beleg.xml.open('rb')
        try:
            post.attach(f'{beleg.nummer}.xml', beleg.xml.read(),
                        'application/xml')
        finally:
            beleg.xml.close()

    # Nach dem Festschreiben erzeugt, weil die Anlage die Belegnummer
    # enthält.
    quellen = anlagenquellen(beleg)
    for art in anlagen:
        if art in quellen:
            post.attach(anlage_dateiname(beleg, quellen[art].titel),
                        anlage_pdf(beleg, art), 'application/pdf')

    try:
        post.send()
    except Exception as fehler:
        raise VersandFehlgeschlagen(
            f'{beleg} ist festgeschrieben und gültig, aber die E-Mail an '
            f'{an} ging nicht hinaus: {fehler}. Laden Sie das PDF herunter '
            f'und schicken Sie es von Hand oder versuchen Sie den Versand '
            f'erneut, sobald der Postausgang wieder erreichbar ist.'
        ) from fehler
