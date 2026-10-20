"""Rechnungsakte: Herkunft der Positionen einer Rechnung.

Zeigt je Rechnung die erfassten Zeiten und Fremdleistungen, die
Auftragspositionen und die beteiligten Personen. Beim Übernehmen erhält jede
Zeit und Fremdleistung einen Verweis auf die Rechnungsposition
(``abgerechnet_in``). Gerechnet wird in ``zuordnung.fuer_rechnung``; die
Tabelle ist dieselbe wie in Projekt- und Auftragsakte.

Aufbau und Route wie in der Auftragsakte. Ein einziges Recht, weil das
Recht auf eine Rechnung ihre Beträge einschließt.
"""

from decimal import Decimal

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from core.blaettern import nachbarn_im_admin
from faktura import services as faktura_services
from faktura.admin import adresse_im_admin
from faktura.formate import euro
from faktura.models import Beleg, BelegStatus, BelegTyp, proxy_fuer

from . import zuordnung

NULL = Decimal('0.00')


def akte(request, pk):
    """Akte einer Rechnung jeder Art, auch im Entwurf, um vor dem Versand
    den Inhalt zu prüfen."""
    if not request.user.has_perm('faktura.view_rechnung'):
        raise PermissionDenied

    rechnung = get_object_or_404(
        Beleg.objects.select_related('projekt', 'kunde'),
        pk=pk, typ=BelegTyp.RECHNUNG,
    )
    auftraggeber = rechnung.kunde or (rechnung.projekt.kunde
                                      if rechnung.projekt_id else None)
    uebersicht = zuordnung.fuer_rechnung(rechnung)

    return render(request, 'admin/faktura/rechnungsakte.html', {
        **admin.site.each_context(request),
        'title': f'Rechnungsakte {rechnung.nummer or "Entwurf"}',
        'hilfe_anker': 'rechnungsakte',
        'rechnung': rechnung,
        # Im Kopf neben der Nummer, wie in der Liste (R-176).
        'zahlungsstand': _zahlungsmarke(rechnung),
        # Schritte vom Entwurf bis zur Zahlung.
        'belegweg': belegweg(rechnung),
        'bezeichnung': (rechnung.rechnungsbezeichnung
                        or rechnung.get_typ_display()),
        'empfaenger': rechnung.empfaenger_kurz,
        'formular_url': adresse_im_admin(rechnung),
        'projektakte_url': (reverse('projektakte', args=[rechnung.projekt_id])
                            if rechnung.projekt_id else ''),
        'kunde_url': (reverse('admin:faktura_kontakt_change',
                              args=[auftraggeber.pk])
                      if auftraggeber else ''),
        'darf_zahlen_sehen': True,
        'zuordnung': uebersicht,
        'zuordnung_titel': 'Fakturierte Positionen',
        'ohne_titel': 'Ohne Auftragsbezug',
        'personen': uebersicht.personen,
        'kennzahlen': _kennzahlen(rechnung),
        # Die Rechnungslisten verlinken hierher, deshalb Navigation zwischen
        # den Akten.
        'blaettern': nachbarn_im_admin(
            request, proxy_fuer(rechnung.typ, rechnung.rechnungsart), pk,
            lambda ziel: reverse('rechnungsakte', args=[ziel])),
    })


#: Optionale Schritte; sie werden nie als nächster Schritt markiert.
OHNE_PFLICHT = {'E-Mail'}


def belegweg(rechnung) -> list[dict]:
    """Schritte einer Rechnung mit Datum, soweit erreicht.

    Angelegt, festgeschrieben, E-Mail, im Archiv, bezahlt. Jeder Schritt hat
    ``erreicht`` (bool), ``datum`` (oder leer) und ``jetzt`` für den ersten
    fehlenden Schritt.

    "E-Mail" wird nie als nächster Schritt markiert, weil eine Rechnung auch
    per Post oder Portal versendet werden kann; der Schritt trägt das Datum
    der ersten Mail oder bleibt leer.

    "Im Archiv" erscheint nur mit ``PAPERLESS_ARCHIVIERUNG`` oder wenn der
    Beleg schon archiviert ist, damit Installationen ohne Paperless keinen
    unerreichbaren Schritt zeigen.

    "Bezahlt" ist der Tag der letzten Zahlung, sobald nichts mehr offen ist
    (R-176). Ein Abschlag, den die Schlussrechnung vollständig absetzt,
    heißt "Abgerechnet" und gilt nicht als bezahlt. Ein Storno endet mit
    "Storniert" ohne weitere Schritte.
    """
    from django.conf import settings
    from django.utils.timezone import localtime

    def tag(zeitpunkt):
        return localtime(zeitpunkt).strftime('%d.%m.%Y') if zeitpunkt else ''

    festgeschrieben = rechnung.status != BelegStatus.ENTWURF
    schritte = [
        ('Angelegt', True, tag(rechnung.erstellt_am)),
        ('Festgeschrieben', festgeschrieben, tag(rechnung.festgeschrieben_am)),
    ]
    if rechnung.status == BelegStatus.STORNIERT:
        schritte.append(('Storniert', True, ''))
    else:
        schritte.append(('E-Mail', bool(rechnung.versendet_am),
                         tag(rechnung.versendet_am)))
        if settings.PAPERLESS_ARCHIVIERUNG or rechnung.archiviert_am:
            schritte.append(('Im Archiv', bool(rechnung.archiviert_am),
                             tag(rechnung.archiviert_am)))
        stand = faktura_services.zahlungsstand(rechnung)
        if stand == faktura_services.ZAHLUNGSSTAND_ABGERECHNET:
            schritte.append(('Abgerechnet', True, ''))
        else:
            bezahlt = stand == faktura_services.ZAHLUNGSSTAND_BEZAHLT
            zahltage = [z.zahlung.datum for z in
                        rechnung.zahlungszuordnungen.select_related('zahlung')]
            schritte.append(('Bezahlt', bezahlt,
                             max(zahltage).strftime('%d.%m.%Y')
                             if bezahlt and zahltage else ''))

    erster_offener = next((i for i, (titel, erreicht, _) in enumerate(schritte)
                           if not erreicht and titel not in OHNE_PFLICHT),
                          None)
    return [{'titel': titel, 'erreicht': erreicht, 'datum': datum,
             'jetzt': i == erster_offener}
            for i, (titel, erreicht, datum) in enumerate(schritte)]


def _zahlungsmarke(rechnung) -> dict | None:
    """Text und Farbe des Zahlungsstatus im Kopf, wie in der Liste."""
    stand = faktura_services.zahlungsstand(rechnung)
    if not stand:
        return None
    return {
        'text': faktura_services.ZAHLUNGSSTAND_TEXT[stand],
        'art': {faktura_services.ZAHLUNGSSTAND_UEBER_FRIST: 'danger',
                faktura_services.ZAHLUNGSSTAND_BEZAHLT: 'success',
                faktura_services.ZAHLUNGSSTAND_OFFEN: 'info'}.get(stand, ''),
    }


def herkunft(rechnung) -> dict:
    """Der Nettobetrag der Rechnung, aufgeteilt nach seiner Herkunft.

    Eine Position zählt als "aus erfassten Zeiten", wenn Zeiten an ihr
    hängen, als "aus Fremdleistungen", wenn Fremdleistungen an ihr hängen,
    sonst als "ohne Nachweis" (von Hand geschrieben, aus dem Katalog,
    Abzüge). Hängt beides an einer Position, was beim Übernehmen nicht
    vorkommt, zählt sie bei den Zeiten. Die drei Teile ergeben den
    Nettobetrag.
    """
    ergebnis = {'zeiten': NULL, 'fremd': NULL, 'ohne': NULL,
                'einkauf': NULL}
    positionen = rechnung.positionen.prefetch_related('erfassung',
                                                      'fremdleistungen')
    for position in positionen:
        summe = faktura_services.positionssumme(
            menge=position.menge, einzelpreis=position.einzelpreis)
        fremde = list(position.fremdleistungen.all())
        if position.erfassung.all():
            ergebnis['zeiten'] += summe
        elif fremde:
            ergebnis['fremd'] += summe
            ergebnis['einkauf'] += sum((f.einkauf_netto for f in fremde), NULL)
        else:
            ergebnis['ohne'] += summe
    return ergebnis


def _kennzahlen(rechnung) -> list[dict]:
    teile = herkunft(rechnung)
    return [
        {
            'titel': 'Netto',
            'wert': euro(faktura_services.belegsummen(rechnung).netto),
            'hinweis': 'Der Rechnungsbetrag ohne Umsatzsteuer.',
            'icon': 'request_quote',
        },
        {
            'titel': 'Aus Erfassungen',
            'wert': euro(teile['zeiten']),
            'hinweis': 'Positionen, an denen erfasste Leistung hängt: '
                       'Zeiten und Mengen.',
            'icon': 'schedule',
        },
        {
            'titel': 'Aus Fremdleistungen',
            'wert': euro(teile['fremd']),
            'hinweis': f'Im Einkauf {euro(teile["einkauf"])}.',
            'icon': 'science',
        },
        {
            'titel': 'Ohne Nachweis',
            'wert': euro(teile['ohne']),
            'hinweis': 'Von Hand geschrieben, aus dem Katalog oder Abzüge.',
            'icon': 'edit_note',
        },
    ]
