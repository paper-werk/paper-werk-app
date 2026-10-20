"""Übernahme der Stammdaten in Belege."""

from decimal import Decimal

import pytest
from django.contrib import admin
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from faktura import services
from faktura.models import (
    Angebot,
    Beleg,
    BelegTyp,
    Kontakt,
)


@pytest.mark.django_db
class TestStammdatenuebernahme:
    """Beim Anlegen im Admin gilt dieselbe Kopierregel wie im Service.

    Regression: Ein im Admin angelegtes Angebot hatte trotz ausgewähltem
    Kunden leere Empfängerfelder; im PDF fehlte die Anschrift.
    """

    def test_kundendaten_landen_im_beleg(self, buero, kunde):
        antwort = buero.post(
            reverse('admin:faktura_angebot_add'),
            {
                'kunde': kunde.pk,
                'betreff': 'Neues Angebot',
                'belegdatum': '',
                'leistungsdatum': '',
                'leistungsdatum_bis': '',
                'kopftext': '',
                'fusstext': '',
                # Management Form der Positionen, ohne die Django das
                # Formular ablehnt.
                'positionen-TOTAL_FORMS': '0',
                'positionen-INITIAL_FORMS': '0',
                'positionen-MIN_NUM_FORMS': '0',
                'positionen-MAX_NUM_FORMS': '1000',
            },
            follow=True,
        )

        assert antwort.status_code == 200
        beleg = Beleg.objects.filter(typ=BelegTyp.ANGEBOT).latest('pk')
        assert beleg.empfaenger == kunde.anschriftfeld
        assert kunde.name in beleg.empfaenger
        assert kunde.ort in beleg.empfaenger
        assert beleg.zahlungsziel_tage == kunde.zahlungsziel_tage

    def test_anlegeformular_zeigt_die_empfaengerfelder(self, buero):
        """Das Formular zum Anlegen zeigt die Empfängerfelder leer, mit der URL
        des Stammdaten-Endpunkts.

        Regression: Die Felder waren beim Anlegen ausgeblendet und
        erschienen erst nach dem Speichern.
        """
        antwort = buero.get(reverse('admin:faktura_angebot_add'))
        inhalt = antwort.content.decode()

        assert 'name="kunde"' in inhalt
        assert 'name="empfaenger"' in inhalt
        # Textareas sind bei Unfold standardmäßig breiter als die übrigen
        # Eingabefelder; das Empfängerfeld soll dieselbe Breite verwenden.
        anfang = inhalt.rindex('<textarea', 0, inhalt.index('name="empfaenger"'))
        feld = inhalt[anfang:inhalt.index('>', anfang)]
        assert '!max-w-2xl' in feld, feld
        # Das Skript liest die URL aus diesem Attribut.
        assert 'data-stammdaten-url' in inhalt
        assert 'kunde_uebernehmen.js' in inhalt

    def test_skript_wird_nach_jquery_geladen(self, buero):
        """Das eigene Skript wird nach jquery.init.js geladen.

        ``django.jQuery`` entsteht erst in ``admin/js/jquery.init.js``; davor
        bricht das Skript ohne sichtbaren Fehler mit "django is not defined"
        ab. Regression: Das Skript stand an fünfter Stelle, jquery.init.js
        an zehnter.

        Django führt die Media aller Widgets zusammen und beachtet nur die
        Reihenfolge innerhalb einer Media-Klasse; deshalb sind jquery.js und
        jquery.init.js dort aufgeführt.

        Geprüft wird die Reihenfolge im gerenderten HTML. Ein Test, der nur
        das Einbinden prüfte, war grün, während das Skript nicht lief.
        """
        import re

        antwort = buero.get(reverse('admin:faktura_angebot_add'))
        skripte = re.findall(
            r'<script[^>]*src="([^"]+)"', antwort.content.decode()
        )

        def platz(teil):
            treffer = [i for i, s in enumerate(skripte) if teil in s]
            assert treffer, f'{teil} wird gar nicht eingebunden'
            return treffer[0]

        assert platz('kunde_uebernehmen.js') > platz('jquery.init.js')
        # Django dedupliziert gleiche Pfade; jQuery darf nur einmal geladen
        # werden, sonst existieren zwei Instanzen.
        assert sum('vendor/jquery/jquery' in s for s in skripte) == 1

    def test_jquery_passt_zum_betriebsmodus(self):
        """Der jQuery-Pfad passt zu DEBUG.

        Django bindet je nach DEBUG jquery.js oder jquery.min.js ein. Ein
        fester Pfad passt nur zu einem Modus; im anderen entstehen zwei Pfade
        auf dieselbe Bibliothek und zwei jQuery-Instanzen.

        Geprüft direkt an der Media, ohne Request, weil die Debug Toolbar mit
        ``DEBUG=True`` URLs sucht, die im Testlauf fehlen. Die Reihenfolge
        im HTML prüft der Test darüber.
        """
        modeladmin = admin.site._registry[Angebot]

        # ``path``, weil die Einträge seit Django 6 ``forms.Script``-Objekte
        # sind, deren ``str()`` das ``<script>``-Tag liefert.
        for debug, erwartet in [(True, 'jquery.js'), (False, 'jquery.min.js')]:
            with override_settings(DEBUG=debug):
                dateien = [datei.path for datei in modeladmin.media._js]

            jquery = [d for d in dateien if 'vendor/jquery/jquery' in d]
            assert len(jquery) == 1, f'DEBUG={debug}: {jquery}'
            assert jquery[0].endswith(erwartet), f'DEBUG={debug}: {jquery[0]}'

            i_init = next(i for i, d in enumerate(dateien) if 'jquery.init' in d)
            i_mein = next(
                i for i, d in enumerate(dateien) if 'kunde_uebernehmen' in d
            )
            assert i_mein > i_init, f'DEBUG={debug}: Skript vor jquery.init'

    def test_empfaengerfelder_sind_beim_anlegen_keine_pflicht(self, buero, kunde):
        """Die Empfängerfelder sind beim Anlegen optional, weil der Server sie
        aus den Stammdaten füllt."""
        antwort = buero.get(reverse('admin:faktura_angebot_add'))
        formular = antwort.context['adminform'].form

        assert not formular.fields['empfaenger'].required

    def test_eigene_anschrift_hat_vorrang(self, buero, kunde):
        """Eine eingegebene Anschrift bleibt vollständig erhalten.

        Der Empfänger ist ein freies Textfeld; ist es gefüllt, bleibt es
        unverändert (Postfach, "z. Hd.", Auslandsformat).
        """
        buero.post(
            reverse('admin:faktura_angebot_add'),
            {
                'kunde': kunde.pk,
                'betreff': 'Mit Postfach',
                'empfaenger': 'Muster GmbH\nz. Hd. Frau Meier\nPostfach 11 22\n10115 Berlin',
                'empfaenger_ust_id': '',
                'belegdatum': '', 'leistungsdatum': '',
                'leistungsdatum_bis': '', 'zahlungsziel_tage': '14',
                'kopftext': '', 'fusstext': '',
                'positionen-TOTAL_FORMS': '0', 'positionen-INITIAL_FORMS': '0',
                'positionen-MIN_NUM_FORMS': '0', 'positionen-MAX_NUM_FORMS': '1000',
            },
            follow=True,
        )

        beleg = Beleg.objects.filter(typ=BelegTyp.ANGEBOT).latest('pk')
        assert 'Postfach 11 22' in beleg.empfaenger
        # Ohne Anteile der Anschrift aus den Stammdaten.
        assert kunde.strasse not in beleg.empfaenger

    def test_stammdatendienst_liefert_die_kundenangaben(self, buero, kunde):
        """Der JSON-Endpunkt liefert die Werte des Kunden für das Skript."""
        antwort = buero.get(
            reverse('admin:faktura_angebot_kundendaten'), {'kunde': kunde.pk}
        )

        assert antwort.status_code == 200
        daten = antwort.json()
        assert daten['empfaenger'] == kunde.anschriftfeld
        assert daten['zahlungsziel_tage'] == kunde.zahlungsziel_tage
        # Auch die strukturierten Felder für die E-Rechnung. Regression:
        # Sie blieben beim Kundenwechsel leer.
        assert daten['empfaenger_name'] == kunde.name
        assert daten['empfaenger_strasse'] == kunde.strasse
        assert daten['empfaenger_plz'] == kunde.plz
        assert daten['empfaenger_ort'] == kunde.ort

    def test_stammdatendienst_mit_hauptansprechpartner(self, buero, kunde):
        """Der Ansprechpartner wird als ID geliefert, weil JsonResponse kein
        Modellobjekt serialisiert."""
        from faktura.models import Ansprechpartner

        person = Ansprechpartner.objects.create(
            kontakt=kunde, nachname='Müller', ist_standard=True)

        antwort = buero.get(
            reverse('admin:faktura_angebot_kundendaten'), {'kunde': kunde.pk}
        )

        assert antwort.status_code == 200
        daten = antwort.json()
        assert daten['ansprechpartner'] == person.pk
        assert 'z. Hd. Müller' in daten['empfaenger']

    def test_stammdatendienst_verlangt_anmeldung(self, client, kunde):
        """Der Endpunkt liegt unter der URL des Modells und verlangt Anmeldung."""
        antwort = client.get(
            reverse('admin:faktura_angebot_kundendaten'), {'kunde': kunde.pk}
        )

        assert antwort.status_code == 302
        assert '/admin/login/' in antwort['Location']

    def test_aenderungsformular_zeigt_den_empfaenger(self, buero, rechnungsentwurf):
        """Das Änderungsformular zeigt den Empfänger, etwa für "z. Hd. ..."."""
        antwort = buero.get(
            reverse('admin:faktura_rechnung_change', args=[rechnungsentwurf.pk])
        )

        assert 'name="empfaenger"' in antwort.content.decode()


@pytest.mark.django_db
class TestStammdatenGegenFormularvorgaben:
    """Der Admin liefert dieselben Werte wie der Service.

    Regression: Ein Kunde mit 30 Tagen Zahlungsziel und Sitz in Österreich
    erhielt im Admin einen Beleg mit 14 Tagen und 'DE', weil die Regel "nur
    leere Felder füllen" die Defaults des Modells im Formular als Eingabe
    wertete. Das Zahlungsziel bestimmt die Fälligkeit, der Ländercode BT-55
    der E-Rechnung.
    """

    @pytest.fixture
    def auslandskunde(self, db):
        return Kontakt.anlegen(
            nummer='K-2000', name='Alpen AG', strasse='Bergweg 3',
            plz='1010', ort='Wien', land='AT', zahlungsziel_tage=30,
        )

    @staticmethod
    def _angebot_anlegen(buero, kunde, **abweichend):
        daten = {
            'kunde': kunde.pk,
            'betreff': 'Probe',
            'empfaenger': '', 'empfaenger_ust_id': '',
            'empfaenger_name': '', 'empfaenger_strasse': '',
            'empfaenger_plz': '', 'empfaenger_ort': '',
            # Defaults, wie das unveränderte Formular sie sendet.
            'empfaenger_land': 'DE',
            'zahlungsziel_tage': '14',
            'leitweg_id': '', 'bestellnummer': '',
            'belegdatum': '', 'leistungsdatum': '', 'leistungsdatum_bis': '',
            'kopftext': '', 'fusstext': '',
            'positionen-TOTAL_FORMS': '0', 'positionen-INITIAL_FORMS': '0',
            'positionen-MIN_NUM_FORMS': '0', 'positionen-MAX_NUM_FORMS': '1000',
        }
        daten.update(abweichend)
        buero.post(reverse('admin:faktura_angebot_add'), daten, follow=True)
        return Beleg.objects.filter(typ=BelegTyp.ANGEBOT).latest('pk')

    def test_zahlungsziel_kommt_aus_den_stammdaten(self, buero, auslandskunde):
        beleg = self._angebot_anlegen(buero, auslandskunde)

        assert beleg.zahlungsziel_tage == 30

    def test_laendercode_kommt_aus_den_stammdaten(self, buero, auslandskunde):
        beleg = self._angebot_anlegen(buero, auslandskunde)

        assert beleg.empfaenger_land == 'AT'

    def test_eigenes_zahlungsziel_gewinnt(self, buero, auslandskunde):
        """Ein eingegebenes Zahlungsziel (21) hat Vorrang vor dem des Kunden
        (30)."""
        beleg = self._angebot_anlegen(
            buero, auslandskunde, zahlungsziel_tage='21'
        )

        assert beleg.zahlungsziel_tage == 21

    def test_ausgelassenes_feld_zaehlt_nicht_als_eingabe(self, buero, auslandskunde):
        """Ein im POST fehlendes Feld gilt nicht als Eingabe.

        ``form.changed_data`` wertet einen fehlenden Wert als Änderung, weil
        er vom Initialwert abweicht; allein darauf gestützt bliebe der
        Default des Modells (14 statt 30 Tage). Der Browser sendet jedes
        Feld, ein Skript oder Import nicht.
        """
        daten = {
            'kunde': auslandskunde.pk, 'betreff': 'Ohne Zahlungsziel',
            'empfaenger': '', 'empfaenger_ust_id': '',
            'empfaenger_name': '', 'empfaenger_strasse': '',
            'empfaenger_plz': '', 'empfaenger_ort': '',
            'leitweg_id': '', 'bestellnummer': '',
            'belegdatum': '', 'leistungsdatum': '', 'leistungsdatum_bis': '',
            'kopftext': '', 'fusstext': '',
            'positionen-TOTAL_FORMS': '0', 'positionen-INITIAL_FORMS': '0',
            'positionen-MIN_NUM_FORMS': '0', 'positionen-MAX_NUM_FORMS': '1000',
        }
        # zahlungsziel_tage und empfaenger_land fehlen bewusst.
        buero.post(reverse('admin:faktura_angebot_add'), daten, follow=True)

        beleg = Beleg.objects.filter(typ=BelegTyp.ANGEBOT).latest('pk')
        assert beleg.zahlungsziel_tage == 30
        assert beleg.empfaenger_land == 'AT'

    def test_faelligkeit_rechnet_mit_dem_kundenzahlungsziel(self, auslandskunde):
        """Die Fälligkeit beim Festschreiben folgt aus dem Zahlungsziel des
        Kunden."""
        rechnung = services.beleg_anlegen(
            kunde=auslandskunde, typ=BelegTyp.RECHNUNG,
            leistungsdatum=timezone.localdate(),
        )
        services.position_hinzufuegen(
            beleg=rechnung, bezeichnung='Montage', menge=Decimal('1'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00',
        )
        festgeschrieben = services.beleg_festschreiben(beleg_id=rechnung.pk)

        assert (festgeschrieben.faellig_am - festgeschrieben.belegdatum).days == 30


@pytest.mark.django_db
class TestAbweichungswarnung:
    """Abweichende Anschriften werden gemeldet und nicht automatisch
    korrigiert, damit jede Änderung am Beleg nachvollziehbar bleibt."""

    @staticmethod
    def _meldungen(antwort):
        return [str(m) for m in antwort.context['messages']]

    def test_abweichende_anschrift_wird_beim_sichern_gemeldet(self, buero, kunde):
        antwort = buero.post(
            reverse('admin:faktura_angebot_add'),
            {
                'kunde': kunde.pk, 'betreff': 'Mit Postfach',
                'empfaenger': 'Muster GmbH\nPostfach 11 22\n10115 Berlin',
                'empfaenger_ust_id': '', 'empfaenger_land': 'DE',
                'belegdatum': '', 'leistungsdatum': '',
                'leistungsdatum_bis': '', 'zahlungsziel_tage': '14',
                'kopftext': '', 'fusstext': '',
                'positionen-TOTAL_FORMS': '0', 'positionen-INITIAL_FORMS': '0',
                'positionen-MIN_NUM_FORMS': '0',
                'positionen-MAX_NUM_FORMS': '1000',
            },
            follow=True,
        )

        warnungen = [m for m in self._meldungen(antwort) if 'weichen ab' in m]
        assert warnungen, self._meldungen(antwort)
        assert 'Hauptstraße 1' in warnungen[0]

    def test_ohne_abweichung_keine_warnung(self, buero, kunde):
        """Im Regelfall (Kunde gewählt, sonst nichts geändert) keine Warnung."""
        antwort = buero.post(
            reverse('admin:faktura_angebot_add'),
            {
                'kunde': kunde.pk, 'betreff': 'Ganz normal',
                'empfaenger': '', 'empfaenger_ust_id': '',
                'empfaenger_land': 'DE',
                'belegdatum': '', 'leistungsdatum': '',
                'leistungsdatum_bis': '', 'zahlungsziel_tage': '14',
                'kopftext': '', 'fusstext': '',
                'positionen-TOTAL_FORMS': '0', 'positionen-INITIAL_FORMS': '0',
                'positionen-MIN_NUM_FORMS': '0',
                'positionen-MAX_NUM_FORMS': '1000',
            },
            follow=True,
        )

        assert not [m for m in self._meldungen(antwort) if 'weichen ab' in m]

    def test_warnung_auch_beim_festschreiben(self, buero, rechnungsentwurf):
        """Die Warnung erscheint auch beim Festschreiben, weil dort PDF und XML
        entstehen."""
        Beleg.objects.filter(pk=rechnungsentwurf.pk).update(
            empfaenger='Ganz Anders GmbH\nAndere Straße 9\n99999 Nirgendwo'
        )

        antwort = buero.post(
            reverse('admin:faktura_rechnung_changelist'),
            {
                'action': 'action_festschreiben',
                '_selected_action': [str(rechnungsentwurf.pk)],
            },
            follow=True,
        )

        warnungen = [m for m in self._meldungen(antwort) if 'weichen ab' in m]
        assert warnungen, self._meldungen(antwort)
        assert 'Stornierung' in warnungen[0]
