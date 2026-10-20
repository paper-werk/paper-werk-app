"""Gemeinsame Fixtures für alle Tests.

``buero``, ``leitung`` und ``verwaltung`` liefern einen angemeldeten
Client mit den Rechten einer Installation; die Gruppen erhalten sie von
``faktura_rechte`` und ``erfassung_rechte``. Nur ``verwaltung`` ist
Superuser, weil ein Superuser keine Rechte prüft.
"""

from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command

from core import gruppen

PASSWORT = 'geheim12345'


@pytest.fixture(autouse=True)
def schnelles_passwort_hashing(settings):
    """Schnelles Passwort-Hashing für Tests, weil Djangos Hasher bewusst
    langsam ist."""
    settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']


@pytest.fixture(autouse=True)
def kein_pdf_beim_festschreiben(request, monkeypatch):
    """Festschreiben ohne PDF und ohne Archivierung, außer bei ``mit_pdf``.

    Das Rendern kostet etwa 0,25 s je Beleg. Abgeschaltet im Test, nicht
    über eine Setting, damit es im Betrieb keinen Weg ohne Dokument gibt.
    """
    if 'mit_pdf' in request.fixturenames:
        return
    monkeypatch.setattr('faktura.services.festschreiben._dokument_ablegen',
                        lambda beleg: None)


@pytest.fixture
def mit_pdf():
    """Schaltet ``kein_pdf_beim_festschreiben`` ab, für Tests des
    Dokuments."""


@pytest.fixture
def rollenrechte(db):
    """Setzt die Gruppenrechte wie bei einer Installation."""
    call_command('faktura_rechte', stdout=StringIO())
    call_command('erfassung_rechte', stdout=StringIO())


@pytest.fixture
def konto(rollenrechte):
    """Legt ein Konto in einer der paper-werk-Gruppen an.

    ``konto(gruppen.BUERO, 'bea')``: Der Name ist frei, die Gruppe
    bestimmt die Rechte.
    """
    def anlegen(gruppe: str, name: str):
        person = get_user_model().objects.create_user(
            username=name, email=f'{name}@example.invalid',
            password=PASSWORT, is_staff=True)
        person.groups.add(Group.objects.get(name=gruppe))
        return person

    return anlegen


@pytest.fixture
def buero(client, konto):
    """Angemeldet als Büro: Belege, Stammdaten, eigene Stunden."""
    client.force_login(konto(gruppen.BUERO, 'sekretariat'))
    return client


@pytest.fixture
def leitung(client, konto):
    """Angemeldet als Projektleitung: wie Büro, dazu fremde Stunden,
    Einkaufspreise und Eingangsrechnungen."""
    client.force_login(konto(gruppen.PROJEKTLEITUNG, 'leitung'))
    return client


@pytest.fixture
def verwaltung(client, db):
    """Angemeldet als Superuser, nur für Aktionen der Verwaltung: Benutzer,
    Gruppen, Firmendaten anlegen."""
    client.force_login(get_user_model().objects.create_superuser(
        username='verwaltung', email='verwaltung@example.invalid',
        password=PASSWORT))
    return client
