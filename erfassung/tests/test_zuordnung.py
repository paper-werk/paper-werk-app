"""Zuordnung von Fremdleistungen zu Auftragspositionen, über den
Fremdschlüssel und von Hand (``erfassung.services.zuordnung``)."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from erfassung import services
from erfassung.models import Eingangsrechnung, Fremdleistung
from faktura.models import (
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Katalogposition,
    Kontakt,
    Projekt,
)

ASBEST = 'P-4711'


@pytest.fixture
def analyse(db):
    return Katalogposition.objects.create(
        bezeichnung='Asbestanalyse', einheit='Stk',
        einzelpreis=Decimal('174.00'), fremdschluessel=ASBEST)


def auftrag_mit(projekt, *katalogpositionen, status=BelegStatus.FESTGESCHRIEBEN,
                nummer='AU-2026-0007'):
    """Auftrag mit einer Leistungsposition je Katalogposition (Werte und
    Fremdschlüssel kopiert), über
    ``bulk_create``, weil ``save()`` festgeschriebene Belege ablehnt. Ein
    Entwurf ohne Nummer, wie im Betrieb."""
    if status == BelegStatus.ENTWURF:
        nummer = None
    auftrag = Beleg.objects.create(typ=BelegTyp.AUFTRAG, status=status,
                                   nummer=nummer, projekt=projekt)
    return Belegposition.objects.bulk_create([
        Belegposition(beleg=auftrag, position=str(10 * (i + 1)),
                      sortierung=f'{10 * (i + 1):08d}',
                      bezeichnung=k.bezeichnung, menge=Decimal('10'),
                      einheit=k.einheit, einzelpreis=k.einzelpreis,
                      fremdschluessel=k.fremdschluessel)
        for i, k in enumerate(katalogpositionen)
    ])


@pytest.fixture
def eingang(db):
    labor = Kontakt.objects.create(ist_kunde=False, ist_lieferant=True,
                                   name='Labor Isartal')
    return Eingangsrechnung.objects.create(
        lieferant=labor, nummer='L-1', datum=date(2026, 11, 2),
        betrag_netto=Decimal('500.00'))


def fremd(eingang, projekt, schluessel=ASBEST, **rest):
    return Fremdleistung.objects.create(
        rechnung=eingang, projekt=projekt, bezeichnung='Asbest, Probe 1',
        fremdschluessel=schluessel, einkaufspreis=Decimal('40.00'), **rest)


class TestPositionZumFremdschluessel:

    def test_genau_ein_treffer_wird_gefunden(self, projekt, analyse):
        (position,) = auftrag_mit(projekt, analyse)

        assert services.auftragsposition_zum_fremdschluessel(
            projekt, ASBEST) == position

    def test_zwei_gleiche_positionen_ergeben_keinen_treffer(self, projekt,
                                                             analyse):
        """Etwa je Geschoss eine Position aus derselben Katalogposition."""
        auftrag_mit(projekt, analyse, analyse)

        assert services.auftragsposition_zum_fremdschluessel(
            projekt, ASBEST) is None

    def test_auch_ueber_mehrere_auftraege(self, projekt, analyse):
        """Ein Nachtrag mit derselben Leistung macht den Treffer mehrdeutig."""
        auftrag_mit(projekt, analyse)
        auftrag_mit(projekt, analyse, nummer='AU-2026-0008')

        assert services.auftragsposition_zum_fremdschluessel(
            projekt, ASBEST) is None

    def test_nur_festgeschriebene_auftraege_des_projekts(self, projekt,
                                                         kunde, analyse):
        auftrag_mit(projekt, analyse, status=BelegStatus.ENTWURF)
        anderes = Projekt.objects.create(nummer='2026-043', kunde=kunde,
                                         bezeichnung='Halle Süd')
        auftrag_mit(anderes, analyse, nummer='AU-2026-0009')

        assert services.auftragsposition_zum_fremdschluessel(
            projekt, ASBEST) is None

    def test_ohne_schluessel_oder_im_abgeschlossenen_projekt_nichts(
            self, projekt, abgeschlossenes_projekt, analyse):
        auftrag_mit(projekt, analyse)
        auftrag_mit(abgeschlossenes_projekt, analyse, nummer='AU-2025-0001')

        assert services.auftragsposition_zum_fremdschluessel(
            projekt, '  ') is None
        assert services.auftragsposition_zum_fremdschluessel(
            abgeschlossenes_projekt, ASBEST) is None


class TestUeberFremdschluesselZuordnen:

    def test_setzt_die_position(self, projekt, analyse, eingang):
        (position,) = auftrag_mit(projekt, analyse)
        zeile = fremd(eingang, projekt)

        befund = services.ueber_fremdschluessel_zuordnen(
            Fremdleistung.objects.all())

        zeile.refresh_from_db()
        assert zeile.auftragsposition == position
        assert befund.geaendert == 1

    def test_eine_vorhandene_position_bleibt(self, projekt, analyse, eingang):
        """Auch eine von Hand gesetzte mit anderem Fremdschlüssel."""
        andere = Katalogposition.objects.create(
            bezeichnung='Probenahme', einzelpreis=Decimal('60.00'))
        analyse_position, von_hand = auftrag_mit(projekt, analyse, andere)
        zeile = fremd(eingang, projekt, auftragsposition=von_hand)

        services.ueber_fremdschluessel_zuordnen(Fremdleistung.objects.all())

        zeile.refresh_from_db()
        assert zeile.auftragsposition == von_hand

    def test_ohne_eindeutigen_treffer_wird_gezaehlt(self, projekt, analyse,
                                                     eingang):
        auftrag_mit(projekt, analyse, analyse)
        fremd(eingang, projekt)
        fremd(eingang, projekt, schluessel='')

        befund = services.ueber_fremdschluessel_zuordnen(
            Fremdleistung.objects.all())

        assert (befund.geaendert, befund.ohne_treffer) == (0, 2)
        assert not Fremdleistung.objects.filter(
            auftragsposition__isnull=False).exists()

    def test_auf_einem_entwurf_bleibt_sie_unveraendert(
            self, projekt, analyse, eingang, entwurfsposition):
        auftrag_mit(projekt, analyse)
        zeile = fremd(eingang, projekt, abgerechnet_in=entwurfsposition)

        befund = services.ueber_fremdschluessel_zuordnen(
            Fremdleistung.objects.all())

        zeile.refresh_from_db()
        assert zeile.auftragsposition is None
        assert befund.gesperrt == 1


class TestAuftragspositionSetzen:

    def test_setzt_und_entfernt(self, projekt, analyse, eingang):
        (position,) = auftrag_mit(projekt, analyse)
        a, b = fremd(eingang, projekt), fremd(eingang, projekt)
        auswahl = Fremdleistung.objects.filter(pk__in=[a.pk, b.pk])

        assert services.auftragsposition_setzen(auswahl, position).geaendert == 2
        assert set(auswahl.values_list('auftragsposition', flat=True)) == {
            position.pk}

        services.auftragsposition_setzen(auswahl, None)
        assert set(auswahl.values_list('auftragsposition', flat=True)) == {None}

    def test_die_version_der_eingangsrechnung_steigt(self, projekt, analyse,
                                                     eingang):
        """Eine offene Maske der Eingangsrechnung darf die Zuordnung nicht
        unbemerkt zurückschreiben (Optimistic Locking)."""
        (position,) = auftrag_mit(projekt, analyse)
        fremd(eingang, projekt)
        vorher = Eingangsrechnung.objects.get(pk=eingang.pk).version

        services.auftragsposition_setzen(Fremdleistung.objects.all(), position)

        assert Eingangsrechnung.objects.get(pk=eingang.pk).version > vorher

    def test_mehrere_projekte_werden_abgewiesen(self, projekt, kunde,
                                                 analyse, eingang):
        (position,) = auftrag_mit(projekt, analyse)
        anderes = Projekt.objects.create(nummer='2026-043', kunde=kunde,
                                         bezeichnung='Halle Süd')
        fremd(eingang, projekt)
        fremd(eingang, anderes)

        with pytest.raises(services.MehrereProjekte):
            services.auftragsposition_setzen(Fremdleistung.objects.all(),
                                             position)

    def test_eine_position_eines_anderen_projekts_wird_abgewiesen(
            self, projekt, kunde, analyse, eingang):
        anderes = Projekt.objects.create(nummer='2026-043', kunde=kunde,
                                         bezeichnung='Halle Süd')
        (fremde_position,) = auftrag_mit(anderes, analyse)
        fremd(eingang, projekt)

        with pytest.raises(services.ZielUngeeignet):
            services.auftragsposition_setzen(Fremdleistung.objects.all(),
                                             fremde_position)

    def test_abgeschlossenes_projekt_wird_abgewiesen(
            self, abgeschlossenes_projekt, analyse, eingang):
        (position,) = auftrag_mit(abgeschlossenes_projekt, analyse)
        fremd(eingang, abgeschlossenes_projekt)

        with pytest.raises(services.ProjektAbgeschlossen):
            services.auftragsposition_setzen(Fremdleistung.objects.all(),
                                             position)

    def test_abgerechnete_bleiben_unveraendert(
            self, projekt, analyse, eingang, festgeschriebene_position):
        (position,) = auftrag_mit(projekt, analyse)
        offen = fremd(eingang, projekt)
        abgerechnet = fremd(eingang, projekt,
                            abgerechnet_in=festgeschriebene_position)

        befund = services.auftragsposition_setzen(
            Fremdleistung.objects.all(), position)

        offen.refresh_from_db()
        abgerechnet.refresh_from_db()
        assert offen.auftragsposition == position
        assert abgerechnet.auftragsposition is None
        assert (befund.geaendert, befund.gesperrt) == (1, 1)


@pytest.fixture
def als_leitung(client, kollege):
    kollege.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='erfassung'))
    kollege.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='faktura',
        codename__in=['view_projekt', 'change_projekt']))
    client.force_login(kollege)
    return client


class TestAktionenInDerListe:
    LISTE = 'admin:erfassung_fremdleistung_changelist'

    def test_zwischenseite_bietet_die_positionen_des_projekts(
            self, als_leitung, projekt, analyse, eingang):
        auftrag_mit(projekt, analyse)
        zeile = fremd(eingang, projekt)

        antwort = als_leitung.post(reverse(self.LISTE), {
            'action': 'position_setzen', '_selected_action': [zeile.pk]})

        inhalt = antwort.content.decode()
        assert antwort.status_code == 200
        assert 'Asbestanalyse' in inhalt
        assert 'Keine (Zuordnung entfernen)' in inhalt

    def test_bestaetigen_setzt_die_position(self, als_leitung, projekt,
                                            analyse, eingang):
        (position,) = auftrag_mit(projekt, analyse)
        zeile = fremd(eingang, projekt)

        antwort = als_leitung.post(reverse(self.LISTE), {
            'action': 'position_setzen', '_selected_action': [zeile.pk],
            'bestaetigt': 'ja', 'auftragsposition': position.pk},
            follow=True)

        zeile.refresh_from_db()
        assert zeile.auftragsposition == position
        assert '1 Fremdleistung zugeordnet' in antwort.content.decode()

    def test_mehrere_projekte_ohne_zwischenseite(self, als_leitung, projekt,
                                                 kunde, analyse, eingang):
        anderes = Projekt.objects.create(nummer='2026-043', kunde=kunde,
                                         bezeichnung='Halle Süd')
        a, b = fremd(eingang, projekt), fremd(eingang, anderes)

        antwort = als_leitung.post(reverse(self.LISTE), {
            'action': 'position_setzen', '_selected_action': [a.pk, b.pk]},
            follow=True)

        assert 'genau eines Projekts' in antwort.content.decode()

    def test_ueber_fremdschluessel(self, als_leitung, projekt, analyse,
                                   eingang):
        (position,) = auftrag_mit(projekt, analyse)
        zeile = fremd(eingang, projekt)

        als_leitung.post(reverse(self.LISTE), {
            'action': 'ueber_fremdschluessel',
            '_selected_action': [zeile.pk]})

        zeile.refresh_from_db()
        assert zeile.auftragsposition == position
