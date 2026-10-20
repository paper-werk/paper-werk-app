"""Positionen und Belegformular im Admin."""

import re
from decimal import Decimal

import pytest
from django.urls import reverse

from faktura import services
from faktura.models import (
    Beleg,
    BelegTyp,
)


@pytest.mark.django_db
class TestDieErsteZeileEinerPosition:
    """Die Katalogsuche steht über der Positionszeile.

    Verworfen: eine eigene Spalte, die für lange Bezeichnungen zu schmal war
    und keinen Platz für weitere Angaben ließ.
    """

    def _maske(self, client, ansicht='angebot'):
        return client.get(
            reverse(f'admin:faktura_{ansicht}_add')).content.decode()

    def test_die_suche_steht_vor_der_positionszeile(self, buero):
        seite = self._maske(buero)

        erste_zeile = seite.index('form-row-erste-zeile')
        katalog = seite.index('name="positionen-0-katalog"')
        positionszeile = seite.index('hat-erste-zeile')
        nummer = seite.index('name="positionen-0-position"')
        assert erste_zeile < katalog < positionszeile < nummer

    def test_und_hat_keine_spalte_im_tabellenkopf(self, buero):
        seite = self._maske(buero)

        assert 'column-bezeichnung' in seite
        assert 'column-katalog' not in seite

    def test_auch_der_lieferschein_hat_sie(self, buero):
        seite = self._maske(buero, 'lieferschein')

        assert 'form-row-erste-zeile' in seite
        assert 'column-katalog' not in seite

    def test_am_festgeschriebenen_beleg_fehlt_sie(self, buero, kunde):
        """Am festgeschriebenen Beleg keine Katalogsuche."""
        beleg = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.ANGEBOT, betreff='Erkundung')
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Probenahme', menge=Decimal('1'),
            einzelpreis=Decimal('85.00'), steuersatz='19.00')
        services.beleg_festschreiben(beleg_id=beleg.pk)

        seite = buero.get(reverse('admin:faktura_angebot_change',
                                  args=[beleg.pk])).content.decode()

        assert 'erste-zeile-feld' not in seite

    def test_der_steuersatz_steht_kurz_da(self, buero):
        """Der Steuersatz erscheint in Kurzform für die schmale Spalte; der
        gespeicherte Wert ist derselbe."""
        seite = self._maske(buero)
        auswahl = seite.split('name="positionen-0-steuersatz"')[1] \
            .split('</select>')[0]

        assert '<option value="19.00" selected>19 %</option>' \
            in auswahl
        assert 'Regelsteuersatz' not in auswahl


@pytest.mark.django_db
class TestPositionsnummern:
    """Leere Zeilen zeigen die Nummern, die sie beim Speichern erhielten
    (10, 20, 30); eingegebene Nummern bleiben.

    Regression: Jede neue Zeile hatte den Default 10, und der
    Unique-Constraint lehnte das Speichern ab.
    """

    def _angebot_mit_zeilen(self, client, kunde, zeilen):
        daten = {
            'kunde': kunde.pk, 'betreff': 'Nummernprobe',
            'belegdatum': '', 'leistungsdatum': '', 'leistungsdatum_bis': '',
            'zahlungsziel_tage': '14',
            'empfaenger': '', 'empfaenger_ust_id': '',
            'kopftext': '', 'fusstext': '',
            'positionen-TOTAL_FORMS': str(len(zeilen)),
            'positionen-INITIAL_FORMS': '0',
            'positionen-MIN_NUM_FORMS': '0', 'positionen-MAX_NUM_FORMS': '1000',
        }
        for i, (position, bezeichnung) in enumerate(zeilen):
            daten.update({
                f'positionen-{i}-katalog': '',
                f'positionen-{i}-position': position,
                f'positionen-{i}-bezeichnung': bezeichnung,
                f'positionen-{i}-menge': '1',
                f'positionen-{i}-einheit': 'Stk',
                f'positionen-{i}-einzelpreis': '10.00',
                f'positionen-{i}-steuersatz': '19.00',
            })
        antwort = client.post(reverse('admin:faktura_angebot_add'), daten, follow=True)
        assert antwort.status_code == 200
        return Beleg.objects.filter(typ=BelegTyp.ANGEBOT).latest('pk')

    def _nummern(self, beleg):
        return list(beleg.positionen.values_list('position', flat=True))

    def test_leere_nummern_werden_in_zehnerschritten_vergeben(self, buero, kunde):
        beleg = self._angebot_mit_zeilen(buero, kunde, [
            ('', 'Erste'), ('', 'Zweite'), ('', 'Dritte'),
        ])

        assert self._nummern(beleg) == ['10', '20', '30']

    def test_eigene_nummern_bleiben_und_es_zaehlt_dahinter_weiter(
        self, buero, kunde
    ):
        beleg = self._angebot_mit_zeilen(buero, kunde, [
            ('10', 'Erste'), ('20', 'Zweite'), ('', 'Dritte'),
        ])

        assert self._nummern(beleg) == ['10', '20', '30']

    def test_einerschritte_werden_erkannt(self, buero, kunde):
        """Nach 1, 2, 3 folgt 4, nicht 13."""
        beleg = self._angebot_mit_zeilen(buero, kunde, [
            ('1', 'Erste'), ('2', 'Zweite'), ('', 'Dritte'),
        ])

        assert self._nummern(beleg) == ['1', '2', '3']

    def _vorbelegt(self, client, adresse):
        """Initialwerte der Nummern in den Zeilen des Formulars."""
        seite = client.get(adresse).content.decode()
        return re.findall(
            r'name="positionen-\d+-position" value="([^"]*)"', seite)

    def test_ein_neuer_beleg_zeigt_10_20_30(self, buero):
        assert self._vorbelegt(
            buero, reverse('admin:faktura_angebot_add')) == ['10', '20', '30']

    def test_hinter_vorhandenen_geht_es_weiter(self, buero, kunde):
        beleg = self._angebot_mit_zeilen(buero, kunde, [
            ('10', 'Erste'), ('20', 'Zweite'),
        ])

        # Unter vorhandenen Positionen nur eine leere Zeile
        # (BelegpositionInline.get_extra).
        assert self._vorbelegt(buero, reverse(
            'admin:faktura_angebot_change', args=[beleg.pk])) \
            == ['10', '20', '30']

    def test_auch_die_vorbelegung_kennt_einerschritte(self, buero, kunde):
        beleg = self._angebot_mit_zeilen(buero, kunde, [
            ('1', 'Erste'), ('2', 'Zweite'),
        ])

        assert self._vorbelegt(buero, reverse(
            'admin:faktura_angebot_change', args=[beleg.pk])) \
            == ['1', '2', '3']

    def _zeile(self, i, position, bezeichnung=''):
        return {
            f'positionen-{i}-katalog': '',
            f'positionen-{i}-position': position,
            f'positionen-{i}-bezeichnung': bezeichnung,
            f'positionen-{i}-menge': '1',
            f'positionen-{i}-einheit': 'Stk',
            f'positionen-{i}-einzelpreis': '10.00' if bezeichnung else '',
            f'positionen-{i}-steuersatz': '19.00',
        }

    def _kopf(self, kunde, betreff):
        return {
            'kunde': kunde.pk, 'betreff': betreff,
            'belegdatum': '', 'leistungsdatum': '', 'leistungsdatum_bis': '',
            'zahlungsziel_tage': '14',
            'empfaenger': '', 'empfaenger_ust_id': '',
            'kopftext': '', 'fusstext': '',
            'positionen-MIN_NUM_FORMS': '0', 'positionen-MAX_NUM_FORMS': '1000',
        }

    def test_leere_zeilen_mit_nummer_bleiben_leer(self, buero, kunde):
        """Eine Zeile nur mit Nummer gilt als leer, auch wenn die Nummer vom
        Initialwert abweicht, weil sonst jede ungenutzte Zeile eine
        Bezeichnung verlangte. So kommen im Browser angefügte Zeilen und
        Zeilen nach dem Löschen einer nicht gespeicherten an.
        """
        buero.post(reverse('admin:faktura_angebot_add'), {
            **self._kopf(kunde, 'Nur eine Zeile genutzt'),
            'positionen-TOTAL_FORMS': '4', 'positionen-INITIAL_FORMS': '0',
            **self._zeile(0, '10', 'Probenahme'),
            **self._zeile(1, '20'),
            # Verschoben: Initialwert war 30, eine vierte Zeile gab es beim
            # Laden nicht.
            **self._zeile(2, '40'),
            **self._zeile(3, '50'),
        }, follow=True)

        beleg = Beleg.objects.get(betreff='Nur eine Zeile genutzt')
        assert self._nummern(beleg) == ['10']

    def test_lv_nummern_zaehlen_in_ihrer_form_weiter(self, buero, kunde):
        """Ordnungszahlen aus dem Leistungsverzeichnis: Die letzte Ziffernfolge
        wird in derselben Breite inkrementiert."""
        beleg = self._angebot_mit_zeilen(buero, kunde, [
            ('01.01.0010', 'Baustelle einrichten'),
            ('01.01.0020', 'Bauzaun'), ('', 'Container'),
        ])

        assert self._nummern(beleg) == ['01.01.0010', '01.01.0020',
                                        '01.01.0030']
        assert self._vorbelegt(buero, reverse(
            'admin:faktura_angebot_change', args=[beleg.pk]))[-1]             == '01.01.0040'

    def test_sortiert_wird_wie_gezaehlt_nicht_wie_text(self, buero, kunde):
        """Sortierung numerisch; als Text stünde "100" vor "20" und "9" nach
        "10"."""
        beleg = self._angebot_mit_zeilen(buero, kunde, [
            ('100', 'Dritte'), ('9', 'Erste'), ('20', 'Zweite'),
        ])

        assert self._nummern(beleg) == ['9', '20', '100']

    def test_an_einer_gespeicherten_position_zaehlt_die_nummer(
            self, buero, kunde):
        """An einer gespeicherten Position gilt eine geänderte Nummer als
        Änderung; nur neue Zeilen ignorieren die Nummer."""
        beleg = self._angebot_mit_zeilen(buero, kunde, [('10', 'Erste')])
        position = beleg.positionen.get()

        buero.post(reverse('admin:faktura_angebot_change', args=[beleg.pk]), {
            **self._kopf(kunde, 'Nummernprobe'),
            'positionen-TOTAL_FORMS': '1', 'positionen-INITIAL_FORMS': '1',
            'positionen-0-id': str(position.pk),
            'positionen-0-beleg': str(beleg.pk),
            **self._zeile(0, '5', 'Erste'),
        }, follow=True)

        assert self._nummern(beleg) == ['5']


@pytest.mark.django_db
class TestDasBelegformular:
    """Link auf das Dokument im Belegformular.

    Der Link im Statusblock erscheint nur am festgeschriebenen Beleg, weil
    er dort die gespeicherte Datei mit Prüfsumme zeigt; am Entwurf zeigte er
    den gespeicherten Stand ohne die aktuellen Eingaben. Das PDF des
    Entwurfs liefert ``detail_pdf`` in der Kopfleiste. Verworfen: ein
    Button "PDF-Vorschau" unter dem Formular, der vorher speicherte.
    """

    def test_entwurf_hat_keinen_dokument_verweis_im_formular(
        self, buero, rechnungsentwurf
    ):
        """Am Entwurf kein Link auf das Dokument und kein Button
        "PDF-Vorschau" im Formular.

        Regression: Eine eingegebene, nicht gespeicherte Position fehlte im
        verlinkten PDF. ``detail_pdf`` in der Kopfleiste prüft dieser Test
        nicht, weil sie von Unfold außerhalb des Formulars gerendert wird.
        """
        antwort = buero.get(
            reverse('admin:faktura_rechnung_change', args=[rechnungsentwurf.pk])
        )

        inhalt = antwort.content.decode()
        assert f'/{rechnungsentwurf.pk}/pdf/' not in inhalt
        assert 'name="_vorschau"' not in inhalt
        assert 'PDF-Vorschau' not in inhalt

    def test_festgeschriebener_beleg_zeigt_den_dokument_verweis(
        self, buero, rechnungsentwurf
    ):
        """Am festgeschriebenen Beleg zeigt der Link die gespeicherte Datei."""
        services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)

        antwort = buero.get(
            reverse('admin:faktura_rechnung_change', args=[rechnungsentwurf.pk])
        )

        assert f'/{rechnungsentwurf.pk}/pdf/' in antwort.content.decode()

    def test_die_rechnung_zeigt_den_erechnungsblock_von_anfang_an(self,
                                                                  buero):
        """Der E-Rechnungsblock erscheint schon beim Anlegen einer Rechnung.

        Regression: Er erschien erst nach dem Speichern."""
        inhalt = buero.get(
            reverse('admin:faktura_rechnung_add')).content.decode()

        assert 'name="empfaenger_name"' in inhalt
        assert 'name="leitweg_id"' in inhalt

    def test_das_angebot_zeigt_ihn_nirgends(self, buero, kunde):
        """Das Angebot hat keinen E-Rechnungs-Tab, beim Anlegen wie beim Ändern.

        Ohne E-Rechnung entfällt der Tab, weil sein Inhalt aus den
        Stammdaten kommt und beim Umwandeln übernommen wird. Geprüft werden
        beide Formulare, damit der Tab nicht nur in einem erscheint.
        """
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT,
                                       betreff='Halle Nord')

        beim_anlegen = buero.get(
            reverse('admin:faktura_angebot_add')).content.decode()
        beim_aendern = buero.get(
            reverse('admin:faktura_angebot_change',
                    args=[beleg.pk])).content.decode()

        for inhalt in (beim_anlegen, beim_aendern):
            assert 'name="leitweg_id"' not in inhalt
            assert 'name="empfaenger_name"' not in inhalt

    def test_die_bestellnummer_bleibt_ueberall(self, buero, kunde):
        """Die Bestellnummer steht bei allen Belegarten oben bei Betreff und
        Zuordnung.

        Sie kommt vom Kunden und erscheint als „Ihre Bestellung" auf jedem
        Beleg-PDF; im E-Rechnungs-Tab entfiele sie mit dem Tab.
        """
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT,
                                       betreff='Halle Nord')

        for adresse in (reverse('admin:faktura_angebot_add'),
                        reverse('admin:faktura_angebot_change',
                                args=[beleg.pk]),
                        reverse('admin:faktura_rechnung_add')):
            assert 'name="bestellnummer"' in buero.get(
                adresse).content.decode(), adresse


@pytest.mark.django_db
class TestDieBelegmaskeIstAufgeraeumt:
    """Aufteilung der Belegmaske in Hauptbereich und Tabs.

    Oben stehen die beim Schreiben gebrauchten Felder; E-Rechnung und
    Status liegen in Tabs, damit die Positionen ohne Scrollen erreichbar
    sind.
    """

    def test_die_maske_hat_reiter(self, buero, rechnungsentwurf):
        inhalt = buero.get(reverse(
            'admin:faktura_rechnung_change',
            args=[rechnungsentwurf.pk])).content.decode()

        reiter = re.findall(r"activeFieldsetTab = '([^']+)'", inhalt)

        assert 'texte' in reiter
        assert 'e-rechnung' in reiter
        assert 'status' in reiter

    def test_der_kern_steht_weiterhin_oben(self, buero, rechnungsentwurf):
        """Zuordnung, Empfänger und Termine bleiben oben, weil jeder Beleg sie
        braucht."""
        inhalt = buero.get(reverse(
            'admin:faktura_rechnung_change',
            args=[rechnungsentwurf.pk])).content.decode()

        reiter = re.findall(r"activeFieldsetTab = '([^']+)'", inhalt)

        for kern in ('empfänger', 'empfaenger', 'termine'):
            assert kern not in reiter, kern
        # Die Felder sind vorhanden.
        assert 'id="id_belegdatum"' in inhalt
        assert 'id="id_empfaenger"' in inhalt

    def test_die_liste_traegt_keine_festen_farben(self, buero,
                                                  rechnungsentwurf):
        """Die Liste enthält keine Inline-Farben, nur CSS-Klassen.

        Wegen des Dark Mode. Regression: ``<b style="color:#1a7f37">`` war
        auf dunklem Hintergrund kaum lesbar.
        """
        inhalt = buero.get(
            reverse('admin:faktura_rechnung_changelist')).content.decode()

        assert 'style="color:#' not in inhalt

    def test_der_zustand_steht_nur_noch_im_schloss(self, buero,
                                                   rechnungsentwurf):
        """Der Zustand erscheint nur als Schloss-Symbol, am Entwurf leer.

        Geprüft an der Zelle, weil "Entwurf" auch im Namen eines Belegs
        ohne Nummer vorkommt ("Rechnung (Entwurf 3)") und eine Prüfung der
        Seite dadurch falsch positiv wäre.
        """
        inhalt = buero.get(
            reverse('admin:faktura_rechnung_changelist')).content.decode()

        assert 'field-status_farbig' not in inhalt
        assert '>lock<' not in inhalt

        services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)
        inhalt = buero.get(
            reverse('admin:faktura_rechnung_changelist')).content.decode()

        assert '>lock<' in inhalt

    def test_der_storno_bekommt_ein_eigenes_zeichen(self, buero,
                                                    rechnungsentwurf):
        """Der stornierte Beleg hat ein eigenes Symbol.

        "Storniert" betrifft die Gültigkeit: Der Beleg steht in der Liste,
        zählt aber nicht. Mit dem Schloss allein wäre er von einer
        gewöhnlichen Rechnung nicht zu unterscheiden.
        """
        original = services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)
        services.rechnung_korrigieren(beleg_id=original.pk)

        inhalt = buero.get(
            reverse('admin:faktura_rechnung_changelist')).content.decode()

        assert '>block<' in inhalt
        assert 'Storniert' in inhalt
