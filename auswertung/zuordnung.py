"""Zuordnung erfasster Zeiten und Fremdleistungen zu Auftragspositionen.

Projekt-, Auftrags- und Rechnungsakte zeigen dieselbe Tabelle (was
geleistet und eingekauft ist, wo es zugeordnet ist, was abgerechnet ist)
für verschiedene Ausschnitte. Deshalb eine Funktion je Akte und ein
gemeinsames Template (``_zuordnung.html``).

Je Zeile eine Auftragsposition, dazu eine Zeile für Leistung ohne
Auftragsposition; in der Projektakte zeigt sie, was noch nicht zugeordnet
ist.

Die Zustände einer Zeit oder Fremdleistung (``Stand``):

* **offen:** auf keiner Rechnung,
* **auf Entwurf:** auf einem Rechnungsentwurf, also reserviert,
* **abgerechnet:** auf einer festgeschriebenen (oder stornierten) Rechnung,
* **nicht abrechenbar:** Kulanz, eigener Fehler; Kosten ohne Erlös.

Gerechnet wird in der Datenbank, eine Abfrage je Quelle. Offene Stunden in
Euro laufen über ``abrechnungsvorschau``, damit sie mit der späteren
Rechnung übereinstimmen (Viertelstunde je Gruppe, R-038).
"""

from dataclasses import dataclass, field
from decimal import Decimal
from urllib.parse import urlencode

from django.db.models import Count, DecimalField, Sum
from django.urls import reverse

from erfassung import services as erfassung_services
from erfassung.formate import dauer_zeigen, personenname
from erfassung.models import Erfassungszeile, Fremdleistung
from faktura import formate
from faktura import services as faktura_services
from faktura.models import Belegposition, BelegStatus, BelegTyp, Leistungsart
from faktura.services.festschreiben import AUF_DEN_AUFTRAG_BERECHNET

NULL = Decimal('0.00')

OFFEN = 'offen'
ENTWURF = 'entwurf'
ABGERECHNET = 'abgerechnet'
NICHT_ABRECHENBAR = 'nicht_abrechenbar'
ZUSTAENDE = (OFFEN, ENTWURF, ABGERECHNET, NICHT_ABRECHENBAR)


def _zustand(abrechenbar: bool, belegstatus: str | None) -> str:
    """Einer der vier Zustände; "nicht abrechenbar" hat Vorrang, wie in
    ``Erfassungszeile.zustand``."""
    if not abrechenbar:
        return NICHT_ABRECHENBAR
    if belegstatus is None:
        return OFFEN
    if belegstatus == BelegStatus.ENTWURF:
        return ENTWURF
    return ABGERECHNET


#: Einheiten, in denen eine Menge eine Zeit ist; sie wird in Minuten
#: umgerechnet.
STUNDEN = {'std', 'h', 'stunde', 'stunden'}


@dataclass(frozen=True)
class Umfang:
    """Erfasster Umfang: Minuten und Mengen je Einheit.

    Eine Zeile auf eine Auftragsposition ohne Leistungsart ist eine
    Mengenzeile; "2 Std" stehen dann als Menge mit null Minuten. Mengen in
    Stunden werden deshalb in Minuten umgerechnet, andere Einheiten (Stk,
    km, pausch) bleiben getrennt. Über Einheiten hinweg wird nichts addiert.
    """

    minuten: int = 0
    #: Paare (Einheit, Menge), sortiert; ein Tupel, damit der Umfang
    #: immutable ist und ``+`` ein neues Objekt liefert.
    mengen: tuple = ()

    @classmethod
    def aus(cls, *, art: str, minuten: int, menge, einheit: str,
            zeilen: int) -> 'Umfang':
        """Umfang einer Gruppe von Erfassungszeilen gleicher Grundlage."""
        if art == Leistungsart.ZEIT:
            return cls(minuten=minuten or 0)
        # Stunden auf einer Pauschale sind Aufwand ohne Menge
        # (Erfassungszeile._pauschale_angleichen) und zählen als Zeit. Ohne
        # beides stammt die Zeile aus Altdaten und zählt als eine Pauschale.
        zeit = cls(minuten=minuten or 0) if art == Leistungsart.PAUSCHALE else cls()
        if art == Leistungsart.PAUSCHALE and not menge and not minuten:
            menge = Decimal(zeilen)
        menge = Decimal(menge or 0)
        if einheit.strip().casefold() in STUNDEN:
            return zeit + cls(minuten=int(menge * 60))
        if not menge:
            return zeit
        return zeit + cls(mengen=((einheit.strip() or 'Stk', menge),))

    def __add__(self, anderer: 'Umfang') -> 'Umfang':
        mengen = dict(self.mengen)
        for einheit, menge in anderer.mengen:
            mengen[einheit] = mengen.get(einheit, Decimal('0')) + menge
        return Umfang(minuten=self.minuten + anderer.minuten,
                      mengen=tuple(sorted(mengen.items())))

    def __bool__(self) -> bool:
        return bool(self.minuten or self.mengen)

    def __str__(self) -> str:
        """Etwa '4:30 Std · 13 Stk', leer ohne Umfang."""
        teile = [f'{dauer_zeigen(self.minuten)} Std'] if self.minuten else []
        teile += [f'{formate.menge(m)} {e}' for e, m in self.mengen]
        return ' · '.join(teile)


@dataclass
class Stand:
    """Wert aufgeteilt nach den vier Zuständen."""

    offen: Decimal | int = 0
    entwurf: Decimal | int = 0
    abgerechnet: Decimal | int = 0
    nicht_abrechenbar: Decimal | int = 0

    def dazu(self, zustand: str, wert) -> None:
        setattr(self, zustand, getattr(self, zustand) + wert)

    @property
    def gesamt(self):
        return (self.offen + self.entwurf + self.abgerechnet
                + self.nicht_abrechenbar)


@dataclass
class Personenanteil:
    name: str
    umfang: Umfang


@dataclass
class Zuordnungszeile:
    """Zeile für eine Auftragsposition oder, mit ``auftragsposition=None``,
    für Leistung ohne Zuordnung."""

    auftragsposition: Belegposition | None
    #: Umfang der erfassten Leistung je Zustand.
    umfang: Stand = field(default_factory=lambda: _leer(Umfang()))
    #: Anzahl der Erfassungszeilen.
    zeilen: int = 0
    personen: list[Personenanteil] = field(default_factory=list)
    #: Sammelstelle für ``personen`` während des Aufbaus.
    umfang_je_person: dict = field(default_factory=dict, repr=False)
    #: Einkauf der Fremdleistungen je Zustand (Zeilenbeträge, R-156).
    einkauf: Stand = field(default_factory=lambda: _leer(NULL))
    fremdleistungen: int = 0
    #: Offene Stunden, bewertet wie die spätere Rechnung (R-050).
    offen_netto: Decimal = NULL
    #: Über alle festgeschriebenen Rechnungen abgerechnete Menge (R-008).
    abgerechnete_menge: Decimal = Decimal('0')
    #: Derselbe Wert netto, ohne Abschläge, wie in der Auftragsakte.
    berechnet_netto: Decimal = NULL
    #: Die zugehörigen Rechnungen, je mit ``nummer`` und ``url`` der
    #: Rechnungsakte.
    rechnungen: list = field(default_factory=list)
    #: Nur in der Rechnungsakte: der Anteil dieser Rechnung, netto.
    auf_dieser_rechnung: Decimal = NULL
    #: Links auf die gefilterten Listen.
    zeiten_url: str = ''
    zeiten_offen_url: str = ''
    fremd_url: str = ''

    @property
    def ist_ohne(self) -> bool:
        return self.auftragsposition is None

    @property
    def zeitanteile(self) -> list[dict]:
        """Zustände mit Umfang, ohne leere, für die Zeile unter der Summe.

        Nur "offen" ist verlinkt, weil die Liste zum Abrechnen dient.
        """
        anteile = [
            ('offen', self.umfang.offen, self.zeiten_offen_url),
            ('auf Entwurf', self.umfang.entwurf, ''),
            ('abgerechnet', self.umfang.abgerechnet, ''),
            ('nicht abrechenbar', self.umfang.nicht_abrechenbar, ''),
        ]
        return [{'titel': t, 'umfang': m, 'url': u}
                for t, m, u in anteile if m]

    @property
    def einkaufsanteile(self) -> list[dict]:
        anteile = [
            ('offen', self.einkauf.offen),
            ('auf Entwurf', self.einkauf.entwurf),
            ('abgerechnet', self.einkauf.abgerechnet),
            ('selbst getragen', self.einkauf.nicht_abrechenbar),
        ]
        return [{'titel': t, 'betrag': b} for t, b in anteile if b]

    @property
    def offen_gesamt(self) -> Decimal:
        """Offener Betrag: Stunden zum Verkaufswert plus Fremdleistung zum
        Einkaufspreis."""
        return self.offen_netto + self.einkauf.offen + self.einkauf.entwurf

    @property
    def ist_ueberzogen(self) -> bool:
        position = self.auftragsposition
        return position is not None and self.abgerechnete_menge > position.menge

    @property
    def ist_leer(self) -> bool:
        return not (self.zeilen or self.fremdleistungen
                    or self.abgerechnete_menge or self.auf_dieser_rechnung)


@dataclass
class Zuordnung:
    zeilen: list[Zuordnungszeile]
    #: Beschriftung der Zeile ohne Auftragsposition: im Projekt "noch nicht
    #: zugeordnet", in der Rechnung "ohne Auftragsbezug".
    ist_rechnung: bool = False

    @property
    def umfang(self) -> Stand:
        return _summe((z.umfang for z in self.zeilen), Umfang())

    @property
    def einkauf(self) -> Stand:
        return _summe((z.einkauf for z in self.zeilen), NULL)

    @property
    def offen_gesamt(self) -> Decimal:
        return sum((z.offen_gesamt for z in self.zeilen), NULL)

    @property
    def berechnet_netto(self) -> Decimal:
        return sum((z.berechnet_netto for z in self.zeilen), NULL)

    @property
    def auf_dieser_rechnung(self) -> Decimal:
        return sum((z.auf_dieser_rechnung for z in self.zeilen), NULL)

    @property
    def personen(self) -> list[Personenanteil]:
        """Erfasster Umfang je Person über alle Zeilen, für die Karte
        "Fakturierte Erfassungen" der Rechnungsakte."""
        je_name: dict[str, Umfang] = {}
        for zeile in self.zeilen:
            for anteil in zeile.personen:
                je_name[anteil.name] = (je_name.get(anteil.name, Umfang())
                                        + anteil.umfang)
        return _personen(je_name)

    @property
    def ist_leer(self) -> bool:
        return all(z.ist_leer for z in self.zeilen)


def _leer(start) -> Stand:
    return Stand(start, start, start, start)


def _summe(staende, start=0) -> Stand:
    ergebnis = _leer(start)
    for stand in staende:
        for zustand in ZUSTAENDE:
            ergebnis.dazu(zustand, getattr(stand, zustand))
    return ergebnis


def _personen(je_name: dict) -> list[Personenanteil]:
    """Sortiert nach Zeit absteigend, bei Gleichstand nach Namen."""
    return sorted((Personenanteil(n, u) for n, u in je_name.items()),
                  key=lambda p: (-p.umfang.minuten, p.name))


# ══════════════════════════════════════════════════════════════════════════
# Einstiegspunkte
# ══════════════════════════════════════════════════════════════════════════

def fuer_projekt(projekt) -> Zuordnung:
    """Alle Positionen der festgeschriebenen Aufträge des Projekts und die
    Leistung ohne Auftragsposition."""
    positionen = list(
        Belegposition.objects
        .filter(beleg__projekt=projekt, beleg__typ=BelegTyp.AUFTRAG,
                beleg__status=BelegStatus.FESTGESCHRIEBEN)
        # Ohne Titel- und Textpositionen, weil darauf nicht erfasst oder
        # abgerechnet wird.
        .exclude(zeilenart__in=('titel', 'text'))
        .select_related('beleg')
        .order_by('beleg__belegdatum', 'beleg__pk', 'sortierung'))
    return _bauen(
        positionen=positionen,
        zeiten=Erfassungszeile.objects.filter(projekt=projekt),
        fremd=Fremdleistung.objects.filter(projekt=projekt),
        filter_basis={'projekt__id__exact': projekt.pk},
        mit_ohne=True,
    )


def fuer_auftrag(auftrag) -> Zuordnung:
    """Positionen dieses Auftrags, ohne die Zeile "ohne Auftragsposition",
    die zum Projekt gehört."""
    positionen = list(auftrag.positionen
                      .exclude(zeilenart__in=('titel', 'text'))
                      .select_related('beleg')
                      .order_by('sortierung', 'pk'))
    return _bauen(
        positionen=positionen,
        zeiten=Erfassungszeile.objects.filter(auftragsposition__beleg=auftrag),
        fremd=Fremdleistung.objects.filter(auftragsposition__beleg=auftrag),
        filter_basis={'auftragsposition__beleg__id__exact': auftrag.pk},
        mit_ohne=False,
    )


def fuer_rechnung(rechnung) -> Zuordnung:
    """Zeiten und Fremdleistungen der Rechnung, gruppiert nach der
    Auftragsposition, die sie abrechnen, mit dem Anteil dieser Rechnung und
    dem Stand über alle Rechnungen.

    Die Zeile "ohne Auftragsbezug" enthält Positionen ohne Auftragsposition
    (Regie, Nebenkosten, Positionen von Hand).
    """
    zeiten = Erfassungszeile.objects.filter(abgerechnet_in__beleg=rechnung)
    fremd = Fremdleistung.objects.filter(abgerechnet_in__beleg=rechnung)

    kennungen = set(
        rechnung.positionen.exclude(auftragsposition=None)
        .values_list('auftragsposition_id', flat=True))
    kennungen |= set(zeiten.exclude(auftragsposition=None)
                     .values_list('auftragsposition_id', flat=True))
    kennungen |= set(fremd.exclude(auftragsposition=None)
                     .values_list('auftragsposition_id', flat=True))
    positionen = list(
        Belegposition.objects.filter(pk__in=kennungen)
        .select_related('beleg')
        .order_by('beleg__belegdatum', 'beleg__pk', 'sortierung'))

    zuordnung = _bauen(
        positionen=positionen, zeiten=zeiten, fremd=fremd,
        filter_basis={'abgerechnet_in__beleg__id__exact': rechnung.pk},
        mit_ohne=True, offen_bewerten=False,
    )
    zuordnung.ist_rechnung = True

    anteile = {
        z['auftragsposition_id']: z['netto'] or NULL
        for z in rechnung.positionen.values('auftragsposition_id').annotate(
            netto=Sum(faktura_services.POSITIONSNETTO,
                      output_field=DecimalField(max_digits=14,
                                                decimal_places=2)))
    }
    for zeile in zuordnung.zeilen:
        schluessel = zeile.auftragsposition.pk if zeile.auftragsposition else None
        zeile.auf_dieser_rechnung = anteile.get(schluessel, NULL)
    return zuordnung


# ══════════════════════════════════════════════════════════════════════════
# Gemeinsamer Aufbau
# ══════════════════════════════════════════════════════════════════════════

def _bauen(*, positionen, zeiten, fremd, filter_basis: dict, mit_ohne: bool,
           offen_bewerten: bool = True) -> Zuordnung:
    zeilen = {p.pk: Zuordnungszeile(auftragsposition=p) for p in positionen}
    ohne = Zuordnungszeile(auftragsposition=None)

    def zeile_zu(kennung):
        if kennung is None:
            return ohne
        return zeilen.get(kennung)

    _zeiten_eintragen(zeiten, zeile_zu, [*zeilen.values(), ohne])
    _fremd_eintragen(fremd, zeile_zu)
    if offen_bewerten:
        _offen_bewerten(zeiten, zeile_zu)
    _berechnetes_eintragen(list(zeilen.values()))

    ergebnis = list(zeilen.values())
    if mit_ohne:
        ergebnis.append(ohne)
    for zeile in ergebnis:
        _verweise_setzen(zeile, filter_basis)
    return Zuordnung(zeilen=ergebnis)


def _zeiten_eintragen(zeiten, zeile_zu, alle) -> None:
    """Minuten und Zeilen je Auftragsposition, Zustand und Person in einer
    Abfrage; die Personen werden gesammelt und am Ende sortiert."""
    from django.contrib.auth import get_user_model

    # Art und Einheit gehören zur Gruppierung, weil sie bestimmen, ob eine
    # Zeile Minuten oder eine Menge enthält. Eine Auftragsposition ohne Art
    # zählt als Menge (wie LeistungsartFilter).
    gruppen = list(
        zeiten.values('auftragsposition_id', 'benutzer_id', 'abrechenbar',
                      'abgerechnet_in__beleg__status',
                      'auftragsposition__art', 'auftragsposition__einheit',
                      'leistung__art', 'leistung__einheit')
        .annotate(minuten=Sum('dauer_minuten'), menge=Sum('menge'),
                  anzahl=Count('pk'))
    )
    namen = {
        benutzer.pk: personenname(benutzer)
        for benutzer in get_user_model().objects.filter(
            pk__in={g['benutzer_id'] for g in gruppen})
    }

    for gruppe in gruppen:
        zeile = zeile_zu(gruppe['auftragsposition_id'])
        if zeile is None:
            continue
        if gruppe['auftragsposition_id']:
            art = gruppe['auftragsposition__art'] or Leistungsart.MENGE
            einheit = gruppe['auftragsposition__einheit'] or ''
        else:
            art = gruppe['leistung__art'] or Leistungsart.MENGE
            einheit = gruppe['leistung__einheit'] or ''
        umfang = Umfang.aus(art=art, minuten=gruppe['minuten'],
                            menge=gruppe['menge'], einheit=einheit,
                            zeilen=gruppe['anzahl'])
        zeile.umfang.dazu(
            _zustand(gruppe['abrechenbar'],
                     gruppe['abgerechnet_in__beleg__status']), umfang)
        zeile.zeilen += gruppe['anzahl']
        name = namen.get(gruppe['benutzer_id'], '?')
        zeile.umfang_je_person[name] = (
            zeile.umfang_je_person.get(name, Umfang()) + umfang)

    for zeile in alle:
        zeile.personen = _personen(zeile.umfang_je_person)


def _fremd_eintragen(fremd, zeile_zu) -> None:
    """Einkauf und Anzahl je Auftragsposition und Zustand in einer Abfrage."""
    for gruppe in (fremd.values('auftragsposition_id', 'weiterberechenbar',
                                'abgerechnet_in__beleg__status')
                   .annotate(einkauf=Sum('einkauf_netto'), anzahl=Count('pk'))):
        zeile = zeile_zu(gruppe['auftragsposition_id'])
        if zeile is None:
            continue
        zeile.einkauf.dazu(
            _zustand(gruppe['weiterberechenbar'],
                     gruppe['abgerechnet_in__beleg__status']),
            gruppe['einkauf'] or NULL)
        zeile.fremdleistungen += gruppe['anzahl']


def _offen_bewerten(zeiten, zeile_zu) -> None:
    """Offene Stunden in Euro über die Abrechnungsvorschau, wie die Rechnung.

    Ein Aufruf je Projekt, weil die Vorschau nur ein Projekt annimmt.
    Entwürfe zählen als offen (``entwuerfe_zaehlen``), wie im Controlling.
    """
    offene = list(
        zeiten.filter(erfassung_services.NOCH_NICHT_ABGERECHNET,
                      abrechenbar=True)
        .select_related('leistung', 'auftragsposition', 'projekt',
                        'abgerechnet_in__beleg'))
    je_projekt: dict[int, list] = {}
    for zeile in offene:
        je_projekt.setdefault(zeile.projekt_id, []).append(zeile)

    for gruppe in je_projekt.values():
        vorschau = erfassung_services.abrechnungsvorschau(
            gruppe, entwuerfe_zaehlen=True)
        for position in vorschau.positionen:
            auftrag = position.auftragsposition
            ziel = zeile_zu(auftrag.pk if auftrag else None)
            if ziel is not None:
                ziel.offen_netto += position.summe


def _berechnetes_eintragen(zeilen) -> None:
    """Über alle festgeschriebenen Rechnungen je Position abgerechnete Menge
    (R-008) und Nettobetrag, in zwei Abfragen."""
    kennungen = [z.auftragsposition.pk for z in zeilen]
    if not kennungen:
        return
    mengen = faktura_services.abgerechnete_mengen(kennungen)
    betraege = {
        z['auftragsposition_id']: z['netto'] or NULL
        for z in Belegposition.objects
        .filter(auftragsposition_id__in=kennungen, **AUF_DEN_AUFTRAG_BERECHNET)
        .values('auftragsposition_id')
        .annotate(netto=Sum(faktura_services.POSITIONSNETTO,
                            output_field=DecimalField(max_digits=14,
                                                      decimal_places=2)))
    }
    rechnungen: dict = {}
    for eintrag in (Belegposition.objects
                    .filter(auftragsposition_id__in=kennungen,
                            **AUF_DEN_AUFTRAG_BERECHNET)
                    .values('auftragsposition_id', 'beleg_id',
                            'beleg__nummer', 'beleg__belegdatum')
                    .distinct()
                    .order_by('beleg__belegdatum', 'beleg_id')):
        rechnungen.setdefault(eintrag['auftragsposition_id'], []).append({
            'nummer': eintrag['beleg__nummer'],
            'url': reverse('rechnungsakte', args=[eintrag['beleg_id']]),
        })
    for zeile in zeilen:
        kennung = zeile.auftragsposition.pk
        zeile.abgerechnete_menge = mengen.get(kennung, Decimal('0'))
        zeile.berechnet_netto = betraege.get(kennung, NULL)
        zeile.rechnungen = rechnungen.get(kennung, [])


def _verweise_setzen(zeile: Zuordnungszeile, filter_basis: dict) -> None:
    """Setzt für jede Zahl den Link auf die gefilterte Liste."""
    if zeile.auftragsposition is None:
        eigener = {'auftragsposition__isnull': 'True'}
    else:
        eigener = {'auftragsposition__id__exact': zeile.auftragsposition.pk}
    abfrage = {**filter_basis, **eigener}

    zeiten = reverse('admin:erfassung_erfassungszeile_changelist')
    fremd = reverse('admin:erfassung_fremdleistung_changelist')
    zeile.zeiten_url = f'{zeiten}?{urlencode(abfrage)}'
    zeile.zeiten_offen_url = f'{zeiten}?{urlencode({**abfrage, "zustand": OFFEN})}'
    zeile.fremd_url = f'{fremd}?{urlencode(abfrage)}'
