"""Liste "Zu erledigen" auf der Startseite.

Rechnet nichts selbst, wie ``dashboard.py``. Aus den Ergebnissen der
Startseite (offene Posten, Projektergebnisse, Alter der nicht abgerechneten
Leistung) werden die Fälle ausgewählt, die eine Handlung verlangen, und
nach Dringlichkeit sortiert. Zusätzlich gibt es eine Abfrage: lange
liegende Rechnungsentwürfe.

Jede Aufgabe verlinkt auf die Stelle, an der sie erledigt wird, eine
gefilterte Liste oder eine Akte. Fehlt dem Benutzer das Recht für das Ziel,
erscheint die Aufgabe ohne Link.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from faktura import services as faktura_services
from faktura.formate import euro
from faktura.models import (
    Beleg,
    BelegStatus,
    BelegTyp,
    Rechnungsart,
    proxy_fuer,
)

#: Alter in Tagen, ab dem ein Rechnungsentwurf als liegengeblieben gilt.
#: Drei Tage, damit ein am Freitag begonnener Entwurf am Montag noch nicht
#: erscheint.
ENTWURF_LIEGT_AB_TAGEN = 3

#: Anzahl der Projekte über Auftragswert, die einzeln aufgeführt werden.
PROJEKTE_UEBER_AUFTRAG = 3

#: Reihenfolge der Schweregrade, rot zuerst.
RANG = {'rot': 0, 'gelb': 1, 'blau': 2, 'grau': 3}


@dataclass(frozen=True)
class Aufgabe:
    """Eine Zeile unter "Zu erledigen"."""

    #: rot (Geld ist überfällig), gelb (Geld liegt), blau (Zahlen sind
    #: unvollständig), grau (Arbeit liegt).
    schwere: str
    titel: str
    text: str
    #: Betrag oder Menge, fertig geschrieben.
    groesse: str
    knopf: str
    #: Leer, wenn der Benutzer das Ziel nicht öffnen darf.
    url: str


def aufgaben(request, *, uebersicht, posten, alt_ueber_90) -> list[Aufgabe]:
    """Aufgaben des Benutzers, die dringendste zuerst.

    ``uebersicht``, ``posten`` und ``alt_ueber_90`` (der Teil der nicht
    abgerechneten Leistung, der älter als 90 Tage ist) sind Ergebnisse, die
    ``dashboard.startseite`` schon geholt hat.
    """
    darf = request.user.has_perm
    liste = []

    liste.extend(_ueberfaellige(darf, posten.ueberfaellig))

    if alt_ueber_90 > 0:
        liste.append(Aufgabe(
            schwere='gelb',
            titel='Leistung liegt länger als 90 Tage',
            text='Erfasst oder zugekauft, aber auf keiner Rechnung',
            groesse=euro(alt_ueber_90),
            knopf='Abrechnen',
            url=reverse('liegengeblieben'),
        ))

    ueberzogen = [z for z in uebersicht.zeilen if z.ist_ueberzogen]
    for stand in sorted(ueberzogen, key=lambda z: -z.ueberschreitung)[
            :PROJEKTE_UEBER_AUFTRAG]:
        liste.append(Aufgabe(
            schwere='gelb',
            titel=f'{stand.projekt.nummer} über dem Auftrag',
            text=(f'{stand.projekt.bezeichnung}: geleistet ist mehr als '
                  'beauftragt. Nachtrag oder Abrechnung nach Aufwand?'),
            groesse=euro(stand.ueberschreitung),
            knopf='Zur Projektakte',
            url=reverse('projektakte', args=[stand.projekt.pk]),
        ))

    if uebersicht.ohne_kostensatz:
        # Der Name aus der Erfassung, nicht der Benutzername.
        namen = sorted(
            person.get_full_name() or person.username for person in
            get_user_model().objects.filter(pk__in=uebersicht.ohne_kostensatz))
        stunden = uebersicht.minuten_ohne_satz // 60
        liste.append(Aufgabe(
            schwere='blau',
            titel='Kostensatz fehlt',
            text=(f'{", ".join(namen)}: {stunden} Std ohne Bewertung, '
                  'die Ergebnisse sind deshalb zu gut'),
            groesse=f'{stunden} Std',
            knopf='Kostensätze pflegen',
            url=(reverse('admin:erfassung_kostensatz_changelist')
                 if darf('erfassung.view_kostensatz') else ''),
        ))

    entwurf = _liegende_entwuerfe()
    if entwurf is not None:
        anzahl, summe, aeltester = entwurf
        liste.append(Aufgabe(
            schwere='grau',
            titel=('Rechnungsentwurf liegt' if anzahl == 1
                   else f'{anzahl} Rechnungsentwürfe liegen'),
            text=(f'Angelegt am {date_format(aeltester, "SHORT_DATE_FORMAT")}'
                  if anzahl == 1 else
                  f'Älter als {ENTWURF_LIEGT_AB_TAGEN} Tage, der älteste vom '
                  f'{date_format(aeltester, "SHORT_DATE_FORMAT")}'),
            groesse=euro(summe),
            knopf='Fertigstellen',
            url=(_liste('rechnung', status__exact=BelegStatus.ENTWURF)
                 if darf('faktura.view_rechnung') else ''),
        ))

    return sorted(liste, key=lambda a: RANG[a.schwere])


def _liegende_entwuerfe():
    """``(Anzahl, Brutto, ältestes Anlagedatum)`` der gewöhnlichen
    Rechnungen, die seit mehr als drei Tagen im Entwurf liegen, oder
    ``None``. Die Summe aus ``services.summe_ueber``, der Rechnung unter
    jeder Belegliste (R-014/R-015)."""
    grenze = timezone.now() - timedelta(days=ENTWURF_LIEGT_AB_TAGEN)
    entwuerfe = Beleg.objects.filter(
        typ=BelegTyp.RECHNUNG, rechnungsart=Rechnungsart.NORMAL,
        status=BelegStatus.ENTWURF, erstellt_am__lt=grenze)
    aeltester = entwuerfe.order_by('erstellt_am').values_list(
        'erstellt_am', flat=True).first()
    if aeltester is None:
        return None
    summe = faktura_services.summe_ueber(entwuerfe)
    return summe.anzahl, summe.brutto, timezone.localtime(aeltester).date()


def _ueberfaellige(darf, ueberfaellig) -> list[Aufgabe]:
    """Überfällige Forderungen, je Rechnungsart eine Aufgabe.

    Abschlags-, Schluss- und Teilschlussrechnungen haben eigene Listen (ein
    Proxy je Art), die Liste "Rechnungen" zeigt sie nicht. Ein gemeinsamer
    Link führte bei einer überfälligen Abschlagsrechnung in eine leere
    Liste. Ist nur eine Rechnung überfällig, verlinkt die Aufgabe direkt auf
    ihre Maske.
    """
    if not ueberfaellig:
        return []
    if len(ueberfaellig) == 1:
        (posten,) = ueberfaellig
        modell = proxy_fuer(posten.beleg.typ, posten.beleg.rechnungsart)
        url = (reverse(f'admin:faktura_{modell._meta.model_name}_change',
                       args=[posten.beleg.pk])
               if darf(f'faktura.view_{modell._meta.model_name}') else '')
        return [_ueberfaellig_aufgabe('Forderungen über der Frist',
                                      ueberfaellig, url)]

    je_art = {}
    for posten in ueberfaellig:
        je_art.setdefault(posten.beleg.rechnungsart, []).append(posten)
    aufgaben_ = []
    for art in Rechnungsart.values:
        if art not in je_art:
            continue
        modell = proxy_fuer(BelegTyp.RECHNUNG, art)
        name = modell._meta.model_name
        url = (_liste(name, zahlungsstand='ueberfaellig')
               if darf(f'faktura.view_{name}') else '')
        aufgaben_.append(_ueberfaellig_aufgabe(
            f'{modell._meta.verbose_name_plural} über der Frist',
            je_art[art], url))
    return aufgaben_


def _ueberfaellig_aufgabe(titel, posten, url) -> Aufgabe:
    aeltester = max(posten, key=lambda p: p.tage_ueberfaellig or 0)
    anzahl = len(posten)
    return Aufgabe(
        schwere='rot',
        titel=titel,
        text=(f'{anzahl} Rechnung{"" if anzahl == 1 else "en"}; die älteste, '
              f'{aeltester.beleg.nummer} an {aeltester.beleg.empfaenger_kurz}, '
              f'seit {aeltester.tage_ueberfaellig} Tagen'),
        groesse=euro(sum((p.offen for p in posten), Decimal('0.00'))),
        knopf='Mahnen oder Zahlung vermerken',
        url=url,
    )


def _liste(modell: str, **filter) -> str:
    """URL einer Liste aus faktura mit Filter."""
    from urllib.parse import urlencode

    return (reverse(f'admin:faktura_{modell}_changelist')
            + '?' + urlencode(filter))
