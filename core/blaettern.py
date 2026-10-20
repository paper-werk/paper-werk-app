"""Blättern auf Detailseiten: ‹ 7 von 42 › in der Reihenfolge der Liste,
aus der der Datensatz geöffnet wurde.

Die Liste gilt als Schnappschuss: ``changelist_view`` legt die
Primärschlüssel der gesamten gefilterten und sortierten Treffermenge in der
Session ab, je Modell und Filter (``_changelist_filters`` ohne Seitenzahl).
Ein Datensatz, der beim Bearbeiten aus dem Filter fällt (Entwurf wird
versendet), bleibt damit Teil der Reihenfolge. Gelöschte und nicht mehr
sichtbare Datensätze werden beim Blättern übersprungen, neue erscheinen erst
nach erneutem Laden der Liste.

Welcher Schnappschuss gilt: der mit dem Filter aus ``_changelist_filters``,
sonst der zuletzt angelegte desselben Modells, der den Datensatz enthält.
Letzteres deckt Seiten ab, die die Liste ohne Filterparameter verlinkt
(Akten).

Schnittstelle: ``BlaetternMixin`` für ``ModelAdmin`` (Schnappschuss,
Pfeile im Änderungsformular, Listenfilter an Detailaktionen) und
``nachbarn`` für eigene Detailseiten (Akten). Angezeigt über
``admin/blaettern.html``.
"""

from urllib.parse import urlencode

from django.contrib.admin.options import IS_POPUP_VAR
from django.contrib.admin.templatetags.admin_urls import add_preserved_filters
from django.contrib.admin.views.main import PAGE_VAR
from django.http import QueryDict
from django.urls import reverse

#: Session-Schlüssel der Schnappschüsse.
SITZUNG = 'blaettern'
#: Obergrenzen: Primärschlüssel je Liste, Listen je Session.
MAX_EINTRAEGE = 5000
MAX_LISTEN = 10
#: Wie viele Kandidaten je Richtung gegen ``get_queryset`` geprüft werden.
FENSTER = 20


def filterschluessel(abfrage: str) -> str:
    """Querystring einer Liste ohne Seitenzahl. Alle Seiten einer Liste
    teilen einen Schnappschuss."""
    werte = QueryDict(abfrage, mutable=True)
    werte.pop(PAGE_VAR, None)
    return werte.urlencode()


def schnappschuss_ablegen(request, modell, abfrage, filter_: str) -> None:
    """Legt die Primärschlüssel von ``abfrage`` (Reihenfolge der Liste) als
    jüngsten Schnappschuss ab; ein älterer mit gleichem Modell und Filter
    wird ersetzt, über ``MAX_LISTEN`` fällt der älteste heraus."""
    label = modell._meta.label_lower
    pks = [str(pk) for pk in
           abfrage.values_list('pk', flat=True)[:MAX_EINTRAEGE]]
    listen = [e for e in request.session.get(SITZUNG, [])
              if (e['modell'], e['filter']) != (label, filter_)]
    listen.append({'modell': label, 'filter': filter_, 'pks': pks})
    request.session[SITZUNG] = listen[-MAX_LISTEN:]


def _schnappschuss(request, label: str, pk: str):
    listen = [e for e in request.session.get(SITZUNG, [])
              if e['modell'] == label and pk in e['pks']]
    if not listen:
        return None
    gesendet = request.GET.get('_changelist_filters')
    if gesendet is not None:
        filter_ = filterschluessel(gesendet)
        for eintrag in listen:
            if eintrag['filter'] == filter_:
                return eintrag
    return listen[-1]


def _erster_sichtbarer(kandidaten: list[str], sichtbar) -> str | None:
    vorhanden = {str(pk) for pk in
                 sichtbar.filter(pk__in=kandidaten).values_list('pk', flat=True)}
    return next((pk for pk in kandidaten if pk in vorhanden), None)


def nachbarn(request, modell, object_id, sichtbar, adresse) -> dict | None:
    """Vorgänger und Nachfolger von ``object_id`` im geltenden Schnappschuss.

    ``sichtbar``: Queryset der Datensätze, die der Benutzer öffnen darf
    (``get_queryset(request)``). ``adresse(pk)``: URL der Detailseite, an
    die ``_changelist_filters`` des Schnappschusses angehängt wird.

    ``None`` ohne Schnappschuss mit diesem Datensatz.
    """
    pk = str(object_id)
    eintrag = _schnappschuss(request, modell._meta.label_lower, pk)
    if eintrag is None:
        return None
    pks = eintrag['pks']
    stelle = pks.index(pk)

    def verweis(ziel):
        if ziel is None:
            return None
        url = adresse(ziel)
        if eintrag['filter']:
            url += '?' + urlencode({'_changelist_filters': eintrag['filter']})
        return url

    vorher = list(reversed(pks[max(0, stelle - FENSTER):stelle]))
    nachher = pks[stelle + 1:stelle + 1 + FENSTER]
    return {
        'zurueck': verweis(_erster_sichtbarer(vorher, sichtbar)),
        'weiter': verweis(_erster_sichtbarer(nachher, sichtbar)),
        'stelle': stelle + 1,
        'anzahl': len(pks),
    }


def nachbarn_im_admin(request, modell, object_id, adresse) -> dict | None:
    """``nachbarn`` für eigene Detailseiten (Akten): sichtbar ist, was
    ``get_queryset`` des registrierten Admins von ``modell`` liefert."""
    from django.contrib import admin
    sichtbar = admin.site.get_model_admin(modell).get_queryset(request)
    return nachbarn(request, modell, object_id, sichtbar, adresse)


def _mit_filtern(pfad: str, preserved_filters: str, opts) -> str:
    return add_preserved_filters(
        {'preserved_filters': preserved_filters, 'opts': opts}, pfad)


class BlaetternMixin:
    """``ModelAdmin``-Mixin: Schnappschuss in ``changelist_view``, Pfeile
    im Änderungsformular (Kontextvariable ``blaettern``, gerendert in
    ``admin/change_form_object_tools.html``).

    Hängt außerdem ``_changelist_filters`` an die Detailaktionen, damit
    "Sichern" nach einer Aktion in die gefilterte Liste zurückführt.
    """

    def changelist_view(self, request, extra_context=None):
        antwort = super().changelist_view(request, extra_context)  # type: ignore[misc]
        liste = getattr(antwort, 'context_data', {}) or {}
        cl = liste.get('cl')
        if cl is not None and IS_POPUP_VAR not in request.GET:
            schnappschuss_ablegen(request, self.model,  # type: ignore[attr-defined]
                                  cl.queryset,
                                  filterschluessel(request.GET.urlencode()))
        return antwort

    def change_view(self, request, object_id, form_url='', extra_context=None):
        opts = self.model._meta  # type: ignore[attr-defined]
        name = f'{self.admin_site.name}:{opts.app_label}_{opts.model_name}_change'  # type: ignore[attr-defined]
        extra_context = {
            **(extra_context or {}),
            'blaettern': nachbarn(
                request, self.model, object_id,  # type: ignore[attr-defined]
                self.get_queryset(request),  # type: ignore[attr-defined]
                lambda pk: reverse(name, args=[pk])),
        }
        return super().change_view(  # type: ignore[misc]
            request, object_id, form_url, extra_context)

    def render_change_form(self, request, context, *args, **kwargs):
        filter_ = self.get_preserved_filters(request)  # type: ignore[attr-defined]
        if filter_:
            opts = self.model._meta  # type: ignore[attr-defined]
            for aktion in context.get('actions_detail') or []:
                if 'path' in aktion:
                    aktion['path'] = _mit_filtern(aktion['path'], filter_, opts)
                for eintrag in aktion.get('items', []):
                    eintrag['path'] = _mit_filtern(eintrag['path'], filter_, opts)
        return super().render_change_form(  # type: ignore[misc]
            request, context, *args, **kwargs)
