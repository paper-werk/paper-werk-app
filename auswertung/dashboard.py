"""Kennzahlen der Startseite.

Registriert in ``AuswertungConfig.ready()`` (auswertung/apps.py) über
``core.erweiterungen.startseite()``; Unfold ruft
``core.erweiterungen.startseite_ansicht`` auf, die hierher weiterreicht. Die
Funktion erhält Request und Kontext des Admin und gibt den erweiterten
Kontext zurück; gerendert wird templates/admin/index.html.

Das Modul rechnet nicht selbst. Die Beträge kommen aus den Services der
Apps, aus denselben Funktionen, die die Rechnung erzeugen; hier werden sie
ausgewählt, geordnet und beschriftet.
"""

from decimal import Decimal

from django.urls import reverse

from erfassung import services as erfassung_services
from faktura import formate
from faktura import services as faktura_services
from faktura.formate import euro

from . import aufgaben, controlling, darstellung, ergebnisse

#: Länge des Verlaufs in Monaten. Zwölf erlauben den Vergleich mit dem
#: Vorjahresmonat bei noch lesbarer Säulenbreite.
VERLAUFSMONATE = 12

#: Anzahl der Projekte in der Tabelle, sortiert nach offenem
#: Auftragsbestand. Die vollständige Liste steht unter "Projekte".
PROJEKTE_IN_DER_UEBERSICHT = 10


def _darf_zahlen_sehen(request) -> bool:
    """Ob der Benutzer die Kennzahlen sehen darf (``controlling_ansehen``).

    Wer nur Stunden erfasst, sieht keine Umsätze. Die Startseite bleibt für
    alle erreichbar, ohne das Recht fehlen nur die Auswertungen.
    """
    return request.user.has_perm('faktura.controlling_ansehen')


def startseite(request, context: dict) -> dict:
    """Ergänzt den Kontext der Admin-Startseite um die Auswertungen.

    Den Zertifikatshinweis setzt ``core.erweiterungen.startseite_ansicht``,
    damit er auch ohne diese App erscheint.
    """
    # Sprungziel für das „?“ in der Kopfleiste (hilfe/templatetags/hilfe.py).
    context['hilfe_anker'] = 'startseite'
    if not _darf_zahlen_sehen(request):
        context['zeige_auswertung'] = False
        return context

    uebersicht = ergebnisse.projektergebnisse()
    verlauf = faktura_services.fakturaverlauf(monate=VERLAUFSMONATE)
    posten = faktura_services.offene_posten()

    # Zwei Hinweise aus dem Controlling unter den Karten, die einen Betrag
    # einordnen, etwa den Bestand als Reichweite in Monaten.
    reichweite = controlling.reichweite(
        auftragsbestand=uebersicht.auftragsbestand, verlauf=verlauf)
    altersklassen = erfassung_services.offene_leistung_nach_alter()

    context.update({
        'zeige_auswertung': True,
        'kennzahlen': _kennzahlen(uebersicht, posten, reichweite,
                                  altersklassen),
        # "Zu erledigen" aus denselben Ergebnissen (auswertung/aufgaben.py).
        'aufgaben': aufgaben.aufgaben(
            request, uebersicht=uebersicht, posten=posten,
            alt_ueber_90=_alter_als_90_tage(altersklassen)),
        'controlling_url': reverse('controlling'),
        'verlauf_saeulen': darstellung.saeulen(
            verlauf, lambda m: m.netto, euro, darstellung.euro_glatt),
        'verlauf_spitze': darstellung.spitzenmonat(
            verlauf, lambda m: m.netto, euro),
        'projektzeilen': _projektzeilen(uebersicht),
        'weitere_projekte': max(
            0, len(uebersicht.zeilen) - PROJEKTE_IN_DER_UEBERSICHT),
        'projekte_url': reverse('admin:faktura_projekt_changelist'),
    })
    return context


def _kennzahlen(uebersicht, posten, reichweite, altersklassen) -> list[dict]:
    """Die fünf Karten über dem Diagramm.

        Fakturiert           Umsatz im laufenden Jahr
        Auftragsbestand      beauftragt, noch nicht berechnet
        Nicht abgerechnet    erbrachte Leistung ohne Rechnung
        Ergebnis             Leistungswert abzüglich Kosten
        Offene Forderungen   ausstehende Zahlungen, davon überfällig
    """
    alt = _alter_als_90_tage(altersklassen)
    return [
        {
            'titel': 'Fakturiert im laufenden Jahr',
            'wert': euro(faktura_services.fakturiert_im_jahr()),
            'hinweis': 'Netto, ohne Entwürfe. Stornos sind abgezogen.',
            'kurz': 'netto, ohne Entwürfe',
            'icon': 'trending_up',
        },
        {
            'titel': 'Offener Auftragsbestand',
            'wert': euro(uebersicht.auftragsbestand),
            'hinweis': _bestandshinweis(uebersicht, reichweite),
            'kurz': _bestand_kurz(uebersicht, reichweite),
            'icon': 'inventory',
        },
        {
            'titel': 'Nicht abgerechnete Leistung',
            'wert': euro(uebersicht.nicht_abgerechnet),
            'hinweis': _liegehinweis(altersklassen),
            'kurz': (f'{euro(alt)} älter als 90 Tage' if alt > 0
                     else 'auf keiner Rechnung'),
            'warnung': alt > 0,
            'icon': 'pending_actions',
        },
        {
            'titel': 'Ergebnis laufender Projekte',
            'wert': euro(uebersicht.ergebnis),
            # Der Vorbehalt steht in der Karte, weil die Zahl ohne
            # Kostensätze zu hoch ist.
            'hinweis': _ergebnishinweis(uebersicht),
            'kurz': _ergebnis_kurz(uebersicht),
            'warnung': not uebersicht.vollstaendig,
            'icon': 'savings',
        },
        {
            'titel': 'Offene Forderungen',
            'wert': euro(posten.offen),
            'hinweis': _forderungshinweis(posten),
            'kurz': (f'{euro(posten.offen_ueberfaellig)} über Frist'
                     if posten.ueberfaellig else
                     f'{posten.anzahl} Rechnung{"" if posten.anzahl == 1 else "en"}, '
                     'keine über Frist'),
            'warnung': bool(posten.ueberfaellig),
            'icon': 'request_quote',
        },
    ]


# Kurzhinweise unter dem Betrag, je eine Zeile; der vollständige Satz steht
# im Tooltip der Karte (``hinweis``). ``warnung`` färbt die Zeile rot.

def _alter_als_90_tage(altersklassen) -> Decimal:
    return sum((k.betrag for k in altersklassen if k.bis_tagen is None),
               Decimal('0.00'))


def _bestand_kurz(uebersicht, reichweite) -> str:
    projekte = len(uebersicht.zeilen)
    grundlage = ('1 laufendes Projekt' if projekte == 1
                 else f'{projekte} laufende Projekte')
    if reichweite.monate is None:
        return grundlage
    if reichweite.ist_knapp:
        return f'{grundlage} · reicht keinen Monat'
    return f'{grundlage} · reicht {formate.menge(reichweite.monate)} Monate'


def _ergebnis_kurz(uebersicht) -> str:
    if uebersicht.vollstaendig:
        return 'Leistungswert minus Kosten'
    zahl = len(uebersicht.ohne_kostensatz)
    return f'{zahl} Person{"" if zahl == 1 else "en"} ohne Kostensatz'


def _forderungshinweis(posten) -> str:
    """Überfälliger Anteil der Forderungen und ältester Verzug."""
    grundlage = (f'Brutto, aus {posten.anzahl} Rechnung'
                 f'{"" if posten.anzahl == 1 else "en"}.')
    if not posten.ueberfaellig:
        return f'{grundlage} Nichts über die Frist.'

    # Nur überfällige Posten; Posten in der Frist haben negative Tage.
    aeltester = max((p.tage_ueberfaellig or 0)
                    for p in posten.ueberfaellig)
    return (f'{grundlage} Davon {euro(posten.offen_ueberfaellig)} über die '
            f'Frist, älteste seit {aeltester} Tagen.')


def _bestandshinweis(uebersicht, reichweite) -> str:
    """Reichweite des Auftragsbestands in Monaten abgerechneter Leistung."""
    grundlage = (f'Beauftragt, noch nicht berechnet, über '
                 f'{len(uebersicht.zeilen)} laufende Projekte.')
    if reichweite.monate is None:
        return grundlage
    if reichweite.ist_knapp:
        return f'{grundlage} Reicht rechnerisch keinen Monat.'
    # menge() formatiert mit Dezimalkomma ("4,3").
    return f'{grundlage} Reicht rechnerisch {formate.menge(reichweite.monate)} Monate.'


def _liegehinweis(altersklassen) -> str:
    """Nicht abgerechnete Leistung mit ihrem Alter.

    Das Alter unterscheidet langsame Abrechnung von vergessener Leistung.
    """
    grundlage = ('Erfasste Stunden und zugekaufte Leistung, die noch auf '
                 'keiner Rechnung stehen.')
    alt = _alter_als_90_tage(altersklassen)
    if alt <= 0:
        return grundlage
    return f'{grundlage} Davon {euro(alt)} älter als 90 Tage.'


def _ergebnishinweis(uebersicht) -> str:
    """Hinweis unter dem Ergebnis.

    Stunden ohne Kostensatz sind unbewertet, das Ergebnis ist dann um deren
    Lohnkosten zu hoch.
    """
    if uebersicht.vollstaendig:
        return ('Leistungswert minus eigene Kosten und Fremdkosten, '
                'netto.')
    zahl = len(uebersicht.ohne_kostensatz)
    stunden = uebersicht.minuten_ohne_satz // 60
    return (f'Zu hoch: {zahl} Person{"" if zahl == 1 else "en"} ohne '
            f'Kostensatz, {stunden} Std unbewertet.')


def _projektzeilen(uebersicht) -> list[dict]:
    """Zeilen der Projekttabelle, nach offenem Auftragsbestand sortiert."""
    zeilen = []
    for stand in uebersicht.zeilen[:PROJEKTE_IN_DER_UEBERSICHT]:
        projekt = stand.projekt
        zeilen.append({
            'nummer': projekt.nummer,
            'bezeichnung': projekt.bezeichnung,
            'kunde': str(projekt.kunde),
            # Link auf die Akte, weil hier der Stand gefragt ist.
            'url': reverse('projektakte', args=[projekt.pk]),
            'beauftragt': euro(stand.beauftragt),
            'fakturiert': euro(stand.fakturiert),
            'offen': euro(stand.offen),
            'leistung': euro(stand.nicht_abgerechnet),
            # Als Satz formuliert.
            'ueberschreitung': (
                f'{euro(stand.ueberschreitung)} über Auftrag'
                if stand.ist_ueberzogen else ''),
            'ergebnis': euro(stand.ergebnis),
            # Für die Einfärbung von Verlustprojekten.
            'traegt': stand.traegt,
            # Ohne Leistungswert ist die Marge undefiniert und bleibt leer.
            'marge': '' if stand.marge is None else f'{stand.marge} %',
            'fortschritt': stand.fortschritt,
            # Ohne Auftrag fehlt der Nenner; kein Balken, weil null Prozent
            # "nichts berechnet" bedeuten würde.
            'zeige_fortschritt': stand.beauftragt > 0,
        })
    return zeilen
