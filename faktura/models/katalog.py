"""Leistungskatalog und Textbausteine, aus denen Belege kopieren.
Spätere Änderungen wirken nicht auf bestehende Belege."""

from django.db import models

from . import steuersatz as steuersatz_tabelle
from .beleg import BelegTyp, Leistungsart


class TextbausteinVerwendung(models.TextChoices):
    #: Text auf dem Beleg über oder unter den Positionen; die Stelle ergibt
    #: sich beim Einfügen.
    BELEGTEXT = 'belegtext', 'Text auf dem Beleg'
    #: Anschreiben beim Versand per E-Mail, die einzige Verwendung mit
    #: Platzhaltern, weil es bei jedem Versand neu entsteht.
    MAIL = 'mail', 'Anschreiben beim Versand'


#: Zulässige Platzhalter in Mail-Bausteinen, bewusst wenige, um keine
#: eigene Template-Sprache zu bauen.
MAIL_PLATZHALTER = {
    'nummer': 'Die Belegnummer, z. B. RE-2026-0098',
    'beleg': 'Die Bezeichnung: "Rechnung" am Entwurf, danach mit Nummer',
    'empfaenger': 'Der Name des Empfängers',
    'betrag': 'Der Bruttobetrag mit Währung',
    'firma': 'Der Name der eigenen Firma',
}


class Textbaustein(models.Model):
    """Wiederkehrende Texte, vom Betrieb gepflegt.

    Wird in den Beleg kopiert; daher kein Fremdschlüssel vom Beleg hierher.
    """

    name = models.CharField(
        'Name', max_length=100, unique=True,
        help_text='Der Name in der Auswahlliste, kurz und wiedererkennbar.',
    )
    verwendung = models.CharField(
        'Verwendung', max_length=20, choices=TextbausteinVerwendung,
        help_text='Bestimmt, in welcher Auswahlliste der Baustein erscheint. '
                  'Beim Anschreiben sind Platzhalter erlaubt: '
                  '{nummer}, {beleg}, {empfaenger}, {betrag}, {firma}.',
    )
    #: Belegart, leer für alle, weil "Anbei unsere Rechnung" nur zur
    #: Rechnung passt, eine Grußformel zu jeder Belegart.
    belegart = models.CharField(
        'Belegart', max_length=20, choices=BelegTyp, blank=True, default='',
        help_text='Leer lassen, wenn der Baustein für jede Belegart taugt. '
                  'Sonst erscheint er nur dort.',
    )
    text = models.TextField('Text')

    class Meta:
        verbose_name = 'Textbaustein'
        verbose_name_plural = 'Textbausteine'
        ordering = ['name']

    def __str__(self) -> str:
        return self.name

    @classmethod
    def fuer(cls, verwendung: str, belegart: str = ''):
        """Bausteine dieser Verwendung, die zur Belegart passenden vor den
        allgemeinen. Ohne ``belegart`` alle."""
        gefunden = cls.objects.filter(verwendung=verwendung)
        if not belegart:
            return gefunden
        return (gefunden.filter(models.Q(belegart=belegart) |
                                models.Q(belegart=''))
                # Leere Belegart ist der kleinste Wert; absteigend stehen
                # die spezifischen zuerst.
                .order_by('-belegart', 'name'))

    def gefuellt(self, **werte) -> str:
        """Der Text mit eingesetzten Platzhaltern.

        Ein unbekannter Platzhalter (``{Betrag}``) bleibt unverändert stehen
        und löst keine Exception aus, damit er im Text sichtbar wird.
        """
        try:
            return self.text.format(**werte)
        except (KeyError, IndexError, ValueError):
            return self.text


class Katalogposition(models.Model):
    """Leistungskatalog: Positionen für Angebote und Stammdaten der
    Leistungserfassung.

    Die Belegposition übernimmt Bezeichnung, Einheit, Preis und Steuersatz
    als Kopie; deshalb kein Fremdschlüssel von dort hierher.
    """

    # Optional und unique. Leer als NULL, weil zwei NULL in einem
    # Unique-Index nicht kollidieren.
    nummer = models.CharField(
        'Artikelnummer', max_length=30, unique=True, null=True, blank=True,
        help_text='Freiwillig. Wenn vergeben, dann eindeutig; sie dient dem '
                  'Wiederfinden und dem Verweis im Angebot.',
        db_comment='Freiwillig und eindeutig. NULL statt Leerstring, damit '
                   'mehrere Positionen ohne Nummer nebeneinander bestehen.',
    )
    bezeichnung = models.CharField('Bezeichnung', max_length=300)
    #: Ausführliche Leistungsbeschreibung unter der Bezeichnung.
    langtext = models.TextField(
        'Langtext', blank=True, default='',
        help_text='Ausführliche Leistungsbeschreibung. Erscheint im Beleg '
                  'unter der Bezeichnung und lässt sich dort noch ändern.',
    )
    einheit = models.CharField('Einheit', max_length=20, blank=True, default='Stk')
    einzelpreis = models.DecimalField('Einzelpreis netto', max_digits=12, decimal_places=2)
    steuersatz = models.CharField(
        'Steuersatz', max_length=5, default=steuersatz_tabelle.vorgabe,
    )

    # ── Für die Leistungserfassung ────────────────────────────────────────

    # Default an, weil die meisten Leistungen erfasst werden; reine
    # Angebotszeilen werden abgewählt.
    kontierbar = models.BooleanField(
        'In der Erfassung', default=True,
        help_text='Diese Leistung erscheint in der Leistungserfassung. '
                  'Abwählen bei Positionen, die nur auf Angebote gehören; '
                  'eine "Baustelleneinrichtung pauschal" bucht niemand im Feld.',
        db_comment='Erscheint diese Leistung in der Leistungserfassung? '
                   'Vorgabe an; abgewählt wird bei reinen Angebotszeilen.',
    )
    art = models.CharField(
        'Art der Erfassung', max_length=10, choices=Leistungsart,
        default=Leistungsart.MENGE,
        help_text='Bestimmt, WIE erfasst wird: Zeit über von/bis, Menge '
                  'über eine Zahl, Pauschale gar nicht (Menge 1).',
    )

    class Meta:
        verbose_name = 'Katalogposition'
        verbose_name_plural = 'Leistungskatalog'
        ordering = ['bezeichnung']

    def __str__(self) -> str:
        return f'{self.nummer} {self.bezeichnung}' if self.nummer \
            else self.bezeichnung
