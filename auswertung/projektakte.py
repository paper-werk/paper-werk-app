"""Projektakte: Belege, Leistung, Zukauf und Ergebnis eines Vorhabens.

Eine eigene, nur lesende Seite. Verworfen: Inlines im ProjektAdmin, weil
zweihundert Erfassungszeilen zweihundert Formularsätze ergäben und
festgeschriebene Belege nicht in ein Eingabeformular gehören. Das Formular
unter Stammdaten pflegt das Vorhaben.

Die URL registriert ``auswertung/apps.py``, weil ProjektAdmin in
``faktura`` liegt und ``faktura`` ``auswertung`` nicht importieren darf.
Der Button im Formular verwendet nur den URL-Namen.

Das Modul rechnet nicht selbst. Die Zahlen kommen aus denselben Funktionen
wie auf Startseite und Rechnung.
"""

import json

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from core.blaettern import nachbarn_im_admin
from erfassung import services as erfassung_services
from erfassung.models import Fremdleistung
from faktura import formate
from faktura import services as faktura_services
from faktura.admin import adresse_im_admin
from faktura.formate import euro, geld
from faktura.models import Projekt

from . import controlling, darstellung, ergebnisse, zuordnung

#: Länge des Aufwandsverlaufs in Monaten, zwölf wie auf der Startseite.
VERLAUFSMONATE = 12

#: Höchstzahl der Fremdleistungen in der Akte; darüber verlinkt sie auf die
#: Liste, damit Vorhaben mit vielen Analysen die Seite nicht überladen.
FREMDLEISTUNGEN_IN_DER_AKTE = 25


def akte(request, pk):
    """Akte eines Vorhabens.

    Zwei Rechte: Mit dem Recht auf Projekte sind Belege, Stunden und Zukauf
    sichtbar; Beträge (Auftragswert, Fakturiertes, Kosten, Ergebnis)
    verlangen zusätzlich ``faktura.view_rechnung``.
    """
    if not request.user.has_perm('faktura.view_projekt'):
        raise PermissionDenied

    projekt = get_object_or_404(Projekt, pk=pk)
    darf_zahlen_sehen = request.user.has_perm('faktura.view_rechnung')

    fremdleistungen = list(
        Fremdleistung.objects
        .filter(projekt=projekt)
        .select_related('rechnung__lieferant', 'abgerechnet_in__beleg')
        .order_by('rechnung__datum', 'pk')
    )
    # Link auf die Rechnung einer Position, nur mit Recht auf Rechnungen,
    # über den Proxy der Rechnungsart.
    for position in fremdleistungen:
        beleg = position.abgerechneter_beleg
        position.rechnungsadresse = (
            adresse_im_admin(beleg) if beleg and darf_zahlen_sehen else '')

    zusammenhang = {
        **admin.site.each_context(request),
        'title': f'Projektakte {projekt.nummer}',
        'hilfe_anker': 'projektakte',
        'projekt': projekt,
        'darf_zahlen_sehen': darf_zahlen_sehen,
        'belege': _belegzeilen(projekt, darf_zahlen_sehen),
        'aufwand_person': erfassung_services.aufwand_je_person(projekt),
        'aufwand_leistung': erfassung_services.aufwand_je_leistung(projekt),
        'fremdleistungen': fremdleistungen[:FREMDLEISTUNGEN_IN_DER_AKTE],
        'weitere_fremdleistungen': max(
            0, len(fremdleistungen) - FREMDLEISTUNGEN_IN_DER_AKTE),
        'formular_url': reverse('admin:faktura_projekt_change', args=[pk]),
        'erfassung_url': (
            f'{reverse("admin:erfassung_erfassungszeile_changelist")}'
            f'?projekt__id__exact={pk}'),
        'fremdleistung_url': (
            f'{reverse("admin:erfassung_fremdleistung_changelist")}'
            f'?projekt__id__exact={pk}'),
        # Zuordnung der Leistung, dieselbe Tabelle wie in Auftrags- und
        # Rechnungsakte, hier mit der Zeile "noch nicht zugeordnet".
        'zuordnung': zuordnung.fuer_projekt(projekt),
        'zuordnung_titel': 'Leistungen',
        'ohne_titel': 'Noch nicht zugeordnet',
        # Jede Zahl verlinkt auf die zugrunde liegenden Belege.
        'kunde_url': (reverse('admin:faktura_kontakt_change',
                              args=[projekt.kunde_id])
                      if projekt.kunde_id else ''),
        'belege_url': (
            f'{reverse("admin:faktura_rechnung_changelist")}'
            f'?projekt__id__exact={pk}'),
    }

    zusammenhang['auftraege'] = _auftraege(projekt) if darf_zahlen_sehen else []

    verlauf = erfassung_services.aufwand_je_monat(
        projekt, monate=VERLAUFSMONATE)
    zusammenhang.update({
        # Verlauf in Stunden, weil er zeigt, wann gearbeitet wurde; ein
        # Verlauf in Euro hätte nur einen Balken je Rechnung.
        'verlauf_saeulen': darstellung.saeulen(
            verlauf, lambda m: m.stunden,
            lambda std: f'{formate.menge(std)} Std',
            lambda std: f'{formate.menge(std)} Std'),
        'verlauf_spitze': darstellung.spitzenmonat(
            verlauf, lambda m: m.stunden,
            lambda std: f'{formate.menge(std)} Std.'),
    })

    if darf_zahlen_sehen:
        zusammenhang.update(_zahlen(projekt))

    # Die Projektliste verlinkt auf das Formular, die Spalte "Akte" auf
    # diese Seite.
    zusammenhang['blaettern'] = nachbarn_im_admin(
        request, Projekt, pk,
        lambda ziel: reverse('projektakte', args=[ziel]))

    return render(request, 'admin/faktura/projektakte.html', zusammenhang)


def _auftraege(projekt) -> list[dict]:
    """Hauptauftrag und Nachträge in der Reihenfolge ihrer Anlage.

    ``projektstaende`` summiert alle Aufträge; die Aufstellung zeigt, woraus
    sich der Auftragswert zusammensetzt. Nachträge ohne zugeordneten
    Hauptauftrag erscheinen als eigene Zeilen, weil sie auch in der Summe
    enthalten sind.
    """
    from faktura.models import BelegStatus, BelegTyp

    auftraege = list(
        projekt.belege
        .filter(typ=BelegTyp.AUFTRAG)
        .exclude(status=BelegStatus.ENTWURF)
        .prefetch_related('positionen')
        .order_by('belegdatum', 'pk')
    )
    if not auftraege:
        return []

    return [
        {
            'beleg': beleg,
            'url': adresse_im_admin(beleg),
            # Die Bezeichnung verlinkt auf die Auftragsakte (Stand), die
            # Nummer auf das Formular (Bearbeiten).
            'akte_url': reverse('auftragsakte', args=[beleg.pk]),
            'bezeichnung': beleg.auftragsbezeichnung,
            'netto': faktura_services.belegsummen(beleg).netto,
        }
        for beleg in auftraege
    ]


def _belegzeilen(projekt, darf_zahlen_sehen: bool) -> list[dict]:
    """Belege des Vorhabens mit Link und Betrag.

    Betrag nur bei Wertbelegen (``ist_wertbeleg``, wie für PDF und Archiv),
    weil etwa Lieferscheine Positionen mit Preis null haben, und nur mit
    dem Recht auf Beträge; ohne das Recht wird er nicht berechnet.

    Entwürfe sind enthalten, anders als in den Summen, mit "Entwurf" an
    Stelle der Nummer und dem Status daneben.

    ``projektakte()`` lädt die Positionen mit prefetch_related; die Summe je
    Beleg braucht keine weitere Abfrage.
    """
    return [
        {
            'beleg': beleg,
            'url': adresse_im_admin(beleg),
            'netto': (faktura_services.belegsummen(beleg).netto
                      if darf_zahlen_sehen and beleg.ist_wertbeleg else None),
        }
        for beleg in faktura_services.projektakte(
            projekt, mit_entwuerfen=True).belege
    ]


def _zahlen(projekt) -> dict:
    """Kennzahlen des Vorhabens mit Hinweis auf unbewertete Stunden.

    Über ``projektergebnis``, damit die Zahlen nach derselben Regel
    entstehen wie auf der Startseite.
    """
    ergebnis = ergebnisse.projektergebnis(projekt)
    if ergebnis is None:
        return {'ergebnis': None, 'kennzahlen': []}

    ertrag = controlling.projektertrag(ergebnis)
    staffel = controlling.projektdeckungsbeitrag(ergebnis)

    return {
        'ergebnis': ergebnis,
        'ertrag': ertrag,
        'staffel': staffel,
        'kostenstruktur': _kostenstruktur(ergebnis),
        'kostenlegende': _kostenlegende(ergebnis),
        'wasserfall': darstellung.wasserfall(staffel),
        # ausschoepfung() kann über 100 liegen; die Balkenbreite wird hier
        # begrenzt, weil Djangos Template-Sprache kein min() hat.
        'balken_fakturiert': min(100, ergebnis.fortschritt),
        'balken_geleistet': (
            None if ergebnis.ausschoepfung is None
            else min(100, ergebnis.ausschoepfung)),
        # Rot, sobald über den Auftragswert hinaus gearbeitet wurde. Die
        # CSS-Klasse wird im Code gesetzt, damit die fachliche Bedingung nur
        # hier steht.
        'ueberzogen_klasse': ('bg-red-600 dark:bg-red-500'
                              if ergebnis.ist_ueberzogen else ''),
        'kennzahlen': [
            {
                'titel': 'Beauftragt',
                'wert': euro(ergebnis.beauftragt),
                'hinweis': 'Summe der Aufträge, netto.',
                'icon': 'assignment_turned_in',
            },
            {
                'titel': 'Fakturiert',
                'wert': euro(ergebnis.fakturiert),
                'hinweis': 'Gestellte Rechnungen, Stornos abgezogen.',
                'icon': 'request_quote',
            },
            {
                'titel': 'Noch abzurechnen',
                'wert': euro(ergebnis.nicht_abgerechnet),
                'hinweis': 'Erfasste Stunden und zugekaufte Leistung ohne '
                           'Beleg.',
                'icon': 'pending_actions',
            },
            {
                'titel': 'Kosten',
                'wert': euro(ergebnis.kosten),
                'hinweis': f'Eigene Arbeit {geld(ergebnis.personalkosten)} €, '
                           f'zugekauft {geld(ergebnis.fremdkosten)} €.',
                'icon': 'payments',
            },
            {
                'titel': 'Ergebnis',
                'wert': euro(ergebnis.ergebnis),
                'hinweis': ('Leistungswert minus Kosten.'
                            if ergebnis.marge is None
                            else f'Leistungswert minus Kosten: '
                                 f'{ergebnis.marge} % Marge.'),
                'icon': 'savings',
            },
            # Der Stundensatz als letzte Karte; ohne erfasste Stunden
            # entfällt sie.
            *([karte] if (karte := _stundenkarte(ertrag)) else []),
        ],
    }


# ══════════════════════════════════════════════════════════════════════════
# Diagramme
# ══════════════════════════════════════════════════════════════════════════


def _kostenstruktur(ergebnis) -> str | None:
    """Aufteilung des Leistungswerts als Ringdiagramm.

    Drei Segmente: eigene Arbeit, Zukauf, Ergebnis. Ein Ringdiagramm passt
    für wenige, deutlich verschieden große Anteile eines Ganzen.

    Bei negativem Ergebnis entfällt das dritte Segment, weil Chart.js einen
    negativen Anteil als positives Segment zeichnet. Der Ring zeigt dann
    nur die Aufteilung der Kosten; die Karte daneben weist darauf hin, dass
    sie den Leistungswert übersteigen.

    ``None`` ohne darstellbare Werte.
    """
    teile = [
        ('Eigene Arbeit', ergebnis.personalkosten, 'var(--pw-reihe-1)'),
        ('Zugekauft', ergebnis.fremdkosten, 'var(--pw-reihe-2)'),
    ]
    if ergebnis.ergebnis > 0:
        teile.append(('Ergebnis', ergebnis.ergebnis, 'var(--pw-reihe-3)'))

    teile = [(titel, betrag, farbe) for titel, betrag, farbe in teile
             if betrag > 0]
    if not teile:
        return None

    return json.dumps({
        'labels': [titel for titel, _b, _f in teile],
        'datasets': [{
            'data': [float(betrag) for _t, betrag, _f in teile],
            'backgroundColor': [farbe for _t, _b, farbe in teile],
            # Abstand zwischen den Segmenten, damit benachbarte Farben auch
            # bei eingeschränktem Farbsehen unterscheidbar bleiben.
            'borderWidth': 2,
            'borderColor': 'transparent',
            'hoverOffset': 6,
        }],
    })


def _kostenlegende(ergebnis) -> list[dict]:
    """Legende neben dem Ring mit Beträgen.

    Der Grünton des dritten Segments liegt auf weißem Grund knapp unter dem
    für Farbe allein nötigen Kontrast. Zulässig ist er, weil die Legende
    jeden Anteil als Zahl nennt.
    """
    gesamt = ergebnis.leistungswert
    zeilen = [
        ('Eigene Arbeit', ergebnis.personalkosten, 'var(--pw-reihe-1)'),
        ('Zugekauft', ergebnis.fremdkosten, 'var(--pw-reihe-2)'),
        ('Ergebnis', ergebnis.ergebnis,
         'var(--pw-reihe-3)' if ergebnis.ergebnis > 0 else 'var(--pw-warnung)'),
    ]
    return [
        {
            'titel': titel,
            'wert': euro(betrag),
            'farbe': farbe,
            'anteil': (int(betrag / gesamt * 100) if gesamt > 0 else None),
        }
        for titel, betrag, farbe in zeilen
    ]


def _stundenkarte(ertrag) -> dict | None:
    """Karte mit dem effektiven Stundensatz, ``None`` ohne erfasste Stunden."""
    if ertrag.erloes_je_stunde is None:
        return None

    hinweis = f'{formate.menge(ertrag.stunden)} Std geleistet, ohne Zukauf gerechnet.'
    if ertrag.faktor is not None:
        hinweis = (f'Faktor {formate.faktor(ertrag.faktor)} auf '
                   f'{geld(ertrag.kosten_je_stunde)} € Kostensatz. '
                   f'{formate.menge(ertrag.stunden)} Std geleistet.')

    return {
        'titel': 'Effektiver Stundensatz',
        'wert': euro(ertrag.erloes_je_stunde),
        'hinweis': hinweis,
        'icon': 'speed',
    }
