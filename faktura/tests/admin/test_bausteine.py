"""Textbausteine im Belegformular."""

import re

import pytest
from django.urls import reverse

from faktura.models import (
    Beleg,
    BelegTyp,
    Textbaustein,
    TextbausteinVerwendung,
)
from faktura.tests.admin.hilfen import User


@pytest.mark.django_db
class TestBausteinAuswahl:
    """Textbausteine werden über ein Menü am Feld eingefügt, ohne
    Beteiligung des Servers.

    Danach ist der Text eine gewöhnliche Eingabe. Verworfen: ein
    ``<select>`` neben dem Feld, dessen Baustein ``clean()`` beim Speichern
    einsetzte, wenn das Textfeld unverändert war. Der Server konnte "nie
    geändert" nicht von "gefüllt und wieder geleert" unterscheiden. Ebenfalls
    verworfen: ein eigenes Browserfenster mit Auswahlseite.
    """

    # --- Button am Feld ---

    def test_beide_textfelder_haben_eine_auswahl(self, buero, bausteine):
        inhalt = buero.get(reverse('admin:faktura_angebot_add')).content.decode()

        assert 'data-ziel="id_kopftext"' in inhalt
        assert 'data-ziel="id_fusstext"' in inhalt

    def test_ohne_bausteine_erscheint_kein_menue(self, buero):
        """Ohne Bausteine kein Menü; das Textfeld bleibt."""
        inhalt = buero.get(reverse('admin:faktura_angebot_add')).content.decode()

        assert 'Textvorlagen' not in inhalt
        assert 'id="id_kopftext"' in inhalt

    def test_beide_felder_zeigen_denselben_vorrat(self, buero, bausteine):
        """Kopf- und Fußtext zeigen dieselben Bausteine.

        Die Stelle ergibt sich beim Einfügen. Verworfen: getrennte
        Verwendungen KOPFTEXT und FUSSTEXT. Jeder Eintrag hat sein Zielfeld
        im Markup.
        """
        erster, zweiter = bausteine
        inhalt = buero.get(reverse('admin:faktura_angebot_add')).content.decode()

        eintraege = re.findall(
            r'data-ziel="([^"]+)"\s+data-text="([^"]*)"', inhalt)
        zuordnung: dict[str, list[str]] = {}
        for ziel, text in eintraege:
            zuordnung.setdefault(ziel, []).append(text)

        for feld in ('id_kopftext', 'id_fusstext'):
            vorrat = ' '.join(zuordnung[feld])
            assert erster.text in vorrat, feld
            assert zweiter.text in vorrat, feld

    def test_ein_baustein_je_belegart_erscheint_nur_dort(self, buero, db):
        """Ein Baustein mit Belegart erscheint nur dort; ohne Belegart
        (Regelfall) überall."""
        Textbaustein.objects.create(
            name='Nur fürs Angebot', verwendung=TextbausteinVerwendung.BELEGTEXT,
            belegart=BelegTyp.ANGEBOT, text='Dieses Angebot bindet 30 Tage.')
        Textbaustein.objects.create(
            name='Für alles', verwendung=TextbausteinVerwendung.BELEGTEXT,
            text='Mit freundlichen Grüßen')

        im_angebot = buero.get(
            reverse('admin:faktura_angebot_add')).content.decode()
        in_der_rechnung = buero.get(
            reverse('admin:faktura_rechnung_add')).content.decode()

        assert 'bindet 30 Tage' in im_angebot
        assert 'bindet 30 Tage' not in in_der_rechnung
        # Der allgemeine erscheint in beiden.
        assert 'Mit freundlichen Grüßen' in im_angebot
        assert 'Mit freundlichen Grüßen' in in_der_rechnung

    def test_das_feld_traegt_die_gestaltung_der_oberflaeche(self, buero,
                                                            bausteine):
        """Das eigene Widget erbt von Unfolds Textarea.

        Regression: Es erbte von ``AdminTextareaWidget``; weil Unfold Widgets
        über ``formfield_overrides`` nur austauscht, wo das Formular keines
        setzt, erschien das Feld ohne Unfold-Styling.

        ``field-sizing-content`` lässt das Feld mit dem Text wachsen.
        """
        inhalt = buero.get(reverse('admin:faktura_angebot_add')).content.decode()

        stelle = inhalt.index('id="id_kopftext"')
        anfang = inhalt.rindex('<textarea', 0, stelle)
        feld = inhalt[anfang:stelle]

        assert 'border-base-200' in feld, feld
        assert 'field-sizing-content' in feld, feld

    def test_jeder_eintrag_zeigt_auf_ein_vorhandenes_feld(self, buero,
                                                          bausteine):
        """``data-ziel`` jedes Eintrags verweist auf ein vorhandenes Feld.

        Das Menü hängt per ``x-teleport`` am ``body``; einzige Verbindung zum
        Feld ist ``data-ziel``. Zeigt es auf kein Feld, öffnet sich das Menü,
        der Text wird aber nirgends eingefügt."""
        inhalt = buero.get(reverse('admin:faktura_angebot_add')).content.decode()

        ziele = re.findall(r'data-ziel="([^"]+)"', inhalt)
        assert ziele, 'kein einziger Eintrag im Formular'

        for ziel in ziele:
            assert f'id="{ziel}"' in inhalt, f'{ziel} zeigt ins Leere'

    def test_der_text_steht_zeilengetreu_am_eintrag(self, buero, bausteine):
        """Der Text steht mit Zeilenumbrüchen im Attribut ``data-text``.

        Das Skript liest ``dataset.text``; ein verlorener Zeilenumbruch
        machte aus zwei Absätzen einen. Im Attribut ist er escaped
        (``&#10;``), ``dataset`` liefert ihn unescaped; geprüft wird daher
        der unescapte Wert."""
        import html as html_modul

        kopf, _ = bausteine

        inhalt = buero.get(reverse('admin:faktura_angebot_add')).content.decode()

        anfang = (inhalt.index('data-ziel="id_kopftext"')
                  + len('data-ziel="id_kopftext"'))
        anfang = inhalt.index('data-text="', anfang) + len('data-text="')
        wert = html_modul.unescape(inhalt[anfang:inhalt.index('"', anfang)])

        assert wert == kopf.text
        assert '\n' in wert

    def test_ohne_leserecht_keine_vorlagen(self, client, bausteine):
        """Ohne View-Recht an Textbausteinen kein Menü; die Texte gelangen
        nicht in die Seite. Das Feld bleibt."""
        from django.contrib.auth.models import Permission

        benutzer = User.objects.create_user(
            username='schreibkraft', email='s@example.com',
            password='geheim12345', is_staff=True,
        )
        for recht in ('view_angebot', 'add_angebot', 'change_angebot'):
            benutzer.user_permissions.add(
                Permission.objects.get(codename=recht)
            )
        client.login(username='schreibkraft', password='geheim12345')

        inhalt = client.get(
            reverse('admin:faktura_angebot_add')
        ).content.decode()

        assert 'data-ziel="id_kopftext"' not in inhalt
        assert 'Textvorlagen' not in inhalt
        assert 'id="id_kopftext"' in inhalt

    # --- Server setzt keine Bausteine ein ---

    @staticmethod
    def _anlegen(buero, kunde, **abweichend):
        daten = {
            'kunde': kunde.pk, 'betreff': 'Probe',
            'empfaenger': 'Muster GmbH', 'empfaenger_ust_id': '',
            'empfaenger_land': 'DE', 'zahlungsziel_tage': '14',
            'belegdatum': '', 'leistungsdatum': '', 'leistungsdatum_bis': '',
            'kopftext': '', 'fusstext': '',
            'positionen-TOTAL_FORMS': '0', 'positionen-INITIAL_FORMS': '0',
            'positionen-MIN_NUM_FORMS': '0', 'positionen-MAX_NUM_FORMS': '1000',
        }
        daten.update(abweichend)
        buero.post(reverse('admin:faktura_angebot_add'), daten, follow=True)
        return Beleg.objects.filter(typ=BelegTyp.ANGEBOT).latest('pk')

    def test_der_server_setzt_keinen_text_mehr_ein(self, buero, kunde, bausteine):
        """Ein geleertes Textfeld bleibt leer.

        Regression: ``clean()`` setzte den Baustein ein, wenn das Textfeld
        unverändert schien, und ein manuell geleertes Feld sah so aus.

        Der POST enthält das alte Auswahlfeld, damit der Test fehlschlägt,
        falls die Regel zurückkommt; Django ignoriert unbekannte Felder.
        """
        kopf, _ = bausteine

        beleg = self._anlegen(buero, kunde,
                              kopftext_baustein=str(kopf.pk))

        assert beleg.kopftext == ''

    def test_getippter_text_kommt_unveraendert_an(self, buero, kunde, bausteine):
        """Gegenprobe: Eingegebener Text bleibt unverändert."""
        beleg = self._anlegen(buero, kunde, kopftext='Von Hand geschrieben.')

        assert beleg.kopftext == 'Von Hand geschrieben.'

    def test_das_formular_kennt_die_bausteinfelder_nicht_mehr(self):
        """Das Formular hat keine Felder für Bausteine mehr, damit die alte
        Regel nicht unbemerkt zurückkommt."""
        from faktura.forms import BelegForm

        assert 'kopftext_baustein' not in BelegForm.declared_fields
        assert 'fusstext_baustein' not in BelegForm.declared_fields
