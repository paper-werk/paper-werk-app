"""Admin der Belege: Liste, Aktionen und Änderungsprotokoll."""

from decimal import Decimal

import pytest
from django.contrib import admin
from django.urls import reverse
from django.utils import timezone

from faktura import services
from faktura.models import (
    Angebot,
    Auftrag,
    BelegStatus,
    BelegTyp,
    Lieferschein,
    Mahnung,
    Rechnung,
    Stornorechnung,
)


@pytest.mark.django_db
class TestBelegAdmin:
    def test_liste_laedt(self, buero, rechnungsentwurf):
        antwort = buero.get(reverse('admin:faktura_rechnung_changelist'))

        assert antwort.status_code == 200

    def test_entwurf_zeigt_bearbeitbares_formular(self, buero, rechnungsentwurf):
        antwort = buero.get(
            reverse('admin:faktura_rechnung_change', args=[rechnungsentwurf.pk])
        )

        assert antwort.status_code == 200
        readonly = antwort.context['adminform'].readonly_fields
        assert 'betreff' not in readonly

    def test_festgeschriebener_beleg_ist_komplett_schreibgeschuetzt(
        self, buero, rechnungsentwurf
    ):
        """Alle Felder eines festgeschriebenen Belegs sind readonly."""
        services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)

        antwort = buero.get(
            reverse('admin:faktura_rechnung_change', args=[rechnungsentwurf.pk])
        )

        readonly = antwort.context['adminform'].readonly_fields
        for feld in ['betreff', 'empfaenger', 'leistungsdatum']:
            assert feld in readonly, f'{feld} müsste gesperrt sein'

    def test_belegart_taucht_im_formular_nicht_auf(self, buero, rechnungsentwurf):
        """Die Belegart ist kein Formularfeld.

        Sie folgt aus dem Menüpunkt und wird in save_model() gesetzt; als
        Auswahlfeld ließe sie sich widersprüchlich setzen.
        """
        antwort = buero.get(
            reverse('admin:faktura_rechnung_change', args=[rechnungsentwurf.pk])
        )

        assert 'name="typ"' not in antwort.content.decode()

    def test_festgeschriebener_beleg_zeigt_keine_speichern_schaltflaechen(
        self, buero, rechnungsentwurf
    ):
        """Ohne Buttons zum Speichern am festgeschriebenen Beleg.

        Die Buttons hängen an has_change_permission(), nicht an
        readonly_fields; sonst blieben sie sichtbar, und ein Klick endete auf
        der Fehlerseite.
        """
        services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)

        antwort = buero.get(
            reverse('admin:faktura_rechnung_change', args=[rechnungsentwurf.pk])
        )
        inhalt = antwort.content.decode()

        assert antwort.status_code == 200
        assert 'name="_save"' not in inhalt
        assert 'name="_continue"' not in inhalt
        assert 'name="_addanother"' not in inhalt

    def test_post_auf_festgeschriebenen_beleg_wird_sauber_abgewiesen(
        self, buero, rechnungsentwurf
    ):
        """Ein manueller POST auf einen festgeschriebenen Beleg löst keine
        Exception aus."""
        services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)

        antwort = buero.post(
            reverse('admin:faktura_rechnung_change', args=[rechnungsentwurf.pk]),
            {'betreff': 'Nachträglich geändert', 'typ': BelegTyp.RECHNUNG},
        )

        # Kein 500 und kein 403: Redirect auf die Read-only-Ansicht mit
        # Warnung (BelegAdmin.changeform_view, faktura/tests/test_gleichzeitig.py).
        assert antwort.status_code == 302
        assert antwort.url == reverse('admin:faktura_rechnung_change',
                                      args=[rechnungsentwurf.pk])
        rechnungsentwurf.refresh_from_db()
        assert rechnungsentwurf.betreff == 'Leistungen'

    def test_entwurf_behaelt_seine_schaltflaechen(self, buero, rechnungsentwurf):
        """Gegenprobe: Ein Entwurf behält die Buttons."""
        antwort = buero.get(
            reverse('admin:faktura_rechnung_change', args=[rechnungsentwurf.pk])
        )

        assert 'name="_save"' in antwort.content.decode()


@pytest.mark.django_db
class TestAdminAktionen:
    def _aktion(self, client, aktion, belege):
        return client.post(
            reverse('admin:faktura_rechnung_changelist'),
            {'action': aktion, '_selected_action': [str(b.pk) for b in belege]},
            follow=True,
        )

    def test_festschreiben_ueber_die_aktion(self, buero, rechnungsentwurf):
        antwort = self._aktion(buero, 'action_festschreiben', [rechnungsentwurf])

        rechnungsentwurf.refresh_from_db()
        assert antwort.status_code == 200
        assert rechnungsentwurf.status == BelegStatus.FESTGESCHRIEBEN
        assert rechnungsentwurf.nummer is not None

    def test_festschreiben_ohne_leistungsdatum_meldet_den_grund(self, buero, kunde):
        """Ein fachlicher Fehler erscheint als Meldung, nicht als 500."""
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='X', menge=Decimal('1'),
            einzelpreis=Decimal('10.00'), steuersatz='19.00',
        )

        antwort = self._aktion(buero, 'action_festschreiben', [beleg])

        assert antwort.status_code == 200
        beleg.refresh_from_db()
        assert beleg.status == BelegStatus.ENTWURF
        meldungen = [str(m) for m in antwort.context['messages']]
        assert any('Leistungsdatum' in m for m in meldungen)

    def test_nachlass_zeigt_zuerst_ein_formular(self, buero, rechnungsentwurf):
        """Aktionen mit Eingaben zeigen zuerst eine Zwischenseite."""
        original = services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)

        antwort = self._aktion(buero, 'action_nachlass', [original])

        assert antwort.status_code == 200
        assert 'Rechnungskorrektur erstellen' in antwort.content.decode()
        # Noch kein Beleg, nur das Formular.
        assert not original.nachfolger.exists()

    def test_nachlass_wird_nach_dem_abschicken_angelegt(self, buero, rechnungsentwurf):
        original = services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)

        buero.post(
            reverse('admin:faktura_rechnung_changelist'),
            {
                'action': 'action_nachlass',
                '_selected_action': [str(original.pk)],
                'anwenden': '1',
                'betrag_netto': '250,00',       # deutsche Schreibweise
                'grund': 'Nachlass wegen Reklamation',
                'steuersatz': '19.00',
            },
            follow=True,
        )

        korrektur = original.nachfolger.get(typ=BelegTyp.GUTSCHRIFT)
        assert services.belegsummen(korrektur).brutto == Decimal('-297.50')
        # Die Ausgangsrechnung bleibt bestehen, anders als beim Storno.
        original.refresh_from_db()
        assert original.status == BelegStatus.FESTGESCHRIEBEN

    def test_nachlass_auf_entwurf_zeigt_erst_gar_kein_formular(
        self, buero, rechnungsentwurf
    ):
        """Die Voraussetzung wird vor dem Formular geprüft.

        Regression: Die Meldung, dass ein Entwurf ausgeschlossen ist, kam
        erst nach Eingabe von Betrag und Grund.
        """
        antwort = self._aktion(buero, 'action_nachlass', [rechnungsentwurf])

        inhalt = antwort.content.decode()
        assert 'Rechnungskorrektur erstellen' not in inhalt
        assert 'betrag_netto' not in inhalt

        meldungen = [str(m) for m in antwort.context['messages']]
        assert any('festgeschriebene' in m and 'Entwurf' in m for m in meldungen)

    def test_nachlass_nur_fuer_eine_einzelne_rechnung(
        self, buero, kunde, rechnungsentwurf
    ):
        """Nachlass nur für genau eine Rechnung.

        Eine Mehrfachauswahl wird vor jeder Änderung abgelehnt, weil derselbe
        Nachlass auf mehreren Rechnungen fachlich kaum vorkommt und mehrere
        Belege erzeugte.
        """
        erste = services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)
        zweite = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Zweiter Vorgang',
            leistungsdatum=timezone.localdate(),
        )
        services.position_hinzufuegen(
            beleg=zweite, bezeichnung='Montage', menge=Decimal('2'),
            einzelpreis=Decimal('50.00'), steuersatz='19.00',
        )
        zweite = services.beleg_festschreiben(beleg_id=zweite.pk)

        antwort = self._aktion(buero, 'action_nachlass', [erste, zweite])

        assert 'Rechnungskorrektur erstellen' not in antwort.content.decode()
        meldungen = [str(m) for m in antwort.context['messages']]
        assert any('einzelne Rechnung' in m for m in meldungen)
        assert not erste.nachfolger.exists()
        assert not zweite.nachfolger.exists()

    def test_mahnen_ueber_die_aktion(self, buero, rechnungsentwurf, ueberfaellig):
        original = ueberfaellig(rechnungsentwurf)

        self._aktion(buero, 'action_mahnen', [original])

        mahnung = original.nachfolger.get(typ=BelegTyp.MAHNUNG)
        assert mahnung.mahnstufe == 1

    def test_mahnstufe_steigt_mit_jeder_mahnung(
        self, buero, rechnungsentwurf, ueberfaellig
    ):
        """Die Mahnstufe ergibt sich aus den bisherigen Mahnungen."""
        original = ueberfaellig(rechnungsentwurf)

        self._aktion(buero, 'action_mahnen', [original])
        self._aktion(buero, 'action_mahnen', [original])

        stufen = sorted(
            original.nachfolger.filter(typ=BelegTyp.MAHNUNG)
            .values_list('mahnstufe', flat=True)
        )
        assert stufen == [1, 2]

    def test_korrigieren_ueber_die_aktion(self, buero, rechnungsentwurf):
        original = services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)

        antwort = self._aktion(buero, 'action_korrigieren', [original])

        original.refresh_from_db()
        assert antwort.status_code == 200
        assert original.status == BelegStatus.STORNIERT
        assert original.nachfolger.filter(typ=BelegTyp.STORNO).exists()
        assert original.nachfolger.filter(typ=BelegTyp.RECHNUNG).exists()


@pytest.mark.django_db
class TestAktionenImAenderungsprotokoll:
    """Festschreiben und Stornieren erscheinen im Verlauf.

    Django schreibt LogEntry nur für Formulare, nicht für Aktionen. Ohne
    expliziten Eintrag fehlte im Verlauf, wer eine Rechnung festgeschrieben
    hat.
    """

    def _aktion(self, client, aktion, belege):
        return client.post(
            reverse('admin:faktura_rechnung_changelist'),
            {'action': aktion, '_selected_action': [str(b.pk) for b in belege]},
            follow=True,
        )

    def _protokoll(self, beleg):
        """Einträge, die der Verlauf der Rechnung zeigt.

        Gefiltert über den ContentType des **Proxy-Modells**, wie Djangos
        history_view (get_for_model mit for_concrete_model=False). Ein
        Eintrag am Basismodell Beleg stünde in der Datenbank, erschiene
        aber nicht im Verlauf der Rechnung.
        """
        from django.contrib.admin.models import LogEntry
        from django.contrib.contenttypes.models import ContentType

        from faktura.models import Rechnung

        inhaltstyp = ContentType.objects.get_for_model(
            Rechnung, for_concrete_model=False
        )
        return LogEntry.objects.filter(
            content_type=inhaltstyp, object_id=str(beleg.pk)
        )

    def test_festschreiben_vermerkt_den_benutzer_am_beleg(
        self, buero, rechnungsentwurf
    ):
        self._aktion(buero, 'action_festschreiben', [rechnungsentwurf])

        rechnungsentwurf.refresh_from_db()
        assert rechnungsentwurf.festgeschrieben_von.username == 'sekretariat'

    def test_festschreiben_steht_im_verlauf(self, buero, rechnungsentwurf):
        self._aktion(buero, 'action_festschreiben', [rechnungsentwurf])

        rechnungsentwurf.refresh_from_db()
        eintraege = self._protokoll(rechnungsentwurf)
        assert eintraege.count() == 1
        eintrag = eintraege.get()
        assert eintrag.user.username == 'sekretariat'
        assert rechnungsentwurf.nummer in eintrag.get_change_message()

    def test_stornieren_steht_im_verlauf_des_originals(
        self, buero, rechnungsentwurf
    ):
        original = services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)

        self._aktion(buero, 'action_korrigieren', [original])

        meldungen = [e.get_change_message() for e in self._protokoll(original)]
        assert any('Storniert' in m for m in meldungen)

    def test_abgelehnte_festschreibung_hinterlaesst_keinen_eintrag(
        self, buero, kunde
    ):
        """Eine abgelehnte Festschreibung erzeugt keinen LogEntry."""
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='X', menge=Decimal('1'),
            einzelpreis=Decimal('10.00'), steuersatz='19.00',
        )

        # Ohne Leistungsdatum lehnt der Service ab.
        self._aktion(buero, 'action_festschreiben', [beleg])

        assert not self._protokoll(beleg).exists()


class TestAktionenStehenWoSieHingehoeren:
    """Die Aktion "in Rechnung umwandeln" erscheint nur an Angebot, Auftrag
    und Lieferschein.

    Die Methode liegt in der Basisklasse und wird von allen Belegarten
    geerbt; die Einschränkung beruht allein auf ``actions``.
    """

    @pytest.mark.parametrize('modell', [Angebot, Auftrag, Lieferschein])
    def test_wo_eine_rechnung_daraus_werden_kann(self, modell):
        assert 'action_in_rechnung' in admin.site._registry[modell].actions

    @pytest.mark.parametrize('modell', [Rechnung, Stornorechnung, Mahnung])
    def test_und_wo_nicht(self, modell):
        """Rechnung und Mahnung haben die geerbte Aktion nicht."""
        assert 'action_in_rechnung' not in (admin.site._registry[modell].actions or [])


class TestDieMixinReihenfolge:
    """MRO der Mixins von ``BelegAdmin``.

    Umsortierte Basisklassen oder eine Methode in zwei Mixins ändern das
    Verhalten ohne Fehlermeldung.
    """

    @staticmethod
    def _eigene_mixins():
        from faktura.admin import beleg

        return [k for k in beleg.BelegAdmin.__mro__
                if k.__module__.startswith('faktura.admin.')
                and k.__name__.endswith('Mixin')]

    def test_die_eigenen_mixins_stehen_vor_dem_modeladmin(self):
        """Die eigenen Mixins stehen in der MRO vor ``ModelAdmin``.

        ``BelegAdmin.media`` ruft ``super().media``, das über
        ``AktionNachDemSichern`` ``aktion_erst_speichern.js`` hinzufügt.
        Stünde ein Mixin nach ``ModelAdmin``, fehlte sein Beitrag ohne
        Fehler.
        """
        from unfold import admin as unfold_admin

        from faktura.admin import BelegAdmin
        from faktura.admin.gemeinsam import AktionNachDemSichern

        mro = list(BelegAdmin.__mro__)
        grenze = mro.index(AktionNachDemSichern)

        for mixin in self._eigene_mixins():
            assert mro.index(mixin) < grenze, (
                f'{mixin.__name__} steht hinter AktionNachDemSichern'
            )
        assert grenze < mro.index(unfold_admin.ModelAdmin)

    def test_kein_mixin_ueberschreibt_ein_anderes(self):
        """Kein Mixin definiert eine Methode eines anderen, weil sonst die MRO
        ohne Fehler eines davon wählt."""
        gesehen = {}
        doppelt = []

        for mixin in self._eigene_mixins():
            for name in vars(mixin):
                if name.startswith('__'):
                    continue
                if name in gesehen:
                    doppelt.append(f'{name}: {gesehen[name]} und {mixin.__name__}')
                gesehen[name] = mixin.__name__

        assert not doppelt, 'mehrfach definiert; ' + '; '.join(doppelt)

    def test_jedes_mixin_traegt_etwas_bei(self):
        """Jedes Mixin definiert mindestens ein Attribut oder eine Methode."""
        for mixin in self._eigene_mixins():
            eigene = [n for n in vars(mixin) if not n.startswith('__')]
            assert eigene, f'{mixin.__name__} ist leer'
