"""Die Arbeitsgruppe erhält dieselben Detailaktionen wie der Superuser.

Die Detailaktionen (Festschreiben, Stornieren, Mahnen, Wieder öffnen usw.)
prüfen eigene Rechte. Der Superuser sieht immer alle, sodass ein fehlendes
Recht in ``faktura_rechte`` nur als fehlender Button auffiele. Verglichen
werden die Buttons beider Rollen am selben Beleg, als Entwurf und
festgeschrieben.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from core import gruppen
from faktura import services
from faktura.models import (
    BelegTyp,
    Kontakt,
    Rechnungsart,
    proxy_fuer,
)


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(nummer='K-1', name='Wohnbau Isartal eG',
                         strasse='Ludwigsplatz 9', plz='84034', ort='Landshut')


def _beleg(kunde, typ, festschreiben, **felder):
    beleg = services.beleg_anlegen(kunde=kunde, typ=typ,
                                   leistungsdatum=date(2026, 9, 1), **felder)
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Leistung', menge=Decimal('1'),
        einzelpreis=Decimal('100.00'), steuersatz='19.00')
    if festschreiben:
        beleg = services.beleg_festschreiben(beleg_id=beleg.pk)
    return beleg


def _angebotene(person, beleg) -> set[str]:
    modell = proxy_fuer(beleg.typ, getattr(beleg, 'rechnungsart', ''))
    model_admin = admin.site.get_model_admin(modell)
    anfrage = RequestFactory().get('/')
    anfrage.user = person
    return {a.action_name for a in
            model_admin.get_actions_detail(anfrage, str(beleg.pk))}


@pytest.mark.django_db
@pytest.mark.parametrize('typ, felder', [
    (BelegTyp.ANGEBOT, {}),
    (BelegTyp.AUFTRAG, {}),
    (BelegTyp.LIEFERSCHEIN, {}),
    (BelegTyp.RECHNUNG, {}),
    # Ein Abschlag braucht den Zeitraum, auf den er sich bezieht.
    (BelegTyp.RECHNUNG, {'rechnungsart': Rechnungsart.ABSCHLAG,
                         'leistungsdatum_bis': date(2026, 9, 1)}),
])
@pytest.mark.parametrize('festschreiben', [False, True],
                         ids=['entwurf', 'festgeschrieben'])
def test_das_buero_bekommt_dieselben_knoepfe(konto, kunde, typ, felder,
                                              festschreiben):
    beleg = _beleg(kunde, typ, festschreiben, **felder)
    chef = get_user_model().objects.create_superuser(
        username='chef', email='chef@example.invalid', password='x')

    beim_buero = _angebotene(konto(gruppen.BUERO, 'bea'), beleg)
    beim_chef = _angebotene(chef, beleg)

    assert beim_buero == beim_chef, (
        f'{beleg}: dem Büro fehlen {sorted(beim_chef - beim_buero)}')
