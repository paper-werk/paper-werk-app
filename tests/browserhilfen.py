"""Hilfsfunktionen der Browsertests (Playwright) in ``test_browser_*.py``.

Geprüft wird durch Klicks, nicht durch Suche im HTML, weil Tests, die nur
das Vorhandensein eines Buttons prüften, bei defekter Funktion grün waren.
Beschränkt auf die Abläufe mit Beträgen und Nummern.

Die Daten entstehen über die Services, weil das Ausfüllen der Admin-
Formulare mit Inlines vor allem Django prüfte. Geprüft werden die eigenen
Buttons (Festschreiben, Wiedereröffnen, Dokument) mit eigener Logik.

``DJANGO_ALLOW_ASYNC_UNSAFE`` unten: pytest-playwright führt den Test in
einem Thread mit laufendem Event Loop aus, aus dem Django ORM-Zugriffe
ablehnt. Die Sperre schützt vor blockierenden Aufrufen in Async-Code; der
Test ist durchgehend synchron.

Die Setting steht auf Modulebene und gilt für den ganzen pytest-Prozess,
weil ``live_server`` von pytest-django vor jeder eigenen Fixture auf die
Datenbank zugreift, auch vor einer mit ``autouse``. Verworfen: eine
Fixture (geprüft).

Vertretbar, weil die Anwendung keinen Async-Code hat (kein ``async def``,
``await`` oder ``sync_to_async``) und unter WSGI läuft
(``gunicorn paperwerk.wsgi:application``, ``WSGI_APPLICATION``); ``asgi.py``
ist das unbenutzte Gerüst aus ``startproject``. Mit der ersten asynchronen
View oder einem Wechsel auf ASGI ist diese Stelle zu prüfen.
"""

import os
from datetime import date
from decimal import Decimal

from faktura import services
from faktura.models import (
    Beleg,
    BelegStatus,
    BelegTyp,
)

os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'


PASSWORT = 'geheim12345'


def _entwurf(kunde, typ=BelegTyp.AUFTRAG):
    beleg = services.beleg_anlegen(
        kunde=kunde, typ=typ, betreff='Elektrosanierung Ludwigsplatz 9',
        leistungsdatum=date(2026, 8, 1))
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Gesellenstunde', menge=Decimal('40'),
        einheit='Std', einzelpreis=Decimal('62.00'),
        steuersatz='19.00')
    return beleg


def _anmelden(page, url):
    page.goto(f'{url}/admin/login/')
    page.fill('#id_username', 'chefin')
    page.fill('#id_password', PASSWORT)
    page.click('button[type=submit], input[type=submit]')
    page.wait_for_load_state('networkidle')


def _bestaetigen(page, beschriftung):
    """Klickt die Bestätigung der Rückfrage, Button oder Link.

    Die eigenen Aktionen sind zweistufig: Der erste Klick zeigt eine
    Rückfrage ("Der Beleg bekommt jetzt seine Nummer …"), erst der zweite
    führt aus.

    Die Rückfrage erscheint auf zwei Arten: *Festschreiben* lädt eine
    eigene Seite mit Submit-Button, *Wieder öffnen* lädt per HTMX
    (``hx-get``) einen Dialog mit Link, ohne Änderung der URL. Deshalb wird
    auf Sichtbarkeit gewartet, nicht auf Navigation.
    """
    for rolle in ('button', 'link'):
        ziel = page.get_by_role(rolle, name=beschriftung, exact=True)
        if ziel.count():
            ziel.last.wait_for(state='visible', timeout=5000)
            ziel.last.click()
            page.wait_for_load_state('networkidle')
            return
    raise AssertionError(
        f'Keine Nachfrage mit der Beschriftung {beschriftung!r}; '
        f'die Seite steht auf {page.url}')


def _knopf(page, pfad):
    """Button der Aktion mit diesem Pfad.

    Über den Pfad, weil die Buttons der Unfold-Detailaktionen als Text ihr
    Material-Symbol enthalten (``lock``, ``picture_as_pdf``) und ein
    Text-Selektor von der Symbolschrift abhinge.
    """
    return page.locator(f'a[href*="{pfad}"]').first


def _menue(page, titel):
    """Klappt ein Aktionsmenü auf ("Weitere …").

    Ohne ``get_by_text(exact=True)``, weil der Link neben dem Titel die
    Namen zweier Symbole enthält (``more_horiz``, ``chevron_right``).
    """
    page.locator('a', has_text=titel).first.click()


def _kunde_waehlen(page, suchtext):
    """Wählt im Select2-Feld "Kunde" über die Oberfläche.

    Das Skript reagiert auf ``select2:select``, nicht auf ``change``; ein
    ``select_option`` auf dem versteckten ``<select>`` löste es nicht aus.
    """
    page.locator('#id_kunde + .select2 .select2-selection').click()
    page.locator('.select2-search__field').fill(suchtext)
    page.locator('.select2-results__option', has_text=suchtext).first.click()


def _katalog_waehlen(page, zeile, suchtext, treffer):
    """Sucht in der Katalogzeile über Position ``zeile`` und wählt."""
    page.locator(
        f'#id_positionen-{zeile}-katalog + .select2 .select2-selection').click()
    page.locator('.select2-search__field').fill(suchtext)
    page.locator('.select2-results__option', has_text=treffer).first.click()


def _auftrag_mit_position(projekt, nummer, bezeichnung):
    """Festgeschriebener Auftrag mit einer Position, am Modell wie in den
    Tests der Akten; ``bulk_create``, weil ``save()`` am festgeschriebenen
    Beleg ablehnt."""
    from faktura.models import Belegposition

    auftrag = Beleg.objects.create(
        typ=BelegTyp.AUFTRAG, status=BelegStatus.FESTGESCHRIEBEN,
        nummer=nummer, projekt=projekt)
    return Belegposition.objects.bulk_create([Belegposition(
        beleg=auftrag, position=10, bezeichnung=bezeichnung,
        menge=Decimal('40'), einheit='Stk', einzelpreis=Decimal('145.00'))])[0]


def _beleg_mit_fuenf_positionen(kunde, typ):
    """Fünf Positionen, die erste mit Langtext und Leistungszeitraum, wie
    eine Rechnung aus erfassten Stunden."""
    beleg = _entwurf(kunde, typ=typ)
    beleg.positionen.update(
        langtext='Verteiler setzen, Leitungen prüfen und beschriften',
        leistung_von=date(2026, 7, 27), leistung_bis=date(2026, 7, 31))
    for bezeichnung in ('Unterverteilung', 'Kabel NYM-J 5x2,5',
                        'Anfahrt', 'Entsorgung'):
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung=bezeichnung, menge=Decimal('1'),
            einheit='Stk', einzelpreis=Decimal('1450.00'),
            steuersatz='19.00')
    return beleg
