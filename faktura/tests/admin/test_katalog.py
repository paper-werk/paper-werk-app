"""Leistungskatalog und Katalogsuche im Admin."""

from decimal import Decimal

import pytest
from django.urls import reverse

from faktura import services
from faktura.models import (
    Beleg,
    BelegTyp,
)
from faktura.tests.admin.hilfen import User


@pytest.mark.django_db
class TestLeistungskatalog:
    """Der Katalog füllt eine Positionszeile durch Kopie.

    Der Vorrang folgt aus changed_data: Die Auswahl füllt nur vom Benutzer
    nicht geänderte Felder, auch wenn sie einen Default haben ('Stk',
    19 %). Eine Regel "nur leere Felder" erfasste diese Defaults nicht.

    Die Textbausteine verwenden ein anderes Verfahren, siehe
    TestBausteinAuswahl.
    """

    @pytest.fixture
    def katalog(self, db):
        from faktura.models import Katalogposition
        return Katalogposition.objects.create(
            bezeichnung='Beratungsstunde',
            einheit='Std',
            einzelpreis=Decimal('120.00'),
            steuersatz='19.00',
        )

    def _angebot_anlegen(self, client, kunde, **extra):
        """POST auf das Formular zum Anlegen, mit einer Positionszeile."""
        daten = {
            'kunde': kunde.pk,
            'betreff': 'Testangebot',
            'belegdatum': '', 'leistungsdatum': '', 'leistungsdatum_bis': '',
            'zahlungsziel_tage': '14',
            'kopftext': '', 'fusstext': '',
            'positionen-TOTAL_FORMS': '1', 'positionen-INITIAL_FORMS': '0',
            'positionen-MIN_NUM_FORMS': '0', 'positionen-MAX_NUM_FORMS': '1000',
            # Die Zeile wie vom Browser gesendet, mit unveränderten
            # Defaults.
            'positionen-0-katalog': '',
            'positionen-0-position': '10',
            'positionen-0-bezeichnung': '',
            'positionen-0-menge': '1',
            'positionen-0-einheit': 'Stk',
            'positionen-0-einzelpreis': '',
            'positionen-0-steuersatz': '19.00',
        }
        daten.update(extra)
        return client.post(reverse('admin:faktura_angebot_add'), daten, follow=True)

    def test_katalog_fuellt_die_positionszeile(self, buero, kunde, katalog):
        """Der Default 'Stk' wird durch den Katalog ersetzt, weil er keine
        Eingabe ist."""
        self._angebot_anlegen(buero, kunde, **{
            'positionen-0-katalog': str(katalog.pk),
        })

        beleg = Beleg.objects.filter(typ=BelegTyp.ANGEBOT).latest('pk')
        position = beleg.positionen.get()
        assert position.bezeichnung == 'Beratungsstunde'
        assert position.einheit == 'Std'
        assert position.einzelpreis == Decimal('120.00')

    def test_eigener_preis_gewinnt_gegen_den_katalog(self, buero, kunde, katalog):
        """Ein eingegebener Preis hat Vorrang vor dem Katalog."""
        self._angebot_anlegen(buero, kunde, **{
            'positionen-0-katalog': str(katalog.pk),
            'positionen-0-einzelpreis': '99.00',
        })

        beleg = Beleg.objects.filter(typ=BelegTyp.ANGEBOT).latest('pk')
        position = beleg.positionen.get()
        assert position.bezeichnung == 'Beratungsstunde'
        assert position.einzelpreis == Decimal('99.00')

    def test_ohne_katalog_bleibt_die_bezeichnung_pflicht(self, buero, kunde):
        """Ohne Katalogauswahl bleibt die Bezeichnung Pflicht."""
        antwort = self._angebot_anlegen(buero, kunde, **{
            'positionen-0-menge': '2',
        })

        assert 'Angeben oder eine Katalogposition' in antwort.content.decode()
        assert not Beleg.objects.filter(typ=BelegTyp.ANGEBOT).exists()

    def test_preisaenderung_im_katalog_laesst_den_beleg_unberuehrt(
        self, buero, kunde, katalog
    ):
        """Eine Preisänderung im Katalog ändert bestehende Belege nicht.

        Ohne Fremdschlüssel trivial; der Test schlägt fehl, sobald einer
        eingeführt wird.
        """
        self._angebot_anlegen(buero, kunde, **{
            'positionen-0-katalog': str(katalog.pk),
        })

        katalog.einzelpreis = Decimal('150.00')
        katalog.save()

        beleg = Beleg.objects.filter(typ=BelegTyp.ANGEBOT).latest('pk')
        assert beleg.positionen.get().einzelpreis == Decimal('120.00')

    def test_lieferschein_bleibt_auch_mit_katalog_preisfrei(
        self, buero, kunde, katalog
    ):
        """Der Lieferschein speichert auch bei Katalogauswahl keinen Preis,
        weil die Nullpreis-Regel nach der Übernahme greift."""
        buero.post(
            reverse('admin:faktura_lieferschein_add'),
            {
                'kunde': kunde.pk, 'betreff': 'Lieferung',
                'belegdatum': '', 'leistungsdatum': '', 'leistungsdatum_bis': '',
                'zahlungsziel_tage': '14',
                'kopftext': '', 'fusstext': '',
                'positionen-TOTAL_FORMS': '1', 'positionen-INITIAL_FORMS': '0',
                'positionen-MIN_NUM_FORMS': '0', 'positionen-MAX_NUM_FORMS': '1000',
                'positionen-0-katalog': str(katalog.pk),
                'positionen-0-position': '10',
                'positionen-0-bezeichnung': '',
                'positionen-0-menge': '3',
                'positionen-0-einheit': 'Stk',
            },
            follow=True,
        )

        beleg = Beleg.objects.filter(typ=BelegTyp.LIEFERSCHEIN).latest('pk')
        position = beleg.positionen.get()
        assert position.bezeichnung == 'Beratungsstunde'
        assert position.einzelpreis == Decimal('0.00')
        assert position.steuersatz == '0.00'

    def test_katalogdienst_liefert_den_preis_als_zeichenkette(
        self, buero, katalog
    ):
        """Preis als String mit Punkt, weil eine JSON-Zahl zum float würde und
        das Zielfeld ein input type="number" mit diesem Format ist."""
        antwort = buero.get(
            reverse('admin:faktura_katalogposition_daten'),
            {'katalog': katalog.pk},
        )

        daten = antwort.json()
        assert daten['einzelpreis'] == '120.00'
        assert daten['bezeichnung'] == 'Beratungsstunde'


@pytest.mark.django_db
class TestKatalogsuche:
    """Die Katalogauswahl über der Positionszeile sucht bei Eingabe.

    Bei hunderten Leistungen wäre ein Select unbrauchbar und stünde in
    jeder Zeile vollständig im HTML. Gesucht wird wie in der Katalogliste:
    Nummer, Bezeichnung, Langtext.
    """

    @pytest.fixture
    def katalog(self, db):
        from faktura.models import Katalogposition
        return [
            Katalogposition.objects.create(
                nummer='B-100', bezeichnung='Rammkernsondierung',
                langtext='bis 6 m unter Gelände, inkl. Schichtenverzeichnis',
                einzelpreis=Decimal('38.00')),
            Katalogposition.objects.create(
                nummer='L-200', bezeichnung='Bodenanalyse Parameterumfang',
                einzelpreis=Decimal('95.00')),
            Katalogposition.objects.create(
                bezeichnung='Probenahme vor Ort', einzelpreis=Decimal('85.00')),
        ]

    def _suche(self, client, **params):
        antwort = client.get(
            reverse('admin:faktura_katalogposition_suche'), params)
        assert antwort.status_code == 200
        return antwort.json()

    def _texte(self, daten):
        return [eintrag['text'] for eintrag in daten['results']]

    def test_findet_ueber_die_bezeichnung(self, buero, katalog):
        daten = self._suche(buero, term='probenahme')

        assert self._texte(daten) == ['Probenahme vor Ort']
        assert daten['results'][0]['id'] == katalog[2].pk

    def test_findet_ueber_die_nummer(self, buero, katalog):
        assert self._texte(self._suche(buero, term='L-200')) == [
            'L-200 Bodenanalyse Parameterumfang']

    def test_findet_ueber_ein_wort_im_langtext(self, buero, katalog):
        """Die Suche trifft Wörter im Langtext ('Schichtenverzeichnis')."""
        assert self._texte(self._suche(buero, term='Schichtenverzeichnis')) \
            == ['B-100 Rammkernsondierung']

    def test_ohne_begriff_kommt_der_katalog_in_seiten(self, buero, db):
        from faktura.admin.stammdaten import KatalogpositionAdmin
        from faktura.models import Katalogposition
        je_seite = KatalogpositionAdmin.SUCHTREFFER_JE_SEITE
        Katalogposition.objects.bulk_create(
            Katalogposition(bezeichnung=f'Leistung {i:03d}',
                            einzelpreis=Decimal('1.00'))
            for i in range(je_seite + 5))

        erste = self._suche(buero)
        zweite = self._suche(buero, page=2)

        assert len(erste['results']) == je_seite
        assert erste['pagination']['more'] is True
        assert len(zweite['results']) == 5
        assert zweite['pagination']['more'] is False

    def test_ohne_leserecht_am_katalog_kein_treffer(self, client, katalog):
        """Ohne View-Recht am Katalog kein Treffer; is_staff erlaubt nur die
        Anmeldung."""
        User.objects.create_user(
            username='ohne-faktura', email='o@example.com',
            password='geheim12345', is_staff=True,
        )
        client.login(username='ohne-faktura', password='geheim12345')

        antwort = client.get(
            reverse('admin:faktura_katalogposition_suche'), {'term': 'Boden'})

        assert antwort.status_code == 403

    def test_im_html_steht_nicht_der_ganze_katalog(self, buero, kunde,
                                                   katalog):
        """Das HTML enthält nur die gewählte Position."""
        beleg = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.ANGEBOT, betreff='Erkundung')

        seite = buero.get(reverse('admin:faktura_angebot_change',
                                  args=[beleg.pk])).content.decode()

        assert 'data-katalog-suche' in seite
        assert 'Rammkernsondierung' not in seite

    def test_nach_einem_fehler_bleibt_die_auswahl_stehen(self, buero, kunde,
                                                         katalog):
        """Nach einem Validierungsfehler bleibt die gewählte Leistung
        ausgewählt."""
        antwort = buero.post(reverse('admin:faktura_angebot_add'), {
            'kunde': kunde.pk, 'betreff': 'Erkundung',
            'belegdatum': '', 'leistungsdatum': '', 'leistungsdatum_bis': '',
            'zahlungsziel_tage': '14', 'kopftext': '', 'fusstext': '',
            'positionen-TOTAL_FORMS': '1', 'positionen-INITIAL_FORMS': '0',
            'positionen-MIN_NUM_FORMS': '0', 'positionen-MAX_NUM_FORMS': '1000',
            'positionen-0-katalog': str(katalog[0].pk),
            'positionen-0-position': '10',
            'positionen-0-bezeichnung': '',
            # Fehler, der das Formular erneut anzeigt.
            'positionen-0-menge': 'viel',
            'positionen-0-einheit': 'Stk',
            'positionen-0-einzelpreis': '',
            'positionen-0-steuersatz': '19.00',
        })

        seite = antwort.content.decode()
        assert not Beleg.objects.filter(betreff='Erkundung').exists()
        assert (f'<option value="{katalog[0].pk}" selected>'
                'B-100 Rammkernsondierung</option>') in seite
        assert 'Bodenanalyse' not in seite
