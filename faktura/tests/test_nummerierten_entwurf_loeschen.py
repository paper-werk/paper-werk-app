"""Ein wieder geöffneter Beleg trägt seine Nummer und lässt sich nicht
löschen (``Beleg.delete``), weil der Nummernkreis lückenlos bleibt.

Regression: Der Admin bot das Löschen jedes Entwurfs an; das Bestätigen
endete mit einem Serverfehler.
"""

from decimal import Decimal

import pytest
from django.urls import reverse

from faktura import services
from faktura.models import Beleg, BelegTyp

pytestmark = pytest.mark.django_db


@pytest.fixture
def geoeffneter_auftrag(kunde):
    auftrag = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.AUFTRAG)
    services.position_hinzufuegen(
        beleg=auftrag, bezeichnung='Probe', menge=Decimal('1'),
        einheit='Stk', einzelpreis=Decimal('10.00'), steuersatz='19.00')
    services.beleg_festschreiben(beleg_id=auftrag.pk)
    services.beleg_wiedereroeffnen(beleg_id=auftrag.pk)
    auftrag.refresh_from_db()
    assert auftrag.ist_entwurf and auftrag.nummer
    return auftrag


def test_loeschen_ueber_den_knopf(admin_client, geoeffneter_auftrag):
    admin_client.raise_request_exception = False
    adresse = reverse('admin:faktura_auftrag_delete',
                      args=[geoeffneter_auftrag.pk])

    antwort = admin_client.post(adresse, {'post': 'yes'})

    assert antwort.status_code < 500
    assert Beleg.objects.filter(pk=geoeffneter_auftrag.pk).exists()


def test_kein_knopf_loeschen(admin_client, geoeffneter_auftrag):
    inhalt = admin_client.get(reverse(
        'admin:faktura_auftrag_change',
        args=[geoeffneter_auftrag.pk])).content.decode()

    assert reverse('admin:faktura_auftrag_delete',
                   args=[geoeffneter_auftrag.pk]) not in inhalt


def test_loeschen_ueber_die_liste(admin_client, geoeffneter_auftrag):
    admin_client.raise_request_exception = False

    antwort = admin_client.post(
        reverse('admin:faktura_auftrag_changelist'),
        {'action': 'delete_selected', 'post': 'yes',
         '_selected_action': [str(geoeffneter_auftrag.pk)]})

    assert antwort.status_code < 500
    assert Beleg.objects.filter(pk=geoeffneter_auftrag.pk).exists()
    assert 'trägt die Nummer' in antwort.content.decode()


def test_entwurf_ohne_nummer_laesst_sich_loeschen(admin_client, kunde):
    entwurf = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.AUFTRAG)

    admin_client.post(reverse('admin:faktura_auftrag_delete',
                              args=[entwurf.pk]), {'post': 'yes'})

    assert not Beleg.objects.filter(pk=entwurf.pk).exists()
