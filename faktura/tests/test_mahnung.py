"""Mahnung und Fälligkeit."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from faktura import services
from faktura.models import (
    Textbaustein,
)


@pytest.mark.django_db
class TestMahnung:
    def test_enthaelt_forderung_und_gebuehr(self, rechnung, ueberfaellig):
        original = ueberfaellig(rechnung)
        offen = services.belegsummen(original).brutto

        mahnung = services.mahnung_erstellen(beleg_id=original.pk, stufe=2)

        assert mahnung.positionen.count() == 2
        assert services.belegsummen(mahnung).brutto == (
            offen + services.mahngebuehr(2))

    def test_erste_stufe_ohne_gebuehr(self, rechnung, ueberfaellig):
        original = ueberfaellig(rechnung)

        mahnung = services.mahnung_erstellen(beleg_id=original.pk, stufe=1)

        assert mahnung.positionen.count() == 1

    def test_weist_keine_umsatzsteuer_aus(self, rechnung, ueberfaellig):
        """Die Mahnung weist keine Umsatzsteuer aus, weil die Steuer auf der
        Rechnung steht und die Mahngebühr als Schadenersatz nicht steuerbar
        ist."""
        original = ueberfaellig(rechnung)

        mahnung = services.mahnung_erstellen(beleg_id=original.pk, stufe=3)

        assert services.belegsummen(mahnung).steuer == Decimal('0.00')

    def test_nur_festgeschriebene_rechnungen(self, rechnung):
        with pytest.raises(services.FalscherStatus):
            services.mahnung_erstellen(beleg_id=rechnung.pk, stufe=1)

    def test_vor_der_faelligkeit_wird_nicht_gemahnt(self, rechnung):
        """Vor der Fälligkeit keine Mahnung, weil Verzug erst danach eintritt
        (§ 286 BGB).

        Regression: Das PDF zeigte "fällig seit 24.09.2026" in einem
        Schreiben vom 25.08.2026.
        """
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)
        assert original.faellig_am > timezone.localdate()

        with pytest.raises(services.FalscherStatus, match='fällig'):
            services.mahnung_erstellen(beleg_id=original.pk, stufe=1)

    def test_die_aufstellung_nennt_rechnung_datum_und_faelligkeit(self, rechnung, ueberfaellig):
        """Die Aufstellung nennt Rechnung, Datum und Fälligkeit.

        Regression: Die Position hieß "Offener Betrag aus Rechnung RE-…",
        ohne Datum und Fälligkeit.
        """
        original = ueberfaellig(rechnung)

        mahnung = services.mahnung_erstellen(beleg_id=original.pk, stufe=1)

        zeile = mahnung.positionen.first().bezeichnung
        assert original.nummer in zeile
        assert original.belegdatum.strftime('%d.%m.%Y') in zeile
        assert 'fällig seit' in zeile

    def test_der_betreff_wiederholt_die_ueberschrift_nicht(self, rechnung, ueberfaellig):
        """Der Betreff nennt den Bezug ohne die Belegart der Überschrift.

        Regression: Überschrift "Zahlungserinnerung MA-2026-0001", darunter
        Betreff "Zahlungserinnerung zu Rechnung RE-2026-0007".
        """
        original = ueberfaellig(rechnung)

        mahnung = services.mahnung_erstellen(beleg_id=original.pk, stufe=1)

        assert mahnung.mahntext not in mahnung.betreff
        assert original.nummer in mahnung.betreff

    def test_ohne_eingefrorenen_betrag_im_text(self, rechnung, ueberfaellig):
        """Der Kopftext enthält keinen Betrag.

        Regression: "über 119.00 EUR" mit Punkt; nach einer Teilzahlung
        widerspräche der Text der Aufstellung.
        """
        from faktura import standardtexte
        standardtexte.anlegen()
        original = ueberfaellig(rechnung)

        mahnung = services.mahnung_erstellen(beleg_id=original.pk, stufe=1)

        assert '119' not in mahnung.kopftext
        assert 'EUR' not in mahnung.kopftext

    @pytest.mark.parametrize('stufe', [1, 2, 3])
    def test_kopftext_aus_dem_baustein_der_stufe(self, rechnung, ueberfaellig,
                                                 stufe):
        """Anrede und Einleitung kommen aus dem Textbaustein der Stufe und sind
        am Beleg änderbar."""
        from faktura import standardtexte
        standardtexte.anlegen()
        original = ueberfaellig(rechnung)

        mahnung = services.mahnung_erstellen(beleg_id=original.pk, stufe=stufe)

        einleitung = Textbaustein.objects.get(
            name=standardtexte.MAHNEINLEITUNG[stufe]).text
        anrede = Textbaustein.objects.get(name='Anrede').text
        assert mahnung.kopftext == f'{anrede}\n\n{einleitung}'

    def test_geaenderter_baustein_gilt(self, rechnung, ueberfaellig):
        """Ein geänderter Baustein gilt, nicht der Wortlaut aus dem Code."""
        from faktura import standardtexte
        standardtexte.anlegen()
        Textbaustein.objects.filter(
            name=standardtexte.MAHNEINLEITUNG[1]).update(text='bitte zahlen.')
        original = ueberfaellig(rechnung)

        mahnung = services.mahnung_erstellen(beleg_id=original.pk, stufe=1)

        assert mahnung.kopftext.endswith('\n\nbitte zahlen.')

    def test_ohne_bausteine_bleibt_der_kopftext_leer(self, rechnung,
                                                     ueberfaellig):
        # Migration 0047 legt die Bausteine der Mahnung an.
        Textbaustein.objects.all().delete()
        original = ueberfaellig(rechnung)

        mahnung = services.mahnung_erstellen(beleg_id=original.pk, stufe=1)

        assert mahnung.kopftext == ''

    def test_das_pdf_zeigt_nur_den_kopftext(self, rechnung, ueberfaellig):
        """Das PDF zeigt nur den Kopftext des Belegs, ohne festen Text im
        Template."""
        from faktura import pdf
        original = ueberfaellig(rechnung)
        mahnung = services.mahnung_erstellen(beleg_id=original.pk, stufe=1)
        mahnung.kopftext = 'Eigener Text am Beleg.'
        mahnung.save()

        inhalt = pdf.beleg_als_html(mahnung)

        assert 'Eigener Text am Beleg.' in inhalt
        assert 'gekreuzt' not in inhalt
        assert 'Durchsicht' not in inhalt

    def test_die_mahnung_bekommt_eine_frist(self, rechnung, ueberfaellig):
        """Die Mahnung erhält eine Frist (``faellig_am``).

        Regression: Die Fälligkeit hing an ``steuerbelege()``, zu denen die
        Mahnung nicht gehört; "Zahlbar bis" blieb leer.
        """
        original = ueberfaellig(rechnung)
        mahnung = services.mahnung_erstellen(beleg_id=original.pk, stufe=1)

        festgeschrieben = services.beleg_festschreiben(beleg_id=mahnung.pk)

        assert festgeschrieben.faellig_am is not None
        assert festgeschrieben.faellig_am == (
            festgeschrieben.belegdatum + timedelta(days=7))

    def test_eigener_nummernkreis(self, rechnung, ueberfaellig):
        original = ueberfaellig(rechnung)
        mahnung = services.mahnung_erstellen(beleg_id=original.pk, stufe=1)

        festgeschrieben = services.beleg_festschreiben(beleg_id=mahnung.pk)

        assert festgeschrieben.nummer.startswith('MA-')


@pytest.mark.django_db
class TestFaelligkeit:
    def test_wird_bei_der_festschreibung_berechnet(self, rechnung):
        """Die Frist wird beim Festschreiben berechnet, weil der Entwurf kein
        Belegdatum hat."""
        assert rechnung.faellig_am is None

        festgeschrieben = services.beleg_festschreiben(beleg_id=rechnung.pk)

        erwartet = festgeschrieben.belegdatum + timedelta(
            days=festgeschrieben.zahlungsziel_tage
        )
        assert festgeschrieben.faellig_am == erwartet
