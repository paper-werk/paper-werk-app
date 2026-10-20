"""Zahlung vermerken an der Rechnung.

Die Berechnung (``ausgleich``, ``offener_betrag``, Prüfung auf
Überzahlung) prüft ``test_zahlungen.py``. Hier geprüft wird der Ablauf:
Erfassen eines Zahlungseingangs an der Rechnung und die dabei entstehenden
Daten.

Regression: Modelle und Masken existierten, aber ohne Menüpunkt und ohne
Aktion an der Rechnung.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from faktura import services
from faktura.models import (
    Beleg,
    BelegTyp,
    Kontakt,
    Zahlung,
    Zahlungsart,
    Zahlungszuordnung,
)

HEUTE = timezone.localdate()
User = get_user_model()


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(nummer='K-3100', name='Stadtwerke Beispiel',
                         strasse='Am Werk 1', plz='84028', ort='Landshut')


@pytest.fixture
def rechnung(kunde):
    """Festgeschriebene Rechnung über 1.190,00 EUR brutto."""
    beleg = services.beleg_anlegen(
        kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Gutachten')
    beleg.leistungsdatum = HEUTE
    beleg.save()
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Gutachten', menge=Decimal('1'),
        einzelpreis=Decimal('1000.00'), steuersatz='19.00',
        einheit='psch')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


# ══════════════════════════════════════════════════════════════════════════
# Service
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestZahlungVerbuchen:

    def test_der_volle_betrag_gleicht_die_rechnung_aus(self, rechnung, kunde):
        zahlung = services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=HEUTE, betrag=Decimal('1190.00'))

        assert services.offener_betrag(rechnung) == Decimal('0.00')
        assert zahlung.kunde == kunde
        assert zahlung.ist_verteilt

    def test_skonto_gleicht_aus_ohne_geflossen_zu_sein(self, rechnung):
        """Skonto gleicht aus ohne Zahlung: Der Kunde überweist 1.154,30 und
        zieht 35,70 Skonto; die Rechnung ist ausgeglichen, gezahlt sind
        1.154,30."""
        zahlung = services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=HEUTE,
            betrag=Decimal('1154.30'), skonto=Decimal('35.70'))

        assert services.offener_betrag(rechnung) == Decimal('0.00')
        assert zahlung.betrag == Decimal('1154.30')
        assert zahlung.zugeordnet == Decimal('1154.30')

    def test_eine_teilzahlung_laesst_den_rest_offen(self, rechnung):
        services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=HEUTE, betrag=Decimal('500.00'))

        assert services.offener_betrag(rechnung) == Decimal('690.00')

    def test_der_beleg_selbst_bleibt_unveraendert(self, rechnung):
        """Der festgeschriebene Beleg bleibt unverändert; "bezahlt" wird aus
        den Zuordnungen berechnet."""
        vorher = Beleg.objects.get(pk=rechnung.pk)

        services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=HEUTE, betrag=Decimal('1190.00'))

        nachher = Beleg.objects.get(pk=rechnung.pk)
        assert nachher.status == vorher.status
        assert nachher.nummer == vorher.nummer
        assert nachher.festgeschrieben_am == vorher.festgeschrieben_am

    def test_ueberzahlung_wird_abgewiesen_und_hinterlaesst_nichts(
            self, rechnung):
        """Eine Überzahlung wird abgelehnt und hinterlässt durch Rollback keine
        Zahlung ohne Zuordnung."""
        with pytest.raises(services.FakturaError):
            services.zahlung_verbuchen(
                beleg_id=rechnung.pk, datum=HEUTE, betrag=Decimal('2000.00'))

        assert not Zahlung.objects.exists()
        assert not Zahlungszuordnung.objects.exists()

    def test_auf_einen_entwurf_wird_nicht_gezahlt(self, kunde):
        entwurf = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Noch nicht fertig')

        with pytest.raises(services.FakturaError):
            services.zahlung_verbuchen(
                beleg_id=entwurf.pk, datum=HEUTE, betrag=Decimal('100.00'))


# ══════════════════════════════════════════════════════════════════════════
# Admin, geprüft über Requests
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestDieMaske:

    def _url(self, rechnung):
        return reverse('admin:faktura_rechnung_detail_zahlung',
                       args=[rechnung.pk])

    def test_die_maske_ist_mit_dem_offenen_betrag_vorbelegt(
            self, buero, rechnung):
        """Die Maske ist mit dem offenen Betrag vorbelegt."""
        antwort = buero.get(self._url(rechnung))

        assert antwort.status_code == 200
        assert antwort.context['form'].initial['betrag'] == Decimal('1190.00')
        assert antwort.context['form'].initial['datum'] == HEUTE

    def test_abschicken_legt_zahlung_und_zuordnung_an(self, buero, rechnung):
        buero.post(self._url(rechnung), {
            'anwenden': '1',
            'datum': HEUTE.strftime('%d.%m.%Y'),
            'betrag': '1190,00',
            'skonto': '',
            'zahlungsart': Zahlungsart.UEBERWEISUNG,
            'verwendungszweck': 'RE-Test',
        })

        assert services.offener_betrag(rechnung) == Decimal('0.00')
        assert Zahlung.objects.get().verwendungszweck == 'RE-Test'

    def _meldung(self, buero, rechnung, betrag):
        antwort = buero.post(self._url(rechnung), {
            'anwenden': '1',
            'datum': HEUTE.strftime('%d.%m.%Y'),
            'betrag': betrag,
            'skonto': '',
            'zahlungsart': Zahlungsart.UEBERWEISUNG,
            'verwendungszweck': '',
        }, follow=True)
        return [str(m) for m in antwort.context['messages']]

    def test_die_meldung_nennt_den_rest_nach_der_zahlung(
            self, buero, rechnung):
        """``get_queryset`` lädt ``zahlungszuordnungen`` per Prefetch. Der
        Rest wurde auf dieser Instanz berechnet und nannte nach voller
        Zahlung den alten Betrag."""
        assert self._meldung(buero, rechnung, '1190,00') == [
            'Zahlung vermerkt. Die Rechnung ist ausgeglichen.']

    def test_die_meldung_nennt_den_rest_einer_teilzahlung(
            self, buero, rechnung):
        assert self._meldung(buero, rechnung, '1000,00') == [
            'Zahlung vermerkt. Offen bleiben 190,00 EUR.']

    def test_an_einer_ausgeglichenen_rechnung_gibt_es_den_knopf_nicht(
            self, buero, rechnung):
        """An einer ausgeglichenen Rechnung kein Button; geprüft an der
        Rechteprüfung, die bestimmt, ob Unfold ihn rendert."""
        from django.contrib import admin

        from faktura.models import Rechnung

        maske = admin.site._registry[Rechnung]
        anfrage = buero.get(
            reverse('admin:faktura_rechnung_change', args=[rechnung.pk])
        ).wsgi_request

        assert maske.has_zahlung_permission(anfrage, rechnung.pk) is True

        services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=HEUTE, betrag=Decimal('1190.00'))

        assert maske.has_zahlung_permission(anfrage, rechnung.pk) is False

    def test_der_zahlstand_steht_in_der_rechnungsliste(self, buero, rechnung):
        services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=HEUTE, betrag=Decimal('1190.00'))

        liste = buero.get(reverse('admin:faktura_rechnung_changelist'))

        assert 'bezahlt' in liste.content.decode()

    def test_die_zahlungsliste_laesst_sich_nach_kunde_filtern(
            self, buero, rechnung, kunde):
        """Dem Link aus der Kundenakte wird gefolgt; ohne Filter Kunde lehnt
        Django den Parameter ab."""
        services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=HEUTE, betrag=Decimal('1190.00'))

        antwort = buero.get(
            f'{reverse("admin:faktura_zahlung_changelist")}'
            f'?kunde__id__exact={kunde.pk}')

        assert antwort.status_code == 200
        assert antwort.context['cl'].result_count == 1


@pytest.mark.django_db
class TestDerMenuepunkt:

    def test_zahlungseingaenge_stehen_im_menue(self, buero):
        """Zahlungseingänge stehen im Menü."""
        seite = buero.get(reverse('admin:index')).content.decode()

        assert 'Zahlungseingänge' in seite
        assert reverse('admin:faktura_zahlung_changelist') in seite

@pytest.mark.django_db
class TestDerReiterAnDerRechnung:
    """Tab "Zahlungen" an der Rechnung mit den Zahlungseingängen."""

    def test_der_eingang_steht_im_formular(self, buero, rechnung):
        services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=HEUTE, betrag=Decimal('1154.30'),
            skonto=Decimal('35.70'), verwendungszweck='Sammelüberweisung')

        seite = buero.get(
            reverse('admin:faktura_rechnung_change', args=[rechnung.pk])
        ).content.decode()

        assert 'Zahlungseingänge' in seite
        assert 'Sammelüberweisung' in seite
        assert 'ausgeglichen' in seite

    def test_an_einem_entwurf_gibt_es_den_reiter_nicht(self, buero, kunde):
        """Am Entwurf kein Tab, weil auf einen Entwurf nicht gezahlt wird."""
        entwurf = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Noch offen')

        antwort = buero.get(
            reverse('admin:faktura_rechnung_change', args=[entwurf.pk]))

        titel = [name for name, _ in antwort.context['adminform'].fieldsets]
        assert 'Zahlungen' not in titel


# ══════════════════════════════════════════════════════════════════════════
# Auswirkungen der Zahlung auf andere Vorgänge
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestDieMahnungKenntDieZahlung:
    """Die Mahnung fordert den offenen Betrag.

    Regression: ``mahnung_erstellen`` verwendete
    ``belegsummen(rechnung).brutto``; nach Zahlung von 1.000 von 1.190 EUR
    mahnte sie 1.190 EUR.
    """

    def _faellig_machen(self, rechnung):
        """Datiert die Fälligkeit über ``update()`` zurück, weil ``save`` am
        festgeschriebenen Beleg ablehnt und vor Fälligkeit nicht gemahnt
        wird."""
        Beleg.objects.filter(pk=rechnung.pk).update(
            faellig_am=HEUTE - timedelta(days=30))
        return Beleg.objects.get(pk=rechnung.pk)

    def test_gemahnt_wird_der_offene_rest(self, rechnung):
        self._faellig_machen(rechnung)
        services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=HEUTE, betrag=Decimal('1000.00'))

        mahnung = services.mahnung_erstellen(beleg_id=rechnung.pk, stufe=1)

        forderung = mahnung.positionen.get(position=10)
        assert forderung.einzelpreis == Decimal('190.00')

    def test_eine_ausgeglichene_rechnung_wird_nicht_gemahnt(self, rechnung):
        self._faellig_machen(rechnung)
        services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=HEUTE, betrag=Decimal('1190.00'))

        with pytest.raises(services.FakturaError):
            services.mahnung_erstellen(beleg_id=rechnung.pk, stufe=1)

    def test_an_ihr_gibt_es_auch_den_knopf_nicht_mehr(self, buero, rechnung):
        from django.contrib import admin

        from faktura.models import Rechnung

        self._faellig_machen(rechnung)
        maske = admin.site._registry[Rechnung]
        anfrage = buero.get(
            reverse('admin:faktura_rechnung_changelist')).wsgi_request

        assert maske.has_mahnen_permission(anfrage, rechnung.pk) is True

        services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=HEUTE, betrag=Decimal('1190.00'))

        assert maske.has_mahnen_permission(anfrage, rechnung.pk) is False

    def test_nachlass_und_storno_bleiben_trotzdem_moeglich(
            self, buero, rechnung):
        """An einer bezahlten Rechnung bleiben Nachlass und Storno möglich.

        Mahnen hat ein eigenes Recht, weil mit ``nachgelagert`` auch
        Nachlass und Storno entfielen."""
        from django.contrib import admin

        from faktura.models import Rechnung

        services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=HEUTE, betrag=Decimal('1190.00'))
        maske = admin.site._registry[Rechnung]
        anfrage = buero.get(
            reverse('admin:faktura_rechnung_changelist')).wsgi_request

        assert maske.has_nachgelagert_permission(anfrage, rechnung.pk) is True


@pytest.mark.django_db
class TestDieZahlungsmaske:

    def test_zur_wahl_stehen_nur_offene_rechnungen(self, buero, rechnung,
                                                   kunde):
        """Die Auswahl enthält nur offene Rechnungen."""
        from django.contrib import admin

        from faktura.models import Zahlung as Zahlungsmodell

        bezahlte = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Längst beglichen')
        bezahlte.leistungsdatum = HEUTE
        bezahlte.save()
        services.position_hinzufuegen(
            beleg=bezahlte, bezeichnung='Beratung', menge=Decimal('1'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00',
            einheit='psch')
        bezahlte = services.beleg_festschreiben(beleg_id=bezahlte.pk)
        services.zahlung_verbuchen(
            beleg_id=bezahlte.pk, datum=HEUTE, betrag=Decimal('119.00'))

        maske = admin.site._registry[Zahlungsmodell]
        inline = maske.inlines[0](Zahlungsmodell, admin.site)
        anfrage = buero.get(
            reverse('admin:faktura_zahlung_changelist')).wsgi_request
        feld = inline.formfield_for_foreignkey(
            Zahlungszuordnung._meta.get_field('beleg'), anfrage)

        waehlbar = list(feld.queryset)
        assert rechnung in waehlbar
        assert bezahlte not in waehlbar

    def test_das_formular_hat_einen_abschnitt_fuer_die_zuordnung(
            self, buero):
        """Das Formular hat einen Abschnitt für die Zuordnung.

        "Erfasst am" fehlt beim Anlegen, weil der Wert beim Speichern
        gesetzt wird. Regression: zwei Abschnitte "Woher" und "Herkunft",
        der zweite eingeklappt."""
        seite = buero.get(
            reverse('admin:faktura_zahlung_add')).content.decode()

        assert 'Zuordnung Kunde' in seite
        assert 'Zuordnung Rechnungen' in seite
        assert 'Herkunft' not in seite
        assert 'Woher' not in seite
        assert 'Erfasst am' not in seite

    def test_am_bestehenden_datensatz_steht_erfasst_am_wieder_da(
            self, buero, kunde):
        """Am bestehenden Datensatz erscheint "Erfasst am"."""
        zahlung = Zahlung.objects.create(
            datum=HEUTE, betrag=Decimal('100.00'), kunde=kunde)

        seite = buero.get(reverse('admin:faktura_zahlung_change',
                                  args=[zahlung.pk])).content.decode()

        assert 'Erfasst am' in seite

    def test_der_filter_findet_die_unverteilte_zahlung(self, buero, kunde,
                                                       rechnung):
        """Der Filter findet Zahlungen mit nicht verteiltem Rest."""
        Zahlung.objects.create(
            datum=HEUTE, betrag=Decimal('500.00'), kunde=kunde,
            verwendungszweck='unleserlich')
        services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=HEUTE, betrag=Decimal('1190.00'))

        liste = buero.get(
            f'{reverse("admin:faktura_zahlung_changelist")}?verteilung=ohne')

        assert liste.context['cl'].result_count == 1
        assert liste.context['cl'].result_list[0].verwendungszweck == \
            'unleserlich'
