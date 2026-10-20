"""Eigene Seiten mit den Rollen des Betriebs.

Ein Fehler im Template, der nur ohne ein bestimmtes Recht auftritt, fällt als
Superuser nicht auf. Geprüft wird je Rolle: 200 oder 403, keine 500.
"""

from datetime import date, time
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from erfassung import services as erfassung_services
from faktura import services
from faktura.models import BelegTyp, Firma, Kontakt, Projekt


@pytest.fixture
def bestand(db):
    """Kunde mit Projekt, festgeschriebenem Auftrag, Rechnung und einer
    erfassten Stunde, damit jede Seite Inhalt hat."""
    Firma.objects.create(name='Hofmeister e.K.', strasse='Weg 1', plz='84034',
                         ort='Landshut', steuernummer='132/218/40391')
    kunde = Kontakt.anlegen(nummer='K-1', name='Wohnbau Isartal eG',
                          strasse='Ludwigsplatz 9', plz='84034', ort='Landshut')
    projekt = Projekt.objects.create(nummer='2026-001', bezeichnung='Halle',
                                     kunde=kunde)
    auftrag = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.AUFTRAG)
    position = services.position_hinzufuegen(
        beleg=auftrag, bezeichnung='Planung', menge=Decimal('10'),
        einheit='Std', einzelpreis=Decimal('90.00'),
        steuersatz='19.00', art='zeit')
    auftrag = services.beleg_festschreiben(beleg_id=auftrag.pk)
    rechnung = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.RECHNUNG,
                                      leistungsdatum=date(2026, 9, 1))
    services.position_hinzufuegen(
        beleg=rechnung, bezeichnung='Planung', menge=Decimal('4'),
        einheit='Std', einzelpreis=Decimal('90.00'),
        steuersatz='19.00', auftragsposition=position)
    services.beleg_festschreiben(beleg_id=rechnung.pk)
    erfassung_services.zeile_erfassen(
        projekt=projekt, auftragsposition=position,
        benutzer=get_user_model().objects.create_user(username='monteur'),
        von=time(8, 0), bis=time(10, 0), beschreibung='Aufmaß')
    return {'projekt': projekt, 'auftrag': auftrag, 'kunde': kunde}


def _seiten(bestand):
    return {
        'startseite': reverse('admin:index'),
        'projektakte': reverse('projektakte', args=[bestand['projekt'].pk]),
        'auftragsakte': reverse('auftragsakte', args=[bestand['auftrag'].pk]),
        'kundenakte': reverse('kundenakte', args=[bestand['kunde'].pk]),
        'liegengeblieben': reverse('liegengeblieben'),
        'controlling': reverse('controlling'),
    }


@pytest.mark.parametrize('seite', ['startseite', 'projektakte',
                                   'auftragsakte', 'kundenakte',
                                   'liegengeblieben', 'controlling'])
@pytest.mark.parametrize('rolle', ['buero', 'leitung'])
def test_die_rollen_sehen_jede_seite(request, bestand, rolle, seite):
    client = request.getfixturevalue(rolle)

    antwort = client.get(_seiten(bestand)[seite])

    assert antwort.status_code == 200, f'{rolle} auf {seite}: {antwort.status_code}'


@pytest.mark.parametrize('seite', ['projektakte', 'auftragsakte',
                                   'kundenakte', 'liegengeblieben',
                                   'controlling'])
def test_ohne_gruppe_kein_zugang(client, bestand, seite):
    """Ohne Gruppe sind die Seiten gesperrt."""
    client.force_login(get_user_model().objects.create_user(
        username='neu', password='geheim12345', is_staff=True))

    antwort = client.get(_seiten(bestand)[seite])

    assert antwort.status_code == 403


def test_ohne_gruppe_bleibt_die_startseite_offen_aber_ohne_zahlen(client,
                                                                  bestand):
    """Ohne Gruppe lädt die Startseite ohne Zahlen."""
    client.force_login(get_user_model().objects.create_user(
        username='neu', password='geheim12345', is_staff=True))

    antwort = client.get(reverse('admin:index'))

    assert antwort.status_code == 200
    assert antwort.context['zeige_auswertung'] is False


def test_die_auslastung_je_person_sieht_nur_die_leitung(buero, bestand,
                                                        konto):
    """Die Auslastung je Person verlangt ``erfassung.view_kostensatz``."""
    from core import gruppen

    beim_buero = buero.get(reverse('controlling')).context['auslastung']
    buero.force_login(konto(gruppen.PROJEKTLEITUNG, 'chefin'))
    bei_der_leitung = buero.get(reverse('controlling')).context['auslastung']

    assert beim_buero == []
    assert bei_der_leitung, 'die Leitung sieht die erfasste Person'
