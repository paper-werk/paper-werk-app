"""Zeilenarten: Titel, Text, Zuschlag (R-180, R-181).

Referenzfall ist ein Leistungsverzeichnis: Titel "01" mit Positionen
"01.0010", "01.0020", ein Text dazwischen, Nebenkosten 3 % auf alles und
ein Erschwerniszuschlag auf eine einzelne Position.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from faktura import facturx, pdf, services
from faktura.models import (
    Abnahme,
    Abnahmeart,
    Beleg,
    Belegposition,
    BelegTyp,
    Kontakt,
    Projekt,
    Rechnungsart,
    Zeilenart,
)
from faktura.tests.test_pdf import xml_wert

VOLL = '19.00'


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-5100', name='Stadtwerke Muster', strasse='Werkstraße 1',
        plz='84028', ort='Landshut', ust_id='DE444555666')


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(
        nummer='2026-501', bezeichnung='Kanal Nord', kunde=kunde)


def _zeile(beleg, nummer, text, menge='1', preis='0.00', *,
           art=Zeilenart.LEISTUNG, prozent=None, auf='', optional=False,
           satz=VOLL):
    return services.position_hinzufuegen(
        beleg=beleg, position=nummer, bezeichnung=text,
        menge=Decimal(menge), einheit='Stk', einzelpreis=Decimal(preis),
        steuersatz=satz, zeilenart=art,
        zuschlag_prozent=Decimal(prozent) if prozent else None,
        zuschlag_auf=auf, optional=optional)


@pytest.fixture
def lv(kunde):
    """Titel 01 (1.000 + 2.500), Titel 02 (400), ein Text, ein optionales
    Teil, Erschwernis 10 % auf 01.0020, Nebenkosten 3 % auf alles."""
    beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT,
                                   betreff='Kanal Nord')
    _zeile(beleg, '01', 'Erdarbeiten', art=Zeilenart.TITEL)
    _zeile(beleg, '01.0010', 'Aushub', '10', '100.00')
    _zeile(beleg, '01.0020', 'Verbau', '5', '500.00')
    _zeile(beleg, '01.0030', 'Wasserhaltung', '1', '800.00', optional=True)
    _zeile(beleg, '01.0040', 'Erschwernis Verbau', art=Zeilenart.ZUSCHLAG,
           prozent='10', auf='01.0020')
    _zeile(beleg, '02', 'Analytik', art=Zeilenart.TITEL)
    _zeile(beleg, '02.0005', 'Vorbemerkung: Proben nach DIN 19698',
           art=Zeilenart.TEXT)
    _zeile(beleg, '02.0010', 'Probe', '4', '100.00')
    _zeile(beleg, '03', 'Nebenkosten', '1', '0.00', art=Zeilenart.ZUSCHLAG,
           prozent='3')
    return beleg


def _p(beleg, nummer) -> Belegposition:
    return beleg.positionen.get(position=nummer)


@pytest.mark.django_db
class TestNummernanfang:

    @pytest.mark.parametrize('nummer, anfang, erwartet', [
        ('01.0010', '01', True),
        ('01', '01', True),
        ('010', '01', False),
        ('01.0010', '01.0010', True),
        ('01.00100', '01.0010', False),
        ('irgendwas', '', True),
    ])
    def test_gehoert_zu(self, nummer, anfang, erwartet):
        assert services.gehoert_zu(nummer, anfang) is erwartet


@pytest.mark.django_db
class TestTitelUndText:

    def test_titel_und_text_haben_weder_menge_noch_preis(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        titel = _zeile(beleg, '01', 'Titel', '3', '99.00',
                       art=Zeilenart.TITEL)
        text = _zeile(beleg, '02', 'Text', '2', '50.00', art=Zeilenart.TEXT)

        for zeile in (titel, text):
            zeile.refresh_from_db()
            assert (zeile.menge, zeile.einzelpreis) == (
                Decimal('0'), Decimal('0.00'))

    def test_sie_zaehlen_in_keine_summe(self, lv):
        """Titel und Text zählen in keine Summe; Python und SQL rechnen gleich,
        ohne Bezug auf die Zeilenart."""
        summen = services.belegsummen(lv)
        sql = services.summe_ueber(Beleg.objects.filter(pk=lv.pk))

        # 1.000 + 2.500 + 250 (Erschwernis) + 400 + 3 % auf 3.900 = 117.
        assert summen.netto == Decimal('4267.00')
        assert sql.netto == summen.netto
        assert services.bruttosummen([lv.pk])[lv.pk] == summen.brutto

    def test_titelsummen_nach_der_letzten_unterposition(self, lv):
        positionen = list(lv.positionen.all())
        nach = services.titelsummen(positionen)

        summen = {s.titel.position: (positionen[i].position, s.netto)
                  for i, liste in nach.items() for s in liste}
        # Titel 01: Aushub, Verbau und Erschwernis, ohne die optionale
        # Wasserhaltung.
        assert summen == {
            '01': ('01.0040', Decimal('3750.00')),
            '02': ('02.0010', Decimal('400.00')),
        }

    def test_innerer_titel_schliesst_zuerst(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        _zeile(beleg, '01', 'Bau', art=Zeilenart.TITEL)
        _zeile(beleg, '01.01', 'Rohbau', art=Zeilenart.TITEL)
        _zeile(beleg, '01.01.0010', 'Mauern', '1', '300.00')
        nach = services.titelsummen(list(beleg.positionen.all()))

        (liste,) = nach.values()
        assert [(s.titel.position, s.netto) for s in liste] == [
            ('01.01', Decimal('300.00')), ('01', Decimal('300.00'))]

    def test_titel_ohne_unterpositionen_hat_keine_summe(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        _zeile(beleg, '10', 'Allgemeines', art=Zeilenart.TITEL)
        _zeile(beleg, '20', 'Leistung', '1', '10.00')

        assert services.titelsummen(list(beleg.positionen.all())) == {}


@pytest.mark.django_db
class TestZuschlag:

    def test_auf_eine_position(self, lv):
        assert _p(lv, '01.0040').einzelpreis == Decimal('250.00')

    def test_auf_alles_ohne_optionale_und_ohne_zuschlaege(self, lv):
        """3 % auf 1.000 + 2.500 + 400, ohne die optionale Wasserhaltung und
        ohne die Erschwernis."""
        nk = _p(lv, '03')
        assert (nk.menge, nk.einzelpreis) == (Decimal('1'), Decimal('117.00'))

    def test_auf_einen_titel(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        _zeile(beleg, '01', 'A', art=Zeilenart.TITEL)
        _zeile(beleg, '01.10', 'a', '1', '1000.00')
        _zeile(beleg, '02.10', 'b', '1', '5000.00')
        z = _zeile(beleg, '01.90', 'Zuschlag A', art=Zeilenart.ZUSCHLAG,
                   prozent='5', auf='01')

        assert z.einzelpreis == Decimal('50.00')

    def test_auf_den_cent_gerundet(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        _zeile(beleg, '10', 'a', '1', '333.33')
        z = _zeile(beleg, '20', 'NK', art=Zeilenart.ZUSCHLAG, prozent='3')

        # 9,9999 -> 10,00
        assert z.einzelpreis == Decimal('10.00')

    def test_neue_position_rechnet_den_zuschlag_nach(self, lv):
        _zeile(lv, '02.0020', 'Noch eine Probe', '1', '100.00')

        assert _p(lv, '03').einzelpreis == Decimal('120.00')

    def test_festschreiben_rechnet_einen_veralteten_zuschlag_nach(
            self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG,
                                       leistungsdatum=date(2026, 10, 1))
        _zeile(beleg, '10', 'a', '1', '1000.00')
        _zeile(beleg, '20', 'NK', art=Zeilenart.ZUSCHLAG, prozent='3')
        # Ohne Service geändert, wie bei einem Import.
        Belegposition.objects.filter(beleg=beleg, position='10').update(
            einzelpreis=Decimal('2000.00'))

        beleg = services.beleg_festschreiben(beleg_id=beleg.pk)

        assert _p(beleg, '20').einzelpreis == Decimal('60.00')
        assert services.belegsummen(beleg).netto == Decimal('2060.00')

    def test_ohne_satz_kein_zuschlag(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        zeile = Belegposition(beleg=beleg, position='10', bezeichnung='NK',
                              einzelpreis=Decimal('0'),
                              zeilenart=Zeilenart.ZUSCHLAG)

        with pytest.raises(ValidationError):
            zeile.full_clean()

    def test_in_der_rechnung_neu_gerechnet_ohne_optionale(self, lv):
        """Vom Angebot zur Rechnung: Die optionale Position entfällt, der
        Zuschlag bezieht sich auf die übrigen; hier unverändert, weil die
        Option nicht zur Basis gehörte."""
        angebot = services.beleg_festschreiben(beleg_id=lv.pk)
        rechnung = services.beleg_umwandeln(beleg_id=angebot.pk,
                                            neuer_typ=BelegTyp.RECHNUNG)

        assert not rechnung.positionen.filter(optional=True).exists()
        assert _p(rechnung, '03').zeilenart == Zeilenart.ZUSCHLAG
        assert _p(rechnung, '03').einzelpreis == Decimal('117.00')
        assert services.belegsummen(rechnung).netto == Decimal('4267.00')

    def test_storno_spiegelt_den_zuschlag(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG,
                                       leistungsdatum=date(2026, 10, 1))
        _zeile(beleg, '10', 'a', '1', '1000.00')
        _zeile(beleg, '20', 'NK', art=Zeilenart.ZUSCHLAG, prozent='3')
        beleg = services.beleg_festschreiben(beleg_id=beleg.pk)

        storno, _ = services.rechnung_korrigieren(beleg_id=beleg.pk)

        assert services.belegsummen(storno).netto == Decimal('-1030.00')


@pytest.mark.django_db
class TestBlatt:

    def test_titel_text_zuschlag_und_titelsumme_stehen_da(self, lv):
        html = pdf.beleg_als_html(lv)

        assert 'class="titelzeile' in html
        assert 'Summe Titel 01 Erdarbeiten' in html
        assert '3.750,00' in html
        assert 'Vorbemerkung: Proben nach DIN 19698' in html
        assert '3 % auf 3.900,00' in html
        assert '10 % auf 2.500,00 (Pos. 01.0020)' in html

    def test_zuschlag_auf_titel_nennt_den_titel(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        _zeile(beleg, '01', 'A', art=Zeilenart.TITEL)
        _zeile(beleg, '01.10', 'a', '1', '1000.00')
        _zeile(beleg, '01.90', 'Zuschlag A', art=Zeilenart.ZUSCHLAG,
               prozent='5', auf='01')

        assert '5 % auf 1.000,00 (Titel 01)' in pdf.beleg_als_html(beleg)


@pytest.mark.django_db
class TestERechnung:

    def test_titel_und_text_fehlen_der_zuschlag_ist_eine_position(
            self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG,
                                       leistungsdatum=date(2026, 10, 1))
        _zeile(beleg, '01', 'Erdarbeiten', art=Zeilenart.TITEL)
        _zeile(beleg, '01.0005', 'Hinweis', art=Zeilenart.TEXT)
        _zeile(beleg, '01.0010', 'Aushub', '10', '100.00')
        _zeile(beleg, '02', 'Nebenkosten', art=Zeilenart.ZUSCHLAG,
               prozent='3')
        beleg = services.beleg_festschreiben(beleg_id=beleg.pk)

        xml = facturx.xml_erzeugen(beleg).decode()

        assert 'Erdarbeiten' not in xml
        assert 'Hinweis' not in xml
        assert '<ram:LineID>01.0010</ram:LineID>' in xml
        assert '<ram:LineID>02</ram:LineID>' in xml
        assert Decimal(xml_wert(xml, 'TaxBasisTotalAmount')) == Decimal(
            '1030.00')


@pytest.mark.django_db
class TestSchlussrechnung:
    """Zuschläge der Abschläge erscheinen einmal als Zuschlag in der
    Schlussrechnung, berechnet auf die volle Leistung (R-179)."""

    @pytest.fixture
    def auftrag(self, projekt):
        beleg = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.AUFTRAG)
        _zeile(beleg, '01', 'Analytik', art=Zeilenart.TITEL)
        _zeile(beleg, '01.0010', 'Probe', '20', '100.00')
        return services.beleg_festschreiben(beleg_id=beleg.pk)

    def _abschlag(self, projekt, ap, menge, tag):
        beleg = services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG,
            rechnungsart=Rechnungsart.ABSCHLAG,
            leistungsdatum=tag, leistungsdatum_bis=tag)
        _zeile(beleg, '01', 'Analytik', art=Zeilenart.TITEL)
        services.position_hinzufuegen(
            beleg=beleg, position='01.0010', bezeichnung='Probe',
            menge=Decimal(menge), einheit='Stk',
            einzelpreis=Decimal('100.00'), steuersatz=VOLL,
            auftragsposition=ap)
        _zeile(beleg, '02', 'Nebenkosten', art=Zeilenart.ZUSCHLAG,
               prozent='3')
        beleg = services.beleg_festschreiben(beleg_id=beleg.pk)
        services.zahlung_verbuchen(
            beleg_id=beleg.pk, datum=tag,
            betrag=services.belegsummen(beleg).brutto)
        return beleg

    def test_ein_zuschlag_auf_die_volle_leistung(self, projekt, auftrag):
        ap = _p(auftrag, '01.0010')
        self._abschlag(projekt, ap, '6', date(2026, 2, 1))
        self._abschlag(projekt, ap, '4', date(2026, 3, 1))
        gesamt = Abnahme.objects.create(
            auftrag=auftrag, art=Abnahmeart.GESAMT,
            abgenommen_am=date(2026, 4, 1))

        schluss = services.rechnung_aus_abnahme(abnahme_id=gesamt.pk)

        leistung = list(schluss.positionen.filter(ist_abzug=False))
        assert [(p.zeilenart, p.menge, p.einzelpreis) for p in leistung] == [
            (Zeilenart.LEISTUNG, Decimal('10.000'), Decimal('100.00')),
            (Zeilenart.ZUSCHLAG, Decimal('1.000'), Decimal('30.00')),
        ]
        # Abgesetzt 618 + 412 = 1.030, gleich der Leistung.
        assert services.belegsummen(schluss).netto == Decimal('0.00')

    def test_titel_im_abschlag_wird_nicht_abgesetzt(self, projekt, auftrag):
        ab = self._abschlag(projekt, _p(auftrag, '01.0010'), '6',
                            date(2026, 2, 1))
        gesamt = Abnahme.objects.create(
            auftrag=auftrag, art=Abnahmeart.GESAMT,
            abgenommen_am=date(2026, 4, 1))
        schluss = services.rechnung_aus_abnahme(abnahme_id=gesamt.pk)

        abgesetzt = {p.abgesetzte_position.zeilenart for p in
                     schluss.positionen.filter(ist_abzug=True)}
        assert abgesetzt == {Zeilenart.LEISTUNG, Zeilenart.ZUSCHLAG}

        # Der Abschlag gilt mit der Schlussrechnung als abgerechnet, obwohl
        # sein Titel nicht abgesetzt wurde.
        services.beleg_festschreiben(beleg_id=schluss.pk)
        assert services.abgerechnet_in(ab) is not None


@pytest.mark.django_db
class TestErfassung:

    def test_auf_einen_titel_wird_nicht_gebucht(self, projekt):
        from erfassung.models import Erfassungszeile

        auftrag = services.beleg_anlegen(projekt=projekt,
                                         typ=BelegTyp.AUFTRAG)
        _zeile(auftrag, '01', 'Titel', art=Zeilenart.TITEL)
        _zeile(auftrag, '01.10', 'Leistung', '1', '10.00')
        auftrag = services.beleg_festschreiben(beleg_id=auftrag.pk)
        zeile = Erfassungszeile(projekt=projekt,
                                auftragsposition=_p(auftrag, '01'),
                                menge=Decimal('1'))

        with pytest.raises(ValidationError, match='Titel'):
            zeile._pruefe_grundlage()


@pytest.mark.django_db
class TestMaske:
    """Über das Formular: Der Zuschlag ist nach dem Speichern berechnet."""

    def test_sichern_rechnet_den_zuschlag(self, buero, kunde):
        zeilen = [
            ('10', 'Leistung', 'leistung', '2', '500.00', ''),
            ('20', 'Nebenkosten', 'zuschlag', '1', '', '3'),
        ]
        daten = {
            'kunde': kunde.pk, 'betreff': 'Zuschlagsprobe',
            'belegdatum': '', 'leistungsdatum': '', 'leistungsdatum_bis': '',
            'zahlungsziel_tage': '14',
            'empfaenger': '', 'empfaenger_ust_id': '',
            'kopftext': '', 'fusstext': '',
            'positionen-TOTAL_FORMS': str(len(zeilen)),
            'positionen-INITIAL_FORMS': '0',
            'positionen-MIN_NUM_FORMS': '0',
            'positionen-MAX_NUM_FORMS': '1000',
        }
        for i, (nummer, text, art, menge, preis, prozent) in enumerate(zeilen):
            daten.update({
                f'positionen-{i}-katalog': '',
                f'positionen-{i}-position': nummer,
                f'positionen-{i}-bezeichnung': text,
                f'positionen-{i}-menge': menge,
                f'positionen-{i}-einheit': 'Stk',
                f'positionen-{i}-einzelpreis': preis,
                f'positionen-{i}-steuersatz': VOLL,
                f'positionen-{i}-zeilenart': art,
                f'positionen-{i}-zuschlag_prozent': prozent,
                f'positionen-{i}-zuschlag_auf': '',
            })

        antwort = buero.post(reverse('admin:faktura_angebot_add'), daten,
                             follow=True)

        assert antwort.status_code == 200
        beleg = Beleg.objects.filter(typ=BelegTyp.ANGEBOT).latest('pk')
        assert _p(beleg, '20').einzelpreis == Decimal('30.00')
        assert services.belegsummen(beleg).netto == Decimal('1030.00')

    def test_geaenderte_menge_rechnet_den_zuschlag_nach(self, buero, lv):
        """Eine geänderte Menge berechnet den Zuschlag neu.

        Regression: Das Formset rechnete mit dem Prefetch-Cache, also mit
        dem Stand vor dem Speichern; erst das Festschreiben korrigierte."""
        from faktura.tests.test_schluss_leistung import _maskendaten
        adresse = reverse('admin:faktura_angebot_change', args=[lv.pk])
        daten = _maskendaten(buero.get(adresse))
        zeile = next(name.rsplit('-', 1)[0] for name, wert in daten.items()
                     if name.endswith('-position') and wert == '01.0020')
        daten[f'{zeile}-einzelpreis'] = '2000.00'

        assert buero.post(adresse, daten).status_code == 302
        assert _p(lv, '01.0040').einzelpreis == Decimal('1000.00')

    def test_zeilenart_steht_links_neben_der_suche(self, buero):
        """Die Zeilenart steht in der ersten Zeile einer neuen Position vor der
        Katalogsuche."""
        seite = buero.get(
            reverse('admin:faktura_angebot_add')).content.decode()

        erste_zeile = seite.index('form-row-erste-zeile')
        zeilenart = seite.index('name="positionen-0-zeilenart"')
        katalog = seite.index('name="positionen-0-katalog"')
        positionszeile = seite.index('name="positionen-0-position"')
        assert erste_zeile < zeilenart < katalog < positionszeile

    def test_was_der_browser_schickt_zaehlt_nur_wo_es_etwas_sagt(
            self, buero, lv):
        """Felder ohne Bedeutung sind ``disabled``: Einheit am Zuschlag und
        Steuersatz am Titel werden ignoriert, die Leistung daneben übernimmt
        ihre Änderung."""
        from faktura.tests.test_schluss_leistung import _maskendaten
        adresse = reverse('admin:faktura_angebot_change', args=[lv.pk])
        daten = _maskendaten(buero.get(adresse))
        nummern = {wert: name.rsplit('-', 1)[0]
                   for name, wert in daten.items()
                   if name.endswith('-position')}
        daten[f'{nummern["01"]}-steuersatz'] = '7.00'
        daten[f'{nummern["01"]}-menge'] = '4'
        daten[f'{nummern["03"]}-einheit'] = 'Stk'
        daten[f'{nummern["02.0010"]}-menge'] = '5'

        antwort = buero.post(adresse, daten)

        assert antwort.status_code == 302
        titel, nebenkosten = _p(lv, '01'), _p(lv, '03')
        assert titel.steuersatz == VOLL
        assert titel.menge == 0
        assert nebenkosten.einheit == ''
        assert _p(lv, '02.0010').menge == 5

    def test_festgeschrieben_ohne_menge_am_titel(self, buero, lv):
        """Am festgeschriebenen Beleg ohne JavaScript lässt ``lesewert`` die
        Zelle leer, ohne "0" oder "-"."""
        from faktura.templatetags.faktura_extras import OHNE_BEDEUTUNG
        services.beleg_festschreiben(beleg_id=lv.pk)

        seite = buero.get(reverse('admin:faktura_angebot_change',
                                  args=[lv.pk])).content.decode()

        assert OHNE_BEDEUTUNG in seite


class TestBezug:
    """Ein Zuschlag, dessen "auf" keine Leistung trifft (etwa vertipptes
    "50.1"), wird gemeldet, weil er sonst ohne Meldung 0,00 ergäbe."""

    def test_die_maske_meldet_es_am_feld(self, buero, lv):
        from faktura.tests.test_schluss_leistung import _maskendaten
        adresse = reverse('admin:faktura_angebot_change', args=[lv.pk])
        daten = _maskendaten(buero.get(adresse))
        zeile = next(name.rsplit('-', 1)[0] for name, wert in daten.items()
                     if name.endswith('-position') and wert == '01.0040')
        daten[f'{zeile}-zuschlag_auf'] = '50.1'

        antwort = buero.post(adresse, daten)

        assert antwort.status_code == 200
        assert 'Keine Leistung mit der Nummer 50.1' in antwort.content.decode()
        assert _p(lv, '01.0040').zuschlag_auf == '01.0020'

    def test_ein_titel_ohne_leistungen_trifft_nichts(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        _zeile(beleg, '01', 'Leer', art=Zeilenart.TITEL)
        _zeile(beleg, '02.0010', 'Probe', '1', '100.00')
        zuschlag = _zeile(beleg, '03', 'Erschwernis', art=Zeilenart.ZUSCHLAG,
                          prozent='10', auf='01')

        assert services.ohne_bezug(beleg.positionen.all()) == [zuschlag]

    def test_eine_optionale_leistung_trifft(self, lv):
        _zeile(lv, '04', 'Wasserhaltung extra', art=Zeilenart.ZUSCHLAG,
               prozent='5', auf='01.0030')

        assert services.ohne_bezug(lv.positionen.all()) == []

    def test_festschreiben_lehnt_ab(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        _zeile(beleg, '10', 'Probe', '1', '100.00')
        _zeile(beleg, '20', 'Erschwernis', art=Zeilenart.ZUSCHLAG,
               prozent='10', auf='50.1')

        with pytest.raises(services.UngueltigerBetrag, match='50.1'):
            services.beleg_festschreiben(beleg_id=beleg.pk)

    def test_in_der_rechnung_fehlt_die_optionale_zielposition(self, kunde):
        """Ohne Formular: Im Angebot bezieht sich der Zuschlag auf eine
        Option, die nicht in die Rechnung übernommen wird."""
        angebot = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        _zeile(angebot, '10', 'Probe', '1', '100.00')
        _zeile(angebot, '20', 'Eilprobe', '1', '50.00', optional=True)
        _zeile(angebot, '30', 'Eilzuschlag', art=Zeilenart.ZUSCHLAG,
               prozent='20', auf='20')
        services.beleg_festschreiben(beleg_id=angebot.pk)
        rechnung = services.beleg_umwandeln(beleg_id=angebot.pk,
                                            neuer_typ=BelegTyp.RECHNUNG)

        with pytest.raises(services.UngueltigerBetrag, match='Eilzuschlag'):
            services.beleg_festschreiben(beleg_id=rechnung.pk)


class TestFelderOhneBedeutung:
    """``felder_ohne_bedeutung``, verwendet von Formular, JavaScript und
    Readonly-Ansicht."""

    def test_am_titel_kein_betrag_am_zuschlag_der_steuersatz(self):
        from faktura.forms import BelegpositionForm
        titel = BelegpositionForm.felder_ohne_bedeutung(Zeilenart.TITEL)
        zuschlag = BelegpositionForm.felder_ohne_bedeutung(Zeilenart.ZUSCHLAG)
        leistung = BelegpositionForm.felder_ohne_bedeutung(Zeilenart.LEISTUNG)

        assert {'menge', 'einheit', 'einzelpreis', 'steuersatz',
                'zeilensumme', 'katalog'} <= set(titel)
        assert {'menge', 'einheit', 'einzelpreis', 'katalog'} <= set(zuschlag)
        assert 'steuersatz' not in zuschlag
        assert 'zuschlag_prozent' not in zuschlag
        assert set(leistung) == {'zuschlag_prozent', 'zuschlag_auf'}

    def test_leer_heisst_leistung(self):
        from faktura.forms import BelegpositionForm
        assert (BelegpositionForm.felder_ohne_bedeutung('')
                == BelegpositionForm.felder_ohne_bedeutung(Zeilenart.LEISTUNG))
