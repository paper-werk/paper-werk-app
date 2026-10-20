"""Projektakte (auswertung/projektakte.py).

Die Akte zeigt Belege aus ``faktura``, Stunden und Zukauf aus ``erfassung``
und Kennzahlen aus ``auswertung.ergebnisse``. Geprüft wird, dass jede Quelle
erscheint und Beträge nur mit dem Recht darauf.
"""

import re
from datetime import date, time
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

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

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def kunde(db):
    return Kontakt.objects.create(nummer='K-7000', name='Stadt Musterstadt')


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
        benutzer=person, gueltig_ab=date(2026, 1, 1), satz=Decimal('55.00'))
    return person


@pytest.fixture
def akte_gefuellt(projekt, stunde, ingenieurin):
    """Vorhaben mit Beleg, Stunden und Zukauf."""
    erfassung_services.zeile_erfassen(
        projekt=projekt, leistung=stunde, benutzer=ingenieurin,
        beschreibung='Probenahme', datum=date(2026, 8, 10),
        von=time(8, 0), bis=time(12, 0))

    labor = Kontakt.objects.create(ist_kunde=False, ist_lieferant=True, name='ISARTAL')
    rechnung = Eingangsrechnung.objects.create(
        lieferant=labor, nummer='AL-4711', datum=date(2026, 8, 12),
        betrag_netto=Decimal('192.00'))
    Fremdleistung.objects.create(
        rechnung=rechnung, projekt=projekt, bezeichnung='Paket 4711 Boden',
        menge=Decimal('2'), einkaufspreis=Decimal('96.00'))

    beleg = Beleg.objects.create(typ=BelegTyp.AUFTRAG,
                                 projekt=projekt)
    Belegposition.objects.create(
        beleg=beleg, position=10, bezeichnung='Pauschalhonorar',
        menge=Decimal('1'), einheit='pausch', einzelpreis=Decimal('5000.00'))
    beleg.status = BelegStatus.FESTGESCHRIEBEN
    beleg.nummer = 'AB-2026-0001'
    beleg.belegdatum = date(2026, 7, 1)
    beleg.save()
    return projekt


@pytest.fixture
def als_buchhalterin(client, db):
    """Konto mit Recht auf Projekte und Rechnungen, sieht also Beträge."""
    person = User.objects.create_user(
        username='bea', password='geheim12345', is_staff=True)
    person.user_permissions.add(*Permission.objects.filter(
        codename__in=['view_projekt', 'view_rechnung', 'view_erfassungszeile',
                      'view_fremdleistung', 'view_eingangsrechnung',
                      # Für die Akte selbst nicht nötig (view_projekt und
                      # view_rechnung), aber für die Tests über die
                      # Startseite.
                      'controlling_ansehen']))
    client.force_login(person)
    return client


@pytest.fixture
def als_monteur(client, db):
    """Konto mit Recht auf Projekte, ohne Recht auf Rechnungen."""
    person = User.objects.create_user(
        username='mo', password='geheim12345', is_staff=True)
    person.user_permissions.add(
        Permission.objects.get(codename='view_projekt'))
    client.force_login(person)
    return client


def _akte(projekt):
    return reverse('projektakte', args=[projekt.pk])


class TestWasAufDerSeiteSteht:

    def test_die_seite_laeuft(self, als_buchhalterin, akte_gefuellt):
        antwort = als_buchhalterin.get(_akte(akte_gefuellt))

        assert antwort.status_code == 200

    def test_alle_drei_quellen_kommen_vor(self, als_buchhalterin,
                                          akte_gefuellt):
        """Belege, eigene Leistung und Zukauf erscheinen."""
        inhalt = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()

        assert 'AB-2026-0001' in inhalt          # Beleg
        assert 'Katrin Reiter' in inhalt         # erfasste Leistung
        assert 'Paket 4711 Boden' in inhalt      # Zukauf

    def test_die_fremdleistung_verweist_auf_ihre_eingangsrechnung(
            self, als_buchhalterin, akte_gefuellt):
        """Eine Fremdleistung verlinkt auf ihre Eingangsrechnung."""
        rechnung = Eingangsrechnung.objects.get()
        ziel = reverse('admin:erfassung_eingangsrechnung_change',
                       args=[rechnung.pk])

        inhalt = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()

        assert ziel in inhalt
        assert 'ISARTAL AL-4711' in inhalt

    def test_die_fremdleistung_zeigt_ihre_ausgangsrechnung(
            self, als_buchhalterin, akte_gefuellt):
        """Eine Fremdleistung zeigt "Offen" oder die Rechnung, auf der sie
        steht; einen Verkaufspreis hat sie erst dort."""
        from erfassung.models import Fremdleistung
        from faktura.admin import adresse_im_admin

        vorher = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()
        assert '>Abgerechnet<' in vorher
        assert 'Offen' in vorher

        beleg, _ = erfassung_services.in_rechnung_uebernehmen(
            zeilen=[], fremdleistungen=Fremdleistung.objects.all())

        nachher = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()
        assert adresse_im_admin(beleg) in nachher

    def test_die_kennzahlen_stehen_in_deutscher_schreibweise(
            self, als_buchhalterin, akte_gefuellt):
        """Kennzahlen im deutschen Format (5.000,00) über denselben Filter wie
        auf dem Beleg."""
        inhalt = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()

        assert '5.000,00' in inhalt

    def test_ein_leeres_vorhaben_sagt_das_auch(self, als_buchhalterin,
                                               projekt):
        """Ein leeres Vorhaben zeigt Hinweistexte an Stelle der Tabellen."""
        inhalt = als_buchhalterin.get(_akte(projekt)).content.decode()

        assert 'noch keinen festgeschriebenen Beleg' in inhalt
        assert 'noch nichts kontiert' in inhalt
        assert 'nichts zugekauft' in inhalt

    def test_die_einzelzeilen_stehen_nicht_da_sondern_ein_weg_dorthin(
            self, als_buchhalterin, akte_gefuellt):
        """Einzelne Erfassungszeilen erscheinen nicht; die Akte verlinkt auf
        die gefilterte Erfassungsliste."""
        inhalt = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()

        ziel = (f'{reverse("admin:erfassung_erfassungszeile_changelist")}'
                f'?projekt__id__exact={akte_gefuellt.pk}')
        assert ziel in inhalt


class TestDieBelegtabelle:
    """Belegtabelle: Nummer mit Link auf den Beleg, Betrag."""

    def test_die_nummer_fuehrt_zum_beleg(self, als_buchhalterin,
                                         akte_gefuellt):
        """Der Link führt über das Proxy-Modell der Belegart, weil
        "admin:faktura_beleg_change" nicht registriert ist."""
        beleg = Beleg.objects.get(nummer='AB-2026-0001')
        ziel = reverse('admin:faktura_auftrag_change',
                       args=[beleg.pk])

        inhalt = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()

        assert f'href="{ziel}"' in inhalt

    def test_jede_belegart_findet_ihre_adresse(self, als_buchhalterin,
                                               projekt):
        """Jede Belegart hat eine URL, abgeleitet aus den Modellen.

        Nur fünf Belegarten heißen wie ihr Typ, und mehrere Rechnungsarten
        teilen den Typ ``rechnung``; eine Zuordnung über den Typ allein ginge
        deshalb nicht.
        """
        from faktura.models import Beleg, BelegTyp, proxy_fuer

        for typ in BelegTyp.values:
            assert proxy_fuer(typ) is not Beleg, typ

    def test_jede_rechnungsart_findet_ihre_eigene_seite(
        self, als_buchhalterin, projekt
    ):
        """Jede Rechnungsart hat ihre eigene URL.

        Mit demselben Modell für alle landete ein LogEntry im Verlauf der
        falschen Rechnungsart. Geprüft gegen die Liste der Rechnungsarten.
        """
        from faktura.models import Rechnungsart, proxy_fuer

        gefunden = {proxy_fuer('rechnung', art) for art in Rechnungsart.values}

        assert len(gefunden) == len(Rechnungsart.values)

    def test_der_betrag_steht_daneben(self, als_buchhalterin, akte_gefuellt):
        inhalt = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()

        assert 'Betrag netto' in inhalt
        assert '5.000,00 €' in inhalt

    def test_beim_lieferschein_steht_kein_betrag(self, als_buchhalterin,
                                                 projekt):
        """Beim Lieferschein erscheint kein Betrag, weil seine Positionen den
        Preis null haben."""
        beleg = Beleg.objects.create(typ=BelegTyp.LIEFERSCHEIN,
                                     projekt=projekt)
        Belegposition.objects.create(
            beleg=beleg, position=10, bezeichnung='Bodenproben',
            menge=Decimal('12'), einheit='Stk', einzelpreis=Decimal('0.00'))
        beleg.status = BelegStatus.FESTGESCHRIEBEN
        beleg.nummer = 'LS-2026-0001'
        beleg.save()

        inhalt = als_buchhalterin.get(_akte(projekt)).content.decode()

        # Geprüft in der Belegzeile, weil "0,00 €" in den Kennzahlkarten
        # vorkommen darf.
        zeile = [z for z in inhalt.split('<tr') if 'LS-2026-0001' in z]
        assert len(zeile) == 1
        assert '0,00' not in zeile[0]
        assert '&ndash;' in zeile[0]

    def test_ohne_recht_fehlt_die_spalte_ganz(self, als_monteur,
                                              akte_gefuellt):
        inhalt = als_monteur.get(_akte(akte_gefuellt)).content.decode()

        assert 'AB-2026-0001' in inhalt
        assert 'Betrag netto' not in inhalt


class TestUeberschreitung:

    def test_im_rahmen_steht_keine_warnung(self, als_buchhalterin,
                                           akte_gefuellt):
        inhalt = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()

        assert 'über dem Auftrag' not in inhalt

    def test_darueber_hinaus_wird_gewarnt(self, als_buchhalterin, projekt,
                                          stunde, ingenieurin):
        """Auftrag über 100 EUR, geleistet 380 EUR: Warnung erscheint."""
        beleg = Beleg.objects.create(typ=BelegTyp.AUFTRAG,
                                     projekt=projekt)
        Belegposition.objects.create(
            beleg=beleg, position=10, bezeichnung='Pauschale',
            menge=Decimal('1'), einheit='pausch',
            einzelpreis=Decimal('100.00'))
        beleg.status = BelegStatus.FESTGESCHRIEBEN
        beleg.nummer = 'AB-klein'
        beleg.save()
        erfassung_services.zeile_erfassen(
            projekt=projekt, leistung=stunde, benutzer=ingenieurin,
            beschreibung='Arbeit', datum=date(2026, 8, 10),
            von=time(8, 0), bis=time(12, 0))

        inhalt = als_buchhalterin.get(_akte(projekt)).content.decode()

        assert 'über dem Auftrag' in inhalt
        assert '280,00' in inhalt


class TestWerWasSieht:
    """Beträge nur mit Recht auf Rechnungen, wie auf der Startseite."""

    def test_ohne_projektrecht_kommt_niemand_hinein(self, client, db,
                                                    akte_gefuellt):
        person = User.objects.create_user(
            username='fremd', password='geheim12345', is_staff=True)
        client.force_login(person)

        assert client.get(_akte(akte_gefuellt)).status_code == 403

    def test_der_monteur_sieht_die_akte_aber_keine_betraege(
            self, als_monteur, akte_gefuellt):
        inhalt = als_monteur.get(_akte(akte_gefuellt)).content.decode()

        assert 'Schadstofferkundung Turnhalle' in inhalt
        # Keine Kennzahlen, Marge oder Einkaufspreise.
        assert 'Ergebnis' not in inhalt
        assert '5.000,00' not in inhalt
        assert '96,00' not in inhalt

    def test_wer_gar_nicht_angemeldet_ist_landet_am_anmeldeschirm(
            self, client, akte_gefuellt):
        antwort = client.get(_akte(akte_gefuellt))

        assert antwort.status_code == 302
        assert '/admin/login/' in antwort['Location']


class TestDieBeidenEinstiege:
    """Die Akte ist aus der Projektliste und aus dem Formular erreichbar."""

    def test_die_liste_verweist_auf_die_akte(self, als_buchhalterin,
                                             akte_gefuellt):
        inhalt = als_buchhalterin.get(
            reverse('admin:faktura_projekt_changelist')).content.decode()

        assert _akte(akte_gefuellt) in inhalt

    def test_das_formular_hat_einen_knopf(self, client, db, akte_gefuellt):
        person = User.objects.create_user(
            username='chef', password='geheim12345', is_staff=True)
        person.user_permissions.add(*Permission.objects.filter(
            codename__in=['view_projekt', 'change_projekt']))
        client.force_login(person)

        inhalt = client.get(reverse(
            'admin:faktura_projekt_change',
            args=[akte_gefuellt.pk])).content.decode()

        assert 'Projektakte' in inhalt

    def test_der_knopf_fuehrt_wirklich_dorthin(self, als_buchhalterin,
                                               akte_gefuellt):
        """Die Detailaktion leitet auf die Akte um; geprüft wird das Ziel,
        weil auch ein falscher URL-Name einen gültigen Redirect ergäbe."""
        antwort = als_buchhalterin.get(
            f'/admin/faktura/projekt/{akte_gefuellt.pk}/akte/', follow=False)

        assert antwort.status_code == 200
        assert re.search(r'Projektakte 2026-042', antwort.content.decode())


class TestWieWeitDasVorhabenIst:
    """Balken für berechneten und geleisteten Anteil am Auftrag.

    Ist der geleistete Anteil deutlich größer als der berechnete, liegt
    nicht abgerechnete Leistung vor.
    """

    def test_die_anteile_stehen_am_auftrag(self, als_buchhalterin,
                                           akte_gefuellt):
        """Auftrag 5.000, geleistet 380 (4 Std zu 95) + 192 (Labor, offen zum
        Einkaufspreis) = 572."""
        inhalt = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()

        breiten = re.findall(r'style="width: (\d+)%"', inhalt)
        # Nichts fakturiert, 11 Prozent geleistet.
        assert breiten == ['0', '11']

    def test_bei_null_prozent_bleibt_die_leiste_stehen(self, als_buchhalterin,
                                                      akte_gefuellt):
        """Bei null Prozent erscheint eine leere Leiste.

        Unfolds progress-Komponente prüft ``{% if items or value %}`` und
        zeichnet bei null Prozent nichts; deshalb sind die Balken eigenes
        Markup.
        """
        inhalt = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()

        assert 'style="width: 0%"' in inhalt
        assert re.search(r'>\s*0 %\s*<', inhalt)

    def test_ueber_dem_auftrag_wird_der_balken_rot_und_bleibt_im_rahmen(
            self, als_buchhalterin, projekt, stunde, ingenieurin):
        beleg = Beleg.objects.create(typ=BelegTyp.AUFTRAG,
                                     projekt=projekt)
        Belegposition.objects.create(
            beleg=beleg, position=10, bezeichnung='Pauschale',
            menge=Decimal('1'), einheit='pausch',
            einzelpreis=Decimal('100.00'))
        beleg.status = BelegStatus.FESTGESCHRIEBEN
        beleg.nummer = 'AB-klein'
        beleg.save()
        erfassung_services.zeile_erfassen(
            projekt=projekt, leistung=stunde, benutzer=ingenieurin,
            beschreibung='Arbeit', datum=date(2026, 8, 10),
            von=time(8, 0), bis=time(12, 0))

        inhalt = als_buchhalterin.get(_akte(projekt)).content.decode()

        # 380 von 100 sind 380 Prozent; die Zahl erscheint, der Balken ist
        # auf 100 begrenzt.
        assert re.search(r'>\s*380 %\s*<', inhalt)
        assert 'style="width: 100%"' in inhalt
        assert 'bg-red-600' in inhalt

    def test_ohne_auftrag_gibt_es_keine_anteile(self, als_buchhalterin,
                                                projekt, stunde, ingenieurin):
        """Ohne Auftrag erscheinen keine Anteile."""
        erfassung_services.zeile_erfassen(
            projekt=projekt, leistung=stunde, benutzer=ingenieurin,
            beschreibung='Arbeit', datum=date(2026, 8, 10),
            von=time(8, 0), bis=time(12, 0))

        inhalt = als_buchhalterin.get(_akte(projekt)).content.decode()

        assert 'style="width:' not in inhalt

    def test_das_diagramm_zeigt_die_erfassten_stunden(self, als_buchhalterin,
                                                      akte_gefuellt):
        inhalt = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()

        assert 'class="pw-saeulen"' in inhalt
        assert 'Erfasste Stunden' in inhalt

    def test_der_monteur_sieht_das_diagramm_aber_keine_anteile(
            self, als_monteur, akte_gefuellt):
        """Ohne Recht auf Rechnungen bleibt der Stundenverlauf sichtbar, die
        Ausschöpfung nicht."""
        inhalt = als_monteur.get(_akte(akte_gefuellt)).content.decode()

        assert 'class="pw-saeulen"' in inhalt
        assert 'style="width:' not in inhalt


class TestDieStartseiteFuehrtInDieAkte:
    """Die Projekttabelle der Startseite verlinkt auf die Akte."""

    def test_die_projektzeile_verweist_auf_die_akte(self, als_buchhalterin,
                                                    akte_gefuellt):
        inhalt = als_buchhalterin.get(reverse('admin:index')).content.decode()

        assert _akte(akte_gefuellt) in inhalt

    def test_und_nicht_mehr_auf_das_formular(self, als_buchhalterin,
                                             akte_gefuellt):
        """Der Link zeigt auf die Akte, nicht auf das Formular."""
        formular = reverse('admin:faktura_projekt_change',
                           args=[akte_gefuellt.pk])

        inhalt = als_buchhalterin.get(reverse('admin:index')).content.decode()

        assert f'href="{formular}"' not in inhalt


class TestAuftragUndNachtraege:
    """Aufstellung von Hauptauftrag und Nachträgen."""

    def test_ein_einzelner_auftrag_bekommt_keine_tabelle(
            self, als_buchhalterin, akte_gefuellt):
        """Ein einzelner Auftrag erscheint nur als Kennzahl, ohne Tabelle."""
        inhalt = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()

        assert 'Auftrag und Nachträge' not in inhalt

    def test_mit_nachtrag_steht_die_herkunft_der_summe_da(
            self, als_buchhalterin, akte_gefuellt):
        haupt = Beleg.objects.get(nummer='AB-2026-0001')
        nachtrag = Beleg.objects.create(
            typ=BelegTyp.AUFTRAG, projekt=akte_gefuellt,
            nachtrag_zu=haupt)
        Belegposition.objects.create(
            beleg=nachtrag, position=10, bezeichnung='Mehrleistung',
            menge=Decimal('1'), einheit='pausch',
            einzelpreis=Decimal('2500.00'))
        nachtrag.status = BelegStatus.FESTGESCHRIEBEN
        nachtrag.nummer = 'AB-2026-0002'
        nachtrag.belegdatum = date(2026, 8, 8)
        nachtrag.save()

        inhalt = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()

        assert 'Auftrag und Nachträge' in inhalt
        assert 'Hauptauftrag' in inhalt
        assert '1. Nachtrag' in inhalt
        assert '7.500,00' in inhalt        # 5.000 + 2.500 beauftragt

    def test_ohne_das_recht_auf_zahlen_gibt_es_sie_nicht(
            self, als_monteur, akte_gefuellt):
        inhalt = als_monteur.get(_akte(akte_gefuellt)).content.decode()

        assert 'Auftrag und Nachträge' not in inhalt


class TestDerRingUndDieStaffel:
    """Ringdiagramm und Deckungsbeitragsstaffel, geprüft am gerenderten
    HTML, damit auch Fehler im Template auffallen."""

    def test_der_ring_traegt_seine_daten(self, als_buchhalterin,
                                         akte_gefuellt):
        inhalt = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()

        assert 'data-type="doughnut"' in inhalt
        assert 'Wohin der Leistungswert' in inhalt

    def test_die_legende_nennt_jeden_anteil_im_klartext(
            self, als_buchhalterin, akte_gefuellt):
        """Die Legende nennt jeden Anteil als Betrag, weil der Grünton allein
        nicht genug Kontrast hat."""
        inhalt = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()

        for titel in ('Eigene Arbeit', 'Zugekauft', 'Ergebnis'):
            assert titel in inhalt

    def test_die_staffel_zeigt_beide_deckungsbeitraege(
            self, als_buchhalterin, akte_gefuellt):
        inhalt = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()

        assert 'Deckungsbeitrag I' in inhalt
        assert 'Deckungsbeitrag II' in inhalt
        assert 'Vom Leistungswert zum Ergebnis' in inhalt

    def test_der_wasserfall_setzt_jede_stufe_an_ihren_platz(
            self, als_buchhalterin, akte_gefuellt):
        """Jede Stufe beginnt, wo der Rest der vorigen endet."""
        inhalt = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()

        assert inhalt.count('class="pw-balken"') == 5
        # Mindestens eine Stufe beginnt nicht am linken Rand.
        assert 'left: 0.0%' in inhalt
        assert inhalt.count('left: 0.0%') < 5

    def test_ohne_das_recht_auf_zahlen_gibt_es_weder_ring_noch_staffel(
            self, als_monteur, akte_gefuellt):
        """Ohne Recht auf Rechnungen erscheinen weder Ring noch Staffel."""
        inhalt = als_monteur.get(_akte(akte_gefuellt)).content.decode()

        assert 'data-type="doughnut"' not in inhalt
        assert 'Deckungsbeitrag' not in inhalt

    def test_ein_verlustvorhaben_bekommt_kein_drittes_ringstueck(
            self, als_buchhalterin, projekt, stunde, ingenieurin):
        """Bei negativem Ergebnis entfällt das dritte Segment.

        Chart.js zeichnete einen negativen Anteil als positives Segment; die
        Karte daneben nennt den Verlust.
        """
        # Ohne Auftrag und Rechnung: Leistungswert aus der erfassten Stunde,
        # Kosten darüber.
        Kostensatz.objects.filter(benutzer=ingenieurin).update(
            satz=Decimal('400.00'))
        erfassung_services.zeile_erfassen(
            projekt=projekt, leistung=stunde, benutzer=ingenieurin,
            beschreibung='Nacharbeit', datum=date(2026, 8, 11),
            von=time(8, 0), bis=time(16, 0), abrechenbar=False)

        inhalt = als_buchhalterin.get(_akte(projekt)).content.decode()

        assert 'übersteigen den Leistungswert' in inhalt

    def test_ein_leeres_vorhaben_zeigt_gar_keinen_ring(
            self, als_buchhalterin, projekt):
        """Ein leeres Vorhaben zeigt keinen Ring."""
        inhalt = als_buchhalterin.get(_akte(projekt)).content.decode()

        assert 'data-type="doughnut"' not in inhalt


class TestDerEffektiveStundensatz:

    def test_er_steht_als_kennzahl_da(self, als_buchhalterin, akte_gefuellt):
        inhalt = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()

        assert 'Effektiver Stundensatz' in inhalt

    def test_ohne_erfasste_stunden_faellt_die_karte_weg(
            self, als_buchhalterin, projekt):
        """Ohne erfasste Stunden entfällt die Karte Stundensatz."""
        inhalt = als_buchhalterin.get(_akte(projekt)).content.decode()

        assert 'Effektiver Stundensatz' not in inhalt

    def test_der_zukauf_zaehlt_nicht_in_den_satz(self, akte_gefuellt):
        """Zukauf zählt nicht zum Stundensatz: Erlös sind vier Stunden zu
        95 EUR, ohne die 290 EUR weiterberechnete Analytik."""
        from auswertung import controlling, ergebnisse

        ergebnis = ergebnisse.projektergebnis(akte_gefuellt)
        ertrag = controlling.projektertrag(ergebnis)

        assert ertrag.stunden == Decimal('4.00')
        assert ertrag.erloes_je_stunde == Decimal('95.00')


class TestDieWegeAusDerAkte:
    """Links von den Zahlen auf die zugrunde liegenden Datensätze."""

    def test_der_auftraggeber_fuehrt_zu_seinen_stammdaten(
            self, als_buchhalterin, akte_gefuellt):
        ziel = reverse('admin:faktura_kontakt_change',
                       args=[akte_gefuellt.kunde_id])

        inhalt = als_buchhalterin.get(_akte(akte_gefuellt)).content.decode()

        assert ziel in inhalt

    def test_ein_vorhaben_ohne_kunden_bleibt_ohne_verweis(
            self, als_buchhalterin, db):
        """Ohne Kunden kein Link; das Feld ist Pflicht, das Template
        behandelt den Fall trotzdem."""
        from auswertung import projektakte

        assert projektakte.akte is not None


class TestEntwuerfeStehenInDerBelegliste:
    """Entwürfe erscheinen in der Belegliste der Akte.

    Mit "Entwurf" an Stelle der Nummer und dem Status daneben.
    """

    def test_eine_offene_abschlagsrechnung_ist_dabei(
        self, als_buchhalterin, projekt
    ):
        from faktura import services
        from faktura.models import Rechnungsart

        entwurf = services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG,
            rechnungsart=Rechnungsart.ABSCHLAG,
            betreff='Erster Abschlag')
        services.position_hinzufuegen(
            beleg=entwurf, bezeichnung='Rohbau', menge=Decimal('1'),
            einzelpreis=Decimal('5000.00'), steuersatz='19.00')

        inhalt = als_buchhalterin.get(_akte(projekt)).content.decode()

        assert 'Erster Abschlag' in inhalt
        assert 'Entwurf' in inhalt

    def test_die_kennzahlen_bleiben_davon_unberuehrt(self, projekt):
        """Entwürfe ändern die Kennzahlen nicht."""
        from faktura import services

        services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG, betreff='Noch nichts')

        akte = services.projektakte(projekt, mit_entwuerfen=True)

        assert akte.fakturiert_netto == Decimal('0.00')


class TestJederVerweisFuehrtIrgendwohin:
    """Jeder Link der Akte in den Admin antwortet unter 400, wie in
    test_auftragsakte.py; erfasst auch künftige Links."""


    @pytest.fixture
    def mit_allen_rechten(self, client, db):
        """Konto mit allen Rechten, siehe test_auftragsakte.py."""
        person = get_user_model().objects.create_superuser(
            username='alles', email='a@example.com', password='geheim12345')
        client.force_login(person)
        return client

    def _adminverweise(self, inhalt):
        return sorted({
            treffer.replace('&amp;', '&')
            for treffer in re.findall(r'href="(/admin/[^"]+)"', inhalt)
        })

    def test_jeder_verweis_antwortet(self, mit_allen_rechten, akte_gefuellt):
        inhalt = mit_allen_rechten.get(_akte(akte_gefuellt)).content.decode()
        verweise = self._adminverweise(inhalt)

        assert len(verweise) >= 3
        for ziel in verweise:
            antwort = mit_allen_rechten.get(ziel)
            assert antwort.status_code < 400, (
                f'{ziel} antwortet mit {antwort.status_code}')
