"""Liste "Zu erledigen" auf der Startseite (auswertung/aufgaben.py).

Die Auswahl wird an nachgebauten Ergebnissen geprüft, weil das Modul nicht
rechnet. Ein Test durchläuft den Weg an einer echten Rechnung: Startseite
öffnen, dem Link folgen, die Liste dahinter zeigt diese Rechnung.
"""

import re
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from auswertung import aufgaben
from faktura import services
from faktura.models import Beleg, BelegTyp, Kontakt, Rechnungsart

User = get_user_model()


def _anfrage(person):
    anfrage = RequestFactory().get('/admin/')
    anfrage.user = person
    return anfrage


def _posten(*tage_und_betraege, art=Rechnungsart.NORMAL):
    """Nachgebaute offene Posten mit den Feldern, die ``aufgaben`` liest."""
    ueber = [SimpleNamespace(
        tage_ueberfaellig=tage, offen=Decimal(betrag),
        beleg=SimpleNamespace(pk=i, nummer=f'RE-{i}', typ=BelegTyp.RECHNUNG,
                              rechnungsart=art,
                              empfaenger_kurz=f'Kunde {i}'))
        for i, (tage, betrag) in enumerate(tage_und_betraege, start=1)]
    return SimpleNamespace(
        ueberfaellig=ueber,
        offen_ueberfaellig=sum((Decimal(b) for _, b in tage_und_betraege),
                               Decimal('0.00')))


def _uebersicht(*, ueber=(), ohne_kostensatz=(), minuten=0):
    zeilen = [SimpleNamespace(
        ist_ueberzogen=Decimal(betrag) > 0, ueberschreitung=Decimal(betrag),
        projekt=SimpleNamespace(pk=i, nummer=f'2026-{i:03d}',
                                bezeichnung=f'Vorhaben {i}'))
        for i, betrag in enumerate(ueber, start=1)]
    return SimpleNamespace(zeilen=zeilen, ohne_kostensatz=set(ohne_kostensatz),
                           minuten_ohne_satz=minuten)


@pytest.fixture
def chefin(db):
    return User.objects.create_superuser('chefin', 'c@example.invalid', 'geheim')


@pytest.mark.django_db
class TestDieAuswahl:

    def test_ohne_anlass_keine_aufgabe(self, chefin):
        liste = aufgaben.aufgaben(
            _anfrage(chefin), uebersicht=_uebersicht(), posten=_posten(),
            alt_ueber_90=Decimal('0.00'))

        assert liste == []

    def test_die_ueberfaelligen_nennen_die_aelteste(self, chefin):
        liste = aufgaben.aufgaben(
            _anfrage(chefin), uebersicht=_uebersicht(),
            posten=_posten((12, '100.00'), (40, '250.00')),
            alt_ueber_90=Decimal('0.00'))

        (aufgabe,) = liste
        assert aufgabe.schwere == 'rot'
        assert aufgabe.titel == 'Rechnungen über der Frist'
        assert aufgabe.groesse == '350,00 €'
        assert 'RE-2 an Kunde 2, seit 40 Tagen' in aufgabe.text
        assert aufgabe.url == (reverse('admin:faktura_rechnung_changelist')
                               + '?zahlungsstand=ueberfaellig')

    def test_eine_einzige_fuehrt_in_ihre_maske(self, chefin):
        """Eine einzelne überfällige Rechnung verlinkt auf ihre Maske, auch
        als Abschlagsrechnung, die die Liste "Rechnungen" nicht zeigt."""
        liste = aufgaben.aufgaben(
            _anfrage(chefin), uebersicht=_uebersicht(),
            posten=_posten((30, '9166.57'), art=Rechnungsart.ABSCHLAG),
            alt_ueber_90=Decimal('0.00'))

        (aufgabe,) = liste
        assert aufgabe.titel == 'Forderungen über der Frist'
        assert aufgabe.url == reverse(
            'admin:faktura_abschlagsrechnung_change', args=[1])

    def test_je_rechnungsart_eine_aufgabe_und_die_summe_stimmt(self, chefin):
        posten = _posten((12, '100.00'), (40, '250.00'), (5, '30.00'))
        posten.ueberfaellig[1].beleg.rechnungsart = Rechnungsart.ABSCHLAG
        posten.ueberfaellig[2].beleg.rechnungsart = Rechnungsart.SCHLUSS

        liste = aufgaben.aufgaben(
            _anfrage(chefin), uebersicht=_uebersicht(), posten=posten,
            alt_ueber_90=Decimal('0.00'))

        assert [(a.titel, a.groesse) for a in liste] == [
            ('Rechnungen über der Frist', '100,00 €'),
            ('Abschlagsrechnungen über der Frist', '250,00 €'),
            ('Schlussrechnungen über der Frist', '30,00 €')]
        assert liste[1].url == (
            reverse('admin:faktura_abschlagsrechnung_changelist')
            + '?zahlungsstand=ueberfaellig')

    def test_die_reihenfolge_ist_die_dringlichkeit(self, chefin):
        """Rot vor Gelb vor Blau, unabhängig von der Reihenfolge der Quellen."""
        person = User.objects.create_user('l.perl', first_name='Lukas',
                                          last_name='Perl')
        liste = aufgaben.aufgaben(
            _anfrage(chefin),
            uebersicht=_uebersicht(ueber=['328.50'], ohne_kostensatz=[person.pk],
                                   minuten=5400),
            posten=_posten((3, '10.00')),
            alt_ueber_90=Decimal('6646.00'))

        assert [a.schwere for a in liste] == ['rot', 'gelb', 'gelb', 'blau']
        assert liste[3].text.startswith('Lukas Perl: 90 Std')

    def test_hoechstens_drei_projekte_ueber_dem_auftrag(self, chefin):
        liste = aufgaben.aufgaben(
            _anfrage(chefin),
            uebersicht=_uebersicht(ueber=['10', '400', '0', '50', '20']),
            posten=_posten(), alt_ueber_90=Decimal('0.00'))

        assert [a.titel for a in liste] == [
            '2026-002 über dem Auftrag', '2026-004 über dem Auftrag',
            '2026-005 über dem Auftrag']

    def test_ohne_recht_kein_knopf(self, db):
        """Ohne Recht auf das Ziel erscheint die Aufgabe ohne Link."""
        person = User.objects.create_user('buero', is_staff=True)
        person.user_permissions.add(Permission.objects.get(
            codename='controlling_ansehen'))

        liste = aufgaben.aufgaben(
            _anfrage(person), uebersicht=_uebersicht(ohne_kostensatz=[person.pk],
                                                     minuten=60),
            posten=_posten((5, '1.00')), alt_ueber_90=Decimal('0.00'))

        assert {a.titel: a.url for a in liste} == {
            'Forderungen über der Frist': '', 'Kostensatz fehlt': ''}


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(nummer='K-7000', name='Bauherr Nord',
                           strasse='Weg 1', plz='80331', ort='München')


def _rechnung(kunde, netto='1000.00'):
    beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)
    beleg.leistungsdatum = date(2026, 9, 1)
    beleg.save()
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Arbeit', menge=Decimal('1'),
        einzelpreis=Decimal(netto), steuersatz='19.00')
    return beleg


@pytest.mark.django_db
class TestDerGanzeWeg:

    def test_vom_knopf_zur_ueberfaelligen_rechnung(self, client, chefin, kunde):
        spaet = services.beleg_festschreiben(beleg_id=_rechnung(kunde).pk)
        Beleg.objects.filter(pk=spaet.pk).update(
            faellig_am=timezone.localdate() - timedelta(days=20))
        services.beleg_festschreiben(beleg_id=_rechnung(kunde, '50.00').pk)
        client.force_login(chefin)

        seite = client.get(reverse('admin:index')).content.decode()
        knopf = re.search(
            r'Forderungen über der Frist.*?<a href="([^"]+)"', seite, re.S)

        assert knopf, 'Keine Aufgabe "Forderungen über der Frist" mit Knopf'
        maske = client.get(knopf.group(1))
        assert maske.status_code == 200
        assert maske.context['original'] == spaet

    def test_jede_liste_zeigt_ihre_ueberfaellige(self, client, chefin, kunde):
        """Bei einer überfälligen Abschlagsrechnung zeigt die verlinkte Liste
        diese Rechnung."""
        normal = services.beleg_festschreiben(beleg_id=_rechnung(kunde).pk)
        abschlag = services.beleg_festschreiben(
            beleg_id=_rechnung(kunde, '500.00').pk)
        Beleg.objects.filter(pk=abschlag.pk).update(
            rechnungsart=Rechnungsart.ABSCHLAG)
        Beleg.objects.filter(pk__in=[normal.pk, abschlag.pk]).update(
            faellig_am=timezone.localdate() - timedelta(days=20))
        client.force_login(chefin)

        seite = client.get(reverse('admin:index')).content.decode()

        for titel, erwartet in (('Rechnungen über der Frist', normal),
                                ('Abschlagsrechnungen über der Frist',
                                 abschlag)):
            knopf = re.search(titel + r'.*?<a href="([^"]+)"', seite, re.S)
            assert knopf, f'Keine Aufgabe "{titel}" mit Knopf'
            liste = client.get(knopf.group(1).replace('&amp;', '&'))
            assert [b.pk for b in liste.context['cl'].queryset] == [
                erwartet.pk]

    def test_der_alte_entwurf_fuehrt_zu_den_entwuerfen(self, client, chefin,
                                                       kunde):
        alt = _rechnung(kunde)
        Beleg.objects.filter(pk=alt.pk).update(
            erstellt_am=timezone.now() - timedelta(days=5))
        _rechnung(kunde)  # von heute, noch nicht liegengeblieben
        client.force_login(chefin)

        seite = client.get(reverse('admin:index')).content.decode()
        knopf = re.search(
            r'Rechnungsentwurf liegt.*?<a href="([^"]+)"', seite, re.S)

        assert knopf
        liste = client.get(knopf.group(1).replace('&amp;', '&'))
        # Die Liste zeigt alle Entwürfe, die Aufgabe nur den liegengebliebenen.
        assert alt in list(liste.context['cl'].queryset)
        assert '1.190,00 €' in seite

    def test_ohne_anlass_steht_ein_satz(self, client, chefin):
        client.force_login(chefin)

        seite = client.get(reverse('admin:index')).content.decode()

        assert 'Nichts liegt an' in seite
