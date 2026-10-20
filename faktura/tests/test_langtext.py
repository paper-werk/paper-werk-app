"""Artikelnummer und Langtext im Leistungskatalog.

Die Bezeichnung erscheint in Listen; der Langtext beschreibt die Leistung
ausführlich (Verfahren, Norm, Umfang, Abgrenzung). Am Beleg steht er als
**Kopie**, damit spätere Änderungen im Katalog bestehende Angebote nicht
ändern.
"""

import io
from decimal import Decimal

import pytest
from django.db.utils import IntegrityError
from django.urls import reverse

from faktura import pdf, services
from faktura.models import (
    Beleg,
    BelegTyp,
    Katalogposition,
    Kontakt,
)

pytestmark = pytest.mark.django_db

BESCHREIBUNG = (
    'Entnahme von Bodenproben nach DIN ISO 10381-1 einschließlich '
    'Probenahmeprotokoll, Kennzeichnung und Transport ins akkreditierte '
    'Labor.\nEnthält Gerätevorhaltung und die Dokumentation der '
    'Entnahmestellen mit Lageplan.'
)


@pytest.fixture
def kunde(db):
    return Kontakt.objects.create(nummer='K-8000', name='Stadt Musterstadt')


@pytest.fixture
def katalogposition(db):
    return Katalogposition.objects.create(
        nummer='2.10', bezeichnung='Probenahme vor Ort',
        langtext=BESCHREIBUNG, einheit='Std',
        einzelpreis=Decimal('85.00'), steuersatz='19.00')


class TestDieArtikelnummer:

    def test_sie_steht_vor_der_bezeichnung(self, katalogposition):
        assert str(katalogposition) == '2.10 Probenahme vor Ort'

    def test_sie_ist_eindeutig(self, katalogposition):
        with pytest.raises(IntegrityError):
            Katalogposition.objects.create(
                nummer='2.10', bezeichnung='Etwas anderes',
                einzelpreis=Decimal('10.00'))

    def test_aber_freiwillig_und_beliebig_oft_leer(self, db):
        """Die Artikelnummer ist optional und darf mehrfach fehlen.

        Mit null=True, weil in PostgreSQL zwei NULL nie gleich sind; mit
        Leerstrings ließe sich keine zweite Position ohne Nummer anlegen."""
        erste = Katalogposition.objects.create(
            bezeichnung='Ohne Nummer', einzelpreis=Decimal('10.00'))
        zweite = Katalogposition.objects.create(
            bezeichnung='Auch ohne', einzelpreis=Decimal('20.00'))

        assert erste.nummer is None and zweite.nummer is None
        assert str(erste) == 'Ohne Nummer'


class TestDerLangtextAufDemBeleg:

    def test_er_kommt_ueber_die_katalogauswahl_mit(self, katalogposition,
                                                   kunde, admin_client):
        """Der Langtext wird wie Bezeichnung, Einheit und Preis übernommen;
        die Feldliste steht in Formular, JSON-Endpunkt und Skript."""
        antwort = admin_client.post(reverse('admin:faktura_angebot_add'), {
            'kunde': kunde.pk, 'betreff': 'Erkundung',
            'belegdatum': '', 'leistungsdatum': '', 'leistungsdatum_bis': '',
            'zahlungsziel_tage': '14', 'kopftext': '', 'fusstext': '',
            'positionen-TOTAL_FORMS': '1', 'positionen-INITIAL_FORMS': '0',
            'positionen-MIN_NUM_FORMS': '0',
            'positionen-MAX_NUM_FORMS': '1000',
            'positionen-0-katalog': str(katalogposition.pk),
            'positionen-0-position': '10',
            'positionen-0-bezeichnung': '',
            'positionen-0-langtext': '',
            'positionen-0-menge': '4',
            'positionen-0-einheit': 'Stk',
            'positionen-0-einzelpreis': '',
            'positionen-0-steuersatz': '19.00',
        }, follow=True)

        assert antwort.status_code == 200
        position = Beleg.objects.filter(
            typ=BelegTyp.ANGEBOT).latest('pk').positionen.get()
        assert position.langtext == BESCHREIBUNG
        assert position.bezeichnung == 'Probenahme vor Ort'

    def test_ein_eigener_text_gewinnt_gegen_den_katalog(self, katalogposition,
                                                        kunde, admin_client):
        """Ein eingegebener Langtext hat Vorrang vor dem Katalog."""
        admin_client.post(reverse('admin:faktura_angebot_add'), {
            'kunde': kunde.pk, 'betreff': 'Erkundung',
            'belegdatum': '', 'leistungsdatum': '', 'leistungsdatum_bis': '',
            'zahlungsziel_tage': '14', 'kopftext': '', 'fusstext': '',
            'positionen-TOTAL_FORMS': '1', 'positionen-INITIAL_FORMS': '0',
            'positionen-MIN_NUM_FORMS': '0',
            'positionen-MAX_NUM_FORMS': '1000',
            'positionen-0-katalog': str(katalogposition.pk),
            'positionen-0-position': '10',
            'positionen-0-bezeichnung': '',
            'positionen-0-langtext': 'Nur zwei Mischproben, ohne Eluat.',
            'positionen-0-menge': '2',
            'positionen-0-einheit': 'Stk',
            'positionen-0-einzelpreis': '',
            'positionen-0-steuersatz': '19.00',
        }, follow=True)

        position = Beleg.objects.filter(
            typ=BelegTyp.ANGEBOT).latest('pk').positionen.get()
        assert position.langtext == 'Nur zwei Mischproben, ohne Eluat.'

    def test_der_dienst_liefert_ihn_mit(self, katalogposition, admin_client):
        """Der JSON-Endpunkt liefert den Langtext."""
        antwort = admin_client.get(
            reverse('admin:faktura_katalogposition_daten'),
            {'katalog': katalogposition.pk})

        assert antwort.json()['langtext'] == BESCHREIBUNG

    def test_beim_umwandeln_geht_er_mit(self, katalogposition, kunde):
        """Beim Umwandeln wird der Langtext übernommen."""
        angebot = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT,
                                         betreff='Erkundung')
        services.position_hinzufuegen(
            beleg=angebot, bezeichnung='Probenahme vor Ort',
            langtext=BESCHREIBUNG, menge=Decimal('4'), einheit='Std',
            einzelpreis=Decimal('85.00'), steuersatz='19.00')
        services.beleg_festschreiben(beleg_id=angebot.pk)

        auftrag = services.beleg_umwandeln(
            beleg_id=angebot.pk, neuer_typ=BelegTyp.AUFTRAG)

        assert auftrag.positionen.get().langtext == BESCHREIBUNG

    def test_und_er_steht_im_pdf(self, katalogposition, kunde, firma,
                                 mit_pdf):
        """Der Langtext steht im PDF."""
        from pypdf import PdfReader

        angebot = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT,
                                         betreff='Schadstofferkundung')
        services.position_hinzufuegen(
            beleg=angebot, bezeichnung='Probenahme vor Ort',
            langtext=BESCHREIBUNG, menge=Decimal('4'), einheit='Std',
            einzelpreis=Decimal('85.00'), steuersatz='19.00')

        daten = pdf.beleg_als_pdf(angebot)
        text = '\n'.join(
            seite.extract_text() for seite in PdfReader(io.BytesIO(daten)).pages)

        assert 'DIN ISO 10381-1' in text
        assert 'Gerätevorhaltung' in text


class TestDerLangtextInDerMaske:
    """Langtext in eigener Tabellenzeile unter der Positionszeile.

    Verworfen: eine neunte Spalte, die die übrigen zu schmal machte. Siehe
    ``zweite_zeile_felder`` am BelegpositionInline.
    """

    @pytest.fixture
    def angebot(self, kunde):
        beleg = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.ANGEBOT, betreff='Erkundung')
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Probenahme vor Ort',
            langtext=BESCHREIBUNG, menge=Decimal('4'), einheit='Std',
            einzelpreis=Decimal('85.00'), steuersatz='19.00')
        return beleg

    def _maske(self, admin_client, beleg, ansicht='angebot'):
        antwort = admin_client.get(
            reverse(f'admin:faktura_{ansicht}_change', args=[beleg.pk]))
        assert antwort.status_code == 200
        return antwort.content.decode()

    def test_er_steht_unter_der_positionszeile_und_nicht_darin(
            self, angebot, admin_client):
        seite = self._maske(admin_client, angebot)

        assert 'form-row-zweite-zeile' in seite
        davor, ab_der_zweiten_zeile = seite.split('form-row-zweite-zeile', 1)
        assert 'positionen-0-langtext' not in davor
        assert 'positionen-0-langtext' in ab_der_zweiten_zeile.split('</tr>', 1)[0]

    def test_und_hat_keine_spalte_mehr_im_tabellenkopf(self, angebot,
                                                       admin_client):
        """Der Tabellenkopf hat keine Spalte für den Langtext, weil eine
        Überschrift ohne Zelle die übrigen verschöbe."""
        seite = self._maske(admin_client, angebot)

        assert 'column-bezeichnung' in seite
        assert 'column-langtext' not in seite

    def test_im_festgeschriebenen_beleg_bleibt_er_lesbar(self, angebot,
                                                         admin_client):
        """Am festgeschriebenen Beleg ist der Langtext readonly sichtbar."""
        services.beleg_festschreiben(beleg_id=angebot.pk)

        seite = self._maske(admin_client, angebot)

        assert 'DIN ISO 10381-1' in seite

    def test_der_lieferschein_bekommt_keine_zweite_zeile(self, kunde,
                                                         admin_client):
        """Der Lieferschein hat keine zweite Zeile, weil er keinen Langtext
        zeigt."""
        lieferschein = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.LIEFERSCHEIN, betreff='Anlieferung')

        seite = self._maske(admin_client, lieferschein, 'lieferschein')

        assert 'form-row-zweite-zeile' not in seite


def _layout(beleg):
    """Boxen der ersten Seite nach WeasyPrint-Layout, nach CSS-Klasse.
    Geprüft wird das Layout, weil ein ``colspan`` im HTML nicht zeigt, wo
    der Text im PDF endet."""
    import weasyprint
    from django.conf import settings
    from weasyprint.formatting_structure.boxes import TableCellBox

    dokument = weasyprint.HTML(
        string=pdf.beleg_als_html(beleg), base_url=str(settings.BASE_DIR),
        url_fetcher=pdf.BelegUrlFetcher()).render()
    kaesten = {}
    stapel = [dokument.pages[0]._page_box]
    while stapel:
        kasten = stapel.pop()
        if isinstance(kasten, TableCellBox):
            for klasse in (kasten.element.get('class') or '').split():
                kaesten.setdefault(klasse, []).append(kasten)
        stapel.extend(getattr(kasten, 'children', []))
    return kaesten


class TestDerLangtextUeberDieGanzeBreite:
    """Der Langtext steht im PDF in eigener Zeile von der Bezeichnung bis
    zum Gesamtpreis (Template v9)."""

    def _angebot(self, kunde, position='10'):
        angebot = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        services.position_hinzufuegen(
            beleg=angebot, position=position, bezeichnung='Probenahme vor Ort',
            langtext=BESCHREIBUNG, menge=Decimal('4'), einheit='Std',
            einzelpreis=Decimal('85.00'), steuersatz='19.00')
        return angebot

    @staticmethod
    def _rechts(kasten):
        return kasten.position_x + kasten.margin_width()

    def test_er_beginnt_unter_der_bezeichnung_und_endet_mit_dem_gesamtpreis(
            self, kunde, firma):
        kaesten = _layout(self._angebot(kunde))

        (langtext,) = kaesten['langtext']
        bezeichnung = kaesten['bezeichnung'][-1]
        summe = kaesten['summe'][-1]
        assert langtext.position_x == pytest.approx(bezeichnung.position_x)
        assert self._rechts(langtext) == pytest.approx(self._rechts(summe))

    def test_die_spalte_pos_waechst_mit_der_nummer(self, kunde, firma):
        """Bis vier Zeichen 8 mm; "01.01.0010" passt ohne Umbruch."""
        kurz = _layout(self._angebot(kunde))['pos'][0]
        lang = _layout(self._angebot(kunde, '01.01.0010'))['pos'][0]

        mm = 96 / 25.4
        assert kurz.margin_width() == pytest.approx(8.0 * mm, abs=0.5)
        assert lang.margin_width() > 17.5 * mm

    def test_der_lieferschein_ohne_preise_spannt_drei_spalten(self, kunde,
                                                             firma):
        angebot = self._angebot(kunde)
        html = pdf.beleg_als_html(angebot)
        assert 'colspan="6"' in html

        lieferschein = services.beleg_anlegen(kunde=kunde,
                                              typ=BelegTyp.LIEFERSCHEIN)
        services.position_hinzufuegen(
            beleg=lieferschein, bezeichnung='Probenahme vor Ort',
            langtext=BESCHREIBUNG, menge=Decimal('4'), einheit='Std',
            einzelpreis=Decimal('0'), steuersatz='19.00')
        assert 'colspan="3"' in pdf.beleg_als_html(lieferschein)
