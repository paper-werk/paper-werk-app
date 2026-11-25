"""Versand von Belegen per E-Mail einschließlich Festschreiben.

Versendet wird immer die gespeicherte Datei, nie ein neu gerendertes PDF,
weil das versendete Dokument der Beleg ist.
"""

from collections.abc import Iterable

from django.conf import settings
from django.core.mail import EmailMessage, mailers
from django.db.models import TextChoices
from django.utils import timezone

from .. import ereignisse
from ..models import Beleg, BelegTyp, Firma
from .anlagen import anlage_dateiname, anlage_pdf, anlagenquellen
from .fehler import EmpfaengeradresseFehlt, VersandFehlgeschlagen
from .festschreiben import _dokument_einfrieren, beleg_festschreiben

STANDARD_POSTAUSGANG = 'default'

#: Alias in ``MAILERS`` je Belegart. Storno, Rechnungskorrektur und Mahnung
#: gehen über den Postausgang der Rechnung, weil der Empfänger auf sie an
#: dieselbe Adresse antwortet. Ist der Alias nicht konfiguriert, gilt
#: ``STANDARD_POSTAUSGANG``.
POSTAUSGANG = {
    BelegTyp.ANGEBOT: 'angebot',
    BelegTyp.RECHNUNG: 'rechnung',
    BelegTyp.STORNO: 'rechnung',
    BelegTyp.GUTSCHRIFT: 'rechnung',
    BelegTyp.MAHNUNG: 'rechnung',
}


def postausgang(beleg: Beleg | None = None) -> str:
    """Alias des Postausgangs in ``MAILERS``, über den ``beleg`` versendet
    wird."""
    alias = POSTAUSGANG.get(beleg.typ) if beleg else None
    return alias if alias and alias in mailers else STANDARD_POSTAUSGANG


def absenderadresse(beleg: Beleg | None = None) -> str:
    """Absenderadresse des Postausgangs von ``beleg``.

    Ein eigener Postausgang hat seinen Absender in ``FAKTURA_ABSENDER``.
    Für den Standard hat ``DEFAULT_FROM_EMAIL`` Vorrang vor der
    Firmenadresse, weil manche SMTP-Server nur einen bestimmten Absender
    akzeptieren.
    """
    alias = postausgang(beleg)
    if alias != STANDARD_POSTAUSGANG:
        if eigener := getattr(settings, 'FAKTURA_ABSENDER', {}).get(alias):
            return eigener
    if eingestellt := getattr(settings, 'DEFAULT_FROM_EMAIL', ''):
        return eingestellt
    firma = Firma.objects.first()
    return firma.email if firma else ''


def kopieadresse(beleg: Beleg | None = None) -> str:
    """Empfänger der Blindkopie, leer bei ``FAKTURA_VERSAND_KOPIE=False``.

    Die Firmenadresse, unabhängig vom Postausgang, damit alle Kopien in
    einem Postfach liegen. Ohne Firmenadresse der Absender.
    """
    if not getattr(settings, 'FAKTURA_VERSAND_KOPIE', True):
        return ''
    firma = Firma.objects.first()
    if firma and firma.email:
        return firma.email
    return absenderadresse(beleg)


def versand_geht_hinaus(beleg: Beleg | None = None) -> bool:
    """Ob eine Mail für ``beleg`` tatsächlich versendet wird.

    Geprüft wird das Backend des Postausgangs von ``beleg``
    (``postausgang()``), weil ein eigener Postausgang per SMTP versendet,
    während ``default`` auf das Console-Backend zeigt, und umgekehrt.
    Maßgeblich ist das Backend, weil ``dev.py`` es unabhängig von
    ``EMAIL_HOST`` setzt.
    """
    backend = mailers.settings.get(postausgang(beleg), {}).get('BACKEND', '')
    return not any(art in backend for art in ('console', 'locmem', 'dummy'))


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
    ereignisse.melden(ereignisse.VERSENDET, beleg)
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

    alias = postausgang(beleg)
    absender = absenderadresse(beleg)
    kopie = kopieadresse(beleg)

    post = EmailMessage(
        subject=betreff or f'{beleg.get_typ_display()} {beleg.nummer}',
        body=nachricht,
        from_email=absender or None,
        to=[an],
        bcc=[kopie] if kopie else [],
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
        post.send(using=alias)
    except Exception as fehler:
        raise VersandFehlgeschlagen(
            f'{beleg} ist festgeschrieben und gültig, aber die E-Mail an '
            f'{an} ging nicht hinaus: {fehler}. Laden Sie das PDF herunter '
            f'und schicken Sie es von Hand oder versuchen Sie den Versand '
            f'erneut, sobald der Postausgang wieder erreichbar ist.'
        ) from fehler
