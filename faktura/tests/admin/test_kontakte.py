"""Kunden- und Dokumentverwaltung im Admin."""

import pytest
from django.urls import reverse

from faktura import services
from faktura.models import (
    Kontakt,
)
from faktura.tests.admin.hilfen import kundenformular


@pytest.mark.django_db
class TestKundeAdmin:
    def test_liste_laedt(self, buero, kunde):
        assert buero.get(reverse('admin:faktura_kontakt_changelist')).status_code == 200

    def test_suche_laedt(self, buero, kunde):
        antwort = buero.get(reverse('admin:faktura_kontakt_changelist'), {'q': 'Muster'})

        assert antwort.status_code == 200
        assert list(antwort.context['cl'].queryset) == [kunde]

    def test_das_leere_formular_traegt_schon_eine_nummer(self, buero):
        """Das leere Kundenformular zeigt die nächste Kundennummer.

        Regression: Die Nummer war erst nach dem Speichern sichtbar."""
        antwort = buero.get(reverse('admin:faktura_kontakt_add'))

        vorgabe = antwort.context['adminform'].form.initial['nummer']
        assert vorgabe.startswith('K-')

    def test_das_formular_oeffnen_verbraucht_keine_nummer(self, buero):
        """Öffnen des Formulars ohne Speichern verbraucht keine Nummer.

        Regression: Der Vorschlag inkrementierte den Zähler. Jetzt wird der
        Bestand gelesen; zweimaliges Öffnen ergibt dieselbe Nummer.
        """
        erste = buero.get(reverse('admin:faktura_kontakt_add')
                          ).context['adminform'].form.initial['nummer']
        zweite = buero.get(reverse('admin:faktura_kontakt_add')
                           ).context['adminform'].form.initial['nummer']

        assert erste == zweite

    def test_beim_aendern_wird_nichts_vorgeschlagen(self, buero, kunde):
        """Im Änderungsformular kein Vorschlag, damit die Nummer eines
        bestehenden Kunden bleibt; Django verwendet den Initialwert nur beim
        Anlegen."""
        antwort = buero.get(
            reverse('admin:faktura_kontakt_change', args=[kunde.pk]))

        assert antwort.context['adminform'].form.initial['nummer'] == 'K-1000'

    def test_anlegen_ohne_nummer_geht(self, buero):
        """Anlegen mit leerem Nummernfeld über das Formular.

        Zusätzlich zum Test am Modell, weil ``blank=True`` und nicht
        ``save()`` bestimmt, ob das Formular die Nummer als Pflichtfeld
        verlangt.
        """
        antwort = buero.post(reverse('admin:faktura_kontakt_add'),
                             kundenformular(name='Ohne Nummer GmbH'))

        assert antwort.status_code == 302, antwort.content.decode()[:400]
        angelegt = Kontakt.objects.get(name='Ohne Nummer GmbH')
        assert angelegt.nummer.startswith('K-')

    def test_autocomplete_fuer_belegformular(self, buero, kunde):
        antwort = buero.get(
            reverse('admin:autocomplete'),
            {'app_label': 'faktura', 'model_name': 'rechnung',
             'field_name': 'kunde', 'term': 'Muster'},
        )

        assert antwort.status_code == 200
        assert antwort.json()['results']


@pytest.mark.django_db
class TestDokumentImAdmin:
    """Die beiden eigenen URLs unterhalb der Belegarten."""

    def test_pdf_ansicht_liefert_ein_pdf(self, buero, mit_pdf, rechnungsentwurf):
        beleg = services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)

        antwort = buero.get(
            reverse('admin:faktura_rechnung_pdf', args=[beleg.pk])
        )

        assert antwort.status_code == 200
        assert antwort['Content-Type'] == 'application/pdf'
        inhalt = b''.join(antwort.streaming_content)
        assert inhalt.startswith(b'%PDF')
        # Ausgeliefert wird die gespeicherte Datei.
        from faktura import pdf as pdf_modul
        assert pdf_modul.pruefsumme(inhalt) == beleg.pdf_sha256

    def test_entwurf_wird_als_vorschau_gerendert(
        self, buero, mit_pdf, rechnungsentwurf
    ):
        antwort = buero.get(
            reverse('admin:faktura_rechnung_pdf', args=[rechnungsentwurf.pk])
        )

        assert antwort.status_code == 200
        assert antwort.content.startswith(b'%PDF')
        rechnungsentwurf.refresh_from_db()
        # Eine Vorschau speichert nichts.
        assert not rechnungsentwurf.pdf
        # Kein Browser-Cache, weil die URL des Entwurfs bei jeder Änderung
        # gleich bleibt. admin_view() setzt never_cache; der Test sichert
        # das ab, falls die View nicht mehr über admin_view() läuft.
        assert 'no-store' in antwort['Cache-Control']

    def test_html_vorschau_zeigt_dieselbe_vorlage(self, buero, rechnungsentwurf):
        antwort = buero.get(
            reverse('admin:faktura_rechnung_vorschau', args=[rechnungsentwurf.pk])
        )

        inhalt = antwort.content.decode()
        assert antwort.status_code == 200
        assert 'Beratung' in inhalt
        assert 'beleg.css' in inhalt

    def test_liste_verweist_auf_das_dokument(self, buero, rechnungsentwurf):
        antwort = buero.get(reverse('admin:faktura_rechnung_changelist'))

        assert f'/{rechnungsentwurf.pk}/pdf/' in antwort.content.decode()
