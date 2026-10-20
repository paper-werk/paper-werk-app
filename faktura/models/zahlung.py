"""Zahlungseingänge und ihre Zuordnung auf Rechnungen.

Zahlungen sind eigene Datensätze, weil eine festgeschriebene Rechnung
unveränderlich ist; ihr Zahlungsstand wird berechnet
(``Beleg.offener_betrag``). Zahlung und Rechnung stehen in n:m-Beziehung:
Eine Sammelüberweisung begleicht mehrere Rechnungen, eine Rate einen Teil.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from core.optimistic_locking import ErhoehtElternversion, MitVersion

from .beleg import Beleg, BelegStatus, BelegTyp, Rechnungsart
from .stammdaten import Kontakt


class Zahlungsart(models.TextChoices):
    """Zahlungsart, nur zur Information, ohne Einfluss auf Berechnungen."""

    UEBERWEISUNG = 'ueberweisung', 'Überweisung'
    LASTSCHRIFT = 'lastschrift', 'Lastschrift'
    BAR = 'bar', 'Bar'
    KARTE = 'karte', 'Karte'
    VERRECHNUNG = 'verrechnung', 'Verrechnung'


class Zahlung(MitVersion):
    """Zahlungseingang, brutto wie auf dem Kontoauszug.

    Die Zahlung enthält den Betrag laut Auszug, die Zuordnungen verteilen
    ihn. Nicht Zugeordnetes erscheint als Rest, damit eine übersehene
    Rechnung einer Sammelüberweisung nicht gemahnt wird.
    """

    datum = models.DateField(
        'Zahlungsdatum',
        help_text='Wertstellung laut Auszug',
    )
    betrag = models.DecimalField(
        'Betrag', max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Betrag laut Auszug',
        db_comment='Der Betrag laut Auszug, die Sollgröße. Die Summe der '
                   'Zuordnungen darf ihn nicht überschreiten; was fehlt, '
                   'steht als Rest am Kopf.',
    )
    zahlungsart = models.CharField(
        'Zahlungsart', max_length=20, choices=Zahlungsart,
        default=Zahlungsart.UEBERWEISUNG,
    )
    #: Zahler, nur für die Navigation. Die beglichene Rechnung ergibt sich
    #: aus der Zuordnung, weil etwa eine Hausverwaltung für Eigentümer zahlt.
    kunde = models.ForeignKey(
        Kontakt,
        on_delete=models.PROTECT,
        related_name='zahlungen',
        limit_choices_to={'ist_kunde': True},
        verbose_name='Kunde',
        null=True, blank=True,
        help_text='Zuordnung Kunde zu diesem Zahlungseingang (optional)',
    )
    zahlername = models.CharField(
        'Name laut Auszug', max_length=200, blank=True, default='',
        help_text='Name laut Kontoauszug. Kann abweichen',
    )
    verwendungszweck = models.TextField(
        'Verwendungszweck', blank=True, default='',
    )
    #: ID aus dem Kontoauszug, damit ein wiederholter Import keine Duplikate
    #: erzeugt. Leer als NULL, weil manuell erfasste Zahlungen keine ID haben
    #: und die Spalte unique ist.
    referenz = models.CharField(
        'Referenz', max_length=100, null=True, blank=True, unique=True,
        help_text='Eindeutige Kennung aus dem Kontoauszug. Wird beim Import '
                  'gesetzt und bleibt sonst leer.',
    )
    notiz = models.TextField('Notiz', blank=True, default='')
    erfasst_am = models.DateTimeField('Erfasst am', auto_now_add=True)

    class Meta:
        verbose_name = 'Zahlung'
        verbose_name_plural = 'Zahlungen'
        ordering = ['-datum', '-pk']

    def __str__(self) -> str:
        wer = self.zahlername or (self.kunde.name if self.kunde_id else 'unbekannt')
        return f'{self.datum} {wer} {self.betrag}'

    @property
    def zugeordnet(self) -> Decimal:
        """Auf Rechnungen verteilter Betrag der Zahlung, ohne Skonto, das die
        Zahlung nicht verbraucht."""
        return sum((z.betrag for z in self.zuordnungen.all()), Decimal('0.00'))

    @property
    def rest(self) -> Decimal:
        """Nicht zugeordneter Betrag, nie negativ (``Zahlungszuordnung.clean``)."""
        return self.betrag - self.zugeordnet

    @property
    def ist_verteilt(self) -> bool:
        return self.rest == 0


class Zahlungszuordnung(ErhoehtElternversion):
    """Teil einer Zahlung, der eine Rechnung begleicht.

    ``betrag`` ist der verbrauchte Teil der Zahlung, ``skonto`` mindert die
    Forderung zusätzlich ohne Überweisung; zusammen ergeben sie
    ``ausgleich``. Skonto wird manuell erfasst, weil eine Unterzahlung
    Skonto, Mängelabzug oder Fehler sein kann. Eine Ausbuchung ohne Zahlung
    gehört in eine Rechnungskorrektur.

    ``kuerzung`` gibt es nur beim Abschlag: Der Kunde erkennt einen Teil
    noch nicht an, der Betrieb fordert ihn mit dem nächsten Abschlag oder der
    Schlussrechnung. Anders als Skonto wird er nicht erlassen; er schließt
    nur den offenen Posten, damit nicht gemahnt wird, was anderweitig
    gefordert ist.
    """

    #: Inline-Änderungen inkrementieren die Version des Elternobjekts.
    version_eltern = ('zahlung',)

    zahlung = models.ForeignKey(
        Zahlung,
        on_delete=models.CASCADE,
        related_name='zuordnungen',
        verbose_name='Zahlung',
    )
    beleg = models.ForeignKey(
        Beleg,
        on_delete=models.PROTECT,
        related_name='zahlungszuordnungen',
        verbose_name='Rechnung',
    )
    betrag = models.DecimalField(
        'Betrag', max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text='Was von dieser Zahlung auf diese Rechnung entfällt.',
    )
    skonto = models.DecimalField(
        'Skonto', max_digits=12, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text='Was zusätzlich als Abzug gilt und deshalb nicht '
                  'überwiesen wurde. Mindert die Forderung, nicht die Zahlung.',
        db_comment='Kein Geld: der vereinbarte Abzug. Zusammen mit betrag '
                   'ergibt er, was die Rechnung ausgleicht.',
    )
    kuerzung = models.DecimalField(
        'Gekürzt', max_digits=12, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text='Nur bei Abschlagsrechnungen: was der Kunde noch nicht '
                  'anerkennt und später gefordert wird. Schließt den offenen '
                  'Posten, die Schlussrechnung fordert den Betrag erneut.',
        db_comment='Kein Geld und nicht erlassen; verschoben in einen '
                   'späteren Abschlag oder die Schlussrechnung. Zählt zum '
                   'Ausgleich, nicht zum Vereinnahmten.',
    )
    notiz = models.TextField('Notiz', blank=True, default='')

    class Meta:
        verbose_name = 'Zahlungszuordnung'
        verbose_name_plural = 'Zahlungszuordnungen'
        ordering = ['beleg__nummer', 'pk']
        constraints = [
            # Eine Zeile je Paar, damit ein doppelter Submit die Rechnung
            # nicht doppelt ausgleicht.
            models.UniqueConstraint(
                fields=['zahlung', 'beleg'],
                name='eine_zuordnung_je_zahlung_und_beleg',
                violation_error_message=(
                    'Diese Rechnung steht bei dieser Zahlung schon einmal. '
                    'Bitte den vorhandenen Betrag ändern statt eine zweite '
                    'Zeile anzulegen.'),
            ),
            models.CheckConstraint(
                condition=(models.Q(betrag__gt=0) | models.Q(skonto__gt=0)
                           | models.Q(kuerzung__gt=0)),
                name='zuordnung_traegt_einen_betrag',
                violation_error_message=(
                    'Eine Zuordnung über null Euro sagt nichts. Bitte einen '
                    'Betrag, einen Skontoabzug oder eine Kürzung eintragen.'),
            ),
        ]

    def __str__(self) -> str:
        return f'{self.beleg.nummer or "Entwurf"}: {self.ausgleich}'

    @property
    def ausgleich(self) -> Decimal:
        """Ausgleich der Rechnung durch diese Zeile: Zahlung, Skonto und
        Kürzung."""
        return self.betrag + self.skonto + self.kuerzung

    @property
    def vereinnahmt(self) -> Decimal:
        """Endgültig ausgeglichener Teil: Zahlung plus Skonto ohne Kürzung;
        diesen Betrag setzt die Schlussrechnung ab."""
        return self.betrag + self.skonto

    def clean(self):
        """Nur auf festgeschriebene Rechnungen, höchstens der überwiesene
        Betrag verteilt, höchstens der offene ausgeglichen.

        Die Summen schließen die eigene Zeile aus, damit eine Änderung nicht
        doppelt zählt.
        """
        if self.beleg_id:
            if self.beleg.typ != BelegTyp.RECHNUNG:
                raise ValidationError({
                    'beleg': 'Zahlungen lassen sich nur Rechnungen zuordnen.',
                })
            if self.beleg.status == BelegStatus.ENTWURF:
                raise ValidationError({
                    'beleg': 'Auf einen Entwurf wird nicht gezahlt; die '
                             'Rechnung muss festgeschrieben sein.',
                })
            if (self.kuerzung and self.kuerzung > 0
                    and self.beleg.rechnungsart != Rechnungsart.ABSCHLAG):
                raise ValidationError({
                    'kuerzung': 'Gekürzt wird nur ein Abschlag: Nur dort '
                                'fordert die Schlussrechnung den Betrag '
                                'erneut. Bei einer anderen Rechnung ist ein '
                                'endgültiger Abzug Skonto oder eine '
                                'Rechnungskorrektur.',
                })

        if self.zahlung_id and self.betrag is not None:
            andere = self.zahlung.zuordnungen.exclude(pk=self.pk)
            verteilt = sum((z.betrag for z in andere), Decimal('0.00'))
            if verteilt + self.betrag > self.zahlung.betrag:
                frei = self.zahlung.betrag - verteilt
                raise ValidationError({
                    'betrag': f'Von dieser Zahlung sind nur noch {frei} EUR '
                              f'frei.',
                })

        if self.beleg_id and self.betrag is not None:
            from .. import services

            offen = services.offener_betrag(self.beleg, ausser=self.pk)
            schluss = services.abgerechnet_in(self.beleg)
            if schluss is not None and self.ausgleich > offen:
                raise ValidationError({
                    'beleg': f'{self.beleg} ist mit {schluss} abgerechnet; '
                             f'was darauf noch fehlte, fordert diese. Die '
                             f'Zahlung bitte {schluss} zuordnen.',
                })
            if self.ausgleich > offen:
                raise ValidationError({
                    'betrag': f'Auf diese Rechnung sind nur noch {offen} EUR '
                              f'offen.',
                })
