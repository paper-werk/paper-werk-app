"""Standard-Textbausteine einer neuen Installation.

Grundausstattung jeder Installation, keine Demodaten; im Code, damit sie
ein Neuaufsetzen der Datenbank überstehen. Angelegt durch
``faktura_textbausteine``.

Enthalten sind die Texte für den Beleg (``BAUSTEINE``, dazu die
Grußformel mit dem Firmennamen) und die Anschreiben für den Mailversand
(``ANSCHREIBEN``), zusammen zwanzig.

Die Einleitungen beginnen klein, weil sie nach der Anrede stehen ("Sehr
geehrte Damen und Herren," und darunter "wir berechnen Ihnen ...").

Bausteine für Abschlag und Schlussrechnung stehen unter ``rechnung``, weil
diese keinen eigenen Belegtyp haben (``Rechnungsart`` am Beleg); sie
erscheinen in derselben Liste wie die Rechnungseinleitung und
unterscheiden sich im Namen.
"""

from .models import BelegTyp, Textbaustein, TextbausteinVerwendung

#: Bausteine ohne Firmennamen: Name, Belegart, Text.
#
# Leere Belegart gilt für alle. Siehe ``Textbaustein.belegart``.
BAUSTEINE = [
    ('Anrede', '',
     'Sehr geehrte Damen und Herren,'),
    ('Dank für Zusammenarbeit', '',
     'Vielen Dank für die gute Zusammenarbeit.'),
    ('Rechnung Einleitung', BelegTyp.RECHNUNG,
     'wir berechnen Ihnen die nachstehend aufgeführten Leistungen.'),
    ('Abschlag Einleitung', BelegTyp.RECHNUNG,
     'für die bisher erbrachten Leistungen berechnen wir Ihnen den '
     'folgenden Abschlag.'),
    ('Schlussrechnung Einleitung', BelegTyp.RECHNUNG,
     'wir berechnen Ihnen abschließend die erbrachten Leistungen.'),
    ('Angebot Einleitung', BelegTyp.ANGEBOT,
     'vielen Dank für Ihre Anfrage. Gern bieten wir Ihnen an:'),
    ('Auftrag Einleitung', BelegTyp.AUFTRAG,
     'vielen Dank für Ihren Auftrag. Wir bestätigen Ihnen hiermit die '
     'folgende Bestellung:'),
    ('Lieferschein Einleitung', BelegTyp.LIEFERSCHEIN,
     'wir liefern Ihnen die nachstehend aufgeführten Positionen.'),
    # Einer je Mahnstufe, von ``mahnung_erstellen`` in den Kopftext gesetzt
    # (``MAHNEINLEITUNG``).
    ('Zahlungserinnerung Einleitung', BelegTyp.MAHNUNG,
     'zu der unten aufgeführten Rechnung konnten wir bisher keinen '
     'Zahlungseingang feststellen. Bitte überweisen Sie den offenen Betrag '
     'bis zum unten genannten Datum. Falls Sie inzwischen bezahlt haben, '
     'betrachten Sie dieses Schreiben bitte als gegenstandslos.'),
    ('Mahnung Einleitung', BelegTyp.MAHNUNG,
     'trotz unserer Zahlungserinnerung konnten wir bisher keinen '
     'Zahlungseingang feststellen. Bitte gleichen Sie den offenen Betrag '
     'bis zum unten genannten Datum aus.'),
    ('Letzte Mahnung Einleitung', BelegTyp.MAHNUNG,
     'trotz mehrfacher Aufforderung ist der unten aufgeführte Betrag '
     'weiterhin offen. Wir fordern Sie hiermit letztmalig auf, ihn bis zum '
     'unten genannten Datum zu begleichen. Nach fruchtlosem Fristablauf '
     'geben wir die Forderung ohne weitere Ankündigung an ein '
     'Inkassounternehmen ab.'),
]

#: Baustein für den Kopftext je Mahnstufe.
#
# Über den Namen, damit ein geänderter Wortlaut gilt. Nach Umbenennen oder
# Löschen des Bausteins bleibt der Kopftext leer.
MAHNEINLEITUNG = {
    1: 'Zahlungserinnerung Einleitung',
    2: 'Mahnung Einleitung',
    3: 'Letzte Mahnung Einleitung',
}

#: Name des Bausteins mit dem Firmennamen.
GRUSSFORMEL = 'Grußformel'

#: Anschreiben für den Mailversand, eines je Belegart.
#
# Grundausstattung, weil sie keinen Betrieb nennen und nur Platzhalter
# enthalten.
#
# ``{beleg}`` und nicht ``{nummer}``, weil der Text in der Versandmaske vor
# dem Festschreiben entsteht und ``{nummer}`` dort leer wäre ("unsere
# Rechnung über 595 EUR"). ``{beleg}`` ergibt "Rechnung" am Entwurf und
# "Rechnung RE-2026-0098" am festgeschriebenen Beleg.
#
# Nur Platzhalter, die zur Belegart passen: Der Lieferschein hat kein
# ``{betrag}``, weil er nur die Lieferung nachweist.
ANSCHREIBEN = [
    ('Angebot', BelegTyp.ANGEBOT,
     'Sehr geehrte Damen und Herren,\n\n'
     'vielen Dank für Ihre Anfrage. Gern unterbreiten wir Ihnen '
     'im Anhang unser {beleg}.\n\n'
     'Für Rückfragen stehen wir Ihnen gern zur Verfügung. Über '
     'Ihren Auftrag würden wir uns freuen.\n\n'
     'Mit freundlichen Grüßen\n{firma}'),
    ('Auftrag', BelegTyp.AUFTRAG,
     'Sehr geehrte Damen und Herren,\n\n'
     'vielen Dank für Ihren Auftrag. Im Anhang erhalten Sie '
     'unseren {beleg} mit allen vereinbarten Leistungen.\n\n'
     'Bitte prüfen Sie diese und melden Sie sich, falls etwas '
     'nicht Ihrer Vorstellung entspricht.\n\n'
     'Mit freundlichen Grüßen\n{firma}'),
    ('Lieferschein', BelegTyp.LIEFERSCHEIN,
     'Sehr geehrte Damen und Herren,\n\n'
     'im Anhang erhalten Sie den {beleg} zu den erbrachten '
     'Leistungen.\n\n'
     'Mit freundlichen Grüßen\n{firma}'),
    ('Rechnung', BelegTyp.RECHNUNG,
     'Sehr geehrte Damen und Herren,\n\n'
     'im Anhang erhalten Sie unsere {beleg} über {betrag}.\n\n'
     'Bitte überweisen Sie den Betrag unter Angabe der '
     'Rechnungsnummer innerhalb des vereinbarten '
     'Zahlungsziels.\n\n'
     'Vielen Dank für Ihren Auftrag.\n\n'
     'Mit freundlichen Grüßen\n{firma}'),
    ('Stornorechnung', BelegTyp.STORNO,
     'Sehr geehrte Damen und Herren,\n\n'
     'im Anhang erhalten Sie die {beleg}. Damit ist die ursprüngliche '
     'Rechnung aufgehoben; eine Zahlung darauf ist nicht mehr '
     'erforderlich.\n\n'
     'Bereits geleistete Zahlungen erstatten wir Ihnen '
     'selbstverständlich zurück.\n\n'
     'Mit freundlichen Grüßen\n{firma}'),
    ('Rechnungskorrektur', BelegTyp.GUTSCHRIFT,
     'Sehr geehrte Damen und Herren,\n\n'
     'im Anhang erhalten Sie die {beleg}. Der Betrag wird mit der '
     'ursprünglichen Rechnung verrechnet.\n\n'
     'Wir bitten, die Unannehmlichkeiten zu entschuldigen.\n\n'
     'Mit freundlichen Grüßen\n{firma}'),
    ('Mahnung', BelegTyp.MAHNUNG,
     'Sehr geehrte Damen und Herren,\n\n'
     'im Anhang erhalten Sie unsere {beleg} über {betrag} mit allen '
     'Angaben zur offenen Rechnung.\n\n'
     'Bitte überweisen Sie den Betrag bis zu dem darin genannten '
     'Datum. Falls Sie inzwischen bezahlt haben, betrachten Sie diese '
     'Nachricht bitte als gegenstandslos.\n\n'
     'Mit freundlichen Grüßen\n{firma}'),
    # Ohne Belegart: Fallback für alle oben nicht aufgeführten.
    ('Kurz und sachlich', '',
     'Sehr geehrte Damen und Herren,\n\n'
     'im Anhang: {beleg}.\n\n'
     'Mit freundlichen Grüßen\n{firma}'),
]


def grussformel(firmenname: str = '') -> str:
    """Grußformel mit dem Namen der eigenen Firma darunter.

    Bausteine für Belegtexte haben keine Platzhalter, weil sie beim Auswählen
    in den Beleg kopiert und dort bearbeitet werden
    (``TextbausteinVerwendung``). Der Name wird daher beim Anlegen
    eingesetzt.

    Ohne Firma entsteht die Formel ohne Namenszeile, damit kein Platzhalter
    im Brief steht.
    """
    if firmenname:
        return f'Mit freundlichen Grüßen\n{firmenname}'
    return 'Mit freundlichen Grüßen'


def anlegen(firma=None) -> int:
    """Legt die Standardbausteine an, die noch fehlen.

    Idempotent: Bausteine mit vorhandenem Namen bleiben unverändert, auch
    bei geändertem Wortlaut.

    ``firma`` nur für die Grußformel. Ohne Angabe wird die eigene Firma
    gesucht; fehlt sie, entsteht die Formel ohne Namenszeile.

    Gibt die Zahl der neu angelegten Bausteine zurück.
    """
    if firma is None:
        from .models import Firma
        firma = Firma.objects.first()

    alle = BAUSTEINE + [
        (GRUSSFORMEL, '', grussformel(firma.name if firma else '')),
    ]

    neu = 0
    for name, belegart, text in alle:
        _, angelegt = Textbaustein.objects.get_or_create(
            name=name,
            defaults={
                'verwendung': TextbausteinVerwendung.BELEGTEXT,
                'belegart': belegart,
                'text': text,
            },
        )
        neu += angelegt

    for name, belegart, text in ANSCHREIBEN:
        _, angelegt = Textbaustein.objects.get_or_create(
            name=name,
            defaults={
                'verwendung': TextbausteinVerwendung.MAIL,
                'belegart': belegart,
                'text': text,
            },
        )
        neu += angelegt
    return neu
