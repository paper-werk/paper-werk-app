"""Kontakte mit Rollen: Kunde, Lieferant, Partner, Interessent.

Aus ``Kunde`` wurde ``Kontakt``, aus ``Lieferant`` eine Rolle daran.
Geprüft wird der Import, die Rollenpflicht,
welche Auswahlliste wen anbietet und die Akte.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.apps import apps
from django.forms import modelform_factory
from django.urls import reverse

from erfassung.models import Eingangsrechnung
from erfassung.services import eingangsrechnung_aus_archiv
from faktura.models import Beleg, Kontakt, Projekt, Zahlung


def _lieferant(name='ISARTAL', **felder):
    return Kontakt.objects.create(name=name, ist_kunde=False,
                                  ist_lieferant=True, **felder)


# -- Import aus Archiv und E-Rechnung ----------------------------------------

def _uebertragen(lieferant):
    return eingangsrechnung_aus_archiv(
        paperless_id=4711, lieferant=lieferant, nummer='AL-1',
        datum=date(2026, 9, 1), betrag_netto=Decimal('50.00'))


@pytest.mark.django_db
def test_ein_gleichnamiger_kunde_wird_zusaetzlich_lieferant():
    kunde = Kontakt.objects.create(name='Isartal GmbH')

    rechnung, _ = _uebertragen('ISARTAL GMBH')

    kunde.refresh_from_db()
    assert rechnung.lieferant == kunde
    assert kunde.ist_kunde and kunde.ist_lieferant
    assert Kontakt.objects.count() == 1


@pytest.mark.django_db
def test_ein_unbekannter_lieferant_wird_ein_reiner_lieferant():
    rechnung, _ = _uebertragen('Prüfstelle Süd')

    assert rechnung.lieferant.ist_lieferant
    assert not rechnung.lieferant.ist_kunde, 'sonst stünde er in jeder Kundenauswahl'


# -- Rollen und Auswahllisten ------------------------------------------------

def test_ohne_rolle_lehnt_die_maske_ab(verwaltung):
    antwort = verwaltung.post(reverse('admin:faktura_kontakt_add'), {
        'nummer': 'K-9000', 'name': 'Niemand',
        'zahlungsziel_tage': '14', 'steuerfall': '',
        'zustellweg': 'pdf_mail',
        'adressen-TOTAL_FORMS': '0', 'adressen-INITIAL_FORMS': '0',
        'kontaktwege-TOTAL_FORMS': '0', 'kontaktwege-INITIAL_FORMS': '0',
        'ansprechpartner-TOTAL_FORMS': '0', 'ansprechpartner-INITIAL_FORMS': '0',
    })

    assert antwort.status_code == 200, 'die Maske kommt mit Fehler zurück'
    assert 'mindestens eine' in antwort.content.decode()
    assert not Kontakt.objects.filter(name='Niemand').exists()


@pytest.mark.django_db
@pytest.mark.parametrize('modell', [Beleg, Projekt, Zahlung])
def test_kundenfelder_bieten_nur_kunden_an(modell):
    kunde = Kontakt.objects.create(name='Wohnbau')
    lieferant = _lieferant()

    # Über ein Formular, weil erst ModelForm (und Djangos Autocomplete)
    # limit_choices_to anwenden.
    angeboten = modelform_factory(modell, fields=['kunde'])().fields['kunde'].queryset

    assert kunde in angeboten
    assert lieferant not in angeboten


@pytest.mark.django_db
def test_die_eingangsrechnung_bietet_nur_lieferanten_an():
    kunde = Kontakt.objects.create(name='Wohnbau')
    lieferant = _lieferant()

    angeboten = modelform_factory(
        Eingangsrechnung, fields=['lieferant'])().fields['lieferant'].queryset

    assert lieferant in angeboten
    assert kunde not in angeboten


def test_die_liste_filtert_nach_rolle(buero):
    Kontakt.objects.create(name='Wohnbau Isartal')
    _lieferant('Labor Nord')

    inhalt = buero.get(reverse('admin:faktura_kontakt_changelist'),
                       {'rolle': 'lieferant'}).content.decode()

    assert 'Labor Nord' in inhalt
    assert 'Wohnbau Isartal' not in inhalt


# -- Akte --------------------------------------------------------------------

def _akte_mit_rechnung(client):
    labor = _lieferant('Labor Nord')
    Eingangsrechnung.objects.create(lieferant=labor, nummer='LN-2026-7',
                                    datum=date(2026, 9, 1),
                                    betrag_netto=Decimal('96.00'))
    return client.get(reverse('kundenakte', args=[labor.pk])).content.decode()


_AUSWERTUNG_NOETIG = pytest.mark.skipif(
    not apps.is_installed('auswertung'),
    reason='Die Kundenakte lebt in auswertung; siehe "nur Kern" '
           '(paperwerk/settings/kern.py).')


@_AUSWERTUNG_NOETIG
def test_die_akte_zeigt_der_leitung_die_eingangsrechnungen(leitung):
    inhalt = _akte_mit_rechnung(leitung)

    assert 'Eingangsrechnungen' in inhalt
    assert 'LN-2026-7' in inhalt


@_AUSWERTUNG_NOETIG
def test_das_buero_sieht_keine_eingangsrechnungen(buero):
    """Die Arbeitsgruppe sieht keine Eingangsrechnungen, weil sie
        Einkaufspreise enthalten."""
    inhalt = _akte_mit_rechnung(buero)

    assert 'LN-2026-7' not in inhalt
