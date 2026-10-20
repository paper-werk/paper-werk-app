"""Belegarten, Proxy-Modelle und Belegarchiv."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from faktura import services
from faktura.models import (
    Beleg,
    BelegTyp,
    Projekt,
    Rechnungsart,
)


@pytest.mark.django_db
class TestLieferschein:
    def test_braucht_kein_leistungsdatum(self, kunde):
        """Die Mahnung braucht kein Leistungsdatum, weil § 14 UStG für sie
        nicht gilt."""
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.LIEFERSCHEIN)
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Kabeltrommel', menge=Decimal('3'),
            einzelpreis=Decimal('0.00'), steuersatz='0.00',
        )

        festgeschrieben = services.beleg_festschreiben(beleg_id=beleg.pk)

        assert festgeschrieben.nummer.startswith('LS-')

    def test_ist_kein_wertbeleg(self, kunde):
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.LIEFERSCHEIN)

        assert not beleg.ist_wertbeleg


@pytest.mark.django_db
class TestProxyModelle:
    """Die Proxy-Manager liefern nur Belege ihrer Art."""

    def test_jede_sicht_zeigt_nur_ihre_belegart(self, kunde):
        from faktura.models import Angebot, Rechnung

        services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)

        assert Angebot.objects.count() == 1
        assert Rechnung.objects.count() == 1
        # ``Beleg.objects`` liefert alle Belege.
        assert Beleg.objects.count() == 2


@pytest.mark.django_db
class TestDieRechnungsarten:
    """Abschlag und Schluss als Rechnungsart.

    Geprüft werden die Zählung je Projekt und die Absetzung in den Summen.
    Die Trennung der drei Listen prüfen ``proxy_fuer`` und
    ``test_projektakte``.
    """

    @pytest.fixture
    def projekt(self, kunde):
        return Projekt.objects.create(
            nummer='2026-042', bezeichnung='Halle Nord', kunde=kunde)

    def _abschlag(self, projekt, betrag='2850.00'):
        beleg = services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG,
            rechnungsart=Rechnungsart.ABSCHLAG, betreff='Abschlag')
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Planung', menge=Decimal('1'),
            einzelpreis=Decimal(betrag), steuersatz='19.00')
        return beleg

    def test_ohne_angabe_ist_eine_rechnung_gewoehnlich(self, kunde):
        """Ohne Angabe ist eine Rechnung gewöhnlich, damit sie in einer Liste
        erscheint."""
        beleg = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)

        assert beleg.rechnungsart == Rechnungsart.NORMAL

    def test_die_abschlaege_zaehlen_je_vorhaben(self, projekt):
        erster = self._abschlag(projekt)
        zweiter = self._abschlag(projekt)

        assert erster.rechnungsbezeichnung == '1. Abschlagsrechnung'
        assert zweiter.rechnungsbezeichnung == '2. Abschlagsrechnung'

    def test_ein_verworfener_abschlag_laesst_die_reihe_aufruecken(self, projekt):
        """Nach Löschen eines Abschlags rücken die folgenden auf.

        Die Nummer wird berechnet wie die Nachtragsnummer, damit keine
        Lücke in der Zählung entsteht.
        """
        erster = self._abschlag(projekt)
        zweiter = self._abschlag(projekt)
        erster.delete()

        assert zweiter.rechnungsbezeichnung == '1. Abschlagsrechnung'

    def test_die_absetzung_mindert_netto_und_steuer(self, projekt):
        """§ 14 Abs. 5 Satz 2 UStG: Abgesetzt werden Teilentgelte **und**
        Steuer.

        Als negative Position, weil ``belegsummen()`` sie ohne Sonderfall je
        Steuersatz verrechnet. Ohne Absetzung wäre die Steuer nach § 14c
        Abs. 1 doppelt geschuldet.
        """
        schluss = services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG,
            rechnungsart=Rechnungsart.SCHLUSS, betreff='Schlussrechnung')
        services.position_hinzufuegen(
            beleg=schluss, bezeichnung='Planung', menge=Decimal('100'),
            einheit='Std', einzelpreis=Decimal('95.00'),
            steuersatz='19.00')
        services.position_hinzufuegen(
            beleg=schluss, bezeichnung='1. Abschlagsrechnung',
            menge=Decimal('1'), einzelpreis=Decimal('-2850.00'),
            steuersatz='19.00', ist_abzug=True)

        summen = services.belegsummen(schluss)

        assert summen.netto == Decimal('6650.00')
        assert summen.steuer == Decimal('1263.50')

    def test_das_pdf_haelt_die_absetzung_aus_der_positionstabelle(self, projekt):
        """Im PDF steht die Absetzung unter der Summe, nicht in der Tabelle der
        Positionen."""
        from faktura import pdf

        schluss = services.beleg_anlegen(
            projekt=projekt, typ=BelegTyp.RECHNUNG,
            rechnungsart=Rechnungsart.SCHLUSS, betreff='Schlussrechnung')
        services.position_hinzufuegen(
            beleg=schluss, bezeichnung='Planung', menge=Decimal('100'),
            einheit='Std', einzelpreis=Decimal('95.00'),
            steuersatz='19.00')
        services.position_hinzufuegen(
            beleg=schluss, bezeichnung='Geleisteter Abschlag',
            menge=Decimal('1'), einzelpreis=Decimal('-2850.00'),
            steuersatz='19.00', ist_abzug=True)

        html = pdf.beleg_als_html(schluss)

        assert 'Schlussrechnung' in html
        assert 'Bereits berechnete Abschl' in html
        # Einmal im Abzugsblock, nicht in der Tabelle der Positionen.
        assert html.count('Geleisteter Abschlag') == 1

    def test_ein_angebot_kennt_keine_rechnungsart(self, kunde):
        """Ein Angebot hat keine Rechnungsart, auch wenn sie beim Umwandeln
        mitkopiert würde."""
        angebot = services.beleg_anlegen(kunde=kunde, typ=BelegTyp.ANGEBOT)
        angebot.rechnungsart = Rechnungsart.ABSCHLAG

        with pytest.raises(ValidationError) as fehler:
            angebot.full_clean()

        assert 'rechnungsart' in fehler.value.error_dict


@pytest.mark.django_db
class TestDerAuftragBekommtKeinDokument:
    """Der Auftrag erhält beim Festschreiben kein Dokument.

    Der Auftrag ist die Grundlage im Projekt, nicht das Schreiben an den
    Kunden, und kein Vertrag, weil dieser durch die Beauftragung entsteht.
    Festgeschrieben wird er dennoch.

    Die Belegarten stehen in ``BelegTyp.mit_dokument()``; geprüft werden
    die Folgen.
    """

    @pytest.fixture(autouse=True)
    def eigenes_medienverzeichnis(self, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path

    @pytest.fixture
    def auftrag(self, kunde):
        beleg = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.AUFTRAG, betreff='Halle Nord')
        services.position_hinzufuegen(
            beleg=beleg, bezeichnung='Montage', menge=Decimal('1'),
            einzelpreis=Decimal('500.00'), steuersatz='19.00')
        return beleg

    def test_beim_festschreiben_entsteht_keine_datei(self, mit_pdf, auftrag):
        """Keine Datei beim Festschreiben, geprüft mit eingeschaltetem
        Rendern."""
        festgeschrieben = services.beleg_festschreiben(beleg_id=auftrag.pk)

        assert festgeschrieben.nummer
        assert not festgeschrieben.pdf.name
        assert not festgeschrieben.pdf_sha256

    def test_das_angebot_bekommt_weiterhin_eines(self, mit_pdf, kunde):
        """Gegenprobe: Das Angebot erhält ein Dokument."""
        angebot = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.ANGEBOT, betreff='Halle Nord')
        services.position_hinzufuegen(
            beleg=angebot, bezeichnung='Montage', menge=Decimal('1'),
            einzelpreis=Decimal('500.00'), steuersatz='19.00')

        festgeschrieben = services.beleg_festschreiben(beleg_id=angebot.pk)

        assert festgeschrieben.pdf.name
        assert festgeschrieben.pdf_sha256

    def test_die_archivpruefung_beanstandet_ihn_nicht(self, auftrag):
        """Die Archivprüfung meldet den Auftrag nicht, damit der tägliche Lauf
        im ordnungsgemäßen Zustand mit Exit-Code 0 endet."""
        services.beleg_festschreiben(beleg_id=auftrag.pk)

        bericht = services.belegarchiv_pruefen()

        assert bericht.in_ordnung, [b.problem for b in bericht.befunde]
        assert bericht.geprueft == 0

    def test_das_archiv_nimmt_ihn_nicht_an(self, auftrag):
        """Auch bei manuellem Aufruf keine Archivierung, weil
        ``belege_archivieren`` alle Belege ohne Dokumentnummer erfasst."""
        festgeschrieben = services.beleg_festschreiben(beleg_id=auftrag.pk)

        zurueck = services.beleg_archivieren(beleg_id=festgeschrieben.pk)

        assert zurueck.paperless_id is None
        assert not zurueck.paperless_task_id


@pytest.mark.django_db
class TestBelegarchiv:
    """``belegarchiv_pruefen`` vergleicht die gespeicherten Prüfsummen.

    Ohne Abgleich fiele eine veränderte oder fehlende Datei erst bei einer
    Anforderung durch die Betriebsprüfung auf. Jeder Fehlerfall wird
    herbeigeführt.
    """

    @pytest.fixture(autouse=True)
    def eigenes_medienverzeichnis(self, settings, tmp_path):
        """Testdateien in einem temporären Verzeichnis, nicht in media/."""
        settings.MEDIA_ROOT = tmp_path

    def _dokument_anheften(self, beleg, daten=b'%PDF-Testdokument',
                           xml=b'<rsm:CrossIndustryInvoice/>'):
        """Simuliert ``_dokument_einfrieren``.

        Ohne WeasyPrint, weil die Archivprüfung nur Datei und Prüfsumme
        braucht; die Tests laufen so ohne GTK.

        Bei E-Rechnungen dazu das XML; ``xml=None`` lässt es weg, für den zu
        meldenden Fall.
        """
        import hashlib

        from django.core.files.base import ContentFile

        from faktura import facturx

        beleg.pdf.save('test.pdf', ContentFile(daten), save=False)
        felder = {
            'pdf': beleg.pdf.name,
            'pdf_sha256': hashlib.sha256(daten).hexdigest(),
        }
        if xml is not None and facturx.ist_erechnungsfaehig(beleg):
            beleg.xml.save('test.xml', ContentFile(xml), save=False)
            felder['xml'] = beleg.xml.name
            felder['xml_sha256'] = hashlib.sha256(xml).hexdigest()
        Beleg.objects.filter(pk=beleg.pk).update(**felder)
        beleg.refresh_from_db()
        return beleg

    def test_unversehrtes_archiv_ohne_beanstandung(self, rechnung):
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)
        self._dokument_anheften(beleg)

        bericht = services.belegarchiv_pruefen()

        assert bericht.geprueft == 1
        assert bericht.in_ordnung

    def test_veraenderte_datei_faellt_auf(self, rechnung):
        """Eine nach dem Festschreiben veränderte Datei wird gemeldet."""
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)
        self._dokument_anheften(beleg)

        with open(beleg.pdf.path, 'wb') as datei:
            datei.write(b'%PDF-nachtraeglich veraendert')

        bericht = services.belegarchiv_pruefen()

        assert not bericht.in_ordnung
        assert 'Prüfsumme weicht ab' in bericht.befunde[0].problem

    def test_fehlende_datei_faellt_auf(self, rechnung):
        """Eine fehlende Datei wird gemeldet, weil das Dateisystem nicht
        geschützt ist."""
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)
        self._dokument_anheften(beleg)

        beleg.pdf.storage.delete(beleg.pdf.name)

        bericht = services.belegarchiv_pruefen()

        assert not bericht.in_ordnung
        assert 'fehlt' in bericht.befunde[0].problem

    def test_festgeschriebener_beleg_ohne_pdf_faellt_auf(self, rechnung):
        """Ein festgeschriebener Beleg ohne PDF wird gemeldet."""
        services.beleg_festschreiben(beleg_id=rechnung.pk)

        bericht = services.belegarchiv_pruefen()

        assert not bericht.in_ordnung
        assert 'kein PDF' in bericht.befunde[0].problem

    def test_stornierte_belege_werden_mitgeprueft(self, rechnung):
        """Stornierte Belege werden geprüft, weil das Storno die
        Aufbewahrungspflicht nicht aufhebt."""
        original = services.beleg_festschreiben(beleg_id=rechnung.pk)
        self._dokument_anheften(original)
        storno, _ = services.rechnung_korrigieren(beleg_id=original.pk)
        self._dokument_anheften(storno)

        bericht = services.belegarchiv_pruefen()

        # Original (storniert) und Storno; der neue Entwurf zählt nicht.
        assert bericht.geprueft == 2
        assert bericht.in_ordnung

    def test_entwuerfe_bleiben_aussen_vor(self, rechnung):
        bericht = services.belegarchiv_pruefen()

        assert bericht.geprueft == 0
        assert bericht.in_ordnung

    # --- XML ---------------------------------------------------------------
    #
    # Bei Versand nur als XML an ein Rechnungsportal ist das XML das
    # Original und wird daher ebenfalls geprüft.

    def test_veraendertes_xml_faellt_auf(self, rechnung):
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)
        self._dokument_anheften(beleg)

        with open(beleg.xml.path, 'wb') as datei:
            datei.write(b'<rsm:CrossIndustryInvoice>anders</rsm:CrossIndustryInvoice>')

        bericht = services.belegarchiv_pruefen()

        assert [b.problem for b in bericht.befunde] == [
            'Prüfsumme des XML weicht ab; die E-Rechnung wurde nach der '
            'Festschreibung verändert'
        ]

    def test_fehlendes_xml_faellt_auf(self, rechnung):
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)
        self._dokument_anheften(beleg)

        beleg.xml.storage.delete(beleg.xml.name)

        bericht = services.belegarchiv_pruefen()

        assert len(bericht.befunde) == 1
        assert 'fehlt im Ablageverzeichnis' in bericht.befunde[0].problem
        assert bericht.befunde[0].problem.startswith(f'Datei {beleg.xml.name}')

    def test_rechnung_ganz_ohne_xml_faellt_auf(self, rechnung):
        beleg = services.beleg_festschreiben(beleg_id=rechnung.pk)
        self._dokument_anheften(beleg, xml=None)

        bericht = services.belegarchiv_pruefen()

        assert [b.problem for b in bericht.befunde] == ['kein XML hinterlegt']

    def test_ohne_pdf_nur_ein_befund(self, rechnung):
        """Ohne PDF nur ein Befund, weil dann auch kein XML entstand."""
        services.beleg_festschreiben(beleg_id=rechnung.pk)

        bericht = services.belegarchiv_pruefen()

        assert [b.problem for b in bericht.befunde] == ['kein PDF hinterlegt']
