"""Gemeinsame Filter, Auswahlfelder und Hilfsfunktionen der
Erfassungsmasken."""


from django import forms
from django.contrib import admin
from django.contrib.admin.options import (
    IncorrectLookupParameters,
)
from django.db.models import Q
from django.utils import timezone
from unfold.widgets import UnfoldAdminSelectWidget

from faktura.admin import adresse_im_admin
from faktura.models import (
    Beleg,
    BelegStatus,
    BelegTyp,
    Leistungsart,
    Rechnungsart,
)

from ..formate import personenname
from ..models import (
    Zustand,
)
from ..sortierung import Sortierung
from ..zeitraum import AUSWAHLBAR, zeitraum_grenzen

#: Recht, Zeilen anderer Personen zu sehen und für sie zu erfassen.
RECHT_FREMDE = 'erfassung.fuer_andere_erfassen'


def _rechnungsadresse(beleg) -> str:
    """Admin-URL einer Rechnung über den Proxy ihrer Rechnungsart."""
    return adresse_im_admin(beleg)


def entwuerfe_fuer(projekt):
    """Rechnungsentwürfe als Ziel einer Übernahme: die des Projekts und die
    Sammelrechnungen des Kunden ohne Projekt. Gilt für Stunden und
    Fremdleistungen."""
    if projekt is None:
        return Beleg.objects.none()
    passend = (Q(projekt=projekt)
               | Q(projekt__isnull=True, kunde=projekt.kunde_id))
    return Beleg.objects.filter(
        passend, typ=BelegTyp.RECHNUNG, status=BelegStatus.ENTWURF,
    ).select_related('kunde', 'projekt').order_by('-erstellt_am')


def entwurfsname_von(beleg) -> str:
    """Bezeichnung eines Entwurfs in der Auswahl, mit Art und Projekt oder
    Kunde, damit mehrere Entwürfe und Abschläge unterscheidbar sind."""
    art = beleg.get_rechnungsart_display() if beleg.rechnungsart else ''
    name = (f'{art} (Entwurf {beleg.pk})'
            if art and not beleg.nummer else str(beleg))
    wofuer = beleg.projekt or beleg.kunde
    return f'{name} - {wofuer}' if wofuer else name


#: Einträge "neu anlegen" der Zielauswahl beim Übernehmen: Formularwert,
#: Beschriftung, Rechnungsart. Der leere Wert ist die gewöhnliche Rechnung.
NEUE_ZIELE = (
    ('', 'Neuen Rechnungsentwurf anlegen', Rechnungsart.NORMAL),
    ('neu-abschlag', 'Neue Abschlagsrechnung anlegen (Entwurf)',
     Rechnungsart.ABSCHLAG),
    ('neu-schluss', 'Neue Schlussrechnung anlegen (Entwurf, Abschläge '
                    'werden abgesetzt)', Rechnungsart.SCHLUSS),
)


def ziel_aus_auswahl(wert: str, projekt):
    """Wertet die Zielauswahl aus und gibt ``(entwurf, rechnungsart)``
    zurück; ``entwurf=None`` bedeutet neu anlegen. Ein nicht angebotener
    Entwurf ergibt ``LookupError``."""
    for kennung, _, art in NEUE_ZIELE:
        if wert == kennung:
            return None, art
    entwurf = entwuerfe_fuer(projekt).filter(pk=wert).first() \
        if str(wert).isdigit() else None
    if entwurf is None:
        raise LookupError(wert)
    return entwurf, entwurf.rechnungsart


class ZeitraumFilter(admin.SimpleListFilter):
    """Filter nach Abrechnungszeiträumen wie "letzter Monat" oder "letztes
    Quartal" (``zeitraum.py``).

    Der Zeitraum steht relativ in der URL, damit ein Lesezeichen "letztes
    Quartal" bleibt.
    """

    title = 'Zeitraum'
    parameter_name = 'zeitraum'

    def lookups(self, request, model_admin):
        return [(z.value, z.label) for z in AUSWAHLBAR]

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        try:
            von, bis = zeitraum_grenzen(self.value(), timezone.localdate())
        except ValueError as fehler:
            # Djangos ChangeList ruft queryset() außerhalb ihres try-Blocks
            # auf; nur IncorrectLookupParameters führt auf die ungefilterte
            # Liste, jede andere Ausnahme ergibt eine 500.
            raise IncorrectLookupParameters(fehler) from fehler

        if von is not None:
            queryset = queryset.filter(datum__gte=von)
        if bis is not None:
            queryset = queryset.filter(datum__lt=bis)
        return queryset


class LeistungsartFilter(admin.SimpleListFilter):
    """Filter nach Zeit, Menge oder Pauschale über Auftrags- und
    Katalogposition. Ohne Art gilt eine Position als Menge."""

    title = "Art der Erfassung"
    parameter_name = "leistungsart"

    def lookups(self, request, model_admin):
        return [(a.value, a.label) for a in Leistungsart]

    def queryset(self, request, queryset):
        wert = self.value()
        if not wert:
            return queryset

        passend = (Q(auftragsposition__art=wert)
                   | Q(auftragsposition__isnull=True, leistung__art=wert))
        if wert == Leistungsart.MENGE:
            # Die Vorgabe für eine Auftragsposition ohne Art.
            passend |= Q(auftragsposition__art="")
        return queryset.filter(passend)


class ZustandFilter(admin.SimpleListFilter):
    """Filter nicht abrechenbar, offen, abgerechnet über
    ``ErfassungszeileQuerySet.im_zustand``."""

    title = 'Zustand'
    parameter_name = 'zustand'

    def lookups(self, request, model_admin):
        return [(z.value, z.label) for z in Zustand]

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        try:
            return queryset.im_zustand(self.value())
        except ValueError as fehler:
            raise IncorrectLookupParameters(fehler) from fehler


class SortierFilter(admin.SimpleListFilter):
    """Sortierung als Filtereintrag, ohne zu filtern.

    Sortiert wird in ``ErfassungszeileAdmin.get_ordering``; der Filter
    konsumiert nur den Parameter, weil Djangos ChangeList ``?sortierung=``
    sonst als Feld-Lookup behandelt und ablehnt. Nachteil: keine
    Sortierpfeile an den Spaltenköpfen.
    """

    title = 'Sortierung'
    parameter_name = 'sortierung'

    def lookups(self, request, model_admin):
        return [(s.value, s.label) for s in Sortierung]

    def queryset(self, request, queryset):
        return queryset


class PersonenAuswahl(forms.ModelChoiceField):
    """Auswahl mit vollem Namen ("Anna Weber") an Stelle des Benutzernamens."""

    def label_from_instance(self, benutzer):
        return personenname(benutzer)


class AuftragspositionsAuswahl(forms.ModelChoiceField):
    """Auswahl mit Auftrag und Projekt je Position, damit gleich benannte
    Positionen ("10. Planung Lph 1-4") unterscheidbar sind."""

    def label_from_instance(self, position):
        auftrag = position.beleg
        vorhaben = auftrag.projekt.nummer if auftrag.projekt_id else ""
        kennung = auftrag.nummer or "Entwurf"
        return f"{kennung} · {position} ({vorhaben})" if vorhaben \
            else f"{kennung} · {position}"


class LeistungsAuswahl(UnfoldAdminSelectWidget):
    """Setzt die Erfassungsart als ``data-art`` an jede Option, für Katalog-
    und Auftragspositionen; ``erfassungsart()`` blendet danach die passenden
    Felder ein."""

    def create_option(self, name, value, label, selected, index,
                      subindex=None, attrs=None):
        eintrag = super().create_option(
            name, value, label, selected, index, subindex, attrs)
        # Die leere Option hat keine Instanz.
        grundlage = getattr(value, 'instance', None)
        if grundlage is not None:
            eintrag['attrs']['data-art'] = grundlage.art
        return eintrag


class AuftragspositionsWidget(LeistungsAuswahl):
    """Setzt zusätzlich das Projekt als ``data-projekt`` an jede Option;
    erfassungsauswahl.js schränkt die Liste darauf ein. Als Attribut, weil
    die Optionen ohnehin im HTML stehen und kein JSON-Endpunkt nötig ist."""

    def create_option(self, name, value, label, selected, index,
                      subindex=None, attrs=None):
        eintrag = super().create_option(
            name, value, label, selected, index, subindex, attrs)
        position = getattr(value, 'instance', None)
        if position is not None and position.beleg.projekt_id:
            eintrag['attrs']['data-projekt'] = position.beleg.projekt_id
        return eintrag
