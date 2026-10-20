"""Spalten der Belegliste: Dokument, Archivverweis, Sortierung."""

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from faktura import services
from faktura.admin import KontaktAdmin, ProjektAdmin
from faktura.models import (
    Beleg,
    Projekt,
)


class TestDokumentspalte:
    """Inhalt der Dokumentspalte in der Liste.

    Prüfsumme und Template-Version stehen nur am einzelnen Beleg.
    Verworfen: "PDF · SHA-256 29edcdc4 · Vorlage v6" in jeder Zeile der
    Liste.
    """

    def _spalte(self, beleg):
        """Rendert die Spalte wie die Changelist.

        Über ``proxy_fuer``, weil ``beleg_festschreiben`` ein ``Beleg``
        zurückgibt und im Admin nur die Proxys je Belegart registriert
        sind.
        """
        from django.contrib.admin.sites import site

        from faktura.models import proxy_fuer
        modell = proxy_fuer(beleg.typ)
        # Proxy-Objekt übergeben, weil der Link aus dessen model_name
        # gebildet wird (admin:faktura_rechnung_pdf); für das Basismodell
        # gibt es die URL nicht.
        return site.get_model_admin(modell).dokument(modell.objects.get(pk=beleg.pk))

    def test_jede_belegart_hat_die_spalte(self, rf, admin_user):
        """Jede registrierte Belegart hat die Dokumentspalte.

        Geprüft über alle registrierten Belegarten, damit neue erfasst
        werden. Regression: Bei der Mahnung fehlte die Spalte, weil ihr
        eigenes ``list_display`` die gemeinsamen Spalten kopierte und eine
        ausließ.
        """
        from django.contrib.admin.sites import site

        from faktura.models import BelegTyp, proxy_fuer

        anfrage = rf.get('/')
        anfrage.user = admin_user

        for typ in BelegTyp.values:
            modell = proxy_fuer(typ)
            spalten = site.get_model_admin(modell).get_list_display(anfrage)
            assert 'dokument' in spalten, (
                f'{modell.__name__} zeigt die Dokumentspalte nicht: {spalten}')

    def test_liste_zeigt_pdf_und_archiv(
        self, buero, rechnungsentwurf, settings, tmp_path
    ):
        settings.MEDIA_ROOT = tmp_path
        settings.PAPERLESS_ANSICHT_URL = 'http://archiv.example'
        beleg = services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)
        services.archivierung_vermerken(beleg_id=beleg.pk, paperless_id=10)
        beleg.refresh_from_db()

        spalte = self._spalte(beleg)

        assert 'http://archiv.example/documents/10/details' in spalte
        assert '>Archiv</a>' in spalte
        # Prüfsumme nur im Formular, nicht in der Liste.
        assert 'SHA-256' not in spalte
        assert 'Vorlage' not in spalte

    def test_ohne_archiv_nur_das_pdf(
        self, buero, rechnungsentwurf, settings, tmp_path
    ):
        settings.MEDIA_ROOT = tmp_path
        beleg = services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)

        spalte = self._spalte(beleg)

        assert '>PDF</a>' in spalte
        assert 'Archiv' not in spalte

    def test_entwurf_ohne_den_zusatz_vorschau(self, buero, rechnungsentwurf):
        """Am Entwurf ohne Zusatz "Vorschau", weil der Status daneben steht."""
        spalte = self._spalte(rechnungsentwurf)

        assert '>PDF</a>' in spalte
        assert 'Vorschau' not in spalte

    def test_nachweis_bleibt_am_einzelnen_beleg(
        self, buero, rechnungsentwurf, settings, tmp_path
    ):
        settings.MEDIA_ROOT = tmp_path
        beleg = services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)
        beleg.pdf.save('probe.pdf', ContentFile(b'%PDF-1.4'), save=False)
        Beleg.objects.filter(pk=beleg.pk).update(pdf=beleg.pdf.name)
        beleg.refresh_from_db()

        antwort = buero.get(
            reverse('admin:faktura_rechnung_change', args=[beleg.pk]))

        inhalt = antwort.content.decode()
        assert 'SHA-256' in inhalt
        assert 'Vorlage' in inhalt


class TestArchivverweisImAdmin:
    """Link von der Rechnung auf das Archivdokument."""

    def test_verweis_steht_auf_der_belegseite(
        self, buero, rechnungsentwurf, settings, tmp_path
    ):
        settings.MEDIA_ROOT = tmp_path
        settings.PAPERLESS_ANSICHT_URL = 'http://archiv.example'
        beleg = services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)
        services.archivierung_vermerken(beleg_id=beleg.pk, paperless_id=4711)

        antwort = buero.get(
            reverse('admin:faktura_rechnung_change', args=[beleg.pk]))

        inhalt = antwort.content.decode()
        assert 'http://archiv.example/documents/4711/details' in inhalt
        assert 'Dokument 4711' in inhalt

    def test_ohne_vermerk_steht_da_dass_nichts_da_ist(
        self, buero, rechnungsentwurf, settings, tmp_path
    ):
        """Ohne Archivierung erscheint ein Hinweis in der Zelle."""
        settings.MEDIA_ROOT = tmp_path
        beleg = services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)

        antwort = buero.get(
            reverse('admin:faktura_rechnung_change', args=[beleg.pk]))

        assert 'nicht archiviert' in antwort.content.decode()


class TestFehlendeBelegdatei:
    """Dokument eingetragen, Datei fehlt.

    Der Fall, den ``pruefe_belegarchiv`` erkennt; er entsteht nach einem
    unvollständigen Restore oder Löschen im Speicherverzeichnis.
    Regression: unbehandelter ``FileNotFoundError`` mit Fehlerseite.
    """

    def test_der_admin_meldet_statt_abzustuerzen(
        self, buero, rechnungsentwurf, settings, tmp_path
    ):
        settings.MEDIA_ROOT = tmp_path
        beleg = services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)
        beleg.pdf.save('probe.pdf', ContentFile(b'%PDF-1.4 Attrappe'), save=False)
        Beleg.objects.filter(pk=beleg.pk).update(pdf=beleg.pdf.name)
        beleg.refresh_from_db()
        beleg.pdf.storage.delete(beleg.pdf.name)

        antwort = buero.get(
            reverse('admin:faktura_rechnung_pdf', args=[beleg.pk]), follow=True
        )

        assert antwort.status_code == 200
        meldungen = [str(m) for m in antwort.context['messages']]
        assert any('fehlt' in m for m in meldungen), meldungen

    def test_mit_datei_kommt_das_dokument(
        self, buero, rechnungsentwurf, settings, tmp_path
    ):
        """Gegenprobe: Mit Datei wird das Dokument ausgeliefert."""
        settings.MEDIA_ROOT = tmp_path
        beleg = services.beleg_festschreiben(beleg_id=rechnungsentwurf.pk)
        beleg.pdf.save('probe.pdf', ContentFile(b'%PDF-1.4 Attrappe'), save=False)
        Beleg.objects.filter(pk=beleg.pk).update(pdf=beleg.pdf.name)
        beleg.refresh_from_db()

        antwort = buero.get(reverse('admin:faktura_rechnung_pdf', args=[beleg.pk]))

        assert antwort.status_code == 200
        assert antwort['Content-Type'] == 'application/pdf'


@pytest.mark.django_db
class TestSpaltensortierungBelegzahl:
    """Sortieren nach der Spalte "Belege" ergibt keine 500.

    ``@admin.display(ordering='belege__count')`` setzt eine Annotation im
    Queryset voraus. Regression: Ohne sie warf erst das Sortieren
    ``FieldError``.

    Die Spalte wird über ``list_display`` ermittelt, damit eine
    Umsortierung der Spalten den Test nicht auf eine andere lenkt.
    """

    @pytest.fixture
    def projekt_mit_beleg(self, kunde, rechnungsentwurf):
        projekt = Projekt.objects.create(
            nummer='2026-042', bezeichnung='Halle Nord', kunde=kunde
        )
        Beleg.objects.filter(pk=rechnungsentwurf.pk).update(
            kunde=None, projekt=projekt
        )
        return projekt

    def _spalte(self, modeladmin_klasse):
        return list(modeladmin_klasse.list_display).index('anzahl_belege') + 1

    def test_projektliste_laesst_sich_nach_belegzahl_sortieren(
        self, buero, projekt_mit_beleg
    ):
        spalte = self._spalte(ProjektAdmin)

        antwort = buero.get(
            reverse('admin:faktura_projekt_changelist') + f'?o={spalte}'
        )

        assert antwort.status_code == 200

    def test_kundenliste_ebenso(self, buero, kunde, rechnungsentwurf):
        """Dasselbe für die Kundenliste."""
        spalte = self._spalte(KontaktAdmin)

        antwort = buero.get(
            reverse('admin:faktura_kontakt_changelist') + f'?o={spalte}'
        )

        assert antwort.status_code == 200

    def test_die_zahl_stimmt(self, buero, projekt_mit_beleg):
        """Die Annotation liefert dieselbe Zahl wie ``.count()`` je Zeile."""
        antwort = buero.get(reverse('admin:faktura_projekt_changelist'))

        zeilen = antwort.context['cl'].result_list
        assert [p.belege__count for p in zeilen] == [1]
