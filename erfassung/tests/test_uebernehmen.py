"""Übernahme in Rechnungen, der einzige Vorgang, der Erfassungszeilen
festschreibt."""

from datetime import time, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from erfassung import services
from erfassung.models import Erfassungszeile, Zustand
from erfassung.tests.hilfen import json_daten
from faktura import services as faktura_services
from faktura.models import Beleg, BelegStatus, BelegTyp, Rechnungsart

LISTE = 'admin:erfassung_erfassungszeile_changelist'


@pytest.fixture
def als_abrechner(client, kollege):
    """Konto, das erfassen und Rechnungen schreiben darf."""
    kollege.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='erfassung'))
    kollege.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='faktura',
        codename__in=['add_beleg', 'change_beleg', 'view_beleg'],
    ))
    client.force_login(kollege)
    return client


@pytest.fixture
def als_monteur(client, mitarbeiter):
    """Konto, das erfassen, aber keine Rechnungen schreiben darf."""
    mitarbeiter.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='erfassung'))
    client.force_login(mitarbeiter)
    return client


def _zeile(projekt, leistung, benutzer, **rest):
    return services.zeile_erfassen(
        projekt=projekt, leistung=leistung, benutzer=benutzer,
        beschreibung=rest.pop('beschreibung', 'Arbeit'), **rest)


# ── Rundung ──────────────────────────────────────────────────────────────────

class TestDieAufrundung:
    """Aufrundung der Summe je Leistung, ohne Datenbank."""

    @pytest.mark.parametrize('minuten, stunden', [
        (0, '0'), (1, '0.25'), (15, '0.25'), (16, '0.5'),
        (240, '4'), (425, '7.25'), (440, '7.5'),
    ])
    def test_es_wird_auf_die_viertelstunde_aufgerundet(self, minuten, stunden):
        assert services.aufgerundete_stunden(minuten) == Decimal(stunden)

    def test_das_ergebnis_ist_als_dezimalzahl_exakt(self):
        """Das Ergebnis ist als Dezimalzahl exakt, weil Viertelstunden
        0,25er Schritte sind."""
        for minuten in range(0, 24 * 60, 7):
            wert = services.aufgerundete_stunden(minuten)
            assert wert * 4 == int(wert * 4)


@pytest.mark.django_db
class TestRundenAufDieSummeIstNichtDasselbe:

    def test_zwoelf_kurze_einsaetze_kosten_die_haelfte_weniger(
        self, projekt, zeitleistung, mitarbeiter
    ):
        """Zwölf Zeilen zu 20 Minuten ergeben 4,00 Std.

        Je Zeile gerundet wären es 6,00 Std, 50 % mehr zu Lasten des Kunden.
        """
        for stunde in range(12):
            _zeile(projekt, zeitleistung, mitarbeiter,
                   von=time(6 + stunde, 0), bis=time(6 + stunde, 20))

        vorschau = services.abrechnungsvorschau(Erfassungszeile.objects.all())
        auf_die_summe = vorschau.positionen[0].menge
        je_zeile = 12 * services.aufgerundete_stunden(20)

        assert auf_die_summe == Decimal('4')
        assert je_zeile == Decimal('6')

    def test_bei_langen_bloecken_ist_es_gleich(self, projekt, zeitleistung,
                                               mitarbeiter):
        """Gegenprobe: Bei langen Blöcken ergeben beide Rundungen 7,25 Std."""
        _zeile(projekt, zeitleistung, mitarbeiter, von=time(8, 0), bis=time(11, 5))
        _zeile(projekt, zeitleistung, mitarbeiter, von=time(12, 0), bis=time(16, 0))

        vorschau = services.abrechnungsvorschau(Erfassungszeile.objects.all())

        assert vorschau.positionen[0].menge == Decimal('7.25')


# ── Vorschau ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestDieVorschau:

    def test_gruppiert_je_leistung_nicht_je_zeile(self, projekt, zeitleistung,
                                                  mengenleistung, mitarbeiter):
        """Zwölf Zeilen Montage ergeben eine Position; die Einzelzeilen stehen
        im Leistungsnachweis."""
        for stunde in (8, 10, 13):
            _zeile(projekt, zeitleistung, mitarbeiter,
                   von=time(stunde, 0), bis=time(stunde + 1, 0))
        _zeile(projekt, mengenleistung, mitarbeiter, menge=Decimal('23'))

        vorschau = services.abrechnungsvorschau(Erfassungszeile.objects.all())

        assert len(vorschau.positionen) == 2
        nach_name = {p.bezeichnung: p for p in vorschau.positionen}
        assert nach_name['Montage'].menge == Decimal('3')
        assert len(nach_name['Montage'].zeilen) == 3
        assert nach_name['Anfahrt'].menge == Decimal('23')

    def test_sie_aendert_nichts(self, projekt, zeitleistung, mitarbeiter):
        """Die Vorschau ändert nichts."""
        zeile = _zeile(projekt, zeitleistung, mitarbeiter,
                       von=time(8, 0), bis=time(9, 0))

        services.abrechnungsvorschau(Erfassungszeile.objects.all())

        assert Erfassungszeile.objects.get(pk=zeile.pk).zustand == Zustand.OFFEN
        assert not Beleg.objects.exists()

    def test_der_preis_kommt_aus_dem_katalog(self, projekt, zeitleistung,
                                             mitarbeiter):
        _zeile(projekt, zeitleistung, mitarbeiter, von=time(8, 0), bis=time(10, 0))

        position = services.abrechnungsvorschau(
            Erfassungszeile.objects.all()).positionen[0]

        assert position.einzelpreis == Decimal('68.00')
        assert position.summe == Decimal('136.00')

    def test_nicht_abrechenbares_wird_benannt(self, projekt, zeitleistung,
                                              mitarbeiter):
        """Nicht abrechenbare Zeilen werden als übergangen gemeldet."""
        zeile = _zeile(projekt, zeitleistung, mitarbeiter,
                       von=time(8, 0), bis=time(10, 0))
        Erfassungszeile.objects.filter(pk=zeile.pk).update(abrechenbar=False)

        vorschau = services.abrechnungsvorschau(Erfassungszeile.objects.all())

        assert not vorschau.positionen
        assert [g for _, g in vorschau.uebergangen] == [
            services.GRUND_NICHT_ABRECHENBAR]

    def test_ohne_umfang_wird_benannt(self, projekt, zeitleistung, mitarbeiter,
                                      zeile_ohne_umfang):
        """Zeilen ohne Umfang aus Altdaten werden als übergangen gemeldet.

        Über die Erfassung entstehen sie nicht mehr
        (``Erfassungszeile._pruefe_umfang``).
        """
        zeile_ohne_umfang(projekt, zeitleistung, mitarbeiter)

        vorschau = services.abrechnungsvorschau(Erfassungszeile.objects.all())

        assert not vorschau.positionen
        assert [g for _, g in vorschau.uebergangen] == [
            services.GRUND_OHNE_UMFANG]

    def test_schon_abgerechnetes_kommt_nicht_zweimal_mit(
        self, projekt, zeitleistung, mitarbeiter, entwurfsposition
    ):
        zeile = _zeile(projekt, zeitleistung, mitarbeiter,
                       von=time(8, 0), bis=time(9, 0))
        Erfassungszeile.objects.filter(pk=zeile.pk).update(
            abgerechnet_in=entwurfsposition)

        vorschau = services.abrechnungsvorschau(Erfassungszeile.objects.all())

        assert not vorschau.positionen
        assert vorschau.uebergangen[0][1] == services.GRUND_SCHON_ABGERECHNET

    def test_zwei_vorhaben_gehen_nicht_auf_eine_rechnung(
        self, projekt, kunde, zeitleistung, mitarbeiter
    ):
        """Zeilen aus zwei Vorhaben werden abgelehnt, weil ein Beleg ein
        Projekt hat und die Anschrift daraus kopiert wird."""
        anderes = projekt.__class__.objects.create(
            nummer='2026-099', bezeichnung='Anderswo', kunde=kunde)
        for vorhaben in (projekt, anderes):
            _zeile(vorhaben, zeitleistung, mitarbeiter,
                   von=time(8, 0), bis=time(9, 0))

        with pytest.raises(services.MehrereProjekte):
            services.abrechnungsvorschau(Erfassungszeile.objects.all())


# ── Übernahme ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestDasUebernehmen:

    def test_es_entsteht_ein_rechnungsentwurf_mit_positionen(
        self, projekt, zeitleistung, mengenleistung, mitarbeiter
    ):
        _zeile(projekt, zeitleistung, mitarbeiter, von=time(8, 0), bis=time(12, 0))
        _zeile(projekt, mengenleistung, mitarbeiter, menge=Decimal('23'))

        beleg, _ = services.in_rechnung_uebernehmen(
            zeilen=Erfassungszeile.objects.all())

        assert beleg.typ == BelegTyp.RECHNUNG
        assert beleg.status == BelegStatus.ENTWURF
        assert beleg.projekt == projekt
        assert beleg.positionen.count() == 2

    def test_die_position_bekommt_den_zeitraum_ihrer_taetigkeiten(
        self, projekt, zeitleistung, mitarbeiter
    ):
        """Die Position erhält erster und letzter Tag als Zeitraum
        (BT-134/135)."""
        heute = timezone.localdate()
        for tage_zurueck in (7, 3, 5):
            _zeile(projekt, zeitleistung, mitarbeiter, von=time(8, 0),
                   bis=time(9, 0),
                   datum=heute - timedelta(days=tage_zurueck))

        beleg, _ = services.in_rechnung_uebernehmen(
            zeilen=Erfassungszeile.objects.all())

        position = beleg.positionen.get()
        assert position.leistung_von == heute - timedelta(days=7)
        assert position.leistung_bis == heute - timedelta(days=3)

    def test_die_anschrift_wird_kopiert(self, projekt, zeitleistung,
                                        mitarbeiter, kunde):
        """Die Anschrift wird kopiert, wie bei jedem Beleg."""
        _zeile(projekt, zeitleistung, mitarbeiter, von=time(8, 0), bis=time(9, 0))

        beleg, _ = services.in_rechnung_uebernehmen(
            zeilen=Erfassungszeile.objects.all())

        assert kunde.name in beleg.empfaenger

    def test_die_zeilen_bekommen_den_vermerk(self, projekt, zeitleistung,
                                             mitarbeiter):
        zeile = _zeile(projekt, zeitleistung, mitarbeiter,
                       von=time(8, 0), bis=time(9, 0))

        beleg, _ = services.in_rechnung_uebernehmen(
            zeilen=Erfassungszeile.objects.all())

        zeile.refresh_from_db()
        # Der Verweis zeigt auf die Position, damit eine entfernte Position
        # ihre Zeilen freigibt.
        assert zeile.abgerechnet_in == beleg.positionen.get()
        assert zeile.abgerechneter_beleg == beleg
        assert zeile.zustand == Zustand.ABGERECHNET

    def test_im_entwurf_ist_die_zeile_schon_gesperrt(self, projekt,
                                                     zeitleistung, mitarbeiter):
        """Schon im Entwurf ist die Zeile gesperrt, weil Entwürfe zur Prüfung
        beim Kunden sein können (``test_zustand.TestJedeRechnungSperrt``)."""
        zeile = _zeile(projekt, zeitleistung, mitarbeiter,
                       von=time(8, 0), bis=time(9, 0))
        services.in_rechnung_uebernehmen(zeilen=Erfassungszeile.objects.all())

        with pytest.raises(services.ZeileAbgerechnet):
            services.zeile_aendern(
                zeile_id=zeile.pk, beschreibung='Genauer beschrieben')

    def test_nach_dem_festschreiben_ist_sie_gesperrt(self, projekt,
                                                     zeitleistung, mitarbeiter):
        """Nach dem Festschreiben ist die Zeile gesperrt."""
        zeile = _zeile(projekt, zeitleistung, mitarbeiter,
                       von=time(8, 0), bis=time(9, 0))
        beleg, _ = services.in_rechnung_uebernehmen(
            zeilen=Erfassungszeile.objects.all())
        Beleg.objects.filter(pk=beleg.pk).update(
            status=BelegStatus.FESTGESCHRIEBEN, nummer='2026-0117')

        with pytest.raises(services.ZeileAbgerechnet):
            services.zeile_aendern(zeile_id=zeile.pk, beschreibung='Doch nicht')

    def test_zweimal_uebernehmen_dupliziert_nichts(self, projekt, zeitleistung,
                                                   mitarbeiter):
        """Eine zweite Übernahme derselben Zeilen erzeugt nichts."""
        _zeile(projekt, zeitleistung, mitarbeiter, von=time(8, 0), bis=time(9, 0))
        services.in_rechnung_uebernehmen(zeilen=Erfassungszeile.objects.all())

        with pytest.raises(services.NichtsAbzurechnen):
            services.in_rechnung_uebernehmen(zeilen=Erfassungszeile.objects.all())

    def test_an_einen_vorhandenen_entwurf_anhaengen(self, projekt, zeitleistung,
                                                    mengenleistung, mitarbeiter):
        """Übernahme in einen vorhandenen Entwurf."""
        _zeile(projekt, zeitleistung, mitarbeiter, von=time(8, 0), bis=time(9, 0))
        beleg, _ = services.in_rechnung_uebernehmen(
            zeilen=Erfassungszeile.objects.all())
        _zeile(projekt, mengenleistung, mitarbeiter, menge=Decimal('23'))

        gleicher, _ = services.in_rechnung_uebernehmen(
            zeilen=Erfassungszeile.objects.filter(abgerechnet_in__isnull=True),
            beleg=beleg)

        assert gleicher.pk == beleg.pk
        assert beleg.positionen.count() == 2

    def test_an_eine_festgeschriebene_rechnung_geht_nicht(
        self, projekt, zeitleistung, mitarbeiter, festgeschriebene_rechnung
    ):
        _zeile(projekt, zeitleistung, mitarbeiter, von=time(8, 0), bis=time(9, 0))

        with pytest.raises(services.ZielUngeeignet):
            services.in_rechnung_uebernehmen(
                zeilen=Erfassungszeile.objects.all(),
                beleg=festgeschriebene_rechnung)

    def test_an_die_rechnung_eines_anderen_kunden_geht_nicht(
        self, projekt, zeitleistung, mitarbeiter
    ):
        """Die Sammelrechnung eines anderen Kunden wird abgelehnt; ohne
        Projekt fiele der falsche Empfänger sonst nicht auf."""
        from faktura.models import Kontakt
        fremder = Kontakt.objects.create(nummer='K-9999', name='Ganz woanders')
        fremd = Beleg.objects.create(
            typ=BelegTyp.RECHNUNG, status=BelegStatus.ENTWURF, kunde=fremder)
        _zeile(projekt, zeitleistung, mitarbeiter, von=time(8, 0), bis=time(9, 0))

        with pytest.raises(services.ZielUngeeignet):
            services.in_rechnung_uebernehmen(
                zeilen=Erfassungszeile.objects.all(), beleg=fremd)

    def test_an_die_sammelrechnung_des_richtigen_kunden_geht(
        self, projekt, zeitleistung, mitarbeiter, kunde
    ):
        """Gegenprobe: Die Sammelrechnung des richtigen Kunden ist ein
        gültiges Ziel."""
        sammel = Beleg.objects.create(
            typ=BelegTyp.RECHNUNG, status=BelegStatus.ENTWURF, kunde=kunde)
        _zeile(projekt, zeitleistung, mitarbeiter, von=time(8, 0), bis=time(9, 0))

        services.in_rechnung_uebernehmen(
            zeilen=Erfassungszeile.objects.all(), beleg=sammel)

        assert sammel.positionen.count() == 1

    def test_an_ein_angebot_geht_nicht(self, projekt, zeitleistung,
                                       mitarbeiter):
        """Ein Angebotsentwurf ist kein Ziel.

        Er gehört zum richtigen Projekt und ist änderbar, erfasste Leistung
        gehört aber auf eine Rechnung.
        """
        angebot = Beleg.objects.create(
            typ=BelegTyp.ANGEBOT, status=BelegStatus.ENTWURF, projekt=projekt)
        _zeile(projekt, zeitleistung, mitarbeiter, von=time(8, 0), bis=time(9, 0))

        with pytest.raises(services.ZielUngeeignet):
            services.in_rechnung_uebernehmen(
                zeilen=Erfassungszeile.objects.all(), beleg=angebot)

        assert angebot.positionen.count() == 0

    def test_bei_einem_fehler_bleibt_nichts_halb_stehen(
        self, projekt, kunde, zeitleistung, mitarbeiter
    ):
        """Bei einem Fehler bleibt nichts gespeichert (``transaction.atomic``)."""
        anderes = projekt.__class__.objects.create(
            nummer='2026-099', bezeichnung='Anderswo', kunde=kunde)
        for vorhaben in (projekt, anderes):
            _zeile(vorhaben, zeitleistung, mitarbeiter,
                   von=time(8, 0), bis=time(9, 0))

        with pytest.raises(services.MehrereProjekte):
            services.in_rechnung_uebernehmen(zeilen=Erfassungszeile.objects.all())

        assert not Beleg.objects.exists()
        assert not Erfassungszeile.objects.exclude(
            abgerechnet_in__isnull=True).exists()


# ── Abschlag oder Schlussrechnung ────────────────────────────────────────────

def _gestellter_abschlag(projekt, betrag='1000.00'):
    """Festgeschriebener Abschlag des Projekts, Status direkt gesetzt, weil
    das Absetzen geprüft wird und nicht das Festschreiben."""
    abschlag = faktura_services.beleg_anlegen(
        projekt=projekt, typ=BelegTyp.RECHNUNG,
        rechnungsart=Rechnungsart.ABSCHLAG, betreff='Abschlag')
    faktura_services.position_hinzufuegen(
        beleg=abschlag, bezeichnung='Abschlag', menge=Decimal('1'),
        einheit='pausch', einzelpreis=Decimal(betrag),
        steuersatz='19.00')
    Beleg.objects.filter(pk=abschlag.pk).update(
        status=BelegStatus.FESTGESCHRIEBEN, nummer='2026-0901',
        belegdatum=timezone.localdate())
    return abschlag


@pytest.mark.django_db
class TestDieRechnungsart:
    """Beim Übernehmen lässt sich eine gewöhnliche, eine Abschlags- oder eine
    Schlussrechnung neu anlegen."""

    def test_eine_neue_abschlagsrechnung(self, projekt, zeitleistung,
                                         mitarbeiter):
        _zeile(projekt, zeitleistung, mitarbeiter, von=time(8, 0), bis=time(12, 0))

        beleg, _ = services.in_rechnung_uebernehmen(
            zeilen=Erfassungszeile.objects.all(),
            rechnungsart=Rechnungsart.ABSCHLAG)

        assert beleg.rechnungsart == Rechnungsart.ABSCHLAG
        assert beleg.status == BelegStatus.ENTWURF
        assert beleg.positionen.count() == 1

    def test_eine_neue_schlussrechnung(self, projekt, zeitleistung,
                                       mitarbeiter):
        _zeile(projekt, zeitleistung, mitarbeiter, von=time(8, 0), bis=time(12, 0))

        beleg, _ = services.in_rechnung_uebernehmen(
            zeilen=Erfassungszeile.objects.all(),
            rechnungsart=Rechnungsart.SCHLUSS)

        assert beleg.rechnungsart == Rechnungsart.SCHLUSS
        assert not beleg.positionen.filter(ist_abzug=True).exists()

    def test_die_schlussrechnung_setzt_die_abschlaege_ab(
            self, projekt, zeitleistung, mitarbeiter):
        """Die neue Schlussrechnung setzt gestellte Abschläge ab."""
        abschlag = _gestellter_abschlag(projekt)
        _zeile(projekt, zeitleistung, mitarbeiter, von=time(8, 0), bis=time(12, 0))

        beleg, _ = services.in_rechnung_uebernehmen(
            zeilen=Erfassungszeile.objects.all(),
            rechnungsart=Rechnungsart.SCHLUSS)

        # Solange der Abschlag nicht bezahlt ist, kommt eine Restzeile hinzu;
        # gesucht wird deshalb die Absetzung.
        abzug = beleg.positionen.get(
            abgesetzte_position=abschlag.positionen.get(),
            einzelpreis__lt=0)
        assert abzug.einzelpreis == Decimal('-1000.00')

    def test_eine_gewoehnliche_rechnung_setzt_nichts_ab(
            self, projekt, zeitleistung, mitarbeiter):
        _gestellter_abschlag(projekt)
        _zeile(projekt, zeitleistung, mitarbeiter, von=time(8, 0), bis=time(12, 0))

        beleg, _ = services.in_rechnung_uebernehmen(
            zeilen=Erfassungszeile.objects.all())

        assert beleg.rechnungsart == Rechnungsart.NORMAL
        assert not beleg.positionen.filter(ist_abzug=True).exists()

    def test_keine_teilschlussrechnung(self, projekt, zeitleistung,
                                       mitarbeiter):
        """Keine Teilschlussrechnung, weil sie nur aus einer Teilabnahme
        entsteht."""
        _zeile(projekt, zeitleistung, mitarbeiter, von=time(8, 0), bis=time(12, 0))

        with pytest.raises(services.ErfassungError):
            services.in_rechnung_uebernehmen(
                zeilen=Erfassungszeile.objects.all(),
                rechnungsart=Rechnungsart.TEILSCHLUSS)

        assert not Beleg.objects.exists()
        assert Erfassungszeile.objects.get().abgerechnet_in is None


# ── Listenaktion ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestDieAktion:

    def _ausloesen(self, client, zeilen, folgen=False, **rest):
        daten = {
            'action': 'in_rechnung',
            '_selected_action': [str(z.pk) for z in zeilen],
            'index': '0',
        }
        daten.update(rest)
        return client.post(reverse(LISTE), daten, follow=folgen)

    @pytest.fixture
    def zeilen(self, projekt, zeitleistung, mitarbeiter):
        _zeile(projekt, zeitleistung, mitarbeiter, von=time(8, 0), bis=time(12, 0))
        return list(Erfassungszeile.objects.all())

    def test_der_erste_klick_zeigt_die_vorschau_und_schreibt_nichts(
        self, als_abrechner, zeilen
    ):
        antwort = self._ausloesen(als_abrechner, zeilen)
        inhalt = antwort.content.decode()

        assert antwort.status_code == 200
        assert 'Das wird daraus' in inhalt
        assert 'Montage' in inhalt
        assert not Beleg.objects.exists()

    def test_die_vorschau_zeigt_die_rohzeit_neben_der_gerundeten_menge(
        self, als_abrechner, projekt, zeitleistung, mitarbeiter
    ):
        """Die Vorschau zeigt die ungerundete Zeit neben der gerundeten
        Menge."""
        _zeile(projekt, zeitleistung, mitarbeiter, von=time(8, 0), bis=time(8, 20))

        antwort = self._ausloesen(als_abrechner, Erfassungszeile.objects.all())
        inhalt = antwort.content.decode()

        assert '0:20' in inhalt
        assert '0,5' in inhalt

    def test_der_zweite_klick_schreibt(self, als_abrechner, zeilen, projekt):
        antwort = self._ausloesen(als_abrechner, zeilen, bestaetigt='ja')

        assert antwort.status_code == 302
        beleg = Beleg.objects.get()
        assert beleg.projekt == projekt
        assert beleg.positionen.count() == 1
        assert Erfassungszeile.objects.get().abgerechneter_beleg == beleg

    def test_in_einen_vorhandenen_entwurf(self, als_abrechner, zeilen,
                                          rechnungsentwurf, projekt):
        rechnungsentwurf.projekt = projekt
        rechnungsentwurf.save()

        self._ausloesen(als_abrechner, zeilen, bestaetigt='ja',
                        ziel=str(rechnungsentwurf.pk))

        assert Beleg.objects.count() == 1
        assert rechnungsentwurf.positionen.count() == 1

    def test_die_auswahl_bietet_alle_drei_arten_an(self, als_abrechner,
                                                   zeilen):
        inhalt = self._ausloesen(als_abrechner, zeilen).content.decode()

        assert 'Neuen Rechnungsentwurf anlegen' in inhalt
        assert 'value="neu-abschlag"' in inhalt
        assert 'value="neu-schluss"' in inhalt
        assert 'Teilschluss' not in inhalt

    @pytest.mark.parametrize('ziel, art', [
        ('', Rechnungsart.NORMAL),
        ('neu-abschlag', Rechnungsart.ABSCHLAG),
        ('neu-schluss', Rechnungsart.SCHLUSS),
    ])
    def test_die_gewaehlte_art_entsteht(self, als_abrechner, zeilen,
                                         ziel, art):
        antwort = self._ausloesen(als_abrechner, zeilen, bestaetigt='ja',
                                  ziel=ziel)

        assert antwort.status_code == 302
        beleg = Beleg.objects.get()
        assert beleg.rechnungsart == art
        assert Erfassungszeile.objects.get().abgerechneter_beleg == beleg

    def test_eine_untergeschobene_art_wird_nicht_genommen(
            self, als_abrechner, zeilen):
        self._ausloesen(als_abrechner, zeilen, bestaetigt='ja',
                        ziel='neu-teilschluss')

        assert not Beleg.objects.exists()

    def test_ein_abschlagsentwurf_heisst_auch_so(self, als_abrechner, zeilen,
                                                 projekt):
        """Ein Abschlagsentwurf heißt in der Auswahl Abschlagsrechnung."""
        entwurf = Beleg.objects.create(
            typ=BelegTyp.RECHNUNG, status=BelegStatus.ENTWURF,
            rechnungsart=Rechnungsart.ABSCHLAG, projekt=projekt)

        inhalt = self._ausloesen(als_abrechner, zeilen).content.decode()

        assert f'Abschlagsrechnung (Entwurf {entwurf.pk})' in inhalt

    def test_ein_untergeschobenes_ziel_wird_nicht_genommen(
        self, als_abrechner, zeilen, projekt
    ):
        """Ein nicht angebotenes Ziel wird abgelehnt.

        Die ID kommt aus dem Request und wird nur unter den angebotenen
        Entwürfen gesucht. Geprüft mit einem Angebotsentwurf desselben
        Vorhabens, den Maske und Service ablehnen.
        """
        angebot = Beleg.objects.create(
            typ=BelegTyp.ANGEBOT, status=BelegStatus.ENTWURF, projekt=projekt)

        self._ausloesen(als_abrechner, zeilen, bestaetigt='ja',
                        ziel=str(angebot.pk))

        assert angebot.positionen.count() == 0
        assert Erfassungszeile.objects.get().abgerechnet_in is None

    def test_ein_monteur_bekommt_die_aktion_gar_nicht_erst(self, als_monteur,
                                                           zeilen):
        """Ohne Recht auf Belege fehlt die Aktion und ist damit auch per POST
        nicht ausführbar, weil Django nur Aktionen aus ``get_actions``
        ausführt."""
        inhalt = als_monteur.get(reverse(LISTE)).content.decode()
        assert 'In Rechnung übernehmen' not in inhalt

        self._ausloesen(als_monteur, zeilen, bestaetigt='ja')

        assert not Beleg.objects.exists()

    def test_der_abrechner_sieht_sie(self, als_abrechner, zeilen):
        """Gegenprobe: Mit Recht auf Belege erscheint die Aktion."""
        inhalt = als_abrechner.get(reverse(LISTE)).content.decode()

        assert 'In Rechnung übernehmen' in inhalt

    def test_eine_sammelrechnung_des_kunden_steht_zur_wahl(
        self, als_abrechner, zeilen, projekt, kunde
    ):
        """Sammelrechnungen des Kunden ohne Projekt stehen zur Wahl.

        Ein Beleg hat entweder ein Projekt oder einen Kunden; eine
        Sammelrechnung hat kein Projekt und fehlte sonst in der Auswahl.
        """
        sammel = Beleg.objects.create(
            typ=BelegTyp.RECHNUNG, status=BelegStatus.ENTWURF, kunde=kunde)

        inhalt = self._ausloesen(als_abrechner, zeilen).content.decode()

        assert f'value="{sammel.pk}"' in inhalt

    def test_die_auswahl_nennt_den_empfaenger(self, als_abrechner, zeilen,
                                              kunde):
        """Die Auswahl nennt den Empfänger, weil ``str(beleg)`` nur "Rechnung
        (Entwurf 10)" ergibt."""
        Beleg.objects.create(typ=BelegTyp.RECHNUNG,
                             status=BelegStatus.ENTWURF, kunde=kunde)

        inhalt = self._ausloesen(als_abrechner, zeilen).content.decode()

        assert kunde.name in inhalt

    def test_die_sammelrechnung_eines_fremden_kunden_nicht(
        self, als_abrechner, zeilen
    ):
        """Sammelrechnungen anderer Kunden stehen nicht zur Wahl."""
        from faktura.models import Kontakt
        fremder = Kontakt.objects.create(nummer='K-9999', name='Ganz woanders')
        fremd = Beleg.objects.create(
            typ=BelegTyp.RECHNUNG, status=BelegStatus.ENTWURF, kunde=fremder)

        inhalt = self._ausloesen(als_abrechner, zeilen).content.decode()
        assert f'value="{fremd.pk}"' not in inhalt

        self._ausloesen(als_abrechner, zeilen, bestaetigt='ja',
                        ziel=str(fremd.pk))
        assert fremd.positionen.count() == 0

    def test_der_leistungsnachweis_oeffnet_einen_neuen_reiter(
        self, als_abrechner, zeilen
    ):
        """Der Leistungsnachweis öffnet in einem neuen Tab.

        Die Aktionsleiste hat einen Submit-Button für alle Aktionen; das
        Formularziel richtet sich nach der gewählten Aktion, die Liste
        dieser Aktionen steht in Python.
        """
        inhalt = als_abrechner.get(reverse(LISTE)).content.decode()

        # Gelesen wird der JSON-Block, weil "in_rechnung" auch in der
        # Aktionsauswahl steht.
        assert json_daten(inhalt, 'aktionen-neues-fenster') == [
            'leistungsnachweis', 'leistungsnachweis_kompakt']

    def test_zwei_vorhaben_werden_gemeldet_statt_gemischt(
        self, als_abrechner, projekt, kunde, zeitleistung, mitarbeiter
    ):
        anderes = projekt.__class__.objects.create(
            nummer='2026-099', bezeichnung='Anderswo', kunde=kunde)
        for vorhaben in (projekt, anderes):
            _zeile(vorhaben, zeitleistung, mitarbeiter,
                   von=time(8, 0), bis=time(9, 0))

        antwort = self._ausloesen(als_abrechner, Erfassungszeile.objects.all(),
                                  folgen=True)

        assert 'mehrere Projekte' in antwort.content.decode()
        assert not Beleg.objects.exists()


@pytest.mark.django_db
class TestDerWegVomBelegAus:
    """Detailaktion "Erbrachte Leistungen hinzufügen" am Beleg.

    Gegenstück zur Listenaktion: Die Detailaktion füllt eine bestimmte
    Rechnung, die Listenaktion rechnet eine Auswahl ab. Beide rufen
    ``in_rechnung_uebernehmen`` auf und durchlaufen dieselben Prüfungen.
    """

    @pytest.fixture
    def als_abrechner(self, als_abrechner, kollege):
        """Zusätzlich Rechte am Proxy-Modell.

        ``als_abrechner`` hat Rechte am Basismodell ``Beleg``; der Admin
        prüft am Proxy (``change_abschlagsrechnung``), weil jede Belegart
        eigene Rechte hat.
        """
        kollege.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='faktura',
            codename__contains='abschlagsrechnung',
        ))
        # Den Rechte-Cache am User leeren; er entsteht beim ersten has_perm()
        # und existiert deshalb nicht immer.
        for speicher in ('_perm_cache', '_user_perm_cache', '_group_perm_cache'):
            kollege.__dict__.pop(speicher, None)
        return als_abrechner

    @pytest.fixture
    def abschlag(self, projekt):
        from faktura import services as faktura_services
        from faktura.models import Rechnungsart

        return faktura_services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG,
            rechnungsart=Rechnungsart.ABSCHLAG, betreff='1. Abschlag')

    @staticmethod
    def _adresse(beleg):
        return reverse('admin:faktura_abschlagsrechnung_detail_leistungen',
                       args=[beleg.pk])

    def test_die_auswahl_zeigt_auftrag_position_und_person(
        self, als_abrechner, projekt, auftragsposition, kollege, abschlag
    ):
        services.zeile_erfassen(
            projekt=projekt, auftragsposition=auftragsposition,
            benutzer=kollege, von=time(8, 0), bis=time(12, 0),
            beschreibung='Entwurfsplanung')

        inhalt = als_abrechner.get(self._adresse(abschlag)).content.decode()

        assert auftragsposition.beleg.nummer in inhalt
        assert auftragsposition.bezeichnung in inhalt
        assert 'data-ebene="person"' in inhalt
        assert 'data-ebene="zeile"' in inhalt

    def test_das_uebernehmen_traegt_den_auftragsbezug_mit(
        self, als_abrechner, projekt, auftragsposition, kollege, abschlag
    ):
        """Die Rechnungsposition verweist auf die Auftragsposition und hat
        deren Preis."""
        for tag in (1, 2):
            services.zeile_erfassen(
                projekt=projekt, auftragsposition=auftragsposition,
                benutzer=kollege, von=time(8, 0), bis=time(12, 0),
                beschreibung=f'Tag {tag}')
        kennungen = [str(z.pk) for z in Erfassungszeile.objects.all()]

        antwort = als_abrechner.post(self._adresse(abschlag),
                                     {'zeile': kennungen})

        assert antwort.status_code == 302
        position = abschlag.positionen.get()
        assert position.auftragsposition == auftragsposition
        assert position.menge == Decimal('8')
        assert position.einzelpreis == Decimal('95.00')
        assert all(z.ist_gesperrt for z in Erfassungszeile.objects.all())

    def test_eine_zeile_eines_fremden_vorhabens_wird_nicht_untergeschoben(
        self, als_abrechner, projekt, kunde, zeitleistung, kollege, abschlag
    ):
        """Eine Zeile eines anderen Vorhabens wird abgelehnt.

        Die IDs kommen aus dem Request; die Maske übernimmt nur angebotene
        Zeilen, wie bei der Zielauswahl der Erfassungsliste. Der Service
        prüft zusätzlich.
        """
        from faktura.models import Projekt

        anderes = Projekt.objects.create(
            nummer='2026-099', bezeichnung='Ganz woanders', kunde=kunde)
        fremd = services.zeile_erfassen(
            projekt=anderes, leistung=zeitleistung, benutzer=kollege,
            von=time(8, 0), bis=time(9, 0), beschreibung='Fremd')

        antwort = als_abrechner.post(self._adresse(abschlag),
                                     {'zeile': [str(fremd.pk)]})

        # Geprüft, damit der Test nicht besteht, wenn die Seite schon an der
        # Rechteprüfung scheitert.
        assert antwort.status_code == 302
        assert abschlag.positionen.count() == 0
        fremd.refresh_from_db()
        assert fremd.zustand == Zustand.OFFEN

    def test_was_schon_auf_einer_rechnung_liegt_steht_nicht_zur_wahl(
        self, als_abrechner, projekt, auftragsposition, kollege, abschlag
    ):
        """Zeilen auf einer Rechnung stehen nicht zur Wahl."""
        zeile = services.zeile_erfassen(
            projekt=projekt, auftragsposition=auftragsposition,
            benutzer=kollege, von=time(8, 0), bis=time(12, 0),
            beschreibung='Schon abgerechnet')
        services.in_rechnung_uebernehmen(zeilen=Erfassungszeile.objects.all())

        inhalt = als_abrechner.get(self._adresse(abschlag)).content.decode()

        assert f'value="{zeile.pk}"' not in inhalt
        assert 'Nichts offen' in inhalt
