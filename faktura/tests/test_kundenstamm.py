"""Kundenstamm aus Kontakt, Adresse, Kontaktweg und Ansprechpartner.

Geprüft wird vor allem, dass keine Anschrift ohne Fehler leer bleibt:

1. **Properties.** ``kunde.strasse`` und die vier weiteren sind keine
   Spalten, liefern aber die Werte der Standardadresse.
2. **Übernahme in den Beleg.** Die aus den Stammdaten in einen neuen Beleg
   kopierten Werte.
3. **Regeln der Tabellen.** Genau eine Standardanschrift, genau ein Träger
   je Kontaktweg, höchstens ein Hauptansprechpartner.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.urls import reverse

from faktura import services
from faktura.models import (
    Adresse,
    Adressverwendung,
    Anrede,
    Ansprechpartner,
    BelegTyp,
    Kontakt,
    Kontaktart,
    Kontaktweg,
)


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-1000', name='Muster GmbH',
        strasse='Hauptstraße 1', plz='10115', ort='Berlin',
        email='info@muster.example', telefon='030 123456',
    )


# ══════════════════════════════════════════════════════════════════════════
# Anlegen aus einer flachen Zeile
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestKundeAnlegen:
    """``Kunde.anlegen``, verwendet von Import, Seed und Tests."""

    def test_aus_einer_zeile_werden_drei_saetze(self, kunde):
        assert kunde.adressen.count() == 1
        assert kunde.kontaktwege.count() == 2

    def test_die_erste_anschrift_ist_die_standardanschrift(self, kunde):
        assert kunde.standardadresse is not None
        assert kunde.standardadresse.strasse == 'Hauptstraße 1'
        assert kunde.standardadresse.verwendung == Adressverwendung.RECHNUNG

    def test_ohne_anschrift_entsteht_keine_leere_adresse(self, db):
        """Ohne Straße und Ort entsteht keine Adresse nur mit Ländercode."""
        namenlos = Kontakt.anlegen(name='Nur ein Name')

        assert namenlos.adressen.count() == 0
        assert namenlos.standardadresse is None

    def test_ein_kunde_ohne_adresse_gibt_leere_zeichenketten(self, db):
        """Ein Kunde ohne Adresse liefert leere Strings ohne Exception, damit er
        nur mit Namen angelegt und später ergänzt werden kann."""
        namenlos = Kontakt.anlegen(name='Nur ein Name')

        assert namenlos.strasse == ''
        assert namenlos.plz == ''
        assert namenlos.ort == ''
        assert namenlos.anschrift == ''
        assert namenlos.email == ''

    def test_ohne_adresse_ist_das_land_trotzdem_DE(self, db):
        """Ohne Adresse ist das Land 'DE', weil BT-55 Pflicht ist."""
        namenlos = Kontakt.anlegen(name='Nur ein Name')

        assert namenlos.land == 'DE'

    def test_ein_ungespeicherter_kunde_wirft_nicht(self, db):
        """``Kunde()`` ohne Primärschlüssel löst keine Exception aus.

        ``UebernahmeMixin`` leitet daraus beim Import des Admins die
        Übernahmefelder ab. Ohne Prüfung auf ``pk`` löst Django beim Zugriff
        auf eine Relation eines nicht gespeicherten Objekts eine Exception
        aus, und der Admin lädt nicht.
        """
        leer = Kontakt()

        assert leer.strasse == ''
        assert leer.email == ''
        assert leer.standardadresse is None
        assert leer.standardansprechpartner is None


# ══════════════════════════════════════════════════════════════════════════
# Properties
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestDieDurchreichen:
    """Fünf Properties ohne Spalte liefern die Werte der Standardadresse."""

    def test_sie_lesen_aus_der_standardanschrift(self, kunde):
        assert kunde.strasse == 'Hauptstraße 1'
        assert kunde.plz == '10115'
        assert kunde.ort == 'Berlin'
        assert kunde.land == 'DE'

    def test_sie_folgen_einer_aenderung_an_der_adresse(self, kunde):
        adresse = kunde.standardadresse
        adresse.strasse = 'Neue Allee 99'
        adresse.ort = 'Hamburg'
        adresse.save()

        kunde.refresh_from_db()
        assert kunde.strasse == 'Neue Allee 99'
        assert kunde.ort == 'Hamburg'

    def test_sie_lassen_sich_nicht_beschreiben(self, kunde):
        """Zuweisung löst eine Exception aus, weil eine wirkungslose Zuweisung
        eine Änderung vortäuschte."""
        with pytest.raises(AttributeError):
            kunde.strasse = 'Irgendwo 1'

    def test_die_email_ist_der_standardkontaktweg(self, kunde):
        assert kunde.email == 'info@muster.example'
        assert kunde.telefon == '030 123456'

    def test_ohne_kennzeichen_gilt_der_erste(self, db):
        """Ohne Markierung als Standard gilt der erste Kontaktweg."""
        still = Kontakt.anlegen(name='Ohne Kennzeichen')
        Kontaktweg.objects.filter(kontakt=still).delete()
        Kontaktweg.objects.bulk_create([Kontaktweg(
            kontakt=still, art=Kontaktart.EMAIL, wert='nur@eine.example',
            ist_standard=False)])

        assert still.email == 'nur@eine.example'


# ══════════════════════════════════════════════════════════════════════════
# Mehrere Anschriften
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestMehrereAnschriften:
    """Mehrere Anschriften je Verwendung, etwa Fachamt und
    Rechnungsprüfung."""

    @pytest.fixture
    def landratsamt(self, db):
        amt = Kontakt.anlegen(nummer='K-2003', name='Landratsamt Musterstadt')
        Adresse.objects.create(
            kontakt=amt, verwendung=Adressverwendung.RECHNUNG,
            bezeichnung='Rechnungsprüfung', zusatz='Zentrale Rechnungsprüfung',
            strasse='Am Alten Viehmarkt 3', plz='84028', ort='Landshut',
            ist_standard=True)
        Adresse.objects.create(
            kontakt=amt, verwendung=Adressverwendung.POST,
            bezeichnung='Fachamt',
            strasse='Veitsbucher Straße 2', plz='84032', ort='Musterstadt')
        return amt

    def test_die_rechnung_geht_an_die_rechnungsanschrift(self, landratsamt):
        anschrift = landratsamt.rechnungsanschrift

        assert anschrift.ort == 'Landshut'

    def test_die_post_geht_an_die_postanschrift(self, landratsamt):
        anschrift = landratsamt.adresse_fuer(Adressverwendung.POST)

        assert anschrift.ort == 'Musterstadt'

    def test_eine_fehlende_verwendung_faellt_auf_die_standardanschrift(
            self, landratsamt):
        """``adresse_fuer`` liefert ohne passende Verwendung die
        Standardanschrift."""
        anschrift = landratsamt.adresse_fuer(Adressverwendung.LIEFERUNG)

        assert anschrift.ort == 'Landshut'

    def test_der_adresszusatz_steht_im_anschriftfeld(self, landratsamt):
        assert landratsamt.anschriftfeld == (
            'Landratsamt Musterstadt\n'
            'Zentrale Rechnungsprüfung\n'
            'Am Alten Viehmarkt 3\n'
            '84028 Landshut'
        )

    def test_zwei_standardanschriften_weist_die_datenbank_ab(self, landratsamt):
        """Zwei Standardadressen lehnt der partielle Index ab.

        Zusätzlich zu ``clean()``, weil ``anschriftfeld`` sonst eine von
        beiden nach Sortierung der Datenbank verwendete.
        """
        zweite = landratsamt.adressen.filter(ist_standard=False).first()
        zweite.ist_standard = True

        with pytest.raises(IntegrityError):
            zweite.save()

    def test_die_erste_anschrift_wird_von_selbst_zur_standardanschrift(self, db):
        """Die erste Anschrift wird Standard, damit Shell und Import keinen
        Kunden ohne Standardanschrift anlegen."""
        stiller = Kontakt.anlegen(name='Ohne Kennzeichen')
        adresse = Adresse.objects.create(
            kontakt=stiller, strasse='Weg 1', plz='12345', ort='Ort')

        assert adresse.ist_standard is True

    def test_eine_zweite_macht_sich_nicht_selbst_zur_standardanschrift(
            self, landratsamt):
        dritte = Adresse.objects.create(
            kontakt=landratsamt, verwendung=Adressverwendung.LIEFERUNG,
            strasse='Bauhof 7', plz='84032', ort='Musterstadt')

        assert dritte.ist_standard is False


# ══════════════════════════════════════════════════════════════════════════
# Ansprechpartner
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestAnsprechpartner:
    """Ansprechpartner als Person beim Kunden, ohne eigenen Kontakt."""

    @pytest.fixture
    def person(self, kunde):
        return Ansprechpartner.objects.create(
            kontakt=kunde, anrede=Anrede.FRAU, titel='Dr.',
            vorname='Anna', nachname='Müller', funktion='Buchhaltung',
            ist_standard=True)

    def test_der_name_traegt_den_titel_und_nicht_die_anrede(self, person):
        assert person.name == 'Dr. Anna Müller'

    def test_die_briefanrede_der_frau(self, person):
        assert person.briefanrede == 'Sehr geehrte Frau Dr. Müller,'

    def test_die_briefanrede_des_herrn(self, kunde):
        herr = Ansprechpartner.objects.create(
            kontakt=kunde, anrede=Anrede.HERR, nachname='Ostermeier')

        assert herr.briefanrede == 'Sehr geehrter Herr Ostermeier,'

    def test_ohne_anrede_die_neutrale_form(self, kunde):
        """Ohne Anrede die neutrale Form, ohne Ableitung aus dem Vornamen
        ("Kim", "Andrea"), weil diese unzuverlässig ist."""
        namenlos = Ansprechpartner.objects.create(
            kontakt=kunde, vorname='Kim', nachname='Berger')

        assert namenlos.briefanrede == 'Sehr geehrte Damen und Herren,'

    def test_der_anschriftzusatz_ist_die_zHd_zeile(self, person):
        assert person.anschriftzusatz == 'z. Hd. Frau Dr. Anna Müller'

    def test_ein_ausgeschiedener_ist_nicht_der_vorschlag(self, kunde, person):
        person.aktiv = False
        person.save()

        kunde.refresh_from_db()
        assert kunde.standardansprechpartner is None

    def test_zwei_hauptansprechpartner_weist_die_datenbank_ab(self, kunde, person):
        zweiter = Ansprechpartner(
            kontakt=kunde, nachname='Wenzl', ist_standard=True)

        with pytest.raises(IntegrityError):
            zweiter.save()

    def test_die_person_hat_eigene_kontaktwege(self, kunde, person):
        """Personen haben eigene Kontaktwege (``a.mueller@``), getrennt von
        denen des Betriebs (``info@``)."""
        Kontaktweg.objects.create(
            ansprechpartner=person, art=Kontaktart.EMAIL,
            wert='a.mueller@muster.example')

        assert person.email == 'a.mueller@muster.example'
        assert kunde.email == 'info@muster.example'


# ══════════════════════════════════════════════════════════════════════════
# Kontaktwege
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestKontaktwege:
    """Kontaktwege: eine Tabelle für fünf Arten."""

    def test_ein_kontaktweg_ohne_traeger_wird_abgewiesen(self, db):
        heimatlos = Kontaktweg(art=Kontaktart.EMAIL, wert='wer@example.com')

        with pytest.raises(ValidationError) as fehler:
            heimatlos.full_clean()

        assert 'entweder' in str(fehler.value)

    def test_ein_kontaktweg_mit_zwei_traegern_wird_abgewiesen(self, kunde):
        person = Ansprechpartner.objects.create(kontakt=kunde, nachname='Müller')
        beides = Kontaktweg(kontakt=kunde, ansprechpartner=person,
                            art=Kontaktart.EMAIL, wert='wer@example.com')

        with pytest.raises(ValidationError):
            beides.full_clean()

    def test_die_datenbank_haelt_die_regel_auch_ohne_clean(self, db):
        """Der Constraint lehnt eine Zeile ohne Träger auch ohne ``clean()`` ab
        (Shell, Import, API)."""
        with pytest.raises(IntegrityError):
            Kontaktweg.objects.create(art=Kontaktart.EMAIL, wert='wer@x.example')

    def test_eine_ungueltige_email_wird_abgewiesen(self, kunde):
        krumm = Kontaktweg(kontakt=kunde, art=Kontaktart.EMAIL, wert='kein-at')

        with pytest.raises(ValidationError):
            krumm.full_clean()

    def test_eine_telefonnummer_wird_nicht_auf_email_geprueft(self, kunde):
        """Eine Telefonnummer wird nicht als E-Mail-Adresse validiert."""
        nummer = Kontaktweg(kontakt=kunde, art=Kontaktart.TELEFON,
                            wert='0871 900-412')

        nummer.full_clean()  # darf nicht werfen

    def test_der_erste_weg_einer_art_wird_der_standardweg(self, db):
        schlicht = Kontakt.anlegen(name='Schlicht')
        weg = Kontaktweg.objects.create(
            kontakt=schlicht, art=Kontaktart.FAX, wert='030 999')

        assert weg.ist_standard is True

    def test_ein_zweiter_derselben_art_wird_es_nicht(self, kunde):
        zweiter = Kontaktweg.objects.create(
            kontakt=kunde, art=Kontaktart.EMAIL, wert='zweite@muster.example')

        assert zweiter.ist_standard is False

    def test_zwei_standardwege_derselben_art_weist_die_datenbank_ab(self, kunde):
        zweiter = Kontaktweg.objects.create(
            kontakt=kunde, art=Kontaktart.EMAIL, wert='zweite@muster.example')
        zweiter.ist_standard = True

        with pytest.raises(IntegrityError):
            zweiter.save()

    def test_kunde_und_person_stoeren_einander_nicht(self, kunde):
        """Standard je Kunde und je Person getrennt, über zwei partielle
        Indizes, weil die NULL-Spalte des anderen Trägers in Postgres nie
        kollidiert."""
        person = Ansprechpartner.objects.create(kontakt=kunde, nachname='Müller')
        eigener = Kontaktweg.objects.create(
            ansprechpartner=person, art=Kontaktart.EMAIL,
            wert='a.mueller@muster.example', ist_standard=True)

        assert eigener.ist_standard is True
        assert kunde.email == 'info@muster.example'


# ══════════════════════════════════════════════════════════════════════════
# Übernahme in den Beleg
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestWasInDenBelegWandert:
    """Aus den Stammdaten in den Beleg kopierte Werte."""

    def test_die_anschrift_kommt_unveraendert_an(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)

        assert beleg.empfaenger == 'Muster GmbH\nHauptstraße 1\n10115 Berlin'
        assert beleg.empfaenger_strasse == 'Hauptstraße 1'
        assert beleg.empfaenger_plz == '10115'
        assert beleg.empfaenger_ort == 'Berlin'
        assert beleg.empfaenger_land == 'DE'

    def test_die_email_kommt_aus_dem_kontaktweg(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)

        assert beleg.empfaenger_email == 'info@muster.example'

    def test_der_hauptansprechpartner_wandert_mit(self, kunde):
        person = Ansprechpartner.objects.create(
            kontakt=kunde, anrede=Anrede.FRAU, vorname='Anna',
            nachname='Müller', ist_standard=True)

        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)

        assert beleg.ansprechpartner == person
        assert 'z. Hd. Frau Anna Müller' in beleg.empfaenger

    def test_seine_email_hat_vorrang_vor_der_des_betriebs(self, kunde):
        person = Ansprechpartner.objects.create(
            kontakt=kunde, nachname='Müller', ist_standard=True)
        Kontaktweg.objects.create(
            ansprechpartner=person, art=Kontaktart.EMAIL,
            wert='a.mueller@muster.example')

        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)

        assert beleg.empfaenger_email == 'a.mueller@muster.example'

    def test_ohne_eigene_email_bleibt_die_des_betriebs(self, kunde):
        Ansprechpartner.objects.create(
            kontakt=kunde, nachname='Müller', ist_standard=True)

        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)

        assert beleg.empfaenger_email == 'info@muster.example'

    def test_die_rechnungsanschrift_gilt_und_nicht_die_postanschrift(self, kunde):
        """Die Adresse mit Verwendung Rechnung hat Vorrang vor der
        Postanschrift."""
        kunde.standardadresse.delete()
        Adresse.objects.create(
            kontakt=kunde, verwendung=Adressverwendung.RECHNUNG,
            strasse='Buchhaltung 5', plz='20095', ort='Hamburg',
            ist_standard=True)
        Adresse.objects.create(
            kontakt=kunde, verwendung=Adressverwendung.POST,
            strasse='Hauptstraße 1', plz='10115', ort='Berlin')

        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)

        assert beleg.empfaenger_ort == 'Hamburg'
        assert 'Buchhaltung 5' in beleg.empfaenger


# ══════════════════════════════════════════════════════════════════════════
# Abweichender Rechnungsempfänger
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestDerAbweichendeRechnungsempfaenger:
    """Abweichender Rechnungsempfänger als Verweis auf einen anderen Kunden.

    Beispiel: Die Hausverwaltung zahlt für die Eigentümergemeinschaft; der
    Auftrag kommt vom einen, die Zahlung vom anderen, beide sind Kunden.
    """

    @pytest.fixture
    def gemeinschaft(self, db):
        verwaltung = Kontakt.anlegen(
            nummer='K-3001', name='Hausverwaltung Bayer GmbH',
            strasse='Verwaltungsweg 2', plz='84034', ort='Landshut')
        return Kontakt.anlegen(
            nummer='K-3000', name='WEG Ludwigsplatz 9',
            strasse='Ludwigsplatz 9', plz='84034', ort='Landshut',
            rechnungsempfaenger=verwaltung)

    def test_die_rechnung_geht_an_die_verwaltung(self, gemeinschaft):
        assert gemeinschaft.rechnungsanschrift.strasse == 'Verwaltungsweg 2'

    def test_auch_der_name_im_anschriftfeld(self, gemeinschaft):
        assert gemeinschaft.anschriftfeld == (
            'Hausverwaltung Bayer GmbH\nVerwaltungsweg 2\n84034 Landshut')

    def test_die_eigene_anschrift_bleibt_daneben_stehen(self, gemeinschaft):
        """Die eigene Anschrift des Kunden bleibt erhalten."""
        assert gemeinschaft.strasse == 'Ludwigsplatz 9'

    def test_der_beleg_uebernimmt_die_verwaltung(self, gemeinschaft):
        beleg = services.beleg_anlegen(
            kunde=gemeinschaft, typ=BelegTyp.RECHNUNG)

        assert beleg.empfaenger_name == 'Hausverwaltung Bayer GmbH'
        assert beleg.empfaenger_strasse == 'Verwaltungsweg 2'
        # Der Fremdschlüssel verweist auf den Auftraggeber als Kunden.
        assert beleg.kunde == gemeinschaft

    def test_niemand_ist_sein_eigener_rechnungsempfaenger(self, kunde):
        kunde.rechnungsempfaenger = kunde

        with pytest.raises(ValidationError):
            kunde.full_clean()


# ══════════════════════════════════════════════════════════════════════════
# Skonto und § 13b ohne automatische Wirkung
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestDieNeuenKaufmaennischenFelder:
    """Skonto und Steuerfall am Kunden sind Vorbelegungen ohne automatische
    Berechnung.

    Dieselbe Entscheidung wie beim Steuersatz ohne Gültigkeitszeitraum.
    """

    def test_skonto_ist_ohne_vereinbarung_null(self, kunde):
        assert kunde.skonto_prozent == Decimal('0.00')
        assert kunde.skonto_tage == 0

    def test_skonto_wandert_nicht_in_den_beleg(self, kunde):
        kunde.skonto_prozent = Decimal('2.00')
        kunde.skonto_tage = 10
        kunde.save()

        werte = services.stammdatenwerte(kunde)

        assert 'skonto_prozent' not in werte
        assert 'skonto_tage' not in werte

    def test_der_steuerfall_aendert_keinen_steuersatz(self, kunde):
        """Der Steuerfall wird übernommen, ändert aber keinen Steuersatz; das
        Festschreiben verlangt 0 %, die der Benutzer einstellt
        (test_pdf.TestSteuerfaelle)."""
        from faktura.models import Steuerfall

        kunde.steuerfall = Steuerfall.INLAND_13B
        kunde.save()

        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Gutachten', menge=Decimal('1'),
            einzelpreis=Decimal('1000.00'), steuersatz='19.00')

        assert beleg.steuerfall == Steuerfall.INLAND_13B
        assert services.belegsummen(beleg).steuer == Decimal('190.00')


# ══════════════════════════════════════════════════════════════════════════
# Validierung im Formular
# ══════════════════════════════════════════════════════════════════════════

def _kundenformular(**felder) -> dict:
    """POST-Daten eines vollständigen Kundenformulars mit den drei Inlines."""
    daten = {
        'nummer': 'K-5000',
        'name': 'Zweimal Standard GmbH',
        'aktiv': 'on',
        'ist_kunde': 'on',
        'ust_id': '',
        'zahlungsziel_tage': '14',
        'skonto_prozent': '0.00',
        'skonto_tage': '0',
        'zustellweg': 'pdf_mail',
        'kaeuferreferenz': '',
        'rechnungsempfaenger': '',
        'notiz': '',
    }
    for block in ('adressen', 'kontaktwege', 'ansprechpartner'):
        daten |= {
            f'{block}-TOTAL_FORMS': '0',
            f'{block}-INITIAL_FORMS': '0',
            f'{block}-MIN_NUM_FORMS': '0',
            f'{block}-MAX_NUM_FORMS': '1000',
        }
    return daten | felder


def _kontaktzeilen(*zeilen) -> dict:
    """Formset-Felder für N Kontaktzeilen."""
    daten = {
        'kontaktwege-TOTAL_FORMS': str(len(zeilen)),
        'kontaktwege-INITIAL_FORMS': '0',
        'kontaktwege-MIN_NUM_FORMS': '0',
        'kontaktwege-MAX_NUM_FORMS': '1000',
    }
    for n, (art, wert, standard) in enumerate(zeilen):
        daten |= {
            f'kontaktwege-{n}-art': art,
            f'kontaktwege-{n}-wert': wert,
            f'kontaktwege-{n}-bezeichnung': '',
            f'kontaktwege-{n}-id': '',
            f'kontaktwege-{n}-kunde': '',
        }
        if standard:
            daten[f'kontaktwege-{n}-ist_standard'] = 'on'
    return daten


@pytest.mark.django_db
class TestNurEinStandard:
    """Höchstens ein Standard je Art, als Fehler des Formsets.

    Regression: Mehrere Standards ließen sich wählen; der partielle Index
    griff erst in der Datenbank, mit einer Meldung an keinem Feld.

    Abgelehnt wird ohne automatische Korrektur. Verworfen: den ersten
    Standard beim zweiten entfernen, aus demselben Grund wie die Regel
    Kunde oder Projekt am Beleg.
    """

    def test_zwei_standard_emails_werden_abgewiesen(self, buero):
        antwort = buero.post(
            reverse('admin:faktura_kontakt_add'),
            _kundenformular(**_kontaktzeilen(
                ('email', 'eins@example.invalid', True),
                ('email', 'zwei@example.invalid', True))))

        assert antwort.status_code == 200, 'hätte nicht durchgehen dürfen'
        assert 'Je Art darf nur eine Zeile' in antwort.content.decode()
        assert not Kontakt.objects.filter(nummer='K-5000').exists()

    def test_die_meldung_nennt_die_betroffene_art(self, buero):
        """Die Meldung nennt das Label der Art ("Telefon"), nicht den Wert."""
        antwort = buero.post(
            reverse('admin:faktura_kontakt_add'),
            _kundenformular(**_kontaktzeilen(
                ('telefon', '0871 1', True),
                ('telefon', '0871 2', True))))

        assert 'Telefon' in antwort.content.decode()

    def test_eine_email_und_ein_telefon_duerfen_beide_standard_sein(self, buero):
        """Ein Standard je Art: E-Mail und Telefon können beide Standard
        sein."""
        antwort = buero.post(
            reverse('admin:faktura_kontakt_add'),
            _kundenformular(**_kontaktzeilen(
                ('email', 'info@example.invalid', True),
                ('telefon', '0871 900-0', True))))

        assert antwort.status_code == 302, antwort.content.decode()[:400]
        angelegt = Kontakt.objects.get(nummer='K-5000')
        assert angelegt.email == 'info@example.invalid'
        assert angelegt.telefon == '0871 900-0'

    def test_zwei_standardanschriften_werden_abgewiesen(self, buero):
        daten = _kundenformular()
        daten |= {
            'adressen-TOTAL_FORMS': '2',
            'adressen-INITIAL_FORMS': '0',
            'adressen-MIN_NUM_FORMS': '0',
            'adressen-MAX_NUM_FORMS': '1000',
        }
        for n, ort in enumerate(('Landshut', 'Musterstadt')):
            daten |= {
                f'adressen-{n}-verwendung': 'rechnung',
                f'adressen-{n}-bezeichnung': '',
                f'adressen-{n}-zusatz': '',
                f'adressen-{n}-strasse': f'Weg {n + 1}',
                f'adressen-{n}-plz': '84028',
                f'adressen-{n}-ort': ort,
                f'adressen-{n}-land': 'DE',
                f'adressen-{n}-ist_standard': 'on',
                f'adressen-{n}-id': '',
                f'adressen-{n}-kunde': '',
            }

        antwort = buero.post(reverse('admin:faktura_kontakt_add'), daten)

        assert antwort.status_code == 200
        assert 'Standardanschrift' in antwort.content.decode()
        assert not Kontakt.objects.filter(nummer='K-5000').exists()


@pytest.mark.django_db
class TestDenStandardWechseln:
    """Wechsel des Standards in einem POST.

    Regression: Nach Wahl einer zweiten E-Mail als Standard und Entfernen
    der alten blieb die Meldung, und der Datensatz ließ sich nicht
    speichern. Jede Zeile prüfte den Constraint gegen die Datenbank, in der
    die alte E-Mail noch Standard war. Den ganzen Satz prüft
    ``EinStandardFormSet``.
    """

    def _wege(self, traeger, zeilen, praefix='kontaktwege', fk='ansprechpartner'):
        """Vorhandene Zeilen mit ID, neue ohne."""
        vorhanden = [z for z in zeilen if z[0] is not None]
        daten = {
            f'{praefix}-TOTAL_FORMS': str(len(zeilen)),
            f'{praefix}-INITIAL_FORMS': str(len(vorhanden)),
            f'{praefix}-MIN_NUM_FORMS': '0',
            f'{praefix}-MAX_NUM_FORMS': '1000',
        }
        for n, (weg, art, wert, standard) in enumerate(zeilen):
            daten |= {
                f'{praefix}-{n}-id': str(weg.pk) if weg else '',
                f'{praefix}-{n}-{fk}': str(traeger.pk),
                f'{praefix}-{n}-art': art,
                f'{praefix}-{n}-wert': wert,
                f'{praefix}-{n}-bezeichnung': '',
            }
            if standard:
                daten[f'{praefix}-{n}-ist_standard'] = 'on'
        return daten

    def test_beim_ansprechpartner(self, admin_client, kunde):
        """Der Ablauf der Regression am Ansprechpartner."""
        person = Ansprechpartner.objects.create(kontakt=kunde, nachname='Kerner')
        alte = Kontaktweg.objects.create(
            ansprechpartner=person, art=Kontaktart.EMAIL,
            wert='alt@example.invalid', ist_standard=True)
        telefon = Kontaktweg.objects.create(
            ansprechpartner=person, art=Kontaktart.TELEFON,
            wert='0871 1', ist_standard=True)
        adresse = reverse('admin:faktura_ansprechpartner_change',
                          args=[person.pk])
        stamm = {'kontakt': kunde.pk, 'nachname': 'Kerner', 'aktiv': 'on',
                 '_continue': '1'}

        # Zuerst beide als Standard: abgelehnt.
        antwort = admin_client.post(adresse, stamm | self._wege(person, [
            (alte, 'email', 'alt@example.invalid', True),
            (telefon, 'telefon', '0871 1', True),
            (None, 'email', 'neu@example.invalid', True)]))
        assert antwort.status_code == 200

        # Dann Standard an der alten entfernt: gespeichert.
        antwort = admin_client.post(adresse, stamm | self._wege(person, [
            (alte, 'email', 'alt@example.invalid', False),
            (telefon, 'telefon', '0871 1', True),
            (None, 'email', 'neu@example.invalid', True)]))

        assert antwort.status_code == 302, antwort.content.decode()[:3000]
        standard = person.kontaktwege.get(art=Kontaktart.EMAIL,
                                          ist_standard=True)
        assert standard.wert == 'neu@example.invalid'
        alte.refresh_from_db()
        assert alte.ist_standard is False

    def test_zwischen_zwei_vorhandenen_zeilen(self, admin_client, kunde):
        """Ohne neue Zeile wechselt der Standard von der ersten zur zweiten.
        Prüft auch die Reihenfolge der Updates, weil der partielle Index
        anschlüge, wenn die neue Standardzeile zuerst geschrieben würde."""
        person = Ansprechpartner.objects.create(kontakt=kunde, nachname='Kerner')
        erste = Kontaktweg.objects.create(
            ansprechpartner=person, art=Kontaktart.EMAIL,
            wert='eins@example.invalid', ist_standard=True)
        zweite = Kontaktweg.objects.create(
            ansprechpartner=person, art=Kontaktart.EMAIL,
            wert='zwei@example.invalid', ist_standard=False)

        antwort = admin_client.post(
            reverse('admin:faktura_ansprechpartner_change', args=[person.pk]),
            {'kontakt': kunde.pk, 'nachname': 'Kerner', 'aktiv': 'on',
             '_continue': '1'} | self._wege(person, [
                 (zweite, 'email', 'zwei@example.invalid', True),
                 (erste, 'email', 'eins@example.invalid', False)]))

        assert antwort.status_code == 302, antwort.content.decode()[:3000]
        erste.refresh_from_db()
        zweite.refresh_from_db()
        assert (erste.ist_standard, zweite.ist_standard) == (False, True)

    def test_beim_kunden(self, admin_client, kunde):
        """Dasselbe Formset am Kunden."""
        alte = kunde.kontaktwege.get(art=Kontaktart.EMAIL)
        telefon = kunde.kontaktwege.get(art=Kontaktart.TELEFON)
        daten = _kundenformular(nummer=kunde.nummer, name=kunde.name)
        daten |= self._wege(kunde, [
            (alte, 'email', alte.wert, False),
            (telefon, 'telefon', telefon.wert, True),
            (None, 'email', 'neu@example.invalid', True)], fk='kontakt')

        antwort = admin_client.post(
            reverse('admin:faktura_kontakt_change', args=[kunde.pk]), daten)

        assert antwort.status_code == 302, antwort.content.decode()[:3000]
        kunde.refresh_from_db()
        assert kunde.email == 'neu@example.invalid'


    def test_die_standardanschrift_wandert(self, admin_client, kunde):
        """Dasselbe Formset bei den Anschriften."""
        erste = kunde.adressen.get()
        zweite = Adresse.objects.create(
            kontakt=kunde, verwendung=Adressverwendung.POST,
            strasse='Weg 2', plz='84028', ort='Landshut')
        daten = _kundenformular(nummer=kunde.nummer, name=kunde.name)
        daten |= {'adressen-TOTAL_FORMS': '2', 'adressen-INITIAL_FORMS': '2'}
        for n, (adresse, standard) in enumerate(((erste, False),
                                                 (zweite, True))):
            daten |= {
                f'adressen-{n}-id': str(adresse.pk),
                f'adressen-{n}-kontakt': str(kunde.pk),
                f'adressen-{n}-verwendung': adresse.verwendung,
                f'adressen-{n}-bezeichnung': '',
                f'adressen-{n}-zusatz': '',
                f'adressen-{n}-strasse': adresse.strasse,
                f'adressen-{n}-plz': adresse.plz,
                f'adressen-{n}-ort': adresse.ort,
                f'adressen-{n}-land': 'DE',
            }
            if standard:
                daten[f'adressen-{n}-ist_standard'] = 'on'

        antwort = admin_client.post(
            reverse('admin:faktura_kontakt_change', args=[kunde.pk]), daten)

        assert antwort.status_code == 302, antwort.content.decode()[:3000]
        assert kunde.adressen.get(ist_standard=True) == zweite


@pytest.mark.django_db
class TestVerstaendlicheMeldungen:
    """Meldungen zu Constraints nennen den Fehler in Worten des Formulars.

    Regression: "Bedingung eine_standardadresse_je_kunde ist nicht
    erfüllt", ohne Hinweis, was zu ändern ist.
    """

    def test_die_standardanschrift_sagt_was_zu_tun_ist(self, kunde):
        zweite = Adresse(kontakt=kunde, verwendung=Adressverwendung.POST,
                         strasse='Weg 2', plz='84028', ort='Landshut',
                         ist_standard=True)

        with pytest.raises(ValidationError) as fehler:
            zweite.full_clean()

        meldung = str(fehler.value)
        assert 'eine_standardadresse_je_kunde' not in meldung
        assert 'nur eine Standardanschrift je Kunde' in meldung

    def test_der_hauptansprechpartner_ebenso(self, kunde):
        Ansprechpartner.objects.create(
            kontakt=kunde, nachname='Erste', ist_standard=True)
        zweiter = Ansprechpartner(
            kontakt=kunde, nachname='Zweite', ist_standard=True)

        with pytest.raises(ValidationError) as fehler:
            zweiter.full_clean()

        assert 'nur einen Hauptansprechpartner' in str(fehler.value)

    def test_kein_bedingungsname_steht_mehr_in_einer_meldung(self, kunde):
        """Kein Constraint-Name in einer Meldung, geprüft für alle vier
        Constraints."""
        Kontaktweg.objects.create(
            kontakt=kunde, art=Kontaktart.FAX, wert='0871 1', ist_standard=True)
        zweites = Kontaktweg(
            kontakt=kunde, art=Kontaktart.FAX, wert='0871 2', ist_standard=True)

        with pytest.raises(ValidationError) as fehler:
            zweites.full_clean()

        meldung = str(fehler.value)
        assert 'ein_standardkontakt' not in meldung
        assert 'Je Art kann nur ein Eintrag der Standard sein' in meldung


@pytest.mark.django_db
class TestDieArtWeitere:
    """Art "Weitere" für Slack, LinkedIn, Teams usw.

    Der Dienst steht in ``bezeichnung``. Verworfen: eine Art je Dienst, weil
    die Liste veraltet und laufend Ergänzungen bräuchte.
    """

    def test_sie_steht_zur_wahl(self, kunde):
        weiterer = Kontaktweg.objects.create(
            kontakt=kunde, art=Kontaktart.WEITERE,
            wert='paper-werk.slack.com', bezeichnung='Slack')

        assert weiterer.get_art_display() == 'Weitere'
        assert str(weiterer) == 'Weitere Slack: paper-werk.slack.com'

    def test_sie_wird_nicht_auf_email_geprueft(self, kunde):
        """Die Art "Weitere" wird nicht als E-Mail-Adresse validiert."""
        weiterer = Kontaktweg(kontakt=kunde, art=Kontaktart.WEITERE,
                              wert='linkedin.com/company/beispiel')

        weiterer.full_clean()  # darf nicht werfen

    def test_sie_zaehlt_als_eigene_art_beim_standard(self, kunde):
        """Die Art "Weitere" hat einen eigenen Standard neben E-Mail."""
        slack = Kontaktweg.objects.create(
            kontakt=kunde, art=Kontaktart.WEITERE, wert='slack.example',
            bezeichnung='Slack', ist_standard=True)

        assert slack.ist_standard is True
        assert kunde.email == 'info@muster.example'


# ══════════════════════════════════════════════════════════════════════════
# Kontaktdaten einer Person
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestVomKundenZurPerson:
    """Ansprechpartner am Kunden mit Link auf die eigene Seite.

    Die Kontaktdaten einer Person stehen auf ihrer Seite, weil Django keine
    verschachtelten Inlines unterstützt; am Kunden steht nur die Übersicht.
    Geprüft wird der Weg hin und zurück über die Links der Seite.
    """

    def _seite(self, client, url) -> str:
        antwort = client.get(url)
        assert antwort.status_code == 200
        return antwort.content.decode()

    def _kundenseite(self, client, kunde) -> str:
        return self._seite(
            client, reverse('admin:faktura_kontakt_change', args=[kunde.pk]))

    def test_hinzufuegen_fuehrt_auf_die_seite_der_person(
            self, admin_client, kunde):
        seite = self._kundenseite(admin_client, kunde)
        ziel = f"{reverse('admin:faktura_ansprechpartner_add')}?kontakt={kunde.pk}"
        assert f'href="{ziel}"' in seite

        dort = self._seite(admin_client, ziel)
        # Der Kunde ist vorbelegt, Telefon und E-Mail sind eingebbar.
        assert f'<option value="{kunde.pk}" selected>' in dort
        assert 'kontaktwege-TOTAL_FORMS' in dort

    def test_sichern_fuehrt_zum_kunden_zurueck(self, admin_client, kunde):
        antwort = admin_client.post(
            f"{reverse('admin:faktura_ansprechpartner_add')}?kontakt={kunde.pk}",
            {'kontakt': kunde.pk, 'vorname': 'Erika', 'nachname': 'Kerner',
             'aktiv': 'on',
             'kontaktwege-TOTAL_FORMS': '1', 'kontaktwege-INITIAL_FORMS': '0',
             'kontaktwege-0-art': Kontaktart.MOBIL,
             'kontaktwege-0-wert': '0171 4711'})

        assert antwort.status_code == 302
        assert antwort.url == reverse('admin:faktura_kontakt_change',
                                      args=[kunde.pk])
        person = Ansprechpartner.objects.get(kontakt=kunde, nachname='Kerner')
        assert person.kontaktwege.get().wert == '0171 4711'

    def test_weiter_bearbeiten_bleibt_auf_der_seite(self, admin_client, kunde):
        """Nur "Sichern" führt zurück zum Kunden; die übrigen Buttons verhalten
        sich wie im Django-Admin."""
        antwort = admin_client.post(
            reverse('admin:faktura_ansprechpartner_add'),
            {'kontakt': kunde.pk, 'nachname': 'Kerner', 'aktiv': 'on',
             '_continue': '1',
             'kontaktwege-TOTAL_FORMS': '0', 'kontaktwege-INITIAL_FORMS': '0'})

        person = Ansprechpartner.objects.get(nachname='Kerner')
        assert antwort.url == reverse('admin:faktura_ansprechpartner_change',
                                      args=[person.pk])

    def test_zum_kontakt_fuehrt_zurueck(self, admin_client, kunde):
        person = Ansprechpartner.objects.create(kontakt=kunde, nachname='Kerner')
        aendern = reverse('admin:faktura_ansprechpartner_change',
                          args=[person.pk])
        seite = self._seite(admin_client, aendern)
        knopf = aendern.replace('change/', 'zum-kontakt/')
        assert f'href="{knopf}"' in seite

        antwort = admin_client.get(knopf)

        assert antwort.url == reverse('admin:faktura_kontakt_change',
                                      args=[kunde.pk])

    def test_der_kunde_zeigt_name_und_kontaktdaten(self, admin_client, kunde):
        person = Ansprechpartner.objects.create(
            kontakt=kunde, vorname='Erika', nachname='Kerner')
        Kontaktweg.objects.create(ansprechpartner=person,
                                  art=Kontaktart.MOBIL, wert='0171 4711')

        seite = self._kundenseite(admin_client, kunde)

        ziel = reverse('admin:faktura_ansprechpartner_change', args=[person.pk])
        assert f'href="{ziel}"' in seite
        assert 'Mobil: 0171 4711' in seite

    def test_am_kunden_laesst_sich_keine_person_mehr_tippen(
            self, admin_client, kunde):
        """Am Kunden lassen sich keine Personen anlegen, damit es nur einen Weg
        mit allen Kontaktdaten gibt."""
        Ansprechpartner.objects.create(kontakt=kunde, nachname='Kerner')

        seite = self._kundenseite(admin_client, kunde)

        assert 'name="ansprechpartner-0-nachname"' not in seite
        assert 'name="ansprechpartner-__prefix__-nachname"' not in seite

    def test_die_anschriften_sind_die_des_kunden(self, admin_client, kunde):
        fremd = Kontakt.anlegen(nummer='K-2000', name='Fremd GmbH',
                                strasse='Andere Str. 9', plz='84028',
                                ort='Landshut')
        dort = self._seite(
            admin_client,
            f"{reverse('admin:faktura_ansprechpartner_add')}?kontakt={kunde.pk}")
        auswahl = dort[dort.index('name="adresse"'):]
        auswahl = auswahl[:auswahl.index('</select>')]

        assert f'value="{kunde.adressen.get().pk}"' in auswahl
        assert f'value="{fremd.adressen.get().pk}"' not in auswahl

    def test_ein_neuer_kunde_sagt_was_zu_tun_ist(self, admin_client, db):
        seite = self._seite(admin_client, reverse('admin:faktura_kontakt_add'))

        assert 'Erst den Kontakt sichern' in seite
