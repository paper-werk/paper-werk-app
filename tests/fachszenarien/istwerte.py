"""Istwerte zu den Sollwertnamen der Fälle.

Jeder Name aus ``[schritt.soll]`` hat hier eine Funktion ``(lauf, beleg,
schritt)``, die den Wert aus den gespeicherten Belegen liest, mit den
Rechenfunktionen, aus denen auch Maske und PDF ihre Beträge haben. Ein Name
ohne Funktion wird als "nicht geprüft" gemeldet und nie stillschweigend
übergangen. Endet ein Name auf ``_hoechstens``, gilt die Funktion des
Namens davor, verglichen mit "kleiner oder gleich".

Begriffe:

* ``netto``, ``ust``, ``brutto``: Leistung des Belegs dieses Schritts, ohne
  abgesetzte Abschläge (``leistungssummen``).
* ``*_kumuliert``: Summe über alle festgeschriebenen, nicht stornierten
  Abschläge des Projekts bis einschließlich diesem.
* ``offen_gesamt``: Summe der offenen Beträge aller Rechnungen des
  Projekts (``offener_betrag``).
* ``offen``: dasselbe je Kunde, Schlüssel wie ``[[kunde]].kennung``.
* ``zahlbetrag``: an Abschlag und Schlussrechnung der Zahlbetrag des
  Belegs; an einer gewöhnlichen Rechnung der offene Betrag, weil der Fall
  dort angerechnete Zahlungen abzieht.
"""

from __future__ import annotations

from decimal import Decimal

from faktura import services
from faktura.models import Beleg, Rechnungsart, Zahlungszuordnung, Zeilenart

from .aktionen import STUNDE, Lauf, abschlaege_bis, rechnungen

NULL = Decimal('0.00')


def _summen(beleg):
    return services.leistungssummen(beleg)


def _netto(positionen) -> Decimal:
    return sum((services.positionssumme(menge=p.menge, einzelpreis=p.einzelpreis)
                for p in positionen), NULL)


def offen_gesamt(lauf: Lauf, beleg=None, schritt=None) -> Decimal:
    """Saldo wie im Katalog: offene Posten (R-147) plus Einbehaltenes
    (R-192), das bestehen bleibt, aber noch nicht fällig ist."""
    offen = sum((services.offener_betrag(b) for b in rechnungen(lauf)), NULL)
    return offen + services.einbehalten(
        Beleg.objects.filter(projekt=lauf.projekt)).gesamt


def offen_je_kunde(lauf: Lauf, beleg, schritt) -> dict[str, Decimal]:
    """Offene Beträge je Kunde; Kunde einer Projektrechnung ist der des
    Projekts."""
    ergebnis = dict.fromkeys(lauf.kunden, NULL)
    nach_pk = {kunde.pk: kennung for kennung, kunde in lauf.kunden.items()}
    for b in rechnungen(lauf):
        kunde = b.kunde_id or b.projekt.kunde_id
        ergebnis[nach_pk[kunde]] += services.offener_betrag(b)
    return ergebnis


def _kumuliert(lauf, beleg, feld):
    return sum((getattr(_summen(b), feld) for b in abschlaege_bis(lauf, beleg)), NULL)


def honorar_kumuliert(lauf, beleg, schritt):
    """Netto der Leistungszeilen ohne Zuschläge, kumuliert."""
    return sum((_netto(b.positionen.filter(zeilenart=Zeilenart.LEISTUNG, ist_abzug=False))
                for b in abschlaege_bis(lauf, beleg)), NULL)


def abgesetzt_brutto(lauf, beleg, schritt):
    """Abgesetzte Abschläge der Schlussrechnung, brutto, positiv: Leistung
    minus Beleg ohne Restzeilen nicht bezahlter Abschläge."""
    return _summen(beleg).brutto - services.umsatzsummen(beleg).brutto


def abgesetzt_netto(lauf, beleg, schritt):
    return _summen(beleg).netto - services.umsatzsummen(beleg).netto


def zahlbetrag(lauf, beleg, schritt):
    if beleg.rechnungsart in (Rechnungsart.ABSCHLAG, Rechnungsart.SCHLUSS,
                              Rechnungsart.TEILSCHLUSS):
        return services.zahlbetrag(beleg)
    return services.offener_betrag(beleg)


def _storno(lauf, schritt) -> Beleg:
    return Beleg.objects.get(pk=lauf.belege[f'Storno-{schritt["rechnung"]}'])


def angerechnet(lauf, beleg, schritt):
    return sum((z.betrag + z.skonto for z in Zahlungszuordnung.objects.filter(beleg=beleg)),
               NULL)


def auftrag_unberechnet_netto(lauf, beleg, schritt):
    """Auftragssumme netto minus Leistung der festgeschriebenen Rechnungen
    ohne Abschläge (die Schlussrechnung enthält sie)."""
    berechnet = sum((_summen(b).netto for b in rechnungen(lauf).exclude(
        rechnungsart=Rechnungsart.ABSCHLAG)), NULL)
    return services.auftragssumme(lauf.projekt, 'netto') - berechnet


def zeithonorar(lauf, beleg, schritt):
    return _netto(beleg.positionen.filter(einheit=STUNDE, ist_abzug=False))


def leistung_ohne_zuschlag(lauf, beleg, schritt):
    return _netto(beleg.positionen.filter(zeilenart=Zeilenart.LEISTUNG, ist_abzug=False))


def weiterberechnet(kennung):
    """Netto der Position einer Kennung samt Aufschlagszeile."""
    def ermitteln(lauf, beleg, schritt):
        name = lauf.katalog[kennung]['bezeichnung']
        return _netto(beleg.positionen.filter(
            bezeichnung__in=[name, f'Aufschlag {name}'], ist_abzug=False))
    return ermitteln


ISTWERTE = {
    'netto': lambda lauf, b, s: _summen(b).netto,
    'ust': lambda lauf, b, s: _summen(b).steuer,
    'brutto': lambda lauf, b, s: _summen(b).brutto,
    'netto_gesamt': lambda lauf, b, s: _summen(b).netto,
    'ust_gesamt': lambda lauf, b, s: _summen(b).steuer,
    'brutto_gesamt': lambda lauf, b, s: _summen(b).brutto,
    'zahlbetrag': zahlbetrag,
    'netto_kumuliert': lambda lauf, b, s: _kumuliert(lauf, b, 'netto'),
    'ust_kumuliert': lambda lauf, b, s: _kumuliert(lauf, b, 'steuer'),
    'brutto_kumuliert': lambda lauf, b, s: _kumuliert(lauf, b, 'brutto'),
    'honorar_kumuliert': honorar_kumuliert,
    'einbehalt_kumuliert': lambda lauf, b, s: sum(
        (a.einbehalt for a in abschlaege_bis(lauf, b)), NULL),
    'abgesetzt_brutto': abgesetzt_brutto,
    'abgesetzt_vereinnahmt': abgesetzt_brutto,
    'abgesetzt_netto': abgesetzt_netto,
    'maengeleinbehalt': lambda lauf, b, s: b.einbehalt,
    'zeithonorar': zeithonorar,
    'schaetzung_netto': leistung_ohne_zuschlag,
    'auftragssumme_netto': lambda lauf, b, s: services.auftragssumme(lauf.projekt, 'netto'),
    'auftrag_unberechnet_netto': auftrag_unberechnet_netto,
    'storno_netto': lambda lauf, b, s: services.belegsummen(_storno(lauf, s)).netto,
    'storno_brutto': lambda lauf, b, s: services.belegsummen(_storno(lauf, s)).brutto,
    'angerechnet': angerechnet,
    'offen_gesamt': offen_gesamt,
    'offen': offen_je_kunde,
    'bohrung_weiterberechnet': weiterberechnet('BOHR'),
    'labor_weiterberechnet': weiterberechnet('LABOR'),
    'feldarbeiten': weiterberechnet('FELD'),
}
