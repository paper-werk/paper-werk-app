"""Navigation zwischen Akten (``core/blaettern.py``).

Getrennt von ``faktura/tests/test_blaettern.py``, weil die Akten zu
``auswertung`` gehören und der CI-Lauf "nur Kern" ohne diese App läuft.
"""

from urllib.parse import urlparse

import pytest
from django.urls import reverse

from faktura.models import BelegTyp, Kontakt
from faktura.tests.test_blaettern import _beleg


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(nummer='K-4000', name='Muster GmbH',
                           strasse='Hauptstraße 1', plz='10115', ort='Berlin')


@pytest.mark.django_db
class TestBlaetternInDenAkten:
    """Rechnungs- und Kontaktliste verlinken auf die Akte; navigiert wird von
    Akte zu Akte."""

    def test_rechnungsakte(self, admin_client, kunde):
        erste = _beleg(kunde, BelegTyp.RECHNUNG, festschreiben=True)
        zweite = _beleg(kunde, BelegTyp.RECHNUNG, festschreiben=True)
        admin_client.get(f'{reverse("admin:faktura_rechnung_changelist")}'
                         '?o=1')

        pfeile = admin_client.get(
            reverse('rechnungsakte', args=[erste.pk])).context['blaettern']

        assert pfeile['zurueck'] is None
        assert urlparse(pfeile['weiter']).path == reverse(
            'rechnungsakte', args=[zweite.pk])

    def test_kundenakte(self, admin_client, kunde):
        zweiter = Kontakt.anlegen(nummer='K-4001', name='Zweite GmbH',
                                  strasse='Weg 1', plz='10115', ort='Berlin')
        admin_client.get(f'{reverse("admin:faktura_kontakt_changelist")}'
                         '?o=1')

        seite = admin_client.get(reverse('kundenakte', args=[kunde.pk]))

        assert urlparse(seite.context['blaettern']['weiter']).path == \
            reverse('kundenakte', args=[zweiter.pk])
        assert 'data-blaettern' in seite.content.decode()

    def test_auftragsakte(self, admin_client, kunde):
        erster, zweiter = _beleg(kunde), _beleg(kunde)
        admin_client.get(f'{reverse("admin:faktura_auftrag_changelist")}')

        pfeile = admin_client.get(
            reverse('auftragsakte', args=[erster.pk])).context['blaettern']

        assert {urlparse(u).path for u in (pfeile['zurueck'],
                                           pfeile['weiter']) if u} == {
            reverse('auftragsakte', args=[zweiter.pk])}

    def test_projektakte(self, admin_client, kunde):
        from faktura.models import Projekt
        erstes = Projekt.objects.create(nummer='2026-1', bezeichnung='A',
                                        kunde=kunde)
        zweites = Projekt.objects.create(nummer='2026-2', bezeichnung='B',
                                         kunde=kunde)
        admin_client.get(f'{reverse("admin:faktura_projekt_changelist")}')

        seite = admin_client.get(reverse('projektakte', args=[erstes.pk]))

        pfeile = seite.context['blaettern']
        assert {urlparse(u).path for u in (pfeile['zurueck'],
                                           pfeile['weiter']) if u} == {
            reverse('projektakte', args=[zweites.pk])}
        assert 'data-blaettern' in seite.content.decode()
