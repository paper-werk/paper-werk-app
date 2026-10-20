"""Folgebelege einer festgeschriebenen Rechnung: Storno,
Rechnungskorrektur, Mahnung.

Der Begriff "Gutschrift" wird vermieden, weil er im UStG die Abrechnung
durch den Leistungsempfänger bezeichnet (§ 14 Abs. 2).
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from ..models import (
    STEUERFREI,
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Firma,
    Rechnungsart,
    Textbaustein,
)
from ..models import steuersatz as steuersatz_tabelle
from ..positionsnummer import naechste_nummern
from ..standardtexte import MAHNEINLEITUNG
from .anlegen import _beleg_kopieren
from .fehler import FalscherStatus, UngueltigerBetrag
from .festschreiben import beleg_festschreiben, pruefe_rechnungskorrektur
from .zahlungen import nachlass, offener_betrag

#: Feld der Firma mit der Gebühr je Mahnstufe.
#
# Verzugszinsen fehlen, weil sie vom halbjährlich wechselnden
# Basiszinssatz abhängen und eine pflegbare Tabelle bräuchten.
MAHNGEBUEHR_FELD = {
    1: 'mahngebuehr_erinnerung',
    2: 'mahngebuehr_mahnung',
    3: 'mahngebuehr_letzte',
}


def mahngebuehr(stufe: int | None) -> Decimal:
    """Gebühr der Stufe aus den Firmendaten. Ohne Firma der Default des
    Modells, bei unbekannter Stufe 0."""
    feld = MAHNGEBUEHR_FELD.get(stufe)
    if feld is None:
        return Decimal('0.00')
    firma = Firma.aktuelle()
    if firma is None:
        return Firma._meta.get_field(feld).default
    return getattr(firma, feld)

#: Bezeichnung der Gebührenzeile, an der ``mahnstufe_angleichen`` sie
#: erkennt.
MAHNGEBUEHR_ZEILE = 'Mahngebühr'


@transaction.atomic
def rechnung_korrigieren(*, beleg_id: int, benutzer=None) -> tuple[Beleg, Beleg]:
    """Storniert eine Rechnung und legt sie als neuen Entwurf wieder an.

    Im Admin der Button "Rechnung korrigieren"; erzeugt eine
    festgeschriebene Stornorechnung und einen neuen Entwurf. Rückgabe:
    (Stornobeleg, neuer Entwurf).
    """
    original = Beleg.objects.select_for_update().get(pk=beleg_id)

    if original.status != BelegStatus.FESTGESCHRIEBEN:
        raise FalscherStatus(
            f'Nur festgeschriebene Belege werden storniert. {original} hat den '
            f'Status "{original.get_status_display()}".'
        )

    # Zuerst der Nachlass, dann die Rechnung, je Beleg ein eigener
    # Gegenbeleg, weil das Storno die volle Rechnung aufhöbe und der
    # Nachlass als zweite Gutschrift bliebe.
    korrekturen = original.nachfolger.filter(
        typ=BelegTyp.GUTSCHRIFT, status=BelegStatus.FESTGESCHRIEBEN)
    if korrekturen.exists():
        nummern = ', '.join(k.nummer for k in korrekturen)
        raise FalscherStatus(
            f'Auf {original} ist mit {nummern} ein Nachlass gewährt. Ein '
            f'Storno höbe die volle Rechnung auf, und der Nachlass käme '
            f'noch einmal dazu. Stornieren Sie zuerst den Nachlass (an der '
            f'Rechnungskorrektur „Weitere …“, „Nachlass stornieren“), dann '
            f'die Rechnung. Ist die Rechnung nur im Betrag zu hoch, genügt '
            f'ein weiterer Nachlass.'
        )

    storno = _beleg_kopieren(
        original,
        typ=BelegTyp.STORNO,
        vorgaenger=original,
        betreff=f'Storno zu {original.nummer}',
        vorzeichen=Decimal('-1'),
    )
    # Die zurückgegebene Instanz verwenden, die Nummer und Status enthält.
    # Das Storno wird sofort festgeschrieben.
    storno = beleg_festschreiben(beleg_id=storno.pk, benutzer=benutzer)

    # Kopie mit derselben Rechnungsart. Regression: Eine korrigierte
    # Abschlags-, Schluss- oder Teilschlussrechnung wurde zur gewöhnlichen
    # Rechnung (mit Leistungsdatum, gegen das Kontingent). Die Abnahme wird
    # übernommen, weil sie Grundlage der (Teil-)Schlussrechnung ist.
    neuer_entwurf = _beleg_kopieren(
        original,
        typ=original.typ,
        vorgaenger=original,
        betreff=original.betreff,
        rechnungsart=original.rechnungsart or None,
    )
    if original.abnahme_id:
        neuer_entwurf.abnahme_id = original.abnahme_id
        neuer_entwurf.save(update_fields=['abnahme'])

    original.status = BelegStatus.STORNIERT
    original.save()

    return storno, neuer_entwurf


@transaction.atomic
def nachlass_stornieren(*, beleg_id: int, benutzer=None) -> Beleg:
    """Hebt eine festgeschriebene Rechnungskorrektur durch ein eigenes
    Storno auf, ohne Neufassung. Rückgabe: das festgeschriebene Storno.

    Das Storno hat positive Beträge und stellt die Forderung wieder her;
    die E-Rechnung hat daher den Typ Rechnung (380) (``facturx.typcode``).
    Danach ist die Rechnung wieder stornierbar (``rechnung_korrigieren``).
    Je Beleg ein Gegenbeleg, damit bei Kunde und Steuerberater jeder offene
    Posten genau einen Ausgleich hat (entscheidungen.md,
    „Rechnungskorrektur und Nachlass“).
    """
    korrektur = Beleg.objects.select_for_update().get(pk=beleg_id)

    if korrektur.typ != BelegTyp.GUTSCHRIFT:
        raise FalscherStatus(
            f'{korrektur} ist keine Rechnungskorrektur.')
    if korrektur.status != BelegStatus.FESTGESCHRIEBEN:
        raise FalscherStatus(
            f'Nur ein festgeschriebener Nachlass wird storniert. '
            f'{korrektur} hat den Status '
            f'"{korrektur.get_status_display()}".')

    rechnung = korrektur.vorgaenger
    bezug = f' zu Rechnung {rechnung.nummer}' if rechnung else ''
    storno = _beleg_kopieren(
        korrektur,
        typ=BelegTyp.STORNO,
        vorgaenger=korrektur,
        betreff=f'Storno zu {korrektur.nummer} (Rechnungskorrektur)',
        vorzeichen=Decimal('-1'),
    )
    # Eigener Text, damit "schreiben wir Ihnen gut" aus der Korrektur
    # entfällt.
    storno.kopftext = (
        f'Hiermit stornieren wir unsere Rechnungskorrektur '
        f'{korrektur.nummer} vom {korrektur.belegdatum:%d.%m.%Y}{bezug}. '
        f'Der dort gewährte Nachlass entfällt.')
    storno.save(update_fields=['kopftext'])
    storno = beleg_festschreiben(beleg_id=storno.pk, benutzer=benutzer)

    korrektur.status = BelegStatus.STORNIERT
    korrektur.save()

    return storno


@transaction.atomic
def rechnungskorrektur_erstellen(
    *, beleg_id: int, betrag_netto: Decimal, grund: str,
    steuersatz: str | None = None,
) -> Beleg:
    """Legt einen nachträglichen Nachlass zu einer Rechnung als Entwurf an.

    Anders als beim Storno bleibt die Rechnung bestehen; steuerlich eine
    Entgeltminderung nach § 17 UStG. Der Betrag wird positiv übergeben und
    negiert. Ohne ``steuersatz`` gilt die Vorgabe der Tabelle.

    Festgeschrieben mindert sie den offenen Betrag der Rechnung (R-182).
    Nicht am Abschlag, nicht über den Rechnungsbetrag hinaus
    (``pruefe_rechnungskorrektur``); Begründung in
    ``docs/entscheidungen.md``, „Rechnungskorrektur und Nachlass“.
    """
    original = Beleg.objects.get(pk=beleg_id)

    if original.typ != BelegTyp.RECHNUNG:
        raise FalscherStatus(
            f'Eine Rechnungskorrektur bezieht sich auf eine Rechnung. '
            f'{original} ist vom Typ "{original.get_typ_display()}".'
        )

    # Nicht am Abschlag, weil ihn die Schlussrechnung abrechnet; nicht
    # Anerkanntes ist dort eine Kürzung bei der Zahlung.
    if original.rechnungsart == Rechnungsart.ABSCHLAG:
        raise FalscherStatus(
            f'{original} ist ein Abschlag. Erkennt der Kunde einen Teil '
            f'nicht an, wird bei der Zahlung gekürzt; die Schlussrechnung '
            f'fordert ihn dann neu.'
        )

    if original.status != BelegStatus.FESTGESCHRIEBEN:
        raise FalscherStatus(
            f'Eine Rechnungskorrektur bezieht sich auf eine festgeschriebene '
            f'Rechnung. {original} hat den Status '
            f'"{original.get_status_display()}".'
        )

    if betrag_netto <= 0:
        raise UngueltigerBetrag(
            'Der Nachlass ist als positiver Betrag anzugeben.'
        )

    korrektur = Beleg.objects.create(
        kunde=original.kunde,
        projekt=original.projekt,
        typ=BelegTyp.GUTSCHRIFT,
        status=BelegStatus.ENTWURF,
        vorgaenger=original,
        betreff=f'Rechnungskorrektur zu {original.nummer}',
        empfaenger=original.empfaenger,
        empfaenger_name=original.empfaenger_name,
        empfaenger_strasse=original.empfaenger_strasse,
        empfaenger_plz=original.empfaenger_plz,
        empfaenger_ort=original.empfaenger_ort,
        empfaenger_land=original.empfaenger_land,
        empfaenger_ust_id=original.empfaenger_ust_id,
        zahlungsziel_tage=original.zahlungsziel_tage,
        leistungsdatum=original.leistungsdatum,
        leistungsdatum_bis=original.leistungsdatum_bis,
        steuerliches_leistungsdatum=original.steuerliches_leistungsdatum,
        leitweg_id=original.leitweg_id,
        bestellnummer=original.bestellnummer,
        steuerfall=original.steuerfall,
        kopftext=f'Zu unserer Rechnung {original.nummer} vom '
                 f'{original.belegdatum:%d.%m.%Y} schreiben wir Ihnen gut:',
    )

    Belegposition.objects.create(
        beleg=korrektur,
        position=10,
        bezeichnung=grund,
        menge=Decimal('1'),
        einheit='pausch',
        einzelpreis=-betrag_netto,
        steuersatz=steuersatz or steuersatz_tabelle.vorgabe(),
    )
    pruefe_rechnungskorrektur(korrektur)

    return korrektur


def _mahneinleitung(stufe: int) -> str:
    """Anrede und Einleitung der Mahnstufe aus den Textbausteinen.

    Vorbelegung des änderbaren Kopftexts der Mahnung. Ohne Bausteine
    bleibt der Kopftext leer. Ohne Betrag, weil er nach einer Teilzahlung
    falsch wäre.
    """
    teile = [
        baustein.text
        for name in ('Anrede', MAHNEINLEITUNG.get(stufe))
        if (baustein := Textbaustein.objects.filter(name=name).first())
    ]
    return '\n\n'.join(teile)


def _grussformel() -> str:
    """Grußformel aus dem Baustein, damit die Mahnung mit dem Absender
    endet."""
    from ..standardtexte import GRUSSFORMEL
    baustein = Textbaustein.objects.filter(name=GRUSSFORMEL).first()
    return baustein.text if baustein else ''


def forderungszeile(mahnung: Beleg) -> Belegposition | None:
    """Zeile der Mahnung mit dem offenen Rechnungsbetrag, erkannt am Präfix
    der Bezeichnung aus ``_forderungstext``."""
    rechnung = mahnung.vorgaenger
    if rechnung is None or not rechnung.nummer:
        return None
    return mahnung.positionen.filter(
        bezeichnung__startswith=f'Rechnung {rechnung.nummer} vom').first()


def _forderungstext(rechnung: Beleg, offen: Decimal) -> str:
    """Rechnung, Datum, Fälligkeit und nach Teilzahlung oder Nachlass die
    Herleitung des Restbetrags, damit erkennbar ist, dass die Zahlung
    berücksichtigt wurde."""
    from .. import formate
    from .summen import belegsummen

    text = (f'Rechnung {rechnung.nummer} vom '
            f'{rechnung.belegdatum:%d.%m.%Y}')
    if rechnung.faellig_am:
        text += f', fällig seit {rechnung.faellig_am:%d.%m.%Y}'
    brutto = belegsummen(rechnung).brutto
    gemindert = nachlass(rechnung)
    bezahlt = brutto - gemindert - offen
    if offen < brutto:
        text += f', Rechnungsbetrag {formate.geld(brutto)} EUR'
    if gemindert:
        text += f', Nachlass {formate.geld(gemindert)} EUR'
    if bezahlt > 0:
        text += f', bereits bezahlt {formate.geld(bezahlt)} EUR'
    return text


@transaction.atomic
def mahnung_erstellen(*, beleg_id: int, stufe: int) -> Beleg:
    """Erzeugt eine Mahnung über den offenen Betrag einer fälligen Rechnung.

    Kein Steuerbeleg: Forderung und Mahngebühr (Schadenersatz) mit 0 %.
    Frist sieben Tage, unabhängig vom Zahlungsziel des Kunden.
    """
    rechnung = Beleg.objects.get(pk=beleg_id)

    if rechnung.typ != BelegTyp.RECHNUNG:
        raise FalscherStatus('Gemahnt werden nur Rechnungen.')

    if rechnung.status != BelegStatus.FESTGESCHRIEBEN:
        raise FalscherStatus(
            f'{rechnung} ist nicht festgeschrieben und damit nicht fällig.'
        )

    if stufe not in MAHNGEBUEHR_FELD:
        raise UngueltigerBetrag(f'Mahnstufe {stufe} gibt es nicht (1 bis 3).')

    # Verzug tritt erst nach Fälligkeit ein (§ 286 BGB); eine Mahnung davor
    # ist wirkungslos.
    heute = timezone.localdate()
    if rechnung.faellig_am and rechnung.faellig_am >= heute:
        raise FalscherStatus(
            f'{rechnung} ist erst am {rechnung.faellig_am:%d.%m.%Y} fällig. '
            f'Vor der Fälligkeit gibt es keinen Verzug und damit nichts zu '
            f'mahnen.'
        )

    # Offener Betrag, weil die Rechnungssumme nach einer Teilzahlung falsch
    # wäre.
    offen = offener_betrag(rechnung)

    if offen <= 0:
        raise FalscherStatus(
            f'{rechnung} ist ausgeglichen; da ist nichts zu mahnen.')

    mahnung = Beleg.objects.create(
        kunde=rechnung.kunde,
        projekt=rechnung.projekt,
        typ=BelegTyp.MAHNUNG,
        status=BelegStatus.ENTWURF,
        vorgaenger=rechnung,
        mahnstufe=stufe,
        # Der Betreff enthält den Bezug; die Belegart ist die Überschrift.
        betreff=f'Rechnung {rechnung.nummer} vom '
                f'{rechnung.belegdatum:%d.%m.%Y}',
        empfaenger=rechnung.empfaenger,
        zahlungsziel_tage=7,
        empfaenger_name=rechnung.empfaenger_name,
        empfaenger_strasse=rechnung.empfaenger_strasse,
        empfaenger_plz=rechnung.empfaenger_plz,
        empfaenger_ort=rechnung.empfaenger_ort,
        empfaenger_land=rechnung.empfaenger_land,
        empfaenger_ust_id=rechnung.empfaenger_ust_id,
        kopftext=_mahneinleitung(stufe),
        fusstext=_grussformel(),
    )

    # Aufstellung ohne Leistungspositionen, Menge und Einheit leer.
    Belegposition.objects.create(
        beleg=mahnung, position=10,
        bezeichnung=_forderungstext(rechnung, offen),
        menge=Decimal('1'), einheit='',
        einzelpreis=offen, steuersatz=STEUERFREI,
    )

    gebuehr = mahngebuehr(stufe)
    if gebuehr:
        Belegposition.objects.create(
            beleg=mahnung, position=20, bezeichnung=MAHNGEBUEHR_ZEILE,
            menge=Decimal('1'), einheit='',
            einzelpreis=gebuehr, steuersatz=STEUERFREI,
        )

    return mahnung


@transaction.atomic
def mahnstufe_angleichen(*, mahnung: Beleg, alte_stufe: int | None,
                         kopftext_geaendert: bool = False) -> None:
    """Aktualisiert Kopftext und Mahngebühr bei Wechsel der Stufe am Entwurf.

    Sonst stünde nach dem Wechsel auf "Letzte Mahnung" der Text der
    Zahlungserinnerung im Brief und keine Gebühr in der Aufstellung.

    Manuelle Änderungen bleiben: Der Kopftext wird nur ersetzt, wenn er der
    Vorbelegung der alten Stufe entspricht und nicht im selben POST geändert
    wurde; die Gebühr nur, wenn sie dem Default der alten Stufe entspricht.
    """
    stufe = mahnung.mahnstufe
    if stufe == alte_stufe or stufe not in MAHNGEBUEHR_FELD:
        return

    if not kopftext_geaendert and mahnung.kopftext == _mahneinleitung(
            alte_stufe):
        mahnung.kopftext = _mahneinleitung(stufe)
        mahnung.save(update_fields=['kopftext'])

    alte_gebuehr = mahngebuehr(alte_stufe)
    gebuehr = mahngebuehr(stufe)
    zeile = mahnung.positionen.filter(bezeichnung=MAHNGEBUEHR_ZEILE).first()
    if zeile is None:
        if alte_gebuehr == 0 and gebuehr:
            vergeben = [p.position for p in mahnung.positionen.all()]
            Belegposition.objects.create(
                beleg=mahnung, position=naechste_nummern(vergeben, 1)[0],
                bezeichnung=MAHNGEBUEHR_ZEILE, menge=Decimal('1'), einheit='',
                einzelpreis=gebuehr, steuersatz=STEUERFREI,
            )
    elif zeile.einzelpreis == alte_gebuehr:
        if gebuehr:
            zeile.einzelpreis = gebuehr
            zeile.save(update_fields=['einzelpreis'])
        else:
            zeile.delete()
