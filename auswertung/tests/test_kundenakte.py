"""Kundenakte (auswertung/kundenakte.py) und Kundenformular.

Umsatz und offene Posten kommen aus Funktionen mit eigenen Tests
(``services.summe_ueber``, ``services.offene_posten``). Geprüft wird hier
die Auswahl: dass die Akte nur die Belege dieses Kunden zählt.

Außerdem am Kundenformular: mehrere Standardhäkchen, die Meldung zum
verletzten Constraint und die Beschriftung "Kontaktwege des Betriebs".
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from faktura import services
from faktura.models import (
    Adresse,
    Adressverwendung,
    Anrede,
    Ansprechpartner,
    Beleg,
    BelegTyp,
    Kontakt,
    Kontaktart,
    Kontaktweg,
    Projekt,
    Zahlung,
    Zahlungszuordnung,
)

HEUTE = timezone.localdate()
User = get_user_model()


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-2003', name='Landratsamt Musterstadt',
        strasse='Veitsbucher Straße 2', plz='84028', ort='Landshut',
        email='poststelle@lra.example', telefon='0871 408-0',
        zahlungsziel_tage=30, kaeuferreferenz='09274-1000-14',
    )


def _rechnung(kunde, *, netto='1000.00', betreff='Leistungen'):
    beleg = services.beleg_anlegen(
        kunde=kunde, typ=BelegTyp.RECHNUNG, betreff=betreff)
    beleg.leistungsdatum = HEUTE
    beleg.save()
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Gutachten', menge=Decimal('1'),
        einzelpreis=Decimal(netto), steuersatz='19.00', einheit='psch')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


def _projektrechnung(projekt, *, netto='1000.00', betreff='Leistungen'):
    """Rechnung an einem Projekt, ``kunde_id`` ist leer.

    Häufigster Fall bei Projektgeschäft.
    """
    beleg = services.beleg_anlegen(
        projekt=projekt, typ=BelegTyp.RECHNUNG, betreff=betreff)
    beleg.leistungsdatum = HEUTE
    beleg.save()
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Gutachten', menge=Decimal('1'),
        einzelpreis=Decimal(netto), steuersatz='19.00', einheit='psch')
    return services.beleg_festschreiben(beleg_id=beleg.pk)


def akte(client, kunde):
    return client.get(reverse('kundenakte', args=[kunde.pk]))


# ══════════════════════════════════════════════════════════════════════════
# Stammdaten
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestDieAkteZeigtDieStammdaten:

    def test_sie_oeffnet_sich(self, buero, kunde):
        antwort = akte(buero, kunde)

        assert antwort.status_code == 200
        assert 'K-2003' in antwort.content.decode()

    def test_die_anschrift_steht_zeilengetreu_darauf(self, buero, kunde):
        """Die Anschrift kommt aus derselben Quelle wie das Empfängerfeld
        eines Belegs."""
        seite = akte(buero, kunde).content.decode()

        assert 'Veitsbucher Straße 2' in seite
        assert '84028 Landshut' in seite

    def test_die_zweite_anschrift_steht_daneben(self, buero, kunde):
        Adresse.objects.create(
            kontakt=kunde, verwendung=Adressverwendung.POST,
            bezeichnung='Fachamt', strasse='Am Alten Viehmarkt 3',
            plz='84032', ort='Musterstadt')

        seite = akte(buero, kunde).content.decode()

        assert 'Am Alten Viehmarkt 3' in seite
        assert 'Rechnungsanschrift' in seite
        assert 'Postanschrift' in seite

    def test_kontaktdaten_stehen_nach_art_gruppiert(self, buero, kunde):
        seite = akte(buero, kunde).content.decode()

        assert 'poststelle@lra.example' in seite
        assert '0871 408-0' in seite
        assert 'Kontaktdaten' in seite

    def test_die_neue_art_weitere_kommt_mit(self, buero, kunde):
        """Die Art "Weitere" (etwa Slack, LinkedIn) erscheint mit der Angabe
        aus "Wofür"."""
        Kontaktweg.objects.create(
            kontakt=kunde, art=Kontaktart.WEITERE,
            wert='linkedin.com/company/lra', bezeichnung='LinkedIn')

        seite = akte(buero, kunde).content.decode()

        assert 'Weitere' in seite
        assert 'LinkedIn' in seite

    def test_ansprechpartner_stehen_mit_funktion_und_erreichbarkeit(
            self, buero, kunde):
        person = Ansprechpartner.objects.create(
            kontakt=kunde, anrede=Anrede.HERR, titel='Dr.', vorname='Michael',
            nachname='Ostermeier', funktion='Wasserwirtschaft',
            ist_standard=True)
        Kontaktweg.objects.create(
            ansprechpartner=person, art=Kontaktart.EMAIL,
            wert='m.ostermeier@lra.example')

        seite = akte(buero, kunde).content.decode()

        assert 'Dr. Michael Ostermeier' in seite
        assert 'Wasserwirtschaft' in seite
        assert 'm.ostermeier@lra.example' in seite
        assert 'Hauptkontakt' in seite

    def test_ein_ausgeschiedener_bleibt_sichtbar_und_gekennzeichnet(
            self, buero, kunde):
        """Inaktive Ansprechpartner erscheinen gekennzeichnet, weil ältere
        Belege sie nennen."""
        Ansprechpartner.objects.create(
            kontakt=kunde, nachname='Wenzl', funktion='Rechnungsprüfung',
            aktiv=False)

        seite = akte(buero, kunde).content.decode()

        assert 'Wenzl' in seite
        assert 'ausgeschieden' in seite

    def test_konditionen_zeigen_nur_was_gesetzt_ist(self, buero, kunde):
        """Ein Kunde ohne Skonto erhält keine Zeile "Skonto: 0 %"."""
        seite = akte(buero, kunde).content.decode()

        assert '30 Tage' in seite
        assert '09274-1000-14' in seite
        assert 'Skonto' not in seite

        kunde.skonto_prozent = Decimal('2.00')
        kunde.skonto_tage = 10
        kunde.save()

        seite = akte(buero, kunde).content.decode()
        assert 'Skonto' in seite

    def test_der_abweichende_rechnungsempfaenger_steht_im_kopf(self, buero, kunde):
        """Ein abweichender Rechnungsempfänger steht im Kopf, weil er für
        jede Rechnung gilt."""
        verwaltung = Kontakt.anlegen(
            nummer='K-3001', name='Hausverwaltung Bayer GmbH',
            strasse='Verwaltungsweg 2', plz='84034', ort='Landshut')
        kunde.rechnungsempfaenger = verwaltung
        kunde.save()

        seite = akte(buero, kunde).content.decode()

        assert 'Rechnung an' in seite
        assert 'Hausverwaltung Bayer GmbH' in seite


# ══════════════════════════════════════════════════════════════════════════
# Projekte und Belege
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestDieAkteZeigtWasDaranHaengt:

    def test_vorhaben_stehen_darauf_laufende_zuerst(self, buero, kunde):
        Projekt.objects.create(
            nummer='2026-001', bezeichnung='Altlasten Bahnhof', kunde=kunde)
        Projekt.objects.create(
            nummer='2025-099', bezeichnung='Altes Vorhaben', kunde=kunde,
            abgeschlossen=True)

        seite = akte(buero, kunde).content.decode()

        assert 'Altlasten Bahnhof' in seite
        assert 'Altes Vorhaben' in seite
        assert seite.index('Altlasten Bahnhof') < seite.index('Altes Vorhaben')

    def test_ein_fremdes_vorhaben_steht_nicht_darauf(self, buero, kunde):
        fremder = Kontakt.anlegen(nummer='K-9999', name='Ganz woanders')
        Projekt.objects.create(
            nummer='2026-500', bezeichnung='Fremdes Vorhaben', kunde=fremder)

        seite = akte(buero, kunde).content.decode()

        assert 'Fremdes Vorhaben' not in seite

    def test_festgeschriebene_belege_stehen_darauf(self, buero, kunde):
        rechnung = _rechnung(kunde, betreff='Gutachten Deponie')

        seite = akte(buero, kunde).content.decode()

        assert rechnung.nummer in seite

    def test_ein_entwurf_steht_nicht_darauf(self, buero, kunde):
        """Entwürfe erscheinen nicht, weil sie keine Nummer haben."""
        services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Noch in Arbeit')

        seite = akte(buero, kunde).content.decode()

        assert 'Noch in Arbeit' not in seite


# ══════════════════════════════════════════════════════════════════════════
# Beträge
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestDieZahlenDerAkte:

    def test_der_umsatz_zaehlt_nur_diesen_kunden(self, buero, kunde):
        """Der Umsatz zählt nur Belege dieses Kunden."""
        _rechnung(kunde, netto='1000.00', betreff='Eigene')
        fremder = Kontakt.anlegen(nummer='K-9999', name='Ganz woanders')
        _rechnung(fremder, netto='5000.00', betreff='Fremde')

        antwort = akte(buero, kunde)

        assert antwort.context['umsatz_netto'] == Decimal('1000.00')
        assert antwort.context['umsatz_brutto'] == Decimal('1190.00')

    def test_offene_posten_zaehlen_nur_diesen_kunden(self, buero, kunde):
        _rechnung(kunde, netto='1000.00', betreff='Eigene')
        fremder = Kontakt.anlegen(nummer='K-9999', name='Ganz woanders')
        _rechnung(fremder, netto='5000.00', betreff='Fremde')

        antwort = akte(buero, kunde)

        assert antwort.context['offen_anzahl'] == 1
        assert antwort.context['offen_betrag'] == Decimal('1190.00')

    def test_die_zahlungseingaenge_stehen_in_der_akte(self, buero, kunde):
        """Zahlungseingänge des Kunden erscheinen in der Akte."""
        rechnung = _rechnung(kunde, netto='1000.00')
        services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=HEUTE, betrag=Decimal('1190.00'))

        antwort = akte(buero, kunde)

        assert len(antwort.context['zahlungen']) == 1
        assert antwort.context['zahlungen'][0]['belege'] == [rechnung.nummer]
        assert antwort.context['offen_anzahl'] == 0

    def test_eine_bezahlte_rechnung_faellt_aus_den_offenen_posten(
            self, buero, kunde):
        rechnung = _rechnung(kunde, netto='1000.00')
        zahlung = Zahlung.objects.create(
            datum=HEUTE, betrag=Decimal('1190.00'), kunde=kunde)
        Zahlungszuordnung.objects.create(
            zahlung=zahlung, beleg=rechnung, betrag=Decimal('1190.00'))

        antwort = akte(buero, kunde)

        assert antwort.context['offen_anzahl'] == 0
        assert antwort.context['offen_betrag'] == Decimal('0.00')
        # Der Umsatz bleibt nach der Zahlung unverändert.
        assert antwort.context['umsatz_netto'] == Decimal('1000.00')

    def test_ueberfaellig_wird_getrennt_ausgewiesen(self, buero, kunde):
        rechnung = _rechnung(kunde, netto='1000.00')
        Beleg.objects.filter(pk=rechnung.pk).update(
            faellig_am=HEUTE - timedelta(days=30))

        antwort = akte(buero, kunde)

        assert antwort.context['ueberfaellig_anzahl'] == 1
        assert antwort.context['ueberfaellig_betrag'] == Decimal('1190.00')
        assert antwort.context['aeltester_verzug'] == 30

    def test_ohne_rechnungsrecht_stehen_keine_betraege_darauf(self, client, db,
                                                              kunde):
        """Ohne Recht auf Rechnungen erscheinen keine Beträge."""
        from django.contrib.auth.models import Permission

        nutzer = User.objects.create_user(
            username='monteur', password='geheim12345', is_staff=True)
        nutzer.user_permissions.add(
            Permission.objects.get(codename='view_kontakt'))
        client.login(username='monteur', password='geheim12345')
        _rechnung(kunde, netto='1000.00')

        antwort = akte(client, kunde)

        assert antwort.status_code == 200
        assert antwort.context['darf_zahlen_sehen'] is False
        assert 'umsatz_netto' not in antwort.context
        assert 'Umsatz netto' not in antwort.content.decode()

    def test_ohne_kundenrecht_gar_nichts(self, client, db, kunde):
        User.objects.create_user(
            username='fremd', password='geheim12345', is_staff=True)
        client.login(username='fremd', password='geheim12345')

        assert akte(client, kunde).status_code == 403


# ══════════════════════════════════════════════════════════════════════════
# Navigation
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestDerWegInDieAkte:
    """Die Kundenliste verlinkt auf die Akte, die Akte auf das Formular;
    bei Projekt und Auftrag ist es umgekehrt."""

    def test_die_kundenliste_verweist_in_die_akte(self, buero, kunde):
        antwort = buero.get(reverse('admin:faktura_kontakt_changelist'))

        assert reverse('kundenakte', args=[kunde.pk]) in antwort.content.decode()

    def test_sie_verweist_nicht_mehr_ins_formular(self, buero, kunde):
        """``list_display_links = None``, damit eine Zelle nicht zwei Links
        enthält."""
        seite = buero.get(
            reverse('admin:faktura_kontakt_changelist')).content.decode()

        assert reverse('admin:faktura_kontakt_change',
                       args=[kunde.pk]) not in seite

    def test_die_akte_fuehrt_ins_formular_zurueck(self, buero, kunde):
        seite = akte(buero, kunde).content.decode()

        assert reverse('admin:faktura_kontakt_change', args=[kunde.pk]) in seite
        assert 'Stammdaten bearbeiten' in seite

    def test_der_knopf_im_formular_fuehrt_in_die_akte(self, buero, kunde):
        antwort = buero.get(
            reverse('admin:faktura_kontakt_change', args=[kunde.pk]))

        assert antwort.status_code == 200
        inhalt = antwort.content.decode()
        assert f'/kontakt/{kunde.pk}/akte/' in inhalt


# ══════════════════════════════════════════════════════════════════════════
# Belege über ein Projekt
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestBelegeUeberEinProjekt:
    """Belege an Projekten zählen in der Kundenakte mit.

    Regression: Ein Kunde mit fakturierten Projektrechnungen zeigte "Umsatz
    netto 0 €". Nach ``kunde_oder_projekt_nicht_beides`` hat ein
    Projektbeleg keine ``kunde_id``, und ``filter(kunde=kunde)`` findet ihn
    nicht. Die Tests hängen deshalb Belege an das Projekt.
    """

    def test_umsatz_und_offene_posten_zaehlen_projektbelege_mit(
            self, buero, kunde):
        projekt = Projekt.objects.create(
            nummer='2026-042', bezeichnung='Kläranlage Nord', kunde=kunde)
        _projektrechnung(projekt, netto='2000.00')

        antwort = akte(buero, kunde)

        assert antwort.context['umsatz_netto'] == Decimal('2000.00')
        assert antwort.context['offen_anzahl'] == 1
        assert antwort.context['offen_betrag'] == Decimal('2380.00')
        assert len(antwort.context['belege']) == 1

    def test_der_verweis_in_die_belegliste_traegt_wirklich(
            self, buero, kunde):
        """Der Link in die Belegliste wird abgerufen und zeigt die Belege.

        Regression: Er zeigte auf ``?kunde__id__exact=``, einen Filter, den
        die Rechnungsliste nicht führt; Django lehnt ihn ab.
        """
        projekt = Projekt.objects.create(
            nummer='2026-043', bezeichnung='Halle Süd', kunde=kunde)
        rechnung = _projektrechnung(projekt, netto='2000.00')

        liste = buero.get(akte(buero, kunde).context['belege_url'])

        assert liste.status_code == 200
        assert rechnung.nummer in liste.content.decode()

    def test_die_spalte_belege_in_der_kundenliste_zaehlt_sie_mit(
            self, buero, kunde):
        """Die Spalte "Belege" der Kundenliste zählt Projektbelege mit;
        ``Count('belege')`` zählte nur Belege direkt am Kunden."""
        projekt = Projekt.objects.create(
            nummer='2026-044', bezeichnung='Brücke Ost', kunde=kunde)
        _projektrechnung(projekt, netto='2000.00')
        _rechnung(kunde, netto='500.00')

        liste = buero.get(reverse('admin:faktura_kontakt_changelist'))
        zeile = [k for k in liste.context['cl'].result_list
                 if k.pk == kunde.pk][0]

        assert zeile.belegzahl == 2
