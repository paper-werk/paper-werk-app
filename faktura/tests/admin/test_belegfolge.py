"""Folgebelege, Duplikate und Wiedereröffnen."""

from decimal import Decimal

import pytest
from django.contrib import admin
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from core.adminhilfen import WEITERE
from faktura import services
from faktura.models import (
    Angebot,
    Beleg,
    BelegStatus,
    BelegTyp,
    Rechnung,
    Rechnungsart,
)
from faktura.tests.admin.hilfen import User


@pytest.mark.django_db
class TestDasAngebotFuehrtWeiter:
    """Folgeschritte der Belegkette als Detailaktionen am Angebot.

    Die Schritte (Angebot, Auftrag, Lieferschein, Rechnung) stehen im
    geöffneten Beleg, zusätzlich zu den Listenaktionen.
    """

    def _maske(self, buero, beleg):
        return buero.get(reverse('admin:faktura_angebot_change',
                                 args=[beleg.pk])).content.decode()

    def test_am_entwurf_gibt_es_nichts_umzuwandeln(self, buero, angebot):
        """Am Entwurf kein Button zum Umwandeln, weil ``beleg_umwandeln`` einen
        festgeschriebenen Beleg verlangt."""
        inhalt = self._maske(buero, angebot)

        # "Versenden" schließt das Festschreiben ein und steht an jeder
        # Belegart.
        assert 'Versenden' in inhalt
        assert 'Auftrag erzeugen' not in inhalt
        assert 'Rechnung erzeugen' not in inhalt

    def test_danach_stehen_die_folgeschritte_da(self, buero, angebot):
        services.beleg_festschreiben(beleg_id=angebot.pk)

        inhalt = self._maske(buero, angebot)

        assert 'Auftrag erzeugen' in inhalt
        assert 'Rechnung erzeugen' in inhalt
        assert 'Festschreiben' not in inhalt

    def test_die_umwandlung_erzeugt_einen_entwurf(self, buero, angebot):
        services.beleg_festschreiben(beleg_id=angebot.pk)

        buero.post(reverse('admin:faktura_angebot_detail_in_auftrag',
                           args=[angebot.pk]),
                   {'_form_submitted': 'on'})

        ab = Beleg.objects.get(typ=BelegTyp.AUFTRAG)
        assert ab.status == BelegStatus.ENTWURF
        assert ab.vorgaenger_id == angebot.pk
        # Die Positionen werden übernommen.
        assert ab.positionen.count() == 1

    def test_die_umwandlung_oeffnet_den_neuen_beleg(self, buero, angebot):
        """Nach der Umwandlung Redirect auf den neuen Beleg."""
        services.beleg_festschreiben(beleg_id=angebot.pk)

        antwort = buero.post(
            reverse('admin:faktura_angebot_detail_in_auftrag',
                    args=[angebot.pk]),
            {'_form_submitted': 'on'})

        ab = Beleg.objects.get(typ=BelegTyp.AUFTRAG)
        assert antwort['Location'] == reverse(
            'admin:faktura_auftrag_change', args=[ab.pk])

    def test_ohne_bestaetigung_entsteht_nichts(self, buero, angebot):
        """Der GET zeigt nur die Bestätigung; ohne POST entsteht nichts."""
        services.beleg_festschreiben(beleg_id=angebot.pk)

        antwort = buero.get(reverse('admin:faktura_angebot_detail_in_auftrag',
                                    args=[angebot.pk]))

        assert antwort.status_code == 200
        assert not Beleg.objects.filter(
            typ=BelegTyp.AUFTRAG).exists()


@pytest.mark.django_db
class TestDieRechnungDupliziert:
    """Duplizieren im Menü "Weitere …" der Rechnung, nicht an der
    Schlussrechnung."""

    def _angeboten(self, modell, beleg):
        anfrage = RequestFactory().get('/')
        anfrage.user = User.objects.get(username='sekretariat')
        modell_admin = admin.site.get_model_admin(modell)
        return {a.action_name.split('_detail_')[-1]
                for a in modell_admin.get_actions_detail(anfrage, str(beleg.pk))}

    def _rechnung(self, kunde, rechnungsart=Rechnungsart.NORMAL):
        beleg = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.RECHNUNG, rechnungsart=rechnungsart,
            leistungsdatum=timezone.localdate())
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Montage', menge=Decimal('1'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00')
        return beleg

    def test_im_menue(self):
        menue = [e for e in admin.site.get_model_admin(Rechnung).actions_detail
                 if isinstance(e, dict)][0]

        assert menue['title'] == WEITERE
        assert 'detail_duplizieren' in menue['items']

    def test_an_rechnung_und_abschlag(self, buero, kunde):
        from faktura.models import Abschlagsrechnung
        assert 'duplizieren' in self._angeboten(Rechnung, self._rechnung(kunde))
        assert 'duplizieren' in self._angeboten(
            Abschlagsrechnung, self._rechnung(kunde, Rechnungsart.ABSCHLAG))

    def test_nicht_an_der_schlussrechnung(self, buero, kunde):
        from faktura.models import Schlussrechnung
        schluss = self._rechnung(kunde, Rechnungsart.SCHLUSS)

        assert 'duplizieren' not in self._angeboten(Schlussrechnung, schluss)

    def test_der_dialog_warnt_vor_den_zeiten(self, buero, kunde):
        """Der Hinweis auf erfasste Zeiten erscheint vor dem Kopieren im
        Dialog."""
        rechnung = self._rechnung(kunde)

        dialog = buero.get(reverse('admin:faktura_rechnung_detail_duplizieren',
                                   args=[rechnung.pk])).content.decode()

        assert 'keinen Bezug zu erfassten Leistungen' in dialog
        assert 'Fremdleistungen werden nicht' in dialog

    def test_duplizieren_oeffnet_die_kopie(self, buero, kunde):
        rechnung = services.beleg_festschreiben(
            beleg_id=self._rechnung(kunde).pk)

        antwort = buero.post(
            reverse('admin:faktura_rechnung_detail_duplizieren',
                    args=[rechnung.pk]),
            {'_form_submitted': 'on'})

        kopie = Beleg.objects.exclude(pk=rechnung.pk).get(
            typ=BelegTyp.RECHNUNG)
        assert antwort['Location'] == reverse(
            'admin:faktura_rechnung_change', args=[kopie.pk])
        assert kopie.status == BelegStatus.ENTWURF


@pytest.mark.django_db
class TestDasAngebotImMenue:
    """Folgeschritte im Menü "Weitere …" wie an der Rechnung; vorn Versenden
    und PDF."""

    def _angeboten(self, person, beleg):
        """Für den Benutzer angezeigte Buttons als Methodennamen; Unfold
        stellt ``faktura_angebot_`` voran."""
        anfrage = RequestFactory().get('/')
        anfrage.user = person
        modell_admin = admin.site.get_model_admin(Angebot)
        return {a.action_name.removeprefix('faktura_angebot_')
                for a in modell_admin.get_actions_detail(anfrage, str(beleg.pk))}

    def test_der_aufbau(self):
        """Aufteilung der Buttons zwischen Kopfleiste und Menü."""
        eintraege = admin.site.get_model_admin(Angebot).actions_detail
        vorn = [e for e in eintraege if isinstance(e, str)]
        menues = [e for e in eintraege if isinstance(e, dict)]

        assert vorn == ['detail_versenden', 'detail_pdf']
        assert len(menues) == 1
        assert menues[0]['title'] == WEITERE
        assert menues[0]['items'] == [
            'detail_erneut_versenden', 'detail_in_auftrag',
            'detail_in_rechnung', 'detail_wiedereroeffnen',
            'detail_duplizieren', 'detail_verlauf']

    def test_am_entwurf_bleibt_im_menue_nur_duplizieren(self, buero, angebot):
        person = User.objects.get(username='sekretariat')
        namen = self._angeboten(person, angebot)

        assert 'detail_duplizieren' in namen
        assert not namen & {'detail_in_auftrag', 'detail_in_rechnung',
                            'detail_wiedereroeffnen'}

    def test_auftrag_und_rechnung(self):
        """Vorn Akte, Statusschritt und PDF; an der Rechnung die Zahlung als
        erster Eintrag in "Weitere …"."""
        from faktura.models import Auftrag

        def aufbau(modell):
            eintraege = admin.site.get_model_admin(modell).actions_detail
            return ([e for e in eintraege if isinstance(e, str)],
                    eintraege[-1]['items'])

        vorn, menue = aufbau(Auftrag)
        assert vorn == ['detail_akte', 'detail_festschreiben', 'detail_pdf']
        assert menue == ['detail_nachtrag', 'detail_in_lieferschein',
                         'detail_in_rechnung', 'detail_wiedereroeffnen',
                         'detail_verlauf']

        vorn, menue = aufbau(Rechnung)
        assert vorn == ['detail_akte', 'detail_versenden', 'detail_pdf']
        assert menue[0] == 'detail_zahlung'
        assert menue[-1] == 'detail_verlauf'

    def test_am_festgeschriebenen_steht_alles_da(self, buero, angebot):
        services.beleg_festschreiben(beleg_id=angebot.pk)
        person = User.objects.get(username='sekretariat')

        namen = self._angeboten(person, angebot)

        assert {'detail_in_auftrag', 'detail_in_rechnung',
                'detail_wiedereroeffnen', 'detail_duplizieren'} <= namen

    def test_ohne_recht_zum_anlegen_kein_duplikat(self, db, angebot):
        """Ohne add-Recht kein Button zum Duplizieren, und die URL antwortet
        mit 403."""
        from django.contrib.auth.models import Permission
        person = User.objects.create_user(
            username='nur-lesen', password='geheim12345', is_staff=True)
        person.user_permissions.add(
            Permission.objects.get(codename='view_angebot'))

        namen = self._angeboten(person, angebot)
        assert 'detail_duplizieren' not in namen

        from django.test import Client
        client = Client()
        client.force_login(person)
        client.post(reverse('admin:faktura_angebot_detail_duplizieren',
                            args=[angebot.pk]), {'_form_submitted': 'on'})
        assert Beleg.objects.filter(typ=BelegTyp.ANGEBOT).count() == 1

    def test_duplizieren_oeffnet_die_kopie(self, buero, angebot):
        services.beleg_festschreiben(beleg_id=angebot.pk)

        antwort = buero.post(
            reverse('admin:faktura_angebot_detail_duplizieren',
                    args=[angebot.pk]),
            {'_form_submitted': 'on'})

        kopie = Beleg.objects.exclude(pk=angebot.pk).get(
            typ=BelegTyp.ANGEBOT)
        assert antwort['Location'] == reverse(
            'admin:faktura_angebot_change', args=[kopie.pk])
        assert kopie.status == BelegStatus.ENTWURF
        assert kopie.positionen.count() == 1

    def test_aus_dem_dialog_per_htmx(self, buero, angebot):
        """Der Dialog sendet per htmx und erhält ``HX-Redirect``; sonst bliebe
        er leer, und die Kopie entstünde unbemerkt."""
        antwort = buero.post(
            reverse('admin:faktura_angebot_detail_duplizieren',
                    args=[angebot.pk]),
            {'_form_submitted': 'on'}, HTTP_HX_REQUEST='true')

        kopie = Beleg.objects.exclude(pk=angebot.pk).get(
            typ=BelegTyp.ANGEBOT)
        assert antwort['HX-Redirect'] == reverse(
            'admin:faktura_angebot_change', args=[kopie.pk])

    def test_ohne_bestaetigung_entsteht_nichts(self, buero, angebot):
        antwort = buero.get(reverse('admin:faktura_angebot_detail_duplizieren',
                                    args=[angebot.pk]))

        assert antwort.status_code == 200
        assert Beleg.objects.filter(typ=BelegTyp.ANGEBOT).count() == 1

    def test_die_kopie_nennt_ihre_herkunft_im_verlauf(self, buero, angebot):
        from django.contrib.admin.models import LogEntry
        buero.post(reverse('admin:faktura_angebot_detail_duplizieren',
                           args=[angebot.pk]), {'_form_submitted': 'on'})
        kopie = Beleg.objects.exclude(pk=angebot.pk).get(
            typ=BelegTyp.ANGEBOT)

        verlauf = buero.get(reverse('admin:faktura_angebot_history',
                                    args=[kopie.pk])).content.decode()

        assert LogEntry.objects.filter(object_id=str(kopie.pk)).exists()
        assert 'Dupliziert aus' in verlauf


@pytest.mark.django_db
class TestWiedereroeffnenImAdmin:
    """Wiedereröffnen: ein Button, ein Dialog, danach ein Entwurf.

    In der Liste ein Schloss oder nichts. Verworfen: zwei wechselnde
    Buttons, eine Zwischenseite mit Feld für den Grund, ein Warnhinweis am
    geöffneten Beleg und eine Spalte für die Fassung in der Liste.
    """

    def _maske(self, buero, beleg, art='angebot'):
        return buero.get(reverse(f'admin:faktura_{art}_change',
                                 args=[beleg.pk])).content.decode()

    def test_am_entwurf_gibt_es_nichts_zu_oeffnen(self, buero, angebot):
        assert 'Wieder öffnen' not in self._maske(buero, angebot)

    def test_am_festgeschriebenen_angebot_steht_der_knopf(self, buero, angebot):
        services.beleg_festschreiben(beleg_id=angebot.pk)

        assert 'Wieder öffnen' in self._maske(buero, angebot)

    def test_an_der_rechnung_niemals(self, buero, rechnungsentwurf):
        """Eine Rechnung lässt sich nie wiedereröffnen, weil sie Buchungsbeleg
        ist."""
        services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)

        assert 'Wieder öffnen' not in self._maske(
            buero, rechnungsentwurf, art='rechnung')

    def test_der_aufruf_allein_oeffnet_nichts(self, buero, angebot):
        """Der GET zeigt nur den Dialog und öffnet nichts."""
        services.beleg_festschreiben(beleg_id=angebot.pk)

        antwort = buero.get(
            reverse('admin:faktura_angebot_detail_wiedereroeffnen',
                    args=[angebot.pk]))

        assert antwort.status_code == 200
        assert (Beleg.objects.get(pk=angebot.pk).status
                == BelegStatus.FESTGESCHRIEBEN)

    def test_der_knopf_macht_einen_entwurf_daraus(self, buero, angebot):
        services.beleg_festschreiben(beleg_id=angebot.pk)

        buero.post(
            reverse('admin:faktura_angebot_detail_wiedereroeffnen',
                    args=[angebot.pk]),
            {'_form_submitted': 'on'})

        beleg = Beleg.objects.get(pk=angebot.pk)
        assert beleg.ist_entwurf
        assert beleg.nummer is not None
        assert beleg.geaendert_von.username == 'sekretariat'

    def test_danach_gibt_es_wieder_versenden(self, buero, angebot):
        """Danach erscheint "Versenden" wie an jedem Entwurf, ohne eigenen
        Button zum erneuten Festschreiben."""
        services.beleg_festschreiben(beleg_id=angebot.pk)
        services.beleg_wiedereroeffnen(beleg_id=angebot.pk)

        inhalt = self._maske(buero, angebot)

        assert 'Versenden' in inhalt
        assert 'Wieder öffnen' not in inhalt

    def test_die_aenderung_geht_wirklich_durch(self, buero, angebot):
        """Nach dem Wiedereröffnen lässt sich der Beleg samt Positionen über
        das Formular speichern.

        Regression: ``BelegNichtAenderbar: Positionen sind gesperrt``, weil
        das Inline-Formset nicht speicherte. Einziger Test über das
        vollständige Formular mit Positionen.
        """
        services.beleg_festschreiben(beleg_id=angebot.pk)
        services.beleg_wiedereroeffnen(beleg_id=angebot.pk)
        beleg = Beleg.objects.get(pk=angebot.pk)
        position = beleg.positionen.get()

        antwort = buero.post(
            reverse('admin:faktura_angebot_change', args=[beleg.pk]),
            {
                'kunde': str(beleg.kunde_id), 'projekt': '',
                'betreff': 'Halle Nord, zweiter Anlauf',
                'empfaenger': beleg.empfaenger, 'empfaenger_email': '',
                'empfaenger_ust_id': '',
                'belegdatum': beleg.belegdatum.strftime('%d.%m.%Y'),
                'leistungsdatum': '', 'leistungsdatum_bis': '',
                'zahlungsziel_tage': str(beleg.zahlungsziel_tage),
                'kopftext': '', 'fusstext': '',
                'empfaenger_name': beleg.empfaenger_name,
                'empfaenger_strasse': beleg.empfaenger_strasse,
                'empfaenger_plz': beleg.empfaenger_plz,
                'empfaenger_ort': beleg.empfaenger_ort,
                'empfaenger_land': beleg.empfaenger_land,
                'leitweg_id': '', 'bestellnummer': '',
                'positionen-TOTAL_FORMS': '1', 'positionen-INITIAL_FORMS': '1',
                'positionen-MIN_NUM_FORMS': '0',
                'positionen-MAX_NUM_FORMS': '1000',
                'positionen-0-id': str(position.pk),
                'positionen-0-katalog': '',
                'positionen-0-position': str(position.position),
                'positionen-0-bezeichnung': 'Montage, überarbeitet',
                'positionen-0-langtext': '',
                'positionen-0-menge': '12',
                'positionen-0-einheit': position.einheit or 'Stk',
                'positionen-0-einzelpreis': '100.00',
                'positionen-0-steuersatz': position.steuersatz,
                '_continue': 'Sichern und weiter bearbeiten',
            },
        )

        assert antwort.status_code == 302, 'Das Formular kam zurück statt zu speichern'
        beleg.refresh_from_db()
        position.refresh_from_db()
        assert beleg.betreff == 'Halle Nord, zweiter Anlauf'
        assert position.bezeichnung == 'Montage, überarbeitet'
        assert position.menge == Decimal('12')
        assert beleg.nummer is not None

    def test_beim_auftrag_warnt_der_dialog_vor_der_erfassung(self, buero,
                                                              kunde):
        """Der Dialog am Auftrag weist darauf hin, dass seine Positionen in der
        Erfassung fehlen, solange er offen ist.

        Gewolltes Verhalten
        (``erfassung.tests.test_admin.TestEinOffenerAuftragIstNichtBebuchbar``);
        der Hinweis steht dort, wo es ausgelöst wird.
        """
        auftrag = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.AUFTRAG,
                                         betreff='Halle Nord')
        services.position_hinzufuegen(
            beleg=auftrag, bezeichnung='Montage', menge=Decimal('1'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00')
        services.beleg_festschreiben(beleg_id=auftrag.pk)

        inhalt = buero.get(
            reverse('admin:faktura_auftrag_detail_wiedereroeffnen',
                    args=[auftrag.pk])).content.decode()

        assert 'Stunden darauf kontieren' in inhalt

    def test_der_vermerk_steht_im_statusreiter(self, buero, angebot):
        """Der Vermerk steht nur im Tab "Status", nicht in der Liste."""
        services.beleg_festschreiben(beleg_id=angebot.pk)
        services.beleg_wiedereroeffnen(beleg_id=angebot.pk)

        assert 'Zuletzt wieder geöffnet am' in self._maske(buero, angebot)

    def test_die_liste_zeigt_ein_schloss_oder_nichts(self, buero, angebot):
        liste = reverse('admin:faktura_angebot_changelist')

        assert '>lock<' not in buero.get(liste).content.decode()

        services.beleg_festschreiben(beleg_id=angebot.pk)

        assert '>lock<' in buero.get(liste).content.decode()

    def test_die_liste_schweigt_ueber_den_wiedereroeffneten(self, buero, angebot):
        """Ein wiedereröffneter Beleg erscheint in der Liste wie ein Entwurf,
        ohne Schloss und Vermerk; die Liste kennt zwei Zustände."""
        services.beleg_festschreiben(beleg_id=angebot.pk)
        services.beleg_wiedereroeffnen(beleg_id=angebot.pk)

        inhalt = buero.get(
            reverse('admin:faktura_angebot_changelist')).content.decode()

        assert '>lock<' not in inhalt
        assert 'Fassung' not in inhalt

    def test_ohne_recht_kein_knopf(self, rf, db, kunde):
        """Ohne ``beleg_wiedereroeffnen`` kein Button, auch mit ``change``."""
        from django.contrib.admin.sites import site
        from django.contrib.auth.models import Permission

        from faktura.models import Angebot

        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Montage', menge=Decimal('1'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00')
        services.beleg_festschreiben(beleg_id=beleg.pk)

        nur_schreiben = User.objects.create_user(
            username='ohne-oeffnen', password='x', is_staff=True)
        nur_schreiben.user_permissions.add(
            Permission.objects.get(codename='change_beleg'),
            Permission.objects.get(codename='view_beleg'),
        )
        anfrage = rf.get('/')
        anfrage.user = User.objects.get(pk=nur_schreiben.pk)

        sichtbar = [a.action_name for a in
                    site.get_model_admin(Angebot).get_actions_detail(
                        anfrage, beleg.pk)]

        assert 'detail_wiedereroeffnen' not in sichtbar
