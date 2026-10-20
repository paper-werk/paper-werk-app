"""Zuordnungstabelle in Projekt-, Auftrags- und Rechnungsakte.

* **Zahlen** (``auswertung.zuordnung``): Stunden je Auftragsposition und
  Zustand, je Person, Fremdleistungen zum Einkaufspreis, offener Betrag,
  abgerechnete Menge.
* **Links:** Die verlinkte Liste zeigt genau die Zeilen, die die Tabelle
  zählt.
* **Rechnungsakte:** Rechte, Aufbau und Aufteilung des Nettobetrags nach
  Herkunft ohne Rest.
"""

from datetime import date, time
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from auswertung import rechnungsakte, zuordnung
from erfassung import services as erfassung_services
from erfassung.models import Eingangsrechnung, Erfassungszeile, Fremdleistung
from faktura import services as faktura_services
from faktura.admin import adresse_im_admin
from faktura.models import (
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Katalogposition,
    Kontakt,
    Leistungsart,
    Projekt,
    Rechnungsart,
)

pytestmark = pytest.mark.django_db

User = get_user_model()


# ── Testdaten ────────────────────────────────────────────────────────────────

@pytest.fixture
def projekt(db):
    kunde = Kontakt.objects.create(nummer='K-8200', name='Gemeinde Beispiel')
    return Projekt.objects.create(
        nummer='2026-061', bezeichnung='Schule Nord', kunde=kunde)


@pytest.fixture
def auftrag(projekt):
    """100 Std Planung zu 95 EUR, 40 Laboranalysen zu 145 EUR."""
    beleg = Beleg.objects.create(typ=BelegTyp.AUFTRAG, projekt=projekt)
    Belegposition.objects.create(
        beleg=beleg, position=10, bezeichnung='Planung', menge=Decimal('100'),
        einheit='Std', einzelpreis=Decimal('95.00'), art=Leistungsart.ZEIT)
    Belegposition.objects.create(
        beleg=beleg, position=20, bezeichnung='Laboranalysen',
        menge=Decimal('40'), einheit='Stk', einzelpreis=Decimal('145.00'),
        art=Leistungsart.MENGE)
    beleg.status = BelegStatus.FESTGESCHRIEBEN
    beleg.nummer = 'AU-2026-0061'
    beleg.belegdatum = date(2026, 7, 1)
    beleg.save()
    return beleg


@pytest.fixture
def planung(auftrag):
    return auftrag.positionen.get(position=10)


@pytest.fixture
def labor(auftrag):
    return auftrag.positionen.get(position=20)


@pytest.fixture
def anna(db):
    return User.objects.create_user(username='anna', first_name='Anna',
                                    last_name='Weber')


@pytest.fixture
def ben(db):
    return User.objects.create_user(username='ben', first_name='Ben',
                                    last_name='Kurz')


@pytest.fixture
def regie(db):
    """Arbeit ohne Auftrag über den Katalog, 68 EUR je Stunde."""
    return Katalogposition.objects.create(
        bezeichnung='Regiestunde', einheit='Std', einzelpreis=Decimal('68.00'),
        art=Leistungsart.ZEIT, kontierbar=True)


def _zeit(projekt, person, *, stunden, position=None, leistung=None,
          abrechenbar=True):
    return erfassung_services.zeile_erfassen(
        projekt=projekt, benutzer=person, beschreibung='Arbeit',
        auftragsposition=position, leistung=leistung,
        datum=date(2026, 8, 10), von=time(8, 0), bis=time(8 + stunden, 0),
        abrechenbar=abrechenbar)


@pytest.fixture
def lieferant(db):
    return Kontakt.objects.create(name='ISARTAL', ist_kunde=False,
                                  ist_lieferant=True)


def _fremd(lieferant, projekt, *, menge, einkauf, position=None,
           weiterberechenbar=True, nummer='AL-1'):
    rechnung, _ = Eingangsrechnung.objects.get_or_create(
        lieferant=lieferant, nummer=nummer,
        defaults={'datum': date(2026, 8, 12), 'betrag_netto': Decimal('0')})
    return Fremdleistung.objects.create(
        rechnung=rechnung, projekt=projekt, bezeichnung='Analyse',
        einheit='Stk', menge=Decimal(menge), einkaufspreis=Decimal(einkauf),
        auftragsposition=position, weiterberechenbar=weiterberechenbar)


def _festschreiben(beleg, nummer):
    """Festschreiben direkt am Modell, wie in test_ergebnisse."""
    beleg.status = BelegStatus.FESTGESCHRIEBEN
    beleg.nummer = nummer
    beleg.belegdatum = date(2026, 8, 20)
    beleg.save()
    return beleg


def _zeile(uebersicht, position):
    return next(z for z in uebersicht.zeilen if z.auftragsposition == position)


def _ohne(uebersicht):
    return next(z for z in uebersicht.zeilen if z.ist_ohne)


# ── Zahlen ───────────────────────────────────────────────────────────────────

class TestAufWelchenRechnungen:
    """Unter "Abgerechnet" stehen die Rechnungen mit Link auf ihre Akte,
    dieselben, die in die Menge eingehen."""

    def test_zwei_rechnungen_auf_einer_position(self, projekt, planung,
                                                anna):
        erste, _ = erfassung_services.in_rechnung_uebernehmen(
            zeilen=[_zeit(projekt, anna, stunden=2, position=planung)])
        _festschreiben(erste, 'RE-2026-0100')
        zweite, _ = erfassung_services.in_rechnung_uebernehmen(
            zeilen=[_zeit(projekt, anna, stunden=3, position=planung)])
        _festschreiben(zweite, 'RE-2026-0101')
        # Ein Entwurf zählt weder bei der Menge noch hier.
        erfassung_services.in_rechnung_uebernehmen(
            zeilen=[_zeit(projekt, anna, stunden=1, position=planung)])

        zeile = _zeile(zuordnung.fuer_auftrag(planung.beleg), planung)

        assert zeile.rechnungen == [
            {'nummer': 'RE-2026-0100',
             'url': reverse('rechnungsakte', args=[erste.pk])},
            {'nummer': 'RE-2026-0101',
             'url': reverse('rechnungsakte', args=[zweite.pk])},
        ]

    def test_steht_in_der_auftragsakte(self, als_chefin, projekt, planung,
                                       anna):
        beleg, _ = erfassung_services.in_rechnung_uebernehmen(
            zeilen=[_zeit(projekt, anna, stunden=2, position=planung)])
        _festschreiben(beleg, 'RE-2026-0100')

        inhalt = als_chefin.get(reverse(
            'auftragsakte', args=[planung.beleg_id])).content.decode()

        assert (f'href="{reverse("rechnungsakte", args=[beleg.pk])}"'
                in inhalt)


class TestDieZeiten:

    def test_je_position_und_zustand(self, projekt, planung, anna, ben):
        """Anna 4 Std offen, Ben 2 Std auf einem Entwurf und 3 Std
        abgerechnet: drei Zustände in einer Zeile."""
        _zeit(projekt, anna, stunden=4, position=planung)
        entwurf = _zeit(projekt, ben, stunden=2, position=planung)
        erfassung_services.in_rechnung_uebernehmen(zeilen=[entwurf])
        fest = _zeit(projekt, ben, stunden=3, position=planung)
        beleg, _ = erfassung_services.in_rechnung_uebernehmen(zeilen=[fest])
        _festschreiben(beleg, 'RE-2026-0100')

        zeile = _zeile(zuordnung.fuer_projekt(projekt), planung)

        assert zeile.umfang.offen.minuten == 240
        assert zeile.umfang.entwurf.minuten == 120
        assert zeile.umfang.abgerechnet.minuten == 180
        assert zeile.umfang.gesamt.minuten == 540
        assert zeile.zeilen == 3

    def test_nicht_abrechenbares_zaehlt_mit_eigenem_zustand(
            self, projekt, planung, anna):
        _zeit(projekt, anna, stunden=2, position=planung, abrechenbar=False)

        zeile = _zeile(zuordnung.fuer_projekt(projekt), planung)

        assert zeile.umfang.nicht_abrechenbar.minuten == 120
        assert not zeile.umfang.offen
        assert zeile.offen_netto == Decimal('0.00')

    def test_je_person_die_laengste_zuerst(self, projekt, planung, anna, ben):
        _zeit(projekt, anna, stunden=2, position=planung)
        _zeit(projekt, ben, stunden=3, position=planung)
        _zeit(projekt, anna, stunden=2, position=planung)

        zeile = _zeile(zuordnung.fuer_projekt(projekt), planung)

        assert [(p.name, p.umfang.minuten) for p in zeile.personen] == [
            ('Anna Weber', 240), ('Ben Kurz', 180)]

    def test_offene_stunden_in_euro_wie_die_rechnung(self, projekt, planung,
                                                     anna):
        """4 Std zu 95 = 380, über die Abrechnungsvorschau und damit mit
        derselben Rundung auf die Viertelstunde wie die Rechnung."""
        _zeit(projekt, anna, stunden=4, position=planung)

        zeile = _zeile(zuordnung.fuer_projekt(projekt), planung)

        assert zeile.offen_netto == Decimal('380.00')


class TestMengenerfassungen:
    """Erfassungen als Menge, nicht nur als Minuten.

    Regression: Die Akte zeigte "1 Zeile, 0:00", während die Rechnung 2 Std
    zu 95 berechnete; die Zeile war eine Menge auf einer Auftragsposition
    ohne Leistungsart.
    """

    @pytest.fixture
    def ohne_art(self, auftrag):
        """Auftragsposition in Std ohne Leistungsart; die Erfassung ist dann
        eine Menge."""
        return Belegposition.objects.bulk_create([Belegposition(
            beleg=auftrag, position=30, bezeichnung='Projektleitung',
            menge=Decimal('120'), einheit='Std', einzelpreis=Decimal('95.00'),
            art='')])[0]

    @pytest.fixture
    def material(self, auftrag):
        return Belegposition.objects.bulk_create([Belegposition(
            beleg=auftrag, position=40, bezeichnung='Kabel',
            menge=Decimal('500'), einheit='m', einzelpreis=Decimal('2.50'),
            art=Leistungsart.MENGE)])[0]

    def test_eine_menge_in_stunden_wird_zur_zeit(self, projekt, ohne_art,
                                                 anna):
        erfassung_services.zeile_erfassen(
            projekt=projekt, benutzer=anna, beschreibung='Leitung',
            auftragsposition=ohne_art, datum=date(2026, 9, 3),
            menge=Decimal('2'))

        zeile = _zeile(zuordnung.fuer_projekt(projekt), ohne_art)

        assert zeile.umfang.gesamt.minuten == 120
        assert str(zeile.umfang.gesamt) == '2:00 Std'
        assert str(zeile.personen[0].umfang) == '2:00 Std'
        # Bewertet wie auf der Rechnung: 2 x 95.
        assert zeile.offen_netto == Decimal('190.00')

    def test_andere_einheiten_bleiben_stehen(self, projekt, material, anna):
        for meter in ('120', '80'):
            erfassung_services.zeile_erfassen(
                projekt=projekt, benutzer=anna, beschreibung='Kabel verlegt',
                auftragsposition=material, datum=date(2026, 9, 3),
                menge=Decimal(meter))

        zeile = _zeile(zuordnung.fuer_projekt(projekt), material)

        assert zeile.umfang.gesamt.minuten == 0
        assert str(zeile.umfang.gesamt) == '200 m'

    def test_zeit_und_menge_nebeneinander(self, projekt, planung, material,
                                          anna):
        """Zeit und Menge werden nicht addiert; Summe und Person zeigen
        beide."""
        _zeit(projekt, anna, stunden=4, position=planung)
        erfassung_services.zeile_erfassen(
            projekt=projekt, benutzer=anna, beschreibung='Kabel verlegt',
            auftragsposition=material, datum=date(2026, 9, 3),
            menge=Decimal('50'))

        uebersicht = zuordnung.fuer_projekt(projekt)

        assert str(uebersicht.umfang.gesamt) == '4:00 Std · 50 m'
        assert str(uebersicht.personen[0].umfang) == '4:00 Std · 50 m'

    def test_die_akte_zeigt_den_umfang(self, als_chefin, projekt, ohne_art,
                                       anna):
        zeit = erfassung_services.zeile_erfassen(
            projekt=projekt, benutzer=anna, beschreibung='Leitung',
            auftragsposition=ohne_art, datum=date(2026, 9, 3),
            menge=Decimal('2'))
        beleg, _ = erfassung_services.in_rechnung_uebernehmen(zeilen=[zeit])

        inhalt = als_chefin.get(
            reverse('rechnungsakte', args=[beleg.pk])).content.decode()

        assert '2:00 Std' in inhalt
        assert '0:00' not in inhalt


class TestDieFremdleistungen:

    def test_im_einkauf_je_zustand(self, projekt, labor, lieferant):
        _fremd(lieferant, projekt, menge='10', einkauf='96.00', position=labor)
        _fremd(lieferant, projekt, menge='2', einkauf='96.00', position=labor,
               weiterberechenbar=False)
        abgerechnet = _fremd(lieferant, projekt, menge='5', einkauf='96.00',
                             position=labor)
        beleg, _ = erfassung_services.in_rechnung_uebernehmen(
            zeilen=[], fremdleistungen=[abgerechnet])
        _festschreiben(beleg, 'RE-2026-0101')

        zeile = _zeile(zuordnung.fuer_projekt(projekt), labor)

        assert zeile.fremdleistungen == 3
        assert zeile.einkauf.offen == Decimal('960.00')
        assert zeile.einkauf.nicht_abrechenbar == Decimal('192.00')
        assert zeile.einkauf.abgerechnet == Decimal('480.00')
        assert zeile.einkauf.gesamt == Decimal('1632.00')

    def test_offen_ist_stunden_plus_einkauf(self, projekt, planung, labor,
                                            anna, lieferant):
        """Offen sind Stunden zum Verkaufswert plus Fremdleistung zum
        Einkaufspreis."""
        _zeit(projekt, anna, stunden=4, position=planung)
        _fremd(lieferant, projekt, menge='10', einkauf='96.00', position=labor)

        uebersicht = zuordnung.fuer_projekt(projekt)

        assert _zeile(uebersicht, planung).offen_gesamt == Decimal('380.00')
        assert _zeile(uebersicht, labor).offen_gesamt == Decimal('960.00')
        assert uebersicht.offen_gesamt == Decimal('1340.00')


class TestOhneAuftragsposition:
    """Zeile für Leistung ohne Auftragsposition."""

    def test_im_projekt_steht_sie_unten(self, projekt, auftrag, anna, regie,
                                        lieferant):
        _zeit(projekt, anna, stunden=2, leistung=regie)
        _fremd(lieferant, projekt, menge='1', einkauf='180.00')

        uebersicht = zuordnung.fuer_projekt(projekt)
        ohne = uebersicht.zeilen[-1]

        assert ohne.ist_ohne
        assert ohne.umfang.offen.minuten == 120
        assert ohne.einkauf.offen == Decimal('180.00')
        # 2 Std Regie zu 68 + 180 Einkauf
        assert ohne.offen_gesamt == Decimal('316.00')

    def test_im_auftrag_gibt_es_sie_nicht(self, projekt, auftrag, anna, regie):
        """In der Auftragsakte fehlt die Zeile, weil Leistung ohne
        Auftragsposition zum Projekt gehört."""
        _zeit(projekt, anna, stunden=2, leistung=regie)

        uebersicht = zuordnung.fuer_auftrag(auftrag)

        assert not any(z.ist_ohne for z in uebersicht.zeilen)
        assert not uebersicht.umfang.gesamt

    def test_jede_auftragsposition_steht_da_auch_ohne_erfassung(
            self, projekt, planung, labor):
        uebersicht = zuordnung.fuer_projekt(projekt)

        assert [z.auftragsposition for z in uebersicht.zeilen[:2]] == [
            planung, labor]
        assert uebersicht.ist_leer


class TestWasAbgerechnetIst:

    def test_menge_und_betrag_ueber_die_festgeschriebenen(self, projekt,
                                                          planung):
        rechnung = Beleg.objects.create(typ=BelegTyp.RECHNUNG, projekt=projekt)
        Belegposition.objects.create(
            beleg=rechnung, position=10, bezeichnung='Planung',
            menge=Decimal('6'), einheit='Std', einzelpreis=Decimal('95.00'),
            auftragsposition=planung)
        _festschreiben(rechnung, 'RE-2026-0102')

        zeile = _zeile(zuordnung.fuer_projekt(projekt), planung)

        assert zeile.abgerechnete_menge == Decimal('6')
        assert zeile.berechnet_netto == Decimal('570.00')
        assert not zeile.ist_ueberzogen

    def test_ein_abschlag_zaehlt_nicht(self, projekt, planung):
        """Dieselbe Regel wie in der Auftragsakte (R-008)."""
        abschlag = Beleg.objects.create(
            typ=BelegTyp.RECHNUNG, projekt=projekt,
            rechnungsart=Rechnungsart.ABSCHLAG)
        Belegposition.objects.create(
            beleg=abschlag, position=10, bezeichnung='Planung',
            menge=Decimal('6'), einheit='Std', einzelpreis=Decimal('95.00'),
            auftragsposition=planung)
        _festschreiben(abschlag, 'RE-2026-0103')

        zeile = _zeile(zuordnung.fuer_projekt(projekt), planung)

        assert zeile.abgerechnete_menge == Decimal('0')
        assert zeile.berechnet_netto == Decimal('0.00')

    def test_mehr_als_beauftragt_faellt_auf(self, projekt, labor):
        rechnung = Beleg.objects.create(typ=BelegTyp.RECHNUNG, projekt=projekt)
        Belegposition.objects.create(
            beleg=rechnung, position=10, bezeichnung='Analysen',
            menge=Decimal('42'), einheit='Stk', einzelpreis=Decimal('145.00'),
            auftragsposition=labor)
        _festschreiben(rechnung, 'RE-2026-0104')

        assert _zeile(zuordnung.fuer_projekt(projekt), labor).ist_ueberzogen


class TestDieRechnung:

    @pytest.fixture
    def rechnung(self, projekt, planung, labor, anna, ben, regie, lieferant):
        """Rechnung mit Planung zweier Personen, Labor als Fremdleistung,
        Regie ohne Auftrag und einer Position von Hand."""
        zeiten = [_zeit(projekt, anna, stunden=4, position=planung),
                  _zeit(projekt, ben, stunden=2, position=planung),
                  _zeit(projekt, anna, stunden=1, leistung=regie)]
        fremd = [_fremd(lieferant, projekt, menge='10', einkauf='96.00',
                        position=labor)]
        beleg, _ = erfassung_services.in_rechnung_uebernehmen(
            zeilen=Erfassungszeile.objects.filter(pk__in=[z.pk for z in zeiten]),
            fremdleistungen=fremd)
        faktura_services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Fahrtkosten pauschal',
            menge=Decimal('1'), einheit='pausch',
            einzelpreis=Decimal('50.00'), steuersatz='19.00')
        return beleg

    def test_nur_was_auf_dieser_rechnung_steht(self, rechnung, projekt,
                                               planung, anna):
        """Eine spätere Zeit auf derselben Position erscheint nicht."""
        _zeit(projekt, anna, stunden=3, position=planung)

        zeile = _zeile(zuordnung.fuer_rechnung(rechnung), planung)

        assert zeile.umfang.gesamt.minuten == 360
        assert [p.name for p in zeile.personen] == ['Anna Weber', 'Ben Kurz']

    def test_der_anteil_dieser_rechnung_je_position(self, rechnung, planung,
                                                    labor):
        uebersicht = zuordnung.fuer_rechnung(rechnung)

        # 6 Std zu 95, 10 Analysen zum Vertragspreis 145
        assert _zeile(uebersicht, planung).auf_dieser_rechnung \
            == Decimal('570.00')
        assert _zeile(uebersicht, labor).auf_dieser_rechnung \
            == Decimal('1450.00')
        # Regie 1 Std zu 68 und Fahrtkosten ohne Auftragsbezug.
        assert _ohne(uebersicht).auf_dieser_rechnung == Decimal('118.00')
        assert _ohne(uebersicht).umfang.gesamt.minuten == 60

    def test_die_anteile_ergeben_die_rechnung(self, rechnung):
        uebersicht = zuordnung.fuer_rechnung(rechnung)

        assert uebersicht.auf_dieser_rechnung \
            == faktura_services.belegsummen(rechnung).netto

    def test_die_herkunft_geht_ohne_rest_auf(self, rechnung):
        """Zeiten, Fremdleistungen und "ohne Nachweis" ergeben zusammen den
        Nettobetrag auf den Cent."""
        teile = rechnungsakte.herkunft(rechnung)

        # 570 Planung + 68 Regie
        assert teile['zeiten'] == Decimal('638.00')
        assert teile['fremd'] == Decimal('1450.00')
        assert teile['einkauf'] == Decimal('960.00')
        assert teile['ohne'] == Decimal('50.00')
        assert teile['zeiten'] + teile['fremd'] + teile['ohne'] \
            == faktura_services.belegsummen(rechnung).netto

    def test_personen_ueber_die_ganze_rechnung(self, rechnung):
        personen = zuordnung.fuer_rechnung(rechnung).personen

        assert [(p.name, p.umfang.minuten) for p in personen] == [
            ('Anna Weber', 300), ('Ben Kurz', 120)]


# ── Links ────────────────────────────────────────────────────────────────────

@pytest.fixture
def als_chefin(client, db):
    """Konto mit allen Rechten der Akten, ohne Superuser."""
    person = User.objects.create_user(
        username='chefin', password='geheim12345', is_staff=True)
    person.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='erfassung'))
    person.user_permissions.add(*Permission.objects.filter(
        codename__in=['view_auftrag', 'view_rechnung', 'view_projekt',
                      'view_abschlagsrechnung', 'change_rechnung',
                      'view_schlussrechnung']))
    client.force_login(person)
    return client


def _anzahl(client, adresse) -> int:
    antwort = client.get(adresse)
    assert antwort.status_code == 200, adresse
    return antwort.context['cl'].result_count


class TestDieVerweise:
    """Die verlinkte Liste zeigt genau die gezählten Zeilen."""

    def test_zeiten_einer_position(self, als_chefin, projekt, planung, labor,
                                   anna, regie):
        _zeit(projekt, anna, stunden=2, position=planung)
        _zeit(projekt, anna, stunden=1, position=planung)
        _zeit(projekt, anna, stunden=1, leistung=regie)

        uebersicht = zuordnung.fuer_projekt(projekt)

        assert _anzahl(als_chefin, _zeile(uebersicht, planung).zeiten_url) == 2
        assert _anzahl(als_chefin, _ohne(uebersicht).zeiten_url) == 1

    def test_nur_die_offenen(self, als_chefin, projekt, planung, anna):
        _zeit(projekt, anna, stunden=2, position=planung)
        abgerechnet = _zeit(projekt, anna, stunden=1, position=planung)
        erfassung_services.in_rechnung_uebernehmen(zeilen=[abgerechnet])

        zeile = _zeile(zuordnung.fuer_projekt(projekt), planung)

        assert _anzahl(als_chefin, zeile.zeiten_offen_url) == 1

    def test_fremdleistungen_mit_und_ohne_position(self, als_chefin, projekt,
                                                   labor, lieferant):
        _fremd(lieferant, projekt, menge='1', einkauf='10.00', position=labor)
        _fremd(lieferant, projekt, menge='1', einkauf='10.00', position=labor)
        _fremd(lieferant, projekt, menge='1', einkauf='10.00')

        uebersicht = zuordnung.fuer_projekt(projekt)

        assert _anzahl(als_chefin, _zeile(uebersicht, labor).fremd_url) == 2
        assert _anzahl(als_chefin, _ohne(uebersicht).fremd_url) == 1

    def test_die_zeiten_einer_rechnung(self, als_chefin, projekt, planung,
                                       anna):
        auf_der_rechnung = _zeit(projekt, anna, stunden=2, position=planung)
        _zeit(projekt, anna, stunden=1, position=planung)
        beleg, _ = erfassung_services.in_rechnung_uebernehmen(
            zeilen=[auf_der_rechnung])

        zeile = _zeile(zuordnung.fuer_rechnung(beleg), planung)

        assert _anzahl(als_chefin, zeile.zeiten_url) == 1

    def test_der_zustandsfilter_der_fremdleistungen(self, als_chefin, projekt,
                                                    lieferant):
        _fremd(lieferant, projekt, menge='1', einkauf='10.00')
        _fremd(lieferant, projekt, menge='1', einkauf='10.00',
               weiterberechenbar=False)
        liste = reverse('admin:erfassung_fremdleistung_changelist')

        assert _anzahl(als_chefin, f'{liste}?zustand=offen') == 1
        assert _anzahl(als_chefin, f'{liste}?zustand=nicht_abrechenbar') == 1

    def test_die_liste_der_fremdleistungen_nennt_die_summe(
            self, als_chefin, projekt, lieferant):
        _fremd(lieferant, projekt, menge='2', einkauf='96.00')

        inhalt = als_chefin.get(
            reverse('admin:erfassung_fremdleistung_changelist')
        ).content.decode()

        assert '192,00' in inhalt


# ── Akten ────────────────────────────────────────────────────────────────────

class TestDieRechnungsakte:

    def test_sie_laeuft_und_zeigt_die_uebersicht(self, als_chefin, projekt,
                                                 planung, anna):
        zeit = _zeit(projekt, anna, stunden=2, position=planung)
        beleg, _ = erfassung_services.in_rechnung_uebernehmen(zeilen=[zeit])

        inhalt = als_chefin.get(
            reverse('rechnungsakte', args=[beleg.pk])).content.decode()

        assert 'Fakturierte Positionen' in inhalt
        assert 'Fakturierte Erfassungen' in inhalt
        assert 'Anna Weber' in inhalt
        assert 'Aus Erfassungen' in inhalt
        assert '190,00' in inhalt

    @pytest.mark.parametrize('art, liste', [
        (Rechnungsart.NORMAL, 'admin:faktura_rechnung_changelist'),
        (Rechnungsart.ABSCHLAG, 'admin:faktura_abschlagsrechnung_changelist'),
        (Rechnungsart.SCHLUSS, 'admin:faktura_schlussrechnung_changelist'),
    ])
    def test_der_klick_in_der_liste_oeffnet_die_akte(self, als_chefin,
                                                     projekt, art, liste):
        """Die Rechnungsliste verlinkt auf die Akte; zum Formular führt
        "Rechnung bearbeiten", wie bei den Kunden."""
        beleg = Beleg.objects.create(typ=BelegTyp.RECHNUNG, projekt=projekt,
                                     rechnungsart=art)

        inhalt = als_chefin.get(reverse(liste)).content.decode()

        assert reverse('rechnungsakte', args=[beleg.pk]) in inhalt
        assert adresse_im_admin(beleg) not in inhalt

    def test_ohne_rechnungsrecht_nicht(self, client, projekt):
        beleg = Beleg.objects.create(typ=BelegTyp.RECHNUNG, projekt=projekt)
        person = User.objects.create_user(
            username='mo', password='geheim12345', is_staff=True)
        person.user_permissions.add(
            Permission.objects.get(codename='view_auftrag'))
        client.force_login(person)

        antwort = client.get(reverse('rechnungsakte', args=[beleg.pk]))

        assert antwort.status_code == 403

    def test_ein_auftrag_ist_keine_rechnung(self, als_chefin, auftrag):
        antwort = als_chefin.get(reverse('rechnungsakte', args=[auftrag.pk]))

        assert antwort.status_code == 404

    def test_der_knopf_am_formular_fuehrt_hinein(self, als_chefin, projekt):
        """Der Button im Formular führt in die Akte, auch bei der
        Abschlagsrechnung mit eigener URL."""
        abschlag = Beleg.objects.create(
            typ=BelegTyp.RECHNUNG, projekt=projekt,
            rechnungsart=Rechnungsart.ABSCHLAG)
        formular = adresse_im_admin(abschlag)
        ziel = reverse('rechnungsakte', args=[abschlag.pk])

        antwort = als_chefin.get(formular.replace('/change/', '/akte/'))

        assert antwort.status_code == 302
        assert antwort.url == ziel
        assert als_chefin.get(ziel).status_code == 200


class TestDieAnderenAkten:

    def test_die_projektakte_nennt_das_nicht_zugeordnete(
            self, als_chefin, projekt, auftrag, anna, regie):
        _zeit(projekt, anna, stunden=2, leistung=regie)

        inhalt = als_chefin.get(
            reverse('projektakte', args=[projekt.pk])).content.decode()

        assert 'Leistungen' in inhalt
        assert 'Noch nicht zugeordnet' in inhalt

    def test_die_auftragsakte_zeigt_die_fremdleistungen(
            self, als_chefin, projekt, labor, lieferant):
        _fremd(lieferant, projekt, menge='10', einkauf='96.00', position=labor)

        inhalt = als_chefin.get(
            reverse('auftragsakte', args=[labor.beleg_id])).content.decode()

        assert 'Leistungen' in inhalt
        assert '1 Position' in inhalt
        assert '960,00' in inhalt

    def test_die_auftragsakte_verweist_nicht_auf_sich_selbst(
            self, als_chefin, projekt, labor, lieferant):
        """In der Auftragsakte fehlt der Link auf den eigenen Auftrag; in
        der Projektakte bleibt er, weil dort mehrere Aufträge stehen."""
        _fremd(lieferant, projekt, menge='10', einkauf='96.00', position=labor)
        eigene = reverse('auftragsakte', args=[labor.beleg_id])

        auftragsakte = als_chefin.get(eigene).content.decode()
        projektakte = als_chefin.get(
            reverse('projektakte', args=[projekt.pk])).content.decode()

        assert f'href="{eigene}"' not in auftragsakte
        assert f'href="{eigene}"' in projektakte

    def test_ohne_rechnungsrecht_keine_betraege(self, client, projekt, labor,
                                                lieferant):
        """Ohne Recht auf Rechnungen erscheinen Fremdleistungen ohne
        Beträge."""
        _fremd(lieferant, projekt, menge='10', einkauf='96.00', position=labor)
        person = User.objects.create_user(
            username='mo', password='geheim12345', is_staff=True)
        person.user_permissions.add(
            Permission.objects.get(codename='view_auftrag'))
        client.force_login(person)

        inhalt = client.get(
            reverse('auftragsakte', args=[labor.beleg_id])).content.decode()

        assert 'Leistungen' in inhalt
        assert '960,00' not in inhalt


# ── Kopf der Rechnungsakte ───────────────────────────────────────────────────

class TestDerKopfDerRechnungsakte:
    """Nummer, Belegstatus und Zahlungsstatus in einer Zeile, mit denselben
    Begriffen wie die Liste (R-176), geprüft am HTML."""

    @pytest.fixture
    def rechnung(self, projekt):
        from datetime import timedelta

        from django.utils import timezone

        from faktura.models import Beleg, BelegTyp

        beleg = faktura_services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG, betreff='Kanal Süd')
        beleg.leistungsdatum = date(2026, 8, 20)
        beleg.save()
        faktura_services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Planung', menge=Decimal('1'),
            einzelpreis=Decimal('1000.00'), steuersatz='19.00')
        beleg = faktura_services.beleg_festschreiben(beleg_id=beleg.pk)
        Beleg.objects.filter(pk=beleg.pk).update(
            faellig_am=timezone.localdate() - timedelta(days=5))
        return beleg

    def _kopf(self, client, beleg) -> str:
        """Text des Kopfs zwischen Seitentitel und "Rechnung bearbeiten",
        ohne Markup."""
        import re
        inhalt = client.get(
            reverse('rechnungsakte', args=[beleg.pk])).content.decode()
        kopf = inhalt[inhalt.index('---- Kopf') if '---- Kopf' in inhalt else 0:
                      inhalt.index('Rechnung bearbeiten')]
        kopf = re.sub(r'<[^>]+>', ' ', kopf[-3000:])
        return ' '.join(kopf.split())

    def test_ueber_der_frist(self, als_chefin, rechnung):
        kopf = self._kopf(als_chefin, rechnung)

        assert rechnung.nummer in kopf
        assert 'Festgeschrieben' in kopf
        assert 'über Frist' in kopf

    def test_der_entwurf_heisst_wie_in_der_liste(self, als_chefin, projekt):
        from faktura.models import BelegTyp

        entwurf = faktura_services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG)

        kopf = self._kopf(als_chefin, entwurf)

        assert f'Entwurf {entwurf.pk}' in kopf
        assert 'über Frist' not in kopf and 'offen' not in kopf.lower().split()


class TestDerWegDesBelegs:
    """Die Schrittleiste der Rechnungsakte (``rechnungsakte.belegweg``)."""

    @pytest.fixture
    def entwurf(self, projekt):
        from faktura.models import BelegTyp

        beleg = faktura_services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG, betreff='Kanal Süd')
        beleg.leistungsdatum = date(2026, 8, 20)
        beleg.save()
        faktura_services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Planung', menge=Decimal('1'),
            einzelpreis=Decimal('1000.00'), steuersatz='19.00')
        return beleg

    @staticmethod
    def _weg(beleg):
        return [(s['titel'], s['erreicht'], s['jetzt'])
                for s in rechnungsakte.belegweg(beleg)]

    def test_der_entwurf_steht_vor_dem_festschreiben(self, entwurf, settings):
        settings.PAPERLESS_ARCHIVIERUNG = False

        assert self._weg(entwurf) == [
            ('Angelegt', True, False), ('Festgeschrieben', False, True),
            ('E-Mail', False, False), ('Bezahlt', False, False)]

    def test_mit_archiv_ein_schritt_mehr(self, entwurf, settings):
        settings.PAPERLESS_ARCHIVIERUNG = True

        assert [t for t, _, _ in self._weg(entwurf)] == [
            'Angelegt', 'Festgeschrieben', 'E-Mail', 'Im Archiv', 'Bezahlt']

    def test_bezahlt_mit_dem_tag_der_letzten_zahlung(self, entwurf, settings):
        settings.PAPERLESS_ARCHIVIERUNG = False
        rechnung = faktura_services.beleg_festschreiben(beleg_id=entwurf.pk)
        faktura_services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=date(2026, 9, 1), betrag=Decimal('500.00'))
        faktura_services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=date(2026, 9, 15), betrag=Decimal('690.00'))

        weg = rechnungsakte.belegweg(rechnung)

        assert weg[-1] == {'titel': 'Bezahlt', 'erreicht': True,
                           'datum': '15.09.2026', 'jetzt': False}
        # Ohne Mail und bezahlt: kein offener Schritt, weil die E-Mail
        # optional ist.
        assert [s['titel'] for s in weg if s['jetzt']] == []

    def test_ohne_mail_ist_die_zahlung_das_naechste(self, entwurf, settings):
        """Ohne Mail ist die Zahlung der nächste Schritt."""
        settings.PAPERLESS_ARCHIVIERUNG = False
        rechnung = faktura_services.beleg_festschreiben(beleg_id=entwurf.pk)

        assert self._weg(rechnung) == [
            ('Angelegt', True, False), ('Festgeschrieben', True, False),
            ('E-Mail', False, False), ('Bezahlt', False, True)]

    def test_der_storno_endet_mit_storniert(self, entwurf, settings):
        settings.PAPERLESS_ARCHIVIERUNG = False
        rechnung = faktura_services.beleg_festschreiben(beleg_id=entwurf.pk)
        faktura_services.rechnung_korrigieren(beleg_id=rechnung.pk)
        rechnung.refresh_from_db()

        assert self._weg(rechnung) == [
            ('Angelegt', True, False), ('Festgeschrieben', True, False),
            ('Storniert', True, False)]

    def test_die_schritte_stehen_in_der_seite(self, als_chefin, entwurf):
        inhalt = als_chefin.get(
            reverse('rechnungsakte', args=[entwurf.pk])).content.decode()

        assert 'id="belegweg"' in inhalt
        assert 'als Nächstes' in inhalt
