"""Controlling-Seite, geprüft am gerenderten HTML.

Die Zahlen prüft ``test_controlling.py``. Hier geht es um Fehler im
Template, Diagramme ohne Daten, Beträge trotz fehlender Rechte und die leere
Datenbank.
"""

from datetime import time, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from erfassung import services as erfassung_services
from erfassung.models import Eingangsrechnung, Fremdleistung, Kostensatz
from faktura.models import (
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Katalogposition,
    Kontakt,
    Leistungsart,
    Projekt,
)

User = get_user_model()
HEUTE = timezone.localdate()
ADRESSE = '/admin/controlling/'


@pytest.fixture
def kunde(db):
    return Kontakt.objects.create(nummer='K-8000', name='Stadt Musterstadt')


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(
        nummer='2026-042', bezeichnung='Schadstofferkundung Turnhalle',
        kunde=kunde)


@pytest.fixture
def stunde(db):
    return Katalogposition.objects.create(
        bezeichnung='Ingenieurstunde', einheit='Std',
        einzelpreis=Decimal('95.00'), kontierbar=True, art=Leistungsart.ZEIT)


@pytest.fixture
def ingenieurin(db):
    person = User.objects.create_user(
        username='reiter', password='geheim12345', is_staff=True,
        first_name='Katrin', last_name='Reiter')
    Kostensatz.objects.create(
        benutzer=person, gueltig_ab=HEUTE - timedelta(days=400),
        satz=Decimal('55.00'))
    return person


def _beleg(typ, projekt, betrag, *, nummer, tage_zurueck=0):
    """Festgeschriebener Beleg, direkt am Modell gesetzt.

    ``beleg_festschreiben`` erzeugt ein PDF und braucht Firmenstammdaten;
    für die Auswertung zählt nur der Belegzustand.
    """
    beleg = Beleg.objects.create(typ=typ, projekt=projekt)
    Belegposition.objects.create(
        beleg=beleg, position=10, bezeichnung='Leistung',
        menge=Decimal('1'), einheit='pausch', einzelpreis=Decimal(betrag))
    beleg.status = BelegStatus.FESTGESCHRIEBEN
    beleg.nummer = nummer
    beleg.belegdatum = HEUTE - timedelta(days=tage_zurueck)
    beleg.save()
    return beleg


@pytest.fixture
def bestand(projekt, stunde, ingenieurin):
    """Bestand mit Auftrag, Umsatz, Stunden und Zukauf."""
    _beleg(BelegTyp.AUFTRAG, projekt, '20000.00',
           nummer='AB-2026-0001', tage_zurueck=90)
    _beleg(BelegTyp.RECHNUNG, projekt, '8000.00',
           nummer='RE-2026-0001', tage_zurueck=45)

    for versatz in (3, 40, 75, 200):
        erfassung_services.zeile_erfassen(
            projekt=projekt, leistung=stunde, benutzer=ingenieurin,
            beschreibung='Probenahme', datum=HEUTE - timedelta(days=versatz),
            von=time(8, 0), bis=time(12, 0))

    erfassung_services.zeile_erfassen(
        projekt=projekt, leistung=stunde, benutzer=ingenieurin,
        beschreibung='Nacharbeit', datum=HEUTE - timedelta(days=5),
        von=time(13, 0), bis=time(15, 0), abrechenbar=False)

    labor = Kontakt.objects.create(ist_kunde=False, ist_lieferant=True, name='ISARTAL')
    rechnung = Eingangsrechnung.objects.create(
        lieferant=labor, nummer='AL-4711', datum=HEUTE - timedelta(days=20),
        betrag_netto=Decimal('960.00'))
    Fremdleistung.objects.create(
        rechnung=rechnung, projekt=projekt, bezeichnung='Paket 4711 Boden',
        menge=Decimal('10'), einkaufspreis=Decimal('96.00'))
    return projekt


@pytest.fixture
def als_leitung(client, db):
    """Konto mit Recht auf Auswertungen und auf die Zeit je Person.

    ``controlling_ansehen`` für die Betriebszahlen, ``view_kostensatz`` für
    die Aufteilung je Mitarbeiter (RECHT und RECHT_PERSONEN in
    controllingseite.py).
    """
    person = User.objects.create_user(
        username='chef', password='geheim12345', is_staff=True)
    person.user_permissions.add(*Permission.objects.filter(
        codename__in=['controlling_ansehen', 'view_rechnung', 'view_projekt',
                      'view_kostensatz']))
    client.force_login(person)
    return client


@pytest.fixture
def als_buchhaltung(client, db):
    """Konto mit Recht auf Betriebszahlen, ohne Zeit je Person."""
    person = User.objects.create_user(
        username='bea', password='geheim12345', is_staff=True)
    person.user_permissions.add(*Permission.objects.filter(
        codename__in=['controlling_ansehen', 'view_rechnung']))
    client.force_login(person)
    return client


@pytest.fixture
def als_monteur(client, db):
    """Konto mit Recht auf Vorhaben, ohne Recht auf Auswertungen."""
    person = User.objects.create_user(
        username='mo', password='geheim12345', is_staff=True)
    person.user_permissions.add(
        Permission.objects.get(codename='view_projekt'))
    client.force_login(person)
    return client


class TestWerHineindarf:

    def test_ohne_das_recht_auf_rechnungen_ist_zu(self, als_monteur):
        """Ohne das Recht ist die ganze Seite gesperrt, weil sie nur aus
        Beträgen besteht."""
        assert als_monteur.get(ADRESSE).status_code == 403

    def test_wer_gar_nicht_angemeldet_ist_landet_am_anmeldeschirm(
            self, client, db):
        antwort = client.get(ADRESSE)

        assert antwort.status_code == 302
        assert '/admin/login/' in antwort['Location']

    def test_mit_dem_recht_geht_sie_auf(self, als_leitung, bestand):
        assert als_leitung.get(ADRESSE).status_code == 200

    def test_der_menueintrag_haengt_am_selben_recht(self, als_leitung):
        """Der Menüeintrag erscheint nur mit dem Recht für die Seite."""
        from core import erweiterungen

        uebersicht = erweiterungen.menue_abschnitte()[0]
        eintrag = next(e for e in uebersicht['items']
                       if e['title'] == 'Controlling')

        assert 'permission' in eintrag


class TestWasAufDerSeiteSteht:

    def test_die_vier_verhaeltnisse_stehen_da(self, als_leitung, bestand):
        """Die vier Verhältniszahlen erscheinen; keine davon steht auf der
        Startseite."""
        inhalt = als_leitung.get(ADRESSE).content.decode()

        for titel in ('Effektiver Stundensatz', 'Auftragsreichweite',
                      'Auftragseingang zu Umsatz', 'Deckungsbeitrag II'):
            assert titel in inhalt

    def test_auftragseingang_und_umsatz_teilen_sich_ein_bild(
            self, als_leitung, bestand):
        """Beide Reihen in einem Diagramm mit einer Achse in Euro netto je
        Monat."""
        inhalt = als_leitung.get(ADRESSE).content.decode()

        assert 'Auftragseingang und Umsatz' in inhalt
        assert 'Auftragseingang' in inhalt
        assert 'Fakturiert' in inhalt

    def test_die_landkarte_traegt_ihre_blasen(self, als_leitung, bestand):
        inhalt = als_leitung.get(ADRESSE).content.decode()

        assert 'data-type="bubble"' in inhalt
        assert 'Ausschöpfung des Auftrags' in inhalt

    def test_die_tabelle_ist_der_weg_in_die_vorhaben(self, als_leitung,
                                                    bestand):
        """Die Tabelle zur Landkarte verlinkt auf die Vorhaben."""
        ziel = reverse('projektakte', args=[bestand.pk])

        inhalt = als_leitung.get(ADRESSE).content.decode()

        assert ziel in inhalt
        assert '2026-042' in inhalt

    def test_die_altersstruktur_steht_gestaffelt_da(self, als_leitung,
                                                   bestand):
        inhalt = als_leitung.get(ADRESSE).content.decode()

        assert 'Verrechnungsdauer' in inhalt
        assert 'bis 30 Tage' in inhalt
        assert 'über 90 Tage' in inhalt

    def test_die_kundenstruktur_nennt_den_groessten(self, als_leitung,
                                                   bestand):
        inhalt = als_leitung.get(ADRESSE).content.decode()

        assert 'Top Auftraggeber' in inhalt
        assert 'Stadt Musterstadt' in inhalt

    def test_die_auslastung_zeigt_alle_drei_toepfe(self, als_leitung,
                                                  bestand):
        inhalt = als_leitung.get(ADRESSE).content.decode()

        assert 'Zeitaufteilung' in inhalt
        assert 'Katrin Reiter' in inhalt
        assert 'Nicht abrechenbar' in inhalt

    def test_die_staffel_steht_auch_fuer_den_ganzen_betrieb(
            self, als_leitung, bestand):
        inhalt = als_leitung.get(ADRESSE).content.decode()

        assert 'Deckungsbeiträge' in inhalt
        assert inhalt.count('class="pw-balken"') == 5


class TestDieZahlenSindDieselben:
    """Seite und Übersicht zeigen dieselben Beträge."""

    def test_die_seite_zeigt_dasselbe_ergebnis_wie_die_uebersicht(
            self, als_leitung, bestand):
        """Das Ergebnis der Seite entspricht dem der Übersicht."""
        from auswertung import controlling, ergebnisse

        lage = controlling.lage()
        uebersicht = ergebnisse.projektergebnisse()

        assert lage.deckungsbeitrag.db2 == uebersicht.ergebnis
        assert lage.reichweite.auftragsbestand == uebersicht.auftragsbestand

    def test_die_altersklassen_ergeben_die_offene_leistung(self, bestand):
        from auswertung import controlling

        lage = controlling.lage()

        assert lage.offene_leistung_gesamt == (
            erfassung_services.offene_leistung_gesamt())


class TestDerVorbehalt:
    """Hinweis bei Stunden ohne Kostensatz, die die Zahlen um deren Lohn zu
    hoch machen."""

    def test_ohne_kostensatz_steht_es_im_kopf_der_seite(
            self, als_leitung, projekt, stunde, db):
        aushilfe = User.objects.create_user(
            username='aushilfe', is_staff=True, first_name='Sophie',
            last_name='Werk')
        erfassung_services.zeile_erfassen(
            projekt=projekt, leistung=stunde, benutzer=aushilfe,
            beschreibung='', datum=HEUTE, von=time(8, 0), bis=time(12, 0))

        inhalt = als_leitung.get(ADRESSE).content.decode()

        assert 'ohne Kostensatz' in inhalt

    def test_mit_kostensaetzen_steht_der_vorbehalt_nicht_da(
            self, als_leitung, bestand):
        inhalt = als_leitung.get(ADRESSE).content.decode()

        assert 'Unvollständig' not in inhalt


class TestDerLeereBestand:
    """Leere Datenbank: Die Seite lädt ohne Division durch null."""

    def test_die_seite_laeuft_auch_ohne_jeden_datensatz(self, als_leitung):
        assert als_leitung.get(ADRESSE).status_code == 200

    def test_sie_sagt_was_fehlt_statt_null_zu_behaupten(self, als_leitung):
        """Ohne Daten erscheint "Kein Maßstab" und keine Null."""
        inhalt = als_leitung.get(ADRESSE).content.decode()

        assert 'kein Maßstab' in inhalt

    def test_ohne_auftrag_gibt_es_keine_landkarte_sondern_einen_satz(
            self, als_leitung, projekt):
        """Ohne Auftragswert erscheint ein Hinweistext an Stelle der
        Landkarte, weil die waagerechte Achse fehlt."""
        inhalt = als_leitung.get(ADRESSE).content.decode()

        assert 'data-type="bubble"' not in inhalt
        assert 'keine Ausschöpfung' in inhalt

    def test_ohne_umsatz_bleibt_die_kundenstruktur_hoeflich(
            self, als_leitung, projekt):
        inhalt = als_leitung.get(ADRESSE).content.decode()

        assert 'noch nichts berechnet' in inhalt


class TestDieBalkenSindGueltigesCss:
    """Balkenbreiten sind gültiges CSS.

    Django lokalisiert floats im Template: 12.5 wird "12,5", und
    ``width: 12,5%`` ist ungültig, der Balken verschwindet ohne Meldung. Alle
    Breiten entstehen deshalb im Code als String mit Dezimalpunkt.
    """

    def test_keine_balkenbreite_traegt_ein_komma(self, als_leitung, bestand):
        import re

        inhalt = als_leitung.get(ADRESSE).content.decode()
        breiten = re.findall(r'width:\s*([0-9,.]+)%', inhalt)

        assert breiten, 'keine Balken auf der Seite gefunden'
        assert not [b for b in breiten if ',' in b]

    def test_auch_die_wasserfallstufen_nicht(self, als_leitung, bestand):
        import re

        inhalt = als_leitung.get(ADRESSE).content.decode()
        raender = re.findall(r'left:\s*([0-9,.]+)%', inhalt)

        assert raender
        assert not [r for r in raender if ',' in r]


class TestDerTooltipDerLandkarte:
    """Tooltip der Landkarte.

    Der Standardtooltip zeigte ``Im Rahmen (21, 35, 12.6999)``: zwei
    Achsenwerte und den Radius in Pixeln, ohne Projektnamen. Chart.js
    erwartet eine Callback-Funktion, Unfold übergibt die Optionen aber über
    ``JSON.parse``; das Skript setzt den Callback im Browser. Geprüft wird,
    dass die Daten die Felder enthalten, die das Skript anzeigt.
    """

    def test_jede_blase_traegt_ihre_bezeichnung_und_ihren_wert(
            self, als_leitung, bestand):
        import json
        import re

        inhalt = als_leitung.get(ADRESSE).content.decode()
        rohdaten = re.search(
            r'data-type="bubble"\s+data-value="([^"]+)"', inhalt).group(1)
        daten = json.loads(rohdaten.replace('&quot;', '"')
                           .replace('&#x27;', "'").replace('&amp;', '&'))

        blasen = [b for reihe in daten['datasets'] for b in reihe['data']]
        assert blasen, 'keine Blase in der Landkarte'
        for blase in blasen:
            for feld in ('nummer', 'bezeichnung', 'kunde', 'wert',
                         'ergebnis'):
                assert blase.get(feld), f'{feld} fehlt an {blase}'

    def test_die_betraege_kommen_fertig_formatiert_an(self, als_leitung,
                                                      bestand):
        """Beträge kommen formatiert an, damit JavaScript keine eigene
        Zahlenformatierung braucht."""
        import json
        import re

        inhalt = als_leitung.get(ADRESSE).content.decode()
        rohdaten = re.search(
            r'data-type="bubble"\s+data-value="([^"]+)"', inhalt).group(1)
        daten = json.loads(rohdaten.replace('&quot;', '"')
                           .replace('&#x27;', "'").replace('&amp;', '&'))

        blase = daten['datasets'][0]['data'][0]

        assert blase['wert'].endswith('€')
        assert ',' in blase['wert'], 'kein deutsches Dezimalkomma'

    def test_das_skript_setzt_den_callback(self, als_leitung, bestand):
        """Das Skript setzt den Callback; sonst zeigt Chart.js (x, y, r)."""
        inhalt = als_leitung.get(ADRESSE).content.decode()

        assert 'tooltip.callbacks' in inhalt
        assert 'Chart.getChart' in inhalt
        assert 'pw-landkarte' in inhalt

    def test_der_radius_steht_in_keiner_beschriftung(self, als_leitung,
                                                     bestand):
        """``r`` bleibt in den Daten, weil Chart.js ihn braucht, erscheint
        aber in keiner Beschriftung."""
        inhalt = als_leitung.get(ADRESSE).content.decode()

        callback = inhalt[inhalt.index('label: function'):
                          inhalt.index('};', inhalt.index('label: function'))]

        assert 'b.r' not in callback
        assert 'b.wert' in callback


class TestDieBeidenRechte:
    """Rechte ``controlling_ansehen`` und ``view_kostensatz``.

    ``view_rechnung`` braucht jeder, der Belege schreibt; als Recht für die
    Auswertungen gäbe es Marge, Kostensätze und Kundenabhängigkeit frei.
    Die Zeit je Person ist eine Leistungsbewertung und verlangt zusätzlich
    ``view_kostensatz``.
    """

    def test_rechnungsrecht_allein_oeffnet_das_controlling_nicht(
            self, client, db):
        """``view_rechnung`` allein gibt die Seite nicht frei."""
        person = User.objects.create_user(
            username='sek', password='geheim12345', is_staff=True)
        person.user_permissions.add(
            Permission.objects.get(codename='view_rechnung'))
        client.force_login(person)

        assert client.get(ADRESSE).status_code == 403

    def test_und_laesst_die_startseite_ohne_zahlen(self, client, db):
        person = User.objects.create_user(
            username='sek2', password='geheim12345', is_staff=True)
        person.user_permissions.add(
            Permission.objects.get(codename='view_rechnung'))
        client.force_login(person)

        antwort = client.get(reverse('admin:index'))

        assert antwort.context['zeige_auswertung'] is False

    def test_das_neue_recht_allein_genuegt(self, client, db, bestand):
        """``controlling_ansehen`` genügt, ohne ``view_rechnung``."""
        person = User.objects.create_user(
            username='con', password='geheim12345', is_staff=True)
        person.user_permissions.add(
            Permission.objects.get(codename='controlling_ansehen'))
        client.force_login(person)

        assert client.get(ADRESSE).status_code == 200

    def test_ohne_kostensatzrecht_fehlt_die_zeit_je_person(
            self, als_buchhaltung, bestand):
        """Ohne ``view_kostensatz`` fehlt die Zeit je Person, weil sie eine
        mitbestimmungspflichtige Leistungsbewertung ist."""
        inhalt = als_buchhaltung.get(ADRESSE).content.decode()

        assert 'Zeitaufteilung' not in inhalt
        assert 'Katrin Reiter' not in inhalt
        # Die Betriebszahlen erscheinen.
        assert 'Deckungsbeitrag II' in inhalt

    def test_mit_kostensatzrecht_steht_sie_da(self, als_leitung, bestand):
        inhalt = als_leitung.get(ADRESSE).content.decode()

        assert 'Zeitaufteilung' in inhalt
        assert 'Katrin Reiter' in inhalt
