"""Summenzeile und Filter der Listen.

Die Summenzeile zeigt die Summe der gefilterten Belege. Geprüft wird vor
allem, **dass sie auf den Cent mit der Summe der Einzelbelege
übereinstimmt**.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from faktura import services
from faktura.models import (
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Kontakt,
    Projekt,
    Rechnung,
)

User = get_user_model()
HEUTE = timezone.localdate()


@pytest.fixture
def kunde(db):
    return Kontakt.objects.create(nummer='K-5000', name='Stadt Beispiel')


@pytest.fixture
def projekt(kunde):
    return Projekt.objects.create(
        nummer='2026-500', bezeichnung='Prüfvorhaben', kunde=kunde)


def _rechnung(projekt, positionen, *, nummer, tage_zurueck=0):
    """Festgeschriebene Rechnung mit beliebigen Positionen.

    Am Modell festgeschrieben, wie in ``test_auswertung.py``, weil der
    Service ein PDF erzeugt und dafür Firmenstammdaten verlangt.
    """
    beleg = Beleg.objects.create(typ=BelegTyp.RECHNUNG, projekt=projekt)
    for nr, (menge, preis, satz) in enumerate(positionen, start=1):
        Belegposition.objects.create(
            beleg=beleg, position=nr * 10, bezeichnung=f'Position {nr}',
            menge=Decimal(menge), einheit='Std',
            einzelpreis=Decimal(preis), steuersatz=satz)
    beleg.status = BelegStatus.FESTGESCHRIEBEN
    beleg.nummer = nummer
    beleg.belegdatum = HEUTE - timedelta(days=tage_zurueck)
    beleg.save()
    return beleg


@pytest.fixture
def als_buchhalterin(client, db):
    person = User.objects.create_user(
        username='bea', password='geheim12345', is_staff=True)
    person.user_permissions.add(*Permission.objects.filter(
        codename__in=['view_rechnung', 'view_lieferschein', 'view_projekt',
                      'view_angebot', 'add_angebot', 'change_angebot']))
    client.force_login(person)
    return client


@pytest.fixture
def als_monteur(client, db):
    """Benutzer mit View-Recht an Angeboten, ohne Rechte an Rechnungen und
    damit ohne Summen."""
    person = User.objects.create_user(
        username='mo', password='geheim12345', is_staff=True)
    person.user_permissions.add(
        Permission.objects.get(codename='view_angebot'))
    client.force_login(person)
    return client


class TestDieSummeStimmt:
    """Summenzeile und Einzelbelege ergeben dieselbe Zahl."""

    def test_sie_ist_die_summe_der_einzelbelege_auf_den_cent(self, projekt):
        """Die Summe entspricht der Summe der Einzelbelege auf den Cent.

        Die Rundungsregel steht in ``belegsummen``: Steuer je Beleg und Satz
        auf die Nettosumme. Eine Gruppierung über alle Belege wiche um Cent
        ab. Mit Beträgen, bei denen ein Rundungsfehler auffällt.
        """
        _rechnung(projekt, [('3.33', '19.99', '19.00'),
                            ('7', '4.44', '7.00')],
                  nummer='RE-1')
        _rechnung(projekt, [('1.17', '333.33', '19.00')],
                  nummer='RE-2')
        _rechnung(projekt, [('5', '11.11', '7.00')],
                  nummer='RE-3')

        summe = services.summe_ueber(Beleg.objects.all())
        einzeln = [services.belegsummen(b) for b in Beleg.objects.all()]

        assert summe.netto == sum(s.netto for s in einzeln)
        assert summe.steuer == sum(s.steuer for s in einzeln)
        assert summe.brutto == sum(s.brutto for s in einzeln)

    def test_ein_lieferschein_zaehlt_nicht_mit_sondern_daneben(self, projekt):
        """Lieferscheine zählen getrennt, weil sie keinen Wert haben und in der
        Summe als Nullzeile erschienen."""
        _rechnung(projekt, [('1', '100.00', '19.00')], nummer='RE-1')
        schein = Beleg.objects.create(typ=BelegTyp.LIEFERSCHEIN,
                                      projekt=projekt)
        Belegposition.objects.create(
            beleg=schein, position=10, bezeichnung='Geliefert',
            menge=Decimal('5'), einheit='Stk', einzelpreis=Decimal('0.00'))

        summe = services.summe_ueber(Beleg.objects.all())

        assert summe.anzahl == 1
        assert summe.ohne_wert == 1
        assert summe.netto == Decimal('100.00')

    def test_eine_leere_menge_ergibt_null_und_nicht_einen_fehler(self, db):
        summe = services.summe_ueber(Beleg.objects.none())

        assert summe.anzahl == 0
        assert summe.netto == Decimal('0.00')
        assert summe.brutto == Decimal('0.00')

    def test_sie_zaehlt_die_gefilterte_menge_und_nicht_die_seite(
            self, projekt):
        """Die Summe umfasst die gefilterte Menge, nicht nur die aktuelle
        Seite."""
        for nummer in range(30):
            _rechnung(projekt, [('1', '100.00', '19.00')],
                      nummer=f'RE-{nummer}')

        summe = services.summe_ueber(Beleg.objects.all())

        assert summe.anzahl == 30
        assert summe.netto == Decimal('3000.00')

    def test_ein_entwurf_zaehlt_mit_denn_die_liste_zeigt_ihn_auch(
            self, projekt):
        """Entwürfe zählen mit, anders als in den Auswertungen, weil die Summe
        den sichtbaren Zeilen der Liste entspricht."""
        beleg = Beleg.objects.create(typ=BelegTyp.RECHNUNG, projekt=projekt)
        Belegposition.objects.create(
            beleg=beleg, position=10, bezeichnung='Noch Entwurf',
            menge=Decimal('1'), einheit='pausch',
            einzelpreis=Decimal('500.00'), steuersatz='19.00')

        summe = services.summe_ueber(Beleg.objects.all())

        assert summe.netto == Decimal('500.00')


class TestDieSummeInDerListe:

    def test_sie_steht_unter_der_rechnungsliste(self, als_buchhalterin,
                                                projekt):
        _rechnung(projekt, [('4', '95.00', '19.00')], nummer='RE-1')

        inhalt = als_buchhalterin.get(
            reverse('admin:faktura_rechnung_changelist')).content.decode()

        assert '380,00' in inhalt      # netto
        assert '452,20' in inhalt      # brutto
        assert 'Brutto' in inhalt

    def test_sie_folgt_dem_filter(self, als_buchhalterin, projekt, kunde):
        """Zwei Projekte, gefiltert auf eines."""
        zweites = Projekt.objects.create(
            nummer='2026-501', bezeichnung='Anderes', kunde=kunde)
        _rechnung(projekt, [('1', '1000.00', '19.00')], nummer='RE-1')
        _rechnung(zweites, [('1', '7000.00', '19.00')], nummer='RE-2')

        adresse = reverse('admin:faktura_rechnung_changelist')
        inhalt = als_buchhalterin.get(
            f'{adresse}?projekt__id__exact={projekt.pk}').content.decode()

        assert '1.000,00' in inhalt
        assert '7.000,00' not in inhalt

    def test_ohne_belege_steht_keine_summenzeile_da(self, als_buchhalterin):
        """Ohne Belege keine Summenzeile."""
        inhalt = als_buchhalterin.get(
            reverse('admin:faktura_rechnung_changelist')).content.decode()

        assert 'Brutto' not in inhalt

    def test_ohne_das_recht_auf_rechnungen_wird_nichts_gerechnet(
            self, als_monteur, projekt):
        """Ohne View-Recht an Rechnungen keine Summen, wie auf der
        Startseite."""
        beleg = Beleg.objects.create(typ=BelegTyp.ANGEBOT, projekt=projekt)
        Belegposition.objects.create(
            beleg=beleg, position=10, bezeichnung='Angebot',
            menge=Decimal('1'), einheit='pausch',
            einzelpreis=Decimal('9999.00'), steuersatz='19.00')
        beleg.status = BelegStatus.FESTGESCHRIEBEN
        beleg.nummer = 'AN-1'
        beleg.belegdatum = HEUTE
        beleg.save()

        inhalt = als_monteur.get(
            reverse('admin:faktura_angebot_changelist')).content.decode()

        assert '9.999,00' not in inhalt or 'Brutto' not in inhalt

    def test_jede_belegart_bekommt_sie(self, als_buchhalterin, projekt):
        """Jede registrierte Belegart hat die Summenzeile."""
        from django.contrib.admin.sites import site

        from faktura.models import proxy_fuer

        for typ in BelegTyp.values:
            modell = proxy_fuer(typ)
            if modell not in site._registry:
                continue
            admin_klasse = site.get_model_admin(modell)
            assert admin_klasse.list_after_template == (
                'admin/faktura/belegsumme.html'), modell.__name__


class TestDieFilter:

    def test_das_belegdatum_ist_ein_bereich_und_keine_jahresliste(self):
        """Das Belegdatum filtert über einen Bereich.

        Verworfen: Djangos Default "Heute / Letzte 7 Tage / Diesen Monat /
        Dieses Jahr", mit dem sich etwa ein Quartal nicht filtern lässt.
        """
        from django.contrib.admin.sites import site
        from unfold.contrib.filters.admin import RangeDateFilter

        eintraege = dict(
            f for f in site.get_model_admin(Rechnung).list_filter
            if isinstance(f, tuple))

        assert eintraege['belegdatum'] is RangeDateFilter

    def test_das_projekt_ist_ein_suchfeld(self):
        """Der Projektfilter ist ein Suchfeld.

        Verworfen: eine Liste in der Seitenleiste und ein Select, das bei
        zehn Jahren Daten 1.200 Projekte in jede Belegliste lud
        (Lasttest)."""
        from django.contrib.admin.sites import site
        from unfold.contrib.filters.admin import AutocompleteSelectFilter

        eintraege = dict(
            f for f in site.get_model_admin(Rechnung).list_filter
            if isinstance(f, tuple))

        assert eintraege['projekt'] is AutocompleteSelectFilter

    def test_gefiltert_wird_erst_auf_knopfdruck(self):
        """Gefiltert wird erst per Button, weil die Seite sonst nach dem ersten
        Datumsfeld neu lädt und nur "ab Datum X" filtert."""
        from django.contrib.admin.sites import site

        assert site.get_model_admin(Rechnung).list_filter_submit

    def test_die_liste_laeuft_mit_den_neuen_filtern(self, als_buchhalterin,
                                                   projekt):
        """Die Liste rendert mit den Filtern, weil Filter erst beim Rendern
        instanziiert werden."""
        _rechnung(projekt, [('1', '100.00', '19.00')], nummer='RE-1')

        antwort = als_buchhalterin.get(
            reverse('admin:faktura_rechnung_changelist'))

        assert antwort.status_code == 200

    @pytest.mark.parametrize('schreibweise', ['%Y-%m-%d', '%d.%m.%Y'])
    def test_ein_gesetzter_datumsbereich_filtert_wirklich(
            self, als_buchhalterin, projekt, schreibweise):
        """Ein Datumsbereich filtert in ISO- und deutscher Schreibweise.

        Die Filterleiste sendet "01.07.2026"; Unfold parst mit
        ``settings.DATE_INPUT_FORMATS``. Regression: Mit Djangos Default
        wurde das Datum ``None``, der Filter lieferte ``None`` statt eines
        Querysets, und die Changelist ignorierte ihn ohne Fehler. Ein Test
        nur mit ISO-Format war grün.
        """
        _rechnung(projekt, [('1', '100.00', '19.00')],
                  nummer='RE-alt', tage_zurueck=200)
        _rechnung(projekt, [('1', '200.00', '19.00')],
                  nummer='RE-neu', tage_zurueck=2)
        _rechnung(projekt, [('1', '300.00', '19.00')],
                  nummer='RE-später', tage_zurueck=-30)

        adresse = reverse('admin:faktura_rechnung_changelist')
        von = (HEUTE - timedelta(days=10)).strftime(schreibweise)
        bis = (HEUTE + timedelta(days=1)).strftime(schreibweise)
        inhalt = als_buchhalterin.get(
            f'{adresse}?belegdatum_from={von}&belegdatum_to={bis}'
        ).content.decode()

        assert 'RE-neu' in inhalt
        assert 'RE-alt' not in inhalt
        assert 'RE-später' not in inhalt

    def test_die_deutsche_schreibweise_steht_in_den_einstellungen(self):
        """``settings.base`` enthält das deutsche Format, weil Unfold die
        Setting liest und nicht die Formate der Locale."""
        from django.conf import settings

        assert '%d.%m.%Y' in settings.DATE_INPUT_FORMATS


class TestJQueryBleibtEinmal:
    """jQuery wird auf Seiten mit Unfold-Filtern nur einmal geladen.

    Unfolds Filterformulare bestimmen in ``class Media`` beim **Import**,
    ob sie jquery.js oder jquery.min.js laden; Djangos Admin entscheidet
    bei jedem Request. Weichen beide ab, stehen zwei Pfade auf dieselbe
    Bibliothek im HTML, und die Übernahme der Kundenanschrift bindet sich
    ohne Fehler an die falsche Instanz.
    """

    @pytest.mark.parametrize('adresse', [
        'admin:faktura_rechnung_changelist',
        'admin:faktura_angebot_add',
    ])
    def test_genau_ein_jquery_im_html(self, als_buchhalterin, adresse):
        import re

        inhalt = als_buchhalterin.get(reverse(adresse)).content.decode()
        pfade = re.findall(r'<script[^>]*src="([^"]+)"', inhalt)
        jquery = [p for p in pfade if 'vendor/jquery/jquery' in p]

        assert len(jquery) == 1, jquery


# ══════════════════════════════════════════════════════════════════════════
# Tabs der Rechnungsliste und "Zahlung vermerken" in der Zeile
# ══════════════════════════════════════════════════════════════════════════

def _faellig(beleg, tage_ueber):
    Beleg.objects.filter(pk=beleg.pk).update(
        faellig_am=HEUTE - timedelta(days=tage_ueber))
    beleg.refresh_from_db()
    return beleg


def _reiter(antwort) -> dict:
    """Tabs der Seite als Titel auf (URL, aktiv), aus dem Template-Kontext
    von Unfold."""
    from unfold.templatetags.unfold import _get_tabs_list

    reiter = _get_tabs_list(antwort.context, 'changelist',
                            antwort.context['opts'])
    return {r['title']: (str(r.get('link_callback') or r['link']), r['active'])
            for r in reiter}


@pytest.mark.django_db
class TestDieReiter:
    """Die Tests folgen den Tabs und prüfen die resultierende Liste."""

    @pytest.fixture
    def belege(self, projekt, kunde):
        neu = _faellig(_rechnung(projekt, [('1', '100.00', '19.00')],
                                 nummer='RE-1'), 5)
        alt = _faellig(_rechnung(projekt, [('1', '200.00', '19.00')],
                                 nummer='RE-2'), 40)
        puenktlich = _faellig(_rechnung(
            projekt, [('1', '300.00', '19.00')], nummer='RE-3'), -7)
        entwurf = Beleg.objects.create(typ=BelegTyp.RECHNUNG, projekt=projekt)
        return {'neu': neu, 'alt': alt, 'puenktlich': puenktlich,
                'entwurf': entwurf}

    def _liste(self, client, adresse):
        antwort = client.get(adresse)
        assert antwort.status_code == 200, adresse
        return antwort

    def test_ueber_frist_zeigt_die_aelteste_zuerst(self, verwaltung, belege):
        reiter = _reiter(self._liste(
            verwaltung, reverse('admin:faktura_rechnung_changelist')))

        antwort = self._liste(verwaltung, reiter['Über Frist'][0])

        assert list(antwort.context['cl'].result_list) == [
            belege['alt'], belege['neu']]
        assert _reiter(antwort)['Über Frist'][1] is True
        assert _reiter(antwort)['Alle'][1] is False

    def test_jeder_reiter_filtert(self, verwaltung, belege):
        reiter = _reiter(self._liste(
            verwaltung, reverse('admin:faktura_rechnung_changelist')))

        def menge(titel):
            return set(self._liste(verwaltung, reiter[titel][0])
                       .context['cl'].queryset)

        assert menge('Entwürfe') == {belege['entwurf']}
        assert menge('Offen') == {belege['neu'], belege['alt'],
                                  belege['puenktlich']}
        assert menge('Bezahlt') == set()
        assert len(menge('Alle')) == 4

    def test_alle_ist_nur_ohne_filter_aktiv(self, verwaltung, belege):
        """"Alle" ist nur ohne Filter aktiv, weil Unfold einen Tab ohne
        Parameter sonst immer als aktiv markiert."""
        ohne = _reiter(self._liste(
            verwaltung, reverse('admin:faktura_rechnung_changelist')))

        assert [t for t, (_, aktiv) in ohne.items() if aktiv] == ['Alle']


@pytest.mark.django_db
class TestZahlungVermerkenInDerZeile:
    """Der Link "Zahlung vermerken" steht nur bei offenen Rechnungen und
    führt zur Zwischenseite."""

    def _zelle(self, antwort, beleg) -> str:
        import re
        zeile = next(z for z in re.findall(
            r'<tr[^>]*>(.*?)</tr>', antwort.content.decode(), re.S)
            if f'>{beleg.nummer}<' in z)
        treffer = re.search(r'field-zahlung_vermerken[^>]*>(.*?)</td>', zeile, re.S)
        return treffer.group(1) if treffer else None

    def test_nur_an_der_offenen_rechnung(self, verwaltung, projekt, kunde):
        offen = _rechnung(projekt, [('1', '100.00', '19.00')],
                          nummer='RE-1')
        bezahlt = _rechnung(projekt, [('1', '100.00', '19.00')],
                            nummer='RE-2')
        services.zahlung_verbuchen(beleg_id=bezahlt.pk, datum=HEUTE,
                                   betrag=Decimal('119.00'))

        antwort = verwaltung.get(reverse('admin:faktura_rechnung_changelist'))

        assert 'payments' in self._zelle(antwort, offen)
        assert 'payments' not in self._zelle(antwort, bezahlt)

    def test_der_verweis_fuehrt_zur_zahlung(self, verwaltung, projekt):
        offen = _rechnung(projekt, [('1', '100.00', '19.00')],
                          nummer='RE-1')
        import re
        antwort = verwaltung.get(reverse('admin:faktura_rechnung_changelist'))
        adresse = re.search(r'href="([^"]+)"', self._zelle(antwort, offen)).group(1)

        ziel = verwaltung.get(adresse)

        assert ziel.status_code == 200
        assert 'RE-1' in ziel.content.decode()

    def test_an_der_bezahlten_weist_der_server_ab(self, verwaltung, projekt):
        """Bei bezahlter Rechnung lehnt der Server die manuell aufgerufene URL
        ab; Unfold prüft ``has_zahlung_permission`` mit der ID."""
        bezahlt = _rechnung(projekt, [('1', '100.00', '19.00')],
                            nummer='RE-2')
        services.zahlung_verbuchen(beleg_id=bezahlt.pk, datum=HEUTE,
                                   betrag=Decimal('119.00'))

        antwort = verwaltung.get(reverse(
            'admin:faktura_rechnung_detail_zahlung', args=[bezahlt.pk]))

        assert antwort.status_code == 403

    def test_ohne_recht_keine_spalte(self, als_buchhalterin, projekt):
        _rechnung(projekt, [('1', '100.00', '19.00')], nummer='RE-1')

        antwort = als_buchhalterin.get(
            reverse('admin:faktura_rechnung_changelist'))

        assert 'field-zahlung_vermerken' not in antwort.content.decode()
