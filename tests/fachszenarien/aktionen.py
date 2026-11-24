"""Fachliche Aktionen der Fälle, abgebildet auf Masken und Formular-POSTs.

Jede Aktion bekommt den ``Lauf`` und den Schritt aus der TOML-Datei. Sie
bedient die Masken wie ein Benutzer und legt die entstandenen Belege unter
ihrem Namen aus dem Fall ab (``lauf.belege['AR1']``). Gelesen wird über die
Datenbank, geschrieben nur über die Masken.

Einrichtung: Kunde, Projekt und Einheit legt ``einrichten`` direkt an. Sie
sind Stammdaten und kein Schritt eines Falls.

Abbildung der Leistungen:

* Pauschale Leistungen mit Leistungsstand (``LPH3 = "0.4"``) stehen im
  Auftrag mit Menge 100 in der Einheit Prozent (UN/ECE ``P1``) und einem
  Preis von einem Hundertstel des Betrags. Ein Abschlag erfasst den Zuwachs
  in Prozent auf die Auftragsposition und übernimmt ihn mit "Erbrachte
  Leistungen hinzufügen". So bleibt jede Rechnungsposition mit ihrer
  Auftragsposition verbunden, was kumulierter Abschlag und Schlussrechnung
  voraussetzen. Der Psch-Weg scheidet aus, weil eine Pauschale in der
  Erfassung immer Menge 1 hat.
* Stundensätze stehen mit der geschätzten Menge (oder 0) in Stunden im
  Auftrag; Stunden werden als Zeit erfasst.
* Zuschläge ``auf = "alle Leistungen"`` sind Zuschlagszeilen mit leerem
  "Zuschlag auf".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.urls import reverse

from erfassung.models import Erfassungszeile, Fremdleistung
from faktura import services
from faktura.admin.gemeinsam import adresse_im_admin
from faktura.models import (
    Abnahme,
    Abzugsgrundlage,
    Beleg,
    BelegStatus,
    BelegTyp,
    Katalogposition,
    Kontakt,
    Projekt,
    Rechnungsart,
    Zahlung,
    Zahlungszuordnung,
)
from faktura.models.einheit import Einheit, Leistungsart

from . import maske
from .fall import Bindung, Fall, aufloesen, betrag

PROZENT = 'P1'
PAUSCHAL = 'LS'
STUNDE = 'HUR'
#: Bezeichnung der Position, die das Zeithonorar auf die Obergrenze kappt.
KAPPUNG = 'Obergrenze Zeithonorar'
HUNDERT = Decimal('100')
CENT = Decimal('0.01')


class Luecke(Exception):
    """Paper-Werk kann den Schritt nicht abbilden."""


@dataclass
class Lauf:
    """Zustand eines Falls während des Durchspielens."""

    fall: Fall
    client: object
    uhr: object
    bindung: Bindung
    projekt: Projekt | None = None
    lieferant: Kontakt | None = None
    kunden: dict[str, Kontakt] = field(default_factory=dict)
    #: Name aus dem Fall auf Beleg-PK ("angebot", "auftrag", "AR1", "N1").
    belege: dict[str, int] = field(default_factory=dict)
    #: Kennung auf PK der Auftragsposition.
    auftragspositionen: dict[str, int] = field(default_factory=dict)
    #: Kennung auf abgerechneten Leistungsstand (Anteil 0 bis 1).
    stand: dict[str, Decimal] = field(default_factory=dict)
    #: Kennung auf Betrag, Bezeichnung, Art (leistung, stunde).
    katalog: dict[str, dict] = field(default_factory=dict)
    #: Erfassungszeilen, die noch nicht übernommen sind, mit Kennung.
    offene_zeilen: dict[int, str] = field(default_factory=dict)
    #: Fremdleistungen, die noch nicht übernommen sind, mit Kennung.
    offene_fremd: dict[int, str] = field(default_factory=dict)
    #: Kennung auf Katalogposition für Stunden ohne Auftragsposition.
    katalogpositionen: dict[str, int] = field(default_factory=dict)
    #: Erfasste Stunden je Kennung.
    stunden: dict[str, Decimal] = field(default_factory=dict)
    #: Tag der letzten Erfassung, Ende des Leistungszeitraums einer
    #: gewöhnlichen Rechnung.
    letzte_leistung: date | None = None
    zahlungen: list[int] = field(default_factory=list)
    #: Einkauf netto je Kennung einer Fremdleistung, für die Abrechnung
    #: nach Nachweis (``_nach_nachweis``).
    einkauf: dict[str, Decimal] = field(default_factory=dict)
    #: Obergrenze des Zeithonorars aus dem Nachtragsangebot, netto.
    obergrenze: Decimal | None = None
    #: Gekürzte, noch zu fordernde Beträge je Rechnungsname, brutto.
    strittig: dict[str, Decimal] = field(default_factory=dict)
    #: Lücken, nach denen der Fall weiterläuft; der Test übernimmt sie
    #: nach jedem Schritt als Befund.
    luecken: list[str] = field(default_factory=list)

    def beleg(self, name: str) -> Beleg:
        return Beleg.objects.get(pk=self.belege[name])

    def wert(self, wert):
        return aufloesen(wert, self.bindung)


# --- Einrichtung -------------------------------------------------------------

def einrichten(lauf: Lauf) -> None:
    """Kunde(n), Lieferant, Projekt mit Einbehalt, Einheit Prozent,
    Katalogpositionen der Stundensätze.

    Ein Sicherheitseinbehalt (``[einbehalt]``) wird mit Grundlage brutto
    eingerichtet. Paper-Werk kennt beide Grundlagen; brutto ist R3.A in
    Fall 02, weil eine Einstellung nur eine Variante zulässt.
    """
    fall = lauf.fall
    einheit, _ = Einheit.objects.get_or_create(code=PROZENT)
    einheit.anzeige = '%'
    einheit.erfassungsart = Leistungsart.MENGE
    einheit.zur_auswahl = True
    einheit.save()

    kunden = fall.liste('kunde') or [{'kennung': 'AG', 'name': 'Auftraggeber GmbH'}]
    for nummer, k in enumerate(kunden, start=1):
        lauf.kunden[k['kennung']] = Kontakt.anlegen(
            nummer=f'K-{fall.nummer}{nummer:02d}', name=k['name'],
            strasse='Hauptstraße 1', plz='80331', ort='München',
            email=f'k{nummer}@example.invalid', ist_kunde=True)
    auftraggeber = next(
        (lauf.kunden[k['kennung']] for k in kunden
         if k.get('rolle', 'Auftraggeber') == 'Auftraggeber'),
        next(iter(lauf.kunden.values())))
    skonto = fall.daten.get('skonto', {})
    if skonto:
        auftraggeber.skonto_prozent = betrag(skonto['prozent'])
        auftraggeber.skonto_tage = skonto['tage']
        auftraggeber.save()
    einbehalt = fall.daten.get('einbehalt', {})
    lauf.projekt = Projekt.objects.create(
        nummer=f'2026-{fall.nummer}', bezeichnung=fall.titel[:100],
        kunde=auftraggeber,
        einbehalt_prozent=(betrag(einbehalt['erfuellung_prozent'])
                           if 'erfuellung_prozent' in einbehalt else None),
        einbehalt_grundlage=Abzugsgrundlage.BRUTTO)
    lauf.lieferant = Kontakt.objects.create(
        nummer=f'L-{fall.nummer}', name='Nachunternehmer GmbH',
        ist_kunde=False, ist_lieferant=True)

    for leistung in fall.liste('leistung'):
        lauf.katalog[leistung['kennung']] = {**leistung, 'art': 'leistung'}
    for satz in fall.liste('stundensatz'):
        lauf.katalog[satz['kennung']] = {**satz, 'art': 'stunde'}
        lauf.katalogpositionen[satz['kennung']] = Katalogposition.objects.create(
            nummer=f'{fall.nummer}-{satz["kennung"]}', bezeichnung=satz['bezeichnung'],
            einheit=STUNDE, einzelpreis=betrag(satz['preis']),
            steuersatz=fall.steuersatz, kontierbar=True).pk
    for fremd in fall.liste('fremdleistung'):
        lauf.katalog[fremd['kennung']] = {**fremd, 'art': 'fremd'}


# --- Hilfen ------------------------------------------------------------------

def _url(beleg: Beleg, aktion: str | None = None) -> str:
    """URL der Maske oder einer Detailaktion am Proxy der Belegart."""
    aenderung = adresse_im_admin(beleg)
    if aktion is None:
        return aenderung
    # .../<pk>/change/ -> .../<pk>/<aktion>/
    return aenderung.rsplit('change/', 1)[0] + f'{aktion}/'


def _runden(wert: Decimal) -> Decimal:
    return wert.quantize(CENT, rounding=ROUND_HALF_UP)


def _positionszeilen(formular, kennungen, lauf: Lauf, zuschlaege,
                     mengen=None) -> None:
    """Füllt die Positionen eines Angebots. ``mengen``: geschätzte
    Stunden je Kennung, sonst ``geschaetzt`` aus dem Stundensatz."""
    nummer = 0
    for eintrag in kennungen:
        if isinstance(eintrag, dict):
            lauf.katalog[eintrag['kennung']] = {**eintrag, 'art': 'leistung'}
            kennung = eintrag['kennung']
        else:
            kennung = eintrag
        k = lauf.katalog[kennung]
        nummer += 10
        index = formular.freie_zeile('positionen')
        if k['art'] == 'leistung':
            preis = betrag(k['betrag']) / HUNDERT
            if preis != _runden(preis):
                raise Luecke(f'{kennung}: {k["betrag"]} nicht in Prozent '
                             f'mit Cent-Preis darstellbar')
            formular.zeile('positionen', index, zeilenart='leistung',
                           position=nummer, bezeichnung=k['bezeichnung'],
                           menge='100', einheit=PROZENT,
                           einzelpreis=_runden(preis), steuersatz=lauf.fall.steuersatz)
        elif k['art'] == 'fremd':
            # Fremdleistung als Position nach Schätzung (README). "LE" als
            # pauschal, weil die Einheit der Fremdleistung zur
            # Auftragsposition passen muss.
            aufschlag = 1 + betrag(k.get('aufschlag_prozent', '0')) / HUNDERT
            formular.zeile('positionen', index, zeilenart='leistung',
                           position=nummer, bezeichnung=k['bezeichnung'],
                           langtext=k.get('hinweis', ''),
                           menge=k['menge'], einheit=PAUSCHAL,
                           einzelpreis=_runden(
                               betrag(k['einkauf_geschaetzt']) * aufschlag),
                           steuersatz=lauf.fall.steuersatz)
        else:
            formular.zeile('positionen', index, zeilenart='leistung',
                           position=nummer, bezeichnung=k['bezeichnung'],
                           menge=(mengen or {}).get(kennung, k.get('geschaetzt', '0')),
                           einheit=STUNDE,
                           einzelpreis=k['preis'], steuersatz=lauf.fall.steuersatz)
    for zuschlag in zuschlaege:
        index = formular.freie_zeile('positionen')
        formular.zeile('positionen', index, zeilenart='zuschlag',
                       position='900', bezeichnung=zuschlag['bezeichnung'],
                       zuschlag_prozent=zuschlag['prozent'], zuschlag_auf='',
                       steuersatz=lauf.fall.steuersatz)


def _beleg_anlegen(lauf: Lauf, admin_name: str, schritt: dict, *,
                   kunde: Kontakt | None = None, felder=None,
                   positionen=None) -> Beleg:
    """Legt einen Beleg über die Maske "Hinzufügen" an."""
    formular = maske.oeffnen(lauf.client, reverse(f'admin:faktura_{admin_name}_add'))
    # Projekt oder Kunde, nicht beides; der Kunde kommt aus dem Projekt.
    # Ein anderer Empfänger steht im Empfängerfeld.
    formular.setzen('projekt', lauf.projekt.pk)
    if kunde is not None and kunde != lauf.projekt.kunde:
        _empfaenger_setzen(formular, kunde)
    formular.setzen('betreff', f'{lauf.fall.titel[:60]} ({schritt["nr"]})')
    formular.setzen('belegdatum', f'{schritt["datum"]:%d.%m.%Y}')
    for name, wert in (felder or {}).items():
        formular.setzen(name, wert)
    if positionen:
        positionen(formular)
    vorher = set(Beleg.objects.values_list('pk', flat=True))
    formular.absenden('_continue')
    neu = Beleg.objects.exclude(pk__in=vorher).get()
    return neu


def _empfaenger_setzen(formular, kunde: Kontakt) -> None:
    """Empfängerfeld und Anschrift der E-Rechnung auf ``kunde``."""
    werte = services.stammdatenwerte(kunde)
    for name in ('empfaenger', 'empfaenger_name', 'empfaenger_strasse',
                 'empfaenger_plz', 'empfaenger_ort', 'empfaenger_land'):
        if name in werte and name in formular:
            formular.setzen(name, getattr(werte[name], 'pk', werte[name]))


def _versenden(lauf: Lauf, beleg: Beleg, *, mehrmenge: bool = False) -> Beleg:
    """"Versenden", Knopf ohne E-Mail: schreibt fest. ``mehrmenge``: Die
    Überschreitung der beauftragten Menge ist Teil des Falls und wird ohne
    Befund bestätigt."""
    formular = maske.oeffnen(lauf.client, _url(beleg, 'versenden'))
    knopf = next((n for n, _, t in formular.knoepfe
                  if n and n not in ('senden', 'herunterladen')), None)
    if knopf is None:
        knopf = 'herunterladen'
    try:
        formular.absenden(knopf)
    except maske.MaskeAbgelehnt as abgelehnt:
        # Mehr als beauftragt: die Maske verlangt eine Bestätigung. Der
        # Fall rechnet die Menge ab; die Überschreitung wird gemeldet.
        wieder = maske.oeffnen(lauf.client, _url(beleg, 'versenden'))
        if 'mengen_bestaetigt' not in maske.oeffnen_html(abgelehnt):
            raise
        if not mehrmenge:
            lauf.luecken.append(f'{beleg}: Überschreitung der beauftragten '
                                f'Menge bestätigt ({abgelehnt})')
        wieder.werte['mengen_bestaetigt'] = ['on']
        wieder.absenden(knopf)
    beleg.refresh_from_db()
    if beleg.status != BelegStatus.FESTGESCHRIEBEN:
        raise maske.MaskeAbgelehnt(f'{beleg}: nach Versenden {beleg.status}')
    return beleg


def _festschreiben(lauf: Lauf, beleg: Beleg) -> Beleg:
    formular = maske.oeffnen(lauf.client, _url(beleg, 'festschreiben'))
    formular.absenden()
    beleg.refresh_from_db()
    if beleg.status != BelegStatus.FESTGESCHRIEBEN:
        raise maske.MaskeAbgelehnt(f'{beleg}: nach Festschreiben {beleg.status}')
    return beleg


def _detailaktion(lauf: Lauf, beleg: Beleg, aktion: str) -> Beleg | None:
    """Detailaktion mit Dialog (Unfold): POST mit ``_form_submitted``.
    Gibt den Beleg zurück, auf den die Antwort leitet."""
    antwort = lauf.client.post(_url(beleg, aktion), {'_form_submitted': 'on'})
    fehler = [m for s, m in maske.meldungen_aus(antwort) if s == 'error']
    if fehler or antwort.status_code not in (200, 302):
        raise maske.MaskeAbgelehnt(f'{aktion} an {beleg}: {fehler or antwort.status_code}')
    ziel = antwort.get('Location') or antwort.headers.get('HX-Redirect', '')
    teile = [t for t in ziel.split('/') if t.isdigit()]
    return Beleg.objects.filter(pk=teile[-1]).first() if teile else None


def _auftragspositionen_merken(lauf: Lauf, auftrag: Beleg) -> None:
    namen = {k['bezeichnung']: kennung for kennung, k in lauf.katalog.items()}
    for p in auftrag.positionen.all():
        if p.bezeichnung in namen:
            lauf.auftragspositionen[namen[p.bezeichnung]] = p.pk


def _erfassen(lauf: Lauf, kennung: str, tag: date, *, menge=None,
              stunden=None) -> None:
    """Erfassungszeile(n) über die Erfassungsmaske. Stunden in Blöcken zu
    höchstens acht Stunden an aufeinanderfolgenden Tagen bis ``tag``."""
    if (kennung not in lauf.auftragspositionen
            and kennung not in lauf.katalogpositionen):
        raise Luecke(f'{kennung}: weder Auftrags- noch Katalogposition')
    if stunden is not None:
        lauf.stunden[kennung] = lauf.stunden.get(kennung, Decimal('0')) + Decimal(stunden)
        rest = Decimal(stunden)
        bloecke = []
        while rest > 0:
            bloecke.append(min(rest, Decimal('8')))
            rest -= bloecke[-1]
        tage = [tag - timedelta(days=i) for i in range(len(bloecke))][::-1]
        for t, dauer in zip(tage, bloecke, strict=True):
            minuten = int(dauer * 60)
            bis = 7 * 60 + minuten
            _erfassungszeile(lauf, kennung, t, von='07:00',
                             bis=f'{bis // 60:02d}:{bis % 60:02d}')
    else:
        _erfassungszeile(lauf, kennung, tag, menge=menge)


def _erfassungszeile(lauf: Lauf, kennung: str, tag: date, **werte) -> None:
    lauf.letzte_leistung = max(filter(None, [lauf.letzte_leistung, tag]))
    formular = maske.oeffnen(lauf.client, reverse('admin:erfassung_erfassungszeile_add'))
    formular.setzen('datum', f'{tag:%d.%m.%Y}')
    formular.setzen('projekt', lauf.projekt.pk)
    if kennung in lauf.auftragspositionen:
        formular.setzen('auftragsposition', lauf.auftragspositionen[kennung])
    else:
        formular.setzen('leistung', lauf.katalogpositionen[kennung])
    if 'benutzer' in formular:
        formular.setzen('benutzer', lauf.client.benutzer.pk)
    formular.setzen('beschreibung', f'{kennung} {tag:%d.%m.%Y}')
    for name, wert in werte.items():
        formular.setzen(name, wert)
    vorher = set(Erfassungszeile.objects.values_list('pk', flat=True))
    formular.absenden('_save')
    for pk in Erfassungszeile.objects.exclude(pk__in=vorher).values_list('pk', flat=True):
        lauf.offene_zeilen[pk] = kennung


def _leistungen_hinzufuegen(lauf: Lauf, beleg: Beleg, kennungen=None) -> None:
    """"Erbrachte Leistungen hinzufügen" mit den offenen Zeilen und
    Fremdleistungen dieses Laufs, auf ``kennungen`` beschränkt.

    Eine nicht angebotene Fremdleistung ist eine Lücke, nach der der Fall
    weiterläuft; eine nicht angebotene Erfassungszeile bricht ab.
    """
    def gewaehlt(offen):
        return [pk for pk, k in offen.items()
                if kennungen is None or k in kennungen]

    zeilen, fremde = gewaehlt(lauf.offene_zeilen), gewaehlt(lauf.offene_fremd)
    if not zeilen and not fremde:
        return
    formular = maske.oeffnen(lauf.client, _url(beleg, 'leistungen'))
    angeboten = {w for w, _ in formular.optionen('zeile')}
    fehlend = {str(z) for z in zeilen} - angeboten
    if fehlend:
        raise Luecke(f'Zeilen {sorted(fehlend)} nicht zur Übernahme angeboten')
    angeboten_fremd = {w for w, _ in formular.optionen('fremdleistung')}
    for pk in [f for f in fremde if str(f) not in angeboten_fremd]:
        lauf.luecken.append(
            f'Fremdleistung {lauf.offene_fremd[pk]} an '
            f'{beleg.get_rechnungsart_display() or beleg} nicht übernehmbar '
            f'(keine Auftragsposition)')
        fremde.remove(pk)
    if not zeilen and not fremde:
        return
    if zeilen:
        formular.setzen('zeile', [str(z) for z in zeilen])
    if fremde:
        formular.setzen('fremdleistung', [str(f) for f in fremde])
    formular.absenden()
    for pk in zeilen:
        lauf.offene_zeilen.pop(pk)
    for pk in fremde:
        _aufschlag_setzen(lauf, beleg, lauf.offene_fremd.pop(pk))


def _aufschlag_setzen(lauf: Lauf, beleg: Beleg, kennung: str) -> None:
    """Aufschlag auf eine übernommene Fremdleistung als Zuschlagszeile auf
    deren Positionsnummer."""
    eintrag = lauf.katalog[kennung]
    prozent = eintrag.get('aufschlag_prozent')
    # Mit Auftragsposition gilt deren Preis, der den Aufschlag enthält.
    if not prozent or kennung in lauf.auftragspositionen:
        return
    position = beleg.positionen.filter(bezeichnung=eintrag['bezeichnung']).last()
    if position is None:
        raise Luecke(f'{kennung}: Position nach Übernahme nicht gefunden')
    formular = maske.oeffnen(lauf.client, _url(beleg))
    index = formular.freie_zeile('positionen')
    formular.zeile('positionen', index, zeilenart='zuschlag',
                   position=f'{position.position}1',
                   bezeichnung=f'Aufschlag {eintrag["bezeichnung"]}',
                   zuschlag_prozent=prozent, zuschlag_auf=position.position,
                   steuersatz=lauf.fall.steuersatz)
    formular.absenden('_continue')


def _leistungsstand_erfassen(lauf: Lauf, stand: dict, tag: date) -> None:
    """Erfasst den Zuwachs gegenüber dem bisher abgerechneten Stand."""
    for kennung, ziel in stand.items():
        ziel = betrag(ziel)
        zuwachs = ziel - lauf.stand.get(kennung, Decimal('0'))
        if zuwachs < 0:
            raise Luecke(f'{kennung}: Leistungsstand sinkt von '
                         f'{lauf.stand[kennung]} auf {ziel}')
        if zuwachs:
            _erfassen(lauf, kennung, tag, menge=(zuwachs * HUNDERT).normalize())
            lauf.stand[kennung] = ziel


def _stunden_erfassen(lauf: Lauf, stunden: dict, tag: date) -> None:
    for kennung, anzahl in stunden.items():
        _erfassen(lauf, kennung, tag, stunden=betrag(anzahl))


def _inhalt(lauf: Lauf, schritt: dict):
    """Kennungen aus ``inhalt``, sonst alle offenen."""
    return set(schritt['inhalt']) if 'inhalt' in schritt else None


# --- Aktionen ----------------------------------------------------------------

def angebot(lauf: Lauf, schritt: dict, name: str = 'angebot') -> Beleg:
    """Angebot mit den Leistungen des Schritts oder, beim Nachtrag nach
    Aufwand, den geschätzten Stunden (``stunden_geschaetzt``)."""
    kunde = lauf.kunden.get(schritt.get('kunde', ''))
    geschaetzt = schritt.get('stunden_geschaetzt', {})
    kennungen = schritt.get('leistungen') or list(geschaetzt)
    if 'obergrenze' in schritt:
        # Kein Feld im Beleg; die Schlussrechnung kappt von Hand
        # (``_obergrenze_kappen``).
        lauf.obergrenze = betrag(schritt['obergrenze'])
    beleg = _beleg_anlegen(
        lauf, 'angebot', schritt, kunde=kunde,
        positionen=lambda f: _positionszeilen(
            f, kennungen, lauf, lauf.fall.liste('zuschlag'), mengen=geschaetzt))
    beleg = _versenden(lauf, beleg)
    lauf.belege[name] = beleg.pk
    return beleg


def auftrag(lauf: Lauf, schritt: dict) -> Beleg:
    quelle = lauf.beleg(schritt.get('aus', 'angebot'))
    neu = _detailaktion(lauf, quelle, 'in-auftrag')
    if neu is None or neu.typ != BelegTyp.AUFTRAG:
        raise maske.MaskeAbgelehnt('Auftrag erzeugen: kein Auftrag')
    neu = _festschreiben(lauf, neu)
    lauf.belege['auftrag'] = neu.pk
    _auftragspositionen_merken(lauf, neu)
    return neu


def nachtragsangebot(lauf: Lauf, schritt: dict) -> Beleg:
    """Angebot über den Nachtrag; beauftragt wird er mit
    ``nachtrag_beauftragen``."""
    return angebot(lauf, schritt, name=f'{schritt["name"]}-angebot')


def nachtrag_beauftragen(lauf: Lauf, schritt: dict) -> Beleg:
    """Auftrag aus dem Nachtragsangebot, in der Maske als Nachtrag zum
    Hauptauftrag gesetzt, dann festgeschrieben."""
    name = schritt['nachtrag']
    neu = _detailaktion(lauf, lauf.beleg(f'{name}-angebot'), 'in-auftrag')
    if neu is None or neu.typ != BelegTyp.AUFTRAG:
        raise maske.MaskeAbgelehnt('Auftrag erzeugen: kein Auftrag')
    formular = maske.oeffnen(lauf.client, _url(neu))
    formular.setzen('nachtrag_zu', lauf.belege['auftrag'])
    formular.absenden('_continue')
    neu = _festschreiben(lauf, neu)
    lauf.belege[name] = neu.pk
    _auftragspositionen_merken(lauf, neu)
    return neu


def folgeauftrag(lauf: Lauf, schritt: dict) -> Beleg:
    """Neuer Auftrag im selben Projekt aus dem Folgeangebot, für Leistung
    nach der Schlussrechnung des bisherigen Auftrags. Er wird der Auftrag
    der folgenden Schritte und bekommt eine eigene Gesamtabnahme; der
    bisherige bleibt unter ``auftrag-<Name>-vorher``."""
    name = schritt['folgeauftrag']
    neu = _detailaktion(lauf, lauf.beleg(f'{name}-angebot'), 'in-auftrag')
    if neu is None or neu.typ != BelegTyp.AUFTRAG:
        raise maske.MaskeAbgelehnt('Auftrag erzeugen: kein Auftrag')
    vorher = lauf.beleg('auftrag')
    formular = maske.oeffnen(lauf.client, _url(neu))
    formular.setzen('kopftext', f'Folgeauftrag zu {vorher.nummer} vom '
                                f'{vorher.belegdatum:%d.%m.%Y}.')
    formular.absenden('_continue')
    neu = _festschreiben(lauf, neu)
    lauf.belege[f'auftrag-{name}-vorher'] = vorher.pk
    lauf.belege['auftrag'] = lauf.belege[name] = neu.pk
    if 'abnahme' in lauf.belege:
        lauf.belege[f'abnahme-{name}-vorher'] = lauf.belege.pop('abnahme')
    _auftragspositionen_merken(lauf, neu)
    return neu


def abschlag(lauf: Lauf, schritt: dict) -> Beleg:
    tag = schritt['datum']
    _leistungsstand_erfassen(lauf, schritt.get('leistungsstand', {}), tag)
    _stunden_erfassen(lauf, schritt.get('stunden', {}), tag)
    beginn = lauf.beleg('auftrag').belegdatum
    beleg = _beleg_anlegen(lauf, 'abschlagsrechnung', schritt, felder={
        'leistungsdatum': f'{beginn:%d.%m.%Y}',
        'leistungsdatum_bis': f'{tag:%d.%m.%Y}',
    })
    _leistungen_hinzufuegen(lauf, beleg, _inhalt(lauf, schritt))
    _nach_nachweis(lauf, beleg)
    for name in schritt.get('rest_aus', []):
        # Paper-Werk fordert den gekürzten Teil mit der Schlussrechnung
        # (ist_abschlagsrest). Eine Handposition im Abschlag verfälschte den
        # Leistungsstand und bekäme den Zuschlag ein zweites Mal.
        lauf.luecken.append(
            f'{schritt["name"]} soll den gekürzten Teil aus {name} '
            f'({lauf.strittig.get(name)}) mitfordern; Paper-Werk fordert '
            f'ihn erst mit der Schlussrechnung')
    beleg = _versenden(lauf, beleg)
    lauf.belege[schritt['name']] = beleg.pk
    return beleg


def zahlung(lauf: Lauf, schritt: dict) -> None:
    """Zahlung vermerken an der Rechnung. Übersteigt der Betrag den offenen
    Betrag oder zahlt ein anderer Kunde, über "Zahlungseingänge": Zuordnung
    bis zum offenen Betrag, der Rest bleibt unverteilt (Lücke)."""
    if not _ausfuehren(lauf, schritt):
        return
    beleg = lauf.beleg(schritt['rechnung'])
    wert = lauf.wert(schritt.get('betrag', 'voll'))
    if wert != 'voll' and betrag(wert) > services.offener_betrag(beleg):
        _einbehalt_freigeben(lauf, beleg, betrag(wert), schritt)
    offen = services.offener_betrag(beleg)
    einbehalten = _maengeleinbehalt(lauf, beleg) if wert == 'voll' else None
    if einbehalten:
        wert = str(offen - einbehalten)
    skonto = lauf.wert(schritt.get('skonto', schritt.get('skonto_beansprucht', '0.00')))
    if isinstance(skonto, str) and skonto.endswith('%'):
        skonto = _runden(offen * betrag(skonto.rstrip(' %')) / HUNDERT)
    skonto = betrag(skonto)
    if wert == 'voll abzüglich Skonto':
        wert = str(offen - skonto)
    zahler = lauf.kunden.get(schritt.get('zahler', ''))
    vorher = set(Zahlungszuordnung.objects.values_list('pk', flat=True))
    if wert != 'voll' and (betrag(wert) + skonto > offen
                           or (zahler and zahler != _kunde_von(beleg))):
        _zahlungseingang(lauf, schritt, beleg, betrag(wert), skonto, offen, zahler)
    else:
        _zahlung_vermerken(lauf, schritt, beleg, wert, skonto, einbehalten)
        if not Zahlungszuordnung.objects.exclude(pk__in=vorher).exists():
            raise maske.MaskeAbgelehnt(f'Zahlung auf {beleg} nicht verbucht')
    neu = Zahlungszuordnung.objects.exclude(pk__in=vorher)
    lauf.zahlungen.extend(neu.values_list('pk', flat=True))


def _name_von(lauf: Lauf, beleg: Beleg) -> str:
    return next((n for n, pk in lauf.belege.items() if pk == beleg.pk), str(beleg.pk))


def _kunde_von(beleg: Beleg) -> Kontakt:
    """Kunde der Rechnung; bei Projektbelegen der des Projekts."""
    return beleg.kunde or beleg.projekt.kunde


def _maengeleinbehalt(lauf, beleg) -> Decimal | None:
    """Mängeleinbehalt des Kunden auf die Schlussrechnung, Prozent vom
    Brutto aus ``[einbehalt] maengel_prozent``."""
    prozent = lauf.fall.daten.get('einbehalt', {}).get('maengel_prozent')
    if not prozent or beleg.rechnungsart != Rechnungsart.SCHLUSS:
        return None
    return _runden(services.leistungssummen(beleg).brutto * betrag(prozent)
                   / HUNDERT)


def _einbehalt_freigeben(lauf, beleg, summe, schritt) -> None:
    """Auszahlung eines Einbehalts: Einbehalten an der früheren Zahlung auf
    0 mit Notiz (Hilfe, „Einbehalt auf die Schlussrechnung“)."""
    for alt in Zahlungszuordnung.objects.filter(beleg=beleg, einbehalten__gt=0):
        formular = maske.oeffnen(lauf.client, reverse(
            'admin:faktura_zahlung_change', args=[alt.zahlung_id]))
        index = next(i for i in range(formular.zeilen('zuordnungen'))
                     if formular.wert(f'zuordnungen-{i}-id') == str(alt.pk))
        frei = min(alt.einbehalten, summe)
        formular.setzen(f'zuordnungen-{index}-einbehalten', alt.einbehalten - frei)
        formular.setzen(f'zuordnungen-{index}-notiz',
                        f'Einbehalt {frei} ausgezahlt am {schritt["datum"]:%d.%m.%Y}')
        formular.absenden('_save')


def _zahlung_vermerken(lauf, schritt, beleg, wert, skonto, einbehalten=None) -> None:
    formular = maske.oeffnen(lauf.client, _url(beleg, 'zahlung'), enthaelt='betrag')
    formular.setzen('datum', f'{schritt["datum"]:%d.%m.%Y}')
    if wert != 'voll':
        formular.setzen('betrag', betrag(wert))
    formular.setzen('skonto', skonto)
    if einbehalten:
        formular.setzen('einbehalten', einbehalten)
    if 'strittig' in schritt:
        if 'kuerzung' not in formular:
            raise Luecke(f'{beleg}: Zahlung ohne Feld Gekürzt')
        formular.setzen('kuerzung', betrag(schritt['strittig']))
        lauf.strittig[schritt['rechnung']] = betrag(schritt['strittig'])
    antwort = formular.absenden('anwenden', erwartet_weiterleitung=False)
    fehler = [m for s, m in antwort.meldungen if s == 'error']
    if fehler or antwort.status_code == 200 and maske.formularfehler(antwort):
        raise maske.MaskeAbgelehnt(
            f'Zahlung auf {beleg}: {fehler or maske.formularfehler(antwort)}')


def _zahlungseingang(lauf, schritt, beleg, summe, skonto, offen, zahler) -> None:
    formular = maske.oeffnen(lauf.client, reverse('admin:faktura_zahlung_add'))
    formular.setzen('datum', f'{schritt["datum"]:%d.%m.%Y}')
    formular.setzen('betrag', summe)
    formular.setzen('kunde', (zahler or _kunde_von(beleg)).pk)
    formular.setzen('verwendungszweck', beleg.nummer)
    zugeordnet = min(summe, offen - skonto) if offen > skonto else Decimal('0.00')
    if zugeordnet > 0:
        formular.zeile('zuordnungen', 0, beleg=beleg.pk, betrag=zugeordnet,
                       skonto=skonto)
    vorher = set(Zahlung.objects.values_list('pk', flat=True))
    formular.absenden('_save')
    rest = summe - zugeordnet
    if rest:
        zahlung = Zahlung.objects.exclude(pk__in=vorher).get()
        rest -= _kuerzung_zuruecknehmen(lauf, zahlung, rest, schritt)
    if rest:
        lauf.luecken.append(
            f'Zahlung {summe} auf {schritt["rechnung"]} mit {offen} offen: '
            f'{rest} ohne offene Rechnung, unverteilt')


def _kuerzung_zuruecknehmen(lauf, zahlung, rest, schritt) -> Decimal:
    """Der Rest ist der nachgezahlte gekürzte Teil: Kürzung an der
    früheren Zahlung auf 0 mit Notiz, Rest dem Abschlag zuordnen (Hilfe,
    „Kürzung zurücknehmen“). Gibt den zugeordneten Betrag zurück."""
    zugeordnet = Decimal('0.00')
    for alt in services.gekuerzte_abschlaege(zahlung):
        betrag_ = min(alt.kuerzung, rest - zugeordnet)
        if betrag_ <= 0:
            break
        formular = maske.oeffnen(lauf.client, reverse(
            'admin:faktura_zahlung_change', args=[alt.zahlung_id]))
        index = next(i for i in range(formular.zeilen('zuordnungen'))
                     if formular.wert(f'zuordnungen-{i}-id') == str(alt.pk))
        formular.setzen(f'zuordnungen-{index}-kuerzung', alt.kuerzung - betrag_)
        formular.setzen(f'zuordnungen-{index}-notiz',
                        f'Kürzung {betrag_} zurückgenommen, bezahlt mit '
                        f'Zahlung vom {schritt["datum"]:%d.%m.%Y}')
        formular.absenden('_save')
        formular = maske.oeffnen(lauf.client, reverse(
            'admin:faktura_zahlung_change', args=[zahlung.pk]))
        index = formular.freie_zeile('zuordnungen')
        formular.zeile('zuordnungen', index, beleg=alt.beleg_id, betrag=betrag_)
        formular.absenden('_save')
        zugeordnet += betrag_
    return zugeordnet


def _ausfuehren(lauf: Lauf, schritt: dict) -> bool:
    """``nur_in = "R2.A"``: Schritt nur, solange die Variante möglich ist;
    ausgeführt legt er sie fest."""
    nur = schritt.get('nur_in')
    if not nur:
        return True
    frage, variante = nur.split('.')
    if not lauf.bindung.erlaubt(frage, variante):
        return False
    lauf.bindung.einschraenken(frage, {variante})
    return True


def abnahme(lauf: Lauf, schritt: dict) -> Abnahme:
    """Gesamtabnahme über die Maske. ``stunden_gesamt`` erfasst vorher
    die Stunden, die bis zum Gesamtstand fehlen."""
    for kennung, gesamt in schritt.get('stunden_gesamt', {}).items():
        fehlend = betrag(gesamt) - lauf.stunden.get(kennung, Decimal('0'))
        if fehlend > 0:
            _erfassen(lauf, kennung, schritt['datum'], stunden=fehlend)
    auftrag = lauf.beleg('auftrag')
    formular = maske.oeffnen(
        lauf.client, reverse('admin:faktura_abnahme_add') + f'?auftrag={auftrag.pk}')
    formular.setzen('auftrag', auftrag.pk)
    formular.setzen('art', formular.option_mit_text('art', 'Gesamt'))
    formular.setzen('abgenommen_am', f'{schritt["datum"]:%d.%m.%Y}')
    if 'bezeichnung' in formular:
        formular.setzen('bezeichnung', 'Gesamtabnahme')
    vorher = set(Abnahme.objects.values_list('pk', flat=True))
    formular.absenden('_continue')
    neu = Abnahme.objects.exclude(pk__in=vorher).get()
    lauf.belege['abnahme'] = neu.pk
    return neu


def schlussrechnung(lauf: Lauf, schritt: dict) -> Beleg:
    """Rest der Leistung erfassen, Abnahme (falls nicht schon Schritt),
    Rechnung aus der Abnahme, fehlende Leistung hinzufügen, Abschläge
    absetzen, versenden."""
    tag = schritt['datum']
    voll = {k: '1' for k, e in lauf.katalog.items()
            if e['art'] == 'leistung' and k in lauf.auftragspositionen}
    _leistungsstand_erfassen(lauf, voll, tag)
    _stunden_erfassen(lauf, schritt.get('stunden', {}), tag)
    vorhanden = Abnahme.objects.filter(pk=lauf.belege.get('abnahme')).first()
    if vorhanden is None:
        abnahme(lauf, schritt)
    maengel = lauf.fall.daten.get('einbehalt', {}).get('maengel_prozent')
    if maengel:
        lauf.luecken.append(f'Mängeleinbehalt {maengel} % steht nicht auf '
                            f'der Schlussrechnung; erfasst mit der Zahlung '
                            f'(Einbehalten)')
    abgerechnet = Beleg.objects.filter(
        abnahme_id=lauf.belege['abnahme'],
        status=BelegStatus.FESTGESCHRIEBEN).order_by('pk').last()
    if abgerechnet is not None:
        # Je Auftrag eine Gesamtabnahme (Constraint
        # abnahme_eine_gesamtabnahme_je_auftrag). Weitere Leistung kommt über
        # "Stornieren und neu schreiben" der Schlussrechnung in eine neue
        # Gesamtschlussrechnung.
        geloest = _zuordnungen_loesen(lauf, abgerechnet)
        _detailaktion(lauf, abgerechnet, 'korrigieren')
        lauf.belege[f'Storno-{_name_von(lauf, abgerechnet)}'] = Beleg.objects.filter(
            vorgaenger=abgerechnet, typ=BelegTyp.STORNO).latest('pk').pk
    else:
        antwort = lauf.client.post(reverse('admin:faktura_abnahme_detail_rechnung',
                                           args=[lauf.belege['abnahme']]))
        fehler = [m for s, m in maske.meldungen_aus(antwort) if s == 'error']
        if fehler:
            raise Luecke(f'Rechnung aus Abnahme: {fehler}')
    beleg = Beleg.objects.filter(abnahme_id=lauf.belege['abnahme'],
                                 status=BelegStatus.ENTWURF).latest('pk')
    _leistungen_hinzufuegen(lauf, beleg, _inhalt(lauf, schritt))
    _nach_nachweis(lauf, beleg)
    gekappt = _obergrenze_kappen(lauf, beleg)
    lauf.client.post(_url(beleg, 'abschlaege'))
    beleg = _versenden(lauf, beleg,
                       mehrmenge=gekappt or _ueber_schaetzung(lauf))
    lauf.belege[schritt['name']] = beleg.pk
    if abgerechnet is not None:
        # Dieselbe Schuld beim selben Kunden: Zahlungen auf die stornierte
        # Schlussrechnung werden angerechnet.
        _zuordnungen_anlegen(lauf, geloest, beleg)
    return beleg


def _ueber_schaetzung(lauf: Lauf) -> bool:
    """Mehr Stunden erfasst als im Angebot geschätzt; der Fall zeigt die
    Überschreitung an, die Bestätigung beim Versenden ist kein Befund."""
    return any(lauf.stunden.get(kennung, 0) > betrag(k['geschaetzt'])
               for kennung, k in lauf.katalog.items()
               if k['art'] == 'stunde' and 'geschaetzt' in k)


def _nach_nachweis(lauf: Lauf, beleg: Beleg) -> None:
    """Preis einer Position nach Nachweis von Hand auf Einkauf mal
    (1 + Aufschlag), wie in der Hilfe beschrieben (B7). Grundlage ist das
    Netto der Eingangsrechnung (R1.A in Fall 03); Paper-Werk kennt keinen
    eigenen Skonto auf den Einkauf."""
    for kennung, k in lauf.katalog.items():
        if (k['art'] != 'fremd' or 'einkauf_geschaetzt' not in k
                or kennung not in lauf.einkauf):
            continue
        aufschlag = 1 + betrag(k.get('aufschlag_prozent', '0')) / HUNDERT
        preis = _runden(lauf.einkauf[kennung] * aufschlag)
        position = beleg.positionen.filter(
            bezeichnung=k['bezeichnung'], ist_abzug=False).first()
        if position is None or position.einzelpreis == preis:
            continue
        formular = maske.oeffnen(lauf.client, _url(beleg))
        index = next((i for i in range(formular.zeilen('positionen'))
                      if formular.wert(f'positionen-{i}-id') == str(position.pk)),
                     None)
        if index is None:
            raise Luecke(f'{kennung}: Position nicht in der Maske')
        formular.zeile('positionen', index, einzelpreis=preis)
        formular.absenden('_continue')
        position.refresh_from_db()
        if position.einzelpreis != preis:
            raise Luecke(f'{kennung}: Preis nach Nachweis ({preis}) in '
                         f'{beleg} nicht änderbar')


def _obergrenze_kappen(lauf: Lauf, beleg: Beleg) -> bool:
    """Liegt das Zeithonorar über der Obergrenze, eine Position mit
    negativem Preis über die Differenz, wie in der Hilfe beschrieben. Die
    Zuschläge rechnen auf den gekappten Betrag, weil die Position eine
    Leistung ist."""
    if lauf.obergrenze is None:
        return False
    stunden = sum((p.menge * p.einzelpreis for p in beleg.positionen.filter(
        einheit=STUNDE, ist_abzug=False)), Decimal('0'))
    ueber = _runden(stunden - lauf.obergrenze)
    if ueber <= 0:
        return False
    formular = maske.oeffnen(lauf.client, _url(beleg))
    index = formular.freie_zeile('positionen')
    formular.zeile('positionen', index, zeilenart='leistung', position='890',
                   bezeichnung=KAPPUNG, menge='1', einheit='LS',
                   einzelpreis=-ueber, steuersatz=lauf.fall.steuersatz)
    formular.absenden('_continue')
    if not beleg.positionen.filter(bezeichnung=KAPPUNG).exists():
        raise Luecke(f'{KAPPUNG}: Position mit negativem Preis abgelehnt')
    return True


def stunden_erfassen(lauf: Lauf, schritt: dict) -> None:
    _stunden_erfassen(lauf, schritt['stunden'], schritt['datum'])


def fremdleistung_erfassen(lauf: Lauf, schritt: dict) -> None:
    """Eingangsrechnung mit einer Fremdleistung auf das Projekt, zum
    Nettobetrag der Rechnung, auf die Auftragsposition der Kennung, falls
    der Auftrag eine hat."""
    kennung = schritt['fremdleistung']
    eintrag = lauf.katalog[kennung]
    netto = betrag(schritt['einkauf_netto'])
    formular = maske.oeffnen(lauf.client,
                             reverse('admin:erfassung_eingangsrechnung_add'))
    formular.setzen('lieferant', lauf.lieferant.pk)
    formular.setzen('nummer', f'ER-{lauf.fall.nummer}-{schritt["nr"]}')
    formular.setzen('datum', f'{schritt["datum"]:%d.%m.%Y}')
    formular.setzen('betrag_netto', netto)
    prefix = _inline_prefix(formular, 'einkaufspreis')
    formular.zeile(prefix, 0, projekt=lauf.projekt.pk,
                   bezeichnung=eintrag['bezeichnung'],
                   leistungsdatum=f'{schritt["datum"]:%d.%m.%Y}',
                   einheit=PAUSCHAL, menge='1', einkaufspreis=netto,
                   weiterberechenbar=True,
                   auftragsposition=lauf.auftragspositionen.get(kennung, ''))
    if f'{prefix}-0-einkauf_netto' in formular:
        formular.setzen(f'{prefix}-0-einkauf_netto', netto)
    vorher = set(Fremdleistung.objects.values_list('pk', flat=True))
    formular.absenden('_save')
    for pk in Fremdleistung.objects.exclude(pk__in=vorher).values_list('pk', flat=True):
        lauf.offene_fremd[pk] = kennung
    lauf.einkauf[kennung] = netto


def _inline_prefix(formular, feld: str) -> str:
    """Prefix der Inline-Zeilen, die ``feld`` enthalten."""
    for name in formular._form.bekannt:
        if name.endswith(f'-__prefix__-{feld}'):
            return name.split('-__prefix__-')[0]
    raise maske.FeldFehlt(f'Keine Inline mit {feld}')


def rechnung(lauf: Lauf, schritt: dict) -> Beleg:
    """Gewöhnliche Rechnung über erfasste Leistung, Zeitraum vom Auftrag
    bis zur letzten Erfassung. Ein anderer Kunde als der des Projekts steht
    nur im Empfängerfeld; die offenen Posten führen die Rechnung beim
    Projektkunden."""
    tag = schritt['datum']
    inhalt = _inhalt(lauf, schritt) or set()
    # Ende des Zeitraums vor der Erfassung des Leistungsstands, die am
    # Rechnungstag geschieht und keinen Leistungstag darstellt.
    ende = lauf.letzte_leistung or tag
    _leistungsstand_erfassen(
        lauf, {k: '1' for k in inhalt if lauf.katalog[k]['art'] == 'leistung'}, tag)
    kunde = lauf.kunden.get(schritt.get('kunde', ''))
    beginn = lauf.beleg('auftrag').belegdatum
    beleg = _beleg_anlegen(lauf, 'rechnung', schritt, kunde=kunde, felder={
        'leistungsdatum': f'{beginn:%d.%m.%Y}',
        'leistungsdatum_bis': f'{ende:%d.%m.%Y}',
    })
    _leistungen_hinzufuegen(lauf, beleg, inhalt)
    beleg = _versenden(lauf, beleg)
    lauf.belege[schritt['name']] = beleg.pk
    return beleg


def storno_und_neufassung(lauf: Lauf, schritt: dict) -> Beleg:
    """"Stornieren und neu schreiben" an der Rechnung. Vorher die
    Zuordnungen der Zahlungen lösen (Maske der Zahlung), weil eine Rechnung
    mit zugeordneter Zahlung nicht storniert wird. In der Neufassung den
    Empfänger auf den Kunden setzen, weitere Leistung hinzufügen,
    versenden; mit ``zahlung_umbuchen`` danach die Zahlungen der
    Neufassung zuordnen, sonst bleiben sie als Rest stehen (erstattet)."""
    alt = lauf.beleg(schritt['rechnung'])
    geloest = _zuordnungen_loesen(lauf, alt)
    _detailaktion(lauf, alt, 'korrigieren')
    neu = Beleg.objects.filter(vorgaenger=alt, typ=BelegTyp.RECHNUNG,
                               status=BelegStatus.ENTWURF).latest('pk')
    storno = Beleg.objects.filter(vorgaenger=alt, typ=BelegTyp.STORNO).latest('pk')
    lauf.belege[f'Storno-{schritt["rechnung"]}'] = storno.pk
    kunde = lauf.kunden.get(schritt.get('kunde', ''))
    if kunde is not None:
        formular = maske.oeffnen(lauf.client, _url(neu))
        _empfaenger_setzen(formular, kunde)
        formular.absenden('_continue')
    _leistungen_hinzufuegen(lauf, neu, _inhalt(lauf, schritt))
    neu = _versenden(lauf, neu)
    lauf.belege[schritt['neu']] = neu.pk
    if 'zahlung_umbuchen' in schritt:
        _zuordnungen_anlegen(lauf, geloest, neu)
    return neu


def _zuordnungen_loesen(lauf: Lauf, beleg: Beleg) -> list[dict]:
    """Löscht in der Maske jeder Zahlung die Zeile auf ``beleg``. Gibt
    Zahlung, Betrag und Skonto der gelösten Zeilen zurück."""
    geloest = []
    for zuordnung in Zahlungszuordnung.objects.filter(beleg=beleg).order_by('pk'):
        formular = maske.oeffnen(lauf.client, reverse(
            'admin:faktura_zahlung_change', args=[zuordnung.zahlung_id]))
        index = next((i for i in range(formular.zeilen('zuordnungen'))
                      if formular.wert(f'zuordnungen-{i}-id') == str(zuordnung.pk)),
                     None)
        if index is None:
            raise Luecke(f'Zuordnung {zuordnung.pk} nicht in der Zahlungsmaske')
        formular.setzen(f'zuordnungen-{index}-DELETE', True)
        formular.absenden('_save')
        if zuordnung.pk in lauf.zahlungen:
            lauf.zahlungen.remove(zuordnung.pk)
        geloest.append({'zahlung': zuordnung.zahlung_id,
                        'betrag': zuordnung.betrag, 'skonto': zuordnung.skonto})
    return geloest


def _zuordnungen_anlegen(lauf: Lauf, geloest: list[dict], beleg: Beleg) -> None:
    """Ordnet die gelösten Zahlungen in deren Maske ``beleg`` zu."""
    if not geloest:
        lauf.luecken.append(f'Keine Zahlung auf den Vorgänger von {beleg} zum Umbuchen')
        return
    for eintrag in geloest:
        formular = maske.oeffnen(lauf.client, reverse(
            'admin:faktura_zahlung_change', args=[eintrag['zahlung']]))
        index = formular.freie_zeile('zuordnungen')
        if str(beleg.pk) not in {w for w, _ in formular.optionen(
                f'zuordnungen-{index}-beleg')}:
            raise Luecke(f'{beleg} in der Zuordnung der Zahlung nicht wählbar')
        formular.zeile('zuordnungen', index, beleg=beleg.pk,
                       betrag=eintrag['betrag'], skonto=eintrag['skonto'])
        vorher = set(Zahlungszuordnung.objects.values_list('pk', flat=True))
        formular.absenden('_save')
        lauf.zahlungen.extend(Zahlungszuordnung.objects.exclude(pk__in=vorher)
                              .values_list('pk', flat=True))


AKTIONEN = {
    'stunden_erfassen': stunden_erfassen,
    'fremdleistung_erfassen': fremdleistung_erfassen,
    'rechnung': rechnung,
    'storno_und_neufassung': storno_und_neufassung,
    'angebot': angebot,
    'auftrag': auftrag,
    'nachtragsangebot': nachtragsangebot,
    'nachtrag_beauftragen': nachtrag_beauftragen,
    'folgeangebot': nachtragsangebot,
    'folgeauftrag': folgeauftrag,
    'abschlag': abschlag,
    'zahlung': zahlung,
    'abnahme': abnahme,
    'schlussrechnung': schlussrechnung,
}


def ausfuehren(lauf: Lauf, schritt: dict):
    aktion = AKTIONEN.get(schritt['aktion'])
    if aktion is None:
        raise Luecke(f'Aktion {schritt["aktion"]!r} im Treiber nicht abgebildet')
    lauf.uhr.stellen(schritt['datum'])
    # Neu anmelden, weil die Sitzung nach zwei Wochen (Django-Vorgabe)
    # abläuft und die Uhr zwischen Schritten weiter springt.
    lauf.client.force_login(lauf.client.benutzer)
    return aktion(lauf, schritt)


def rechnungen(lauf: Lauf):
    """Festgeschriebene Rechnungen aller Arten im Projekt."""
    return Beleg.objects.filter(projekt=lauf.projekt, typ=BelegTyp.RECHNUNG,
                                status=BelegStatus.FESTGESCHRIEBEN)


def abschlaege_bis(lauf: Lauf, beleg: Beleg) -> list[Beleg]:
    """Festgeschriebene, nicht stornierte Abschläge bis einschließlich
    ``beleg``, nach PK."""
    return list(rechnungen(lauf).filter(rechnungsart=Rechnungsart.ABSCHLAG,
                                        pk__lte=beleg.pk).order_by('pk'))

