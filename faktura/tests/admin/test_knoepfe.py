"""Knöpfe und Aktionen in der Belegmaske."""

import re
from decimal import Decimal

import pytest
from django.contrib import admin
from django.forms import Script
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from faktura import services
from faktura.models import (
    Angebot,
    Auftrag,
    BelegStatus,
    BelegTyp,
    Rechnung,
)
from faktura.tests.admin.hilfen import User


@pytest.mark.django_db
class TestAktionenImBeleg:
    """Detailaktionen im geöffneten Beleg.

    Ersetzen den Weg über die Liste (Auswahl, Aktion, "Ausführen"). Die
    Listenaktionen bleiben für Massenoperationen; die Detailaktion ruft die
    Listenaktion auf (BelegAdmin._als_detailaktion).
    """

    @pytest.fixture
    def angebotsentwurf(self, kunde):
        """Angebotsentwurf für Tests des Festschreibens.

        Die Rechnung hat kein ``detail_festschreiben``, siehe Kommentar
        weiter unten.
        """
        beleg = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.ANGEBOT, betreff='Halle Nord',
            leistungsdatum=timezone.localdate(),
        )
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Beratung', menge=Decimal('10'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00',
        )
        return beleg

    def _maske(self, buero, beleg):
        return buero.get(reverse('admin:faktura_rechnung_change',
                                 args=[beleg.pk])).content.decode()

    def test_am_entwurf_steht_das_versenden(self, buero, rechnungsentwurf):
        """Am Entwurf nur "Versenden".

        Mahnen, Nachlass und Stornieren setzen eine festgeschriebene
        Rechnung voraus; der Service lehnte sie am Entwurf ab, deshalb keine
        Buttons dafür. "Versenden" schließt das Festschreiben ein.
        """
        inhalt = self._maske(buero, rechnungsentwurf)

        assert 'Versenden' in inhalt
        for spaeter in ('Mahnung erzeugen', 'Nachlass gewähren',
                        'Stornieren und neu schreiben'):
            assert spaeter not in inhalt, spaeter

    def test_an_der_festgeschriebenen_rechnung_stehen_die_nachgelagerten(
        self, buero, rechnungsentwurf
    ):
        """An der festgeschriebenen Rechnung erscheinen Mahnen, Nachlass und
        Stornieren.

        Mit eigenem Recht, weil ``has_change_permission`` am
        festgeschriebenen Beleg False liefert und die Buttons mit ``change``
        nie sichtbar wären (BelegAdmin.has_nachgelagert_permission).
        """
        services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)

        inhalt = self._maske(buero, rechnungsentwurf)

        for jetzt in ('Mahnung erzeugen', 'Nachlass gewähren',
                      'Stornieren und neu schreiben'):
            assert jetzt in inhalt, jetzt
        # Kein zweites Festschreiben.
        assert 'Festschreiben' not in inhalt

    # ``detail_versenden`` schließt das Festschreiben ein und steht an jeder
    # Belegart. Die Regel, dass ein GET nichts festschreibt, prüft der erste
    # Test unten; die Versandmaske prüft test_versand.py.

    def test_der_aufruf_der_versandmaske_schreibt_nichts_fest(
        self, buero, angebotsentwurf
    ):
        """Der GET auf die Versandmaske schreibt nicht fest.

        Eine Detailaktion ist ein Link, also ein GET. Schriebe er fest,
        genügte ein versehentlicher Klick oder Link-Prefetching des
        Browsers. Der GET zeigt nur die Maske; erst der POST schreibt
        fest.
        """
        antwort = buero.get(reverse(
            'admin:faktura_angebot_detail_versenden',
            args=[angebotsentwurf.pk]))

        angebotsentwurf.refresh_from_db()

        assert antwort.status_code == 200
        assert angebotsentwurf.status == BelegStatus.ENTWURF
        assert angebotsentwurf.nummer is None

    def test_jede_belegart_kann_versenden(self, buero, angebotsentwurf):
        """Alle neun Belegarten haben "Versenden", weil der Textbaustein für
        das Anschreiben eine Belegart hat."""
        inhalt = buero.get(reverse('admin:faktura_angebot_change',
                                   args=[angebotsentwurf.pk])).content.decode()

        assert 'versenden/' in inhalt

    def test_am_festgeschriebenen_beleg_fehlt_der_knopf(self, buero,
                                                        rechnungsentwurf):
        """Am festgeschriebenen Beleg fehlt der Button, weil
        ``has_change_permission`` dort False liefert."""
        services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)

        inhalt = buero.get(reverse(
            'admin:faktura_rechnung_change',
            args=[rechnungsentwurf.pk])).content.decode()

        assert 'Festschreiben' not in inhalt

    def test_die_rechtepruefung_vertraegt_eine_kennung(self, buero,
                                                       rechnungsentwurf):
        """``has_change_permission`` akzeptiert Objekt und ID.

        Django übergibt ein Modellobjekt, Unfold bei Detailaktionen die
        **ID** als String aus der URL. Regression: ``obj.ist_aenderbar``
        warf ``AttributeError: 'str' object has no attribute
        'ist_aenderbar'``, und jede Belegmaske schlug fehl.

        Geprüft werden die Methode mit einer ID und die Maske.
        """
        admin_klasse = admin.site.get_model_admin(Rechnung)
        anfrage = RequestFactory().get('/')
        anfrage.user = User.objects.get(username='sekretariat')

        # Mit ID, wie Unfold.
        assert admin_klasse.has_change_permission(
            anfrage, str(rechnungsentwurf.pk)) is True

        # Mit Objekt, wie Django.
        assert admin_klasse.has_change_permission(
            anfrage, rechnungsentwurf) is True

        antwort = buero.get(reverse('admin:faktura_rechnung_change',
                                    args=[rechnungsentwurf.pk]))
        assert antwort.status_code == 200

    def test_eine_kennung_ohne_beleg_ergibt_keinen_absturz(self, buero):
        """Eine ID ohne Beleg (manuell eingegebene URL) löst keine Exception
        aus."""
        admin_klasse = admin.site.get_model_admin(Rechnung)
        anfrage = RequestFactory().get('/')
        anfrage.user = User.objects.get(username='sekretariat')

        assert admin_klasse.has_change_permission(anfrage, '999999') is True

    def test_der_nachlass_fuehrt_auf_seine_zwischenseite(self, buero,
                                                         rechnungsentwurf):
        """Die Detailaktion Nachlass führt auf die Zwischenseite für Betrag und
        Grund."""
        services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)

        antwort = buero.get(reverse('admin:faktura_rechnung_detail_nachlass',
                                    args=[rechnungsentwurf.pk]))

        assert antwort.status_code == 200
        assert 'Rechnungskorrektur erstellen' in antwort.content.decode()


@pytest.mark.django_db
class TestKnopfUndAuslieferung:
    """Layout des Buttons und Auslieferung der statischen Dateien.

    Regressionen, beide im HTML nachweisbar:

    1. Der Button stand rechts neben dem Textfeld, weil der Admin jedes Feld
       in einen Flex-Container ohne Umbruch setzt und alles nach dem Feld
       in dieselbe Zeile gerät.
    2. Der Klick hatte keine Wirkung, weil der Browser eine ältere Version
       des Skripts mit unverändertem Namen und URL aus dem Cache verwendete.
    """

    def test_feld_und_knopf_stehen_in_einem_eigenen_rahmen(self, buero,
                                                           bausteine):
        """Feld und Button stehen in einem eigenen Container.

        Geprüft wird die Reihenfolge: Container, Button, Feld. Der Button
        steht über dem Feld in der Zeile des Labels.
        """
        inhalt = buero.get(reverse('admin:faktura_angebot_add')).content.decode()

        rahmen = inhalt.index('class="textvorlagen-feld"')
        knopf = inhalt.index('Textvorlagen', rahmen)
        feld = inhalt.index('id="id_kopftext"', rahmen)

        assert rahmen < knopf < feld

    def test_der_knopf_traegt_die_knopfklassen_der_oberflaeche(self, buero,
                                                              bausteine):
        """Der Button verwendet die Klassen von Unfold, ohne eigenes CSS.

        Die Klassenliste stammt aus ``unfold/components/button.html``,
        Variante "default" (Begründung im Widget). Geprüft werden drei
        kennzeichnende Klassen, damit der Test bei Unfold-Updates nicht ohne
        Fehler am Button fehlschlägt.
        """
        inhalt = buero.get(reverse('admin:faktura_angebot_add')).content.decode()

        stelle = inhalt.index('Textvorlagen')
        anfang = inhalt.rindex('<button', 0, stelle)
        knopf = inhalt[anfang:stelle]

        for klasse in ('rounded-default', 'border-base-200', 'bg-white'):
            assert klasse in knopf, f'{klasse} fehlt: {knopf}'

    def test_der_knopf_heisst_wie_der_anwender_ihn_nennt(self, buero,
                                                        bausteine):
        """Der Button heißt "Textvorlagen"; das Modell heißt Textbaustein."""
        inhalt = buero.get(reverse('admin:faktura_angebot_add')).content.decode()

        anfang = inhalt.index('class="textvorlagen-feld"')
        ende = inhalt.index('id="id_kopftext"', anfang)

        assert 'Textvorlagen' in inhalt[anfang:ende]
        assert 'Textbaustein' not in inhalt[anfang:ende]

    def test_das_eigene_stilblatt_wird_ausgeliefert(self, buero):
        """Das eigene Stylesheet wird ausgeliefert, weil der Container allein
        den Button nicht über dem Feld anordnet."""
        inhalt = buero.get(reverse('admin:faktura_angebot_add')).content.decode()

        assert 'faktura/css/faktura_admin.css' in inhalt

    # --- Auslieferung ---

    def test_eigene_dateien_tragen_ihren_stand(self, buero):
        """Eigene statische Dateien haben einen Cache-Buster.

        Sie ändern den Inhalt bei gleichem Namen; ohne Cache-Buster
        verwendet der Browser die gecachte Version ohne Revalidierung.
        """
        import re

        inhalt = buero.get(reverse('admin:faktura_angebot_add')).content.decode()

        eigene = re.findall(r'(?:src|href)="(/static/faktura/[^"]+)"', inhalt)
        assert eigene, 'keine eigene Datei im HTML'

        ohne_stand = [d for d in eigene if '?stand=' not in d]
        assert not ohne_stand, f'ohne Versionsangabe: {ohne_stand}'

    def test_der_stand_folgt_der_datei(self, tmp_path):
        """Der Cache-Buster ist der Änderungszeitpunkt der Datei, damit sich die
        URL genau mit der Datei ändert."""
        import os

        from django.contrib.staticfiles import finders

        from core.adminhilfen import mit_stand

        pfad = 'faktura/js/textbaustein_einfuegen.js'
        datei = finders.find(pfad)

        assert mit_stand(pfad).endswith(f'?stand={int(os.path.getmtime(datei))}')

    def test_djangos_eigene_dateien_bleiben_unangetastet(self):
        """Dateien von Django erhalten keinen Cache-Buster, weil sie sich nur
        mit der Django-Version ändern und ihre Pfade von DEBUG abhängen."""
        modeladmin = admin.site._registry[Angebot]

        pfade = [d.path for d in modeladmin.media._js]
        admin_dateien = [p for p in pfade if '/admin/js/' in p]

        assert admin_dateien
        assert all('?stand=' not in p for p in admin_dateien), admin_dateien

    def test_der_skriptverweis_bringt_seinen_stand_mit(self):
        """Der Cache-Buster übersteht ``static()`` in ``forms.Script``.

        ``forms.Script`` (Django 6) lässt Pfade mit führendem ``/``
        unverändert. Darauf beruht der Verzicht auf die eigene Klasse
        ``SkriptMitStand``; ginge der Query-String verloren, erreichte eine
        geänderte Datei den Browser nicht.
        """
        from core.adminhilfen import skript_mit_stand

        eintrag = skript_mit_stand('faktura/js/kunde_uebernehmen.js')

        assert isinstance(eintrag, Script)
        assert '?stand=' in eintrag.path
        assert eintrag.path.startswith('/static/faktura/js/')

    def test_zwei_verweise_auf_dieselbe_datei_zaehlen_als_einer(self):
        """Zwei Script-Objekte für dieselbe Datei werden dedupliziert.

        Sichert ab, dass ``MediaAsset`` ``__eq__`` und ``__hash__``
        implementiert; sonst stünde das Skript zweimal in der Seite.
        """
        from django.forms import Media

        from core.adminhilfen import skript_mit_stand

        pfad = 'faktura/js/kunde_uebernehmen.js'
        zusammen = Media(js=[skript_mit_stand(pfad)]) + Media(js=[skript_mit_stand(pfad)])

        assert len(zusammen._js) == 1


class TestKeinSkriptSchweigt:
    """Jeder ``catch`` in den eigenen Skripten protokolliert den Fehler.

    Regression: Alle drei Skripte hatten einen leeren ``catch``; ein Fehler
    blieb im Browser ohne Meldung und ohne Wirkung. Protokolliert wird in
    die Konsole, damit der Benutzer ohne Dialog weiterarbeiten kann.

    Verworfen: ein Test auf den Kommentartext im Quelltext, weil er an das
    Vorhandensein von ``console.`` gekoppelt war und nicht fehlschlagen
    konnte.
    """

    @staticmethod
    def _skripte():
        from pathlib import Path

        from django.contrib.staticfiles import finders

        for name in ('kunde_uebernehmen.js', 'katalog_uebernehmen.js',
                     'textbaustein_einfuegen.js'):
            pfad = finders.find(f'faktura/js/{name}')
            assert pfad, f'{name} nicht gefunden'
            yield name, Path(pfad).read_text(encoding='utf-8')

    def test_kein_catch_bleibt_stumm(self):
        """Jeder ``catch`` gibt den Fehler in der Konsole aus."""
        import re

        stumm = []
        for name, inhalt in self._skripte():
            for treffer in re.finditer(r'\.catch\(function[^)]*\)\s*\{', inhalt):
                # Block bis zur schließenden Klammer derselben Ebene.
                rest = inhalt[treffer.end():]
                rumpf = rest[:rest.index('});')]
                if 'console.' not in rumpf:
                    stumm.append(f'{name}: {rumpf.strip()[:60]}')

        assert not stumm, 'schluckt Fehler: ' + '; '.join(stumm)


@pytest.mark.django_db
class TestDerPdfKnopfAmBeleg:
    """Button "PDF" in der Kopfleiste des Belegs.

    Der Link im Tab "Status" neben Prüfsumme und Archivverweis bleibt für
    den Nachweis; für den Aufruf aus dem Beleg genügte er nicht, weil er
    schwer auffindbar war.
    """

    def test_jede_belegart_hat_den_knopf(self, rf, admin_user):
        """Jede registrierte Belegart hat den Button.

        ``actions_detail`` ist ein Klassenattribut, das eine Unterklasse
        vollständig ersetzt; ein geerbter Eintrag fiele ohne Fehler weg.
        Regression: Beim Auftrag fehlte er.
        """
        from django.contrib.admin.sites import site

        from faktura.models import BelegTyp, proxy_fuer

        anfrage = rf.get('/')
        anfrage.user = admin_user

        for typ in BelegTyp.values:
            modell = proxy_fuer(typ)
            if modell not in site._registry:
                continue
            namen = site.get_model_admin(modell)._extract_action_names(
                site.get_model_admin(modell).actions_detail)
            assert 'detail_pdf' in namen, (
                f'{modell.__name__} hat keinen PDF-Knopf in der Detailansicht')

    def test_der_knopf_liefert_das_dokument(self, buero, rechnungsentwurf,
                                            settings, tmp_path, mit_pdf):
        """Der Button liefert ``application/pdf``."""
        settings.MEDIA_ROOT = tmp_path
        beleg = services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)

        # Unfold bildet den URL-Namen aus dem Methodennamen
        # (app_model_<methode>); ``url_path`` bestimmt nur den Pfad.
        antwort = buero.get(reverse('admin:faktura_rechnung_detail_pdf',
                                    args=[beleg.pk]))

        assert antwort.status_code == 200
        assert antwort['Content-Type'] == 'application/pdf'

    def test_er_geht_in_einen_neuen_reiter(self):
        """``target="_blank"``, damit die Maske geöffnet bleibt."""
        from django.contrib.admin.sites import site

        from faktura.models import Rechnung

        aktion = site.get_model_admin(Rechnung).detail_pdf

        assert aktion.attrs == {'target': '_blank'}

    def test_ohne_leserecht_kein_knopf(self, rf, db):
        """Ohne View-Recht an der Belegart kein Button, weil das PDF alle
        Positionen und Preise enthält."""
        from django.contrib.admin.sites import site

        from faktura.models import Rechnung

        ohne_rechte = User.objects.create_user(
            username='ohne', password='x', is_staff=True)
        anfrage = rf.get('/')
        anfrage.user = ohne_rechte

        sichtbar = [a.action_name for a in
                    site.get_model_admin(Rechnung).get_actions_detail(
                        anfrage, 1)]

        assert 'detail_pdf' not in sichtbar


@pytest.mark.django_db
class TestErstSichernDannDieAktion:
    """Detailaktionen speichern zuerst das Formular.

    Jede Detailaktion ist ein Link; ohne vorheriges Speichern arbeitet sie
    mit dem gespeicherten Stand und verwirft die Eingaben. Beim Versenden
    erhielte der Kunde ein PDF ohne die Korrektur, und der Beleg wäre
    festgeschrieben. Aktionen mit Dialog laden ihn per htmx, ohne Warnung
    des Browsers. Regression: Änderungen gingen beim Festschreiben eines
    Angebots verloren.

    Geprüft wird der Server: ``_danach`` führt zur richtigen URL und öffnet
    nur Aktionen, die der Benutzer ausführen darf. Das Abfangen des Klicks
    (``aktion_erst_speichern.js``) läuft im Browser und ist hier nicht
    testbar.
    """

    def _adresse(self, beleg, pfad, benutzer, rf):
        from django.contrib.admin.sites import site

        from faktura.models import Angebot

        anfrage = rf.post('/', {'_danach': pfad})
        anfrage.user = benutzer
        verwaltung = site.get_model_admin(Angebot)
        return verwaltung._adresse_der_aktion(anfrage, beleg, pfad)

    @pytest.fixture
    def chefin(self, db):
        return User.objects.create_superuser(
            username='chefin', email='c@example.com', password='geheim12345')

    def test_das_wegstueck_wird_zur_adresse(self, angebot, chefin, rf):
        ziel = self._adresse(angebot, 'pdf-ansehen', chefin, rf)

        assert ziel == reverse('admin:faktura_angebot_detail_pdf',
                               args=[angebot.pk])

    def test_ein_unbekanntes_wegstueck_fuehrt_nirgendwohin(self, angebot,
                                                           chefin, rf):
        """Ein unbekannter Wert für ``_danach`` löst weder Exception noch
        Redirect auf die Aktion aus; der Beleg ist gespeichert, und
        ``_continue`` führt zurück auf ihn.
        """
        assert self._adresse(angebot, 'ausgedacht', chefin, rf) is None

    def test_keine_aktion_die_gerade_nicht_erlaubt_ist(self, angebot, chefin,
                                                       rf):
        """``_danach`` öffnet keine aktuell unzulässige Aktion.

        „Wieder öffnen" gibt es nur am festgeschriebenen Beleg. Geprüft wird
        gegen ``get_actions_detail``, dieselbe Liste, die die Buttons samt
        Rechten und Zustand bestimmt, damit keine zweite Liste nötig ist.
        """
        assert self._adresse(angebot, 'wieder-oeffnen', chefin, rf) is None

        services.beleg_festschreiben(beleg_id=angebot.pk)
        angebot.refresh_from_db()

        assert self._adresse(angebot, 'wieder-oeffnen', chefin, rf) is not None

    def test_gesichert_wird_und_dann_geht_es_weiter(self, buero, angebot):
        """Das Formular wird gespeichert, danach folgt der Redirect zur
        Aktion.
        """
        position = angebot.positionen.get()

        antwort = buero.post(
            reverse('admin:faktura_angebot_change', args=[angebot.pk]),
            {
                'kunde': str(angebot.kunde_id), 'projekt': '',
                'betreff': 'Kurz vor dem Klick geändert',
                'empfaenger': angebot.empfaenger, 'empfaenger_email': '',
                'empfaenger_ust_id': '',
                'belegdatum': (angebot.belegdatum
                               or timezone.localdate()).strftime('%d.%m.%Y'),
                'leistungsdatum': '', 'leistungsdatum_bis': '',
                'zahlungsziel_tage': str(angebot.zahlungsziel_tage),
                'kopftext': '', 'fusstext': '',
                'empfaenger_name': angebot.empfaenger_name,
                'empfaenger_strasse': angebot.empfaenger_strasse,
                'empfaenger_plz': angebot.empfaenger_plz,
                'empfaenger_ort': angebot.empfaenger_ort,
                'empfaenger_land': angebot.empfaenger_land,
                'leitweg_id': '', 'bestellnummer': '',
                'positionen-TOTAL_FORMS': '1', 'positionen-INITIAL_FORMS': '1',
                'positionen-MIN_NUM_FORMS': '0',
                'positionen-MAX_NUM_FORMS': '1000',
                'positionen-0-id': str(position.pk),
                'positionen-0-katalog': '',
                'positionen-0-position': str(position.position),
                'positionen-0-bezeichnung': position.bezeichnung,
                'positionen-0-langtext': '',
                'positionen-0-menge': '10',
                'positionen-0-einheit': position.einheit or 'Stk',
                'positionen-0-einzelpreis': '100.00',
                'positionen-0-steuersatz': position.steuersatz,
                '_danach': 'pdf-ansehen',
                '_continue': '1',
            },
        )

        angebot.refresh_from_db()
        assert angebot.betreff == 'Kurz vor dem Klick geändert'
        assert antwort.status_code == 302
        assert antwort['Location'] == reverse(
            'admin:faktura_angebot_detail_pdf', args=[angebot.pk])

    def test_das_skript_liegt_in_der_maske_und_wartet_auf_die_seite(
        self, buero, angebot
    ):
        """Das Skript ist in der Maske eingebunden und hat ``defer``.

        Django bindet Media im ``<head>`` ein. Regression: Ohne ``defer``
        lief das Skript vor dem Formular, ``querySelector`` fand nichts, und
        es endete ohne Fehler und ohne Wirkung.
        """
        inhalt = buero.get(
            reverse('admin:faktura_angebot_change',
                    args=[angebot.pk])).content.decode()

        treffer = re.search(
            r'<script[^>]*aktion_erst_speichern\.js[^>]*>', inhalt)

        assert treffer is not None, 'Skript fehlt in der Maske'
        assert 'defer' in treffer.group(0)

    def test_der_sicherungsknopf_ist_dem_formular_zugeordnet(self, buero,
                                                             angebot):
        """Der Button zum Speichern ist dem Formular zugeordnet.

        Unfold rendert die Leiste zum Speichern sticky am unteren Rand,
        *außerhalb* des ``<form>``, verbunden über das HTML5-Attribut
        ``form="angebot_form"``:

            <button type="submit" form="angebot_form" name="_save" ...>

        Daran erkennt das Skript, ob die Maske beschreibbar ist (ein
        festgeschriebener Beleg hat diesen Button nicht). Regression: Es
        suchte nur innerhalb des Formulars und beendete sich jedes Mal ohne
        Fehler.

        Der Test lässt beide Varianten zu: Button im Formular oder über
        ``form=`` zugeordnet; ohne Zuordnung schlägt er fehl.
        """
        inhalt = buero.get(
            reverse('admin:faktura_angebot_change',
                    args=[angebot.pk])).content.decode()

        formular = re.search(r'<form[^>]*id="(\w+_form)"[^>]*>', inhalt)
        assert formular is not None, 'kein Änderungsformular gefunden'
        kennung = formular.group(1)

        ende = inhalt.index('</form>', formular.end())
        stelle = inhalt.find('name="_save"')
        assert stelle != -1, 'kein Sicherungsknopf in der Maske'

        im_formular = formular.end() < stelle < ende
        zugeordnet = re.search(
            r'<button[^>]*\bform="' + kennung + r'"[^>]*\bname="_save"',
            inhalt) is not None

        assert im_formular or zugeordnet, (
            'Der Sicherungsknopf gehört zu keinem Formular; '
            'aktion_erst_speichern.js findet ihn dann nicht.'
        )

    def test_auch_das_projekt_bekommt_es(self, buero, kunde):
        """Dasselbe am Projekt mit „Projektakte"."""
        from faktura.models import Projekt

        projekt = Projekt.objects.create(
            nummer='2026-099', bezeichnung='Halle Nord', kunde=kunde)

        inhalt = buero.get(
            reverse('admin:faktura_projekt_change',
                    args=[projekt.pk])).content.decode()

        assert 'faktura/js/aktion_erst_speichern.js' in inhalt


@pytest.mark.django_db
class TestDieKnopfleisteDesAuftrags:
    """Der Auftrag hat "Festschreiben" und kein "Versenden".

    Die Auftragsbestätigung erzeugt ``detail_pdf`` bei Bedarf aus dem
    aktuellen Stand.
    """

    @pytest.fixture
    def auftragsentwurf(self, kunde):
        beleg = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.AUFTRAG, betreff='Halle Nord')
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Montage', menge=Decimal('1'),
            einzelpreis=Decimal('500.00'), steuersatz='19.00')
        return beleg

    def _knoepfe(self, modell):
        admin_klasse = admin.site.get_model_admin(modell)
        return admin_klasse._extract_action_names(admin_klasse.actions_detail)

    def test_festschreiben_steht_da_und_versenden_nicht(self):
        namen = self._knoepfe(Auftrag)

        assert 'detail_festschreiben' in namen
        assert 'detail_versenden' not in namen
        assert 'detail_erneut_versenden' not in namen

    def test_das_angebot_behaelt_seinen_versandknopf(self):
        """Gegenprobe: Das Angebot hat "Versenden"."""
        namen = self._knoepfe(Angebot)

        assert 'detail_versenden' in namen
        assert 'detail_festschreiben' not in namen

    def test_es_gibt_gar_keine_versandadresse_mehr(self, auftragsentwurf):
        """Für den Auftrag gibt es keine Versand-URL, weil Unfold URLs nur aus
        ``actions_detail`` erzeugt."""
        from django.urls import NoReverseMatch

        with pytest.raises(NoReverseMatch):
            reverse('admin:faktura_auftrag_detail_versenden',
                    args=[auftragsentwurf.pk])

    def test_und_die_rechtepruefung_sagt_ebenfalls_nein(self, buero,
                                                        auftragsentwurf):
        """Die Rechteprüfung lehnt den Versand am Auftrag ab, abhängig von der
        Belegart und unabhängig von ``actions_detail``."""
        anfrage = RequestFactory().get('/')
        anfrage.user = User.objects.get(username='sekretariat')

        erlaubt = admin.site.get_model_admin(Auftrag).has_versenden_permission(
            anfrage, str(auftragsentwurf.pk))

        assert erlaubt is False

    def test_der_aufruf_allein_schreibt_nichts_fest(self, buero,
                                                   auftragsentwurf):
        """Der GET zeigt nur die Bestätigung und vergibt keine Nummer."""
        antwort = buero.get(
            reverse('admin:faktura_auftrag_detail_festschreiben',
                    args=[auftragsentwurf.pk]))

        auftragsentwurf.refresh_from_db()
        assert antwort.status_code == 200
        assert auftragsentwurf.status == BelegStatus.ENTWURF
        assert auftragsentwurf.nummer is None

    def test_die_zwischenseite_traegt_das_admin_geruest(self, buero,
                                                        auftragsentwurf):
        """Die Zwischenseite rendert das vollständige Admin-Template.

        Regression: Als Unfold-Dialog erschien sie ohne Styling, weil
        ``aktion_erst_speichern.js`` die URL direkt aufruft und das Fragment
        nicht in ein Modal geladen wird."""
        inhalt = buero.get(
            reverse('admin:faktura_auftrag_detail_festschreiben',
                    args=[auftragsentwurf.pk])).content.decode()

        assert '<html' in inhalt
        assert 'stylesheet' in inhalt
        assert 'Festschreiben' in inhalt

    def test_nach_dem_sichern_fuehrt_der_weg_hierher(self, buero,
                                                     auftragsentwurf, rf):
        """Nach dem Speichern Redirect auf die URL der Aktion, die eine
        vollständige Seite liefert."""
        anfrage = rf.post('/', {'_danach': 'festschreiben'})
        anfrage.user = User.objects.get(username='sekretariat')

        ziel = admin.site.get_model_admin(Auftrag)._adresse_der_aktion(
            anfrage, auftragsentwurf, 'festschreiben')

        assert ziel == reverse('admin:faktura_auftrag_detail_festschreiben',
                               args=[auftragsentwurf.pk])
        assert '<html' in buero.get(ziel).content.decode()

    def test_die_seite_sagt_dass_kein_dokument_entsteht(self, buero,
                                                       auftragsentwurf):
        """Die Zwischenseite weist darauf hin, dass kein Dokument entsteht."""
        inhalt = buero.get(
            reverse('admin:faktura_auftrag_detail_festschreiben',
                    args=[auftragsentwurf.pk])).content.decode()

        assert 'Ein Dokument entsteht dabei nicht' in inhalt

    def test_der_knopf_schreibt_fest(self, buero, auftragsentwurf):
        buero.post(reverse('admin:faktura_auftrag_detail_festschreiben',
                           args=[auftragsentwurf.pk]),
                   {'festschreiben': '1'})

        auftragsentwurf.refresh_from_db()
        assert auftragsentwurf.status == BelegStatus.FESTGESCHRIEBEN
        assert auftragsentwurf.nummer

    def test_das_festschreiben_steht_im_verlauf(self, buero, auftragsentwurf):
        """Das Festschreiben erscheint im Verlauf; den LogEntry schreibt
        ``action_festschreiben``, die der Button aufruft."""
        buero.post(reverse('admin:faktura_auftrag_detail_festschreiben',
                           args=[auftragsentwurf.pk]),
                   {'festschreiben': '1'})

        from django.contrib.admin.models import LogEntry
        from django.contrib.contenttypes.models import ContentType

        eintraege = [
            eintrag.change_message for eintrag in LogEntry.objects.filter(
                object_id=str(auftragsentwurf.pk),
                content_type=ContentType.objects.get_for_model(
                    Auftrag, for_concrete_model=False))
        ]
        assert any('estgeschrieben' in e for e in eintraege), eintraege

    def test_am_festgeschriebenen_auftrag_ist_der_knopf_weg(
            self, buero, auftragsentwurf):
        services.beleg_festschreiben(beleg_id=auftragsentwurf.pk)

        inhalt = buero.get(reverse('admin:faktura_auftrag_change',
                                   args=[auftragsentwurf.pk])).content.decode()

        assert 'festschreiben/' not in inhalt

    def test_die_auftragsbestaetigung_gibt_es_weiterhin(
            self, buero, mit_pdf, auftragsentwurf, settings, tmp_path):
        """Ohne gespeichertes Dokument rendert ``ansicht_pdf`` die
        Auftragsbestätigung bei Aufruf aus dem aktuellen Stand."""
        settings.MEDIA_ROOT = tmp_path
        services.beleg_festschreiben(beleg_id=auftragsentwurf.pk)

        antwort = buero.get(reverse('admin:faktura_auftrag_detail_pdf',
                                    args=[auftragsentwurf.pk]))

        assert antwort.status_code == 200
        assert antwort['Content-Type'] == 'application/pdf'

    def test_der_statusreiter_zeigt_keine_leeren_nachweise(
            self, buero, auftragsentwurf):
        """Der Tab "Status" zeigt am Auftrag keine Felder für PDF, Prüfsumme
        und Archiv, die dort immer leer wären."""
        services.beleg_festschreiben(beleg_id=auftragsentwurf.pk)

        antwort = buero.get(reverse('admin:faktura_auftrag_change',
                                    args=[auftragsentwurf.pk]))
        felder = {
            name
            for _, optionen in antwort.context['adminform'].fieldsets
            for eintrag in optionen['fields']
            for name in (eintrag if isinstance(eintrag, (tuple, list))
                         else [eintrag])
        }

        assert 'dokumentnachweis' not in felder
        assert 'archivverweis' not in felder
        assert 'versendet_am' not in felder
