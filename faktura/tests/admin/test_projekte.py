"""Projekte im Admin und im Belegformular."""

import re
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from faktura import services
from faktura.models import (
    Beleg,
    Belegposition,
    BelegTyp,
    Kontakt,
    Projekt,
)


@pytest.mark.django_db
class TestProjektAdmin:

    def test_das_leere_formular_traegt_schon_eine_nummer(self, buero):
        """Das leere Formular zeigt die nächste Projektnummer, wie beim
        Kunden, mit Zähler je Jahr."""
        antwort = buero.get(reverse('admin:faktura_projekt_add'))

        vorgabe = antwort.context['adminform'].form.initial['nummer']
        assert vorgabe.startswith(f'{timezone.localdate().year}-')

    def test_das_formular_oeffnen_verbraucht_keine_nummer(self, buero):
        """Öffnen des Formulars verbraucht keine Nummer, wie beim Kunden."""
        erste = buero.get(reverse('admin:faktura_projekt_add')
                          ).context['adminform'].form.initial['nummer']
        zweite = buero.get(reverse('admin:faktura_projekt_add')
                           ).context['adminform'].form.initial['nummer']

        assert erste == zweite

    def test_der_vorschlag_schliesst_an_den_bestand_an(self, buero, kunde):
        """Der Vorschlag folgt auf die höchste vorhandene Nummer."""
        jahr = timezone.localdate().year
        Projekt.objects.create(nummer=f'{jahr}-042', bezeichnung='Schon da',
                               kunde=kunde)

        vorschlag = buero.get(reverse('admin:faktura_projekt_add')
                              ).context['adminform'].form.initial['nummer']

        assert vorschlag == f'{jahr}-043'

    def test_die_vorgeschlagene_nummer_ist_ueberschreibbar(self, buero, kunde):
        """Die vorgeschlagene Projektnummer ist überschreibbar, weil
        Projektnummern oft extern vorgegeben sind."""
        antwort = buero.post(reverse('admin:faktura_projekt_add'), {
            'nummer': 'BV-Halle-Nord',
            'bezeichnung': 'Halle Nord',
            'kunde': kunde.pk,
            'beschreibung': '',
            'notiz': '',
            # Das Projekt hat ein Inline (Fremdleistungen aus
            # erfassung/admin.py); ohne dessen Management Form verwirft
            # Django den POST ohne Fehlermeldung mit 200.
            'fremdleistungen-TOTAL_FORMS': '0',
            'fremdleistungen-INITIAL_FORMS': '0',
            'fremdleistungen-MIN_NUM_FORMS': '0',
            'fremdleistungen-MAX_NUM_FORMS': '1000',
        })

        assert antwort.status_code == 302
        assert Projekt.objects.filter(nummer='BV-Halle-Nord').exists()


@pytest.mark.django_db
class TestProjektAlsKlammer:
    """Ein Beleg gehört einem Kunden, einem Projekt oder keinem von beiden.

    Kunde und Projekt zugleich werden abgelehnt, damit keine implizite
    Vorrangregel entscheidet. Verworfen: eine Vorrangregel.

    Drei zulässige Zustände:

    ==========  ===========================================
    nichts      Anschrift wird von Hand eingetragen
    nur Kunde   Anschrift aus seinen Stammdaten
    nur Projekt Anschrift aus dem Kunden des Projekts
    ==========  ===========================================
    """

    @pytest.fixture
    def projekt(self, kunde):
        return Projekt.objects.create(
            nummer='2026-042',
            bezeichnung='Halle Nord, Dachsanierung',
            kunde=kunde,
        )

    # --- Validierung ---

    def test_kunde_und_projekt_zugleich_wird_abgewiesen(self, kunde, projekt):
        beleg = Beleg(typ=BelegTyp.ANGEBOT, kunde=kunde, projekt=projekt)

        with pytest.raises(ValidationError) as fehler:
            beleg.clean()

        assert 'projekt' in fehler.value.message_dict

    def test_die_datenbank_haelt_dieselbe_regel(self, kunde, projekt):
        """Der Constraint greift auch ohne clean() (Import, Shell, Skript)."""
        from django.db import IntegrityError, transaction

        with pytest.raises(IntegrityError), transaction.atomic():
            # Ohne clean(), wie ein Importskript.
            Beleg.objects.create(
                typ=BelegTyp.ANGEBOT, kunde=kunde, projekt=projekt
            )

    def test_nur_kunde_ist_erlaubt(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)

        assert beleg.kunde == kunde
        assert beleg.projekt is None

    def test_nur_projekt_ist_erlaubt(self, projekt):
        beleg = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.ANGEBOT)

        assert beleg.projekt == projekt
        assert beleg.kunde is None

    def test_ganz_ohne_zuordnung_ist_erlaubt(self, db):
        """Ein Beleg ohne Kunde und Projekt mit manueller Anschrift ist
        zulässig."""
        beleg = services.beleg_anlegen(typ=BelegTyp.ANGEBOT, betreff='Frei')

        assert beleg.kunde is None
        assert beleg.projekt is None
        assert beleg.empfaenger == ''

    # --- Herkunft der Anschrift ---

    def test_das_projekt_liefert_die_anschrift_seines_kunden(self, projekt, kunde):
        """Mit Projekt kommt die Anschrift von dessen Kunden."""
        beleg = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.ANGEBOT)

        assert beleg.empfaenger == kunde.anschriftfeld
        assert beleg.empfaenger_name == kunde.name
        assert beleg.empfaenger_plz == kunde.plz
        assert beleg.zahlungsziel_tage == kunde.zahlungsziel_tage

    def test_anschriftgeber_ist_die_einzige_auskunft(self, kunde, projekt, db):
        """``anschriftgeber`` deckt alle drei Fälle ab, damit keine eigene
        or-Verkettung nötig ist."""
        assert services.anschriftgeber(
            Beleg(typ=BelegTyp.ANGEBOT, kunde=kunde)) == kunde
        assert services.anschriftgeber(
            Beleg(typ=BelegTyp.ANGEBOT, projekt=projekt)) == kunde
        assert services.anschriftgeber(Beleg(typ=BelegTyp.ANGEBOT)) is None

    def test_die_anschrift_bleibt_kopiert(self, projekt, kunde):
        """Die Anschrift bleibt kopiert.

        Ein späterer Kundenwechsel des Projekts ändert bestehende Belege
        nicht, damit der Beleg im System dem versendeten entspricht.
        """
        beleg = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.ANGEBOT)
        vorher = beleg.empfaenger

        anderer = Kontakt.objects.create(nummer='K-999', name='Ganz Anders GmbH')
        projekt.kunde = anderer
        projekt.save()
        beleg.refresh_from_db()

        assert beleg.empfaenger == vorher
        assert 'Anders' not in beleg.empfaenger

    # --- Übernahme in Folgebelege ---

    def test_storno_erbt_das_projekt(self, projekt):
        """Das Storno übernimmt das Projekt, damit alle Belege eines Vorhabens
        zugeordnet bleiben."""
        rechnung = services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG, leistungsdatum=timezone.localdate()
        )
        Belegposition.objects.create(
            beleg=rechnung, position=10, bezeichnung='Arbeit',
            menge=Decimal('1'), einzelpreis=Decimal('100.00'),
        )
        services.beleg_festschreiben(beleg_id=rechnung.pk)
        rechnung.refresh_from_db()

        storno, _ = services.rechnung_korrigieren(beleg_id=rechnung.pk)

        assert storno.projekt == projekt
        assert storno.kunde is None

    # --- PDF und E-Rechnung ---

    def test_das_projekt_steht_im_infoblock(self, projekt):
        from faktura import pdf

        beleg = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.ANGEBOT)
        html = pdf.beleg_als_html(beleg)

        assert projekt.nummer in html
        assert projekt.bezeichnung in html

    def test_ohne_kunde_keine_leere_kundennummer(self, projekt):
        """Ohne Kunde keine leere Zeile "Kundennummer:"."""
        from faktura import pdf

        beleg = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.ANGEBOT)
        html = pdf.beleg_als_html(beleg)

        assert 'Kundennummer' not in html

    def test_die_erechnung_traegt_das_projekt_als_bt11(self, projekt):
        """Das Projekt steht als BT-11 (SpecifiedProcuringProject) in der
        E-Rechnung, damit der Empfänger die Belege eines Vorhabens
        zuordnen kann."""
        from faktura import facturx

        rechnung = self._festgeschriebene_rechnung(projekt=projekt)
        xml = facturx.xml_und_metadaten(rechnung)[0].read().decode()

        assert '<ram:SpecifiedProcuringProject>' in xml
        assert f'<ram:ID>{projekt.nummer}</ram:ID>' in xml
        assert f'<ram:Name>{projekt.bezeichnung}</ram:Name>' in xml

    def test_ohne_projekt_bleibt_der_block_weg(self, kunde):
        """Ohne Projekt kein BT-11-Block, weil Validatoren ein leeres Element
        als Fehler melden."""
        from faktura import facturx

        rechnung = self._festgeschriebene_rechnung(kunde=kunde)
        xml = facturx.xml_und_metadaten(rechnung)[0].read().decode()

        assert 'SpecifiedProcuringProject' not in xml

    @staticmethod
    def _festgeschriebene_rechnung(**zuordnung):
        rechnung = services.beleg_anlegen(
            typ=BelegTyp.RECHNUNG, leistungsdatum=timezone.localdate(), **zuordnung
        )
        Belegposition.objects.create(
            beleg=rechnung, position=10, bezeichnung='Arbeit',
            menge=Decimal('1'), einzelpreis=Decimal('100.00'),
        )
        services.beleg_festschreiben(beleg_id=rechnung.pk)
        rechnung.refresh_from_db()
        return rechnung


@pytest.mark.django_db
class TestProjektImFormular:
    """Projekt im Belegformular."""

    @pytest.fixture
    def projekt(self, kunde):
        return Projekt.objects.create(
            nummer='2026-042', bezeichnung='Halle Nord', kunde=kunde
        )

    def test_beide_felder_stehen_im_formular(self, buero, projekt):
        inhalt = buero.get(reverse('admin:faktura_angebot_add')).content.decode()

        assert 'id="id_kunde"' in inhalt
        assert 'id="id_projekt"' in inhalt

    def test_beide_felder_kennen_den_stammdatendienst(self, buero, projekt):
        """Kunde und Projekt haben das Attribut mit der URL des
        Stammdaten-Endpunkts; das Skript bildet den Parameter aus dem
        Feldnamen. Ohne Attribut füllt sich das Formular ohne Fehler
        nicht."""
        inhalt = buero.get(reverse('admin:faktura_angebot_add')).content.decode()

        for feld in ('id_kunde', 'id_projekt'):
            stelle = inhalt.index(f'id="{feld}"')
            anfang = inhalt.rindex('<select', 0, stelle)
            select = inhalt[anfang:inhalt.index('>', stelle) + 1]
            assert 'data-stammdaten-url' in select, f'{feld}: {select}'

    def test_der_dienst_antwortet_auch_auf_projekte(self, buero, projekt, kunde):
        antwort = buero.get(
            reverse('admin:faktura_angebot_kundendaten'), {'projekt': projekt.pk}
        )

        assert antwort.status_code == 200
        assert antwort.json()['empfaenger_name'] == kunde.name

    def test_abgeschlossene_projekte_stehen_nicht_zur_wahl(self, buero, projekt):
        projekt.abgeschlossen = True
        projekt.save()

        antwort = buero.get(reverse('admin:faktura_angebot_add'))
        formular = antwort.context['adminform'].form

        assert projekt not in formular.fields['projekt'].queryset

    def test_ein_abgeschlossenes_bleibt_am_eigenen_beleg_sichtbar(
        self, buero, projekt
    ):
        """Ein abgeschlossenes Projekt bleibt am eigenen Beleg auswählbar,
        damit es beim Speichern nicht verloren geht."""
        beleg = services.beleg_anlegen(projekt=projekt, typ=BelegTyp.ANGEBOT)
        projekt.abgeschlossen = True
        projekt.save()

        antwort = buero.get(
            reverse('admin:faktura_angebot_change', args=[beleg.pk])
        )
        formular = antwort.context['adminform'].form

        assert projekt in formular.fields['projekt'].queryset

    def test_ueber_das_formular_angelegt_kommt_die_anschrift_mit(
        self, buero, projekt, kunde
    ):
        """Beim Anlegen über das Formular wird die Anschrift übernommen."""
        buero.post(reverse('admin:faktura_angebot_add'), {
            'projekt': projekt.pk, 'betreff': 'Aus dem Formular',
            'empfaenger': '', 'empfaenger_ust_id': '',
            'empfaenger_land': 'DE', 'zahlungsziel_tage': '14',
            'belegdatum': '', 'leistungsdatum': '', 'leistungsdatum_bis': '',
            'kopftext': '', 'fusstext': '',
            'positionen-TOTAL_FORMS': '0', 'positionen-INITIAL_FORMS': '0',
            'positionen-MIN_NUM_FORMS': '0', 'positionen-MAX_NUM_FORMS': '1000',
        }, follow=True)

        beleg = Beleg.objects.get(betreff='Aus dem Formular')
        assert beleg.projekt == projekt
        assert beleg.kunde is None
        assert beleg.empfaenger == kunde.anschriftfeld

    def test_das_formular_weist_beides_zugleich_ab(self, buero, projekt, kunde):
        antwort = buero.post(reverse('admin:faktura_angebot_add'), {
            'kunde': kunde.pk, 'projekt': projekt.pk, 'betreff': 'Beides',
            'empfaenger': 'Von Hand', 'empfaenger_ust_id': '',
            'empfaenger_land': 'DE', 'zahlungsziel_tage': '14',
            'belegdatum': '', 'leistungsdatum': '', 'leistungsdatum_bis': '',
            'kopftext': '', 'fusstext': '',
            'positionen-TOTAL_FORMS': '0', 'positionen-INITIAL_FORMS': '0',
            'positionen-MIN_NUM_FORMS': '0', 'positionen-MAX_NUM_FORMS': '1000',
        })

        assert not Beleg.objects.filter(betreff='Beides').exists()
        assert antwort.status_code == 200, 'kein erneutes Formular mit Fehler'


@pytest.mark.django_db
class TestDieProjektspalte:
    """Spalte Projekt in den Listen von Angebot und Auftrag.

    Nur dort, weil die Zuordnung zum Vorhaben bei Angeboten und Aufträgen
    vorrangig ist und bei Rechnungen bereits feststeht.
    """

    @pytest.fixture
    def projekt(self, kunde):
        from faktura.models import Projekt

        return Projekt.objects.create(
            nummer='2026-042', bezeichnung='Halle Nord', kunde=kunde)

    def _beleg(self, projekt, typ):
        beleg = services.beleg_anlegen(projekt=projekt, typ=typ,
                                       betreff='Rohbau')
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Montage', menge=Decimal('1'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00')
        return beleg

    def test_das_angebot_zeigt_sein_projekt(self, buero, projekt):
        self._beleg(projekt, BelegTyp.ANGEBOT)

        inhalt = buero.get(
            reverse('admin:faktura_angebot_changelist')).content.decode()

        assert 'field-projekt_zeile' in inhalt
        assert '2026-042 Halle Nord' in inhalt

    def test_der_auftrag_auch(self, buero, projekt):
        self._beleg(projekt, BelegTyp.AUFTRAG)

        inhalt = buero.get(
            reverse('admin:faktura_auftrag_changelist')).content.decode()

        assert 'field-projekt_zeile' in inhalt
        assert '2026-042 Halle Nord' in inhalt

    def test_ohne_projekt_bleibt_die_zelle_leer(self, buero, kunde):
        """Ohne Projekt bleibt die Zelle leer, ohne Strich."""
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT,
                                       betreff='Direkt an den Kunden')
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Montage', menge=Decimal('1'),
            einzelpreis=Decimal('100.00'), steuersatz='19.00')

        inhalt = buero.get(
            reverse('admin:faktura_angebot_changelist')).content.decode()

        zelle = re.search(
            r'<td class="field-projekt_zeile[\s"][^>]*>(.*?)</td>',
            inhalt, re.S)
        assert zelle is not None
        assert zelle.group(1).strip() in ('', '-')

    def test_die_spalte_laesst_sich_sortieren(self, buero, projekt):
        """Sortiert wird nach Projektnummer, weil der Fremdschlüssel nach
        Reihenfolge der Anlage sortierte."""
        self._beleg(projekt, BelegTyp.ANGEBOT)

        antwort = buero.get(
            reverse('admin:faktura_angebot_changelist'), {'o': '2'})

        assert antwort.status_code == 200

    def test_die_rechnungsliste_bleibt_wie_sie_war(self, buero,
                                                   rechnungsentwurf):
        inhalt = buero.get(
            reverse('admin:faktura_rechnung_changelist')).content.decode()

        assert 'field-projekt_zeile' not in inhalt
