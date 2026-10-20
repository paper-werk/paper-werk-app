"""Nummernkreis bei gleichzeitigen Zugriffen.

Der Nummernkreis ist GoBD-relevant (``services.naechste_belegnummer``).
Race Conditions zeigen sich nur mit mehreren Threads; eine Lücke oder eine
doppelte Rechnungsnummer wäre ein Befund der Betriebsprüfung.

Alle Tests laufen mit ``transaction=True``, weil pytest-django sonst jeden
Test in eine Transaktion mit Rollback einschließt und ein zweiter Thread die
Daten des ersten nicht sähe.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal

import pytest
from django.db import connection, transaction

from faktura import services
from faktura.models import (
    Beleg,
    Belegposition,
    BelegStatus,
    BelegTyp,
    Firma,
    Kontakt,
)


@pytest.fixture
def firma(db):
    return Firma.objects.create(
        name='Elektro Hofmeister e.K.', strasse='Schirmbeckstraße 14',
        plz='84034', ort='Landshut', steuernummer='132/218/40391')


@pytest.fixture
def kunde(db):
    return Kontakt.anlegen(nummer='K-1001', name='Wohnbau Isartal eG',
                                strasse='Ludwigsplatz 9', plz='84034',
                                ort='Landshut')


def _entwurf(kunde, betrag='100.00'):
    """Rechnungsentwurf zum Festschreiben."""
    beleg = services.beleg_anlegen(
        kunde=kunde, typ=BelegTyp.RECHNUNG, betreff='Prüfung Nummernkreis',
        leistungsdatum=date(2026, 8, 1))
    services.position_hinzufuegen(
        beleg=beleg, bezeichnung='Gesellenstunde', menge=Decimal('1'),
        einheit='Std', einzelpreis=Decimal(betrag),
        steuersatz='19.00')
    return beleg


def _gleichzeitig(pks, tor):
    """Schreibt alle Belege gleichzeitig fest.

    ``tor`` ist eine ``threading.Barrier``, die alle Threads gemeinsam
    freigibt. Ohne sie wäre der erste Task eines ``ThreadPoolExecutor`` oft
    fertig, bevor der letzte startet, und der Test liefe sequenziell.

    Jeder Thread schließt seine Verbindung, weil Postgres die Test-Datenbank
    sonst nicht löscht und der Lauf mit einem Timeout endet.
    """
    def einer(pk):
        try:
            tor.wait(timeout=10)
            return services.beleg_festschreiben(beleg_id=pk)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=len(pks)) as pool:
        return list(pool.map(einer, pks))


@pytest.mark.django_db(transaction=True)
class TestZweiZugleich:
    """Zwei gleichzeitige Festschreibungen."""

    def test_zwei_gleichzeitige_festschreibungen_ergeben_zwei_nummern(
            self, firma, kunde):
        """Zwei gleichzeitige Festschreibungen ergeben zwei Nummern.

        django-sequences sperrt die Zählerzeile bis zum Ende der
        Transaktion; der zweite Thread wartet und erhält die nächste
        Nummer.
        """
        entwuerfe = [_entwurf(kunde).pk for _ in range(2)]

        belege = _gleichzeitig(entwuerfe, threading.Barrier(2))

        nummern = sorted(b.nummer for b in belege)
        assert len(set(nummern)) == 2, f'doppelte Nummer: {nummern}'
        assert nummern == ['RE-2026-0001', 'RE-2026-0002'], nummern

    def test_zehn_gleichzeitige_bleiben_lueckenlos(self, firma, kunde):
        """Zehn parallele Festschreibungen ergeben genau 1 bis 10, ohne Lücke
        und ohne Duplikat."""
        entwuerfe = [_entwurf(kunde).pk for _ in range(10)]

        belege = _gleichzeitig(entwuerfe, threading.Barrier(10))

        laufende = sorted(int(b.nummer.rsplit('-', 1)[1]) for b in belege)
        assert laufende == list(range(1, 11)), (
            f'nicht lückenlos: {laufende}')


@pytest.mark.django_db(transaction=True)
class TestDerAbbruch:
    """Nummer bei Rollback der Transaktion."""

    def test_ein_rollback_gibt_die_nummer_wieder_frei(self, firma, kunde):
        """Ein Rollback gibt die Nummer wieder frei.

        Prüft die Begründung in ``naechste_belegnummer`` für django-sequences:
        Eine Postgres-Sequence verbraucht Werte auch bei Rollback.
        """
        gescheitert = _entwurf(kunde).pk

        class Abbruch(Exception):
            pass

        with pytest.raises(Abbruch):
            with transaction.atomic():
                services.beleg_festschreiben(beleg_id=gescheitert)
                raise Abbruch

        # Der nächste Beleg erhält die 1, nicht die 2.
        danach = services.beleg_festschreiben(beleg_id=_entwurf(kunde).pk)

        assert danach.nummer == 'RE-2026-0001', (
            f'{danach.nummer}; der Abbruch hat eine Nummer verbraucht')

    def test_der_abgebrochene_beleg_bleibt_entwurf(self, firma, kunde):
        """Nach Rollback bleibt der Beleg Entwurf, damit kein festgeschriebener
        Beleg ohne Nummer entsteht."""
        pk = _entwurf(kunde).pk

        class Abbruch(Exception):
            pass

        with pytest.raises(Abbruch):
            with transaction.atomic():
                services.beleg_festschreiben(beleg_id=pk)
                raise Abbruch

        beleg = Beleg.objects.get(pk=pk)
        assert beleg.status == BelegStatus.ENTWURF
        assert not beleg.nummer


@pytest.mark.django_db(transaction=True)
class TestDieKreiseSindGetrennt:
    def test_angebot_und_rechnung_zaehlen_unabhaengig(self, firma, kunde):
        """Angebot und Rechnung haben getrennte Zähler, weil ein gemeinsamer
        Lücken in beiden Nummernkreisen erzeugte."""
        angebot = services.beleg_anlegen(
            kunde=kunde, typ=BelegTyp.ANGEBOT, betreff='Angebot',
            leistungsdatum=date(2026, 8, 1))
        Belegposition.objects.create(
            beleg=angebot, position=10, bezeichnung='Pauschal',
            menge=Decimal('1'), einheit='psch', einzelpreis=Decimal('500.00'))

        rechnung = services.beleg_festschreiben(beleg_id=_entwurf(kunde).pk)
        angebot = services.beleg_festschreiben(beleg_id=angebot.pk)

        assert rechnung.nummer.endswith('-0001')
        assert angebot.nummer.endswith('-0001')
        assert rechnung.nummer != angebot.nummer
