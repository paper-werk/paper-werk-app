"""Benannte Sortierungen (``erfassung/sortierung.py``)."""

from datetime import date, time, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from erfassung import services
from erfassung.sortierung import Sortierung, ordnung
from erfassung.tests.hilfen import spalte as _spalte
from erfassung.tests.hilfen import zelle as _zelle
from faktura.models import Beleg, Belegposition, BelegStatus, BelegTyp
from faktura.positionsnummer import sortierschluessel

LISTE = 'admin:erfassung_erfassungszeile_changelist'


@pytest.fixture
def als_mitarbeiter(client, mitarbeiter):
    mitarbeiter.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='erfassung',
        codename__in=['add_erfassungszeile', 'view_erfassungszeile',
                      'change_erfassungszeile'],
    ))
    client.force_login(mitarbeiter)
    return client


class TestDerVorratIstVollstaendig:
    """Jede Auswahl hat eine Regel, ohne Datenbank geprüft."""

    def test_jede_sortierung_hat_eine_regel(self):
        """Jede Sortierung der Auswahl hat eine Regel."""
        for schluessel in Sortierung:
            assert ordnung(schluessel), schluessel

    def test_eine_erfundene_sortierung_scheitert_laut(self):
        """Eine unbekannte Sortierung wirft ``ValueError``."""
        with pytest.raises(ValueError):
            ordnung('nach_gefuehl')


@pytest.fixture
def gemischter_tag(projekt, zeitleistung, mengenleistung, pauschalleistung,
                   mitarbeiter):
    """Ein Vorhaben, zwei Tage, alle drei Leistungsarten. Die Reihenfolge
    wird an den Beschreibungen abgelesen."""
    gestern = timezone.localdate() - timedelta(days=1)
    heute = timezone.localdate()

    services.zeile_erfassen(
        projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
        datum=gestern, von=time(8, 0), bis=time(12, 0),
        beschreibung='A gestern Stunden')
    services.zeile_erfassen(
        projekt=projekt, leistung=mengenleistung, benutzer=mitarbeiter,
        datum=gestern, menge=23, beschreibung='B gestern Menge')
    services.zeile_erfassen(
        projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
        datum=heute, von=time(13, 0), bis=time(17, 0),
        beschreibung='C heute Stunden')
    services.zeile_erfassen(
        projekt=projekt, leistung=pauschalleistung, benutzer=mitarbeiter,
        datum=heute, beschreibung='D heute Pauschale')


@pytest.mark.django_db
class TestNachweisUndTagebuch:
    """Auf einem Kundenbericht stehen je Vorhaben zuerst Pauschalen und
    Mengen, dann Stunden."""

    def test_nachweis_stellt_pauschale_und_menge_voran(self, als_mitarbeiter,
                                                       gemischter_tag):
        """Je Vorhaben erst Pauschalen, dann Mengen, dann Stunden."""
        antwort = als_mitarbeiter.get(reverse(LISTE),
                                      {'sortierung': Sortierung.NACHWEIS})

        assert _spalte(antwort.content.decode(), 'beschreibung') == [
            'D heute Pauschale',
            'B gestern Menge',
            'A gestern Stunden',
            'C heute Stunden',
        ]

    def test_tagebuch_stellt_den_tag_voran(self, als_mitarbeiter,
                                           gemischter_tag):
        """Je Tag zuerst Pauschalen, dann Stunden."""
        antwort = als_mitarbeiter.get(reverse(LISTE),
                                      {'sortierung': Sortierung.TAGEBUCH})

        assert _spalte(antwort.content.decode(), 'beschreibung') == [
            'B gestern Menge',
            'A gestern Stunden',
            'D heute Pauschale',
            'C heute Stunden',
        ]

    def test_neueste_zuerst_ist_die_vorgabe(self, als_mitarbeiter,
                                            gemischter_tag):
        """Vorgabe: zuletzt Erfasstes zuerst."""
        antwort = als_mitarbeiter.get(reverse(LISTE))
        ohne = _spalte(antwort.content.decode(), 'beschreibung')

        assert ohne[0].startswith(('C heute', 'D heute'))
        assert ohne[-1].startswith(('A gestern', 'B gestern'))

    def test_die_sortierung_aendert_die_reihenfolge_wirklich(
        self, als_mitarbeiter, gemischter_tag
    ):
        """Die Sortierungen liefern verschiedene Reihenfolgen."""
        gesehen = set()
        for schluessel in Sortierung:
            antwort = als_mitarbeiter.get(reverse(LISTE),
                                          {'sortierung': schluessel})
            gesehen.add(tuple(_spalte(antwort.content.decode(), 'beschreibung')))

        assert len(gesehen) >= 3


def _auftrag(projekt, nummer, *positionen):
    """Festgeschriebener Auftrag mit Positionen ``(nummer, bezeichnung)``.

    Über ``bulk_create`` wie die Fixture ``auftragsposition``, deshalb mit
    gesetzter ``sortierung``.
    """
    auftrag = Beleg.objects.create(
        typ=BelegTyp.AUFTRAG, status=BelegStatus.FESTGESCHRIEBEN,
        nummer=nummer, projekt=projekt)
    return Belegposition.objects.bulk_create([
        Belegposition(
            beleg=auftrag, position=position, bezeichnung=bezeichnung,
            sortierung=sortierschluessel(position), menge=Decimal('10'),
            einheit='Std', einzelpreis=Decimal('95.00'), art='zeit')
        for position, bezeichnung in positionen
    ])


@pytest.mark.django_db
class TestNachAuftrag:
    """Je Vorhaben nach Auftrag und Position, Katalogzeilen am Ende."""

    @pytest.fixture
    def zwei_auftraege(self, projekt, zeitleistung, mitarbeiter):
        """Zwei Aufträge und eine Katalogzeile, in gemischter Reihenfolge
        angelegt. Position "9" vor "10" prüft die Sortierung nach
        ``Belegposition.sortierung`` statt nach dem Text."""
        zehn, neun = _auftrag(projekt, 'AU-2026-0002',
                              ('10', 'Bauüberwachung'), ('9', 'Prüfung'))
        (erster,) = _auftrag(projekt, 'AU-2026-0001', ('10', 'Planung'))

        def erfassen(beschreibung, tag, **grundlage):
            services.zeile_erfassen(
                projekt=projekt, benutzer=mitarbeiter, beschreibung=beschreibung,
                datum=date(2026, 9, tag), von=time(8), bis=time(9),
                **grundlage)

        erfassen('Katalog', 1, leistung=zeitleistung)
        erfassen('0002/10 später', 5, auftragsposition=zehn)
        erfassen('0002/9', 2, auftragsposition=neun)
        erfassen('0001/10', 9, auftragsposition=erster)
        erfassen('0002/10 früher', 3, auftragsposition=zehn)

    def test_auftrag_position_datum_und_katalog_am_ende(
        self, als_mitarbeiter, zwei_auftraege
    ):
        antwort = als_mitarbeiter.get(reverse(LISTE),
                                      {'sortierung': Sortierung.AUFTRAG})

        assert _spalte(antwort.content.decode(), 'beschreibung') == [
            '0001/10', '0002/9', '0002/10 früher', '0002/10 später',
            'Katalog']

    def test_worauf_zeigt_die_positionsnummer(self, als_mitarbeiter,
                                              zwei_auftraege):
        """Die Spalte zeigt die Position mit Nummer, darunter den Auftrag."""
        antwort = als_mitarbeiter.get(reverse(LISTE),
                                      {'sortierung': Sortierung.AUFTRAG})

        zelle = _zelle(antwort.content.decode(), 'worauf')
        assert '10. Planung' in zelle
        assert 'AU-2026-0001' in zelle


@pytest.mark.django_db
class TestDieUhrzeitSortiertMit:

    def test_drei_bloecke_am_selben_tag_stehen_in_der_richtigen_folge(
        self, als_mitarbeiter, projekt, zeitleistung, mitarbeiter
    ):
        """Drei Blöcke am selben Tag stehen nach Uhrzeit.

        Drei Zeilen in gemischter Anlegereihenfolge, damit weder auf- noch
        absteigende Sortierung nach Primärschlüssel die Uhrzeit zufällig
        trifft.
        """
        for stunde, name in ((12, 'Mittag'), (9, 'Vormittag'),
                             (15, 'Nachmittag')):
            services.zeile_erfassen(
                projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
                von=time(stunde, 0), bis=time(stunde + 1, 0),
                beschreibung=name)

        antwort = als_mitarbeiter.get(reverse(LISTE),
                                      {'sortierung': Sortierung.TAGEBUCH})

        assert _spalte(antwort.content.decode(), 'beschreibung') == [
            'Vormittag', 'Mittag', 'Nachmittag']

    def test_eine_zeile_ohne_uhrzeit_steht_am_tagesanfang(
        self, als_mitarbeiter, projekt, zeitleistung, mitarbeiter
    ):
        """Eine Zeile ohne Uhrzeit steht am Tagesanfang (``nulls_first``).

        Beide Zeilen sind Zeitleistungen, damit nicht der Artrang die
        Reihenfolge bestimmt.
        """
        services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            von=time(9, 0), bis=time(12, 0), beschreibung='Mit Uhrzeit')
        services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Noch ohne Uhrzeit')

        antwort = als_mitarbeiter.get(reverse(LISTE),
                                      {'sortierung': Sortierung.TAGEBUCH})

        assert _spalte(antwort.content.decode(), 'beschreibung') == [
            'Noch ohne Uhrzeit', 'Mit Uhrzeit']


@pytest.mark.django_db
class TestDieListeBleibtBedienbar:

    def test_ein_spaltenkopf_schlaegt_die_sortierung(self, als_mitarbeiter,
                                                     gemischter_tag):
        """``?o=`` aus einem Spaltenkopf hat Vorrang vor der benannten
        Sortierung."""
        spalte = list(als_mitarbeiter.get(reverse(LISTE))
                      .context_data['cl'].list_display).index('beschreibung')

        antwort = als_mitarbeiter.get(reverse(LISTE), {
            'sortierung': Sortierung.NACHWEIS, 'o': spalte})

        assert _spalte(antwort.content.decode(), 'beschreibung') == [
            'A gestern Stunden', 'B gestern Menge',
            'C heute Stunden', 'D heute Pauschale',
        ]

    def test_eine_erfundene_sortierung_wirft_keinen_serverfehler(
        self, als_mitarbeiter
    ):
        """Eine unbekannte Sortierung in der URL ergibt keine 500.

        Wie bei den Filtern wird ``get_ordering`` außerhalb von Djangos
        try-Block aufgerufen.
        """
        antwort = als_mitarbeiter.get(reverse(LISTE),
                                      {'sortierung': 'nach_gefuehl'})

        assert antwort.status_code == 302
        assert antwort['Location'].endswith('?e=1')

    def test_die_sortierung_steht_in_der_filterleiste(self, als_mitarbeiter):
        """Die Sortierung erscheint in der Filterleiste, weil sie als Filter
        umgesetzt ist."""
        inhalt = als_mitarbeiter.get(reverse(LISTE)).content.decode()

        assert 'Nachweis: Projekt, Art, Datum' in inhalt


@pytest.mark.django_db
class TestNurDieStunden:
    """Filter auf Zeitleistungen."""

    def test_der_artfilter_laesst_nur_zeitzeilen_stehen(self, als_mitarbeiter,
                                                        gemischter_tag):
        antwort = als_mitarbeiter.get(reverse(LISTE),
                                      {'leistung__art__exact': 'zeit'})
        inhalt = antwort.content.decode()

        assert antwort.status_code == 200
        assert _spalte(inhalt, 'beschreibung') == [
            'C heute Stunden', 'A gestern Stunden']

    def test_ohne_filter_stehen_alle_da(self, als_mitarbeiter, gemischter_tag):
        """Gegenprobe: Ohne Filter erscheinen alle Zeilen."""
        antwort = als_mitarbeiter.get(reverse(LISTE))

        assert len(_spalte(antwort.content.decode(), 'beschreibung')) == 4
