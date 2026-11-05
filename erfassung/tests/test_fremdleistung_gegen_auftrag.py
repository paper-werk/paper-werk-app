"""Fremdleistungen an Rechnungen, die gegen den Auftrag abrechnen.

Abschlags-, Teilschluss- und Schlussrechnung nehmen Fremdleistungen nur zum
Preis einer Auftragsposition mit passender Einheit auf
(``Rechnungsart.gegen_auftrag``); die gewöhnliche Rechnung auch zum
Einkaufspreis. Geprüft über den Service, die Auswahl an der Rechnung und
die Listenaktion.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from erfassung import services
from erfassung.models import Eingangsrechnung, Fremdleistung
from faktura import services as faktura_services
from faktura.models import (
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Kontakt,
    Rechnungsart,
)

GEGEN_AUFTRAG = [Rechnungsart.ABSCHLAG, Rechnungsart.TEILSCHLUSS,
                 Rechnungsart.SCHLUSS]
LISTE = {
    Rechnungsart.NORMAL: 'rechnung',
    Rechnungsart.ABSCHLAG: 'abschlagsrechnung',
    Rechnungsart.TEILSCHLUSS: 'teilschlussrechnung',
    Rechnungsart.SCHLUSS: 'schlussrechnung',
}


@pytest.fixture
def laborrechnung(db):
    labor = Kontakt.objects.create(name='Bodenlabor Isartal GmbH', ist_kunde=False,
                                   ist_lieferant=True)
    return Eingangsrechnung.objects.create(
        lieferant=labor, nummer='RE-2026-0815', datum=date(2026, 10, 1),
        betrag_netto=Decimal('1000.00'))


@pytest.fixture
def positionen(projekt):
    """Festgeschriebener Auftrag: Pos. 10 je Stück, Pos. 20 pauschal."""
    auftrag = Beleg.objects.create(
        typ=BelegTyp.AUFTRAG, status=BelegStatus.FESTGESCHRIEBEN,
        nummer='AU-2026-0012', projekt=projekt)
    return Belegposition.objects.bulk_create([
        Belegposition(beleg=auftrag, position='10',
                      bezeichnung='Asbest Materialprobe', menge=Decimal('40'),
                      einheit='Stk', einzelpreis=Decimal('65.00'),
                      steuersatz='19.00'),
        Belegposition(beleg=auftrag, position='20',
                      bezeichnung='Probenaufbereitung', menge=Decimal('1'),
                      einheit='pausch', einzelpreis=Decimal('300.00'),
                      steuersatz='19.00'),
    ])


@pytest.fixture
def bestand(laborrechnung, projekt, positionen):
    """Je zwei Fremdleistungen: zur Position, ohne Position, mit falscher
    Einheit. Bezeichnungen wie aus dem Laborimport."""
    stueck, pauschal = positionen

    def anlegen(auftragsposition, schluessel, paket, probe):
        return Fremdleistung.objects.create(
            rechnung=laborrechnung, projekt=projekt,
            auftragsposition=auftragsposition, fremdschluessel=schluessel,
            bezeichnung=f'{paket}, Probe {probe}, Analyse {probe}00',
            einheit='Stk', menge=Decimal('1'),
            einkaufspreis=Decimal('56.70'))

    return {
        'passend': [anlegen(stueck, '12422', 'Asbest Materialprobe', p)
                    for p in (1, 2)],
        'ohne': [anlegen(None, '1700', 'KI-Index Mineralfasern', p)
                 for p in (3, 4)],
        'einheit': [anlegen(pauschal, '65736', 'Aufbereitung Asbest/KMF', p)
                    for p in (5, 6)],
    }


def _rechnung(projekt, art):
    if art == Rechnungsart.TEILSCHLUSS:
        # Entsteht sonst nur aus einer Teilabnahme
        # (``services.rechnung_aus_abnahme``).
        return Beleg.objects.create(
            typ=BelegTyp.RECHNUNG, rechnungsart=art,
            status=BelegStatus.ENTWURF, projekt=projekt)
    return faktura_services.beleg_anlegen(
        projekt=projekt, typ=BelegTyp.RECHNUNG, rechnungsart=art,
        betreff='Test')


def _pks(fremdleistungen):
    return [f.pk for f in fremdleistungen]


# ── Service ──────────────────────────────────────────────────────────────


class TestUebernahme:

    @pytest.mark.parametrize('art', GEGEN_AUFTRAG)
    def test_nur_zum_auftragspreis(self, projekt, bestand, art):
        rechnung = _rechnung(projekt, art)

        _, vorschau = services.in_rechnung_uebernehmen(
            zeilen=[], fremdleistungen=Fremdleistung.objects.all(),
            beleg=rechnung)

        position = rechnung.positionen.get()
        assert (position.menge, position.einzelpreis) == (2, Decimal('65.00'))
        uebernommen = Fremdleistung.objects.filter(abgerechnet_in__isnull=False)
        assert set(_pks(uebernommen)) == set(_pks(bestand['passend']))
        assert sorted(grund for _, grund in vorschau.uebergangen) == [
            services.GRUND_EINHEIT_ABWEICHEND] * 2 + [
            services.GRUND_OHNE_AUFTRAGSPOSITION] * 2

    @pytest.mark.parametrize('art', [Rechnungsart.ABSCHLAG,
                                     Rechnungsart.SCHLUSS])
    def test_neu_angelegt_gilt_dasselbe(self, projekt, bestand, art):
        """Ohne ``beleg`` zählt die ``rechnungsart`` des neuen Entwurfs
        (Listenaktion, Ziel „Neue Abschlagsrechnung“)."""
        rechnung, _ = services.in_rechnung_uebernehmen(
            zeilen=[], fremdleistungen=Fremdleistung.objects.all(),
            rechnungsart=art)

        assert rechnung.positionen.get().einzelpreis == Decimal('65.00')

    def test_die_gewoehnliche_rechnung_nimmt_alles(self, projekt, bestand):
        rechnung = _rechnung(projekt, Rechnungsart.NORMAL)

        services.in_rechnung_uebernehmen(
            zeilen=[], fremdleistungen=Fremdleistung.objects.all(),
            beleg=rechnung)

        assert not Fremdleistung.objects.filter(
            abgerechnet_in__isnull=True).exists()
        # Zum Einkaufspreis je Bezeichnung eine Position.
        preise = sorted(p.einzelpreis for p in rechnung.positionen.all())
        assert preise == [Decimal('56.70')] * 4 + [Decimal('65.00')]

    def test_nur_ausgeschlossene_ergibt_eine_erklaerung(self, projekt,
                                                        bestand):
        rechnung = _rechnung(projekt, Rechnungsart.ABSCHLAG)

        with pytest.raises(services.NichtsAbzurechnen,
                           match='nur zum Preis einer Auftragsposition'):
            services.in_rechnung_uebernehmen(
                zeilen=[], fremdleistungen=Fremdleistung.objects.filter(
                    pk__in=_pks(bestand['ohne'])),
                beleg=rechnung)

        assert not rechnung.positionen.exists()


class TestAuswahl:

    def test_offen_nur_zum_auftragspreis(self, projekt, bestand):
        [gruppe] = services.offene_fremdleistungen(
            projekt, nur_auftragspreis=True)

        assert _pks(gruppe.positionen) == _pks(bestand['passend'])

    def test_ohne_einschraenkung_alles(self, projekt, bestand):
        [gruppe] = services.offene_fremdleistungen(projekt)

        assert len(gruppe.positionen) == 6

    def test_ausschluesse_gruppiert_nach_grund_und_leistung(
            self, projekt, bestand):
        ausschluesse = services.nicht_uebernehmbare_fremdleistungen(projekt)

        assert [(a.grund, a.bezeichnung, a.anzahl, a.detail)
                for a in ausschluesse] == [
            (services.GRUND_EINHEIT_ABWEICHEND, 'Aufbereitung Asbest/KMF', 2,
             'Stk, Pos. 20 hat pausch'),
            (services.GRUND_OHNE_AUFTRAGSPOSITION, 'KI-Index Mineralfasern', 2,
             ''),
        ]

    def test_abgerechnetes_und_nicht_weiterberechenbares_fehlt(
            self, projekt, bestand):
        Fremdleistung.objects.filter(
            pk__in=_pks(bestand['ohne'])).update(weiterberechenbar=False)

        ausschluesse = services.nicht_uebernehmbare_fremdleistungen(projekt)

        assert [a.grund for a in ausschluesse] == [
            services.GRUND_EINHEIT_ABWEICHEND]


# ── Admin ────────────────────────────────────────────────────────────────


class TestMaskeAnDerRechnung:

    @staticmethod
    def _adresse(rechnung):
        return reverse(f'admin:faktura_{LISTE[rechnung.rechnungsart]}'
                       f'_detail_leistungen', args=[rechnung.pk])

    @pytest.mark.parametrize('art', GEGEN_AUFTRAG)
    def test_zeigt_nur_passende_und_den_hinweis(self, admin_client, projekt,
                                                bestand, art):
        rechnung = _rechnung(projekt, art)

        inhalt = admin_client.get(self._adresse(rechnung)).content.decode()

        angeboten = {int(k) for k in _werte(inhalt, 'fremdleistung')}
        assert angeboten == set(_pks(bestand['passend']))
        assert 'data-ausschluesse' in inhalt
        assert '2 &times; KI-Index Mineralfasern' in inhalt
        assert 'Stk, Pos. 20 hat pausch' in inhalt
        assert (f'?projekt__id__exact={projekt.pk}&amp;zustand=offen'
                in inhalt)

    def test_gewoehnliche_rechnung_ohne_hinweis(self, admin_client, projekt,
                                                bestand):
        rechnung = _rechnung(projekt, Rechnungsart.NORMAL)

        inhalt = admin_client.get(self._adresse(rechnung)).content.decode()

        assert len(_werte(inhalt, 'fremdleistung')) == 6
        assert 'data-ausschluesse' not in inhalt

    def test_untergeschobene_kennung_wird_nicht_uebernommen(
            self, admin_client, projekt, bestand):
        """Die IDs kommen aus dem Request; der Service prüft selbst."""
        rechnung = _rechnung(projekt, Rechnungsart.ABSCHLAG)

        admin_client.post(self._adresse(rechnung), {'fremdleistung': [
            str(pk) for pk in _pks(bestand['passend'] + bestand['ohne'])]})

        assert rechnung.positionen.get().einzelpreis == Decimal('65.00')
        assert not Fremdleistung.objects.filter(
            pk__in=_pks(bestand['ohne']),
            abgerechnet_in__isnull=False).exists()



class TestListe:

    @pytest.mark.parametrize('wert, gruppe', [
        ('ohne', 'ohne'), ('einheit', 'einheit'), ('zugeordnet', 'passend')])
    def test_filter_zuordnung(self, admin_client, projekt, bestand, wert,
                              gruppe):
        antwort = admin_client.get(
            reverse('admin:erfassung_fremdleistung_changelist'),
            {'projekt__id__exact': projekt.pk, 'zuordnung': wert})

        assert antwort.status_code == 200
        gefunden = {f.pk for f in antwort.context['cl'].queryset}
        assert gefunden == set(_pks(bestand[gruppe]))

    def test_einheit_ohne_schreibweise_verglichen(self, admin_client,
                                                  projekt, bestand):
        """„ stk “ passt zu „Stk“ wie beim Übernehmen."""
        Fremdleistung.objects.filter(
            pk__in=_pks(bestand['passend'])).update(einheit=' stk ')

        antwort = admin_client.get(
            reverse('admin:erfassung_fremdleistung_changelist'),
            {'zuordnung': 'einheit'})

        gefunden = {f.pk for f in antwort.context['cl'].queryset}
        assert gefunden == set(_pks(bestand['einheit']))

    def test_vorschau_nennt_die_zum_einkaufspreis(self, admin_client,
                                                  projekt, bestand):
        antwort = admin_client.post(
            reverse('admin:erfassung_fremdleistung_changelist'),
            {'action': 'in_rechnung', 'index': '0',
             '_selected_action': [str(f.pk) for f in
                                  Fremdleistung.objects.all()]})

        inhalt = antwort.content.decode()
        assert 'data-zum-einkaufspreis' in inhalt
        assert '4 Fremdleistungen' in inhalt

    def test_neue_abschlagsrechnung_uebergeht_sie(self, admin_client,
                                                  projekt, bestand):
        admin_client.post(
            reverse('admin:erfassung_fremdleistung_changelist'),
            {'action': 'in_rechnung', 'index': '0', 'bestaetigt': 'ja',
             'ziel': 'neu-abschlag',
             '_selected_action': [str(f.pk) for f in
                                  Fremdleistung.objects.all()]})

        rechnung = Beleg.objects.get(typ=BelegTyp.RECHNUNG)
        assert rechnung.rechnungsart == Rechnungsart.ABSCHLAG
        assert rechnung.positionen.get().einzelpreis == Decimal('65.00')


def _werte(inhalt: str, name: str) -> list[str]:
    import re

    return re.findall(rf'name="{name}" value="(\d+)"', inhalt)


def test_liste_zeigt_eingangsrechnung_und_fremdschluessel(
        admin_client, laborrechnung, bestand):
    antwort = admin_client.get(
        reverse('admin:erfassung_fremdleistung_changelist'))
    inhalt = antwort.content.decode()

    assert 'field-eingangsrechnung_spalte' in inhalt
    assert reverse('admin:erfassung_eingangsrechnung_change',
                   args=[laborrechnung.pk]) in inhalt
    assert 'RE-2026-0815' in inhalt
    assert '<td class="field-fremdschluessel' in inhalt
    assert '65736' in inhalt
