"""Optimistic Locking am Beleg (``core/optimistic_locking.py``).

Ablauf je Test: Zwei Clients laden dieselbe Änderungsseite, A speichert,
danach sendet B seine beim Laden gelesenen Formulardaten. Die Daten werden
aus dem gerenderten HTML geparst, damit ``version_beim_laden`` genau so
mitkommt wie aus dem Browser.

Assertions prüfen die Datenbank: Nichts von B gespeichert, alles von A
erhalten. Ohne ``VersionAdminMixin`` schlagen die Konflikttests fehl.
"""

from decimal import Decimal
from html.parser import HTMLParser

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import gruppen
from core.optimistic_locking import version_erhoehen
from faktura import services
from faktura.models import Beleg, BelegStatus, BelegTyp, Kontakt

HINWEIS = 'Ihre Eingaben konnten nicht gespeichert werden. Die Daten sind nicht mehr aktuell.'


class _Formularleser(HTMLParser):
    """Parst die Felder, die ein Browser aus dem Änderungsformular sendet."""

    def __init__(self, formular_id):
        super().__init__()
        self.formular_id = formular_id
        self.drin = False
        self.daten: dict[str, list[str]] = {}
        self._auswahl = None        # (name, optionen, gewaehlt, mehrfach)
        self._textfeld = None       # (name, teile)

    def _dazu(self, name, wert):
        self.daten.setdefault(name, []).append(wert)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'form':
            self.drin = a.get('id') == self.formular_id
            return
        if tag == 'option' and self.drin and self._auswahl is not None:
            self._auswahl[1].append(a.get('value', ''))
            if 'selected' in a:
                self._auswahl[2].append(a.get('value', ''))
            return
        if not self.drin or not a.get('name') or 'disabled' in a:
            return
        if tag == 'input':
            art = (a.get('type') or 'text').lower()
            if art in ('submit', 'button', 'file', 'image', 'reset'):
                return
            if art in ('checkbox', 'radio'):
                if 'checked' in a:
                    self._dazu(a['name'], a.get('value') or 'on')
                return
            self._dazu(a['name'], a.get('value') or '')
        elif tag == 'select':
            self._auswahl = (a['name'], [], [], 'multiple' in a)
        elif tag == 'textarea':
            self._textfeld = (a['name'], [])

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self._textfeld is not None:
            self._textfeld[1].append(data)

    def handle_endtag(self, tag):
        if tag == 'form':
            self.drin = False
        elif tag == 'textarea' and self._textfeld is not None:
            name, teile = self._textfeld
            text = ''.join(teile)
            # HTML-Spezifikation: Ein Newline direkt nach <textarea>
            # gehört nicht zum Wert.
            self._dazu(name, text[1:] if text.startswith('\n') else text)
            self._textfeld = None
        elif tag == 'select' and self._auswahl is not None:
            name, optionen, gewaehlt, mehrfach = self._auswahl
            if gewaehlt:
                for wert in gewaehlt:
                    self._dazu(name, wert)
            elif optionen and not mehrfach:
                self._dazu(name, optionen[0])
            self._auswahl = None


def formulardaten(antwort, modellname='rechnung'):
    """POST-Daten des Änderungsformulars."""
    leser = _Formularleser(f'{modellname}_form')
    leser.feed(antwort.content.decode())
    daten = dict(leser.daten)
    daten['_save'] = ['Sichern']
    return daten


def gesichert(antwort):
    """True bei Redirect, sonst AssertionError mit den Formularfehlern
    (aussagekräftiger als "200 != 302")."""
    if antwort.status_code == 302:
        return True
    kontext = antwort.context
    fehler = [kontext['adminform'].form.errors]
    fehler += [f.formset.errors + [f.formset.non_form_errors()]
               for f in kontext['inline_admin_formsets']]
    raise AssertionError(f'Nicht gesichert: {fehler}')


def setze(daten, name, wert):
    daten[name] = [str(wert)]


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(
        nummer='K-1000', name='Muster GmbH', strasse='Hauptstraße 1',
        plz='10115', ort='Berlin',
    )


@pytest.fixture
def entwurf(kunde):
    """Eine Rechnung mit den Positionen 10, 20, 30."""
    beleg = services.beleg_anlegen(
        kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Leistungen',
        leistungsdatum=timezone.localdate(),
    )
    for bezeichnung in ('Beratung', 'Planung', 'Bauleitung'):
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung=bezeichnung, menge=Decimal('10'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00',
        )
    return beleg


@pytest.fixture
def zwei(konto):
    """Zwei Clients A und B."""
    anna = konto(gruppen.PROJEKTLEITUNG, 'anna')
    anna.first_name, anna.last_name = 'Anna', 'Bach'
    anna.save()
    a, b = Client(), Client()
    a.force_login(anna)
    b.force_login(konto(gruppen.BUERO, 'bea'))
    return a, b


def adresse(beleg):
    return reverse('admin:faktura_rechnung_change', args=[beleg.pk])


def beide_oeffnen(zwei, beleg):
    a, b = zwei
    return formulardaten(a.get(adresse(beleg))), formulardaten(b.get(adresse(beleg)))


def zeile(daten, nummer):
    """Formset-Präfix der gespeicherten Position mit dieser Nummer."""
    for i in range(int(daten['positionen-INITIAL_FORMS'][0])):
        if daten[f'positionen-{i}-position'] == [str(nummer)]:
            return f'positionen-{i}-'
    raise AssertionError(f'Position {nummer} nicht im Formular')


def neue_position(daten, bezeichnung, nummer):
    """Füllt die leere Extra-Zeile oder legt, wie "Zeile hinzufügen" im
    Browser, eine neue aus der ``__prefix__``-Vorlage an."""
    anzahl = int(daten['positionen-TOTAL_FORMS'][0])
    erste = int(daten['positionen-INITIAL_FORMS'][0])
    frei = [i for i in range(erste, anzahl)
            if daten.get(f'positionen-{i}-bezeichnung', ['']) == ['']]
    if frei:
        i = frei[0]
    else:
        i = anzahl
        for name, werte in list(daten.items()):
            if name.startswith('positionen-__prefix__-'):
                daten[name.replace('__prefix__', str(i))] = list(werte)
        setze(daten, 'positionen-TOTAL_FORMS', anzahl + 1)
    p = f'positionen-{i}-'
    setze(daten, f'{p}position', nummer)
    setze(daten, f'{p}bezeichnung', bezeichnung)
    setze(daten, f'{p}menge', '1')
    setze(daten, f'{p}einzelpreis', '50.00')


@pytest.mark.django_db
class TestOhneFremdeAenderung:

    def test_sichern_geht_wie_bisher(self, zwei, entwurf):
        a, _ = zwei
        daten = formulardaten(a.get(adresse(entwurf)))
        setze(daten, 'betreff', 'Neuer Betreff')

        antwort = a.post(adresse(entwurf), daten)

        assert gesichert(antwort)
        entwurf.refresh_from_db()
        assert entwurf.betreff == 'Neuer Betreff'

    def test_zweimal_hintereinander_aus_frisch_geoeffneter_maske(
            self, zwei, entwurf):
        """Neu geladenes Formular trägt die aktuelle Version, erneutes
        Speichern ohne Konflikt."""
        a, _ = zwei
        for betreff in ('Erster', 'Zweiter'):
            daten = formulardaten(a.get(adresse(entwurf)))
            setze(daten, 'betreff', betreff)
            assert gesichert(a.post(adresse(entwurf), daten))

        entwurf.refresh_from_db()
        assert entwurf.betreff == 'Zweiter'

    def test_das_feld_steht_im_formular(self, zwei, entwurf):
        a, _ = zwei
        daten = formulardaten(a.get(adresse(entwurf)))

        assert daten['version_beim_laden'] == [
            str(Beleg.objects.get(pk=entwurf.pk).version)]


@pytest.mark.django_db
class TestZweiGleichzeitig:

    def test_kopf_a_bleibt_b_bekommt_den_hinweis(self, zwei, entwurf):
        """Die Kopffelder von A bleiben, B erhält den Hinweis. Regression: B
        überschrieb alle Kopffelder mit den Werten beim Laden (Lost
        Update)."""
        a, b = zwei
        daten_a, daten_b = beide_oeffnen(zwei, entwurf)

        setze(daten_a, 'zahlungsziel_tage', '30')
        assert gesichert(a.post(adresse(entwurf), daten_a))

        setze(daten_b, 'betreff', 'Von B')
        antwort = b.post(adresse(entwurf), daten_b)

        assert antwort.status_code == 200
        text = antwort.content.decode()
        assert HINWEIS in text
        assert 'Letzte Änderung: Anna Bach' in text
        # Keine Sammelzeile "unten aufgeführte Fehler", unten steht keiner.
        assert 'unten aufgeführten' not in text
        # Kein Speichern aus dem veralteten Formular, nur der Link zum
        # aktuellen Stand.
        assert 'name="_save"' not in text
        assert 'name="_continue"' not in text
        assert '<a href="" class="underline font-semibold">Aktuellen Stand laden</a>' in text
        # B's Eingabe bleibt im Formular.
        assert 'value="Von B"' in text
        entwurf.refresh_from_db()
        assert entwurf.zahlungsziel_tage == 30
        assert entwurf.betreff == 'Leistungen'

    def test_dieselbe_zeile_verschiedene_felder(self, zwei, entwurf):
        """A ändert den Preis, B die Menge von Pos. 10. Regression: B schrieb
        die ganze Zeile mit dem alten Preis zurück."""
        a, b = zwei
        daten_a, daten_b = beide_oeffnen(zwei, entwurf)

        setze(daten_a, f'{zeile(daten_a, 10)}einzelpreis', '120.00')
        assert gesichert(a.post(adresse(entwurf), daten_a))

        setze(daten_b, f'{zeile(daten_b, 10)}menge', '99')
        antwort = b.post(adresse(entwurf), daten_b)

        assert HINWEIS in antwort.content.decode()
        pos = entwurf.positionen.get(position='10')
        assert pos.einzelpreis == Decimal('120.00')
        assert pos.menge == Decimal('10')

    def test_a_zwei_neue_positionen_b_eine(self, zwei, entwurf):
        """A fügt zwei Positionen an, B eine. Ergebnis: A's fünf, B erhält
        ``VersionKonflikt``. Nach Neuladen speichert B, dann sechs."""
        a, b = zwei
        daten_a, daten_b = beide_oeffnen(zwei, entwurf)

        neue_position(daten_a, 'Von A, erste', 40)
        neue_position(daten_a, 'Von A, zweite', 50)
        assert gesichert(a.post(adresse(entwurf), daten_a))
        assert entwurf.positionen.count() == 5

        neue_position(daten_b, 'Von B', 40)
        antwort = b.post(adresse(entwurf), daten_b)

        assert HINWEIS in antwort.content.decode()
        assert entwurf.positionen.count() == 5
        assert not entwurf.positionen.filter(bezeichnung='Von B').exists()

        daten_b = formulardaten(b.get(adresse(entwurf)))
        neue_position(daten_b, 'Von B', 60)
        assert gesichert(b.post(adresse(entwurf), daten_b))
        assert entwurf.positionen.count() == 6

    def test_versenden_mit_veralteter_version(self, zwei, entwurf):
        """"Versenden" speichert zuerst (``aktion_erst_speichern.js``). Mit
        veralteter Version scheitert bereits das Speichern: Beleg bleibt
        Entwurf, keine Nummer vergeben."""
        a, b = zwei
        daten_a, daten_b = beide_oeffnen(zwei, entwurf)

        setze(daten_a, 'betreff', 'Korrigiert von A')
        assert gesichert(a.post(adresse(entwurf), daten_a))

        setze(daten_b, '_danach', 'versenden')
        setze(daten_b, '_continue', '1')
        antwort = b.post(adresse(entwurf), daten_b)

        assert antwort.status_code == 200
        assert HINWEIS in antwort.content.decode()
        entwurf.refresh_from_db()
        assert entwurf.status == BelegStatus.ENTWURF
        assert entwurf.nummer is None
        assert entwurf.betreff == 'Korrigiert von A'

    def test_ein_dienst_zaehlt_wie_ein_sichern(self, zwei, entwurf):
        """Schreibzugriffe über Services inkrementieren ebenfalls: Eine per
        Service angelegte Position führt bei B zum Konflikt."""
        _, b = zwei
        daten_b = formulardaten(b.get(adresse(entwurf)))

        services.position_hinzufuegen(
            beleg=entwurf, bezeichnung='Aus der Erfassung', menge=Decimal('1'),
            einzelpreis=Decimal('10.00'), steuersatz='19.00')

        setze(daten_b, 'betreff', 'Von B')
        antwort = b.post(adresse(entwurf), daten_b)

        assert HINWEIS in antwort.content.decode()
        entwurf.refresh_from_db()
        assert entwurf.betreff == 'Leistungen'

    def test_ohne_das_feld_wird_nicht_geprueft(self, zwei, entwurf):
        """Ohne ``version_beim_laden`` im POST entfällt die Prüfung."""
        a, b = zwei
        daten_a, daten_b = beide_oeffnen(zwei, entwurf)
        assert gesichert(a.post(adresse(entwurf), daten_a))

        del daten_b['version_beim_laden']
        assert gesichert(b.post(adresse(entwurf), daten_b))


@pytest.mark.django_db
class TestFestgeschriebenWaehrendOffen:

    def test_hinweis_statt_403(self, zwei, entwurf):
        """Beleg wird festgeschrieben, B speichert danach. Statt 403
        Redirect auf die Read-only-Ansicht mit Warnung."""
        a, b = zwei
        daten_b = formulardaten(b.get(adresse(entwurf)))

        services.beleg_festschreiben(beleg_id=entwurf.pk)

        setze(daten_b, 'betreff', 'Von B')
        antwort = b.post(adresse(entwurf), daten_b, follow=True)

        assert antwort.status_code == 200
        assert antwort.redirect_chain[-1][0] == adresse(entwurf)
        text = antwort.content.decode()
        assert 'ist inzwischen festgeschrieben' in text
        assert 'Die Änderungen sind nicht gesichert' in text
        entwurf.refresh_from_db()
        assert entwurf.betreff == 'Leistungen'


@pytest.mark.django_db
class TestVersionWirdInkrementiert:
    """Jeder Schreibzugriff auf Inhalt inkrementiert ``version``; ein neuer
    Schreibpfad ohne Inkrement lässt diese Tests fehlschlagen."""

    def _version(self, beleg):
        return Beleg.objects.values_list(
            'version', flat=True).get(pk=beleg.pk)

    def test_beleg_save(self, entwurf):
        vorher = self._version(entwurf)
        entwurf.betreff = 'Anders'
        entwurf.save()
        assert self._version(entwurf) == vorher + 1
        # refresh_from_db nach dem Update.
        assert entwurf.version == vorher + 1

    def test_save_mit_update_fields(self, entwurf):
        vorher = self._version(entwurf)
        entwurf.betreff = 'Anders'
        entwurf.save(update_fields=['betreff'])
        assert self._version(entwurf) == vorher + 1

    def test_veraltete_instanz_ueberschreibt_kein_inkrement(
            self, entwurf):
        """``save()`` einer Instanz mit veralteter Version behält
        zwischenzeitliche Inkremente aus ``version_erhoehen``."""
        vorher = self._version(entwurf)
        version_erhoehen(Beleg, entwurf.pk)
        version_erhoehen(Beleg, entwurf.pk)
        entwurf.save()
        assert self._version(entwurf) == vorher + 3

    def test_position_anlegen_aendern_loeschen(self, entwurf):
        vorher = self._version(entwurf)
        pos = services.position_hinzufuegen(
            beleg=entwurf, bezeichnung='Neu', menge=Decimal('1'),
            einzelpreis=Decimal('1.00'), steuersatz='19.00')
        nach_anlegen = self._version(entwurf)
        assert nach_anlegen > vorher

        pos.menge = Decimal('2')
        pos.save()
        assert self._version(entwurf) == nach_anlegen + 1

        pos.delete()
        assert self._version(entwurf) == nach_anlegen + 2

    def test_festschreiben_und_wiedereroeffnen(self, entwurf):
        vorher = self._version(entwurf)
        services.beleg_festschreiben(beleg_id=entwurf.pk)
        festgeschrieben = self._version(entwurf)
        assert festgeschrieben > vorher

        # Wiedereröffnen nur bei Angebot und Auftrag.
        angebot = services.beleg_anlegen(
            kunde=entwurf.kunde, typ=BelegTyp.ANGEBOT, betreff='A')
        services.position_hinzufuegen(
            beleg=angebot, bezeichnung='X', menge=Decimal('1'),
            einzelpreis=Decimal('1.00'), steuersatz='19.00')
        services.beleg_festschreiben(beleg_id=angebot.pk)
        vor_dem_oeffnen = self._version(angebot)
        services.beleg_wiedereroeffnen(beleg_id=angebot.pk)
        assert self._version(angebot) == vor_dem_oeffnen + 1

    def test_ein_neuer_beleg_beginnt_bei_null(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        assert self._version(beleg) == 0

