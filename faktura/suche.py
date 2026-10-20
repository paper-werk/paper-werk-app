"""Treffer von faktura für die Schnellsuche (Strg+K).

Registriert in ``FakturaConfig.ready()`` über ``core.erweiterungen.suche``.
Je Art höchstens ``GRENZE`` Treffer; jeder Treffer verlinkt auf die
**Akte**, wo es eine gibt, weil die Suche nach einem Kunden meist seinem
Stand gilt.

Vier Arten, jede nur mit dem View-Recht:

* Kontakte nach Nummer und Name,
* Projekte nach Nummer und Bezeichnung,
* Belege nach Nummer, Empfänger und Betreff,
* Belege nach **Betrag**: "1.445,14" findet die Rechnung über 1.445,14 EUR
  brutto, den Betrag auf dem Kontoauszug.

Unfold wandelt den Suchbegriff in Kleinbuchstaben und cacht die Treffer
fünf Minuten (``UnfoldAdminSite.search``); ein neuer Beleg erscheint
eventuell erst danach.
"""

import re
from decimal import Decimal, InvalidOperation

from django.db.models import Q
from django.urls import reverse

from core import erweiterungen

from . import services
from .admin.gemeinsam import adresse_im_admin
from .formate import euro
from .models import Beleg, BelegStatus, Kontakt, Projekt, proxy_fuer

#: Maximale Zahl der Treffer je Art.
GRENZE = 8


def treffer(request, begriff: str) -> list[dict]:
    """Alle Treffer von faktura für ``core.erweiterungen.suchergebnisse``."""
    begriff = begriff.strip()
    if len(begriff) < 2:
        return []
    darf = request.user.has_perm
    ergebnis = []
    if darf('faktura.view_kontakt'):
        ergebnis += _kontakte(begriff)
    if darf('faktura.view_projekt'):
        ergebnis += _projekte(begriff)
    sichtbar = _sichtbare_belegarten(request)
    if sichtbar:
        ergebnis += _belege(begriff, sichtbar)
        betrag = als_betrag(begriff)
        if betrag is not None:
            ergebnis += _belege_mit_betrag(betrag, sichtbar)
    return ergebnis


def als_betrag(begriff: str) -> Decimal | None:
    """Suchbegriff als Geldbetrag oder ``None``.

    Deutsches Format ("1.445,14", "1445,14") wie auf dem Beleg; ein Punkt
    mit genau zwei Nachkommastellen ("1445.14") gilt als Dezimalpunkt, wie
    in Bankportalen. Ganze Zahlen ("2026") gelten nicht als Betrag, weil sie
    meist Teil einer Nummer sind.
    """
    roh = begriff.replace('€', '').replace('eur', '').replace(' ', '')
    if re.fullmatch(r'\d{1,3}(\.\d{3})*,\d{1,2}', roh) or re.fullmatch(r'\d+,\d{1,2}', roh):
        roh = roh.replace('.', '').replace(',', '.')
    elif not re.fullmatch(r'\d+\.\d{2}', roh):
        return None
    try:
        return Decimal(roh)
    except InvalidOperation:
        return None


def _kontakte(begriff):
    kontakte = (Kontakt.objects
                .filter(Q(nummer__icontains=begriff) | Q(name__icontains=begriff))
                .order_by('name')[:GRENZE])
    return [{
        'titel': f'{k.nummer} · {k.name}',
        'beschreibung': 'Kontakt',
        'link': (erweiterungen.akte_url('kunde', k.pk)
                 or reverse('admin:faktura_kontakt_change', args=[k.pk])),
        'icon': 'groups',
    } for k in kontakte]


def _projekte(begriff):
    projekte = (Projekt.objects
                .filter(Q(nummer__icontains=begriff)
                        | Q(bezeichnung__icontains=begriff))
                .select_related('kunde').order_by('-nummer')[:GRENZE])
    return [{
        'titel': f'{p.nummer} · {p.bezeichnung}',
        'beschreibung': f'Projekt · {p.kunde.name}' if p.kunde_id else 'Projekt',
        'link': (erweiterungen.akte_url('projekt', p.pk)
                 or reverse('admin:faktura_projekt_change', args=[p.pk])),
        'icon': 'construction',
    } for p in projekte]


def _sichtbare_belegarten(request) -> list[tuple[str, str]]:
    """``(typ, rechnungsart)`` der für den Benutzer sichtbaren Belegarten,
    je Art nach dem Recht ihres Proxys, wie in den Listen."""
    arten = (Beleg.objects.order_by().values_list('typ', 'rechnungsart')
             .distinct())
    sichtbar = []
    for typ, art in arten:
        modell = proxy_fuer(typ, art)
        if modell is not Beleg and request.user.has_perm(
                f'{modell._meta.app_label}.view_{modell._meta.model_name}'):
            sichtbar.append((typ, art))
    return sichtbar


def _nur(sichtbar) -> Q:
    bedingung = Q(pk__in=[])
    for typ, art in sichtbar:
        bedingung |= Q(typ=typ, rechnungsart=art)
    return bedingung


def _belege(begriff, sichtbar):
    belege = (Beleg.objects.filter(_nur(sichtbar))
              .filter(Q(nummer__icontains=begriff)
                      | Q(empfaenger__icontains=begriff)
                      | Q(betreff__icontains=begriff))
              .order_by('-belegdatum', '-pk')[:GRENZE])
    return [_belegtreffer(b) for b in belege]


def _belege_mit_betrag(betrag, sichtbar):
    """Festgeschriebene Belege mit genau diesem Bruttobetrag, über
    ``services.bruttosummen``, dieselbe Berechnung wie die Spalte "Brutto"
    (R-173)."""
    alle = Beleg.objects.filter(_nur(sichtbar),
                                status=BelegStatus.FESTGESCHRIEBEN)
    treffer_pks = [pk for pk, brutto in services.bruttosummen(alle).items()
                   if brutto == betrag][:GRENZE]
    belege = Beleg.objects.filter(pk__in=treffer_pks).order_by('-belegdatum')
    return [_belegtreffer(b, icon='euro') for b in belege]


def _belegtreffer(beleg, icon='receipt_long') -> dict:
    akte = (erweiterungen.akte_url('rechnung', beleg.pk)
            if beleg.typ == 'rechnung' else None)
    titel = beleg.nummer or f'Entwurf {beleg.pk}'
    teile = [beleg.get_typ_display(), beleg.empfaenger_kurz]
    if beleg.status == BelegStatus.FESTGESCHRIEBEN:
        teile.append(euro(services.belegsummen(beleg).brutto))
    return {
        'titel': f'{titel} · {beleg.betreff}' if beleg.betreff else titel,
        'beschreibung': ' · '.join(t for t in teile if t),
        'link': akte or adresse_im_admin(beleg),
        'icon': icon,
    }
