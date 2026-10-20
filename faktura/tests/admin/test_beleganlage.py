"""Anlegen von Belegen und Pflichtangaben je Belegart."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib import admin
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from faktura import services
from faktura.admin import BelegAdmin
from faktura.models import (
    Angebot,
    Beleg,
    BelegTyp,
    Katalogposition,
    Lieferschein,
)
from faktura.tests.admin.hilfen import User


@pytest.mark.django_db
class TestLieferscheinAnlegen:
    """Der Lieferschein zeigt beim Anlegen dieselben Felder wie beim Ändern.

    Regression: Er hatte eigene fieldsets nur zum Ändern und zeigte beim
    Anlegen die der Basisklasse (Zahlungsziel, USt-IdNr., Leitweg-ID,
    E-Rechnungsblock), die nach dem Speichern verschwanden.
    """

    ERECHNUNGSFELDER = ['empfaenger_land', 'zahlungsziel_tage', 'leitweg_id',
                        'empfaenger_ust_id', 'bestellnummer']

    def test_anlegemaske_zeigt_keine_erechnungsfelder(self, buero):
        inhalt = buero.get(
            reverse('admin:faktura_lieferschein_add')
        ).content.decode()

        gezeigt = [f for f in self.ERECHNUNGSFELDER if f'id_{f}"' in inhalt]
        assert not gezeigt, f'nicht erwartet: {gezeigt}'
        # Die Felder des Lieferscheins sind vorhanden.
        assert 'id_empfaenger"' in inhalt
        assert 'id_kunde"' in inhalt

    def test_aenderungsmaske_zeigt_sie_ebenfalls_nicht(self, buero, kunde):
        """Auch das Änderungsformular zeigt die Felder nicht."""
        lieferschein = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.LIEFERSCHEIN
        )
        inhalt = buero.get(
            reverse('admin:faktura_lieferschein_change', args=[lieferschein.pk])
        ).content.decode()

        gezeigt = [f for f in self.ERECHNUNGSFELDER if f'id_{f}"' in inhalt]
        assert not gezeigt, f'nicht erwartet: {gezeigt}'

    def test_ausgeblendete_felder_kommen_trotzdem_aus_den_stammdaten(
        self, buero, kunde
    ):
        """Ausgeblendete Felder füllt der Server aus den Stammdaten, weil aus
        dem Lieferschein eine Rechnung werden kann."""
        kunde.ust_id = 'DE111222333'
        kunde.zahlungsziel_tage = 30
        kunde.save()

        buero.post(
            reverse('admin:faktura_lieferschein_add'),
            {
                'kunde': kunde.pk, 'betreff': 'Lieferung',
                'empfaenger': '', 'belegdatum': '', 'leistungsdatum': '',
                'kopftext': '', 'fusstext': '',
                'positionen-TOTAL_FORMS': '0', 'positionen-INITIAL_FORMS': '0',
                'positionen-MIN_NUM_FORMS': '0',
                'positionen-MAX_NUM_FORMS': '1000',
            },
            follow=True,
        )

        beleg = Beleg.objects.filter(typ=BelegTyp.LIEFERSCHEIN).latest('pk')
        assert beleg.empfaenger_ust_id == 'DE111222333'
        assert beleg.zahlungsziel_tage == 30
        assert beleg.empfaenger_name == kunde.name


@pytest.mark.django_db
class TestRechteAnDenJsonDiensten:
    """Die JSON-Endpunkte prüfen das View-Recht am Modell.

    ``AdminSite.admin_view()`` prüft nur ``is_active and is_staff``.
    Regression: Die drei Endpunkte zur Vorbelegung waren für jeden Benutzer
    mit Admin-Zugang erreichbar, auch ohne Recht in faktura; der Katalog
    lieferte Preise, die der Lieferschein bewusst ausblendet.

    Geprüft wird das Recht am Modell, wie beim Autocomplete von Django.
    """

    @pytest.fixture
    def dienste(self, kunde):
        katalog = Katalogposition.objects.create(
            bezeichnung='Montagestunde', einzelpreis=Decimal('95.00')
        )
        return [
            (reverse('admin:faktura_katalogposition_daten'),
             {'katalog': katalog.pk}, 'view_katalogposition'),
            (reverse('admin:faktura_angebot_kundendaten'),
             {'kunde': kunde.pk}, 'view_kontakt'),
        ]

    @pytest.fixture
    def monteur(self, client, db):
        """Benutzer mit Admin-Zugang ohne Rechte in faktura."""
        User.objects.create_user(
            username='monteur', email='m@example.com',
            password='geheim12345', is_staff=True,
        )
        client.login(username='monteur', password='geheim12345')
        return client

    def test_ohne_recht_kein_zugriff(self, monteur, dienste):
        for adresse, parameter, _ in dienste:
            antwort = monteur.get(adresse, parameter)
            assert antwort.status_code == 403, f'{adresse} lieferte Daten'

    def test_mit_recht_kommen_die_daten(self, monteur, dienste):
        from django.contrib.auth.models import Permission

        benutzer = User.objects.get(username='monteur')
        for _, _, recht in dienste:
            benutzer.user_permissions.add(
                Permission.objects.get(codename=recht)
            )

        for adresse, parameter, _ in dienste:
            antwort = monteur.get(adresse, parameter)
            assert antwort.status_code == 200, f'{adresse} verweigerte'
            assert antwort.json()

    def test_angemeldet_bleibt_pflicht(self, client, kunde):
        """Ohne Anmeldung weiterhin kein Zugriff."""
        antwort = client.get(
            reverse('admin:faktura_angebot_kundendaten'), {'kunde': kunde.pk}
        )

        assert antwort.status_code == 302
        assert '/admin/login/' in antwort['Location']


class TestRuecksprungNachFehler:
    """Der Redirect nach einem Fehler ignoriert fremde Referer.

    Der Referer ist vom Client bestimmt. Regression: Ein Link von einer
    fremden Seite auf die PDF-URL wurde bei einem Renderfehler zum
    Redirect-Ziel.
    """

    @staticmethod
    def _anfrage(referer):
        from django.test import RequestFactory

        anfrage = RequestFactory().get('/admin/faktura/rechnung/1/pdf/')
        if referer is not None:
            anfrage.META['HTTP_REFERER'] = referer
        return anfrage

    def test_eigene_adresse_wird_angenommen(self):
        ziel = BelegAdmin._zurueck(
            self._anfrage('http://testserver/admin/faktura/rechnung/')
        )

        assert ziel.endswith('/admin/faktura/rechnung/')

    def test_fremde_adresse_wird_verworfen(self):
        assert BelegAdmin._zurueck(
            self._anfrage('https://boese.example.com/falle')
        ) == '..'

    def test_ohne_referer_geht_es_eine_ebene_hoch(self):
        assert BelegAdmin._zurueck(self._anfrage(None)) == '..'


@pytest.mark.django_db
class TestNeuanlageMerkmal:
    """Das Attribut für das Anlegen hält Anzeige und gespeicherten Wert
    gleich.

    Das Skript füllt nur vom Benutzer nicht ausgefüllte Felder.
    Zahlungsziel und Ländercode haben aber Defaults; ohne Attribut für das
    Anlegen zeigte das Formular 14, während der Server 30 speicherte.
    """

    def test_anlegeformular_traegt_das_merkmal(self, buero):
        inhalt = buero.get(reverse('admin:faktura_angebot_add')).content.decode()

        assert 'data-neuanlage="1"' in inhalt

    def test_aenderungsformular_traegt_es_nicht(self, buero, rechnungsentwurf):
        """Das Änderungsformular hat das Attribut nicht, weil dort ein
        Kundenwechsel sonst die ganze Anschrift überschriebe."""
        inhalt = buero.get(
            reverse('admin:faktura_rechnung_change', args=[rechnungsentwurf.pk])
        ).content.decode()

        assert 'data-neuanlage' not in inhalt


@pytest.mark.django_db
class TestLeistungsdatumJeBelegart:
    """Label und Hilfetext des Leistungsdatums je Belegart.

    Ein Feldpaar mit verschiedener Bedeutung je Belegart. Regression: Der
    Hilfetext "Pflichtangabe nach § 14 UStG" stand auch beim Angebot, für
    das es weder Leistungsdatum noch diese Pflicht gibt.
    """

    @staticmethod
    def _formularfeld(modeladmin, name):
        anfrage = RequestFactory().get('/')
        anfrage.user = User.objects.get(username='sekretariat')
        formular = modeladmin.get_form(anfrage, None)()
        return formular.fields[name]


    def test_lieferschein_nennt_es_lieferdatum(self, buero):
        feld = self._formularfeld(
            admin.site._registry[Lieferschein], 'leistungsdatum'
        )

        assert feld.label == 'Lieferdatum'

    def test_mahnung_zeigt_das_feld_gar_nicht(self, buero, kunde, ueberfaellig):
        """Die Mahnung hat kein Leistungsdatum, weil sie eine berechnete
        Leistung erneut fordert."""
        rechnung = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.RECHNUNG,
            leistungsdatum=timezone.localdate(),
        )
        services.position_hinzufuegen(
            beleg=rechnung, bezeichnung='X', menge=Decimal('1'),
            einzelpreis=Decimal('10.00'), steuersatz='19.00',
        )
        original = ueberfaellig(rechnung)
        mahnung = services.mahnung_erstellen(beleg_id=original.pk, stufe=1)

        inhalt = buero.get(
            reverse('admin:faktura_mahnung_change', args=[mahnung.pk])
        ).content.decode()

        assert 'id_leistungsdatum' not in inhalt
        # Die Felder der Mahnung sind vorhanden.
        assert 'id_mahnstufe' in inhalt
        # Als Select mit Namen, ohne Zahl mit Legende.
        assert '<select name="mahnstufe"' in inhalt
        assert '>Zahlungserinnerung</option>' in inhalt
        assert '1 = Zahlungserinnerung' not in inhalt


@pytest.mark.django_db
class TestZeitraumLaeuftNichtRueckwaerts:
    """Ein Leistungszeitraum endet nicht vor seinem Beginn.

    Regression: Ein Beleg hatte "01.09.2026 bis 31.08.2026" ohne Fehler.
    Der Zeitraum ist Pflichtangabe nach § 14 Abs. 4 Nr. 6 UStG.
    """

    def test_rueckwaerts_wird_abgewiesen(self, kunde):
        from django.core.exceptions import ValidationError

        beleg = Beleg(
            kunde=kunde, typ=BelegTyp.ANGEBOT,
            leistungsdatum=date(2026, 9, 1),
            leistungsdatum_bis=date(2026, 8, 31),
        )

        with pytest.raises(ValidationError) as fehler:
            beleg.full_clean()

        assert 'leistungsdatum_bis' in fehler.value.error_dict

    def test_gleicher_tag_ist_erlaubt(self, kunde):
        """Ein eintägiger Zeitraum ist zulässig."""
        beleg = Beleg(
            kunde=kunde, typ=BelegTyp.ANGEBOT,
            leistungsdatum=date(2026, 9, 1),
            leistungsdatum_bis=date(2026, 9, 1),
        )
        beleg.full_clean()

    def test_nur_ein_datum_ist_erlaubt(self, kunde):
        """Ein einzelnes Datum ohne Ende ist zulässig."""
        beleg = Beleg(
            kunde=kunde, typ=BelegTyp.ANGEBOT,
            leistungsdatum=date(2026, 9, 1),
        )
        beleg.full_clean()

    def test_das_admin_formular_meldet_es_am_feld(self, buero, kunde):
        """Das Admin-Formular meldet den Fehler am Feld."""
        antwort = buero.post(
            reverse('admin:faktura_angebot_add'),
            {
                'kunde': kunde.pk, 'betreff': 'Rückwärts',
                'empfaenger': '', 'empfaenger_ust_id': '',
                'empfaenger_land': 'DE', 'zahlungsziel_tage': '14',
                'belegdatum': '',
                'leistungsdatum': '01.09.2026',
                'leistungsdatum_bis': '31.08.2026',
                'kopftext': '', 'fusstext': '',
                'positionen-TOTAL_FORMS': '0', 'positionen-INITIAL_FORMS': '0',
                'positionen-MIN_NUM_FORMS': '0',
                'positionen-MAX_NUM_FORMS': '1000',
            },
        )

        assert antwort.status_code == 200, 'kein Redirect; also nicht gespeichert'
        assert not Beleg.objects.filter(betreff='Rückwärts').exists()
        assert 'liegt vor' in antwort.content.decode()


@pytest.mark.django_db
class TestTerminbezeichnungAufDemBeleg:
    """Bezeichnung des Termins im Infoblock des PDFs.

    Geprüft am HTML, weil Template und CSS dieselben sind und der
    WeasyPrint-Lauf (etwa 0,25 s je Beleg) entfällt.
    """

    @staticmethod
    def _beleg(kunde, typ):
        beleg = services.beleg_anlegen(
            kunde=kunde, typ=typ,
            leistungsdatum=date(2026, 9, 1),
        )
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Leistung', menge=Decimal('1'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00',
        )
        return beleg

    def test_rechnung_nennt_das_leistungsdatum(self, kunde):
        from faktura import pdf

        html = pdf.beleg_als_html(self._beleg(kunde, BelegTyp.RECHNUNG))

        assert 'Leistungsdatum' in html

    def test_angebot_nennt_die_ausfuehrung(self, kunde):
        """Das Angebot nennt die Ausführung, weil die Leistung noch nicht
        erbracht ist."""
        from faktura import pdf

        html = pdf.beleg_als_html(self._beleg(kunde, BelegTyp.ANGEBOT))

        assert 'Ausf&uuml;hrung' in html or 'Ausführung' in html
        assert 'Leistungsdatum' not in html

    def test_lieferschein_nennt_das_lieferdatum(self, kunde):
        from faktura import pdf

        html = pdf.beleg_als_html(self._beleg(kunde, BelegTyp.LIEFERSCHEIN))

        assert 'Lieferdatum' in html
        assert 'Leistungsdatum' not in html

    def test_zeitraum_wird_als_zeitraum_bezeichnet(self, kunde):
        """Mit zwei Daten heißt es Zeitraum, mit einem nicht."""
        from faktura import pdf

        beleg = self._beleg(kunde, BelegTyp.ANGEBOT)
        beleg.leistungsdatum_bis = date(2026, 10, 31)

        html = pdf.beleg_als_html(beleg)

        assert 'szeitraum' in html
        assert '31.10.2026' in html


@pytest.mark.django_db
class TestZahlbarBisNurWoEsGilt:
    """"Zahlbar bis" nur bei Belegarten mit Zahlungsziel.

    ``faellig_am`` entsteht aus dem Zahlungsziel nur bei Rechnung, Storno,
    Korrektur und Mahnung (BelegTyp.mit_zahlungsziel). Am Angebot wäre das
    Feld immer leer.
    """

    #: Geprüft am Label, weil das Feld readonly ist (gesetzt beim
    #: Festschreiben) und Django readonly-Felder ohne ``name`` und ``id``
    #: rendert; eine Prüfung auf "faellig_am" wäre immer grün.
    BESCHRIFTUNG = 'Zahlbar bis'

    def test_das_angebot_zeigt_es_nicht(self, buero, angebot):
        inhalt = buero.get(reverse('admin:faktura_angebot_change',
                                   args=[angebot.pk])).content.decode()

        assert self.BESCHRIFTUNG not in inhalt

    def test_die_rechnung_zeigt_es_weiterhin(self, buero, rechnungsentwurf):
        """Gegenprobe: Die Rechnung zeigt "Zahlbar bis"."""
        inhalt = buero.get(reverse('admin:faktura_rechnung_change',
                                   args=[rechnungsentwurf.pk])).content.decode()

        assert self.BESCHRIFTUNG in inhalt

    def test_die_streichung_geht_ueber_das_feldbild(self, buero, angebot):
        """Das Feld fehlt in den fieldsets, nicht nur im HTML.

        Ein Feld kann im HTML fehlen, weil es aus den fieldsets entfernt
        wurde oder das Template es nicht ausgibt; gewollt ist das Erste.
        """
        from django.test import RequestFactory

        admin_klasse = admin.site.get_model_admin(Angebot)
        anfrage = RequestFactory().get('/')
        anfrage.user = User.objects.get(username='sekretariat')

        felder = []
        for _titel, optionen in admin_klasse.get_fieldsets(anfrage, angebot):
            for eintrag in optionen['fields']:
                felder.extend(eintrag if isinstance(eintrag, tuple)
                              else [eintrag])

        assert 'faellig_am' not in felder
        # Die übrigen Felder des Statusblocks sind vorhanden.
        assert 'nummer' in felder
