"""Abnahme, aus der das steuerliche Leistungsdatum stammt.

Die *Gesamtabnahme* schließt den Auftrag ab; aus ihr entsteht die
Schlussrechnung. Die *Teilabnahme* schließt eine gesondert geschuldete
Teilleistung ab (ganze Auftragspositionen, z. B. "Lph 1-4"); nur aus ihr
entsteht eine Teilschlussrechnung. Im Regelfall sind Abschläge Anzahlungen,
und es gibt keine Teilabnahme.

Eigene Tabelle, weil Auftrag und Auftragspositionen festgeschrieben und
gesperrt sind; die Abnahme folgt später und betrifft die Erfüllung des
Vertrags.

Das Leistungsdatum ist ein eigenes Feld, obwohl es meist dem Abnahmedatum
entspricht, damit keine steuerliche Angabe nur aus einem anderen Feld
abgeleitet wird. ``save()`` setzt es vor.

Entgelt und Steuersatz stehen an den Auftragspositionen: Das gesondert
vereinbarte Entgelt ist deren Summe, und der Satz wird von dort in die
Teilschlussrechnung kopiert.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from simple_history.models import HistoricalRecords

from core import rechnen
from core.optimistic_locking import FELD as VERSIONSFELD
from core.optimistic_locking import MitVersion


class Abnahmeart(models.TextChoices):
    GESAMT = 'gesamt', 'Gesamtabnahme'
    TEIL = 'teil', 'Teilabnahme'


class Abnahmestand(models.TextChoices):
    """Abgeleiteter Zustand ohne Datenbankfeld, siehe ``Abnahme.stand``."""

    OFFEN = 'offen', 'offen'
    ABGENOMMEN = 'abgenommen', 'abgenommen'
    ABGERECHNET = 'abgerechnet', 'abgerechnet'


class Abnahme(MitVersion):
    auftrag = models.ForeignKey(
        'faktura.Beleg',
        on_delete=models.PROTECT,
        related_name='abnahmen',
        limit_choices_to={'typ': 'auftrag', 'status': 'festgeschrieben',
                          'nachtrag_zu__isnull': True},
        verbose_name='Auftrag',
    )
    art = models.CharField('Art', max_length=10, choices=Abnahmeart,
                           default=Abnahmeart.GESAMT)
    bezeichnung = models.CharField(
        'Bezeichnung', max_length=200, blank=True, default='',
        help_text='Bei der Teilabnahme: welche Teilleistung, z. B. '
                  '"Leistungsphasen 1-4".')
    positionen = models.ManyToManyField(
        'faktura.Belegposition',
        blank=True,
        related_name='teilabnahmen',
        verbose_name='Auftragspositionen',
        help_text='Nur bei der Teilabnahme: die Positionen der '
                  'Teilleistung: ganze Positionen, aus diesem Auftrag oder '
                  'seinen Nachträgen.',
    )
    leistungsbeginn = models.DateField('Leistungsbeginn', null=True,
                                       blank=True)
    leistungsende = models.DateField('Leistungsende', null=True, blank=True)
    abgenommen_am = models.DateField(
        'Abgenommen am', null=True, blank=True,
        help_text='Abnahme bzw. Vollendung unserer Leistung, nicht die '
                  'Abnahme der Bauleistung eines anderen. Leer: noch offen.')
    steuerliches_leistungsdatum = models.DateField(
        'Leistungsdatum', null=True, blank=True,
        help_text='Geht als Leistungsdatum in die Rechnung. Vorbelegt mit '
                  'dem Abnahmedatum; nur ändern, wenn der Steuerberater es '
                  'anders sieht.')
    notiz = models.TextField('Notiz', blank=True, default='')
    erfasst_am = models.DateTimeField('Erfasst am', auto_now_add=True)

    history = HistoricalRecords(verbose_name='Änderung der Abnahme',
                                excluded_fields=[VERSIONSFELD])

    class Meta:
        verbose_name = 'Abnahme'
        verbose_name_plural = 'Abnahmen'
        ordering = ['auftrag', 'art', 'pk']
        constraints = [
            # Eine Gesamtabnahme je Auftrag, weil zwei Abnahmen zwei
            # Leistungsdaten für dieselbe Leistung ergäben.
            models.UniqueConstraint(
                fields=['auftrag'], condition=models.Q(art='gesamt'),
                name='abnahme_eine_gesamtabnahme_je_auftrag'),
        ]

    def __str__(self) -> str:
        was = self.bezeichnung or self.get_art_display()
        nummer = self.auftrag.nummer if self.auftrag_id else 'ohne Auftrag'
        return f'{was} ({nummer})'

    def save(self, *args, **kwargs):
        if self.abgenommen_am and not self.steuerliches_leistungsdatum:
            self.steuerliches_leistungsdatum = self.abgenommen_am
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.auftrag_id:
            from .beleg import BelegStatus, BelegTyp
            auftrag = self.auftrag
            if (auftrag.typ != BelegTyp.AUFTRAG
                    or auftrag.status != BelegStatus.FESTGESCHRIEBEN
                    or auftrag.nachtrag_zu_id):
                raise ValidationError({
                    'auftrag': 'Abgenommen wird ein festgeschriebener '
                               'Hauptauftrag; seine Nachträge gehören dazu.'})
        if (self.leistungsbeginn and self.leistungsende
                and self.leistungsende < self.leistungsbeginn):
            raise ValidationError({
                'leistungsende': 'Das Ende liegt vor dem Beginn.'})
        if self.steuerliches_leistungsdatum and not self.abgenommen_am:
            raise ValidationError({
                'abgenommen_am': 'Ohne Abnahme kein Leistungsdatum; die '
                                 'Leistung ist noch nicht vollendet.'})
        if self.pk and self.ist_abgerechnet and self._geaendert():
            raise ValidationError(
                f'{self} ist abgerechnet und kann nicht mehr geändert werden.')

    def _geaendert(self) -> bool:
        alt = Abnahme.objects.filter(pk=self.pk).values(
            'art', 'leistungsbeginn', 'leistungsende', 'abgenommen_am',
            'steuerliches_leistungsdatum').first()
        return alt is not None and any(
            getattr(self, feld) != wert for feld, wert in alt.items())

    # --- Abgeleitetes ---

    @property
    def rechnung(self):
        """Festgeschriebene (Teil-)Schlussrechnung oder None."""
        from .beleg import BelegStatus
        return self.rechnungen.filter(
            status=BelegStatus.FESTGESCHRIEBEN).first()

    @property
    def ist_abgerechnet(self) -> bool:
        return self.rechnung is not None

    @property
    def stand(self) -> str:
        if self.ist_abgerechnet:
            return Abnahmestand.ABGERECHNET
        if self.abgenommen_am:
            return Abnahmestand.ABGENOMMEN
        return Abnahmestand.OFFEN

    def auftragspositionen(self):
        """Abgeschlossene Positionen: bei der Teilabnahme die gewählten, bei der
        Gesamtabnahme alle des Auftrags und seiner Nachträge."""
        from .beleg import Belegposition
        if self.art == Abnahmeart.TEIL:
            return self.positionen.order_by('beleg__pk', 'sortierung')
        return Belegposition.objects.filter(
            models.Q(beleg=self.auftrag_id)
            | models.Q(beleg__nachtrag_zu=self.auftrag_id),
            beleg__status='festgeschrieben',
        ).order_by('beleg__pk', 'sortierung')

    @property
    def entgelt_netto(self) -> Decimal:
        """Vereinbartes Entgelt als Summe der Positionen ohne optionale
        (R-178), weil bei diesen nur der Preis vereinbart ist."""
        return sum((rechnen.auf_cent(p.menge * p.einzelpreis)
                    for p in self.auftragspositionen() if not p.optional),
                   Decimal('0.00'))
