"""Übernahme der Stammdaten, Kunden- und Projektnummern, Käuferreferenz."""

import pytest
from django.utils import timezone

from faktura import services
from faktura.models import (
    Beleg,
    BelegTyp,
    Kontakt,
    Projekt,
)


@pytest.mark.django_db
class TestStammdatenWerdenKopiert:
    """Stammdaten werden in den Beleg kopiert."""

    def test_anschrift_wird_beim_anlegen_uebernommen(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)

        assert beleg.empfaenger == 'Muster GmbH\nHauptstraße 1\n10115 Berlin'

    def test_strukturfelder_fuer_die_erechnung_werden_mitkopiert(self, kunde):
        """Die Anschrift wird zweimal kopiert, als Freitext für das PDF und
        strukturiert für die E-Rechnung (EN 16931), beides aus den
        Stammdaten."""
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)

        assert beleg.empfaenger_name == 'Muster GmbH'
        assert beleg.empfaenger_strasse == 'Hauptstraße 1'
        assert beleg.empfaenger_plz == '10115'
        assert beleg.empfaenger_ort == 'Berlin'

    def test_umzug_des_kunden_laesst_alte_belege_unberuehrt(self, rechnung, kunde):
        """Eine Änderung der Standardadresse ändert bestehende Belege nicht."""
        services.beleg_festschreiben(beleg_id=rechnung.pk)

        adresse = kunde.standardadresse
        adresse.strasse = 'Neue Allee 99'
        adresse.ort = 'Hamburg'
        adresse.save()

        rechnung.refresh_from_db()
        assert 'Hauptstraße 1' in rechnung.empfaenger
        assert 'Berlin' in rechnung.empfaenger
        assert 'Neue Allee' not in rechnung.empfaenger


@pytest.mark.django_db
class TestStammdatenuebernahme:
    """Übernahme der Stammdaten und Vorrang der Eingaben.

    Regression: Die Regel "nur leere Felder" scheiterte an Defaults
    (14 Tage Zahlungsziel, 'DE'); ein Kunde mit 30 Tagen erhielt eine
    Rechnung mit 14 Tagen und falscher Fälligkeit.
    """

    def test_vorgabewerte_werden_durch_die_stammdaten_ersetzt(self, kunde):
        kunde.zahlungsziel_tage = 30
        kunde.save()
        # Das Land steht an der Adresse; die Übernahme in den Beleg ist
        # dieselbe.
        adresse = kunde.standardadresse
        adresse.land = 'AT'
        adresse.save()

        beleg = Beleg(kunde=kunde)
        services.stammdaten_uebernehmen(beleg=beleg, kunde=kunde)

        assert beleg.zahlungsziel_tage == 30
        assert beleg.empfaenger_land == 'AT'

    def test_angefasste_felder_bleiben_unberuehrt(self, kunde):
        """``ausser`` enthält die vom Benutzer eingetragenen Felder, die
        bleiben."""
        kunde.zahlungsziel_tage = 30
        kunde.save()

        beleg = Beleg(kunde=kunde, zahlungsziel_tage=21,
                      empfaenger='Ganz woanders\nPostfach 1')
        services.stammdaten_uebernehmen(
            beleg=beleg, kunde=kunde,
            ausser=['zahlungsziel_tage', 'empfaenger'],
        )

        assert beleg.zahlungsziel_tage == 21
        assert beleg.empfaenger == 'Ganz woanders\nPostfach 1'
        # Nicht genannte Felder kommen aus den Stammdaten.
        assert beleg.empfaenger_name == kunde.name

    def test_ohne_angabe_gewinnen_die_stammdaten_vollstaendig(self, kunde):
        beleg = Beleg(kunde=kunde, empfaenger='Altes Zeug')
        services.stammdaten_uebernehmen(beleg=beleg, kunde=kunde)

        assert beleg.empfaenger == kunde.anschriftfeld


@pytest.mark.django_db
class TestEmpfaengerAbweichungen:
    """Abweichungen zwischen freiem Empfängerfeld (PDF) und strukturierten
    Feldern (XML) werden gemeldet, nicht korrigiert, damit die Herkunft
    jedes Werts nachvollziehbar bleibt."""

    def test_gleiche_anschrift_ohne_befund(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)

        assert services.empfaenger_abweichungen(beleg) == []

    def test_zusaetze_im_ausdruck_sind_erlaubt(self, kunde):
        """Zusätze wie "z. Hd." im freien Feld sind zulässig."""
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)
        beleg.empfaenger = (
            f'{kunde.name}\nz. Hd. Frau Meier\n{kunde.strasse}\n'
            f'{kunde.plz} {kunde.ort}'
        )

        assert services.empfaenger_abweichungen(beleg) == []

    def test_anderer_ort_faellt_auf(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)
        beleg.empfaenger = f'{kunde.name}\n{kunde.strasse}\n20095 Hamburg'

        befunde = services.empfaenger_abweichungen(beleg)

        assert any('Berlin' in b for b in befunde)
        assert any('10115' in b for b in befunde)

    def test_postfach_statt_strasse_faellt_auf(self, kunde):
        """Ein Postfach im freien Feld bei Straße im strukturierten Feld wird
        gemeldet, weil das Postfach dann in BT-50 gehört."""
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)
        beleg.empfaenger = f'{kunde.name}\nPostfach 11 22\n{kunde.plz} {kunde.ort}'

        befunde = services.empfaenger_abweichungen(beleg)

        assert any('Hauptstraße 1' in b for b in befunde)

    def test_fehlende_strukturangabe_faellt_auf(self, kunde):
        """Eine fehlende strukturierte Angabe wird gemeldet, weil facturx.py dann
        die Heuristik verwendet."""
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)
        beleg.empfaenger_name = ''

        assert any('fehlt der Name' in b
                   for b in services.empfaenger_abweichungen(beleg))

    def test_leeres_empfaengerfeld_ist_kein_widerspruch(self, kunde):
        """Ein leeres Empfängerfeld erzeugt keine Warnung; beim Festschreiben
        meldet beleg_festschreiben() den fehlenden Empfänger."""
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)
        beleg.empfaenger = ''

        assert services.empfaenger_abweichungen(beleg) == []

    def test_gross_und_kleinschreibung_zaehlt_nicht(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)
        beleg.empfaenger = beleg.empfaenger.upper()

        assert services.empfaenger_abweichungen(beleg) == []


@pytest.mark.django_db
class TestKundennummer:
    """Kundennummer: vergeben, wenn keine eingetragen ist, sonst
    übernommen."""

    def test_ohne_angabe_wird_eine_vergeben(self):
        kunde = Kontakt.objects.create(name='Neuer Kunde')

        assert kunde.nummer.startswith('K-')
        assert kunde.nummer[2:].isdigit()

    def test_eine_eigene_nummer_bleibt_stehen(self):
        """Eine eingetragene Nummer bleibt, damit Nummern aus einem Altsystem
        übernommen werden können."""
        kunde = Kontakt.objects.create(nummer='DEBITOR-4711', name='Alt')

        assert kunde.nummer == 'DEBITOR-4711'

    def test_zwei_kunden_bekommen_verschiedene(self):
        erster = Kontakt.objects.create(name='Erster')
        zweiter = Kontakt.objects.create(name='Zweiter')

        assert erster.nummer != zweiter.nummer

    def test_eine_belegte_nummer_wird_uebersprungen(self):
        """Vergebene Nummern werden übersprungen.

        Der Zähler beginnt bei 1000, eine Nummer, die etwa der Seed bereits
        vergibt (K-1000); ohne Überspringen verletzte das erste Anlegen den
        Unique-Constraint.
        """
        Kontakt.objects.create(nummer='K-1000', name='Schon da')
        Kontakt.objects.create(nummer='K-1001', name='Auch schon da')

        neuer = Kontakt.objects.create(name='Der Neue')

        assert neuer.nummer not in ('K-1000', 'K-1001')

    def test_beim_aendern_bleibt_sie_unangetastet(self):
        """Beim Ändern bleibt die Nummer unverändert."""
        kunde = Kontakt.objects.create(name='Kunde')
        vorher = kunde.nummer

        kunde.name = 'Kunde GmbH'
        kunde.save()

        assert kunde.nummer == vorher


@pytest.mark.django_db
class TestProjektnummer:
    """Projektnummer: vorgeschlagen, wenn keine eingetragen ist, sonst
    übernommen.

    Wie die Kundennummer, aber mit Zähler **je Jahr**, weil das Jahr Teil der
    Nummer ist; ein durchgehender Zähler ergäbe 2027-127.
    """

    def test_ohne_angabe_wird_eine_vergeben(self, kunde):
        projekt = Projekt.objects.create(bezeichnung='Neues Vorhaben',
                                         kunde=kunde)

        jahr = timezone.localdate().year
        assert projekt.nummer.startswith(f'{jahr}-')
        assert projekt.nummer[len(str(jahr)) + 1:].isdigit()

    def test_eine_eigene_nummer_bleibt_stehen(self, kunde):
        """Eine eingetragene Nummer bleibt, weil Projektnummern oft extern
        vorgegeben sind (Bauherr, Ausschreibung)."""
        projekt = Projekt.objects.create(nummer='BV-Halle-Nord',
                                         bezeichnung='Halle', kunde=kunde)

        assert projekt.nummer == 'BV-Halle-Nord'

    def test_sie_schliesst_an_den_bestand_an(self, kunde):
        """Der Vorschlag folgt auf die höchste vorhandene Nummer (nach 2026-124
        folgt 2026-125)."""
        jahr = timezone.localdate().year
        Projekt.objects.create(nummer=f'{jahr}-124', bezeichnung='Schon da',
                               kunde=kunde)

        neues = Projekt.objects.create(bezeichnung='Das Neue', kunde=kunde)

        assert neues.nummer == f'{jahr}-125'

    def test_fremde_schreibweisen_stoeren_den_zaehler_nicht(self, kunde):
        """Nummern außerhalb des Musters ("BV-Halle-Nord") werden ignoriert und
        lösen keine Exception aus."""
        Projekt.objects.create(nummer='BV-Halle-Nord', bezeichnung='Halle',
                               kunde=kunde)

        neues = Projekt.objects.create(bezeichnung='Das Neue', kunde=kunde)

        assert neues.nummer.startswith(f'{timezone.localdate().year}-')

    def test_beim_aendern_bleibt_sie_unangetastet(self, kunde):
        projekt = Projekt.objects.create(bezeichnung='Vorhaben', kunde=kunde)
        vorher = projekt.nummer

        projekt.bezeichnung = 'Umbenannt'
        projekt.save()

        assert projekt.nummer == vorher


@pytest.mark.django_db
class TestKaeuferreferenz:
    """BT-10 der EN 16931 vom Kundenstamm bis ins XML.

    Behörden verlangen hier die Leitweg-ID, Unternehmen eine Kostenstelle;
    ein Feld für beide Verwendungen.

    Am Kunden heißt es ``kaeuferreferenz`` (Name von BT-10 in der Norm), am
    Beleg ``leitweg_id``, weil die API diesen Namen verwendet.
    """

    def test_wird_aus_den_stammdaten_uebernommen(self, kunde):
        kunde.kaeuferreferenz = '991-12345-67'
        kunde.save()

        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)

        assert beleg.leitweg_id == '991-12345-67'

    def test_ueber_das_projekt_ebenso(self, kunde):
        """Über das Projekt kommt die Referenz von dessen Kunden."""
        kunde.kaeuferreferenz = 'KST-4711'
        kunde.save()
        projekt = Projekt.objects.create(
            nummer='2026-500', bezeichnung='Umbau', kunde=kunde)

        beleg = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.RECHNUNG)

        assert beleg.leitweg_id == 'KST-4711'

    def test_am_beleg_hat_vorrang(self, kunde):
        """Der Wert am Beleg hat Vorrang vor der Vorbelegung.

        Weil Leitweg-IDs oft je Organisationseinheit verschieden sind, etwa
        je Amt eines Landkreises.
        """
        kunde.kaeuferreferenz = '991-00000-00'
        kunde.save()
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)

        services.stammdaten_uebernehmen(
            beleg=beleg, kunde=kunde, ausser=['leitweg_id'])

        assert beleg.leitweg_id == '991-00000-00'

    def test_ohne_referenz_bleibt_das_feld_leer(self, kunde):
        """Ohne Referenz bleibt das Feld leer, ohne Platzhalter.

        In EN 16931 ist BT-10 optional. Verworfen: "00" als Platzhalter,
        das manche Programme für BR-DE-15 der XRechnung eintragen.
        """
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)

        assert beleg.leitweg_id == ''

    def test_die_feldliste_steht_nur_an_einer_stelle(self):
        """Die Liste der Übernahmefelder steht an einer Stelle.

        Regression: Sie stand an vier Stellen; eine eigene Liste im Admin
        fiele erst beim nächsten neuen Feld auf.
        """
        from django.contrib.admin.sites import site

        from faktura.models import Rechnung

        admin_liste = site.get_model_admin(Rechnung).UEBERNAHMEFELDER

        assert set(admin_liste) == set(services.stammdatenwerte(Kontakt()))
        assert 'leitweg_id' in admin_liste
