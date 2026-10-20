"""Gemeinsame Hilfen für die Admins aller Apps, vor allem Workarounds für
Unfold, Django und den Browser.

Gesammelt in einem Modul, damit bei einem Update von Unfold oder Django an
einer Stelle zu prüfen ist, welche noch nötig sind.
"""

import os

from django import forms
from django.contrib.admin.utils import quote
from django.contrib.staticfiles import finders
from django.core.exceptions import PermissionDenied
from django.forms import Script
from django.shortcuts import redirect
from django.templatetags.static import static
from django.urls import reverse
from simple_history.admin import SimpleHistoryAdmin
from unfold.decorators import action as unfold_action
from unfold.widgets import SELECT_CLASSES

from core.blaettern import BlaetternMixin

#: Unfolds CSS-Klassen für ein Auswahlfeld, das ein Template ohne Widget
#: rendert. Aus Unfold importiert, damit sie bei einem Update aktuell bleiben.
AUSWAHL_KLASSEN = ' '.join(SELECT_CLASSES)


def mit_stand(pfad: str) -> str:
    """URL einer statischen Datei mit mtime als Cache-Buster.

    Ergebnis etwa ``/static/faktura/js/x.js?stand=1755…``. Der
    Entwicklungsserver sendet keine Cache-Header; der Browser verwendet dann
    heuristisch die alte Fassung. Im Betrieb übernimmt das
    ``ManifestStaticFilesStorage``.
    """
    adresse = static(pfad)
    datei = finders.find(pfad)
    if datei is None:              # z. B. wenn noch nicht eingesammelt
        return adresse
    return f'{adresse}?stand={int(os.path.getmtime(datei))}'


def skript_mit_stand(pfad: str) -> Script:
    """``forms.Script`` mit der URL aus ``mit_stand``.

    ``forms.Script`` lässt URLs, die mit ``/`` beginnen, unverändert.
    """
    return Script(mit_stand(pfad))


def jquery_entdoppeln(media, extra: str):
    """Entfernt doppelt eingebundenes jQuery aus ``media``.

    Unfolds Filterformulare wählen ``jquery{extra}.js`` beim Import, Djangos
    Admin bei jedem Request. Unterscheidet sich ``DEBUG`` dazwischen (pytest
    schaltet es um), sind ``jquery.js`` und ``jquery.min.js`` beide
    eingebunden. Die Stammdatenübernahme bindet sich dann ohne Fehlermeldung
    an die falsche Instanz. Behalten wird die Datei, die Django gewählt hätte.

    Das Ergebnis ist ein neues ``Media``-Objekt, weil Media-Objekte zwischen
    Formularen geteilt werden.
    """
    gewaehlt = f'jquery{extra}.js'
    behalten = [
        datei for datei in media._js
        if not ('vendor/jquery/jquery' in getattr(datei, 'path', str(datei))
                and not getattr(datei, 'path', str(datei)).endswith(gewaehlt))
    ]

    bereinigt = forms.Media()
    bereinigt._js_lists = [behalten]
    bereinigt._css_lists = media._css_lists
    return bereinigt


#: Titel des Dropdowns für selten gebrauchte Detailaktionen.
WEITERE = 'Weitere …'


def weitere(*aktionen: str) -> dict:
    """Dropdown ``Weitere …`` für ``actions_detail``.

    Enthält die übergebenen Detailaktionen und danach ``detail_verlauf``.
    Gehört als letzter Eintrag in ``actions_detail``.
    """
    return {'title': WEITERE, 'icon': 'more_horiz',
            'items': [*aktionen, 'detail_verlauf']}


class VerlaufInWeitere:
    """``ModelAdmin``-Mixin: Verlauf als letzter Eintrag in ``Weitere …``.

    Ersetzt Unfolds Button in der Kopfleiste (``SHOW_HISTORY`` ist aus). In
    der Kopfleiste stehen nur Akte, PDF und der nächste Schritt laut Status.
    Admins mit eigenem ``actions_detail`` enden mit ``weitere(...)``;
    ``core/tests/test_weitere.py`` prüft beides für jeden registrierten Admin.
    """

    actions_detail: list = [weitere()]

    @unfold_action(
        description='Verlauf',
        icon='history',
        permissions=['view'],
        url_path='verlauf',
    )  # type: ignore
    def detail_verlauf(self, request, object_id):
        """Redirect auf die History-View (Django oder simple_history).

        Der Pfad ``verlauf`` ist in ``aktion_erst_speichern.js``
        ausgenommen, weil der Verlauf nichts ändert und vorher nicht
        gespeichert werden muss.
        """
        opts = self.model._meta  # type: ignore[attr-defined]
        return redirect(reverse(
            f'{self.admin_site.name}:{opts.app_label}_{opts.model_name}_history',  # type: ignore[attr-defined]
            args=[quote(object_id)]))


class Kopfleiste(BlaetternMixin, VerlaufInWeitere):
    """Kopfleiste jeder Änderungsseite.

    Links die Navigation ‹ 7 von 42 › (``core.blaettern``), dann die
    Detailaktionen, zuletzt „Weitere …“ mit dem Verlauf. Erste Basisklasse
    jedes ``ModelAdmin``; ``core/tests/test_weitere.py`` prüft das.
    """


class GeschichteZumLesen(SimpleHistoryAdmin):
    """Änderungshistorie ohne Revert (GoBD).

    ``SIMPLE_HISTORY_REVERT_DISABLED`` blendet in 3.13 nur den Button aus;
    ein POST auf die History-Form würde den alten Stand trotzdem speichern.
    Deshalb lehnt die View jeden POST ab.
    """

    def history_form_view(self, request, object_id, version_id,
                          extra_context=None):
        if request.method == 'POST':
            raise PermissionDenied
        return super().history_form_view(request, object_id, version_id,
                                         extra_context)
