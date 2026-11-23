"""Fixtures der Fachszenarien.

Die Fälle liegen außerhalb des Repos; ohne ``PAPERWERK_FACHSZENARIEN``
werden die Tests übersprungen (``fall.UMGEBUNG``).
"""

from datetime import datetime, time
from unittest import mock

import pytest
from django.contrib.auth.models import Permission
from django.utils import timezone

from faktura.models import Firma

from . import fall


@pytest.fixture
def firma(db):
    """Eigene Firma, ohne die das Festschreiben einer Rechnung abbricht."""
    return Firma.objects.create(
        name='Ingenieurbüro Beispiel GmbH', strasse='Musterweg 12',
        plz='80331', ort='München', email='post@example.invalid',
        steuernummer='143/815/47110', ust_id='DE123456789',
        bank='Stadtsparkasse', iban='DE02120300000000202051',
        bic='BYLADEM1001', geschaeftsfuehrung='A. Beispiel',
        registergericht='AG München', handelsregister='HRB 12345')


@pytest.fixture
def buero(client, konto, firma):
    """Angemeldet als Büro mit dem Recht, Angebote festzuschreiben, wie
    ``buero`` im Wurzel-conftest; zusätzlich Projektleitung für
    Eingangsrechnungen und fremde Stunden."""
    from django.contrib.auth.models import Group

    from core import gruppen

    person = konto(gruppen.BUERO, 'buero')
    person.groups.add(Group.objects.get(name=gruppen.PROJEKTLEITUNG))
    person.user_permissions.add(Permission.objects.get(
        content_type__app_label='faktura', codename='angebot_festschreiben'))
    client.force_login(person)
    client.benutzer = person
    return client


class Uhr:
    """Setzt ``django.utils.timezone.now`` auf den Mittag eines Tages.

    ``localdate()`` und ``auto_now_add`` lesen ``timezone.now`` über das
    Modul und folgen dem Patch. Nötig, weil die Fälle über Monate laufen
    und die Erfassung keine künftigen Tage annimmt.
    """

    def __init__(self):
        self._patch = None

    def stellen(self, tag) -> None:
        self.anhalten()
        zeitpunkt = timezone.make_aware(datetime.combine(tag, time(12, 0)))
        self._patch = mock.patch('django.utils.timezone.now',
                                 return_value=zeitpunkt)
        self._patch.start()

    def anhalten(self) -> None:
        if self._patch is not None:
            self._patch.stop()
            self._patch = None


@pytest.fixture
def uhr():
    stellwerk = Uhr()
    yield stellwerk
    stellwerk.anhalten()


def pytest_collection_modifyitems(config, items):
    """Überspringt die Fachszenarien ohne Ordner der Fälle."""
    if fall.dateien():
        return
    grund = pytest.mark.skip(
        reason=f'{fall.UMGEBUNG} nicht gesetzt oder ohne Falldateien')
    for item in items:
        if 'fachszenarien' in str(item.fspath):
            item.add_marker(grund)
