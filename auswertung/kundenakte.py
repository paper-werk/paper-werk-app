"""Kundenakte: Stammdaten, Projekte, Belege und Zahlungen eines Kunden.

Kunden werden häufiger nachgeschlagen als geändert. Deshalb verlinkt die
Kundenliste auf die Akte, anders als bei Projekt und Auftrag, und die Akte
hat einen Button zu den Stammdaten. Eine Kontakthistorie gibt es nicht.

Das Modul rechnet nicht selbst. Die Zahlen kommen aus denselben Funktionen
wie auf Startseite und Rechnung, vor allem ``services.offene_posten``.
"""

from decimal import Decimal

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from core.blaettern import nachbarn_im_admin
from faktura import services as faktura_services
from faktura.admin import adresse_im_admin
from faktura.models import (
    Adressverwendung,
    Beleg,
    BelegStatus,
    BelegTyp,
    Kontakt,
    Projekt,
    Zahlung,
)

#: Höchstzahl der Belege in der Akte; darüber verlinkt sie auf die Liste,
#: damit Kunden mit vielen Rechnungen die Seite nicht überladen (wie
#: ``FREMDLEISTUNGEN_IN_DER_AKTE`` in der Projektakte).
BELEGE_IN_DER_AKTE = 15

#: Höchstzahl der Projekte in der Akte.
PROJEKTE_IN_DER_AKTE = 15

#: Höchstzahl der Zahlungseingänge. Sie zeigen das Zahlungsverhalten, dafür
#: genügen die letzten; ältere Zahlungen findet die Suche der Zahlungsliste.
ZAHLUNGEN_IN_DER_AKTE = 10


def akte(request, pk):
    """Akte eines Kunden.

    Zwei Rechte, wie in der Projektakte: Mit dem Recht auf Kunden sind
    Anschriften, Personen und Projekte sichtbar; Beträge (Umsatz, offene
    Posten) verlangen zusätzlich ``faktura.view_rechnung``.
    """
    if not request.user.has_perm('faktura.view_kontakt'):
        raise PermissionDenied

    kunde = get_object_or_404(
        Kontakt.objects.prefetch_related(
            'adressen', 'kontaktwege',
            'ansprechpartner__kontaktwege', 'ansprechpartner__adresse'),
        pk=pk)
    darf_zahlen_sehen = request.user.has_perm('faktura.view_rechnung')

    zusammenhang = {
        **admin.site.each_context(request),
        'title': (f'Kundenakte {kunde.nummer}' if kunde.ist_kunde
                  else f'Kontaktakte {kunde.nummer}'),
        'hilfe_anker': 'kundenakte',
        'kunde': kunde,
        'darf_zahlen_sehen': darf_zahlen_sehen,
        'anschriften': _anschriften(kunde),
        'kontaktdaten': _kontaktdaten(kunde),
        'personen': _personen(kunde),
        'konditionen': _konditionen(kunde),
        'projekte': _projekte(kunde),
        'formular_url': reverse('admin:faktura_kontakt_change', args=[pk]),
        'projekte_url': (
            f'{reverse("admin:faktura_projekt_changelist")}'
            f'?kunde__id__exact={pk}'),
        # ``?kunde=`` verwendet KundeBelegFilter, der Projektbelege
        # einschließt. ``?kunde__id__exact=`` wäre unvollständig und wird
        # abgewiesen, weil die Belegmasken ``kunde`` nicht in
        # ``list_filter`` führen.
        'belege_url': (
            f'{reverse("admin:faktura_rechnung_changelist")}'
            f'?kunde={pk}'),
        # Ein abweichender Rechnungsempfänger verlinkt auf seine eigene Akte.
        'rechnungsempfaenger_url': (
            reverse('kundenakte', args=[kunde.rechnungsempfaenger_id])
            if kunde.rechnungsempfaenger_id else ''),
        # Die Kontaktliste verlinkt hierher, deshalb Navigation zwischen den
        # Akten.
        'blaettern': nachbarn_im_admin(
            request, Kontakt, pk,
            lambda ziel: reverse('kundenakte', args=[ziel])),
    }

    if darf_zahlen_sehen:
        zusammenhang.update(_zahlen(kunde))
        zusammenhang['belege'] = _belegzeilen(kunde)
        zusammenhang['zahlungen'] = _zahlungseingaenge(kunde)
        zusammenhang['zahlungen_url'] = (
            f'{reverse("admin:faktura_zahlung_changelist")}'
            f'?kunde__id__exact={pk}')

    # Bei Lieferanten deren Eingangsrechnungen, nur mit dem Recht darauf,
    # weil sie Einkaufspreise enthalten.
    if (kunde.ist_lieferant
            and request.user.has_perm('erfassung.view_eingangsrechnung')):
        zusammenhang['eingangsrechnungen'] = _eingangsrechnungen(kunde)
        zusammenhang['eingangsrechnungen_url'] = (
            f'{reverse("admin:erfassung_eingangsrechnung_changelist")}'
            f'?lieferant__id__exact={pk}')

    return render(request, 'admin/faktura/kundenakte.html', zusammenhang)


#: Höchstzahl der Eingangsrechnungen; darüber verlinkt die Akte auf die
#: gefilterte Liste.
EINGANGSRECHNUNGEN_IN_DER_AKTE = 10


def _eingangsrechnungen(kontakt) -> list[dict]:
    """Jüngste Eingangsrechnungen des Lieferanten mit offenem Betrag."""
    from erfassung.models import Eingangsrechnung

    rechnungen = (Eingangsrechnung.objects.filter(lieferant=kontakt)
                  .prefetch_related('positionen')
                  .order_by('-datum', '-pk')[:EINGANGSRECHNUNGEN_IN_DER_AKTE])
    return [
        {
            'datum': rechnung.datum,
            'nummer': rechnung.nummer,
            'betrag': rechnung.betrag_netto,
            'rest': rechnung.rest,
            'url': reverse('admin:erfassung_eingangsrechnung_change',
                           args=[rechnung.pk]),
        }
        for rechnung in rechnungen
    ]


# --------------------------------------------------------------------------
# Stammdaten
# --------------------------------------------------------------------------

def _anschriften(kunde) -> list[dict]:
    """Anschriften als Textblock, Standardanschrift zuerst.

    Die Zeilen kommen aus ``Adresse.zeilen``, aus dem auch das Empfängerfeld
    eines Belegs entsteht; die Akte zeigt die Anschrift also wie auf dem
    Beleg.
    """
    return [
        {
            'verwendung': adresse.get_verwendung_display(),
            'bezeichnung': adresse.bezeichnung,
            'zeilen': adresse.zeilen,
            'land': adresse.land,
            'ist_standard': adresse.ist_standard,
            # Die Rechnungsanschrift wird gekennzeichnet, weil sie als einzige
            # automatisch verwendet wird.
            'ist_rechnungsanschrift': (
                adresse.verwendung == Adressverwendung.RECHNUNG),
        }
        for adresse in kunde.adressen.all()
    ]


def _kontaktdaten(kunde) -> list[dict]:
    """Kontaktwege (Telefon, E-Mail, Web), nach Art gruppiert.

    Innerhalb der Art der Standard zuerst, wie ``Kontaktweg.Meta.ordering``
    liefert. Gruppiert wird in Python, damit das Template keine
    Sortierbedingung über ``ifchanged`` enthält.
    """
    gruppen: dict[str, dict] = {}
    for kontakt in kunde.kontaktwege.all():
        gruppe = gruppen.setdefault(
            kontakt.art,
            {'art': kontakt.get_art_display(), 'eintraege': []})
        gruppe['eintraege'].append({
            'wert': kontakt.wert,
            'wofuer': kontakt.bezeichnung,
            'ist_standard': kontakt.ist_standard,
            # Nur E-Mail und Web als Link; ein tel:-Link hat auf
            # Bürorechnern meist keine Funktion.
            'verweis': _verweis(kontakt),
        })
    return list(gruppen.values())


def _verweis(kontakt) -> str:
    """Link für einen Kontaktweg oder leer."""
    from faktura.models import Kontaktart

    if kontakt.art == Kontaktart.EMAIL:
        return f'mailto:{kontakt.wert}'
    if kontakt.art == Kontaktart.WEB:
        wert = kontakt.wert.strip()
        return wert if wert.startswith(('http://', 'https://')) else f'https://{wert}'
    return ''


def _personen(kunde) -> list[dict]:
    """Ansprechpartner, Hauptansprechpartner zuerst, inaktive zuletzt.

    Inaktive Personen erscheinen gekennzeichnet, weil ältere Belege sie
    nennen ("z. Hd. Frau Müller"). Dafür gibt es das Feld ``aktiv`` anstelle
    des Löschens.
    """
    personen = sorted(
        kunde.ansprechpartner.all(),
        key=lambda p: (not p.aktiv, not p.ist_standard, p.nachname, p.vorname))
    return [
        {
            'name': person.name,
            'anrede': person.get_anrede_display() if person.anrede else '',
            'funktion': person.funktion,
            'email': person.email,
            'telefon': person.telefon,
            'mobil': person.kontaktweg('mobil'),
            'standort': (person.adresse.bezeichnung or str(person.adresse)
                         if person.adresse_id else ''),
            'ist_standard': person.ist_standard,
            'aktiv': person.aktiv,
            'notiz': person.notiz,
            'url': reverse('admin:faktura_ansprechpartner_change',
                           args=[person.pk]),
        }
        for person in personen
    ]


def _konditionen(kunde) -> list[dict]:
    """Konditionen des Kunden für Belege als Liste.

    Nur gesetzte Werte; ein Kunde ohne Skonto erhält keine Zeile "Skonto:
    0 %" (wie ``Beleg.mahntext``).
    """
    zeilen = [
        ('Zahlungsziel', f'{kunde.zahlungsziel_tage} Tage'),
    ]
    if kunde.skonto_prozent:
        zeilen.append((
            'Skonto',
            f'{kunde.skonto_prozent.normalize():f} % '
            f'innerhalb von {kunde.skonto_tage} Tagen'))
    if kunde.ust_id:
        zeilen.append(('USt-IdNr.', kunde.ust_id))
    if kunde.steuerfall:
        zeilen.append(('Steuerfall', kunde.get_steuerfall_display()))
    zeilen.append(('Zustellweg', kunde.get_zustellweg_display()))
    if kunde.kaeuferreferenz:
        zeilen.append(('Käuferreferenz', kunde.kaeuferreferenz))
    return [{'was': was, 'wert': wert} for was, wert in zeilen]


# --------------------------------------------------------------------------
# Projekte, Belege, Zahlungen
# --------------------------------------------------------------------------

def _projekte(kunde) -> list[dict]:
    """Projekte des Kunden, laufende zuerst."""
    projekte = (
        Projekt.objects
        .filter(kunde=kunde)
        .annotate(belegzahl=Count('belege', distinct=True))
        .order_by('abgeschlossen', '-nummer')
    )
    return [
        {
            'nummer': projekt.nummer,
            'bezeichnung': projekt.bezeichnung,
            'abgeschlossen': projekt.abgeschlossen,
            'belegzahl': projekt.belegzahl,
            'url': reverse('projektakte', args=[projekt.pk]),
        }
        for projekt in projekte[:PROJEKTE_IN_DER_AKTE]
    ]


def _belege_des_kunden(kunde):
    """Alle Belege des Kunden, direkt am Kunden oder an seinen Projekten.

    Der Constraint ``kunde_oder_projekt_nicht_beides`` ordnet jeden Beleg
    entweder dem Kunden oder einem Projekt zu; ein Projektbeleg hat keine
    ``kunde_id``. ``filter(kunde=kunde)`` fände ihn nicht und ergäbe 0 €
    Umsatz. In der Auftragsakte entspricht dem
    ``auftrag.kunde or auftrag.projekt.kunde``.
    """
    return Beleg.objects.filter(Q(kunde=kunde) | Q(projekt__kunde=kunde))


def _belegzeilen(kunde) -> list[dict]:
    """Jüngste Belege, nur Wertbelege mit Nummer.

    Ohne Entwürfe, wie in allen Auswertungen, weil sie keine Nummer haben
    und frei änderbar sind.
    """
    belege = (
        _belege_des_kunden(kunde)
        .filter(typ__in=BelegTyp.wertbelege())
        .exclude(status=BelegStatus.ENTWURF)
        .prefetch_related('positionen', 'zahlungszuordnungen')
        .order_by('-belegdatum', '-nummer')[:BELEGE_IN_DER_AKTE]
    )
    return [
        {
            'nummer': beleg.nummer,
            'typ': beleg.get_typ_display(),
            'datum': beleg.belegdatum,
            'betreff': beleg.betreff,
            'brutto': faktura_services.belegsummen(beleg).brutto,
            'offen': beleg.offener_betrag,
            'url': adresse_im_admin(beleg),
        }
        for beleg in belege
    ]


def _zahlungseingaenge(kunde) -> list[dict]:
    """Zahlungseingänge des Kunden, die jüngsten zuerst.

    Zeigt das Zahlungsverhalten neben den offenen Forderungen. Je Zahlung
    steht die zugeordnete Rechnung; Zahlungen ohne Zuordnung erscheinen als
    "noch nicht zugeordnet".
    """
    if not kunde.pk:
        return []

    zahlungen = (
        Zahlung.objects
        .filter(kunde=kunde)
        .prefetch_related('zuordnungen__beleg')
        .order_by('-datum', '-pk')[:ZAHLUNGEN_IN_DER_AKTE]
    )
    return [
        {
            'datum': zahlung.datum,
            'betrag': zahlung.betrag,
            'art': zahlung.get_zahlungsart_display(),
            'zweck': zahlung.verwendungszweck,
            'belege': [z.beleg.nummer for z in zahlung.zuordnungen.all()
                       if z.beleg.nummer],
            'rest': zahlung.rest,
            'url': reverse('admin:faktura_zahlung_change', args=[zahlung.pk]),
        }
        for zahlung in zahlungen
    ]


def _zahlen(kunde) -> dict:
    """Umsatz und offene Posten des Kunden.

    Die offenen Posten kommen aus ``services.offene_posten`` und werden nur
    gefiltert, damit Kundenakte und Rechnungsliste dieselben Beträge zeigen.
    """
    # Dieselbe Funktion, eingeschränkt auf die Belege des Kunden.
    eigene = faktura_services.offene_posten(
        belege=_belege_des_kunden(kunde)).posten

    umsatz = faktura_services.summe_ueber(
        _belege_des_kunden(kunde)
        .filter(typ__in=BelegTyp.steuerbelege())
        .exclude(status=BelegStatus.ENTWURF),
        als_umsatz=True,
    )

    return {
        'umsatz_netto': umsatz.netto,
        'umsatz_brutto': umsatz.brutto,
        'offen_anzahl': len(eigene),
        'offen_betrag': sum((p.offen for p in eigene), Decimal('0.00')),
        'ueberfaellig_anzahl': len([p for p in eigene if p.ist_ueberfaellig]),
        'ueberfaellig_betrag': sum(
            (p.offen for p in eigene if p.ist_ueberfaellig), Decimal('0.00')),
        'aeltester_verzug': max(
            (p.tage_ueberfaellig for p in eigene
             if p.tage_ueberfaellig is not None), default=0),
    }
