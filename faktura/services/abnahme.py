"""Erzeugt aus einer Abnahme die abschließende Rechnung.

Teilabnahme ergibt Teilschlussrechnung, Gesamtabnahme Schlussrechnung.
Leistungsdatum (BT-72) und Zeitraum (BT-73/74) kommen aus der Abnahme und
werden als eigene Werte an der Rechnung gespeichert, damit sie nach dem
Festschreiben unverändert bleiben.

Positionen: Die Teilschlussrechnung übernimmt die Positionen der
Teilleistung mit offener Menge, Preis und Satz aus dem Vertrag (das
gesondert vereinbarte Entgelt). Die Schlussrechnung erhält die Leistung aus
den abgesetzten Abschlägen, je Leistung mit der Gesamtmenge
(``abschlaege._leistung_aus_abschlaegen``). Leistungen ohne Abschlag kommen
aus der Erfassung ("Leistungen übernehmen"). Die Auftragspositionen werden
nicht übernommen, weil sie eine zweite Quelle für dieselbe Leistung wären.
"""

from datetime import date

from django.db import transaction
from django.db.models import Max, Min, Q

from ..models import (
    Abnahme,
    Abnahmeart,
    Beleg,
    BelegStatus,
    BelegTyp,
    Rechnungsart,
)
from .abschlaege import abschlaege_absetzen
from .anlegen import beleg_anlegen, position_hinzufuegen
from .fehler import FalscherStatus


def leistungszeitraum_vorschlag(auftrag, positionen=None
                                ) -> tuple[date | None, date | None]:
    """Erster und letzter Tag mit Erfassung auf diese Auftragspositionen,
    Vorschlag für Leistungsbeginn und -ende der Abnahme.

    Über die Reverse Relation ``kontierungen`` der Erfassung, ohne Import,
    weil faktura nicht von erfassung abhängt.
    """
    from ..models import Belegposition
    if positionen is None:
        positionen = Belegposition.objects.filter(
            Q(beleg=auftrag) | Q(beleg__nachtrag_zu=auftrag))
    grenzen = Belegposition.objects.filter(
        pk__in=[p.pk for p in positionen]).aggregate(
        beginn=Min('kontierungen__datum'), ende=Max('kontierungen__datum'))
    return grenzen['beginn'], grenzen['ende']


@transaction.atomic
def rechnung_aus_abnahme(*, abnahme_id: int) -> Beleg:
    """Legt die (Teil-)Schlussrechnung zu einer Abnahme als Entwurf an."""
    abnahme = Abnahme.objects.select_for_update().select_related(
        'auftrag').get(pk=abnahme_id)

    if not abnahme.abgenommen_am:
        raise FalscherStatus(
            f'{abnahme} ist noch nicht abgenommen; ohne Abnahme kein '
            f'Leistungsdatum, also keine Schlussrechnung.')
    if abnahme.ist_abgerechnet:
        raise FalscherStatus(
            f'{abnahme} ist schon abgerechnet mit {abnahme.rechnung}.')
    entwurf = abnahme.rechnungen.filter(status=BelegStatus.ENTWURF).first()
    if entwurf is not None:
        raise FalscherStatus(
            f'Zu {abnahme} gibt es schon den Entwurf {entwurf}.')

    teil = abnahme.art == Abnahmeart.TEIL
    positionen = list(abnahme.auftragspositionen()) if teil else []
    if teil and not positionen:
        raise FalscherStatus(
            f'{abnahme} nennt keine Auftragsposition; welche Teilleistung '
            f'abgenommen wurde, steht in den Positionen.')
    # Nur Positionen mit offener Menge, weil sonst eine Rechnung nur aus
    # negativen Abzügen entstünde, etwa wenn die Positionen bereits mit der
    # Schlussrechnung abgerechnet sind.
    if teil and not any(p.offene_menge for p in positionen):
        raise FalscherStatus(
            f'Die Positionen von {abnahme} sind schon vollständig '
            f'abgerechnet; es bleibt nichts für eine Teilschlussrechnung.')

    auftrag = abnahme.auftrag
    art = Rechnungsart.TEILSCHLUSS if teil else Rechnungsart.SCHLUSS
    rechnung = beleg_anlegen(
        projekt=auftrag.projekt,
        kunde=None if auftrag.projekt_id else auftrag.kunde,
        typ=BelegTyp.RECHNUNG,
        rechnungsart=art,
        abnahme=abnahme,
        betreff=(f'{art.label}: {abnahme.bezeichnung}' if abnahme.bezeichnung
                 else f'{art.label} zu {auftrag.nummer}'),
        bestellnummer=auftrag.bestellnummer,
        leistungsdatum=abnahme.leistungsbeginn,
        leistungsdatum_bis=abnahme.leistungsende,
        steuerliches_leistungsdatum=abnahme.steuerliches_leistungsdatum,
    )
    for position in positionen:
        # Optionale Positionen werden nicht übernommen, auch nicht mit
        # geschätzter Menge, weil der Abruf manuell erfasst wird.
        if position.optional:
            continue
        menge = position.offene_menge
        if not menge:
            continue
        # Nummer aus dem Auftrag, damit die Ordnung eines
        # Leistungsverzeichnisses erhalten bleibt. Bei Duplikaten (Auftrag
        # und Nachtrag zählen beide ab 10) vergibt position_hinzufuegen die
        # nächste freie.
        belegt = set(rechnung.positionen.values_list('position', flat=True))
        position_hinzufuegen(
            position=None if position.position in belegt else position.position,
            beleg=rechnung, bezeichnung=position.bezeichnung,
            langtext=position.langtext, menge=menge,
            einheit=position.einheit, einzelpreis=position.einzelpreis,
            steuersatz=position.steuersatz, art=position.art,
            # Ein Zuschlag bleibt Zuschlag, bezogen auf die Teilleistung.
            zeilenart=position.zeilenart,
            zuschlag_prozent=position.zuschlag_prozent,
            zuschlag_auf=position.zuschlag_auf,
            auftragsposition=position,
            leistung_von=abnahme.leistungsbeginn,
            leistung_bis=abnahme.leistungsende,
        )
    # Zugehörige Abschläge direkt absetzen.
    abschlaege_absetzen(beleg_id=rechnung.pk)
    return rechnung
