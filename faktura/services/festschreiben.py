"""Festschreiben, wieder öffnen, E-Rechnung neu ausstellen.

Das Festschreiben vergibt Nummer, Datum, Fälligkeit und speichert das
Dokument; danach ist der Beleg unveränderlich. Archiv- und Versandfelder
an festgeschriebenen Belegen werden über ``queryset.update()`` gesetzt und
umgehen ``Beleg.save()``, dessen Sperre dem Inhalt gilt.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import DecimalField, Sum
from django.utils import timezone
from sequences import get_next_value

from core.optimistic_locking import version_erhoehen

from .. import formate
from ..models import (
    STEUERFREI,
    Beleg,
    Belegfassung,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Firma,
    Rechnungsart,
)
from .abschlaege import ABSETZENDE, veraltete_abschlagsreste
from .archivierung import _archivierung_anstossen
from .fehler import (
    BelegOhnePositionen,
    DokumentFehlt,
    EmpfaengerFehlt,
    FalscherStatus,
    KeineERechnung,
    LeistungsdatumFehlt,
    MengeUeberschritten,
    UngueltigerBetrag,
    UnzulaessigerSteuersatz,
    WiedereroeffnenGesperrt,
)
from .summen import POSITIONSNETTO, belegsummen
from .zahlungen import nachlass
from .zuschlaege import bezugsfehler, ohne_bezug, zuschlaege_nachrechnen

logger = logging.getLogger(__name__)

#: Rechnung, Storno und Rechnungskorrektur teilen einen Nummernkreis, weil
#: alle drei steuerlich Rechnungen sind und die Lückenlosigkeit für die
#: Reihe gilt. Die übrigen Belegarten haben je einen eigenen.
#:
#: Explizit typisiert, weil die Schlüssel zur Laufzeit Strings sind und mit
#: dem str aus der Datenbank nachgeschlagen werden.
NUMMERNKREIS: dict[str, str] = {
    BelegTyp.ANGEBOT: 'angebot',
    BelegTyp.AUFTRAG: 'auftrag',
    BelegTyp.LIEFERSCHEIN: 'lieferschein',
    BelegTyp.RECHNUNG: 'rechnung',
    BelegTyp.STORNO: 'rechnung',
    BelegTyp.GUTSCHRIFT: 'rechnung',
    BelegTyp.MAHNUNG: 'mahnung',
}

PRAEFIX: dict[str, str] = {
    BelegTyp.ANGEBOT: 'AN',
    BelegTyp.AUFTRAG: 'AU',
    BelegTyp.LIEFERSCHEIN: 'LS',
    BelegTyp.RECHNUNG: 'RE',
    BelegTyp.STORNO: 'RE',
    BelegTyp.GUTSCHRIFT: 'RE',
    BelegTyp.MAHNUNG: 'MA',
}


def naechste_belegnummer(*, typ: str, jahr: int) -> str:
    """Nächste Nummer aus dem passenden Nummernkreis (RE-2026-0001).

    Mit django-sequences, weil eine PostgreSQL-Sequence Werte auch bei
    Rollback verbraucht und Lücken hinterlässt. django-sequences sperrt eine
    Zählerzeile bis zum Ende der Transaktion; bei Rollback ist die Nummer
    wieder frei. Der Aufruf **muss** daher in einer Transaktion stehen.
    """
    kreis = f'{NUMMERNKREIS[typ]}-{jahr}'
    laufend = get_next_value(kreis)
    return f'{PRAEFIX[typ]}-{jahr}-{laufend:04d}'


#: Filter der Rechnungspositionen, die gegen ihren Auftrag zählen, für
#: ``abgerechnete_mengen`` und ``berechneter_wert``.
AUF_DEN_AUFTRAG_BERECHNET = {
    'beleg__typ': BelegTyp.RECHNUNG,
    'beleg__rechnungsart__in': Rechnungsart.endgueltige(),
    'beleg__status': BelegStatus.FESTGESCHRIEBEN,
}


def abgerechnete_mengen(auftragspositionen) -> dict:
    """Verbindlich abgerechnete Menge je Auftragsposition.

    Schlüssel ist die ID der Position; nicht Abgerechnetes fehlt. Es zählen
    gewöhnliche und Schlussrechnungen, ohne Abschläge, weil diese
    Anzahlungen sind und die Schlussrechnung die Leistung erneut aufführt.
    Nur Festgeschriebenes; stornierte Rechnungen geben ihre Mengen frei.
    Stornopositionen haben keinen Auftragsbezug.
    """
    kennungen = [p.pk if hasattr(p, "pk") else p for p in auftragspositionen]
    if not kennungen:
        return {}

    summen = (
        Belegposition.objects
        .filter(auftragsposition_id__in=kennungen,
                **AUF_DEN_AUFTRAG_BERECHNET)
        .values('auftragsposition_id')
        .annotate(menge=Sum('menge'))
    )
    return {z['auftragsposition_id']: z['menge'] or Decimal('0')
            for z in summen}


def berechneter_wert(auftrag) -> Decimal:
    """Verbindlich berechneter Nettobetrag des Auftrags, über
    ``POSITIONSNETTO`` mit Rundung je Position. Dieselbe Auswahl wie
    ``abgerechnete_mengen``."""
    ergebnis = (
        Belegposition.objects
        .filter(auftragsposition__beleg=auftrag, **AUF_DEN_AUFTRAG_BERECHNET)
        .aggregate(summe=Sum(
            POSITIONSNETTO,
            output_field=DecimalField(max_digits=14, decimal_places=2)))
    )
    return ergebnis['summe'] or Decimal('0.00')


@dataclass(frozen=True)
class Mengenueberschreitung:
    """Auftragsposition, deren Menge diese Rechnung überschreitet."""

    auftragsposition: Belegposition
    #: Von festgeschriebenen Rechnungen abgerechnete Menge.
    vorher: Decimal
    #: Von dieser Rechnung abgerechnete Menge.
    hier: Decimal

    @property
    def zu_viel(self) -> Decimal:
        return self.vorher + self.hier - self.auftragsposition.menge

    def __str__(self) -> str:
        position = self.auftragsposition
        return (
            f'{position.beleg.nummer or "Auftrag"}, Position '
            f'{position.position} "{position.bezeichnung}": beauftragt sind '
            f'{position.menge.normalize():f} {position.einheit}, davon '
            f'bereits {self.vorher.normalize():f} abgerechnet. Diese Rechnung '
            f'fordert weitere {self.hier.normalize():f}; das sind '
            f'{self.zu_viel.normalize():f} zu viel.'
        )


def mengenueberschreitungen(beleg: Beleg) -> list[Mengenueberschreitung]:
    """Positionen, bei denen diese Rechnung zusammen mit den
    festgeschriebenen mehr abrechnet als beauftragt; leer, wenn alles passt.

    Ein Abschlag verbraucht kein Kontingent und überschreitet nie. Der
    Vergleich ist nur bei gleichen Einheiten aussagekräftig (12 Analysen
    gegen "1 pauschal" ergeben eine formale Überschreitung); deshalb nur ein
    Hinweis ohne Sperre.

    Eine **optionale** Auftragsposition überschreitet nie, weil dort der
    Preis beauftragt ist und die Menge nach Bedarf abgerufen wird.
    """
    if beleg.rechnungsart not in Rechnungsart.endgueltige():
        return []

    eigene: dict = {}
    for position in beleg.positionen.select_related(
            'auftragsposition__beleg'):
        if (position.auftragsposition_id
                and not position.auftragsposition.optional):
            eintrag = eigene.setdefault(position.auftragsposition_id,
                                        [position.auftragsposition, Decimal('0')])
            eintrag[1] += position.menge

    if not eigene:
        return []

    bereits = abgerechnete_mengen(eigene)
    ergebnis = []
    for kennung, (auftragsposition, hier) in eigene.items():
        vorher = bereits.get(kennung, Decimal('0'))
        if vorher + hier > auftragsposition.menge:
            ergebnis.append(Mengenueberschreitung(
                auftragsposition=auftragsposition, vorher=vorher, hier=hier))
    ergebnis.sort(key=lambda u: (u.auftragsposition.beleg_id,
                                 u.auftragsposition.sortierung))
    return ergebnis


def _pruefe_mengen(beleg: Beleg, *, bestaetigt: bool) -> None:
    """Verhindert, dass alle Rechnungen zusammen mehr abrechnen als
    beauftragt, sofern die Überschreitung nicht bestätigt ist.

    Beim Festschreiben, weil ein Entwurf zwischenzeitlich inkonsistent sein
    darf. Kein Constraint, weil über mehrere Belege summiert wird.

    Ohne Bestätigung bricht das Festschreiben ab, damit niemand versehentlich
    über den Auftrag hinaus abrechnet. Die Maske zeigt die Überschreitung
    vorher und verlangt eine Bestätigung; die API verlangt
    ``mengen_bestaetigt``.
    """
    if bestaetigt:
        return
    ueberschreitungen = mengenueberschreitungen(beleg)
    if ueberschreitungen:
        raise MengeUeberschritten(
            ' '.join(str(u) for u in ueberschreitungen)
            + ' Wer das so will, bestätigt die Überschreitung in der Maske '
              '„Versenden“; sonst die Menge anpassen oder einen Nachtrag '
              'anlegen.'
        )


def _pruefe_mahnung(mahnung: Beleg) -> None:
    """Verhindert eine Mahnung über bereits gezahlte Beträge.

    Zwischen Entwurf und Versand kann eine Zahlung eingehen. Eine Mahnung
    über eine bezahlte Rechnung oder über den alten Betrag nach einer
    Teilzahlung forderte zu viel. Der Betrag wird nicht automatisch
    angepasst, damit der Text der Mahnung vor dem Versand geprüft wird.
    """
    # Lokaler Import, weil korrektur.py dieses Modul importiert.
    from .korrektur import forderungszeile
    from .zahlungen import offener_betrag

    rechnung = mahnung.vorgaenger
    if rechnung is None:
        return
    if rechnung.status != BelegStatus.FESTGESCHRIEBEN:
        raise FalscherStatus(
            f'{rechnung} ist nicht mehr offen ({rechnung.get_status_display()}). '
            f'{mahnung} bitte löschen.')
    offen = offener_betrag(rechnung)
    if offen <= 0:
        raise FalscherStatus(
            f'{rechnung} ist inzwischen bezahlt. {mahnung} bitte löschen.')
    zeile = forderungszeile(mahnung)
    if zeile is not None and zeile.einzelpreis != offen:
        raise UngueltigerBetrag(
            f'Auf {rechnung} sind inzwischen noch {formate.geld(offen)} EUR '
            f'offen, die Mahnung fordert {formate.geld(zeile.einzelpreis)} '
            f'EUR. Bitte {mahnung} löschen und neu erzeugen.')


def pruefe_rechnungskorrektur(korrektur: Beleg) -> None:
    """Ein Nachlass mindert eine festgeschriebene Rechnung, höchstens um
    ihren Bruttobetrag abzüglich früherer Nachlässe (R-182).

    Beim Anlegen und erneut beim Festschreiben, weil der Entwurf geändert,
    die Rechnung storniert oder ein anderer Nachlass festgeschrieben worden
    sein kann.
    """
    rechnung = korrektur.vorgaenger
    if rechnung is None:
        return
    if rechnung.status != BelegStatus.FESTGESCHRIEBEN:
        raise FalscherStatus(
            f'{rechnung} ist nicht mehr gültig '
            f'({rechnung.get_status_display()}); ein Nachlass darauf ist '
            f'nicht möglich. {korrektur} bitte löschen.')

    dieser = -belegsummen(korrektur).brutto
    if dieser <= 0:
        raise UngueltigerBetrag(
            f'{korrektur} mindert nichts: Die Summe einer '
            f'Rechnungskorrektur ist negativ.')

    brutto = belegsummen(rechnung).brutto
    bisher = nachlass(rechnung)
    if bisher + dieser > brutto:
        frueher = (f', davon schon gewährt {formate.geld(bisher)} EUR'
                   if bisher else '')
        raise UngueltigerBetrag(
            f'Der Nachlass von {formate.geld(dieser)} EUR brutto ist höher '
            f'als {rechnung} über {formate.geld(brutto)} EUR{frueher}.')


@transaction.atomic
def beleg_festschreiben(
    *, beleg_id: int, belegdatum: date | None = None, benutzer=None,
    mengen_bestaetigt: bool = False,
) -> Beleg:
    """Schreibt einen Entwurf fest.

    Prüft die Pflichtangaben, vergibt die Nummer (ein wiedereröffneter Beleg
    behält seine), setzt Datum und Fälligkeit, speichert das Dokument und
    startet nach dem Commit die Archivierung.

    Belegdatum: ``belegdatum``, sonst der Wert im Entwurf, sonst heute,
    damit ein am Monatsletzten geschriebener und am Folgetag freigegebener
    Beleg das Datum des Monatsletzten behält. ``benutzer`` wird als
    ``festgeschrieben_von`` gespeichert (GoBD: Benutzer zum Zeitpunkt); ein
    User-Objekt, kein Request.
    ``mengen_bestaetigt`` lässt eine Rechnung über den Auftrag hinaus zu
    (``mengenueberschreitungen``).
    """
    # Row Lock, damit zwei gleichzeitige Requests nicht zwei Nummern
    # vergeben.
    beleg = Beleg.objects.select_for_update().get(pk=beleg_id)

    if beleg.status != BelegStatus.ENTWURF:
        raise FalscherStatus(f'{beleg} ist bereits festgeschrieben.')

    if not beleg.positionen.exists():
        raise BelegOhnePositionen('Ein Beleg ohne Positionen kann nicht festgeschrieben werden.')

    # Zuschläge neu berechnen, damit kein veralteter Betrag festgeschrieben
    # wird (R-180).
    zuschlaege_nachrechnen(beleg)
    # Auch ohne Formular, weil in einer Rechnung aus einem Auftrag die
    # optionale Position fehlt, auf die sich ein Zuschlag dort bezog.
    for zuschlag in ohne_bezug(beleg.positionen.all()):
        raise UngueltigerBetrag(
            f'Zuschlag {zuschlag.position} „{zuschlag.bezeichnung}“: '
            f'{bezugsfehler(zuschlag)}')

    # Pflichtangaben nach § 14 UStG, nur bei Steuerbelegen. Der Abschlag
    # braucht einen Zeitraum (den Leistungsstand) und hat kein
    # Leistungsdatum (``Beleg.steuerliches_leistungsdatum``). Alle anderen
    # brauchen das Leistungsdatum, der Zeitraum ist optional.
    if beleg.typ in BelegTyp.steuerbelege() and beleg.ist_anzahlung:
        if not (beleg.leistungsdatum and beleg.leistungsdatum_bis):
            raise LeistungsdatumFehlt(
                f'Ein Abschlag nennt den Zeitraum, auf den er sich bezieht; '
                f'Beginn und Stichtag, z. B. Projektbeginn bis heute. Fehlt '
                f'bei {beleg}.'
            )
    elif (beleg.typ in BelegTyp.steuerbelege()
            and not beleg.steuerliches_leistungsdatum):
        raise LeistungsdatumFehlt(
            f'Bei einer Rechnung ist das Leistungsdatum Pflichtangabe '
            f'(§ 14 Abs. 4 Nr. 6 UStG). Fehlt bei {beleg}.'
        )

    if beleg.typ in BelegTyp.steuerbelege() and not beleg.empfaenger.strip():
        raise EmpfaengerFehlt(
            f'Ohne Empfängeranschrift keine Rechnung '
            f'(§ 14 Abs. 4 Nr. 1 UStG). Fehlt bei {beleg}.'
        )

    # Kleinunternehmer und Steuerfälle (§ 13b, EU, Drittland) weisen keine
    # Steuer aus, weil sonst das XML "steuerfrei" enthielte, während die
    # Positionen 19 % berechnen. Keine automatische Umstellung.
    firma = Firma.aktuelle()
    if (
        firma is not None and firma.kleinunternehmer
        and beleg.typ in BelegTyp.wertbelege()
        and beleg.positionen.exclude(steuersatz=STEUERFREI).exists()
    ):
        raise UnzulaessigerSteuersatz(
            f'{firma} ist Kleinunternehmer nach § 19 UStG und darf '
            f'keine Umsatzsteuer ausweisen. {beleg} hat Positionen mit '
            f'einem Steuersatz über 0 Prozent.'
        )

    if (
        beleg.steuerfall
        and beleg.typ in BelegTyp.wertbelege()
        and beleg.positionen.exclude(steuersatz=STEUERFREI).exists()
    ):
        raise UnzulaessigerSteuersatz(
            f'{beleg} hat den Steuerfall „{beleg.get_steuerfall_display()}“ '
            f'und darf keine Umsatzsteuer ausweisen. Stellen Sie alle '
            f'Positionen auf 0 % oder den Steuerfall auf den Regelfall.'
        )

    # Der nicht bezahlte Teil eines Abschlags hängt von den Zahlungen ab.
    # Nach einer späteren Zahlung ist die Restzeile veraltet, und die
    # Rechnung forderte Bezahltes (R-174).
    if (beleg.typ == BelegTyp.RECHNUNG
            and beleg.rechnungsart in ABSETZENDE):
        veraltet = veraltete_abschlagsreste(beleg)
        if veraltet:
            nummern = ', '.join(b.nummer or str(b) for b in veraltet)
            raise UngueltigerBetrag(
                f'Seit dem Absetzen hat sich geändert, was auf {nummern} '
                f'bezahlt ist. Bitte „Abschläge absetzen“ noch einmal '
                f'ausführen, dann stimmt der nicht bezahlte Teil wieder.'
            )

    if beleg.typ == BelegTyp.MAHNUNG:
        _pruefe_mahnung(beleg)

    if beleg.typ == BelegTyp.GUTSCHRIFT:
        pruefe_rechnungskorrektur(beleg)

    # Zuletzt, weil sie als einzige Prüfung andere Belege liest, und vor der
    # Vergabe der Nummer.
    _pruefe_mengen(beleg, bestaetigt=mengen_bestaetigt)

    beleg.belegdatum = belegdatum or beleg.belegdatum or timezone.localdate()

    if not beleg.nummer:
        beleg.nummer = naechste_belegnummer(typ=beleg.typ, jahr=beleg.belegdatum.year)
    beleg.status = BelegStatus.FESTGESCHRIEBEN
    beleg.festgeschrieben_am = timezone.now()
    beleg.festgeschrieben_von = benutzer

    if beleg.typ in BelegTyp.mit_zahlungsziel():
        beleg.faellig_am = beleg.belegdatum + timedelta(days=beleg.zahlungsziel_tage)

    beleg.save()

    if beleg.typ in BelegTyp.mit_dokument():
        _dokument_ablegen(beleg)

    return beleg


def _dokument_ablegen(beleg: Beleg) -> None:
    """Erzeugt das PDF und archiviert es nach dem Commit.

    Ein wiedereröffneter Beleg hat weder PDF noch Archivnummer und erhält
    hier ein neues Dokument. Archiviert wird nach dem Commit, damit das
    Archiv nichts enthält, was durch Rollback nicht entstand, und der Upload
    keinen Lock hält.

    Eigene Funktion, damit Tests das Rendern (etwa 0,25 s je Beleg) an einer
    Stelle abschalten können, siehe ``conftest.py``.
    """
    _dokument_einfrieren(beleg)
    transaction.on_commit(lambda: _archivierung_anstossen(beleg.pk))


@transaction.atomic
def beleg_wiedereroeffnen(*, beleg_id: int, benutzer=None) -> Beleg:
    """Setzt ein festgeschriebenes Angebot oder einen Auftrag zurück in den
    Entwurf.

    Ohne dritten Zustand: Der Beleg ist danach ein gewöhnlicher Entwurf. Er
    behält seine Nummer, verliert den Archivverweis (das Dokument dort gehört
    zur alten Fassung und bleibt) und erhält dauerhaft
    ``geaendert_am/-von`` (GoBD).

    PDF und XML werden vom Beleg gelöst, weil ``ansicht_pdf`` eine
    gespeicherte Datei statt der Vorschau ausliefert; der Entwurf zeigte
    sonst den Stand vom Festschreiben. Die Dateien bleiben im
    Ablageverzeichnis, das Festschreiben legt neue an.

    Über ``update()``, weil ``save()`` Änderungen an festgeschriebenen
    Belegen ablehnt.
    """
    beleg = Beleg.objects.select_for_update().get(pk=beleg_id)

    if beleg.typ not in BelegTyp.entsperrbar():
        raise WiedereroeffnenGesperrt(
            f'{beleg} ist ein Buchungsbeleg und bleibt festgeschrieben. '
            f'Für eine Korrektur wird storniert.'
        )

    if beleg.status != BelegStatus.FESTGESCHRIEBEN:
        raise FalscherStatus(
            f'{beleg} ist nicht festgeschrieben; da gibt es nichts zu '
            f'öffnen.'
        )

    Beleg.objects.filter(pk=beleg.pk).update(
        status=BelegStatus.ENTWURF,
        geaendert_am=timezone.now(),
        geaendert_von=benutzer,
        # Auch die offene Task-ID, weil der nächste Lauf sonst das Dokument
        # der alten Fassung als neues speicherte.
        paperless_id=None,
        archiviert_am=None,
        paperless_task_id='',
        pdf=None, pdf_sha256='', xml=None, xml_sha256='',
        erechnungsprofil='', vorlagenversion='',
    )
    # Version inkrementieren, damit ein vor dem Festschreiben geladenes
    # Formular den wiedereröffneten Beleg nicht überschreibt.
    version_erhoehen(Beleg, beleg.pk)
    beleg.refresh_from_db()

    logger.info('Beleg %s wieder geöffnet durch %s (Archivdokument gelöst).',
                beleg.nummer, benutzer or 'unbekannt')
    return beleg


@transaction.atomic
def erechnung_neu_ausstellen(
    *, beleg_id: int, grund: str, leitweg_id: str | None = None,
    bestellnummer: str | None = None, benutzer=None,
) -> Beleg:
    """Stellt die E-Rechnung einer festgeschriebenen Rechnung neu aus, etwa
    nach Ablehnung durch ein Rechnungsportal.

    Änderbar sind Leitweg-ID und Bestellnummer sowie Angaben aus den
    Stammdaten (Kontakt der Firma, Zustellweg und damit Profil). Nummer,
    Datum, Positionen und Beträge bleiben; die Funktion hat dafür keine
    Parameter. Die alte Fassung bleibt als ``Belegfassung``, die neue wird
    als eigenes Dokument archiviert.

    Die Zulässigkeit derselben Nummer gehört in die Verfahrensdokumentation
    des Betriebs (Vorlage, Abschnitt 2.3).
    """
    from .. import facturx

    beleg = Beleg.objects.select_for_update().get(pk=beleg_id)

    if beleg.status != BelegStatus.FESTGESCHRIEBEN:
        raise FalscherStatus(
            f'{beleg}: Neu ausstellen lässt sich nur eine festgeschriebene '
            f'Rechnung. Diese steht auf "{beleg.get_status_display()}".'
        )
    if beleg.typ not in facturx.TYP_CODE:
        raise KeineERechnung(f'Zu {beleg} gibt es keine E-Rechnung.')
    if not beleg.pdf:
        raise KeineERechnung(
            f'{beleg} hat noch kein Dokument; es entsteht beim '
            f'Festschreiben, eine Neuausstellung ist nicht nötig.'
        )
    if not grund.strip():
        raise KeineERechnung(
            'Ohne Grund keine Neuausstellung; er ist das, wonach der '
            'Prüfer fragt.'
        )

    Belegfassung.objects.create(
        beleg=beleg,
        pdf=beleg.pdf.name,
        pdf_sha256=beleg.pdf_sha256,
        xml=beleg.xml.name or None,
        xml_sha256=beleg.xml_sha256,
        erechnungsprofil=beleg.erechnungsprofil,
        vorlagenversion=beleg.vorlagenversion,
        leitweg_id=beleg.leitweg_id,
        bestellnummer=beleg.bestellnummer,
        paperless_id=beleg.paperless_id,
        abgeloest_von=benutzer,
        grund=grund.strip(),
    )

    Beleg.objects.filter(pk=beleg.pk).update(
        leitweg_id=beleg.leitweg_id if leitweg_id is None else leitweg_id,
        bestellnummer=(beleg.bestellnummer if bestellnummer is None
                       else bestellnummer),
        pdf=None, pdf_sha256='', xml=None, xml_sha256='',
        erechnungsprofil='',
        # Das Archivdokument gehört zur alten Fassung und ist dort
        # gespeichert.
        paperless_id=None, archiviert_am=None, paperless_task_id='',
    )
    version_erhoehen(Beleg, beleg.pk)
    beleg.refresh_from_db()

    # Bei einem Fehler Rollback; die alte Fassung bleibt gültig.
    _dokument_einfrieren(beleg)
    transaction.on_commit(lambda: _archivierung_anstossen(beleg.pk))

    logger.info('E-Rechnung zu %s neu ausgestellt durch %s: %s',
                beleg.nummer, benutzer or 'unbekannt', grund)
    beleg.refresh_from_db()
    return beleg


def _dokument_einfrieren(beleg: Beleg) -> None:
    """Erzeugt das PDF einmalig und speichert es mit Prüfsumme und
    Template-Version am Beleg, bei E-Rechnungen dazu das XML mit denselben
    Bytes wie im PDF.

    Das gespeicherte PDF ist der Beleg, damit eine Änderung am Layout alte
    Rechnungen nicht ändert. Schlägt die Erzeugung fehl, schlägt das
    Festschreiben in derselben Transaktion fehl, und die Nummer ist wieder
    frei.
    """
    # Lokaler Import, weil pdf.py WeasyPrint samt GTK lädt.
    from django.core.files.base import ContentFile

    from .. import facturx
    from .. import pdf as pdf_modul

    try:
        xml = (facturx.xml_erzeugen(beleg)
               if facturx.ist_erechnungsfaehig(beleg) else None)
        daten = pdf_modul.beleg_als_pdf(beleg, xml=xml)
    except Exception as fehler:
        raise DokumentFehlt(
            f'Das PDF zu {beleg} konnte nicht erzeugt werden: {fehler}'
        ) from fehler

    try:
        beleg.pdf.save(
            pdf_modul.dateiname(beleg), ContentFile(daten), save=False
        )
        if xml is not None:
            beleg.xml.save(
                pdf_modul.dateiname(beleg, 'xml'), ContentFile(xml),
                save=False,
            )
    except Exception as fehler:
        raise DokumentFehlt(
            f'Das PDF zu {beleg} wurde erzeugt, konnte aber nicht abgelegt '
            f'werden: {fehler}'
        ) from fehler

    xml_pruefsumme = pdf_modul.pruefsumme(xml) if xml is not None else ''
    profil = facturx.profilname(beleg) if xml is not None else ''

    Beleg.objects.filter(pk=beleg.pk).update(
        pdf=beleg.pdf.name,
        pdf_sha256=pdf_modul.pruefsumme(daten),
        xml=beleg.xml.name if xml is not None else None,
        xml_sha256=xml_pruefsumme,
        erechnungsprofil=profil,
        vorlagenversion=pdf_modul.VORLAGENVERSION,
    )
    beleg.pdf_sha256 = pdf_modul.pruefsumme(daten)
    beleg.xml_sha256 = xml_pruefsumme
    beleg.erechnungsprofil = profil
    beleg.vorlagenversion = pdf_modul.VORLAGENVERSION
