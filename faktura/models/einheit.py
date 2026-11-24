"""Mengeneinheiten nach UN/ECE Recommendation 20 und 21.

Positionen (Katalog, Beleg, Fremdleistung) speichern den UN/ECE-Code als
Text, etwa ``'HUR'``, wie den Steuersatz (``steuersatz.py``). Der Code ist
fest und geht unverändert in die E-Rechnung (BT-130). Die Tabelle liefert
dazu den Anzeigetext für Maske und PDF, die Erfassungsart und ob die Einheit
in der Auswahl steht.

Die Tabelle enthält alle Codes der KoSIT-Codelisten zu XRechnung
(``faktura/daten/einheiten_unece.json``), damit jeder Code einer
eingehenden E-Rechnung bekannt ist. Zur Auswahl steht nur, was der Betrieb
einschaltet.

Gefüllt wird nach jedem ``migrate`` über ``post_migrate``
(``grundausstattung_anlegen``), wie beim Steuersatz. Fehlende Codes werden
ergänzt, vorhandene Einträge nicht verändert.
"""

import json
import threading
from functools import cache
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import models


class Leistungsart(models.TextChoices):
    """Erfassungsart einer Einheit; bestimmt die Erfassungsmaske: zwei
    Uhrzeiten, eine Zahl oder Menge 1 mit möglichen Uhrzeiten."""

    ZEIT = 'zeit', 'Zeit (von/bis)'
    MENGE = 'menge', 'Menge'
    PAUSCHALE = 'pauschale', 'Pauschale'


#: Code einer Zeile ohne Einheit in der E-Rechnung (Zuschlag); BT-130 ist
#: Pflicht.
OHNE_EINHEIT = 'C62'

STUECK = 'C62'
STUNDE = 'HUR'
PAUSCHAL = 'LS'

#: Vorgabe an neuen Katalog- und Belegpositionen.
VORGABE = STUECK

DATEI = Path(__file__).resolve().parent.parent / 'daten' / 'einheiten_unece.json'

#: Code: (Anzeigetext, Erfassungsart). Bei einer neuen Installation zur
#: Auswahl eingeschaltet; alle übrigen Codes sind ausgeschaltet und haben
#: die Erfassungsart Menge.
GRUNDAUSSTATTUNG = {
    'C62': ('Stk', Leistungsart.MENGE),
    'HUR': ('Std', Leistungsart.ZEIT),
    'DAY': ('Tag', Leistungsart.MENGE),
    'LS': ('psch', Leistungsart.PAUSCHALE),
    'MTR': ('m', Leistungsart.MENGE),
    'MTK': ('m²', Leistungsart.MENGE),
    'MTQ': ('m³', Leistungsart.MENGE),
    'KGM': ('kg', Leistungsart.MENGE),
    'TNE': ('t', Leistungsart.MENGE),
    'LTR': ('l', Leistungsart.MENGE),
    'KMT': ('km', Leistungsart.MENGE),
    'SET': ('Satz', Leistungsart.MENGE),
}

#: Anzeigetext weiterer Codes aus ``SCHREIBWEISEN``, die beim ersten Füllen
#: nur dann zur Auswahl stehen, wenn Positionen sie tragen.
ANZEIGE = {'MIN': 'Min', 'WEE': 'Wo', 'MON': 'Monat', 'PR': 'Paar', 'CMT': 'cm'}

#: Übliche Schreibweisen zum Code, für Importe und Demodaten, deren Einheit
#: als Text vorliegt. Schlüssel normalisiert (``_normalisiert``). Die
#: Migration ``0066_einheit`` hat eine eigene Kopie.
SCHREIBWEISEN = {
    'stk': 'C62', 'stck': 'C62', 'st': 'C62', 'stück': 'C62',
    'stueck': 'C62', 'stuck': 'C62',
    'std': 'HUR', 'h': 'HUR', 'stunde': 'HUR', 'stunden': 'HUR',
    'tag': 'DAY', 'tage': 'DAY', 'd': 'DAY',
    'psch': 'LS', 'pausch': 'LS', 'pauschal': 'LS', 'pauschale': 'LS',
    'pschl': 'LS', 'pa': 'LS',
    'm': 'MTR', 'lfm': 'MTR', 'lfdm': 'MTR', 'meter': 'MTR',
    'm2': 'MTK', 'qm': 'MTK',
    'm3': 'MTQ', 'cbm': 'MTQ',
    'kg': 'KGM', 't': 'TNE', 'to': 'TNE',
    'l': 'LTR', 'ltr': 'LTR', 'liter': 'LTR',
    'km': 'KMT',
    'satz': 'SET',
    'cm': 'CMT',
    'min': 'MIN', 'wo': 'WEE', 'woche': 'WEE', 'wochen': 'WEE', 'monat': 'MON',
    'monate': 'MON', 'paar': 'PR',
}


class Einheit(models.Model):
    code = models.CharField(
        'Code', max_length=3, primary_key=True,
        help_text='UN/ECE Recommendation 20 oder 21. Steht in der '
                  'E-Rechnung und ist nicht änderbar.',
    )
    bezeichnung = models.CharField(
        'Bezeichnung (UN/ECE)', max_length=100,
        help_text='Englische Bezeichnung aus der Codeliste.',
    )
    anzeige = models.CharField(
        'Anzeige', max_length=20, blank=True, default='',
        help_text='So steht die Einheit in Maske und PDF, etwa „Std“ oder '
                  '„h“. Pflicht für Einheiten in der Auswahl.',
    )
    erfassungsart = models.CharField(
        'Erfassungsart', max_length=10, choices=Leistungsart,
        default=Leistungsart.MENGE,
        help_text='Zeit: Erfassung mit Von und Bis. Menge: mit einer Zahl. '
                  'Pauschale: Menge 1, Von und Bis möglich. Nicht änderbar, '
                  'solange Positionen die Einheit verwenden.',
    )
    zur_auswahl = models.BooleanField(
        'Zur Auswahl', default=False,
        help_text='Steht in der Auswahl an Katalog-, Beleg- und '
                  'Fremdleistungspositionen. Abgewählt behalten bestehende '
                  'Positionen die Einheit.',
    )

    class Meta:
        verbose_name = 'Einheit'
        verbose_name_plural = 'Einheiten'
        ordering = ['-zur_auswahl', 'anzeige', 'code']

    def __str__(self) -> str:
        return self.anzeige or self.code

    def in_verwendung(self) -> bool:
        """Ob eine Katalog-, Beleg- oder Fremdleistungsposition den Code
        trägt. Dann ist die Erfassungsart fest, weil sie bestimmt, ob
        vorhandene Erfassungszeilen als Zeit oder als Menge gelten."""
        from django.apps import apps
        modelle = [apps.get_model('faktura', 'Katalogposition'),
                   apps.get_model('faktura', 'Belegposition')]
        if apps.is_installed('erfassung'):
            modelle.append(apps.get_model('erfassung', 'Fremdleistung'))
        return any(m.objects.filter(einheit=self.code).exists()
                   for m in modelle)

    def clean(self):
        fehler = {}
        alt = (Einheit.objects.filter(pk=self.pk)
               .values('erfassungsart').first() if self.pk else None)
        if (alt and alt['erfassungsart'] != self.erfassungsart
                and self.in_verwendung()):
            fehler['erfassungsart'] = (
                'Positionen verwenden diese Einheit; die Erfassungsart ist '
                'deshalb fest.')
        if self.erfassungsart == Leistungsart.ZEIT and self.code != STUNDE:
            # Die Übernahme in die Rechnung rechnet die Dauer in Stunden um.
            fehler['erfassungsart'] = 'Zeit gibt es nur bei der Einheit Stunde.'
        if self.zur_auswahl and not self.anzeige.strip():
            fehler['anzeige'] = 'Einheiten in der Auswahl brauchen eine Anzeige.'
        if fehler:
            raise ValidationError(fehler)


@cache
def codeliste() -> tuple[tuple[str, str], ...]:
    """(Code, Bezeichnung) aller Codes der mitgelieferten Codeliste."""
    with DATEI.open(encoding='utf-8') as datei:
        return tuple((code, name) for code, name in json.load(datei)['codes'])


@cache
def codes() -> frozenset[str]:
    """Alle Codes der mitgelieferten Codeliste, ohne Datenbank."""
    return frozenset(code for code, _ in codeliste())


_zwischenspeicher = threading.local()


def _abweichende() -> dict[str, tuple[str, str]]:
    """Code: (Anzeige, Erfassungsart) der Einheiten mit Anzeigetext oder
    einer anderen Erfassungsart als Menge, eine Abfrage je Request.

    Thread-lokal und geleert bei jedem ``request_started`` und jedem
    Speichern einer Einheit (``FakturaConfig.ready``), damit Listen nicht
    je Zeile die Tabelle lesen und eine Änderung mit dem nächsten Request
    gilt."""
    tabelle = getattr(_zwischenspeicher, 'tabelle', None)
    if tabelle is None:
        tabelle = {
            code: (text, art) for code, text, art in
            Einheit.objects.filter(
                ~models.Q(anzeige='') | ~models.Q(erfassungsart=Leistungsart.MENGE))
            .values_list('code', 'anzeige', 'erfassungsart')}
        _zwischenspeicher.tabelle = tabelle
    return tabelle


def zwischenspeicher_leeren(**kwargs) -> None:
    """Empfänger für ``request_started`` und ``post_save``."""
    _zwischenspeicher.tabelle = None


def anzeige(code: str) -> str:
    """Anzeigetext zum Code, ``''`` ohne Code, der Code selbst ohne Eintrag
    oder ohne Anzeige."""
    if not code:
        return ''
    text, _ = _abweichende().get(code, ('', ''))
    return text or code


def erfassungsart(code: str) -> str:
    """Erfassungsart zum Code; Menge ohne Code oder ohne Eintrag."""
    if not code:
        return Leistungsart.MENGE
    return _abweichende().get(code, ('', Leistungsart.MENGE))[1]


def codes_der_art(art: str):
    """Subquery der Codes einer Erfassungsart, für ``einheit__in``."""
    return Einheit.objects.filter(erfassungsart=art).values('code')


def angeboten(aktuell: str | None = None) -> list[tuple[str, str]]:
    """Choices für ein Formular: die Einheiten zur Auswahl, dazu
    ``aktuell``, wenn die Position eine nicht mehr ausgewählte trägt."""
    einheiten = Einheit.objects.filter(
        models.Q(zur_auswahl=True) | models.Q(pk=aktuell or None))
    return [('', '---------')] + [(e.code, str(e)) for e in einheiten]


def _normalisiert(text: str) -> str:
    return (text.strip().rstrip('.').strip().lower()
            .replace('²', '2').replace('³', '3'))


def code_zum_text(text: str) -> str:
    """UN/ECE-Code zu einer Einheit als Text, ``''`` ohne Treffer.

    Für Importe und Demodaten. In dieser Reihenfolge: Anzeigetexte der
    Tabelle, ``SCHREIBWEISEN``, der Code selbst. Der Code zuletzt, weil
    „Stk“ sonst ``STK`` (stick) ergäbe."""
    if not (text or '').strip():
        return ''
    roh = text.strip()
    normal = _normalisiert(roh)
    for code, angezeigt in Einheit.objects.exclude(anzeige='').values_list(
            'code', 'anzeige'):
        if _normalisiert(angezeigt) == normal:
            return code
    if normal in SCHREIBWEISEN:
        return SCHREIBWEISEN[normal]
    return roh.upper() if Einheit.objects.filter(pk=roh.upper()).exists() else ''


def pruefen(code: str) -> None:
    """``ValidationError``, wenn der Code nicht in der Tabelle steht."""
    if code and not Einheit.objects.filter(pk=code).exists():
        raise ValidationError(f'Unbekannte Einheit „{code}“.')


def grundausstattung_anlegen(sender, apps=None, using='default', **kwargs):
    """``post_migrate``: ergänzt fehlende Codes der Codeliste.

    Beim ersten Füllen stehen ``GRUNDAUSSTATTUNG`` und alle Codes, die
    Positionen schon tragen, zur Auswahl. Vorhandene Einträge bleiben
    unverändert. ``migrate`` übergibt den Migrationsstand als ``apps``,
    ``flush`` nicht; dann gilt die globale Registry."""
    if apps is None:
        from django.apps import apps
    try:
        modell = apps.get_model('faktura', 'Einheit')
    except LookupError:
        # Migrationsstand vor dieser Tabelle.
        return
    tabelle = modell.objects.using(using)
    erstes_fuellen = not tabelle.exists()
    vorhanden = set(tabelle.values_list('code', flat=True))
    verwendet = set()
    if erstes_fuellen:
        quellen = [('faktura', 'Katalogposition'), ('faktura', 'Belegposition'),
                   ('erfassung', 'Fremdleistung')]
        for app, name in quellen:
            try:
                quelle = apps.get_model(app, name)
            except LookupError:
                continue
            verwendet |= set(quelle.objects.using(using)
                             .exclude(einheit='').values_list('einheit', flat=True)
                             .distinct())
    neu = []
    for code, name in codeliste():
        if code in vorhanden:
            continue
        text, art = GRUNDAUSSTATTUNG.get(
            code, (ANZEIGE.get(code, ''), Leistungsart.MENGE))
        auswahl = erstes_fuellen and (code in GRUNDAUSSTATTUNG or code in verwendet)
        neu.append(modell(code=code, bezeichnung=name[:100],
                          anzeige=text or (code if auswahl else ''),
                          erfassungsart=art, zur_auswahl=auswahl))
    tabelle.bulk_create(neu)
    zwischenspeicher_leeren()
