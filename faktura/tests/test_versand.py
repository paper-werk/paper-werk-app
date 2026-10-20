"""Versenden mit Festschreiben.

Geprüft werden die Reihenfolge und Abbrüche, nicht das Layout der Maske:

1. Ohne Adresse geschieht **nichts**, auch kein Festschreiben.
2. Erst festschreiben, dann senden.
3. Schlägt der Versand fehl, **bleibt der Beleg gültig**.

Die dritte Regel greift bei Ausfall des SMTP-Servers; die Meldung muss
dann die vergebene Nummer nennen.
"""

import re
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from faktura import services
from faktura.models import (
    Beleg,
    BelegStatus,
    BelegTyp,
    Kontakt,
    Textbaustein,
    TextbausteinVerwendung,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-1000', name='Muster GmbH', strasse='Hauptstraße 1',
        plz='10115', ort='Berlin', email='buchhaltung@muster.example',
    )


@pytest.fixture
def entwurf(kunde):
    """Versandfertiger Rechnungsentwurf."""
    beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG,
                                   betreff='Leistungen August')
    beleg.leistungsdatum = timezone.localdate()
    beleg.save()
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Beratung', menge=Decimal('10'),
        einzelpreis=Decimal('100.00'), steuersatz='19.00',
        einheit='Std')
    return beleg


class TestDieReihenfolge:

    def test_ohne_adresse_geschieht_gar_nichts(self, entwurf):
        """Ohne Adresse kein Festschreiben.

        Die Prüfung steht vor dem Festschreiben, damit ein Eingabefehler
        keinen unveränderlichen Beleg erzeugt.
        """
        entwurf.empfaenger_email = ''
        entwurf.save()

        with pytest.raises(services.EmpfaengeradresseFehlt):
            services.beleg_versenden(beleg_id=entwurf.pk)

        entwurf.refresh_from_db()
        assert entwurf.status == BelegStatus.ENTWURF
        assert entwurf.nummer is None
        assert not mail.outbox

    def test_mit_adresse_wird_festgeschrieben_und_versendet(self, entwurf):
        versendet = services.beleg_versenden(
            beleg_id=entwurf.pk, betreff='Ihre Rechnung', nachricht='Anbei.')

        assert versendet.status == BelegStatus.FESTGESCHRIEBEN
        assert versendet.nummer.startswith('RE-')
        assert versendet.versendet_am is not None
        assert versendet.versendet_an == 'buchhaltung@muster.example'
        assert len(mail.outbox) == 1

    def test_der_beleg_bleibt_gueltig_wenn_die_post_scheitert(self, entwurf):
        """Bei SMTP-Fehler bleibt der Beleg festgeschrieben.

        Das Festschreiben ist der handelsrechtliche Vorgang, der Versand
        nur Transport; ein Rollback der Nummer hinterließe eine Lücke im
        Nummernkreis.
        """
        with patch('faktura.services.versand.EmailMessage.send',
                   side_effect=OSError('Verbindung abgelehnt')):
            with pytest.raises(services.VersandFehlgeschlagen) as fehler:
                services.beleg_versenden(beleg_id=entwurf.pk)

        entwurf.refresh_from_db()
        assert entwurf.status == BelegStatus.FESTGESCHRIEBEN
        assert entwurf.nummer is not None
        # ... aber ``versendet_am`` bleibt leer.
        assert entwurf.versendet_am is None
        # Die Meldung nennt Festschreiben und Fehlschlag.
        assert 'festgeschrieben und gültig' in str(fehler.value)

    def test_ein_zweiter_versand_zieht_keine_zweite_nummer(self, entwurf):
        """Ein zweiter Versand nach Fehlschlag verbraucht keine Nummer."""
        with patch('faktura.services.versand.EmailMessage.send',
                   side_effect=OSError('Verbindung abgelehnt')):
            with pytest.raises(services.VersandFehlgeschlagen):
                services.beleg_versenden(beleg_id=entwurf.pk)

        entwurf.refresh_from_db()
        nummer = entwurf.nummer

        wieder = services.beleg_versenden(beleg_id=entwurf.pk)

        assert wieder.nummer == nummer
        assert wieder.versendet_am is not None


class TestDiePost:

    def test_der_beleg_haengt_als_pdf_an(self, entwurf):
        """Angehängt wird die gespeicherte Datei, ohne erneutes Rendern.

        Wie im Archiv ist das versendete PDF der Beleg; neu gerendert wiche
        es nach einer Layoutänderung von der Prüfsumme ab.
        """
        versendet = services.beleg_versenden(beleg_id=entwurf.pk)

        name, inhalt, typ = mail.outbox[0].attachments[0]
        assert name == f'{versendet.nummer}.pdf'
        assert typ == 'application/pdf'
        assert inhalt[:4] == b'%PDF'

    def test_der_konsolen_postausgang_gilt_nicht_als_versand(self, settings):
        """Das Console-Backend gilt nicht als Versand.

        Regression: In der Entwicklungsumgebung meldete der Admin
        "versendet" und setzte ``versendet_am``, obwohl das Console-Backend
        nur in die Konsole schrieb.
        """
        settings.MAILERS = {'default': {
            'BACKEND': 'django.core.mail.backends.console.EmailBackend'}}

        assert not services.versand_geht_hinaus()

    def test_ein_echter_postausgang_zaehlt(self, settings):
        settings.MAILERS = {'default': {
            'BACKEND': 'django.core.mail.backends.smtp.EmailBackend'}}

        assert services.versand_geht_hinaus()

    def test_eine_kopie_geht_an_die_eigene_firma(self, entwurf, settings):
        """Eine Kopie geht an die eigene Firma, als Ersatz für die Ablage im
        Postausgang."""
        settings.FAKTURA_VERSAND_KOPIE = True

        services.beleg_versenden(beleg_id=entwurf.pk)

        assert mail.outbox[0].bcc

    def test_ohne_kopie_keine_blindkopie(self, entwurf, settings):
        settings.FAKTURA_VERSAND_KOPIE = False

        services.beleg_versenden(beleg_id=entwurf.pk)

        assert not mail.outbox[0].bcc

    def test_die_angegebene_adresse_schlaegt_die_am_beleg(self, entwurf):
        """Die angegebene Adresse hat Vorrang und wird als ``versendet_an``
        gespeichert, als Nachweis."""
        versendet = services.beleg_versenden(
            beleg_id=entwurf.pk, an='andere@muster.example')

        assert mail.outbox[0].to == ['andere@muster.example']
        assert versendet.versendet_an == 'andere@muster.example'


class TestDieMaske:
    """Die drei Buttons der Versandmaske; jeder schreibt fest."""

    def _versenden(self, beleg):
        return f'/admin/faktura/rechnung/{beleg.pk}/versenden/'

    def _felder(self, **zusatz):
        return {'an': 'buchhaltung@muster.example', 'betreff': 'Ihre Rechnung',
                'nachricht': 'Anbei.', **zusatz}

    def test_die_maske_laedt(self, buero, entwurf):
        antwort = buero.get(self._versenden(entwurf))

        assert antwort.status_code == 200
        inhalt = antwort.content.decode()
        # Alle drei Buttons sind vorhanden.
        assert 'name="senden"' in inhalt
        assert 'name="herunterladen"' in inhalt
        assert 'name="nur_festschreiben"' in inhalt

    def test_nur_der_mailknopf_verlangt_die_adresse(self, buero, entwurf):
        """Nur der Button für die Mail verlangt die Adresse im Browser.

        Das Adressfeld hat ``required``. Regression: Das blockierte auch „Nur
        festschreiben" und „Herunterladen", die keine Adresse brauchen.

        ``formnovalidate`` steht an diesen beiden Buttons, nicht am Button
        für die Mail, damit der Browser dort Tippfehler vor dem
        Festschreiben meldet.
        """
        inhalt = buero.get(self._versenden(entwurf)).content.decode()

        def knopf(name):
            stelle = inhalt.index('name="' + name + '"')
            anfang = inhalt.rindex('<button', 0, stelle)
            return inhalt[anfang:inhalt.index('>', stelle) + 1]

        assert 'formnovalidate' in knopf('nur_festschreiben')
        assert 'formnovalidate' in knopf('herunterladen')
        assert 'formnovalidate' not in knopf('senden')

    def test_die_adresse_bleibt_ein_pflichtfeld(self, buero, entwurf):
        """Gegenprobe: Die Adresse bleibt ``required``."""
        inhalt = buero.get(self._versenden(entwurf)).content.decode()

        stelle = inhalt.index('name="an"')
        feld = inhalt[inhalt.rindex('<input', 0, stelle):
                      inhalt.index('>', stelle) + 1]

        assert 'required' in feld

    def test_am_festgeschriebenen_beleg_gibt_es_kein_festschreiben_mehr(
            self, buero, entwurf):
        """Am festgeschriebenen Beleg kein Button zum Festschreiben; zum
        Schließen dient „Abbrechen"."""
        services.beleg_festschreiben(beleg_id=entwurf.pk)

        inhalt = buero.get(self._versenden(entwurf)).content.decode()

        assert 'name="nur_festschreiben"' not in inhalt
        assert 'Nichts tun' not in inhalt
        # Die übrigen zwei Buttons bleiben.
        assert 'name="herunterladen"' in inhalt
        assert 'name="senden"' in inhalt

    def test_nur_festschreiben_schickt_nichts(self, buero, entwurf):
        buero.post(self._versenden(entwurf),
                   self._felder(nur_festschreiben='1'))

        entwurf.refresh_from_db()
        assert entwurf.status == BelegStatus.FESTGESCHRIEBEN
        assert entwurf.versendet_am is None
        assert not mail.outbox

    def test_herunterladen_fuehrt_zum_pdf(self, buero, entwurf):
        """Redirect über das Proxy-Modell, weil ``beleg_festschreiben`` einen
        ``Beleg`` zurückgibt und ``faktura_beleg_pdf`` nicht existiert."""
        antwort = buero.post(self._versenden(entwurf),
                             self._felder(herunterladen='1'))

        entwurf.refresh_from_db()
        assert entwurf.status == BelegStatus.FESTGESCHRIEBEN
        assert antwort.status_code == 302
        assert antwort['Location'].startswith(
            f'/admin/faktura/rechnung/{entwurf.pk}/pdf/')

    def test_herunterladen_laedt_wirklich_herunter(self, buero, entwurf):
        """„Herunterladen" liefert ``attachment``.

        Regression: Das PDF öffnete sich im selben Tab und ersetzte den
        Beleg. ``?speichern=1`` setzt ``Content-Disposition: attachment``;
        „PDF anzeigen" bleibt ``inline``.
        """
        antwort = buero.post(self._versenden(entwurf),
                             self._felder(herunterladen='1'))
        entwurf.refresh_from_db()

        geladen = buero.get(antwort['Location'])
        angezeigt = buero.get(
            reverse('admin:faktura_rechnung_pdf', args=[entwurf.pk]))

        assert geladen['Content-Disposition'].startswith('attachment;')
        assert angezeigt['Content-Disposition'].startswith('inline;')

    def test_senden_schreibt_fest_und_schickt(self, buero, entwurf):
        buero.post(self._versenden(entwurf), self._felder(senden='1'))

        entwurf.refresh_from_db()
        assert entwurf.status == BelegStatus.FESTGESCHRIEBEN
        assert entwurf.versendet_am is not None
        assert len(mail.outbox) == 1

    def test_ohne_adresse_bleibt_das_formular_stehen(self, buero, entwurf):
        """Ohne Adresse erscheint das Formular erneut, der Beleg bleibt
        Entwurf."""
        antwort = buero.post(self._versenden(entwurf),
                             self._felder(senden='1', an=''))

        entwurf.refresh_from_db()
        assert antwort.status_code == 200
        assert entwurf.status == BelegStatus.ENTWURF
        assert not mail.outbox

    def test_ohne_adresse_darf_man_trotzdem_festschreiben(self, buero, entwurf):
        """Ohne Adresse lässt sich festschreiben, weil nur der Versand per Mail
        ein gültiges Formular verlangt."""
        buero.post(self._versenden(entwurf),
                   self._felder(nur_festschreiben='1', an=''))

        entwurf.refresh_from_db()
        assert entwurf.status == BelegStatus.FESTGESCHRIEBEN

    def test_am_entwurf_steht_der_knopf_ohne_jede_einstellung(
            self, buero, entwurf, kunde):
        """„Versenden" steht am Entwurf unabhängig von Settings.

        Regression: ``FAKTURA_VERSAND`` war im Container aus und in
        ``dev.py`` an; im Container ließ sich kein Entwurf festschreiben,
        und die Tests mit ``dev.py`` erfassten das nicht.
        """
        angebot = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT,
                                         betreff='Halle Nord')

        rechnung = buero.get(reverse('admin:faktura_rechnung_change',
                                     args=[entwurf.pk])).content.decode()
        angebotsmaske = buero.get(reverse('admin:faktura_angebot_change',
                                          args=[angebot.pk])).content.decode()

        assert 'versenden/' in rechnung
        assert 'versenden/' in angebotsmaske

    def test_am_stornierten_beleg_gibt_es_ihn_nicht(self, buero, entwurf):
        services.beleg_festschreiben(beleg_id=entwurf.pk)
        entwurf.refresh_from_db()
        entwurf.status = BelegStatus.STORNIERT
        entwurf.save()

        inhalt = buero.get(reverse('admin:faktura_rechnung_change',
                                   args=[entwurf.pk])).content.decode()

        assert 'versenden/' not in inhalt


class TestDerVermerk:

    def test_er_ueberlebt_die_aenderungssperre(self, entwurf):
        """``versendet_am`` wird trotz Sperre des festgeschriebenen Belegs
        gespeichert.

        ``Beleg.save()`` lehnt jede Änderung ab; die Versandfelder werden
        über ``queryset.update()`` gesetzt.
        """
        versendet = services.beleg_versenden(beleg_id=entwurf.pk)

        # In der Datenbank, nicht nur an der Instanz.
        aus_der_datenbank = Beleg.objects.get(pk=versendet.pk)
        assert aus_der_datenbank.versendet_am is not None
        assert aus_der_datenbank.versendet_an == 'buchhaltung@muster.example'


class TestKeinOffenerBelegGehtHinaus:
    """Kein Versand eines Entwurfs; erst festschreiben, dann senden.

    Ein wiedereröffneter Beleg ist ein Entwurf und wird ebenso
    festgeschrieben; die Tests prüfen, dass er seine Nummer behält.
    """

    @pytest.fixture
    def wiedereroeffnetes_angebot(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT,
                                       betreff='Halle Nord')
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Montage', menge=Decimal('10'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00')
        services.beleg_festschreiben(beleg_id=beleg.pk)
        return services.beleg_wiedereroeffnen(beleg_id=beleg.pk)

    def test_versenden_schreibt_ihn_zuerst_fest(self, wiedereroeffnetes_angebot):
        versendet = services.beleg_versenden(
            beleg_id=wiedereroeffnetes_angebot.pk)

        assert versendet.status == BelegStatus.FESTGESCHRIEBEN
        assert versendet.versendet_am is not None

    def test_die_nummer_bleibt_dabei_dieselbe(self, wiedereroeffnetes_angebot):
        """Die Nummer bleibt dieselbe wie auf dem zuvor versendeten Angebot."""
        vorher = wiedereroeffnetes_angebot.nummer

        versendet = services.beleg_versenden(
            beleg_id=wiedereroeffnetes_angebot.pk)

        assert versendet.nummer == vorher


class TestDasAnschreiben:
    """Der Mailtext kommt aus einem Baustein oder aus dem Fallback."""

    def _maske(self, beleg):
        return f'/admin/faktura/rechnung/{beleg.pk}/versenden/'

    def _text(self, buero, beleg):
        antwort = buero.get(self._maske(beleg))
        return antwort.context['form'].initial['nachricht']

    def test_ohne_baustein_steht_der_eingebaute_text_da(self, buero, entwurf):
        """Ohne Baustein steht der eingebaute Text im Feld, für neue
        Installationen ohne Bausteine."""
        text = self._text(buero, entwurf)

        assert 'Sehr geehrte Damen und Herren' in text

    def test_ein_baustein_schlaegt_den_eingebauten(self, buero, entwurf):
        Textbaustein.objects.create(
            name='Rechnungsmail', verwendung=TextbausteinVerwendung.MAIL,
            text='Guten Tag,\n\nanbei {beleg} über {betrag}.')

        text = self._text(buero, entwurf)

        assert text.startswith('Guten Tag,')
        assert 'Sehr geehrte' not in text

    def test_die_platzhalter_werden_gefuellt(self, buero, entwurf):
        Textbaustein.objects.create(
            name='Mit Platzhaltern', verwendung=TextbausteinVerwendung.MAIL,
            text='Für {empfaenger}: {beleg} über {betrag}. Gruß, {firma}')

        text = self._text(buero, entwurf)

        assert 'Muster GmbH' in text          # der Empfänger
        assert '1.190,00 EUR' in text       # deutsche Schreibweise
        assert '{' not in text

    def test_das_nachrichtenfeld_hat_ein_vorlagenmenue(self, buero, entwurf):
        """Das Nachrichtenfeld hat ein Vorlagenmenü wie der Belegtext.

        Die Zwischenseite gibt ``{{ form.media }}`` aus, weil der Button ohne
        das Skript keine Wirkung hätte.
        """
        Textbaustein.objects.create(
            name='Kurz und knapp', verwendung=TextbausteinVerwendung.MAIL,
            text='Anbei.')

        inhalt = buero.get(self._maske(entwurf)).content.decode()

        assert 'Textvorlagen' in inhalt
        assert 'data-ziel="id_nachricht"' in inhalt
        assert 'textbaustein_einfuegen' in inhalt

    def test_das_menue_zeigt_nur_die_texte_dieser_belegart(self, buero,
                                                           entwurf):
        """Das Menü zeigt nur Anschreiben dieser Belegart."""
        Textbaustein.objects.create(
            name='Fürs Angebot', verwendung=TextbausteinVerwendung.MAIL,
            belegart=BelegTyp.ANGEBOT, text='Gern unterbreiten wir Ihnen')
        Textbaustein.objects.create(
            name='Für alles', verwendung=TextbausteinVerwendung.MAIL,
            text='Mit freundlichen Grüßen')

        inhalt = buero.get(self._maske(entwurf)).content.decode()

        assert 'Fürs Angebot' not in inhalt
        assert 'Für alles' in inhalt

    def test_ein_tippfehler_frisst_den_text_nicht(self, buero, entwurf):
        """Ein unbekannter Platzhalter (``{Betrag}``) bleibt im Text stehen,
        ohne Exception, damit er sichtbar wird."""
        Textbaustein.objects.create(
            name='Mit Fehler', verwendung=TextbausteinVerwendung.MAIL,
            text='Anbei {Betrag} und ein { einzelnes Zeichen.')

        text = self._text(buero, entwurf)

        assert text == 'Anbei {Betrag} und ein { einzelnes Zeichen.'


class TestDieArbeitsliste:
    """Spalte "E-Mail" und Filter für nicht versendete Belege."""

    def _liste(self, buero, **parameter):
        return buero.get(reverse('admin:faktura_rechnung_changelist'),
                         parameter)

    @staticmethod
    def _zelle(antwort, beleg):
        """Gerenderte Zelle "E-Mail" in der Zeile dieses Belegs."""
        cl = antwort.context['cl']
        zeile = next(b for b in cl.result_list if b.pk == beleg.pk)
        return cl.model_admin.versandstand(zeile)

    def test_ohne_mail_bleibt_die_zelle_leer(self, buero, entwurf):
        """Ohne Mail bleibt die Zelle leer, weil die Rechnung per Post
        versendet sein kann."""
        services.beleg_festschreiben(beleg_id=entwurf.pk)

        antwort = self._liste(buero)

        assert self._zelle(antwort, entwurf) == ''
        inhalt = antwort.content.decode()
        assert '>nicht versendet<' not in inhalt
        kopf = re.search(r'class="[^"]*column-versandstand.*?</th>', inhalt,
                         re.S).group()
        assert 'E-Mail' in kopf

    def test_nach_der_mail_steht_ihr_tag(self, buero, entwurf):
        services.beleg_versenden(beleg_id=entwurf.pk)

        antwort = self._liste(buero)

        assert self._zelle(antwort, entwurf) == (
            timezone.localdate().strftime('%d.%m.%Y'))

    def test_der_filter_findet_die_liegengebliebenen(self, buero, entwurf,
                                                     kunde):
        versendet = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)
        versendet.leistungsdatum = timezone.localdate()
        versendet.save()
        services.position_hinzufuegen(
            beleg=versendet, bezeichnung='Beratung', menge=Decimal('1'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00')
        services.beleg_versenden(beleg_id=versendet.pk)
        liegengeblieben = services.beleg_festschreiben(beleg_id=entwurf.pk)

        antwort = self._liste(buero, versandstand='offen')

        gefunden = [b.pk for b in antwort.context['cl'].queryset]
        assert liegengeblieben.pk in gefunden
        assert versendet.pk not in gefunden

    def test_der_filter_findet_auch_die_versendeten(self, buero, entwurf):
        services.beleg_versenden(beleg_id=entwurf.pk)

        antwort = self._liste(buero, versandstand='versendet')

        assert [b.pk for b in antwort.context['cl'].queryset] == [entwurf.pk]

    def test_entwuerfe_gelten_nicht_als_offen(self, buero, entwurf):
        """Entwürfe gelten im Filter nicht als offen."""
        antwort = self._liste(buero, versandstand='offen')

        assert not list(antwort.context['cl'].queryset)


class TestZweiKnoepfeFuerZweiAnlaesse:
    """„Versenden" vor dem ersten Versand, „Erneut versenden" danach."""

    def _maske(self, buero, beleg):
        return buero.get(reverse('admin:faktura_rechnung_change',
                                 args=[beleg.pk])).content.decode()

    def test_vor_dem_versand_heisst_er_versenden(self, buero, entwurf):
        inhalt = self._maske(buero, entwurf)

        assert 'Versenden' in inhalt
        assert 'Erneut versenden' not in inhalt

    def test_danach_heisst_er_erneut_versenden(self, buero, entwurf):
        services.beleg_versenden(beleg_id=entwurf.pk)

        inhalt = self._maske(buero, entwurf)

        assert 'Erneut versenden' in inhalt

    def test_am_stornierten_beleg_gibt_es_keinen(self, buero, entwurf):
        """Am stornierten Beleg kein Button zum Versenden."""
        original = services.beleg_festschreiben(beleg_id=entwurf.pk)
        services.rechnung_korrigieren(beleg_id=original.pk)

        inhalt = self._maske(buero, entwurf)

        assert 'Erneut versenden' not in inhalt
        assert 'versenden/' not in inhalt

    def test_der_knopf_fuehrt_auch_wirklich_zur_maske(self, buero, entwurf):
        """„Erneut versenden" führt zur Maske.

        Regression: 403, weil ``detail_erneut_versenden``
        ``self.detail_versenden()`` aufrief. ``@unfold_action`` umgibt jede
        Aktion mit ihrer Rechteprüfung; ``has_versenden_permission`` lehnt
        am versendeten Beleg ab. Ein Test, der nur das Vorhandensein des
        Buttons prüfte, war grün; hier wird dem Link gefolgt.
        """
        services.beleg_versenden(beleg_id=entwurf.pk)

        antwort = buero.get(
            reverse('admin:faktura_rechnung_detail_erneut_versenden',
                    args=[entwurf.pk]))

        assert antwort.status_code == 200
        assert 'Erneut versenden' in antwort.content.decode()

    def test_und_der_erste_knopf_ebenso(self, buero, entwurf):
        antwort = buero.get(
            reverse('admin:faktura_rechnung_detail_versenden',
                    args=[entwurf.pk]))

        assert antwort.status_code == 200

    def test_der_erstversand_ist_danach_verschlossen(self, buero, entwurf):
        """Gegenprobe: Nach dem Versand lehnt die URL des Erstversands ab;
        zuständig ist „Erneut versenden"."""
        services.beleg_versenden(beleg_id=entwurf.pk)

        antwort = buero.get(
            reverse('admin:faktura_rechnung_detail_versenden',
                    args=[entwurf.pk]))

        assert antwort.status_code == 403


class TestDerErstversandBleibtStehen:
    """Ein zweiter Versand überschreibt ``versendet_am`` nicht.

    Regression: Ein erneuter Versand überschrieb das Datum des ersten, das
    als Nachweis des Zugangs dient. Weitere Versände stehen im Verlauf;
    ``versendet_am`` verwenden Listen und Filter.
    """

    def test_der_erste_versand_steht_am_beleg(self, entwurf):
        versendet = services.beleg_versenden(beleg_id=entwurf.pk)

        assert versendet.versendet_am is not None
        assert versendet.versendet_an == 'buchhaltung@muster.example'

    def test_der_zweite_laesst_ihn_stehen(self, entwurf):
        erst = services.beleg_versenden(beleg_id=entwurf.pk)
        zuerst_am, zuerst_an = erst.versendet_am, erst.versendet_an

        services.beleg_versenden(beleg_id=entwurf.pk,
                                 an='zweite@muster.example')

        beleg = Beleg.objects.get(pk=entwurf.pk)
        assert beleg.versendet_am == zuerst_am
        assert beleg.versendet_an == zuerst_an


class TestDerVerlaufHaeltAllesFest:
    """Festschreiben, Wiedereröffnen und Versand erscheinen im Verlauf.

    Regression: Diese Vorgänge fehlten im Verlauf, weil die Services einen
    ``Beleg`` zurückgeben, Djangos ``history_view`` aber über den
    ContentType des **Proxys** filtert; ein LogEntry am Basismodell erschien
    nicht. Geprüft wird daher der angezeigte Verlauf.
    """

    def _verlauf(self, beleg, art='Angebot'):
        from django.contrib.admin.models import LogEntry
        from django.contrib.contenttypes.models import ContentType

        from faktura import models as m

        inhaltstyp = ContentType.objects.get_for_model(
            getattr(m, art), for_concrete_model=False)
        return [e.change_message for e in LogEntry.objects.filter(
            content_type=inhaltstyp, object_id=str(beleg.pk))]

    @pytest.fixture
    def angebot(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT,
                                       betreff='Halle Nord')
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Montage', menge=Decimal('10'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00')
        return beleg

    def _maske(self, beleg, art='angebot'):
        return reverse(f'admin:faktura_{art}_detail_versenden',
                       args=[beleg.pk])

    def test_nur_festschreiben_steht_im_verlauf(self, buero, angebot):
        buero.post(self._maske(angebot),
                   {'nur_festschreiben': '1', 'an': '', 'betreff': '',
                    'nachricht': ''})

        angebot.refresh_from_db()
        eintraege = self._verlauf(angebot)
        assert any('Festgeschrieben' in e for e in eintraege), eintraege
        assert any(angebot.nummer in e for e in eintraege)

    def test_der_download_steht_im_verlauf(self, buero, angebot):
        buero.post(self._maske(angebot),
                   {'herunterladen': '1', 'an': '', 'betreff': '',
                    'nachricht': ''})

        eintraege = self._verlauf(angebot)
        assert any('heruntergeladen' in e for e in eintraege), eintraege
        # Ebenso das Festschreiben dabei.
        assert any('Festgeschrieben' in e for e in eintraege), eintraege

    def test_der_mailversand_steht_im_verlauf(self, buero, angebot):
        buero.post(self._maske(angebot),
                   {'senden': '1', 'an': 'kunde@muster.example',
                    'betreff': 'Angebot', 'nachricht': 'Anbei.'})

        eintraege = self._verlauf(angebot)
        assert any('kunde@muster.example' in e for e in eintraege), eintraege

    def test_das_wiedereroeffnen_steht_im_verlauf(self, buero, angebot):
        services.beleg_festschreiben(beleg_id=angebot.pk)

        buero.post(
            reverse('admin:faktura_angebot_detail_wiedereroeffnen',
                    args=[angebot.pk]),
            {'_form_submitted': 'on'})

        eintraege = self._verlauf(angebot)
        assert any('Wieder geöffnet' in e for e in eintraege), eintraege

    def test_der_zweite_versand_steht_neben_dem_ersten(self, buero, angebot):
        """Beide Versände stehen im Verlauf.

        Verworfen: eine eigene Tabelle für Versände.
        """
        buero.post(self._maske(angebot),
                   {'senden': '1', 'an': 'erste@muster.example',
                    'betreff': 'A', 'nachricht': ''})
        buero.post(
            reverse('admin:faktura_angebot_detail_erneut_versenden',
                    args=[angebot.pk]),
            {'senden': '1', 'an': 'zweite@muster.example',
             'betreff': 'A', 'nachricht': ''})

        eintraege = self._verlauf(angebot)
        assert any('erste@muster.example' in e for e in eintraege), eintraege
        assert any('zweite@muster.example' in e for e in eintraege), eintraege


LEITWEG_ID = '09162000-12345-67'


class TestDieERechnungImVersand:
    """Die versendete Datei folgt aus dem Beleg: XRechnung als XML, sonst
    PDF; Mail und Download liefern dieselbe.

    Verworfen: Auswahl aus PDF, XML oder beidem. Ein einzelnes XML gilt als
    XRechnung; das EN-16931-XML eines ZUGFeRD-Kunden fiel im
    KoSIT-Validator durch, und "beides" erzeugte zwei E-Rechnungen mit
    derselben Nummer.
    """

    def _maske(self, beleg, art='rechnung'):
        return reverse(f'admin:faktura_{art}_detail_versenden',
                       args=[beleg.pk])

    def _verlauf(self, beleg):
        from django.contrib.admin.models import LogEntry
        from django.contrib.contenttypes.models import ContentType

        from faktura import models as m

        inhaltstyp = ContentType.objects.get_for_model(
            m.Rechnung, for_concrete_model=False)
        return [e.change_message for e in LogEntry.objects.filter(
            content_type=inhaltstyp, object_id=str(beleg.pk))]

    def _anhaenge(self):
        return [name for name, _, _ in mail.outbox[0].attachments]

    @pytest.fixture
    def angebot(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Montage', menge=Decimal('1'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00')
        return beleg

    @pytest.fixture
    def behoerde(self, db):
        """Eigener Kunde mit Zustellweg XRechnung, damit ``entwurf`` unverändert
        bleibt."""
        from faktura.models import Zustellweg

        return Kontakt.anlegen(
            nummer='K-3000', name='Gemeinde Altdorf',
            strasse='Rathausplatz 1', plz='84032', ort='Altdorf',
            email='rechnung@altdorf.example',
            zustellweg=Zustellweg.XRECHNUNG, kaeuferreferenz=LEITWEG_ID,
        )

    @pytest.fixture
    def xrechnung(self, behoerde):
        beleg = services.beleg_anlegen(kunde=behoerde, typ=BelegTyp.RECHNUNG,
                                       betreff='Gutachten')
        beleg.leistungsdatum = timezone.localdate()
        beleg.save()
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Prüfung', menge=Decimal('2'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00',
            einheit='Std')
        return beleg

    # --- Service -----------------------------------------------------------

    def test_die_behoerde_bekommt_nur_das_xml(self, xrechnung):
        versendet = services.beleg_versenden(beleg_id=xrechnung.pk)
        versendet.refresh_from_db()

        assert versendet.erechnungsprofil == 'XRECHNUNG'
        anhaenge = mail.outbox[0].attachments
        assert len(anhaenge) == 1
        name, inhalt, typ = anhaenge[0]
        assert name == f'{versendet.nummer}.xml'
        assert typ == 'application/xml'
        assert inhalt == versendet.xml.read()

    def test_alle_anderen_bekommen_nur_das_pdf(self, entwurf):
        versendet = services.beleg_versenden(beleg_id=entwurf.pk)
        versendet.refresh_from_db()

        assert versendet.erechnungsprofil == 'EN 16931'
        assert self._anhaenge() == [f'{versendet.nummer}.pdf']

    def test_das_angebot_geht_als_pdf(self, angebot):
        versendet = services.beleg_versenden(
            beleg_id=angebot.pk, an='kunde@muster.example')

        assert self._anhaenge() == [f'{versendet.nummer}.pdf']

    def test_es_zaehlt_das_eingefrorene_profil(self, mit_pdf, entwurf,
                                               kunde):
        """Maßgeblich ist das gespeicherte Profil: Nach Umstellung des Kunden
        auf XRechnung wird das gespeicherte ZUGFeRD-PDF versendet; eine
        XRechnung entsteht durch Neuausstellung."""
        from faktura.models import Zustellweg

        beleg = services.beleg_festschreiben(beleg_id=entwurf.pk)
        kunde.zustellweg = Zustellweg.XRECHNUNG
        kunde.save()

        services.beleg_versenden(beleg_id=beleg.pk)

        assert self._anhaenge() == [f'{beleg.nummer}.pdf']

    def test_am_entwurf_gilt_der_zustellweg(self, xrechnung, entwurf):
        assert (services.versandformat(xrechnung)
                == services.Versandanhang.XML)
        assert (services.versandformat(entwurf)
                == services.Versandanhang.PDF)

    # --- Maske -------------------------------------------------------------

    def test_keine_wahl_und_kein_xml_knopf(self, buero, entwurf):
        inhalt = buero.get(self._maske(entwurf)).content.decode()

        assert 'name="anhang"' not in inhalt
        assert 'name="xml_herunterladen"' not in inhalt
        assert 'PDF und XML' not in inhalt
        assert 'name="herunterladen"' in inhalt

    def test_die_maske_nennt_datei_und_zustellweg(self, buero, entwurf):
        inhalt = buero.get(self._maske(entwurf)).content.decode()

        assert 'PDF mit eingebetteter E-Rechnung (ZUGFeRD)' in inhalt
        assert 'Zustellweg von Muster GmbH: PDF per E-Mail' in inhalt

    def test_bei_der_behoerde_nennt_sie_die_xrechnung(self, buero,
                                                      xrechnung):
        inhalt = buero.get(self._maske(xrechnung)).content.decode()

        assert 'XRechnung (XML für das Rechnungsportal)' in inhalt
        assert 'ZUGFeRD' not in inhalt

    def test_am_angebot_nur_das_pdf(self, buero, angebot):
        inhalt = buero.get(
            self._maske(angebot, art='angebot')).content.decode()

        assert 'ZUGFeRD' not in inhalt
        assert 'XRechnung' not in inhalt

    def test_herunterladen_liefert_bei_xrechnung_das_xml(
            self, buero, xrechnung, mit_pdf):
        """Der Download liefert bei XRechnung das XML für den Upload ins
        Portal; geprüft bis zur Datei."""
        antwort = buero.post(self._maske(xrechnung),
                             {'herunterladen': '1', 'an': '',
                              'betreff': '', 'nachricht': ''})

        xrechnung.refresh_from_db()
        assert xrechnung.status == BelegStatus.FESTGESCHRIEBEN
        assert antwort.status_code == 302
        assert antwort['Location'] == (
            f'/admin/faktura/rechnung/{xrechnung.pk}/xml/')

        datei = buero.get(antwort['Location'])
        assert datei.status_code == 200
        assert datei['Content-Type'] == 'application/xml'
        assert 'attachment' in datei['Content-Disposition']
        assert (f'Rechnung_{xrechnung.nummer}.xml'
                in datei['Content-Disposition'])
        assert b''.join(datei.streaming_content) == xrechnung.xml.read()
        assert 'XRechnung heruntergeladen.' in self._verlauf(xrechnung)

    def test_herunterladen_liefert_sonst_das_pdf(self, buero, entwurf,
                                                 mit_pdf):
        antwort = buero.post(self._maske(entwurf),
                             {'herunterladen': '1', 'an': '',
                              'betreff': '', 'nachricht': ''})

        assert antwort.status_code == 302
        assert antwort['Location'] == (
            f'/admin/faktura/rechnung/{entwurf.pk}/pdf/?speichern=1')
        assert 'PDF heruntergeladen.' in self._verlauf(entwurf)

    def test_der_verlauf_nennt_die_datei(self, buero, xrechnung):
        """Der Verlauf nennt die versendete Datei, weil sie bei E-Rechnungen
        das Original bestimmt."""
        buero.post(self._maske(xrechnung),
                   {'senden': '1', 'an': 'rechnung@behoerde.example',
                    'betreff': 'Rechnung', 'nachricht': ''})

        eintraege = self._verlauf(xrechnung)
        assert any('(Anhang: XRechnung (XML für das Rechnungsportal))' in e
                   for e in eintraege), eintraege
        assert self._anhaenge()[0].endswith('.xml')

    # --- XML nur bei XRechnung ---------------------------------------------

    def test_ein_zugferd_xml_gibt_es_nicht_einzeln(self, buero, entwurf,
                                                   mit_pdf):
        """Ein ZUGFeRD-XML gibt es nicht einzeln, weder per URL noch am Beleg;
        Clients erhalten es über die API mit Angabe des Profils."""
        beleg = services.beleg_festschreiben(beleg_id=entwurf.pk)
        assert beleg.xml

        antwort = buero.get(f'/admin/faktura/rechnung/{beleg.pk}/xml/')
        assert antwort.status_code == 302
        assert 'Content-Disposition' not in antwort

        seite = buero.get(
            f'/admin/faktura/rechnung/{beleg.pk}/change/').content.decode()
        assert f'/rechnung/{beleg.pk}/xml/' not in seite
        assert 'E-Rechnung im PDF' in seite

    def test_die_xrechnung_steht_am_beleg(self, buero, xrechnung, mit_pdf):
        beleg = services.beleg_festschreiben(beleg_id=xrechnung.pk)

        seite = buero.get(
            f'/admin/faktura/rechnung/{beleg.pk}/change/').content.decode()
        assert f'/rechnung/{beleg.pk}/xml/' in seite


class TestDerZustellwegPasstNicht:
    """Leitweg-ID am Beleg ohne Zustellweg XRechnung: Warnung in der
    Versandmaske vor dem Festschreiben, ohne Sperre. Danach bleibt nur die
    Neuausstellung."""

    WARNUNG = 'ist eine Leitweg-ID'

    @pytest.fixture
    def mit_leitweg_id(self, entwurf):
        entwurf.leitweg_id = LEITWEG_ID
        entwurf.save()
        return entwurf

    def test_die_versandmaske_warnt(self, buero, mit_leitweg_id):
        inhalt = buero.get(reverse(
            'admin:faktura_rechnung_detail_versenden',
            args=[mit_leitweg_id.pk])).content.decode()

        assert self.WARNUNG in inhalt
        assert 'Passt das Format zum Kunden?' in inhalt

    def test_eine_gewoehnliche_kaeuferreferenz_ist_kein_anlass(
            self, buero, entwurf):
        entwurf.leitweg_id = 'KST-4711'
        entwurf.save()

        inhalt = buero.get(reverse(
            'admin:faktura_rechnung_detail_versenden',
            args=[entwurf.pk])).content.decode()

        assert 'Passt das Format zum Kunden?' not in inhalt

    def test_beim_xrechnung_kunden_kein_anlass(self, mit_leitweg_id, kunde):
        from faktura import facturx
        from faktura.models import Zustellweg

        kunde.zustellweg = Zustellweg.XRECHNUNG
        kunde.save()

        assert facturx.zustellweg_warnung(mit_leitweg_id) == ''

    def test_nach_dem_festschreiben_der_weg_zum_neu_ausstellen(
            self, mit_pdf, entwurf, kunde):
        from faktura import facturx
        from faktura.models import Zustellweg

        beleg = services.beleg_festschreiben(beleg_id=entwurf.pk)
        assert facturx.zustellweg_warnung(beleg) == ''

        kunde.zustellweg = Zustellweg.XRECHNUNG
        kunde.save()
        beleg = Beleg.objects.get(pk=beleg.pk)

        assert 'neu ausstellen' in facturx.zustellweg_warnung(beleg)

    def test_trotzdem_festschreibbar(self, mit_leitweg_id):
        beleg = services.beleg_festschreiben(beleg_id=mit_leitweg_id.pk)

        assert beleg.status == BelegStatus.FESTGESCHRIEBEN


class TestMehrAlsBeauftragt:
    """Überschreitung des Beauftragten in der Versandmaske.

    Die Maske zeigt die Überschreitung; festgeschrieben wird nur mit
    Bestätigung, sonst erscheint die Maske mit Meldung erneut und der Beleg
    bleibt Entwurf.
    """

    @pytest.fixture
    def zuviel(self, kunde):
        """10 Std beauftragt, die Rechnung über 12."""
        from faktura.models import Projekt

        projekt = Projekt.objects.create(
            nummer='2026-077', bezeichnung='Halle Süd', kunde=kunde)
        auftrag = services.beleg_anlegen(projekt=projekt,
                                         typ=BelegTyp.AUFTRAG)
        position = services.position_hinzufuegen(
            beleg=auftrag, bezeichnung='Planung', menge=Decimal('10'),
            einheit='Std', einzelpreis=Decimal('95.00'),
            steuersatz='19.00')
        services.beleg_festschreiben(beleg_id=auftrag.pk)

        rechnung = services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG,
            leistungsdatum=timezone.localdate())
        services.position_hinzufuegen(
            beleg=rechnung, bezeichnung='Planung', menge=Decimal('12'),
            einheit='Std', einzelpreis=Decimal('95.00'),
            steuersatz='19.00', auftragsposition=position)
        return rechnung

    def _versenden(self, beleg):
        return f'/admin/faktura/rechnung/{beleg.pk}/versenden/'

    def test_die_maske_zeigt_die_ueberschreitung_vorher(self, buero, zuviel):
        inhalt = buero.get(self._versenden(zuviel)).content.decode()

        assert 'Mehr als beauftragt' in inhalt
        assert '2 zu viel' in inhalt
        assert 'name="mengen_bestaetigt"' in inhalt

    def test_im_rahmen_fragt_die_maske_nicht(self, buero, entwurf):
        inhalt = buero.get(self._versenden(entwurf)).content.decode()

        assert 'name="mengen_bestaetigt"' not in inhalt

    def test_ohne_haken_bleibt_es_beim_entwurf(self, buero, zuviel):
        antwort = buero.post(self._versenden(zuviel),
                             {'nur_festschreiben': '1'})

        # Die Maske erscheint erneut mit der Bestätigung.
        assert antwort.status_code == 200
        assert 'name="mengen_bestaetigt"' in antwort.content.decode()
        zuviel.refresh_from_db()
        assert zuviel.status == BelegStatus.ENTWURF
        assert zuviel.nummer is None

    def test_mit_haken_wird_festgeschrieben(self, buero, zuviel):
        antwort = buero.post(self._versenden(zuviel),
                             {'nur_festschreiben': '1',
                              'mengen_bestaetigt': '1'})

        assert antwort.status_code == 302
        zuviel.refresh_from_db()
        assert zuviel.status == BelegStatus.FESTGESCHRIEBEN

    def test_auch_der_mailweg_fragt(self, buero, zuviel):
        daten = {'an': 'buchhaltung@muster.example', 'betreff': 'Rechnung',
                 'nachricht': 'Anbei.', 'senden': '1'}

        buero.post(self._versenden(zuviel), daten)
        zuviel.refresh_from_db()
        assert zuviel.status == BelegStatus.ENTWURF
        assert not mail.outbox

        buero.post(self._versenden(zuviel),
                   {**daten, 'mengen_bestaetigt': '1'})
        zuviel.refresh_from_db()
        assert zuviel.status == BelegStatus.FESTGESCHRIEBEN
        assert len(mail.outbox) == 1
