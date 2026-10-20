"""Formular der Mahnung und Wechsel der Mahnstufe.

Die Mahnung hat eigene fieldsets ohne Katalogsuche, Menge, Einheit,
Steuersatz und Langtext; Kunde und Projekt sind readonly, die Stufe ist ein
Select. Ein Wechsel der Stufe aktualisiert Text und Mahngebühr.
"""

from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from faktura import services, standardtexte
from faktura.models import BelegTyp, Kontakt


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-1000', name='Muster GmbH', strasse='Hauptstraße 1',
        plz='10115', ort='Berlin',
    )


@pytest.fixture
def mahnung(kunde, ueberfaellig):
    standardtexte.anlegen()
    rechnung = services.beleg_anlegen(
        kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Leistungen',
        leistungsdatum=timezone.localdate(),
    )
    services.position_hinzufuegen(
        beleg=rechnung, bezeichnung='Beratung', menge=Decimal('1'),
        einzelpreis=Decimal('100.00'), steuersatz='19.00',
    )
    original = ueberfaellig(rechnung)
    return services.mahnung_erstellen(beleg_id=original.pk, stufe=1)


def _adresse(mahnung):
    return reverse('admin:faktura_mahnung_change', args=[mahnung.pk])


def _formular(mahnung, **aenderungen):
    """POST-Daten des Formulars mit den Werten der Mahnung."""
    zeilen = list(mahnung.positionen.order_by('position'))
    daten = {
        'mahnstufe': str(mahnung.mahnstufe),
        'betreff': mahnung.betreff,
        'empfaenger': mahnung.empfaenger,
        'empfaenger_email': mahnung.empfaenger_email,
        'belegdatum': mahnung.belegdatum.strftime('%d.%m.%Y')
        if mahnung.belegdatum else '',
        'zahlungsziel_tage': str(mahnung.zahlungsziel_tage),
        'kopftext': mahnung.kopftext,
        'fusstext': mahnung.fusstext,
        'positionen-TOTAL_FORMS': str(len(zeilen)),
        'positionen-INITIAL_FORMS': str(len(zeilen)),
        'positionen-MIN_NUM_FORMS': '0',
        'positionen-MAX_NUM_FORMS': '1000',
    }
    for i, zeile in enumerate(zeilen):
        daten.update({
            f'positionen-{i}-id': str(zeile.pk),
            f'positionen-{i}-beleg': str(mahnung.pk),
            f'positionen-{i}-position': zeile.position,
            f'positionen-{i}-bezeichnung': zeile.bezeichnung,
            f'positionen-{i}-einzelpreis': str(zeile.einzelpreis),
        })
    daten.update(aenderungen)
    return daten


def _gebuehr(mahnung):
    zeile = mahnung.positionen.filter(
        bezeichnung=services.korrektur.MAHNGEBUEHR_ZEILE).first()
    return zeile.einzelpreis if zeile else None


@pytest.mark.django_db
class TestMaske:
    def test_aufstellung_nur_mit_bezeichnung_und_betrag(self, buero, mahnung):
        inhalt = buero.get(_adresse(mahnung)).content.decode()

        assert 'name="positionen-0-bezeichnung"' in inhalt
        assert 'name="positionen-0-einzelpreis"' in inhalt
        for feld in ('menge', 'einheit', 'steuersatz', 'langtext', 'katalog'):
            assert f'name="positionen-0-{feld}"' not in inhalt, feld

    def test_spalten_wie_an_der_rechnung(self, buero, mahnung):
        """Die CSS-Klasse der Positionen ist gesetzt, weil die Spaltenbreiten in
        faktura_admin.css davon abhängen. Regression: Pos., Bezeichnung und
        Betrag waren gleich breit."""
        inhalt = buero.get(_adresse(mahnung)).content.decode()

        assert 'positionszeile' in inhalt
        # Keine leere Zeile unter der Aufstellung.
        n = mahnung.positionen.count()
        assert f'name="positionen-{n}-bezeichnung"' not in inhalt

    def test_kunde_und_ust_id_nicht_aenderbar(self, buero, mahnung):
        """Kunde und USt-IdNr. sind readonly, weil sie von der Rechnung
        kommen."""
        inhalt = buero.get(_adresse(mahnung)).content.decode()

        assert 'name="kunde"' not in inhalt
        assert 'name="projekt"' not in inhalt
        assert 'name="empfaenger_ust_id"' not in inhalt
        assert 'Gemahnte Rechnung' in inhalt

    def test_stufe_als_auswahl_ohne_leeren_eintrag(self, buero, mahnung):
        inhalt = buero.get(_adresse(mahnung)).content.decode()

        anfang = inhalt.index('<select name="mahnstufe"')
        auswahl = inhalt[anfang:inhalt.index('</select>', anfang)]
        assert '>Letzte Mahnung</option>' in auswahl
        assert '---------' not in auswahl

    def test_vorlagenmenue_bietet_die_mahnstufen(self, buero, mahnung):
        """Das Vorlagenmenü zeigt die Bausteine der Mahnung, nicht die der
        Rechnung."""
        inhalt = buero.get(_adresse(mahnung)).content.decode()

        assert 'Letzte Mahnung Einleitung' in inhalt
        assert 'Rechnung Einleitung' not in inhalt

    def test_neue_zeile_steht_mit_null_prozent(self, buero, mahnung):
        """Eine neue Zeile hat 0 % und keine Einheit "Stk", etwa für manuell
        ergänzte Verzugszinsen."""
        daten = _formular(mahnung)
        n = mahnung.positionen.count()
        daten.update({
            'positionen-TOTAL_FORMS': str(n + 1),
            f'positionen-{n}-beleg': str(mahnung.pk),
            f'positionen-{n}-position': '30',
            f'positionen-{n}-bezeichnung': 'Verzugszinsen',
            f'positionen-{n}-einzelpreis': '3.50',
        })

        antwort = buero.post(_adresse(mahnung), daten)

        assert antwort.status_code == 302
        zeile = mahnung.positionen.get(bezeichnung='Verzugszinsen')
        assert zeile.steuersatz == '0.00'
        assert zeile.menge == Decimal('1')
        assert zeile.einheit == ''


@pytest.mark.django_db
class TestStufenwechsel:
    def test_text_und_gebuehr_folgen_der_stufe(self, buero, mahnung):
        antwort = buero.post(_adresse(mahnung),
                             _formular(mahnung, mahnstufe='3'))

        assert antwort.status_code == 302
        mahnung.refresh_from_db()
        assert mahnung.mahnstufe == 3
        assert 'letztmalig' in mahnung.kopftext
        assert _gebuehr(mahnung) == services.mahngebuehr(3)

    def test_zurueck_auf_erinnerung_nimmt_die_gebuehr_weg(self, mahnung):
        mahnung.mahnstufe = 2
        mahnung.save()
        services.mahnstufe_angleichen(mahnung=mahnung, alte_stufe=1)
        assert _gebuehr(mahnung) == services.mahngebuehr(2)

        mahnung.mahnstufe = 1
        mahnung.save()
        services.mahnstufe_angleichen(mahnung=mahnung, alte_stufe=2)

        assert _gebuehr(mahnung) is None

    def test_eigener_text_bleibt(self, buero, mahnung):
        mahnung.kopftext = 'Von Hand geschrieben.'
        mahnung.save()

        buero.post(_adresse(mahnung), _formular(mahnung, mahnstufe='2'))

        mahnung.refresh_from_db()
        assert mahnung.kopftext == 'Von Hand geschrieben.'

    def test_text_in_derselben_eingabe_geaendert_bleibt(self, buero, mahnung):
        buero.post(_adresse(mahnung), _formular(
            mahnung, mahnstufe='2', kopftext='Neu getippt.'))

        mahnung.refresh_from_db()
        assert mahnung.kopftext == 'Neu getippt.'

    def test_eigene_gebuehr_bleibt(self, mahnung):
        mahnung.mahnstufe = 2
        mahnung.save()
        services.mahnstufe_angleichen(mahnung=mahnung, alte_stufe=1)
        mahnung.positionen.filter(
            bezeichnung=services.korrektur.MAHNGEBUEHR_ZEILE).update(
            einzelpreis=Decimal('7.50'))

        mahnung.mahnstufe = 3
        mahnung.save()
        services.mahnstufe_angleichen(mahnung=mahnung, alte_stufe=2)

        assert _gebuehr(mahnung) == Decimal('7.50')


@pytest.mark.django_db
class TestPdf:
    """Der Inhalt der Maske erscheint im PDF."""

    @staticmethod
    def _html(mahnung):
        from faktura import pdf
        return pdf.beleg_als_html(mahnung)

    def test_auch_eine_zeile_mit_positionsnummer(self, mahnung):
        """Auch die Positionsnummer erscheint im PDF."""
        zeile = mahnung.positionen.get()

        inhalt = self._html(mahnung)

        assert '>Pos.</th>' in inhalt
        assert f'<td class="pos">{zeile.position}</td>' in inhalt

    def test_mit_gebuehr_mit_positionsnummern(self, mahnung):
        mahnung.mahnstufe = 2
        mahnung.save()
        services.mahnstufe_angleichen(mahnung=mahnung, alte_stufe=1)

        inhalt = self._html(mahnung)

        assert '>Pos.</th>' in inhalt
        for zeile in mahnung.positionen.all():
            assert f'<td class="pos">{zeile.position}</td>' in inhalt

    def test_verwendungszweck_nennt_rechnung_und_mahnung(self, mahnung):
        """Der Verwendungszweck nennt Rechnung und Mahnung, damit beim
        Zahlungseingang erkennbar ist, ob die Gebühr mitbezahlt wurde."""
        festgeschrieben = services.beleg_festschreiben(beleg_id=mahnung.pk)

        inhalt = self._html(festgeschrieben)

        rechnung = festgeschrieben.vorgaenger.nummer
        assert (f'<th>Verwendungszweck</th><td>{rechnung} '
                f'{festgeschrieben.nummer}</td>') in inhalt


def _zahlen(mahnung, betrag):
    services.zahlung_verbuchen(beleg_id=mahnung.vorgaenger_id,
                               datum=timezone.localdate(), betrag=betrag)


@pytest.mark.django_db
class TestNichtsMahnenWasBezahltIst:
    """Keine Mahnung über Bezahltes, weil zwischen Entwurf und Versand
    Zahlungen eingehen können."""

    def test_bezahlte_rechnung_wird_nicht_gemahnt(self, mahnung):
        _zahlen(mahnung, services.offener_betrag(mahnung.vorgaenger))

        with pytest.raises(services.FalscherStatus, match='bezahlt'):
            services.beleg_festschreiben(beleg_id=mahnung.pk)

    def test_teilzahlung_nach_dem_entwurf_haelt_auf(self, mahnung):
        _zahlen(mahnung, Decimal('50.00'))

        with pytest.raises(services.UngueltigerBetrag, match='offen'):
            services.beleg_festschreiben(beleg_id=mahnung.pk)

    def test_teilzahlung_vor_der_mahnung_steht_in_der_aufstellung(
            self, mahnung):
        """Eine Teilzahlung vor der Mahnung erscheint in der Aufstellung."""
        _zahlen(mahnung, Decimal('50.00'))

        neu = services.mahnung_erstellen(beleg_id=mahnung.vorgaenger_id,
                                         stufe=2)

        zeile = services.korrektur.forderungszeile(neu)
        assert zeile.einzelpreis == Decimal('69.00')
        assert 'Rechnungsbetrag 119,00 EUR' in zeile.bezeichnung
        assert 'bereits bezahlt 50,00 EUR' in zeile.bezeichnung
        services.beleg_festschreiben(beleg_id=neu.pk)


@pytest.mark.django_db
class TestBrief:
    def test_endet_mit_gruss(self, mahnung):
        assert mahnung.fusstext.startswith('Mit freundlichen Grüßen')

    def test_entwurf_nennt_die_frist(self, mahnung):
        """Der Entwurf nennt die Frist, auf die der Text als "das unten
        genannte Datum" verweist."""
        from datetime import timedelta

        from faktura import pdf
        frist = timezone.localdate() + timedelta(days=7)

        inhalt = pdf.beleg_als_html(mahnung)

        assert f'{frist:%d.%m.%Y}' in inhalt
        assert mahnung.zahlbar_bis == frist

    def test_maske_ohne_steuerzeilen(self, buero, mahnung):
        inhalt = buero.get(_adresse(mahnung)).content.decode()

        assert 'Netto 0' not in inhalt
        assert 'Offener Gesamtbetrag' in inhalt
        assert f'{mahnung.zahlbar_bis:%d.%m.%Y}' in inhalt


@pytest.mark.django_db
class TestGebuehrAusDenFirmendaten:
    """Die Mahngebühr kommt aus den Firmendaten."""

    def test_vorgabe(self):
        assert services.mahngebuehr(1) == Decimal('0.00')
        assert services.mahngebuehr(2) == Decimal('2.50')
        assert services.mahngebuehr(3) == Decimal('2.50')

    def test_der_betrieb_stellt_sie_ein(self, firma, mahnung):
        firma.mahngebuehr_mahnung = Decimal('1.80')
        firma.save()

        mahnung.mahnstufe = 2
        mahnung.save()
        services.mahnstufe_angleichen(mahnung=mahnung, alte_stufe=1)

        assert _gebuehr(mahnung) == Decimal('1.80')

    def test_ohne_gebuehr_keine_zeile(self, firma, mahnung):
        firma.mahngebuehr_letzte = Decimal('0.00')
        firma.save()

        neu = services.mahnung_erstellen(beleg_id=mahnung.vorgaenger_id,
                                         stufe=3)

        assert _gebuehr(neu) is None
