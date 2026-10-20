"""Zahlungseingänge, Zuordnung und offene Posten.

Die offenen Posten bestimmen, wer gemahnt wird. Geprüft wird jede Größe
einzeln (Rechenregister R-141 bis R-152) sowie die drei Fälle der
Zwischentabelle: Sammelüberweisung, Teilzahlung, Skonto.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from faktura import services
from faktura.models import (
    Beleg,
    BelegStatus,
    BelegTyp,
    Kontakt,
    Zahlung,
    Zahlungszuordnung,
)

HEUTE = timezone.localdate()

User = get_user_model()


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-1000', name='Muster GmbH',
        strasse='Hauptstraße 1', plz='10115', ort='Berlin',
        zahlungsziel_tage=14,
    )


def _rechnung(kunde, *, netto='1000.00', betreff='Leistungen'):
    """Festgeschriebene Rechnung über einen runden Nettobetrag.

    Festgeschrieben, weil ``offener_betrag`` sonst 0 liefert. 1.000 netto
    ergeben 1.190 brutto.
    """
    beleg = services.beleg_anlegen(
        kunde=kunde, typ=BelegTyp.RECHNUNG, betreff=betreff)
    beleg.leistungsdatum = HEUTE
    beleg.save()
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Beratung', menge=Decimal('1'),
        einzelpreis=Decimal(netto), steuersatz='19.00', einheit='psch')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


@pytest.fixture
def rechnung(kunde):
    return _rechnung(kunde)


def _faellig_setzen(beleg, tag):
    """Ändert die Fälligkeit über ``update()``.

    Weil ``save()`` am festgeschriebenen Beleg ablehnt; ebenso die Fixture
    ``ueberfaellig`` in conftest.
    """
    Beleg.objects.filter(pk=beleg.pk).update(faellig_am=tag)
    beleg.refresh_from_db()
    return beleg


def _zahlung(kunde, betrag, **felder):
    return Zahlung.objects.create(
        datum=felder.pop('datum', HEUTE), betrag=Decimal(betrag),
        kunde=kunde, **felder)


# ══════════════════════════════════════════════════════════════════════════
# Zahlung
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestDerZahlungskopf:
    """R-141 bis R-143: verteilt, Rest, vollständig verteilt.

    Wie bei ``Eingangsrechnung``: Die Zahlung enthält den gezahlten Betrag,
    nicht Zugeordnetes erscheint als Rest.
    """

    def test_ohne_zuordnung_ist_alles_rest(self, kunde):
        zahlung = _zahlung(kunde, '1190.00')

        assert zahlung.zugeordnet == Decimal('0.00')
        assert zahlung.rest == Decimal('1190.00')
        assert zahlung.ist_verteilt is False

    def test_vollstaendig_zugeordnet_laesst_keinen_rest(self, kunde, rechnung):
        zahlung = _zahlung(kunde, '1190.00')
        Zahlungszuordnung.objects.create(
            zahlung=zahlung, beleg=rechnung, betrag=Decimal('1190.00'))

        assert zahlung.zugeordnet == Decimal('1190.00')
        assert zahlung.rest == Decimal('0.00')
        assert zahlung.ist_verteilt is True

    def test_der_rest_einer_teilweise_verteilten_zahlung(self, kunde, rechnung):
        """4.000 gezahlt, 1.190 zugeordnet: Rest 2.810."""
        zahlung = _zahlung(kunde, '4000.00')
        Zahlungszuordnung.objects.create(
            zahlung=zahlung, beleg=rechnung, betrag=Decimal('1190.00'))

        assert zahlung.zugeordnet == Decimal('1190.00')
        assert zahlung.rest == Decimal('2810.00')

    def test_skonto_verbraucht_nichts_von_der_zahlung(self, kunde, rechnung):
        """Skonto verbraucht nichts von der Zahlung.

        1.150 gezahlt, 40 Skonto auf 1.190: ``zugeordnet`` ist 1.150. Mit
        Skonto erschiene die Zahlung überzahlt.
        """
        zahlung = _zahlung(kunde, '1150.00')
        Zahlungszuordnung.objects.create(
            zahlung=zahlung, beleg=rechnung,
            betrag=Decimal('1150.00'), skonto=Decimal('40.00'))

        assert zahlung.zugeordnet == Decimal('1150.00')
        assert zahlung.rest == Decimal('0.00')


@pytest.mark.django_db
class TestDerAusgleichEinerZeile:
    """R-144: Ausgleich einer Zuordnung."""

    def test_ohne_skonto_ist_der_ausgleich_der_betrag(self, kunde, rechnung):
        zuordnung = Zahlungszuordnung.objects.create(
            zahlung=_zahlung(kunde, '500.00'), beleg=rechnung,
            betrag=Decimal('500.00'))

        assert zuordnung.ausgleich == Decimal('500.00')

    def test_mit_skonto_ist_er_die_summe_aus_beidem(self, kunde, rechnung):
        zuordnung = Zahlungszuordnung.objects.create(
            zahlung=_zahlung(kunde, '1150.00'), beleg=rechnung,
            betrag=Decimal('1150.00'), skonto=Decimal('40.00'))

        assert zuordnung.ausgleich == Decimal('1190.00')


# ══════════════════════════════════════════════════════════════════════════
# Stand der Rechnung
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestDerStandEinerRechnung:
    """R-145 bis R-148: bezahlt, ausgeglichen, offen, erledigt."""

    def test_eine_unbezahlte_rechnung_ist_ganz_offen(self, rechnung):
        assert rechnung.bezahlt == Decimal('0.00')
        assert rechnung.ausgeglichen == Decimal('0.00')
        assert rechnung.offener_betrag == Decimal('1190.00')
        assert rechnung.ist_bezahlt is False

    def test_die_volle_zahlung_gleicht_sie_aus(self, kunde, rechnung):
        Zahlungszuordnung.objects.create(
            zahlung=_zahlung(kunde, '1190.00'), beleg=rechnung,
            betrag=Decimal('1190.00'))

        assert rechnung.offener_betrag == Decimal('0.00')
        assert rechnung.ist_bezahlt is True

    def test_bezahlt_und_ausgeglichen_gehen_bei_skonto_auseinander(
            self, kunde, rechnung):
        """Bei Skonto unterscheiden sich ``bezahlt`` (für den Kontoabgleich)
        und ``ausgeglichen`` (für das Mahnwesen)."""
        Zahlungszuordnung.objects.create(
            zahlung=_zahlung(kunde, '1150.00'), beleg=rechnung,
            betrag=Decimal('1150.00'), skonto=Decimal('40.00'))

        assert rechnung.bezahlt == Decimal('1150.00')
        assert rechnung.ausgeglichen == Decimal('1190.00')
        assert rechnung.offener_betrag == Decimal('0.00')
        assert rechnung.ist_bezahlt is True

    def test_teilzahlung_laesst_den_rest_stehen(self, kunde, rechnung):
        Zahlungszuordnung.objects.create(
            zahlung=_zahlung(kunde, '500.00'), beleg=rechnung,
            betrag=Decimal('500.00'))

        assert rechnung.offener_betrag == Decimal('690.00')
        assert rechnung.ist_bezahlt is False

    def test_zwei_teilzahlungen_gleichen_sie_zusammen_aus(self, kunde, rechnung):
        """Mehrere Zahlungen auf eine Rechnung (Raten)."""
        Zahlungszuordnung.objects.create(
            zahlung=_zahlung(kunde, '500.00'), beleg=rechnung,
            betrag=Decimal('500.00'))
        Zahlungszuordnung.objects.create(
            zahlung=_zahlung(kunde, '690.00'), beleg=rechnung,
            betrag=Decimal('690.00'))

        assert rechnung.bezahlt == Decimal('1190.00')
        assert rechnung.offener_betrag == Decimal('0.00')

    def test_die_sammelueberweisung_trifft_zwei_rechnungen(self, kunde):
        """Eine Zahlung auf mehrere Rechnungen (Sammelüberweisung).

        Grund für die Zwischentabelle; ein Boolean "bezahlt" an der Rechnung
        bildete die Verteilung nicht ab.
        """
        eine = _rechnung(kunde, netto='1000.00', betreff='Erste')
        andere = _rechnung(kunde, netto='2000.00', betreff='Zweite')
        zahlung = _zahlung(kunde, '3570.00')

        Zahlungszuordnung.objects.create(
            zahlung=zahlung, beleg=eine, betrag=Decimal('1190.00'))
        Zahlungszuordnung.objects.create(
            zahlung=zahlung, beleg=andere, betrag=Decimal('2380.00'))

        assert zahlung.rest == Decimal('0.00')
        assert eine.offener_betrag == Decimal('0.00')
        assert andere.offener_betrag == Decimal('0.00')

    def test_ein_entwurf_fordert_nichts(self, kunde):
        """Ein Entwurf hat offenen Betrag 0, weil er keine Forderung ist."""
        entwurf = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Noch in Arbeit')
        services.position_hinzufuegen(
            beleg=entwurf, bezeichnung='Beratung', menge=Decimal('1'),
            einzelpreis=Decimal('1000.00'), steuersatz='19.00')

        assert entwurf.offener_betrag == Decimal('0.00')
        assert entwurf.ist_bezahlt is False

    def test_ein_angebot_fordert_nichts(self, kunde):
        angebot = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.ANGEBOT, betreff='Unverbindlich')

        assert angebot.offener_betrag == Decimal('0.00')
        assert angebot.ist_bezahlt is False

    def test_eine_stornierte_rechnung_fordert_nichts_mehr(self, kunde, rechnung):
        rechnung.status = BelegStatus.STORNIERT
        rechnung.save(update_fields=['status'])

        assert rechnung.offener_betrag == Decimal('0.00')


# ══════════════════════════════════════════════════════════════════════════
# Validierung
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestWasAbgewiesenWird:
    """Die vier Prüfungen aus ``Zahlungszuordnung.clean``."""

    def test_mehr_verteilen_als_ueberwiesen_wurde(self, kunde, rechnung):
        zuordnung = Zahlungszuordnung(
            zahlung=_zahlung(kunde, '500.00'), beleg=rechnung,
            betrag=Decimal('600.00'))

        with pytest.raises(ValidationError) as fehler:
            zuordnung.full_clean()

        assert 'nur noch' in str(fehler.value)

    def test_mehr_ausgleichen_als_gefordert_wird(self, kunde, rechnung):
        zuordnung = Zahlungszuordnung(
            zahlung=_zahlung(kunde, '2000.00'), beleg=rechnung,
            betrag=Decimal('1500.00'))

        with pytest.raises(ValidationError):
            zuordnung.full_clean()

    def test_auf_einen_entwurf_wird_nicht_gezahlt(self, kunde):
        entwurf = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Noch in Arbeit')
        zuordnung = Zahlungszuordnung(
            zahlung=_zahlung(kunde, '100.00'), beleg=entwurf,
            betrag=Decimal('100.00'))

        with pytest.raises(ValidationError) as fehler:
            zuordnung.full_clean()

        assert 'festgeschrieben' in str(fehler.value)

    def test_nur_rechnungen_nehmen_zahlungen_an(self, kunde):
        angebot = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.ANGEBOT, betreff='Unverbindlich')
        zuordnung = Zahlungszuordnung(
            zahlung=_zahlung(kunde, '100.00'), beleg=angebot,
            betrag=Decimal('100.00'))

        with pytest.raises(ValidationError) as fehler:
            zuordnung.full_clean()

        assert 'nur Rechnungen' in str(fehler.value)

    def test_die_eigene_zeile_zaehlt_beim_aendern_nicht_mit(self, kunde, rechnung):
        """Beim Ändern zählt die eigene Zeile nicht mit (``ausser``).

        Sonst zählte eine Zuordnung über 1.190 sich selbst und meldete die
        Rechnung als ausgeglichen.
        """
        zuordnung = Zahlungszuordnung.objects.create(
            zahlung=_zahlung(kunde, '1190.00'), beleg=rechnung,
            betrag=Decimal('1190.00'))

        zuordnung.notiz = 'Nachgetragen'
        zuordnung.full_clean()  # darf nicht werfen
        zuordnung.save()

        assert rechnung.offener_betrag == Decimal('0.00')


# ══════════════════════════════════════════════════════════════════════════
# Offene Posten
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestOffenePosten:
    """R-149 bis R-152: Liste der offenen Posten."""

    def test_eine_unbezahlte_rechnung_steht_darin(self, rechnung):
        stand = services.offene_posten()

        assert stand.anzahl == 1
        assert stand.posten[0].beleg == rechnung
        assert stand.posten[0].brutto == Decimal('1190.00')
        assert stand.posten[0].bezahlt == Decimal('0.00')
        assert stand.posten[0].offen == Decimal('1190.00')
        assert stand.offen == Decimal('1190.00')

    def test_eine_bezahlte_rechnung_verschwindet(self, kunde, rechnung):
        Zahlungszuordnung.objects.create(
            zahlung=_zahlung(kunde, '1190.00'), beleg=rechnung,
            betrag=Decimal('1190.00'))

        assert services.offene_posten().anzahl == 0

    def test_eine_teilzahlung_laesst_den_rest_in_der_liste(self, kunde, rechnung):
        Zahlungszuordnung.objects.create(
            zahlung=_zahlung(kunde, '500.00'), beleg=rechnung,
            betrag=Decimal('500.00'))

        posten = services.offene_posten().posten[0]

        assert posten.brutto == Decimal('1190.00')
        assert posten.bezahlt == Decimal('500.00')
        assert posten.offen == Decimal('690.00')

    def test_entwuerfe_stehen_nie_darin(self, kunde):
        services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Noch in Arbeit')

        assert services.offene_posten().anzahl == 0

    def test_stornierte_bleiben_draussen(self, rechnung):
        rechnung.status = BelegStatus.STORNIERT
        rechnung.save(update_fields=['status'])

        assert services.offene_posten().anzahl == 0

    def test_die_summe_geht_ueber_alle_posten(self, kunde):
        _rechnung(kunde, netto='1000.00', betreff='Erste')
        _rechnung(kunde, netto='2000.00', betreff='Zweite')

        stand = services.offene_posten()

        assert stand.anzahl == 2
        assert stand.offen == Decimal('3570.00')

    def test_ueberfaellig_zaehlt_ab_dem_tag_nach_der_faelligkeit(self, rechnung):
        """Überfällig ab dem Tag nach ``faellig_am``."""
        stichtag = rechnung.faellig_am

        posten = services.offene_posten(stichtag=stichtag).posten[0]

        assert posten.tage_ueberfaellig == 0
        assert posten.ist_ueberfaellig is False

    def test_eine_woche_spaeter_sind_es_sieben_tage(self, rechnung):
        stichtag = rechnung.faellig_am + timedelta(days=7)

        posten = services.offene_posten(stichtag=stichtag).posten[0]

        assert posten.tage_ueberfaellig == 7
        assert posten.ist_ueberfaellig is True

    def test_vor_der_faelligkeit_ist_die_zahl_negativ(self, rechnung):
        """Vor Fälligkeit ist der Wert negativ. Verworfen: Begrenzung auf 0,
        die zehn Tage vor und am Tag der Fälligkeit gleich darstellte."""
        stichtag = rechnung.faellig_am - timedelta(days=10)

        posten = services.offene_posten(stichtag=stichtag).posten[0]

        assert posten.tage_ueberfaellig == -10
        assert posten.ist_ueberfaellig is False

    def test_die_ueberfaellige_summe_zaehlt_nur_die_ueberfaelligen(self, kunde):
        """Die Summe der überfälligen enthält nur überfällige Rechnungen."""
        alt = _faellig_setzen(_rechnung(kunde, netto='1000.00', betreff='Alt'),
                              HEUTE - timedelta(days=30))
        _faellig_setzen(_rechnung(kunde, netto='2000.00', betreff='Neu'),
                        HEUTE + timedelta(days=10))

        stand = services.offene_posten()

        assert stand.offen == Decimal('3570.00')
        assert [p.beleg for p in stand.ueberfaellig] == [alt]
        assert stand.offen_ueberfaellig == Decimal('1190.00')

    def test_das_aelteste_steht_oben(self, kunde):
        alt = _faellig_setzen(_rechnung(kunde, netto='1000.00', betreff='Alt'),
                              HEUTE - timedelta(days=60))
        jung = _faellig_setzen(_rechnung(kunde, netto='1000.00', betreff='Jung'),
                               HEUTE - timedelta(days=5))

        stand = services.offene_posten()

        assert [p.beleg for p in stand.posten] == [alt, jung]

    def test_ohne_rechnungen_ist_die_liste_leer(self, db):
        stand = services.offene_posten()

        assert stand.anzahl == 0
        assert stand.offen == Decimal('0.00')
        assert stand.offen_ueberfaellig == Decimal('0.00')


@pytest.mark.django_db
class TestDieFestschreibungBleibtUnberuehrt:
    """Zahlungen ändern die festgeschriebene Rechnung nicht.

    Der Zahlungsstand wird aus den Zuordnungen berechnet. Verworfen: eine
    Spalte ``bezahlt_am``, die bei jedem Zahlungseingang geschrieben
    würde.
    """

    def test_eine_zahlung_aendert_den_beleg_nicht(self, kunde, rechnung):
        vorher = {
            'nummer': rechnung.nummer,
            'status': rechnung.status,
            'geaendert_am': rechnung.geaendert_am,
            'pdf_sha256': rechnung.pdf_sha256,
        }

        Zahlungszuordnung.objects.create(
            zahlung=_zahlung(kunde, '1190.00'), beleg=rechnung,
            betrag=Decimal('1190.00'))

        rechnung.refresh_from_db()
        assert rechnung.nummer == vorher['nummer']
        assert rechnung.status == vorher['status']
        assert rechnung.geaendert_am == vorher['geaendert_am']
        assert rechnung.pdf_sha256 == vorher['pdf_sha256']
        assert rechnung.ist_bezahlt is True


# ══════════════════════════════════════════════════════════════════════════
# Rechnungsliste im Admin
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestDerZahlungsstandInDerListe:
    """Spalte "Offen" und Filter des Zahlungsstands in der Rechnungsliste.

    Der Filter wird über den Request ausgelöst, nicht im HTML gesucht.
    """

    def test_die_spalte_zeigt_den_offenen_betrag(self, buero, kunde, rechnung):
        antwort = buero.get(reverse('admin:faktura_rechnung_changelist'))

        assert antwort.status_code == 200
        assert '1.190,00' in antwort.content.decode()

    def test_der_filter_offen_findet_die_unbezahlte(self, buero, rechnung):
        antwort = buero.get(reverse('admin:faktura_rechnung_changelist'),
                            {'zahlungsstand': 'offen'})

        assert list(antwort.context['cl'].queryset) == [rechnung]

    def test_der_filter_offen_laesst_die_bezahlte_heraus(
            self, buero, kunde, rechnung):
        Zahlungszuordnung.objects.create(
            zahlung=_zahlung(kunde, '1190.00'), beleg=rechnung,
            betrag=Decimal('1190.00'))

        antwort = buero.get(reverse('admin:faktura_rechnung_changelist'),
                            {'zahlungsstand': 'offen'})

        assert list(antwort.context['cl'].queryset) == []

    def test_der_filter_bezahlt_findet_sie(self, buero, kunde, rechnung):
        Zahlungszuordnung.objects.create(
            zahlung=_zahlung(kunde, '1190.00'), beleg=rechnung,
            betrag=Decimal('1190.00'))

        antwort = buero.get(reverse('admin:faktura_rechnung_changelist'),
                            {'zahlungsstand': 'bezahlt'})

        assert list(antwort.context['cl'].queryset) == [rechnung]

    def test_der_filter_ueberfaellig_zaehlt_die_frist(self, buero, kunde):
        puenktlich = _rechnung(kunde, betreff='Noch Zeit')
        _faellig_setzen(puenktlich, HEUTE + timedelta(days=10))
        spaet = _rechnung(kunde, betreff='Schon lange')
        _faellig_setzen(spaet, HEUTE - timedelta(days=30))

        antwort = buero.get(reverse('admin:faktura_rechnung_changelist'),
                            {'zahlungsstand': 'ueberfaellig'})

        assert list(antwort.context['cl'].queryset) == [spaet]

    def test_entwuerfe_fallen_bei_jeder_auswahl_heraus(self, buero, kunde):
        """Entwürfe fehlen bei jeder Auswahl, weil sie keine Forderung sind."""
        services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Noch in Arbeit')

        for auswahl in ('offen', 'bezahlt', 'ueberfaellig'):
            antwort = buero.get(
                reverse('admin:faktura_rechnung_changelist'),
                {'zahlungsstand': auswahl})
            assert list(antwort.context['cl'].queryset) == [], auswahl

    def _zelle(self, antwort, feld):
        """Inhalt der Zelle ``field-<feld>``, weil die Wörter auch in Filtern
        und Überschriften vorkommen."""
        import re
        treffer = re.findall(
            r'<td[^>]*class="[^"]*field-' + feld + r'[^"]*"[^>]*>(.*?)</td>',
            antwort.content.decode(), re.S)
        assert len(treffer) == 1, treffer
        return ' '.join(treffer[0].split())

    def test_die_marke_sagt_ueber_frist(self, buero, kunde):
        _faellig_setzen(_rechnung(kunde), HEUTE - timedelta(days=39))

        antwort = buero.get(reverse('admin:faktura_rechnung_changelist'))

        assert 'über Frist' in self._zelle(antwort, 'zahlungsstand')
        assert '+39 T' in self._zelle(antwort, 'faelligkeit')

    def test_vor_der_frist_steht_der_abstand(self, buero, kunde):
        _faellig_setzen(_rechnung(kunde), HEUTE + timedelta(days=7))

        antwort = buero.get(reverse('admin:faktura_rechnung_changelist'))

        assert '> offen <' in self._zelle(antwort, 'zahlungsstand')
        assert 'in 7 T' in self._zelle(antwort, 'faelligkeit')

    def test_bezahlt_ohne_abstand_und_ohne_betrag(self, buero, kunde, rechnung):
        """Bezahlt ohne Frist und ohne Betrag; die Spalte "Offen" zeigt einen
        Strich."""
        Zahlungszuordnung.objects.create(
            zahlung=_zahlung(kunde, '1190.00'), beleg=rechnung,
            betrag=Decimal('1190.00'))

        antwort = buero.get(reverse('admin:faktura_rechnung_changelist'))

        assert 'bezahlt' in self._zelle(antwort, 'zahlungsstand')
        assert ' T<' not in self._zelle(antwort, 'faelligkeit')
        assert '–' in self._zelle(antwort, 'offener_betrag')

    def test_die_geldspalten_stehen_rechts(self, buero, rechnung):
        """``formatting='price'`` setzt Kopf und Zelle rechtsbündig; geprüft an
        der CSS-Klasse."""
        import re
        inhalt = buero.get(
            reverse('admin:faktura_rechnung_changelist')).content.decode()

        for feld in ('summe_brutto', 'offener_betrag'):
            assert re.search(r'<td[^>]*class="[^"]*text-right[^"]*field-'
                             + feld, inhalt) or re.search(
                r'<td[^>]*class="[^"]*field-' + feld + r'[^"]*text-right',
                inhalt), feld


# ══════════════════════════════════════════════════════════════════════════
# Zahlungsstand einer Rechnung (R-176)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestDerZahlungsstand:
    """Zahlungsstand für die Marke in der Liste und den Zähler der
    Seitenleiste, mit derselben Frist wie die offenen Posten (R-150)."""

    def test_der_entwurf_hat_keinen(self, kunde):
        entwurf = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)

        assert services.zahlungsstand(entwurf) == ''

    def test_die_stornierte_hat_keinen(self, rechnung):
        rechnung.status = BelegStatus.STORNIERT
        rechnung.save(update_fields=['status'])

        assert services.zahlungsstand(rechnung) == ''

    def test_am_tag_der_faelligkeit_noch_offen(self, rechnung):
        assert services.zahlungsstand(
            rechnung, stichtag=rechnung.faellig_am) == services.ZAHLUNGSSTAND_OFFEN

    def test_am_tag_danach_ueber_der_frist(self, rechnung):
        stichtag = rechnung.faellig_am + timedelta(days=1)

        assert services.zahlungsstand(
            rechnung, stichtag=stichtag) == services.ZAHLUNGSSTAND_UEBER_FRIST
        assert services.tage_ueber_frist(rechnung, stichtag) == 1

    def test_dieselbe_frist_wie_die_offenen_posten(self, kunde):
        """Dieselbe Frist wie die offenen Posten, damit Marke und Startseite
        übereinstimmen."""
        for tage in (-5, 0, 1, 40):
            _faellig_setzen(_rechnung(kunde, betreff=f'T{tage}'),
                            HEUTE - timedelta(days=tage))

        for posten in services.offene_posten().posten:
            ueber = (services.zahlungsstand(posten.beleg)
                     == services.ZAHLUNGSSTAND_UEBER_FRIST)
            assert ueber == posten.ist_ueberfaellig, posten.beleg.betreff
            assert (services.tage_ueber_frist(posten.beleg)
                    == posten.tage_ueberfaellig)

    def test_teilbezahlt_bleibt_offen(self, kunde, rechnung):
        Zahlungszuordnung.objects.create(
            zahlung=_zahlung(kunde, '500.00'), beleg=rechnung,
            betrag=Decimal('500.00'))

        assert services.zahlungsstand(rechnung) == services.ZAHLUNGSSTAND_OFFEN

    def test_mit_skonto_ausgeglichen_ist_bezahlt(self, kunde, rechnung):
        Zahlungszuordnung.objects.create(
            zahlung=_zahlung(kunde, '1166.20'), beleg=rechnung,
            betrag=Decimal('1166.20'), skonto=Decimal('23.80'))

        assert services.zahlungsstand(rechnung) == services.ZAHLUNGSSTAND_BEZAHLT

    def test_ohne_faelligkeit_nie_ueber_der_frist(self, rechnung):
        """Altdaten ohne ``faellig_am``: offen, nie über der Frist."""
        _faellig_setzen(rechnung, None)

        assert services.zahlungsstand(rechnung) == services.ZAHLUNGSSTAND_OFFEN
        assert services.tage_ueber_frist(rechnung) is None


def _formular_wie_angezeigt(antwort) -> dict:
    """POST-Daten beim unveränderten Speichern, aus der gerenderten Seite
    gelesen (Formular und Inlines)."""
    daten = {}
    formulare = [antwort.context['adminform'].form]
    for inline in antwort.context['inline_admin_formsets']:
        verwaltung = inline.formset.management_form
        formulare += [verwaltung, *inline.formset.forms]
    for formular in formulare:
        for name in formular.fields:
            wert = formular[name].value()
            if wert is not None:
                daten[formular.add_prefix(name)] = wert
    return daten


@pytest.mark.django_db
class TestEineVerteilteZahlungLaesstSichWiederSichern:
    """Eine verteilte Zahlung lässt sich erneut speichern.

    Die Auswahl im Inline enthält nur offene Rechnungen sowie die von dieser
    Zahlung ausgeglichene, weil die eigene Zeile sonst ungültig wäre."""

    def test_unveraendert_sichern(self, buero, kunde, rechnung):
        zahlung = _zahlung(kunde, '1190.00')
        Zahlungszuordnung.objects.create(
            zahlung=zahlung, beleg=rechnung, betrag=Decimal('1190.00'))
        adresse = reverse('admin:faktura_zahlung_change', args=[zahlung.pk])

        daten = _formular_wie_angezeigt(buero.get(adresse))
        antwort = buero.post(adresse, {**daten, '_save': 'Sichern'})

        assert antwort.status_code == 302, antwort.context and [
            f.errors for f in antwort.context['inline_admin_formsets'][0].formset]
