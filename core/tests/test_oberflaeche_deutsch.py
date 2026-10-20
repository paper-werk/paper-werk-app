"""Deutsche Texte für Unfold.

Unfold liefert keine deutsche Übersetzung; die Texte stehen in
``locale/de/LC_MESSAGES/django.po`` (Abschnitt "Unfold"). Geprüft wird am
gerenderten HTML, weil eine msgid, die um ein Leerzeichen vom Original
abweicht, im Katalog steht und trotzdem nicht greift.

Nach einem Update von Unfold können Texte hinzukommen oder sich ändern. Das
Vorgehen steht im Kopf des Unfold-Abschnitts der .po-Datei: makemessages
über eine Kopie von Unfold, fehlende Einträge übernehmen,
``compilemessages``. Die Tests decken die sichtbarsten Texte ab, nicht alle.
"""

import pytest
from django.urls import reverse
from django.utils import translation

#: Englische Texte, die auf den geprüften Seiten nicht vorkommen dürfen.
ENGLISCH = ['Welcome back to', 'Return to site', 'Type to search',
            'Apply Filters', 'Search apps and models']


@pytest.mark.django_db
def test_anmeldeseite_ist_deutsch(client):
    seite = client.get(reverse('admin:login')).content.decode()
    assert 'Willkommen bei' in seite
    assert 'Zur Webseite' in seite
    for text in ENGLISCH:
        assert text not in seite, text


@pytest.mark.django_db
def test_liste_ist_deutsch(admin_client):
    """Suchfeld und Filter-Button einer Liste."""
    seite = admin_client.get(
        reverse('admin:faktura_rechnung_changelist')).content.decode()
    assert 'Suchen …' in seite
    for text in ENGLISCH:
        assert text not in seite, text


def test_befehlspalette_und_kuerzel():
    """Texte, die erst per JavaScript erscheinen (Strg+K, Tastenkürzel).

    Geprüft über den Katalog mit der msgid aus Unfolds Template, weil sie im
    gerenderten HTML nicht stehen.
    """
    with translation.override('de'):
        assert translation.gettext('Recent searches') == 'Zuletzt gesucht'
        assert translation.gettext('Nothing matched your search') == 'Keine Treffer'
        assert translation.gettext('Open command tool') == 'Schnellsuche öffnen'
        assert translation.gettext('Light') == 'Hell'
