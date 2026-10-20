"""Leistungsnachweis als Anlage der Rechnung.

Er enthält die Stunden und die weiterberechneten Fremdleistungen, die auf
dieser Rechnung abgerechnet sind, ohne Preise. Er ist kein Beleg: nicht
festgeschrieben, nicht gespeichert, jederzeit neu erzeugt, immer kompakt.
In der Versandmaske lässt er sich anhängen (Vorgabe: nicht angehakt), an
der Rechnung ansehen, auch nachträglich.
"""

from datetime import date, time
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from erfassung import nachweis, services
from erfassung.models import Eingangsrechnung, Fremdleistung
from faktura import services as faktura_services
from faktura.models import Firma, Katalogposition, Kontakt, Leistungsart


@pytest.fixture
def als_abrechner(client, kollege):
    kollege.user_permissions.add(*Permission.objects.filter(
        content_type__app_label__in=['erfassung', 'faktura']))
    client.force_login(kollege)
    return client


@pytest.fixture(autouse=True)
def firma(db):
    """Firma für das Rechnungs-PDF beim Festschreiben."""
    return Firma.objects.create(
        name='Werkstatt Amper GmbH', strasse='Musterweg 12', plz='80331',
        ort='München', email='post@example.de', steuernummer='143/815/47110',
        ust_id='DE123456789', iban='DE02120300000000202051',
        bic='BYLADEM1001')


@pytest.fixture
def labor(db):
    return Kontakt.objects.create(name='Bodenlabor Isartal GmbH', ist_kunde=False,
                                  ist_lieferant=True)


def _fremd(projekt, labor, tag, bezeichnung='Asbest, Probe BK 1'):
    rechnung, _ = Eingangsrechnung.objects.get_or_create(
        lieferant=labor, nummer='1299001',
        defaults={'datum': date(2026, 10, 14),
                  'betrag_netto': Decimal('80.00')})
    return Fremdleistung.objects.create(
        rechnung=rechnung, projekt=projekt, bezeichnung=bezeichnung,
        menge=Decimal('1'), einkaufspreis=Decimal('40.00'),
        leistungsdatum=tag)


@pytest.fixture
def rechnung(projekt, zeitleistung, kollege, labor):
    """Entwurf mit einer Stunde vom 6.10. und einer Analyse vom 2.10."""
    services.zeile_erfassen(
        projekt=projekt, leistung=zeitleistung, benutzer=kollege,
        beschreibung='Probenahme vor Ort', datum=date(2026, 10, 6),
        von=time(8, 0), bis=time(9, 0))
    _fremd(projekt, labor, date(2026, 10, 2))
    beleg, _ = services.in_rechnung_uebernehmen(
        zeilen=services.offene_leistungen(projekt)[0].zeilen,
        fremdleistungen=Fremdleistung.objects.all())
    beleg.leistungsdatum = timezone.localdate()
    beleg.save()
    return beleg


# ── Inhalt ───────────────────────────────────────────────────────────────


def test_nur_was_auf_dieser_rechnung_steht(rechnung, projekt, labor):
    _fremd(projekt, labor, date(2026, 10, 9), 'Noch offen')

    a = services.nachweis_zur_rechnung(rechnung)

    assert [z.beschreibung for z in a.zeilen] == ['Probenahme vor Ort']
    assert [f.bezeichnung for f in a.fremdleistungen] == [
        'Asbest, Probe BK 1']
    assert a.beleg == rechnung
    assert a.projekt == projekt
    # Der Zeitraum reicht über Stunden und Fremdleistungen.
    assert (a.von, a.bis) == (date(2026, 10, 2), date(2026, 10, 6))


def test_ohne_preise_ohne_lieferant(rechnung):
    html = nachweis.nachweis_als_html(services.nachweis_zur_rechnung(rechnung))

    assert 'Asbest, Probe BK 1' in html
    assert 'Bodenlabor Isartal GmbH' not in html
    assert '>Fremdleistungen<' not in html
    assert 'Unterschrift' not in html
    assert '40,00' not in html and '68,00' not in html


def test_datum_beider_tabellen_mit_jahr(rechnung):
    html = nachweis.nachweis_als_html(services.nachweis_zur_rechnung(rechnung))

    assert '>06.10.2026<' in html and '>02.10.2026<' in html


def test_stueckleistung_zeigt_den_umfang_nicht_die_stunden(projekt, kollege):
    """Zeit auf einer Stückleistung ist Aufwand: Die Rechnung berechnet
    1 Stk; der Nachweis zeigt keine Dauer dazu und zählt sie nicht in der
    Stundensumme."""
    probe = Katalogposition.objects.create(
        bezeichnung='Asbest Einzelprobe', einheit='Stk',
        einzelpreis=Decimal('45.00'), kontierbar=True, art=Leistungsart.MENGE)
    zeile = services.zeile_erfassen(
        projekt=projekt, leistung=probe, benutzer=kollege, menge=1,
        beschreibung='Probe vor Ort', datum=date(2026, 9, 23),
        von=time(7, 0), bis=time(16, 30))
    beleg, _ = services.in_rechnung_uebernehmen(zeilen=[zeile])

    a = services.nachweis_zur_rechnung(beleg)
    html = nachweis.nachweis_als_html(a)

    assert a.minuten == 0
    assert '1 Stk' in html
    assert '9:30' not in html
    assert 'Summe der Stunden' not in html


def test_rechnung_ohne_stunden_und_fremdleistungen_hat_keinen(db):
    from faktura.models import Beleg, BelegTyp
    assert not services.hat_nachweis(Beleg.objects.create(
        typ=BelegTyp.RECHNUNG))


# ── Fassung ──────────────────────────────────────────────────────────────


def test_immer_kompakt(rechnung):
    with patch.object(nachweis, 'nachweis_als_pdf') as pdf:
        nachweis.zur_rechnung_als_pdf(rechnung)
    assert pdf.call_args.kwargs == {'mit_uhrzeit': False}


# ── Versand ──────────────────────────────────────────────────────────────


def _versenden(beleg):
    return reverse('admin:faktura_rechnung_detail_versenden', args=[beleg.pk])


def _felder(**zusatz):
    return {'an': 'kunde@vogt.example', 'betreff': 'Rechnung',
            'nachricht': 'Anbei.', 'senden': '1', **zusatz}


def test_die_maske_bietet_ihn_an_nicht_angehakt(als_abrechner, rechnung):
    inhalt = als_abrechner.get(_versenden(rechnung)).content.decode()

    assert 'Leistungsnachweis anhängen' in inhalt
    assert 'name="anlage_leistungsnachweis"' in inhalt
    assert 'name="anlage_leistungsnachweis" checked' not in inhalt
    assert 'fassung_leistungsnachweis' not in inhalt
    assert f'href="{_ansehen(rechnung)}"' in inhalt


def test_angehakt_geht_er_mit(als_abrechner, rechnung, mit_pdf):
    with patch.object(nachweis, 'nachweis_als_pdf',
                      return_value=b'%PDF nachweis') as pdf:
        als_abrechner.post(_versenden(rechnung), _felder(
            anlage_leistungsnachweis='on'))

    rechnung.refresh_from_db()
    namen = [name for name, _, _ in mail.outbox[0].attachments]
    assert namen == [f'{rechnung.nummer}.pdf',
                     f'Leistungsnachweis_{rechnung.nummer}.pdf']
    assert mail.outbox[0].attachments[1][1] == b'%PDF nachweis'
    assert pdf.call_args.kwargs == {'mit_uhrzeit': False}


def test_ohne_haken_nur_die_rechnung(als_abrechner, rechnung, mit_pdf):
    als_abrechner.post(_versenden(rechnung), _felder())

    assert len(mail.outbox[0].attachments) == 1


def test_beim_erneuten_versand_nachholbar(als_abrechner, rechnung, mit_pdf):
    """Auch beim erneuten Versand einer Rechnung lässt sich der Nachweis
    anhängen."""
    als_abrechner.post(_versenden(rechnung), _felder())
    erneut = reverse('admin:faktura_rechnung_detail_erneut_versenden',
                     args=[rechnung.pk])

    als_abrechner.post(erneut, _felder(anlage_leistungsnachweis='on'))

    assert len(mail.outbox[1].attachments) == 2


# ── Ansehen ──────────────────────────────────────────────────────────────


def _ansehen(beleg):
    return reverse('admin:faktura_rechnung_detail_leistungsnachweis',
                   args=[beleg.pk])


def test_am_entwurf(als_abrechner, rechnung):
    antwort = als_abrechner.get(_ansehen(rechnung))

    assert antwort['Content-Type'] == 'application/pdf'
    assert antwort.content.startswith(b'%PDF')


def test_auch_nach_dem_festschreiben(als_abrechner, rechnung):
    faktura_services.beleg_festschreiben(beleg_id=rechnung.pk)
    rechnung.refresh_from_db()

    antwort = als_abrechner.get(_ansehen(rechnung))

    assert antwort.content.startswith(b'%PDF')
    assert f'Leistungsnachweis_{rechnung.nummer}.pdf' in antwort[
        'Content-Disposition']
