"""Die wählbaren Umsatzsteuersätze.

Als Tabelle, damit der Betrieb einen geänderten Satz zum Stichtag selbst
anlegen kann, ohne Update der Software.

Die Tabelle bestimmt nur die Auswahl. Belegposition und Katalogposition
speichern den Satz als Text (``'19.00'``), weil Stammdaten kopiert werden
(``entscheidungen.md``); eine Rechnung von 2020 behält ihre 16 %. Daraus
folgt: ``satz`` ist nach dem Anlegen unveränderlich, Sätze werden nicht
gelöscht. Ein inaktiver Satz fehlt in der Auswahl neuer Positionen und
bleibt gültiger Wert bestehender.

Keine Gültigkeitszeiträume, weil der Satz je Position gewählt und nicht
aus dem Leistungsdatum abgeleitet wird.

Die Grundausstattung legt ``grundausstattung_anlegen`` nach jedem
``migrate`` an, wenn die Tabelle leer ist (``FakturaConfig.ready``). Über
``post_migrate``, weil auch ``flush`` das Signal sendet und die Tabelle nach
einem Transaktionstest wieder gefüllt ist. Verworfen: eine Datenmigration.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction

from .. import formate

#: 0 % ist fest und unabhängig von der Tabelle, weil Mahnung, Lieferschein
#: und die Steuerfälle (§ 13b, Ausfuhr, § 19) ihn gesetzlich setzen. Der
#: Satz 0 lässt sich daher nicht deaktivieren.
STEUERFREI = '0.00'

#: (Satz, Bezeichnung, Vorgabe) in der Reihenfolge der Auswahl. Die
#: gesenkten Sätze galten im zweiten Halbjahr 2020 und sind enthalten, weil
#: Kataloge und Belege aus dieser Zeit sie verwenden.
GRUNDAUSSTATTUNG = [
    ('19.00', 'Regelsteuersatz', True),
    ('7.00', 'ermäßigt', False),
    ('0.00', 'steuerfrei', False),
    ('16.00', 'gesenkter Regelsteuersatz', False),
    ('5.00', 'gesenkter ermäßigter Satz', False),
]


def als_wert(satz) -> str:
    """Gespeicherter Text eines Satzes, immer mit zwei Nachkommastellen,
    weil Filter Text vergleichen (``exclude(steuersatz=STEUERFREI)``) und
    ``'0'`` und ``'0.00'`` dort verschieden wären."""
    return f'{Decimal(satz):.2f}'


class Steuersatz(models.Model):
    satz = models.DecimalField(
        'Satz in %', max_digits=4, decimal_places=2, unique=True,
        validators=[MinValueValidator(Decimal('0')),
                    MaxValueValidator(Decimal('99.99'))],
        help_text='Nach dem Anlegen nicht mehr änderbar. Positionen '
                  'speichern den Satz als Wert, nicht als Verweis.',
    )
    bezeichnung = models.CharField(
        'Bezeichnung', max_length=60, blank=True,
        help_text='Steht in der Auswahl hinter dem Satz, '
                  'z. B. „19 % (Regelsteuersatz)“.',
    )
    aktiv = models.BooleanField(
        'Wählbar', default=True,
        help_text='Abgewählt fehlt der Satz in der Auswahl neuer Positionen. '
                  'Bestehende Positionen behalten ihn.',
    )
    vorgabe = models.BooleanField(
        'Vorgabe', default=False,
        help_text='Vorbelegt an neuen Positionen und Katalogeinträgen. '
                  'Genau ein Satz ist Vorgabe.',
    )
    reihenfolge = models.PositiveSmallIntegerField(
        'Reihenfolge', default=0,
        help_text='Position in der Auswahl, kleinere Zahl zuerst.',
    )

    class Meta:
        verbose_name = 'Steuersatz'
        verbose_name_plural = 'Steuersätze'
        ordering = ['reihenfolge', '-satz']
        constraints = [
            models.UniqueConstraint(
                fields=['vorgabe'], condition=models.Q(vorgabe=True),
                name='steuersatz_eine_vorgabe',
            ),
            models.CheckConstraint(
                condition=models.Q(vorgabe=False) | models.Q(aktiv=True),
                name='steuersatz_vorgabe_ist_aktiv',
            ),
            models.CheckConstraint(
                condition=~models.Q(satz=0) | models.Q(aktiv=True),
                name='steuersatz_null_bleibt_aktiv',
            ),
        ]

    def __str__(self) -> str:
        text = formate.prozent(self.satz)
        return f'{text} ({self.bezeichnung})' if self.bezeichnung else text

    def save(self, *args, **kwargs):
        """Eine neue Vorgabe ersetzt die bisherige in derselben Transaktion,
        damit ``steuersatz_eine_vorgabe`` nicht verletzt wird."""
        with transaction.atomic():
            if self.vorgabe:
                Steuersatz.objects.filter(vorgabe=True).exclude(
                    pk=self.pk).update(vorgabe=False)
            super().save(*args, **kwargs)

    def get_constraints(self):
        """Ohne ``steuersatz_eine_vorgabe`` in ``full_clean``, weil die neue
        Vorgabe die alte erst in ``save()`` ersetzt. In der Datenbank gilt
        der Constraint."""
        return [(klasse, [c for c in constraints
                          if c.name != 'steuersatz_eine_vorgabe'])
                for klasse, constraints in super().get_constraints()]

    @property
    def wert(self) -> str:
        """Text, den eine Position speichert."""
        return als_wert(self.satz)

    def clean(self):
        alt = (Steuersatz.objects.filter(pk=self.pk)
               .values('satz', 'vorgabe').first() if self.pk else None)
        fehler = {}
        if alt and self.satz is not None and alt['satz'] != self.satz:
            fehler['satz'] = ('Der Satz ist nach dem Anlegen fest. Legen Sie '
                              'den neuen Satz an und nehmen Sie den alten aus '
                              'der Auswahl.')
        if alt and alt['vorgabe'] and not self.vorgabe:
            fehler['vorgabe'] = ('Ein Satz muss Vorgabe sein. Setzen Sie die '
                                 'Vorgabe an dem Satz, der sie übernimmt.')
        if self.vorgabe and not self.aktiv:
            fehler['aktiv'] = 'Die Vorgabe muss wählbar sein.'
        if self.satz == 0 and not self.aktiv:
            fehler['aktiv'] = ('0 % bleibt wählbar: Mahnung, Lieferschein und '
                               'die Steuerfälle setzen ihn.')
        if fehler:
            raise ValidationError(fehler)


def vorgabe() -> str:
    """Vorgabesatz als gespeicherter Text, ``''`` ohne Vorgabe.

    Callable-Default von Belegposition und Katalogposition."""
    satz = (Steuersatz.objects.filter(vorgabe=True)
            .values_list('satz', flat=True).first())
    return als_wert(satz) if satz is not None else ''


def anzeige(wert: str) -> str:
    """``19 % (Regelsteuersatz)`` zum gespeicherten Text; ohne Eintrag in
    der Tabelle nur der Satz."""
    satz = Decimal(wert)
    treffer = Steuersatz.objects.filter(satz=satz).first()
    return str(treffer) if treffer else formate.prozent(satz)


def angeboten(aktuell: str | None = None, *, kurz: bool = False) -> list[tuple[str, str]]:
    """Choices für ein Formular: alle aktiven Sätze, dazu ``aktuell``, wenn
    die Position einen inzwischen inaktiven hat.

    ``kurz`` ohne Bezeichnung (``19 %``) für die schmale Spalte der
    Positionszeile."""
    saetze = Steuersatz.objects.filter(models.Q(aktiv=True) | models.Q(
        satz=Decimal(aktuell) if aktuell else None))
    return [(s.wert, formate.prozent(s.satz) if kurz else str(s))
            for s in saetze]


def grundausstattung_anlegen(sender, apps=None, using='default', **kwargs):
    """``post_migrate``: legt ``GRUNDAUSSTATTUNG`` an, wenn die Tabelle leer
    ist. Eine gefüllte Tabelle bleibt unverändert.

    ``migrate`` übergibt den Migrationsstand als ``apps``, ``flush`` nicht;
    dann gilt die globale Registry."""
    if apps is None:
        from django.apps import apps
    try:
        modell = apps.get_model('faktura', 'Steuersatz')
    except LookupError:
        # Migrationsstand vor dieser Tabelle.
        return
    if modell.objects.using(using).exists():
        return
    modell.objects.using(using).bulk_create([
        modell(satz=Decimal(satz), bezeichnung=bezeichnung, vorgabe=ist_vorgabe,
               reihenfolge=(nummer + 1) * 10)
        for nummer, (satz, bezeichnung, ist_vorgabe) in enumerate(GRUNDAUSSTATTUNG)
    ])
