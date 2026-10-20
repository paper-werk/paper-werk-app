"""Admin der Erfassung, geprüft mit den Rollen des Betriebs.

Kein Test läuft als Superuser, weil der alle Rechte hat und Lücken in der
Rechteprüfung so nicht auffallen.
"""

import re
from datetime import time, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from erfassung import services
from erfassung.models import Erfassungszeile
from erfassung.tests.hilfen import zelle as _zelle
from faktura.models import (
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Leistungsart,
    Projekt,
)

LISTE = 'admin:erfassung_erfassungszeile_changelist'
ANLEGEN = 'admin:erfassung_erfassungszeile_add'
AENDERN = 'admin:erfassung_erfassungszeile_change'


@pytest.fixture
def als_mitarbeiter(client, mitarbeiter):
    """Bürokonto mit dem Recht zu erfassen, sonst keinem."""
    mitarbeiter.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='erfassung',
        codename__in=['add_erfassungszeile', 'view_erfassungszeile',
                      'change_erfassungszeile'],
    ))
    client.force_login(mitarbeiter)
    return client


@pytest.fixture
def als_uebernehmer(client, mitarbeiter):
    """Konto, das erfassen und in Rechnungen übernehmen darf.

    Die Übernahme legt einen Beleg an und braucht Rechte über die Erfassung
    hinaus. Eigener Client, damit ``als_mitarbeiter`` ohne weitere Rechte
    bleibt.
    """
    mitarbeiter.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='erfassung',
        codename__in=['add_erfassungszeile', 'view_erfassungszeile',
                      'change_erfassungszeile'],
    ))
    mitarbeiter.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='faktura',
        codename__in=['add_beleg', 'change_beleg', 'view_beleg'],
    ))
    client.force_login(mitarbeiter)
    return client


@pytest.fixture
def als_chef(client, kollege):
    """Wie ``als_uebernehmer``, zusätzlich mit dem Recht, für andere zu
    erfassen."""
    kollege.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='erfassung',
        codename__in=['add_erfassungszeile', 'view_erfassungszeile',
                      'change_erfassungszeile', 'fuer_andere_erfassen'],
    ))
    client.force_login(kollege)
    return client


@pytest.fixture
def fremde_zeile(projekt, zeitleistung, kollege):
    return services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
        projekt=projekt, leistung=zeitleistung, benutzer=kollege,
        beschreibung='Was der Kollege gemacht hat',
    )


def _formular(projekt, leistung, **abweichend):
    """POST-Daten des Formulars mit dem Umfang, den die Leistungsart
    verlangt.

    ``clean()`` lehnt Zeilen ohne Umfang ab (``Erfassungszeile._pruefe_umfang``);
    ohne Vorgabe entstünde keine Zeile. Für unvollständige Fälle die Felder
    überschreiben: ``_formular(projekt, zeitleistung, von='', bis='')``.
    """
    daten = {
        'datum': timezone.localdate().strftime('%d.%m.%Y'),
        'projekt': projekt.pk,
        'leistung': leistung.pk,
        'von': '',
        'bis': '',
        'menge': '',
        'beschreibung': 'Arbeit',
    }
    if leistung.art == Leistungsart.ZEIT:
        daten['von'], daten['bis'] = '08:00', '10:00'
    elif leistung.art == Leistungsart.MENGE:
        daten['menge'] = '12'
    daten.update(abweichend)
    return daten


@pytest.mark.django_db
class TestJederSiehtSeineZeilen:

    def test_die_liste_zeigt_nur_eigene(
        self, als_mitarbeiter, projekt, zeitleistung, mitarbeiter, fremde_zeile
    ):
        services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Meine Arbeit',
        )

        inhalt = als_mitarbeiter.get(reverse(LISTE)).content.decode()

        assert 'Meine Arbeit' in inhalt
        assert 'Was der Kollege gemacht hat' not in inhalt

    def test_eine_fremde_zeile_ist_nicht_erreichbar(
        self, als_mitarbeiter, fremde_zeile
    ):
        """Eine fremde Zeile ist auch über ihre URL nicht erreichbar.

        Django antwortet auf einen Datensatz außerhalb des Querysets mit
        einem Redirect auf die Startseite, nicht mit 404. Geprüft werden der
        Redirect und das Fehlen des Inhalts.
        """
        antwort = als_mitarbeiter.get(
            reverse(AENDERN, args=[fremde_zeile.pk]), follow=True)

        assert 'Was der Kollege gemacht hat' not in antwort.content.decode()
        assert antwort.redirect_chain, 'es wurde gar nicht umgeleitet'
        assert antwort.redirect_chain[-1][0].endswith('/admin/')

    def test_der_chef_sieht_alle(
        self, als_chef, projekt, zeitleistung, mitarbeiter, fremde_zeile
    ):
        """Gegenprobe: Mit dem Recht für andere sind alle Zeilen sichtbar."""
        services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Meine Arbeit',
        )

        inhalt = als_chef.get(reverse(LISTE)).content.decode()

        assert 'Meine Arbeit' in inhalt
        assert 'Was der Kollege gemacht hat' in inhalt


@pytest.mark.django_db
class TestDiePersonWirdGesetztNichtGefragt:

    def test_das_feld_fehlt_im_formular(self, als_mitarbeiter):
        inhalt = als_mitarbeiter.get(reverse(ANLEGEN)).content.decode()

        assert 'name="benutzer"' not in inhalt

    def test_beim_chef_steht_es_da(self, als_chef):
        """Gegenprobe: Mit dem Recht für andere erscheint die Personenauswahl."""
        inhalt = als_chef.get(reverse(ANLEGEN)).content.decode()

        assert 'name="benutzer"' in inhalt

    def test_erfasst_wird_auf_den_angemeldeten(
        self, als_mitarbeiter, projekt, zeitleistung, mitarbeiter
    ):
        """Ohne Personenauswahl gilt der angemeldete Benutzer.

        Der Admin speichert über sein Formular und nicht über den Service;
        die Regel muss deshalb auch dort gelten.
        """
        als_mitarbeiter.post(reverse(ANLEGEN),
                             _formular(projekt, zeitleistung))

        assert Erfassungszeile.objects.get().benutzer == mitarbeiter


@pytest.mark.django_db
class TestVonBisUndDieBerechneteDauer:
    """Die Dauer wird aus von und bis berechnet."""

    def test_die_dauer_erscheint_in_der_liste(
        self, als_mitarbeiter, projekt, zeitleistung
    ):
        als_mitarbeiter.post(reverse(ANLEGEN), _formular(
            projekt, zeitleistung, von='07:00', bis='14:15'))

        assert Erfassungszeile.objects.get().dauer_minuten == 435
        assert '7:15' in als_mitarbeiter.get(reverse(LISTE)).content.decode()

    def test_es_gibt_kein_eingabefeld_fuer_die_dauer(
        self, als_mitarbeiter
    ):
        """Kein Eingabefeld für die Dauer, weil sie sonst von von und bis
        abweichen könnte."""
        inhalt = als_mitarbeiter.get(reverse(ANLEGEN)).content.decode()

        assert 'name="dauer_minuten"' not in inhalt
        assert 'name="von"' in inhalt
        assert 'name="bis"' in inhalt

    @pytest.mark.parametrize('von, bis', [('', ''), ('07:00', ''), ('', '14:15')])
    def test_eine_fehlende_uhrzeit_wird_am_feld_abgewiesen(
        self, als_mitarbeiter, projekt, zeitleistung, von, bis
    ):
        """Eine fehlende Uhrzeit wird mit Meldung am Feld abgelehnt.

        Alle drei Fälle (von fehlt, bis fehlt, beide fehlen) ergeben die
        Dauer null und damit eine Zeile ohne Umfang.
        """
        antwort = als_mitarbeiter.post(reverse(ANLEGEN), _formular(
            projekt, zeitleistung, von=von, bis=bis))

        assert not Erfassungszeile.objects.exists()
        assert 'keine Dauer' in antwort.content.decode()

    def test_rueckwaerts_wird_am_feld_abgewiesen(
        self, als_mitarbeiter, projekt, zeitleistung
    ):
        antwort = als_mitarbeiter.post(reverse(ANLEGEN), _formular(
            projekt, zeitleistung, von='22:00', bis='02:00'))

        assert not Erfassungszeile.objects.exists()
        assert 'nach der Anfangszeit' in antwort.content.decode()


@pytest.mark.django_db
class TestDieListeIstDerLeistungsnachweis:
    """Die Liste zeigt die Angaben des Leistungsnachweises.

    Mit Uhrzeiten und nicht nur der Dauer, weil ein Nachweis von und bis
    nennt. Bei Mengenzeilen bleiben diese Spalten leer.
    """

    def test_uhrzeiten_stehen_in_der_liste(
        self, als_mitarbeiter, projekt, zeitleistung, mitarbeiter
    ):
        from datetime import time
        services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            von=time(9, 0), bis=time(12, 0), beschreibung='Vormittag',
        )

        inhalt = als_mitarbeiter.get(reverse(LISTE)).content.decode()

        assert '09:00' in inhalt
        assert '12:00' in inhalt
        assert '3:00' in inhalt

    def test_eine_mengenzeile_zeigt_ihre_menge(
        self, als_mitarbeiter, projekt, mengenleistung, mitarbeiter
    ):
        """Eine Mengenzeile zeigt ihre Menge, etwa die Kilometer einer
        Anfahrt."""
        from decimal import Decimal
        services.zeile_erfassen(
            projekt=projekt, leistung=mengenleistung, benutzer=mitarbeiter,
            menge=Decimal('23'), beschreibung='Hin und zurück',
        )

        inhalt = als_mitarbeiter.get(reverse(LISTE)).content.decode()

        assert '23 km' in inhalt

    def test_bei_einer_mengenzeile_steht_keine_dauer(
        self, als_mitarbeiter, projekt, mengenleistung, mitarbeiter
    ):
        """Eine Mengenzeile zeigt keine Dauer "0:00".

        Geprüft wird die Zelle, weil die Summenzeile über der Liste bei
        reinen Mengen korrekt 0:00 enthält.
        """
        from decimal import Decimal
        services.zeile_erfassen(
            projekt=projekt, leistung=mengenleistung, benutzer=mitarbeiter,
            menge=Decimal('23'), beschreibung='Anfahrt',
        )

        inhalt = als_mitarbeiter.get(reverse(LISTE)).content.decode()

        # Django stellt eine leere Anzeige als "-" dar (empty_value_display).
        assert _zelle(inhalt, 'dauer') == '-'
        assert _zelle(inhalt, 'umfang') == '23 km'

    def test_eine_mengenzeile_ohne_menge_stuerzt_die_liste_nicht_ab(
        self, als_mitarbeiter, projekt, mengenleistung, mitarbeiter,
        zeile_ohne_umfang
    ):
        """Eine Mengenzeile ohne Menge führt nicht zu einer 500.

        Die Umfangsspalte ruft ``menge.normalize()``; auf ``None`` wäre das
        ein AttributeError. Solche Zeilen lassen sich nicht mehr erfassen,
        kommen aber in Altdaten vor; deshalb über ``zeile_ohne_umfang``.
        """
        zeile_ohne_umfang(projekt, mengenleistung, mitarbeiter,
                          beschreibung='Anfahrt, km nachtragen')

        antwort = als_mitarbeiter.get(reverse(LISTE))

        assert antwort.status_code == 200
        assert _zelle(antwort.content.decode(), 'umfang') == '-'

    def test_die_personenspalte_fehlt_wer_nur_sich_sieht(
        self, als_mitarbeiter, projekt, zeitleistung, mitarbeiter
    ):
        """Ohne Recht für andere fehlt die Personenspalte, weil sie nur den
        eigenen Namen enthielte.

        Geprüft im gerenderten HTML, nicht an ``list_display``.
        """
        services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Arbeit',
        )
        antwort = als_mitarbeiter.get(reverse(LISTE))

        assert 'field-person' not in antwort.content.decode()

    def test_beim_chef_steht_der_personenname_da(
        self, als_chef, fremde_zeile, kollege
    ):
        """Gegenprobe: Mit dem Recht für andere erscheint die Personenspalte
        mit vollem Namen."""
        kollege.first_name, kollege.last_name = 'Bernd', 'Vogt'
        kollege.save()

        antwort = als_chef.get(reverse(LISTE))

        assert _zelle(antwort.content.decode(), 'person') == 'Bernd Vogt'

    def test_nach_der_personenspalte_laesst_sich_sortieren(
        self, als_chef, fremde_zeile
    ):
        """Die Personenspalte ist sortierbar.

        Die Spalte ist eine Methode; Django sortiert nur mit korrektem
        ``admin_order_field``. Ein Tippfehler darin fällt erst beim Klick auf
        die Spaltenüberschrift auf, den der Test ausführt.
        """
        spalte = list(als_chef.get(reverse(LISTE))
                      .context_data['cl'].list_display).index('person')

        antwort = als_chef.get(reverse(LISTE), {'o': spalte})

        assert antwort.status_code == 200

    def test_ohne_gepflegten_namen_steht_der_anmeldename_da(
        self, als_chef, fremde_zeile
    ):
        """Ohne gepflegten Namen erscheint der Benutzername."""
        antwort = als_chef.get(reverse(LISTE))

        assert _zelle(antwort.content.decode(), 'person') == 'bernd'


@pytest.mark.django_db
class TestLeistungsauswahl:
    """Auswahl der Leistung, gefiltert wie beim Projekt."""

    def test_ohne_leistung_wird_nicht_gespeichert(
        self, als_mitarbeiter, projekt, zeitleistung
    ):
        daten = _formular(projekt, zeitleistung)
        daten['leistung'] = ''

        antwort = als_mitarbeiter.post(reverse(ANLEGEN), daten)

        assert antwort.status_code == 200
        assert not Erfassungszeile.objects.exists()

    def test_nur_kontierbare_stehen_zur_wahl(
        self, als_mitarbeiter, zeitleistung, nur_fuer_angebote
    ):
        inhalt = als_mitarbeiter.get(reverse(ANLEGEN)).content.decode()

        assert str(zeitleistung) in inhalt
        assert str(nur_fuer_angebote) not in inhalt

    def test_an_der_bestehenden_zeile_bleibt_sie_stehen(
        self, als_mitarbeiter, projekt, zeitleistung, mitarbeiter
    ):
        """Eine nicht mehr kontierbare Leistung bleibt an bestehenden Zeilen
        wählbar, wie beim Projekt."""
        zeile = services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Arbeit',
        )
        type(zeitleistung).objects.filter(pk=zeitleistung.pk).update(
            kontierbar=False)

        inhalt = als_mitarbeiter.get(
            reverse(AENDERN, args=[zeile.pk])).content.decode()

        assert str(zeitleistung) in inhalt


@pytest.mark.django_db
class TestDieMaskeIstAufgeraeumt:
    """Keine Symbole zum Anlegen, Ändern, Ansehen und Löschen an den
    Auswahlfeldern.

    In der Erfassung werden keine Projekte oder Personen gepflegt. Geprüft
    im gerenderten HTML, weil die Attribute am ``RelatedFieldWidgetWrapper``
    gesetzt werden müssen, den Django erst nach
    ``formfield_for_foreignkey`` erzeugt.
    """

    def _knoepfe(self, html: str, feld: str) -> list[str]:
        return sorted(set(re.findall(
            rf'id="(add|change|delete|view)_id_{feld}"', html)))

    def test_am_projekt_steht_kein_knopf(self, als_mitarbeiter):
        inhalt = als_mitarbeiter.get(reverse(ANLEGEN)).content.decode()

        assert self._knoepfe(inhalt, 'projekt') == []

    def test_an_der_person_steht_kein_knopf(self, als_chef):
        """Mit Recht für andere, weil das Feld nur dann erscheint."""
        inhalt = als_chef.get(reverse(ANLEGEN)).content.decode()

        assert self._knoepfe(inhalt, 'benutzer') == []

    def test_an_der_leistung_steht_genau_das_pluszeichen(self, als_mitarbeiter):
        """An der Leistung bleibt nur "anlegen", weil neue Leistungen beim
        Erfassen entstehen; Ändern und Löschen gehören in die
        Katalogpflege."""
        inhalt = als_mitarbeiter.get(reverse(ANLEGEN)).content.decode()

        assert self._knoepfe(inhalt, 'leistung') == ['add']

    def test_eine_frisch_angelegte_leistung_ist_sofort_waehlbar(
        self, als_mitarbeiter, projekt
    ):
        """Eine über "anlegen" erzeugte Leistung ist sofort wählbar.

        Mit ``kontierbar`` als Vorgabe aus stand die neue Leistung zwar in
        der Auswahl, das Speichern scheiterte aber mit "Bitte eine gültige
        Auswahl treffen".
        """
        from faktura.models import Katalogposition
        neu = Katalogposition.objects.create(
            bezeichnung='Gerüstbau', einheit='Std', einzelpreis=Decimal('55.00'),
        )

        als_mitarbeiter.post(reverse(ANLEGEN), _formular(projekt, neu))

        assert Erfassungszeile.objects.get().leistung == neu

    def test_von_und_bis_stehen_in_einer_zeile(self, als_mitarbeiter):
        """Von und bis stehen in einer Formularzeile.

        Geprüft wird, dass zwischen beiden Feldern keine neue Zeile beginnt;
        das gilt für Djangos und Unfolds Markup gleichermaßen.
        """
        inhalt = als_mitarbeiter.get(reverse(ANLEGEN)).content.decode()
        dazwischen = inhalt[inhalt.index('field-von'):inhalt.index('field-bis')]

        assert 'form-row' not in dazwischen


@pytest.mark.django_db
class TestMengeIstFreiwillig:
    """Das Feld Menge ist optional, weil es bei Zeitleistungen nicht
    verwendet wird."""

    def test_eine_zeitzeile_ohne_menge_wird_gespeichert(
        self, als_mitarbeiter, projekt, zeitleistung
    ):
        antwort = als_mitarbeiter.post(reverse(ANLEGEN), _formular(
            projekt, zeitleistung, von='09:00', bis='12:00'))

        assert Erfassungszeile.objects.count() == 1
        assert 'zwingend erforderlich' not in antwort.content.decode()

    def test_das_feld_ist_nicht_mehr_als_pflicht_ausgezeichnet(
        self, als_mitarbeiter
    ):
        """Das Eingabefeld hat kein ``required``-Attribut.

        Geprüft am Eingabefeld, weil ``required`` die Validierung im Browser
        steuert und unabhängig vom Markup der Formularzeile ist.
        """
        inhalt = als_mitarbeiter.get(reverse(ANLEGEN)).content.decode()
        feld = re.search(r'<input[^>]*id="id_menge"[^>]*>', inhalt)

        assert feld is not None
        assert 'required' not in feld.group(0)

    def test_eine_mengenzeile_mit_angabe_geht_weiterhin(
        self, als_mitarbeiter, projekt, mengenleistung
    ):
        """Gegenprobe: Eine angegebene Menge wird gespeichert."""
        als_mitarbeiter.post(reverse(ANLEGEN), _formular(
            projekt, mengenleistung, menge='23'))

        assert Erfassungszeile.objects.get().menge == Decimal('23.000')


@pytest.mark.django_db
class TestBeschreibungIstFreiwillig:
    """Die Beschreibung ist optional.

    Eine Anfahrt braucht keine. Auch Zeitzeilen kommen ohne aus; auf dem
    Regiebericht steht dann nur die Leistung.
    """

    def test_ohne_beschreibung_wird_gespeichert(
        self, als_mitarbeiter, projekt, mengenleistung
    ):
        daten = _formular(projekt, mengenleistung)
        daten['beschreibung'] = ''
        daten['menge'] = '23'

        als_mitarbeiter.post(reverse(ANLEGEN), daten)

        zeile = Erfassungszeile.objects.get()
        assert zeile.beschreibung == ''
        assert zeile.menge == Decimal('23.000')

    def test_auch_bei_einer_zeitzeile(
        self, als_mitarbeiter, projekt, zeitleistung
    ):
        daten = _formular(projekt, zeitleistung, von='09:00', bis='12:00')
        daten['beschreibung'] = ''

        als_mitarbeiter.post(reverse(ANLEGEN), daten)

        assert Erfassungszeile.objects.get().dauer_minuten == 180

    def test_das_feld_ist_nicht_mehr_als_pflicht_ausgezeichnet(
        self, als_mitarbeiter
    ):
        inhalt = als_mitarbeiter.get(reverse(ANLEGEN)).content.decode()
        feld = re.search(r'<input[^>]*id="id_beschreibung"[^>]*>', inhalt)

        assert feld is not None
        assert 'required' not in feld.group(0)


@pytest.mark.django_db
class TestProjektauswahl:

    def test_abgeschlossene_stehen_nicht_zur_wahl(
        self, als_mitarbeiter, projekt, abgeschlossenes_projekt
    ):
        inhalt = als_mitarbeiter.get(reverse(ANLEGEN)).content.decode()

        assert str(projekt) in inhalt
        assert str(abgeschlossenes_projekt) not in inhalt

    def test_am_bestehenden_eintrag_bleibt_es_stehen(
        self, als_mitarbeiter, projekt, zeitleistung, mitarbeiter
    ):
        """An bestehenden Einträgen bleibt der gespeicherte Wert wählbar."""
        zeile = services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Arbeit',
        )
        Projekt.objects.filter(pk=projekt.pk).update(abgeschlossen=True)

        inhalt = als_mitarbeiter.get(
            reverse(AENDERN, args=[zeile.pk])).content.decode()

        assert str(projekt) in inhalt


@pytest.mark.django_db
class TestSummeUeberDerListe:

    def test_zeigt_die_summe_des_gefilterten_bestandes(
        self, als_mitarbeiter, projekt, zeitleistung, mitarbeiter
    ):
        from datetime import time
        for von, bis in [(time(8, 0), time(9, 30)), (time(13, 0), time(15, 15))]:
            services.zeile_erfassen(
                projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
                von=von, bis=bis, beschreibung='Arbeit',
            )

        antwort = als_mitarbeiter.get(reverse(LISTE))

        # Geprüft im gerenderten HTML, weil ein Wert im Kontext nicht heißt,
        # dass das Template ihn ausgibt.
        assert antwort.context_data['zeitsumme'] == '3:45'
        assert '3:45' in antwort.content.decode()
        assert 'Summe des angezeigten Zeitraums' in antwort.content.decode()

    def test_fremde_zeilen_zaehlen_nicht_mit(
        self, als_mitarbeiter, projekt, zeitleistung, mitarbeiter, fremde_zeile
    ):
        """Die Summe zählt nur sichtbare Zeilen, damit sie keine fremden
        Stunden offenlegt."""
        from datetime import time
        services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            von=time(8, 0), bis=time(9, 0), beschreibung='Meine Arbeit',
        )

        antwort = als_mitarbeiter.get(reverse(LISTE))

        assert antwort.context_data['zeitsumme'] == '1:00'


@pytest.mark.django_db
class TestDatumsregelImFormular:

    def test_die_zukunft_wird_am_feld_abgewiesen(
        self, als_mitarbeiter, projekt, zeitleistung
    ):
        morgen = timezone.localdate() + timedelta(days=1)

        antwort = als_mitarbeiter.post(reverse(ANLEGEN), _formular(
            projekt, zeitleistung, datum=morgen.strftime('%d.%m.%Y')))

        assert not Erfassungszeile.objects.exists()
        assert 'nicht im Voraus' in antwort.content.decode()


@pytest.mark.django_db
class TestAbrechenbarGehoertDerLeitung:
    """"abrechenbar" setzt nur, wer für andere erfassen darf, weil es eine
    kaufmännische Entscheidung ist.

    Das Feld fehlt im Formular der übrigen Benutzer und lässt sich deshalb
    auch per POST nicht setzen.
    """

    def test_beim_mitarbeiter_steht_es_nicht_im_formular(self, als_mitarbeiter):
        antwort = als_mitarbeiter.get(reverse(ANLEGEN))

        assert 'name="abrechenbar"' not in antwort.content.decode()

    def test_beim_chef_steht_es_da(self, als_chef):
        """Gegenprobe."""
        antwort = als_chef.get(reverse(ANLEGEN))

        assert 'name="abrechenbar"' in antwort.content.decode()

    def test_der_mitarbeiter_kommt_auch_per_post_nicht_daran(
        self, als_mitarbeiter, projekt, zeitleistung
    ):
        """Ein mitgesendetes Feld "abrechenbar" wird ignoriert."""
        als_mitarbeiter.post(reverse(ANLEGEN), _formular(
            projekt, zeitleistung, abrechenbar=''))

        assert Erfassungszeile.objects.get().abrechenbar is True

    def test_der_chef_darf_es_ausschalten(self, als_chef, projekt,
                                          zeitleistung, kollege):
        als_chef.post(reverse(ANLEGEN), _formular(
            projekt, zeitleistung, benutzer=kollege.pk))

        assert Erfassungszeile.objects.get().abrechenbar is False


@pytest.mark.django_db
class TestZustandInDerListe:

    def test_die_spalte_zeigt_den_zustand(self, als_mitarbeiter, projekt,
                                          zeitleistung, mitarbeiter):
        services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Arbeit',
        )
        antwort = als_mitarbeiter.get(reverse(LISTE))

        assert _zelle(antwort.content.decode(), 'zustand') == 'Offen'

    def test_der_zustandsfilter_trennt(self, als_mitarbeiter, projekt,
                                       zeitleistung, mitarbeiter):
        services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Wird berechnet',
        )
        services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Kulanz', abrechenbar=False,
        )

        antwort = als_mitarbeiter.get(reverse(LISTE), {'zustand': 'offen'})
        inhalt = antwort.content.decode()

        assert 'Wird berechnet' in inhalt
        assert 'Kulanz' not in inhalt

    def test_ein_erfundener_zustand_wirft_keinen_serverfehler(
        self, als_mitarbeiter
    ):
        """Ein unbekannter Zustand in der URL ergibt keine 500.

        Django fängt ``IncorrectLookupParameters`` und zeigt die ungefilterte
        Liste. Ein ``ValueError`` ergäbe eine 500, weil der Filter in
        ``django/contrib/admin/views/main.py`` außerhalb des try-Blocks
        aufgerufen wird.
        """
        antwort = als_mitarbeiter.get(reverse(LISTE), {'zustand': 'vielleicht'})

        assert antwort.status_code == 302
        assert antwort['Location'].endswith('?e=1')


@pytest.mark.django_db
class TestZeitraumfilterInDerListe:
    """Zeitraumfilter wie „letzter Monat“ und „letztes Quartal“."""

    def test_letzter_monat_laesst_heute_draussen(self, als_mitarbeiter, projekt,
                                                 zeitleistung, mitarbeiter):
        services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Von heute',
        )

        antwort = als_mitarbeiter.get(reverse(LISTE),
                                      {'zeitraum': 'letzter_monat'})

        assert 'Von heute' not in antwort.content.decode()

    def test_dieser_monat_nimmt_heute_mit(self, als_mitarbeiter, projekt,
                                          zeitleistung, mitarbeiter):
        """Gegenprobe: "dieser Monat" enthält heute."""
        services.zeile_erfassen(
            von=time(8, 0), bis=time(10, 0),
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            beschreibung='Von heute',
        )

        antwort = als_mitarbeiter.get(reverse(LISTE),
                                      {'zeitraum': 'dieser_monat'})

        assert 'Von heute' in antwort.content.decode()

    def test_ein_erfundener_zeitraum_wirft_keinen_serverfehler(
        self, als_mitarbeiter
    ):
        antwort = als_mitarbeiter.get(reverse(LISTE),
                                      {'zeitraum': 'vorletztes_quartal'})

        assert antwort.status_code == 302
        assert antwort['Location'].endswith('?e=1')


@pytest.mark.django_db
class TestDieZwischenseiteVorDemUebernehmen:
    """Vorschau vor der Übernahme in eine Rechnung.

    Prüft das Template; den Service prüft erfassung/tests/test_uebernehmen.py.
    """

    def _aufrufen(self, client, zeilen):
        return client.post(reverse(LISTE), {
            'action': 'in_rechnung',
            '_selected_action': [str(z.pk) for z in zeilen],
            'index': '0',
        })

    def test_sie_wird_ausgeliefert(self, als_uebernehmer, projekt,
                                   zeitleistung, mitarbeiter):
        zeile = services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            von=time(9, 0), bis=time(12, 0), beschreibung='Montage',
        )

        antwort = self._aufrufen(als_uebernehmer, [zeile])

        assert antwort.status_code == 200
        inhalt = antwort.content.decode()
        assert 'Das wird daraus' in inhalt
        assert 'Montage' in inhalt

    def test_das_auswahlfeld_traegt_die_klassen_der_oberflaeche(
        self, als_uebernehmer, projekt, zeitleistung, mitarbeiter
    ):
        """Das im Template gerenderte Auswahlfeld hat Unfolds CSS-Klassen aus
        dem Kontext (core/adminhilfen.AUSWAHL_KLASSEN)."""
        zeile = services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            von=time(9, 0), bis=time(12, 0), beschreibung='Montage',
        )

        inhalt = self._aufrufen(als_uebernehmer, [zeile]).content.decode()
        anfang = inhalt.index('<select name="ziel"')
        feld = inhalt[anfang:inhalt.index('>', anfang) + 1]

        assert 'rounded-default' in feld, feld

    def test_uebergangene_zeilen_werden_genannt(self, als_uebernehmer, projekt,
                                                zeitleistung, mitarbeiter):
        """Übergangene Zeilen werden gemeldet."""
        mit = services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            von=time(9, 0), bis=time(12, 0), beschreibung='Montage',
        )
        ohne = services.zeile_erfassen(
            projekt=projekt, leistung=zeitleistung, benutzer=mitarbeiter,
            von=time(13, 0), bis=time(14, 0), beschreibung='Kulanzarbeit',
        )
        Erfassungszeile.objects.filter(pk=ohne.pk).update(abrechenbar=False)

        inhalt = self._aufrufen(als_uebernehmer, [mit, ohne]).content.decode()

        assert 'Diese Zeilen kommen nicht mit' in inhalt
        assert 'nicht abrechenbar' in inhalt


@pytest.mark.django_db
class TestWeitererfassen:
    """"Sichern und neu hinzufügen" übernimmt Projekt und Person.

    Mehrere Zeilen nacheinander gehören meist zum selben Projekt.
    """

    def test_das_projekt_steht_in_der_naechsten_maske_schon_da(
            self, als_mitarbeiter, projekt, zeitleistung):
        antwort = als_mitarbeiter.post(
            reverse(ANLEGEN), _formular(projekt, zeitleistung, _addanother='1'))

        assert antwort.status_code == 302
        assert f'projekt={projekt.pk}' in antwort['Location']

        naechste = als_mitarbeiter.get(antwort['Location'])
        vorbelegt = naechste.context['adminform'].form.initial
        assert vorbelegt['projekt'] == str(projekt.pk)

    def test_gewoehnliches_sichern_belegt_nichts_vor(
            self, als_mitarbeiter, projekt, zeitleistung):
        """Gegenprobe: "Sichern" belegt nichts vor."""
        antwort = als_mitarbeiter.post(
            reverse(ANLEGEN), _formular(projekt, zeitleistung))

        assert 'projekt=' not in antwort['Location']

    def test_wer_fuer_andere_erfasst_behaelt_auch_die_person(
            self, als_chef, projekt, zeitleistung, mitarbeiter):
        """Mit Recht für andere wird auch die Person übernommen, etwa beim
        Abtippen eines fremden Stundenzettels."""
        antwort = als_chef.post(reverse(ANLEGEN), _formular(
            projekt, zeitleistung, benutzer=mitarbeiter.pk, _addanother='1'))

        assert f'benutzer={mitarbeiter.pk}' in antwort['Location']


@pytest.mark.django_db
class TestNurDiePassendenFelder:
    """Die Maske zeigt nur die Felder der gewählten Leistungsart.

    Eine Anfahrt hat kein "von", eine Pauschale keine Menge (Uhrzeiten nimmt
    sie als Aufwand für das Controlling). Sonst lehnte erst ``clean()`` nach
    dem Speichern eine falsche Angabe ab.
    """

    def test_die_auswahlliste_sagt_die_art_gleich_mit(
            self, als_mitarbeiter, zeitleistung, mengenleistung):
        """Jede Option trägt die Leistungsart als ``data-art``."""
        seite = als_mitarbeiter.get(reverse(ANLEGEN)).content.decode()

        assert f'value="{zeitleistung.pk}" data-art="zeit"' in seite
        assert f'value="{mengenleistung.pk}" data-art="menge"' in seite

    def test_von_bis_und_menge_haengen_an_beiden_grundlagen(
            self, als_mitarbeiter, zeitleistung):
        """Die Ausdrücke für von, bis und Menge lesen beide Grundlagen.

        Alpine wertet einen Ausdruck nur bei Änderung der darin gelesenen
        Felder neu aus. Stünde nur ``leistung`` darin, reagierte die Maske
        nicht auf einen Wechsel zur Auftragsposition.
        """
        seite = als_mitarbeiter.get(reverse(ANLEGEN)).content.decode()

        beide = '(auftragsposition || leistung)'
        zeit = (f'{beide} &amp;&amp; [&#x27;zeit&#x27;, &#x27;pauschale&#x27;]'
                f'.includes(erfassungsart())')
        assert seite.count(f'x-show="{zeit}"') == 2  # von und bis
        assert (f'x-show="{beide} &amp;&amp; erfassungsart() == '
                '&#x27;menge&#x27;"') in seite

    def test_erst_das_vorhaben_dann_die_position(self, als_mitarbeiter,
                                                 zeitleistung):
        """Ohne Projekt keine Positionsauswahl; mit gewählter Position kein
        Katalog.

        Die zweite Regel prüft auch ``_pruefe_grundlage``; die Maske blendet
        das Feld vorher aus.
        """
        seite = als_mitarbeiter.get(reverse(ANLEGEN)).content.decode()

        assert 'x-show="projekt"' in seite
        assert 'x-show="projekt &amp;&amp; !auftragsposition"' in seite
        assert 'erfassung/js/erfassungsauswahl.js?stand=' in seite

    def test_die_maske_bringt_ihr_skript_und_ihre_breiten_mit(
            self, als_mitarbeiter, zeitleistung):
        seite = als_mitarbeiter.get(reverse(ANLEGEN)).content.decode()

        assert 'erfassung/js/erfassungsart.js?stand=' in seite
        assert 'erfassung/css/erfassung_admin.css?stand=' in seite


class TestDieMixinReihenfolge:
    """MRO und Methoden der Mixins von ``ErfassungszeileAdmin``.

    Wie bei ``BelegAdmin``: Eine geänderte Reihenfolge der Basisklassen oder
    dieselbe Methode in zwei Mixins ändert das Verhalten ohne
    Fehlermeldung.
    """

    @staticmethod
    def _eigene_mixins():
        from erfassung.admin import ErfassungszeileAdmin

        return [k for k in ErfassungszeileAdmin.__mro__
                if k.__module__.startswith('erfassung.admin.')
                and k.__name__.endswith('Mixin')]

    def test_die_eigenen_mixins_stehen_vor_dem_modeladmin(self):
        from unfold import admin as unfold_admin

        from erfassung.admin import ErfassungszeileAdmin

        mro = list(ErfassungszeileAdmin.__mro__)
        grenze = mro.index(unfold_admin.ModelAdmin)

        eigene = self._eigene_mixins()
        assert eigene, 'keine Mixins gefunden'
        for mixin in eigene:
            assert mro.index(mixin) < grenze, (
                f'{mixin.__name__} steht hinter ModelAdmin; seine Methoden '
                f'gelten dann nicht'
            )

    def test_kein_mixin_ueberschreibt_ein_anderes(self):
        """Keine Methode ist in zwei Mixins definiert."""
        gesehen = {}
        doppelt = []

        for mixin in self._eigene_mixins():
            for name in vars(mixin):
                if name.startswith('__'):
                    continue
                if name in gesehen:
                    doppelt.append(
                        f'{name}: {gesehen[name]} und {mixin.__name__}')
                gesehen[name] = mixin.__name__

        assert not doppelt, 'mehrfach definiert; ' + '; '.join(doppelt)

    @pytest.mark.django_db
    def test_die_maske_laedt_immer_noch(self, als_mitarbeiter):
        """Die Maske lädt mit allen Mixins, etwa wenn eine Methode Attribute
        eines anderen Mixins braucht."""
        antwort = als_mitarbeiter.get(reverse(ANLEGEN))

        assert antwort.status_code == 200


class TestEinOffenerAuftragIstNichtBebuchbar:
    """Positionen eines wieder geöffneten Auftrags sind nicht bebuchbar.

    Festlegung: Ein Auftrag, dessen Positionen gerade geändert werden, ist
    keine verlässliche Grundlage für eine Buchung; kontiert wird nach dem
    erneuten Festschreiben. Beim Öffnen erklärt ein Hinweis die dann leere
    Auswahl (``faktura.admin.belegkette``).
    """

    @pytest.fixture
    def auftrag_mit_position(self, projekt, zeitleistung):
        auftrag = Beleg.objects.create(
            typ=BelegTyp.AUFTRAG, status=BelegStatus.FESTGESCHRIEBEN,
            nummer='AU-2026-0099', projekt=projekt)
        Belegposition.objects.bulk_create([
            Belegposition(
                beleg=auftrag, position=10, bezeichnung='Rohbau begleiten',
                menge=Decimal('50'), einheit='Std',
                einzelpreis=Decimal('95.00'), art=zeitleistung.art)])
        return auftrag

    def _auswahl(self, client):
        """Positionen in der Auswahl "Auftragsposition"."""
        antwort = client.get(reverse(ANLEGEN))
        feld = antwort.context['adminform'].form.fields['auftragsposition']
        return [str(p) for p in feld.queryset]

    def test_festgeschrieben_steht_er_zur_wahl(self, als_mitarbeiter,
                                               auftrag_mit_position):
        assert any('Rohbau begleiten' in e
                   for e in self._auswahl(als_mitarbeiter))

    def test_wieder_geoeffnet_verschwindet_er(self, als_mitarbeiter,
                                              auftrag_mit_position):
        """Nach dem Öffnen fehlen die Positionen des Auftrags in der
        Auswahl."""
        from faktura import services as faktura_services

        faktura_services.beleg_wiedereroeffnen(
            beleg_id=auftrag_mit_position.pk)

        assert not any('Rohbau begleiten' in e
                       for e in self._auswahl(als_mitarbeiter))

    def test_und_ist_nach_dem_zuschreiben_wieder_da(self, als_mitarbeiter,
                                                    auftrag_mit_position):
        """Nach dem erneuten Festschreiben sind sie wieder wählbar."""
        from faktura import services as faktura_services

        faktura_services.beleg_wiedereroeffnen(
            beleg_id=auftrag_mit_position.pk)
        faktura_services.beleg_festschreiben(beleg_id=auftrag_mit_position.pk)

        assert any('Rohbau begleiten' in e
                   for e in self._auswahl(als_mitarbeiter))
