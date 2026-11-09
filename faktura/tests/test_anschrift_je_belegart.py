"""Anschrift nach Belegart und Hinweis bei umgewandelten Belegen."""

from decimal import Decimal

import pytest
from django.contrib.admin.models import LogEntry
from django.urls import reverse
from django.utils import timezone

from faktura import services
from faktura.models import Adresse, Adressverwendung, BelegTyp, Kontakt
from faktura.tests.admin.hilfen import User


@pytest.fixture
def kontakt(db):
    kunde = Kontakt.anlegen(nummer='K-5000', name='Landratsamt',
                            strasse='Postweg 1', plz='84028', ort='Landshut')
    post = kunde.adressen.get()
    post.verwendung = Adressverwendung.POST
    post.save()
    Adresse.objects.create(kontakt=kunde, verwendung=Adressverwendung.RECHNUNG,
                           strasse='Kassenweg 2', plz='84030', ort='Ergolding')
    Adresse.objects.create(kontakt=kunde, verwendung=Adressverwendung.LIEFERUNG,
                           strasse='Baustelle 3', plz='84032', ort='Altdorf')
    return Kontakt.objects.get(pk=kunde.pk)


def _beleg(kontakt, typ):
    beleg = services.beleg_anlegen(kunde=kontakt, typ=typ, betreff='Probe',
                                   leistungsdatum=timezone.localdate())
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Leistung', menge=Decimal('1'),
        einzelpreis=Decimal('100.00'), steuersatz='19.00')
    return beleg


def _fest(beleg):
    return services.beleg_festschreiben(beleg_id=beleg.pk)


@pytest.mark.django_db
class TestNeuerBeleg:

    @pytest.mark.parametrize(('typ', 'strasse'), [
        (BelegTyp.ANGEBOT, 'Postweg 1'),
        (BelegTyp.AUFTRAG, 'Postweg 1'),
        (BelegTyp.LIEFERSCHEIN, 'Baustelle 3'),
        (BelegTyp.RECHNUNG, 'Kassenweg 2'),
    ])
    def test_anschrift_folgt_der_belegart(self, kontakt, typ, strasse):
        beleg = _beleg(kontakt, typ)

        assert strasse in beleg.empfaenger
        assert beleg.empfaenger_strasse == strasse

    def test_ohne_passende_gilt_die_standardanschrift(self, db):
        kunde = Kontakt.anlegen(nummer='K-5001', name='Einfach GmbH',
                                strasse='Nur Hier 1', plz='80331', ort='München')

        beleg = _beleg(kunde, BelegTyp.ANGEBOT)

        assert beleg.empfaenger_strasse == 'Nur Hier 1'

    def test_rechnungsempfaenger_gilt_nur_fuer_die_rechnung(self, kontakt):
        verwaltung = Kontakt.anlegen(
            nummer='K-5002', name='Hausverwaltung', strasse='Verwaltungsweg 9',
            plz='80331', ort='München')
        kontakt.rechnungsempfaenger = verwaltung
        kontakt.save()

        angebot = _beleg(kontakt, BelegTyp.ANGEBOT)
        rechnung = _beleg(kontakt, BelegTyp.RECHNUNG)

        assert angebot.empfaenger_name == 'Landratsamt'
        assert angebot.empfaenger_strasse == 'Postweg 1'
        assert rechnung.empfaenger_name == 'Hausverwaltung'
        assert rechnung.empfaenger_strasse == 'Verwaltungsweg 9'

    def test_vorbelegung_im_formular_folgt_der_belegart(self, buero, kontakt):
        daten = buero.get(reverse('admin:faktura_angebot_kundendaten'),
                          {'kunde': kontakt.pk}).json()

        assert daten['empfaenger_strasse'] == 'Postweg 1'


@pytest.mark.django_db
class TestUmwandeln:

    @pytest.fixture
    def folge(self, kontakt):
        angebot = _fest(_beleg(kontakt, BelegTyp.ANGEBOT))
        return services.beleg_umwandeln(beleg_id=angebot.pk,
                                        neuer_typ=BelegTyp.RECHNUNG)

    def test_der_empfaenger_wird_unveraendert_kopiert(self, folge):
        assert folge.empfaenger_strasse == 'Postweg 1'

    def test_die_abweichung_wird_gemeldet(self, folge):
        abweichung = services.andere_anschrift(folge)

        assert abweichung.bezeichnung == 'Rechnungsanschrift'
        assert 'Postweg 1' in abweichung.aktuell
        assert 'Kassenweg 2' in abweichung.vorschlag

    def test_angebot_zu_auftrag_ohne_hinweis(self, kontakt):
        angebot = _fest(_beleg(kontakt, BelegTyp.ANGEBOT))
        auftrag = services.beleg_umwandeln(beleg_id=angebot.pk,
                                           neuer_typ=BelegTyp.AUFTRAG)

        assert services.andere_anschrift(auftrag) is None

    def test_uebernehmen_ersetzt_freitext_und_felder(self, folge):
        services.anschrift_uebernehmen(beleg_id=folge.pk)

        folge.refresh_from_db()
        assert 'Kassenweg 2' in folge.empfaenger
        assert 'Postweg 1' not in folge.empfaenger
        assert (folge.empfaenger_strasse, folge.empfaenger_plz,
                folge.empfaenger_ort) == ('Kassenweg 2', '84030', 'Ergolding')
        assert services.andere_anschrift(folge) is None
        assert services.empfaenger_abweichungen(folge) == []

    def test_ohne_abweichung_nichts_zu_uebernehmen(self, folge):
        services.anschrift_uebernehmen(beleg_id=folge.pk)

        with pytest.raises(services.FakturaError):
            services.anschrift_uebernehmen(beleg_id=folge.pk)

    def test_festgeschrieben_kein_hinweis(self, folge):
        fest = _fest(folge)

        assert services.andere_anschrift(fest) is None


@pytest.mark.django_db
class TestMaske:

    @pytest.fixture
    def folge(self, kontakt):
        angebot = _fest(_beleg(kontakt, BelegTyp.ANGEBOT))
        return services.beleg_umwandeln(beleg_id=angebot.pk,
                                        neuer_typ=BelegTyp.RECHNUNG)

    def _adresse(self, folge, name='change'):
        return reverse(f'admin:faktura_rechnung_{name}', args=[folge.pk])

    def _klick(self, client, folge):
        return client.post(
            reverse('admin:faktura_rechnung_detail_anschrift', args=[folge.pk]),
            {'_form_submitted': 'on'}, HTTP_HX_REQUEST='true')

    def test_hinweis_und_knopf_in_der_maske(self, buero, folge):
        antwort = buero.get(self._adresse(folge))

        meldungen = [str(m) for m in antwort.context['messages']]
        assert any('Kassenweg 2' in m and 'Postweg 1' in m for m in meldungen)
        assert 'Anschrift laut Kontakt' in antwort.content.decode()

    def test_klick_ersetzt_und_steht_im_verlauf(self, buero, folge):
        """Der Klick wird wie im Dialog per htmx ausgelöst."""
        antwort = self._klick(buero, folge)

        assert antwort['HX-Redirect'] == self._adresse(folge)
        folge.refresh_from_db()
        assert folge.empfaenger_strasse == 'Kassenweg 2'
        eintrag = LogEntry.objects.get(object_id=str(folge.pk))
        assert 'Postweg 1' in eintrag.change_message
        assert 'Kassenweg 2' in eintrag.change_message

    def test_nur_ansehen_darf_nicht_ersetzen(self, client, folge):
        from django.contrib.auth.models import Permission

        konto = User.objects.create_user(
            username='nur-sehen', email='s@example.invalid',
            password='geheim12345', is_staff=True)
        konto.user_permissions.add(Permission.objects.get(
            content_type__app_label='faktura', codename='view_rechnung'))
        client.force_login(konto)

        antwort = self._klick(client, folge)

        assert antwort.status_code == 403
        folge.refresh_from_db()
        assert folge.empfaenger_strasse == 'Postweg 1'

    def test_hinweis_beim_versenden(self, buero, folge):
        inhalt = buero.get(self._adresse(folge).replace(
            '/change/', '/versenden/')).content.decode()

        assert 'Passt der Empfänger?' in inhalt
        assert 'Kassenweg 2' in inhalt
