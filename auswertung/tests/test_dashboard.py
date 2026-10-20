"""Startseite (auswertung/dashboard.py) und Basisklassen aller Admins.

Prüft außerdem, dass jede registrierte Admin-Klasse von Unfolds
Basisklassen erbt, auch die von Django und DRF.
"""

from decimal import Decimal

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from unfold.admin import ModelAdmin as UnfoldModelAdmin
from unfold.admin import StackedInline as UnfoldStackedInline
from unfold.admin import TabularInline as UnfoldTabularInline

from faktura import services
from faktura.models import BelegTyp, Kontakt, Projekt

User = get_user_model()


class TestJedeAdminKlasseTraegtDieOberflaeche:
    """Jede registrierte Admin-Klasse erbt von Unfolds ``ModelAdmin``.

    Die Widgets kommen aus der Basisklasse. Mit ``admin.ModelAdmin`` gibt es
    keine Fehlermeldung, nur Eingabefelder im Stil des Django-Admin;
    ``manage.py check`` erkennt das nicht. Geprüft wird über die Registry
    des Admin, also auch für Djangos Gruppen und DRFs API-Schlüssel, die
    core/admin.py neu registriert.
    """

    def test_alle_registrierten_modelle(self):
        falsch = [
            f'{modell._meta.label}: {type(modell_admin).__name__}'
            for modell, modell_admin in admin.site._registry.items()
            if not isinstance(modell_admin, UnfoldModelAdmin)
        ]

        assert falsch == []

    def test_alle_inlines(self):
        """Auch jedes Inline erbt von Unfolds Basisklasse."""
        unfold_inlines = (UnfoldTabularInline, UnfoldStackedInline)
        falsch = [
            f'{type(modell_admin).__name__}.{inline.__name__}'
            for modell_admin in admin.site._registry.values()
            for inline in modell_admin.inlines
            if not issubclass(inline, unfold_inlines)
        ]

        assert falsch == []


@pytest.fixture
def buchhalterin(db):
    """Konto mit Recht auf Rechnungen und Auswertungen."""
    person = User.objects.create_user(
        username='bea', password='geheim', is_staff=True)
    person.user_permissions.add(
        Permission.objects.get(codename='controlling_ansehen'))
    return person


@pytest.fixture
def monteur(db):
    """Konto mit Admin-Zugang, ohne Rechte in faktura."""
    return User.objects.create_user(
        username='mo', password='geheim', is_staff=True)


@pytest.fixture
def projekt_mit_stand(db):
    kunde = Kontakt.anlegen(
        nummer='K-3000', name='Bauherr GmbH', strasse='Werkstraße 5',
        plz='80331', ort='München')
    projekt = Projekt.objects.create(
        nummer='2026-200', bezeichnung='Halle Süd', kunde=kunde)

    for typ, netto in ((BelegTyp.AUFTRAG, '8000.00'),
                       (BelegTyp.RECHNUNG, '3000.00')):
        beleg = services.beleg_anlegen(projekt=projekt, typ=typ)
        beleg.leistungsdatum = '2026-01-15'
        beleg.save()
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Leistung', menge=Decimal('1'),
            einzelpreis=Decimal(netto), steuersatz='19.00',
        )
        services.beleg_festschreiben(beleg_id=beleg.pk)

    return projekt


@pytest.mark.django_db
class TestDieStartseite:

    def test_sie_laedt(self, client, buchhalterin):
        """Die Startseite lädt. Der Dashboard-Callback läuft bei jedem Aufruf
        der Admin-Startseite; eine Ausnahme dort sperrt den Admin."""
        client.force_login(buchhalterin)

        assert client.get(reverse('admin:index')).status_code == 200

    def test_sie_laedt_auch_ohne_einen_einzigen_beleg(self, client,
                                                      buchhalterin):
        """Leere Datenbank: kein Fehler bei Höchstwert über leerer Menge
        oder Division durch einen Auftrag von null."""
        client.force_login(buchhalterin)

        antwort = client.get(reverse('admin:index'))

        assert antwort.status_code == 200
        assert antwort.context['zeige_auswertung'] is True

    def test_die_projektzeile_steht_da(self, client, buchhalterin,
                                       projekt_mit_stand):
        client.force_login(buchhalterin)

        antwort = client.get(reverse('admin:index'))
        zeilen = antwort.context['projektzeilen']

        assert len(zeilen) == 1
        assert zeilen[0]['nummer'] == '2026-200'
        # 3000 von 8000 beauftragt sind 37 Prozent, abgerundet.
        assert zeilen[0]['fortschritt'] == 37
        assert zeilen[0]['zeige_fortschritt'] is True

    def test_die_betraege_sind_lesbar_formatiert(self, client, buchhalterin,
                                                 projekt_mit_stand):
        """Beträge mit Tausenderpunkt und Dezimalkomma trotz
        USE_THOUSAND_SEPARATOR = False (faktura.formate.euro)."""
        client.force_login(buchhalterin)

        zeile = client.get(reverse('admin:index')).context['projektzeilen'][0]

        assert zeile['beauftragt'] == '8.000,00 €'
        assert zeile['offen'] == '5.000,00 €'

    def test_jede_spalte_der_projektzeile_steht_in_der_seite(
            self, client, buchhalterin, projekt_mit_stand):
        """Jede Spalte der Projektzeile erscheint im HTML.

        Regression: Nach dem Umbenennen von ``leistung`` in
        ``leistungsbezeichnung`` am Erfassungsmodell war auch das Template
        der Startseite umbenannt, wo ``leistung`` etwas anderes bedeutet.
        Der Kontext war richtig, die Spalte "Nicht abgerechnet" leer.
        """
        import re

        client.force_login(buchhalterin)
        antwort = client.get(reverse('admin:index'))
        zeile = antwort.context['projektzeilen'][0]

        tabellenzeile = next(
            t for t in re.findall(r'<tr[^>]*>(.*?)</tr>',
                                  antwort.content.decode(), re.S)
            if zeile['nummer'] in t)
        zellen = [' '.join(re.sub(r'<[^>]+>', ' ', z).split())
                  for z in re.findall(r'<td[^>]*>(.*?)</td>', tabellenzeile, re.S)]

        assert zellen[1:6] == [
            zeile['beauftragt'], zeile['fakturiert'], zeile['offen'],
            zeile['leistung'],
            f"{zeile['ergebnis']} {zeile['marge']}".strip(),
        ]

    def test_wer_keine_rechnungen_sehen_darf_sieht_keine_zahlen(
        self, client, monteur, projekt_mit_stand
    ):
        """Ohne Recht auf Auswertungen erscheinen keine Beträge."""
        client.force_login(monteur)

        antwort = client.get(reverse('admin:index'))

        assert antwort.status_code == 200
        assert antwort.context['zeige_auswertung'] is False
        assert 'kennzahlen' not in antwort.context

    def test_die_zahlen_stehen_auch_im_ausgelieferten_html(
        self, client, buchhalterin, projekt_mit_stand
    ):
        """Die Zahlen erscheinen im HTML, nicht nur im Kontext."""
        client.force_login(buchhalterin)

        inhalt = client.get(reverse('admin:index')).content.decode()

        assert 'Offener Auftragsbestand' in inhalt
        assert '2026-200' in inhalt

    def test_der_monteur_bekommt_die_zahlen_auch_nicht_ins_html(
        self, client, monteur, projekt_mit_stand
    ):
        client.force_login(monteur)

        inhalt = client.get(reverse('admin:index')).content.decode()

        assert 'Offener Auftragsbestand' not in inhalt


class TestVorlagenkommentareBleibenKommentare:
    """Kein Template enthält einen mehrzeiligen ``{# #}``-Kommentar.

    Djangos Lexer erkennt ``{#.*?#}`` ohne ``re.DOTALL``; ein Kommentar über
    mehrere Zeilen wird als Text ausgegeben. Für mehrere Zeilen
    ``{% comment %}`` verwenden.
    """

    def test_kein_mehrzeiliger_rautenkommentar(self):
        import re
        from pathlib import Path

        # Wie Djangos Lexer, ohne DOTALL.
        einzeilig = re.compile(r'\{#.*?#\}')

        gefunden = []
        for pfad in sorted(Path('.').glob('**/templates/**/*.html')):
            if '.venv' in str(pfad):
                continue
            ohne = einzeilig.sub('', pfad.read_text(encoding='utf-8'))
            for treffer in re.finditer(r'\{#', ohne):
                zeile = ohne[:treffer.start()].count('\n') + 1
                gefunden.append(f'{pfad}:{zeile}')

        assert gefunden == [], (
            'mehrzeilige {# #}-Kommentare; bitte {% comment %} verwenden: '
            + ', '.join(gefunden)
        )


class TestDerVerweisAufDieWebseite:
    """Link "Webseite anzeigen" im Benutzermenü.

    Unfolds Vorgabe für ``SITE_URL`` ist ``/``, wo diese Anwendung keine
    Seite hat. Gesetzt wird der Link über ``MARKE_WEBSEITE``;
    ``UNFOLD['SITE_URL']`` enthält die Funktion aus ``core/marke.py``,
    deshalb prüfen die Tests das gerenderte Menü.
    """

    def test_die_wurzel_ist_wirklich_nicht_bedient(self, client):
        """``/`` liefert keine Seite. Ändert sich das, ist Unfolds Vorgabe
        wieder brauchbar."""
        assert client.get('/').status_code == 404

    def test_der_verweis_zeigt_woandershin(self, settings):
        assert settings.MARKE_WEBSEITE != '/'

    def test_und_er_steht_auf_der_seite(self, client, buchhalterin, settings):
        client.force_login(buchhalterin)

        inhalt = client.get(reverse('admin:index')).content.decode()

        assert f'href="{settings.MARKE_WEBSEITE}"' in inhalt

    def test_die_adresse_ist_einstellbar(self, client, buchhalterin, settings):
        """Der Link folgt ``MARKE_WEBSEITE``."""
        settings.MARKE_WEBSEITE = 'https://www.beispielbuero.de'
        client.force_login(buchhalterin)

        inhalt = client.get(reverse('admin:index')).content.decode()

        assert 'href="https://www.beispielbuero.de"' in inhalt
        assert 'ki-werkstatt' not in inhalt

    def test_leer_gesetzt_verschwindet_er(self, client, buchhalterin, settings):
        """Mit leerem ``MARKE_WEBSEITE`` entfällt der Link."""
        settings.MARKE_WEBSEITE = ''
        client.force_login(buchhalterin)

        inhalt = client.get(reverse('admin:index')).content.decode()

        assert 'ki-werkstatt' not in inhalt


@pytest.mark.django_db
class TestDieStartseiteSagtWasDieZahlBedeutet:
    """Hinweise unter den Karten ordnen Beträge ein.

    Etwa den Auftragsbestand als Reichweite in Monaten. Als Text unter
    bestehenden Karten, damit die Startseite keine weiteren Karten erhält.
    """

    def test_der_bestand_nennt_seine_reichweite(self, client, buchhalterin,
                                                projekt_mit_stand):
        """Die Reichweite erscheint, sobald ein abgeschlossener Monat Umsatz
        hat; der laufende Monat zählt nicht."""
        from datetime import timedelta

        from django.utils import timezone

        from faktura.models import Beleg, BelegTyp

        vormonat = timezone.localdate().replace(day=1) - timedelta(days=15)
        Beleg.objects.filter(typ=BelegTyp.RECHNUNG).update(
            belegdatum=vormonat)
        client.force_login(buchhalterin)

        inhalt = client.get(reverse('admin:index')).content.decode()

        assert 'Reicht rechnerisch' in inhalt

    def test_ohne_umsatz_bleibt_die_karte_bei_ihrer_alten_auskunft(
            self, client, buchhalterin):
        """Ohne abgeschlossenen Monat fehlt der Nenner; die Karte zeigt dann
        nur ihren Bezug, keine Reichweite."""
        client.force_login(buchhalterin)

        inhalt = client.get(reverse('admin:index')).content.decode()

        assert 'Reicht rechnerisch' not in inhalt
        assert 'Beauftragt, noch nicht berechnet' in inhalt

    def test_ohne_alte_posten_steht_kein_alter_da(self, client,
                                                  buchhalterin):
        client.force_login(buchhalterin)

        inhalt = client.get(reverse('admin:index')).content.decode()

        assert 'älter als 90 Tage' not in inhalt

    def test_ein_weg_ins_controlling(self, client, buchhalterin):
        client.force_login(buchhalterin)

        inhalt = client.get(reverse('admin:index')).content.decode()

        assert reverse('controlling') in inhalt

    def test_ohne_das_recht_auf_zahlen_gibt_es_auch_den_weg_nicht(
            self, client, monteur):
        """Ohne das Recht auf Auswertungen fehlt auch der Link zur
        Controlling-Seite."""
        client.force_login(monteur)

        inhalt = client.get(reverse('admin:index')).content.decode()

        assert reverse('controlling') not in inhalt


class TestDerVerlaufNenntSeinenZeitraum:
    """Der Titel des Verlaufs nennt seinen Zeitraum.

    Die Karte "Fakturiert" gilt für das Kalenderjahr, der Verlauf für die
    letzten zwölf Monate; die Säulen summieren sich deshalb nicht zur Zahl
    der Karte. Die Zeiträume bleiben verschieden: Das Kalenderjahr ist die
    kaufmännische Größe, der rollende Verlauf fällt am 1. Januar nicht auf
    null, und ``controlling.reichweite`` rechnet auf demselben Verlauf.
    """

    def test_der_titel_nennt_die_zwoelf_monate(self, client, buchhalterin):
        client.force_login(buchhalterin)

        inhalt = client.get(reverse('admin:index')).content.decode()

        assert 'in den letzten 12 Monaten' in inhalt

    def test_und_die_jahreszahl_steht_weiterhin_daneben(self, client,
                                                        buchhalterin):
        """Die Jahreszahl der Karte bleibt erhalten."""
        client.force_login(buchhalterin)

        inhalt = client.get(reverse('admin:index')).content.decode()

        assert 'laufenden Jahr' in inhalt


class TestDerStaerksteMonatIstEinMonat:
    """Der Spitzenmonat wird mit Monat und Betrag genannt.

    Bei zwölf schmalen Säulen ist der Monat nicht ablesbar.
    """

    def test_der_satz_nennt_monat_und_betrag(self, client, buchhalterin,
                                             projekt_mit_stand):
        from django.utils import timezone

        from faktura.models import Beleg, BelegTyp

        heute = timezone.localdate()
        Beleg.objects.filter(typ=BelegTyp.RECHNUNG).update(belegdatum=heute)
        client.force_login(buchhalterin)

        inhalt = client.get(reverse('admin:index')).content.decode()

        monate = ('Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
                  'Juli', 'August', 'September', 'Oktober', 'November',
                  'Dezember')
        assert 'Stärkster Monat:' in inhalt
        assert f'{monate[heute.month - 1]} {heute.year} mit' in inhalt

    def test_ohne_umsatz_steht_dort_nichts(self, client, buchhalterin):
        """Ohne Umsatz erscheint kein Spitzenmonat."""
        client.force_login(buchhalterin)

        inhalt = client.get(reverse('admin:index')).content.decode()

        assert 'Stärkster Monat:' not in inhalt

    def test_der_monatsname_kommt_aus_django(self):
        """Der Monatsname kommt aus ``date_format`` und damit aus Djangos
        Übersetzung."""
        from faktura import formate

        assert formate.monat(2026, 1) == 'Januar 2026'
        assert formate.monat(2025, 10) == 'Oktober 2025'


@pytest.mark.django_db
class TestDieKarteOffeneForderungen:
    """Karte "Offene Forderungen".

    Geprüft werden Auswahl und Hinweis; die Berechnung prüft
    ``faktura/tests/test_zahlungen.py``. Eine Summe ohne Zahlungseingänge sähe
    ebenso plausibel aus.
    """

    def test_die_karte_nennt_den_offenen_bruttobetrag(
            self, client, buchhalterin, projekt_mit_stand):
        """3.000 netto ergeben 3.570 brutto offen."""
        client.force_login(buchhalterin)

        inhalt = client.get(reverse('admin:index')).content.decode()

        assert 'Offene Forderungen' in inhalt
        assert '3.570' in inhalt
        assert 'Gemahnt' not in inhalt

    def test_eine_bezahlte_rechnung_faellt_aus_der_karte(
            self, client, buchhalterin, projekt_mit_stand):
        """Eine bezahlte Rechnung zählt nicht mehr als offen."""
        from datetime import date

        from faktura.models import Beleg, BelegTyp

        rechnung = Beleg.objects.get(typ=BelegTyp.RECHNUNG)
        services.zahlung_verbuchen(
            beleg_id=rechnung.pk, datum=date(2026, 2, 1),
            betrag=Decimal('3570.00'))
        client.force_login(buchhalterin)

        inhalt = client.get(reverse('admin:index')).content.decode()

        assert '3.570' not in inhalt
        assert 'Nichts über die Frist' in inhalt

    def test_ueberfaelliges_steht_mit_seinem_alter_darunter(
            self, client, buchhalterin, projekt_mit_stand):
        """Überfällige Forderungen erscheinen mit ihrem Alter."""
        from datetime import timedelta

        from django.utils import timezone

        from faktura.models import Beleg, BelegTyp

        # Am festgeschriebenen Beleg nur per QuerySet.update(), weil
        # ``save`` die Änderung ablehnt.
        Beleg.objects.filter(typ=BelegTyp.RECHNUNG).update(
            faellig_am=timezone.localdate() - timedelta(days=120))
        client.force_login(buchhalterin)

        inhalt = client.get(reverse('admin:index')).content.decode()

        assert 'über die Frist' in inhalt
        assert 'seit 120 Tagen' in inhalt
