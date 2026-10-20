"""Auftragsakte: Abrechnungsstand eines Auftrags je Position.

Die Projektakte stellt Erlös und Kosten eines Vorhabens gegenüber. Die
Auftragsakte stellt Beauftragtes und Berechnetes je Auftragsposition
gegenüber und zeigt, was offen ist. Eine Position, die zu 140 Prozent
abgerechnet ist, fällt in der Projektakte nicht auf, weil dort alles in
eine Summe eingeht.

Jede Tabelle beruht auf ``Belegposition.auftragsposition``, also darauf,
welche Auftragsposition eine Rechnungsposition abrechnet.

Aufbau, Route und Rechte wie in der Projektakte; gerechnet wird in
``ergebnisse.auftragsstand``.
"""

from decimal import Decimal

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db.models import DecimalField, Sum
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from core.blaettern import nachbarn_im_admin
from erfassung import services as erfassung_services
from erfassung.models import Erfassungszeile
from faktura import services as faktura_services
from faktura.admin import adresse_im_admin
from faktura.formate import euro
from faktura.models import (
    Abnahmestand,
    Auftrag,
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Rechnungsart,
)

from . import ergebnisse, zuordnung

#: Höchstzahl der einzeln gezeigten Erfassungszeilen; darüber verlinkt die
#: Seite auf die Liste. Ein Auftrag über sechs Wochen hat einige hundert
#: Zeilen (wie bei den Fremdleistungen in der Projektakte).
ZEILEN_IN_DER_AKTE = 15


def akte(request, pk):
    """Akte eines Auftrags.

    Zwei Rechte, wie in der Projektakte: Mit dem Recht auf Aufträge sind
    Positionen, Mengen und erfasste Stunden sichtbar; Beträge verlangen
    zusätzlich ``faktura.view_rechnung``. Wer offene Stunden einer Position
    nachschlägt, braucht keinen Auftragswert.

    Auch Entwürfe haben eine Akte, weil beim Zusammenstellen eines
    Nachtrags der Stand des Hauptauftrags gebraucht wird. Die Zahlen sind am
    Entwurf richtig, aber noch nicht verbindlich.
    """
    if not request.user.has_perm('faktura.view_auftrag'):
        raise PermissionDenied

    auftrag = get_object_or_404(
        Beleg.objects.select_related('projekt', 'kunde'),
        pk=pk, typ=BelegTyp.AUFTRAG,
    )
    darf_zahlen_sehen = request.user.has_perm('faktura.view_rechnung')
    auftraggeber = auftrag.kunde or (auftrag.projekt.kunde
                                     if auftrag.projekt_id else None)

    # Eine Abfrage für alle Positionen. ``Belegposition.abgerechnete_menge``
    # fragt je Aufruf einzeln ab, für eine Tabelle mit zwanzig Positionen
    # also zwanzigmal. ``auftragsstand`` holt alle Mengen auf einmal und
    # liefert die Kennzahlen mit.
    stand = ergebnisse.auftragsstand(auftrag)

    zusammenhang = {
        **admin.site.each_context(request),
        'title': f'Auftragsakte {auftrag.nummer or "Entwurf"}',
        'hilfe_anker': 'auftragsakte',
        'auftrag': auftrag,
        'darf_zahlen_sehen': darf_zahlen_sehen,
        'positionen': _positionszeilen(stand.posten, darf_zahlen_sehen),
        'klammer': _klammer(auftrag),
        'rechnungen': _rechnungen(auftrag, darf_zahlen_sehen),
        'formular_url': adresse_im_admin(auftrag),
        'projektakte_url': (reverse('projektakte', args=[auftrag.projekt_id])
                            if auftrag.projekt_id else ''),
        # Der Auftraggeber steht am Beleg oder am Projekt, beides zugleich
        # schließt der Constraint ``kunde_oder_projekt_nicht_beides`` aus;
        # ein Auftrag zu einem Vorhaben hat deshalb keinen eigenen Kunden.
        # Der Name kommt aus ``empfaenger_kurz`` wie in der Belegliste, was
        # einen von Hand eingegebenen Empfänger einschließt.
        'empfaenger': auftrag.empfaenger_kurz,
        'kunde_url': (reverse('admin:faktura_kontakt_change',
                              args=[auftraggeber.pk])
                      if auftraggeber else ''),
        # Gefiltert über die Auftragsposition, damit die Liste nur die Zeilen
        # dieses Auftrags zeigt und nicht das ganze Vorhaben.
        'erfassung_url': (
            f'{reverse("admin:erfassung_erfassungszeile_changelist")}'
            f'?auftragsposition__beleg__id__exact={pk}'),
    }
    zusammenhang.update(_erfassung(auftrag))
    # Leistungen, dieselbe Tabelle wie in Projekt- und Rechnungsakte. Ohne
    # Zeile "ohne Auftragsposition", die zum Projekt gehört, und ohne Angabe
    # des Auftrags je Position, weil alle Positionen zu diesem Auftrag
    # gehören.
    zusammenhang.update({
        'zuordnung': zuordnung.fuer_auftrag(auftrag),
        'zuordnung_titel': 'Leistungen',
        'ohne_titel': '',
        'zuordnung_ohne_auftrag': True,
    })

    zusammenhang.update(_abnahmen(request, auftrag))

    if darf_zahlen_sehen:
        zusammenhang.update(_zahlen(stand))

    # Die Auftragsliste verlinkt auf das Formular, die Spalte "Akte" auf
    # diese Seite.
    zusammenhang['blaettern'] = nachbarn_im_admin(
        request, Auftrag, pk,
        lambda ziel: reverse('auftragsakte', args=[ziel]))

    return render(request, 'admin/faktura/auftragsakte.html', zusammenhang)


def _abnahmen(request, auftrag) -> dict:
    """Abnahmen des Auftrags, aus denen Schluss- und Teilschlussrechnungen
    entstehen. Erfasst werden sie nur am festgeschriebenen Hauptauftrag."""
    zeilen = [{
        'abnahme': abnahme,
        'url': reverse('admin:faktura_abnahme_change', args=[abnahme.pk]),
        'stand': Abnahmestand(abnahme.stand).label,
        'rechnung': abnahme.rechnungen.order_by('-pk').first(),
    } for abnahme in auftrag.abnahmen.order_by('art', 'pk')]
    for zeile in zeilen:
        zeile['rechnung_url'] = (adresse_im_admin(zeile['rechnung'])
                                 if zeile['rechnung'] else '')
    darf_erfassen = (
        request.user.has_perm('faktura.add_abnahme')
        and auftrag.status == BelegStatus.FESTGESCHRIEBEN
        and not auftrag.nachtrag_zu_id)
    return {
        'abnahmen': zeilen,
        'abnahme_neu_url': (
            f'{reverse("admin:faktura_abnahme_add")}?auftrag={auftrag.pk}'
            if darf_erfassen else ''),
    }


def _positionszeilen(posten, darf_zahlen_sehen: bool) -> list[dict]:
    """Auftragspositionen mit Abrechnungsstand für das Template.

    Die Tabelle stellt je Position beauftragte und abgerechnete Menge
    nebeneinander und zeigt damit, was eine Projektsumme verdeckt: eine
    Position bei 140 Prozent, eine andere bei null.

    Gerechnet wird in ``ergebnisse.Auftragsposten``. Für die Anzeige ist
    ``anteil`` auf 100 begrenzt, damit der Balken in der Zelle bleibt;
    ``prozent`` zeigt den tatsächlichen Wert.
    """
    return [
        {
            'position': einer.position,
            'abgerechnet': einer.abgerechnet,
            'offen': einer.offen,
            'prozent': einer.fortschritt,
            'anteil': min(100, einer.fortschritt),
            'ueberzogen': einer.ist_ueberzogen,
            'optional': einer.optional,
            'netto': einer.netto if darf_zahlen_sehen else None,
        }
        for einer in posten
    ]


def _klammer(auftrag) -> list[dict]:
    """Hauptauftrag und Nachträge, zu denen dieser Auftrag gehört.

    Von jedem Auftrag der Gruppe aus dieselbe Liste; markiert ist der
    aktuelle. Leer bei einem Auftrag ohne Nachträge, weil die Tabelle sonst
    nur den aktuellen Beleg enthielte.
    """
    haupt = auftrag.nachtrag_zu or auftrag
    geschwister = list(
        Beleg.objects
        .filter(typ=BelegTyp.AUFTRAG, nachtrag_zu=haupt)
        .order_by('belegdatum', 'pk')
    )
    if not geschwister:
        return []

    return [
        {
            'beleg': beleg,
            'bezeichnung': beleg.auftragsbezeichnung,
            'url': reverse('auftragsakte', args=[beleg.pk]),
            'ist_dieser': beleg.pk == auftrag.pk,
            'netto': faktura_services.belegsummen(beleg).netto,
        }
        for beleg in [haupt, *geschwister]
    ]


def _rechnungen(auftrag, darf_zahlen_sehen: bool) -> list[dict]:
    """Rechnungen auf diesen Auftrag, je Rechnung eine Zeile.

    Der Betrag ist der Anteil der Rechnung, der auf diesen Auftrag entfällt.
    Eine Rechnung kann Positionen mehrerer Aufträge und Positionen ohne
    Auftragsbezug enthalten; ihre Gesamtsumme wäre hier falsch.

    Entwürfe sind enthalten und am Status erkennbar. Der Text unter der
    Tabelle weist darauf hin, dass sie in den Kennzahlen nicht mitzählen
    (wie in der Projektakte).
    """
    # Über POSITIONSNETTO, weil die Rundung je Position zur Rechenregel
    # gehört und die Spalte mit der Rechnung verglichen wird.
    betrag = Sum(faktura_services.POSITIONSNETTO,
                 output_field=DecimalField(max_digits=14, decimal_places=2))
    zeilen = (
        Belegposition.objects
        .filter(auftragsposition__beleg=auftrag)
        .values('beleg_id')
        .annotate(anteil=betrag)
    )
    anteile = {z['beleg_id']: z['anteil'] or Decimal('0') for z in zeilen}
    if not anteile:
        return []

    belege = (Beleg.objects.filter(pk__in=anteile)
              .order_by('belegdatum', 'pk'))
    return [
        {
            'beleg': beleg,
            'url': adresse_im_admin(beleg),
            # Mit Art und Nummer ("2. Abschlagsrechnung"), weil die Art hier
            # die wesentliche Angabe ist.
            'bezeichnung': beleg.rechnungsbezeichnung or beleg.get_typ_display(),
            'netto': anteile[beleg.pk] if darf_zahlen_sehen else None,
            'zaehlt': _zaehlt_auf_das_kontingent(beleg),
        }
        for beleg in belege
    ]


def _zaehlt_auf_das_kontingent(beleg) -> bool:
    """Ob die Rechnung auf die beauftragte Menge angerechnet wird.

    Dieselbe Bedingung wie in ``services.abgerechnete_mengen``, als Funktion
    gekapselt, damit das Template sie nicht nachbaut.
    """
    return (beleg.status == BelegStatus.FESTGESCHRIEBEN
            and beleg.typ == BelegTyp.RECHNUNG
            and beleg.rechnungsart in Rechnungsart.endgueltige())


def _erfassung(auftrag) -> dict:
    """Auf diesen Auftrag kontierte Stunden, abgerechnet und offen.

    Gefiltert über die Auftragsposition, weil Stunden auf einem Nachtrag
    nicht in die Akte des Hauptauftrags gehören, auch wenn beide zum selben
    Vorhaben zählen. Der offene Teil entspricht der Seite "Nicht
    abgerechnet" für diesen einen Auftrag.
    """
    zeilen = list(
        Erfassungszeile.objects
        .filter(auftragsposition__beleg=auftrag)
        .select_related('benutzer', 'auftragsposition',
                        'abgerechnet_in__beleg')
        .order_by('-datum', '-pk')
    )
    # Offen: auf keiner gültigen Rechnung. Eine Zeile auf einem
    # Rechnungsentwurf zählt als offen, wie in der Karte "Erfasst, nicht
    # berechnet".
    offen = [z for z in zeilen
             if z.abrechenbar and (not z.abgerechnet_in_id
                                   or z.abgerechnet_in.beleg.status
                                   == BelegStatus.ENTWURF)]

    return {
        'zeilen': zeilen[:ZEILEN_IN_DER_AKTE],
        'weitere_zeilen': max(0, len(zeilen) - ZEILEN_IN_DER_AKTE),
        'zeilen_gesamt': len(zeilen),
        'personen': erfassung_services.aufwand_je_person(
            auftrag.projekt, auftrag=auftrag) if auftrag.projekt_id else [],
        'offene_zeilen': len(offen),
    }


def _zahlen(stand) -> dict:
    """Beschriftung der vier Kennzahlen.

    Überschriften, Symbole, Hinweise und Begrenzung der Balkenbreiten; jede
    Zahl kommt aus ``ergebnisse.Auftragsstand``. Der Fortschritt kann über
    100 liegen, der Balken wird hier auf 100 begrenzt, weil Djangos
    Template-Sprache kein ``min()`` hat.
    """
    fortschritt = stand.fortschritt

    return {
        'beauftragt': stand.beauftragt,
        'fortschritt': fortschritt,
        'ist_ueberzogen': stand.ist_ueberzogen,
        'balken_berechnet': min(100, fortschritt or 0),
        # Rot, sobald mehr berechnet als beauftragt ist. Die CSS-Klasse wird
        # im Code gesetzt, damit die fachliche Bedingung nur hier steht (wie
        # in der Projektakte).
        'ueberzogen_klasse': ('bg-red-600 dark:bg-red-500'
                              if stand.ist_ueberzogen else ''),
        'kennzahlen': [
            {
                'titel': 'Beauftragt',
                'wert': euro(stand.beauftragt),
                'hinweis': f'{len(stand.posten)} Positionen, netto.',
                'icon': 'assignment_turned_in',
            },
            {
                'titel': 'Abgerechnet',
                'wert': euro(stand.berechnet),
                'hinweis': ('Festgeschriebene Rechnungen auf diesen Auftrag. '
                            'Abschläge zählen nicht mit.'),
                'icon': 'request_quote',
            },
            {
                'titel': 'Offen',
                'wert': euro(stand.offen),
                'hinweis': 'Was vom Auftrag noch abzurechnen ist.',
                'icon': 'pending_actions',
            },
            {
                'titel': 'Erfasst, nicht berechnet',
                'wert': euro(stand.nicht_berechnet),
                'hinweis': 'Geleistet und auf diesen Auftrag kontiert, aber '
                           'noch auf keiner Rechnung.',
                'icon': 'savings',
            },
        ],
    }


