"""Hauptauftrag und Nachträge.

Ein Nachtrag ist ein Auftrag mit Verweis auf den Hauptauftrag
(``nachtrag_zu``) und wird wie dieser verhandelt, bestätigt und
abgerechnet. ``projektstaende`` summiert alle Aufträge eines Projekts; der
Verweis zeigt die Zusammensetzung (10.300 EUR Hauptauftrag plus 8.520 EUR
Nachtrag ergeben 18.820 EUR).
"""

from datetime import date
from decimal import Decimal

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError

from faktura import services
from faktura.models import (
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Kontakt,
    Projekt,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def kunde(db):
    return Kontakt.objects.create(nummer='K-5000', name='Stadt Musterstadt')


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(
        nummer='2026-051', bezeichnung='Gewerbegebiet Ost', kunde=kunde)


def _auftrag(projekt, betrag, *, tag=date(2026, 6, 19), haupt=None,
             nummer=None):
    """Festgeschriebener Auftrag über diesen Betrag.

    Am Modell festgeschrieben, weil der Verweis geprüft wird und nicht der
    Service.
    """
    beleg = Beleg.objects.create(
        typ=BelegTyp.AUFTRAG, projekt=projekt,
        nachtrag_zu=haupt)
    Belegposition.objects.create(
        beleg=beleg, position=10, bezeichnung='Leistung',
        menge=Decimal('1'), einheit='pausch', einzelpreis=Decimal(betrag))
    beleg.status = BelegStatus.FESTGESCHRIEBEN
    beleg.nummer = nummer or f'AB-{beleg.pk}'
    beleg.belegdatum = tag
    beleg.save()
    return beleg


class TestDieKlammer:

    def test_der_hauptauftrag_heisst_so(self, projekt):
        haupt = _auftrag(projekt, '10300.00')

        assert not haupt.ist_nachtrag
        assert haupt.nachtragsnummer is None
        assert haupt.auftragsbezeichnung == 'Hauptauftrag'

    def test_nachtraege_werden_der_reihe_nach_gezaehlt(self, projekt):
        haupt = _auftrag(projekt, '10300.00')
        erster = _auftrag(projekt, '8520.00', tag=date(2026, 8, 8),
                          haupt=haupt)
        zweiter = _auftrag(projekt, '2000.00', tag=date(2026, 9, 1),
                           haupt=haupt)

        assert erster.auftragsbezeichnung == '1. Nachtrag'
        assert zweiter.auftragsbezeichnung == '2. Nachtrag'

    def test_die_reihenfolge_kommt_vom_belegdatum(self, projekt):
        """Die Nummer folgt dem Belegdatum: Ein später angelegter, früher
        datierter Nachtrag erhält die 1 (berechnet, nicht gespeichert)."""
        haupt = _auftrag(projekt, '10300.00')
        spaeter = _auftrag(projekt, '1000.00', tag=date(2026, 9, 1),
                           haupt=haupt)
        frueher = _auftrag(projekt, '1000.00', tag=date(2026, 7, 1),
                           haupt=haupt)

        assert frueher.nachtragsnummer == 1
        assert spaeter.nachtragsnummer == 2


class TestWasNichtGeht:
    """Vier Regeln, drei davon lesen einen zweiten Datensatz; deshalb
    clean() und kein CheckConstraint."""

    def test_eine_rechnung_ist_kein_nachtrag(self, projekt):
        haupt = _auftrag(projekt, '10300.00')
        rechnung = Beleg(typ=BelegTyp.RECHNUNG, projekt=projekt,
                         nachtrag_zu=haupt)

        with pytest.raises(ValidationError) as fehler:
            rechnung.full_clean(exclude=['empfaenger'])

        assert 'nachtrag_zu' in fehler.value.error_dict

    def test_kein_nachtrag_zu_sich_selbst(self, projekt):
        auftrag = _auftrag(projekt, '10300.00')
        auftrag.nachtrag_zu = auftrag

        with pytest.raises(ValidationError) as fehler:
            auftrag.full_clean(exclude=['empfaenger'])

        assert 'nachtrag_zu' in fehler.value.error_dict

    def test_kein_nachtrag_zu_einem_angebot(self, projekt):
        angebot = Beleg.objects.create(typ=BelegTyp.ANGEBOT, projekt=projekt)
        nachtrag = Beleg(typ=BelegTyp.AUFTRAG, projekt=projekt,
                         nachtrag_zu=angebot)

        with pytest.raises(ValidationError):
            nachtrag.full_clean(exclude=['empfaenger'])

    def test_keine_kette_von_nachtraegen(self, projekt):
        """Kein Nachtrag zu einem Nachtrag, damit die Summe des Beauftragten
        nicht von der Tiefe einer Kette abhängt."""
        haupt = _auftrag(projekt, '10300.00')
        erster = _auftrag(projekt, '8520.00', haupt=haupt)
        zweiter = Beleg(typ=BelegTyp.AUFTRAG, projekt=projekt,
                        nachtrag_zu=erster)

        with pytest.raises(ValidationError) as fehler:
            zweiter.full_clean(exclude=['empfaenger'])

        assert 'selbst ein Nachtrag' in str(fehler.value)

    def test_nicht_ueber_vorhaben_hinweg(self, projekt, kunde):
        anderes = Projekt.objects.create(
            nummer='2026-099', bezeichnung='Woanders', kunde=kunde)
        haupt = _auftrag(projekt, '10300.00')
        fremder = Beleg(typ=BelegTyp.AUFTRAG, projekt=anderes,
                        nachtrag_zu=haupt)

        with pytest.raises(ValidationError) as fehler:
            fremder.full_clean(exclude=['empfaenger'])

        assert 'verschiedenen Projekten' in str(fehler.value)


class TestWasDerNachtragMitDerSummeMacht:

    def test_er_zaehlt_zum_beauftragten(self, projekt):
        """Der Nachtrag zählt zum Beauftragten."""
        haupt = _auftrag(projekt, '10300.00')
        _auftrag(projekt, '8520.00', tag=date(2026, 8, 8), haupt=haupt)

        stand = services.projektstaende()[0]

        assert stand.beauftragt == Decimal('18820.00')

    def test_und_holt_ein_ueberzogenes_vorhaben_zurueck(self, projekt):
        """Ein bestätigter Nachtrag hebt die Überschreitung des Projekts
        auf."""
        from auswertung import ergebnisse

        haupt = _auftrag(projekt, '10000.00')
        rechnung = Beleg.objects.create(typ=BelegTyp.RECHNUNG,
                                        projekt=projekt)
        Belegposition.objects.create(
            beleg=rechnung, position=10, bezeichnung='Leistung',
            menge=Decimal('1'), einheit='pausch',
            einzelpreis=Decimal('16000.00'))
        rechnung.status = BelegStatus.FESTGESCHRIEBEN
        rechnung.nummer = 'RE-1'
        rechnung.save()

        vorher = ergebnisse.projektergebnis(projekt)
        assert vorher.ueberschreitung == Decimal('6000.00')

        _auftrag(projekt, '5000.00', tag=date(2026, 8, 8), haupt=haupt)

        nachher = ergebnisse.projektergebnis(projekt)
        assert nachher.beauftragt == Decimal('15000.00')
        assert nachher.ueberschreitung == Decimal('1000.00')


class TestWoManDenNachtragSieht:
    """Sichtbarkeit des Nachtrags in Formular und Liste.

    Regression: Das Feld stand im Tab "Status", und in der Liste war der
    Nachtrag nicht vom Auftrag zu unterscheiden.
    """

    @pytest.fixture
    def als_sachbearbeiter(self, client, db):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission

        person = get_user_model().objects.create_user(
            username='sb', password='geheim12345', is_staff=True)
        person.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='faktura'))
        client.force_login(person)
        return client

    # Keine Spalte "Auftrag" in der Liste, weil die Auftragsakte die
    # Zuordnung vollständig zeigt (test_auftragsakte.py, TestDieKlammer).

    @pytest.mark.skipif(
        not apps.is_installed('auswertung'),
        reason='Die Auftragsakte lebt in auswertung; siehe "nur Kern" '
               '(paperwerk/settings/kern.py).')
    def test_die_liste_fuehrt_in_die_akte(self, als_sachbearbeiter, projekt):
        """Die Liste verlinkt auf die Auftragsakte mit der vollständigen
        Zuordnung."""
        from django.urls import reverse

        haupt = _auftrag(projekt, '10300.00', nummer='AB-100')

        inhalt = als_sachbearbeiter.get(reverse(
            'admin:faktura_auftrag_changelist')).content.decode()

        assert reverse('auftragsakte', args=[haupt.pk]) in inhalt

    def test_im_formular_steht_es_oben_und_nicht_im_statusreiter(
            self, als_sachbearbeiter, projekt):
        """Das Feld steht bei Kunde, Projekt und Betreff, weil es eine Eingabe
        ist, nicht im Tab "Status"."""
        from django.urls import reverse

        # Ein Entwurf, weil der festgeschriebene Beleg keine Eingabefelder
        # hat.
        entwurf = Beleg.objects.create(
            typ=BelegTyp.AUFTRAG, projekt=projekt)

        inhalt = als_sachbearbeiter.get(reverse(
            'admin:faktura_auftrag_change',
            args=[entwurf.pk])).content.decode()

        assert 'id_nachtrag_zu' in inhalt
        # Nach Kunde, Projekt und Betreff und vor den Tabs, geprüft an der
        # Reihenfolge im HTML.
        assert (inhalt.index('id_betreff')
                < inhalt.index('id_nachtrag_zu')
                < inhalt.index('id_kopftext'))

    def test_an_einer_rechnung_gibt_es_das_feld_nicht(self, als_sachbearbeiter,
                                                     projekt):
        """Die Rechnung hat kein Feld "Nachtrag zu"."""
        from django.urls import reverse

        rechnung = Beleg.objects.create(typ=BelegTyp.RECHNUNG,
                                        projekt=projekt)

        inhalt = als_sachbearbeiter.get(reverse(
            'admin:faktura_rechnung_change',
            args=[rechnung.pk])).content.decode()

        assert 'id_nachtrag_zu' not in inhalt


class TestEinenNachtragAnlegen:
    """Detailaktion zum Anlegen eines Nachtrags am Hauptauftrag.

    Verworfen: neuen Auftrag anlegen, speichern und den Hauptauftrag im
    Feld "Nachtrag zu" wählen, das beim Anlegen fehlte.
    """

    def test_er_entsteht_ohne_positionen(self, projekt):
        """Der Nachtrag entsteht ohne Positionen, weil er nur Zusätzliches
        enthält und eine Kopie die Auftragssumme verdoppelte."""
        haupt = _auftrag(projekt, '10300.00', nummer='AB-300')

        nachtrag = services.nachtrag_anlegen(beleg_id=haupt.pk)

        assert nachtrag.typ == BelegTyp.AUFTRAG
        assert nachtrag.status == BelegStatus.ENTWURF
        assert nachtrag.nachtrag_zu == haupt
        assert nachtrag.projekt == projekt
        assert nachtrag.positionen.count() == 0
        assert nachtrag.betreff == '1. Nachtrag zu AB-300'

    def test_der_zweite_zaehlt_weiter(self, projekt):
        haupt = _auftrag(projekt, '10300.00', nummer='AB-301')
        services.nachtrag_anlegen(beleg_id=haupt.pk)

        zweiter = services.nachtrag_anlegen(beleg_id=haupt.pk)

        assert zweiter.betreff == '2. Nachtrag zu AB-301'

    def test_nicht_zu_einem_entwurf(self, projekt):
        """Kein Nachtrag zu einem Entwurf, weil dieser selbst geändert
        wird."""
        entwurf = Beleg.objects.create(
            typ=BelegTyp.AUFTRAG, projekt=projekt)

        with pytest.raises(services.FalscherStatus):
            services.nachtrag_anlegen(beleg_id=entwurf.pk)

    def test_nicht_zu_einem_nachtrag(self, projekt):
        haupt = _auftrag(projekt, '10300.00', nummer='AB-302')
        nachtrag = _auftrag(projekt, '500.00', haupt=haupt, nummer='AB-303')

        with pytest.raises(services.FalscherStatus):
            services.nachtrag_anlegen(beleg_id=nachtrag.pk)

    def test_nicht_zu_einer_rechnung(self, projekt):
        rechnung = Beleg.objects.create(typ=BelegTyp.RECHNUNG,
                                        projekt=projekt)

        with pytest.raises(services.FalscherStatus):
            services.nachtrag_anlegen(beleg_id=rechnung.pk)


class TestDerKnopfAmAuftrag:

    @pytest.fixture
    def als_sachbearbeiter(self, client, db):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission

        person = get_user_model().objects.create_user(
            username='sb2', password='geheim12345', is_staff=True)
        person.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='faktura'))
        client.force_login(person)
        return client

    def test_er_steht_am_hauptauftrag(self, als_sachbearbeiter, projekt):
        from django.urls import reverse

        haupt = _auftrag(projekt, '10300.00', nummer='AB-400')

        inhalt = als_sachbearbeiter.get(reverse(
            'admin:faktura_auftrag_change',
            args=[haupt.pk])).content.decode()

        assert 'Nachtrag anlegen' in inhalt

    def test_und_nicht_am_nachtrag_selbst(self, als_sachbearbeiter, projekt):
        """Am Nachtrag kein Button für einen weiteren Nachtrag, weil die
        Hierarchie flach ist."""
        from django.urls import reverse

        haupt = _auftrag(projekt, '10300.00', nummer='AB-401')
        nachtrag = _auftrag(projekt, '500.00', haupt=haupt, nummer='AB-402')

        inhalt = als_sachbearbeiter.get(reverse(
            'admin:faktura_auftrag_change',
            args=[nachtrag.pk])).content.decode()

        assert 'Nachtrag anlegen' not in inhalt

    def test_der_blosse_aufruf_legt_nichts_an(self, als_sachbearbeiter,
                                              projekt):
        """Der GET legt nichts an; erst der POST des Dialogs (Begründung beim
        Festschreiben)."""
        from django.urls import reverse

        haupt = _auftrag(projekt, '10300.00', nummer='AB-403')
        vorher = Beleg.objects.count()

        antwort = als_sachbearbeiter.get(reverse(
            'admin:faktura_auftrag_detail_nachtrag',
            args=[haupt.pk]))

        assert antwort.status_code == 200
        assert 'Nachtrag zu diesem Auftrag anlegen?' in antwort.content.decode()
        assert Beleg.objects.count() == vorher

    def test_mit_bestaetigung_landet_man_im_neuen_entwurf(
            self, als_sachbearbeiter, projekt):
        from django.urls import reverse

        haupt = _auftrag(projekt, '10300.00', nummer='AB-404')

        antwort = als_sachbearbeiter.post(
            reverse('admin:faktura_auftrag_detail_nachtrag',
                    args=[haupt.pk]),
            {'_form_submitted': 'on'},
        )

        nachtrag = Beleg.objects.get(nachtrag_zu=haupt)
        assert antwort.status_code == 302
        assert str(nachtrag.pk) in antwort['Location']
