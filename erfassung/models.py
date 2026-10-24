"""Modelle der Leistungserfassung.

* ``Erfassungszeile``: eigene Leistung als Zeit (von/bis) oder Menge
  (Kilometer, Stück), kontiert auf eine Auftragsposition oder ersatzweise
  eine Katalogleistung.
* ``Eingangsrechnung`` und ``Fremdleistung``: zugekaufte Leistung zum
  Einkaufspreis, auf Projekte verteilt. Der Verkaufspreis entsteht in der
  Rechnung.
* ``Kostensatz``: Kosten einer Arbeitsstunde für den Betrieb.

Eigene und zugekaufte Leistung durchlaufen dieselbe Übernahme in die
Rechnung (``services.in_rechnung_uebernehmen``): Die Zeile erhält einen
Verweis auf die Belegposition, nicht übernommene bleiben offen. Die App
hängt an den Stammdaten von ``faktura`` (Projekt, Katalogposition).
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.optimistic_locking import ErhoehtElternversion, MitVersion
from faktura.formate import geld
from faktura.models import Leistungsart

from .formate import MINUTEN_JE_TAG, dauer_zeigen


class Zustand(models.TextChoices):
    """Die drei Zustände einer Zeile, abgeleitet aus ``abrechenbar`` und
    ``abgerechnet_in`` und nicht gespeichert.

    Auch nicht abrechenbare Leistung (Gewährleistung, Kulanz) wird erfasst,
    weil sie Kosten verursacht und in die Nachkalkulation gehört.
    """

    NICHT_ABRECHENBAR = 'nicht_abrechenbar', 'Nicht abrechenbar'
    OFFEN = 'offen', 'Offen'
    ABGERECHNET = 'abgerechnet', 'Abgerechnet'


def wurde_geaendert(instanz) -> bool:
    """Ob das Objekt vom gespeicherten Stand abweicht.

    Django validiert im Formset jede vorhandene Zeile, auch unveränderte;
    ohne diese Prüfung verhinderte eine gesperrte Position das Speichern der
    ganzen Eingangsrechnung. Kostet eine Abfrage, deshalb erst nach der
    Sperrprüfung aufrufen. Ein neues Objekt gilt als geändert.
    """
    if instanz.pk is None or instanz._state.adding:
        return True

    namen = [feld.attname for feld in instanz._meta.concrete_fields]
    alt = (type(instanz)._base_manager
           .filter(pk=instanz.pk).values(*namen).first())
    if alt is None:
        return True
    return any(getattr(instanz, name) != alt[name] for name in namen)


class ErfassungszeileQuerySet(models.QuerySet):

    def im_zustand(self, zustand: str):
        """Filtert auf einen der drei Zustände, dieselbe Regel wie
        ``Erfassungszeile.zustand`` in SQL; "nicht abrechenbar" hat Vorrang.
        Ein Test prüft, dass beide übereinstimmen."""
        if zustand == Zustand.NICHT_ABRECHENBAR:
            return self.filter(abrechenbar=False)
        if zustand == Zustand.OFFEN:
            return self.filter(abrechenbar=True, abgerechnet_in__isnull=True)
        if zustand == Zustand.ABGERECHNET:
            return self.filter(abrechenbar=True, abgerechnet_in__isnull=False)
        raise ValueError(f'Unbekannter Zustand: {zustand!r}')


class Erfassungszeile(models.Model):
    """Erbrachte Leistung, kontiert auf ein Projekt.

    Datum und Uhrzeiten getrennt ohne DateTimeField, weil Erfassung
    Ortszeit ist: "8:00 bis 12:00" sind vier Stunden, auch am Tag der
    Zeitumstellung.

    Zwei Umfangsfelder: Zeit in ganzen Minuten (eine Drittelstunde ist als
    Dezimalzahl nicht exakt), Menge als Decimal. Welches gilt, bestimmt die
    Leistungsart. Beim Übernehmen in die Rechnung wird die Zeit in Stunden
    umgerechnet und auf die Viertelstunde aufgerundet.
    """

    datum = models.DateField('Datum', default=timezone.localdate)
    projekt = models.ForeignKey(
        'faktura.Projekt',
        on_delete=models.PROTECT,
        related_name='erfassung',
        verbose_name='Projekt',
    )
    # ── Grundlage ────────────────────────────────────────────────────────
    #
    # Genau eines von beiden (``_pruefe_grundlage``). Regelfall ist die
    # Auftragsposition: Der Preis kommt aus dem Vertrag, und die Rechnung
    # kann gegen die Position abrechnen. Die Katalogposition ist für Arbeit
    # ohne Auftrag.
    auftragsposition = models.ForeignKey(
        'faktura.Belegposition',
        on_delete=models.PROTECT,
        null=True, blank=True,
        limit_choices_to={'beleg__typ': 'auftrag',
                          'beleg__status': 'festgeschrieben',
                          # Auf einen Titel, Text oder Zuschlag wird nicht
                          # gearbeitet.
                          'zeilenart': 'leistung'},
        related_name='kontierungen',
        verbose_name='Auftragsposition',
        db_comment='Der Regelfall. Preis und Einheit kommen von hier, also '
                   'aus dem Vertrag und nicht aus dem Katalog.',
    )
    leistung = models.ForeignKey(
        'faktura.Katalogposition',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='erfassung',
        verbose_name='Leistung aus dem Katalog',
    )
    # PROTECT, weil die erfassende Person zum Nachweis gehört; Konten werden
    # deaktiviert und nicht gelöscht.
    benutzer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='erfassung',
        verbose_name='Person',
    )

    # ── Zeitleistungen ───────────────────────────────────────────────────
    #
    # In der Datenbank optional, weil eine Anfahrt keine Uhrzeiten hat; bei
    # einer Zeitleistung verlangt ``_pruefe_umfang`` sie.
    von = models.TimeField(
        'Von', null=True, blank=True,
        db_comment='Wanduhrzeit, kein Zeitpunkt, deshalb time und nicht '
                   'timestamp. Am Tag der Zeitumstellung sind 8:00 bis 12:00 '
                   'vier Stunden, und bezahlt werden vier. Freiwillig: fehlt '
                   'von oder bis, ist die Dauer 0.',
    )
    bis = models.TimeField(
        'Bis', null=True, blank=True,
        db_comment='Siehe von. Muss am selben Tag liegen; eine Schicht über '
                   'Mitternacht wird auf zwei Zeilen aufgeteilt.',
    )

    #: In ``save()`` aus von/bis berechnet und gespeichert, damit Summen und
    #: Sortierung in der Datenbank laufen.
    dauer_minuten = models.PositiveIntegerField(
        'Dauer in Minuten', default=0, editable=False,
        db_comment='BERECHNET aus von/bis, nie eingegeben. Ganze Minuten, '
                   'weil eine Drittelstunde als Dezimalzahl nur gerundet zu '
                   'haben ist (0,333 h weichen je Zeile um 1,2 Sekunden ab). '
                   'Gilt nur bei Leistungen der Art "zeit"; bei Mengen- und '
                   'Pauschalleistungen steht hier 0.',
    )

    # ── Mengenleistungen ─────────────────────────────────────────────────
    #
    # Dieselbe Genauigkeit wie Belegposition.menge. NULL bedeutet keine
    # Menge, nicht null Stück; bei einer Mengenleistung verlangt
    # ``_pruefe_umfang`` sie.
    menge = models.DecimalField(
        'Menge', max_digits=10, decimal_places=3, null=True, blank=True,
        db_comment='EINGEGEBEN, freiwillig. NULL heißt "keine Menge"; bei '
                   'Zeitleistungen gibt es keine, bei Mengenleistungen ohne '
                   'Angabe fehlt sie noch. Zusammen mit dauer_minuten die '
                   'zweite Mengenspalte: die eine wird getippt, die andere '
                   'gerechnet. In einer Spalte vereint wäre die Dauer wieder '
                   'eingebbar, neben von/bis, und die beiden liefen '
                   'auseinander.',
    )

    # Optional, etwa bei einer Anfahrt.
    beschreibung = models.CharField(
        'Beschreibung', max_length=300, blank=True, default='',
        db_comment='Freiwillig. Bei Mengenleistungen wie einer Anfahrt sagt '
                   'die Leistung selbst schon, was geschehen ist.',
    )

    # ── Abrechnung ───────────────────────────────────────────────────────
    #
    # Zwei Felder ergeben drei Zustände (siehe Zustand); kein Statusfeld.
    abrechenbar = models.BooleanField(
        'Abrechenbar', default=True,
        db_comment='Kaufmännische Entscheidung, keine Erfassungsangabe, '
                   'deshalb im Formular nur für die Leitung sichtbar. '
                   'Vorgabe true: Der Normalfall ist abrechenbar, und die '
                   'Ausnahme soll die Ausnahme bleiben.',
    )
    # Verweis auf die Position, damit das Entfernen einer Position aus dem
    # Entwurf genau ihre Zeilen freigibt. SET_NULL ist der einzige Weg aus
    # der Sperre (``ist_gesperrt``); entsperrt wird über die Rechnung.
    abgerechnet_in = models.ForeignKey(
        'faktura.Belegposition',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='erfassung',
        verbose_name='Abgerechnet in',
        help_text='Wird beim Übernehmen in eine Rechnung gesetzt. Kein '
                  'Eingabefeld.',
        db_comment='Die Rechnungsposition, auf der diese Zeile steht. '
                   'SET_NULL: Wird die Position entfernt oder der Entwurf '
                   'verworfen, ist die Zeile wieder abrechenbar. Der Beleg '
                   'ergibt sich über abgerechnet_in.beleg.',
    )

    objects = ErfassungszeileQuerySet.as_manager()

    #: Historie jedes früheren Stands mit Benutzer und Zeitpunkt (GoBD), weil
    #: eine Zeit abrechnungsrelevantes Ursprungsdatum ist. Nicht erfasst wird
    #: ``QuerySet.update()``, mit dem die Übernahme ``abgerechnet_in`` setzt;
    #: das ist an der Rechnungsposition nachvollziehbar.
    history = HistoricalRecords(verbose_name='Änderung der Erfassungszeile')

    class Meta:
        verbose_name = 'Erfassungszeile'
        verbose_name_plural = 'Erfassung'
        ordering = ['-datum', '-pk']
        permissions = [
            # Eigenes Recht, weil "Zeilen ändern" sonst Einblick in die
            # Stunden aller gäbe.
            ('fuer_andere_erfassen', 'Kann für andere Personen erfassen'),
        ]
        constraints = [
            # In der Datenbank, damit auch bulk_create und Importe geprüft
            # werden.
            models.CheckConstraint(
                condition=models.Q(dauer_minuten__lte=MINUTEN_JE_TAG),
                name='erfassungszeile_hoechstens_ein_tag',
            ),
        ]

    def __str__(self) -> str:
        # projekt_id, weil eine ungespeicherte Zeile noch kein Projekt hat.
        projekt = self.projekt.nummer if self.projekt_id else 'ohne Projekt'
        return f'{self.datum:%d.%m.%Y} {self.dauer} {projekt}'

    def save(self, *args, **kwargs):
        """Setzt die Dauer. In ``save()``, weil auch Service, Import und Shell
        darüber schreiben."""
        self.dauer_minuten = self.berechnete_dauer()
        self._pauschale_angleichen()
        super().save(*args, **kwargs)

    def _pauschale_angleichen(self) -> None:
        """Behandelt Uhrzeiten auf einer Pauschale als Aufwand.

        Das Controlling zeigt so die Zeit, die in einer Pauschale steckt. Eine
        Zeile mit Uhrzeiten wird nicht abrechenbar und hat keine Menge, sonst
        stünde die Pauschale je Zeitzeile auf der Rechnung. Die Stunden zählen
        als Personalkosten. Abgerechnet wird die Pauschale über eine Zeile
        ohne Uhrzeit mit Menge 1.

        Werden die Uhrzeiten entfernt, bleibt "abrechenbar" aus, weil das
        Modell nicht unterscheiden kann, ob es vorher absichtlich aus war.
        """
        if not self.grundlage or self.leistungsart != Leistungsart.PAUSCHALE:
            return
        if self.dauer_minuten:
            self.abrechenbar = False
            self.menge = None
        elif self.menge is None:
            self.menge = Decimal('1')

    def _pruefe_grundlage(self) -> None:
        """Prüft, dass genau eine Grundlage gesetzt ist und zum Projekt gehört.

        Kein Constraint, weil die Projektregel einen zweiten Datensatz liest.
        """
        if self.auftragsposition_id and self.leistung_id:
            raise ValidationError({
                "leistung": "Entweder eine Auftragsposition oder eine "
                            "Leistung aus dem Katalog, nicht beides. Sonst "
                            "stünden zwei Preise nebeneinander, und keiner "
                            "wäre der richtige.",
            })

        # Fehler am Feld Leistung, weil die Auftragsposition optional ist und
        # nicht jedes Projekt einen Auftrag hat.
        if not self.auftragsposition_id and not self.leistung_id:
            raise ValidationError({
                "leistung": "Ohne Auftragsposition braucht die Zeile eine "
                            "Leistung aus dem Katalog. Sie bestimmt Einheit "
                            "und Preis.",
            })

        # Verhindert Leistung auf dem Auftrag und der Rechnung eines anderen
        # Kunden.
        if self.auftragsposition_id:
            if self.auftragsposition.zeilenart != 'leistung':
                raise ValidationError({
                    "auftragsposition": "Auf einen Titel, Text oder "
                                        "Zuschlag wird nicht gearbeitet; "
                                        "bitte eine Leistung wählen.",
                })
            auftrag = self.auftragsposition.beleg
            if auftrag.projekt_id != self.projekt_id:
                raise ValidationError({
                    "auftragsposition": f"{auftrag} gehört zu einem "
                                        f"anderen Projekt.",
                })

    def _pruefe_umfang(self) -> None:
        """Prüft den Umfang je nach Leistungsart.

        * **Zeit:** von und bis; eine Menge wird nicht verwendet.
        * **Menge:** Menge ungleich null.
        * **Pauschale:** keine Angabe, die Menge ist immer 1.

        Ohne Grundlage entfällt die Prüfung, weil ``_pruefe_grundlage`` den
        Fehler meldet. Kein Constraint, weil die Art in einer anderen Tabelle
        steht. Altdaten ohne Umfang bleiben möglich; Liste und
        Abrechnungsvorschau behandeln sie (``GRUND_OHNE_UMFANG``).
        """
        if not self.grundlage:
            return

        art = self.leistungsart

        if art == Leistungsart.ZEIT and not self.berechnete_dauer():
            raise ValidationError({
                'von': 'Ohne Von und Bis hat diese Zeile keine Dauer und '
                       'damit nichts, was sich nachweisen oder abrechnen '
                       'ließe. Wer die Uhrzeiten noch nicht kennt, trägt sie '
                       'nach; eine leere Zeile hilft niemandem.',
            })

        if art == Leistungsart.MENGE and not self.menge:
            raise ValidationError({
                'menge': f'Bei "{self.leistungsbezeichnung}" gehört eine '
                         f'Menge dazu ({self.einheit}), sonst steht '
                         f'die Zeile ohne Umfang in Nachweis und Abrechnung.',
            })

    @property
    def dauer(self) -> str:
        """Die Dauer als ``h:mm``."""
        return dauer_zeigen(self.dauer_minuten)

    @property
    def grundlage(self):
        """Auftrags- oder Katalogposition, aus der Bezeichnung, Einheit,
        Preis, Steuersatz und Art kommen. Beide haben dieselben Felder, so
        dass Aufrufer nicht unterscheiden müssen."""
        return self.auftragsposition or self.leistung

    @property
    def leistungsart(self) -> str:
        """Zeit, Menge oder Pauschale. Ohne Art (von Hand eingegebene
        Auftragsposition) gilt MENGE, damit keine Ausnahme entsteht."""
        grundlage = self.grundlage
        return (grundlage.art if grundlage else "") or Leistungsart.MENGE

    @property
    def leistungsbezeichnung(self) -> str:
        """Bezeichnung der Leistung für Nachweis, Listen und Rechnung."""
        return self.grundlage.bezeichnung if self.grundlage else ""

    @property
    def einheit(self) -> str:
        return self.grundlage.einheit if self.grundlage else ""

    @property
    def einzelpreis(self):
        """Preis aus der Auftragsposition, sonst aus dem Katalog."""
        return self.grundlage.einzelpreis if self.grundlage else None

    @property
    def steuersatz(self) -> str:
        return self.grundlage.steuersatz if self.grundlage else ""

    @property
    def ist_zeitleistung(self) -> bool:
        return bool(self.grundlage) and self.leistungsart == Leistungsart.ZEIT

    @property
    def dauer_anzeige(self) -> str:
        """Dauer zur Anzeige: bei einer Anfahrt leer, bei Stunden auf einer
        Pauschale die Stunden."""
        return self.dauer if self.ist_zeitleistung or self.dauer_minuten else ''

    @property
    def umfang(self) -> str:
        """Menge mit Einheit, bei Zeitzeilen leer. Am Modell, weil Liste und
        Leistungsnachweis sie verwenden."""
        if self.ist_zeitleistung or self.menge is None:
            return ''
        return f'{self.menge.normalize():f} {self.einheit}'.strip()

    @property
    def zustand(self) -> str:
        """Abgeleiteter Zustand; "nicht abrechenbar" hat Vorrang, auch wenn
        ein Beleg verweist. ``im_zustand()`` filtert nach derselben Regel."""
        if not self.abrechenbar:
            return Zustand.NICHT_ABRECHENBAR
        if self.abgerechnet_in_id:
            return Zustand.ABGERECHNET
        return Zustand.OFFEN

    @property
    def zustand_anzeige(self) -> str:
        return Zustand(self.zustand).label

    @property
    def abgerechneter_beleg(self):
        """Beleg, auf dem die Zeile abgerechnet ist, oder None. Für Meldungen
        wie "mit RE-2026-0007 abgerechnet"."""
        return self.abgerechnet_in.beleg if self.abgerechnet_in_id else None

    @property
    def ist_gesperrt(self) -> bool:
        """Ob die Zeile auf einer Rechnung steht, Entwürfe eingeschlossen.

        Entwürfe gehen oft zur Prüfung an den Auftraggeber und dürfen sich
        dann nicht ändern. Geändert wird über die Rechnung (Position
        entfernen). Verwendet von ``clean()`` und ``services.zeile_aendern``
        (dort als 409).
        """
        return bool(self.abgerechnet_in_id)

    def berechnete_dauer(self) -> int:
        """Minuten aus ``von`` und ``bis``, null, wenn eines fehlt."""
        if self.von is None or self.bis is None:
            return 0
        minuten = (self.bis.hour * 60 + self.bis.minute) - (
            self.von.hour * 60 + self.von.minute)
        return max(minuten, 0)

    def clean(self):
        """Validierung mit Meldungen an den Feldern.

        Die Regel "kein abgeschlossenes Projekt" prüft der Service, damit
        ältere Zeilen eines später abgeschlossenen Projekts korrigierbar
        bleiben.
        """
        super().clean()

        if self.datum and self.datum > timezone.localdate():
            raise ValidationError({
                'datum': 'Erfasst wird für vergangene Tage und heute; '
                         'gearbeitet wird nicht im Voraus.',
            })

        if self.von is not None and self.bis is not None and self.bis <= self.von:
            raise ValidationError({
                'bis': 'Die Endzeit muss nach der Anfangszeit liegen. Eine '
                       'Schicht über Mitternacht wird auf zwei Zeilen '
                       'aufgeteilt, eine je Tag.',
            })

        if self.berechnete_dauer() > MINUTEN_JE_TAG:
            raise ValidationError({
                'bis': f'{dauer_zeigen(self.berechnete_dauer())} sind mehr '
                       f'als ein Tag.',
            })

        self._pruefe_grundlage()
        self._pruefe_umfang()

        # Gilt auch für Berechtigte, weil die Zeile zu einem Dokument beim
        # Kunden gehört.
        if self.ist_gesperrt and wurde_geaendert(self):
            raise ValidationError(
                f'Dieser Eintrag steht auf {self.abgerechneter_beleg} und kann '
                f'nicht geändert werden. Zum Ändern ggf. '
                f'Position aus der Rechnung nehmen.'
            )


# ══════════════════════════════════════════════════════════════════════════
# Fremdleistung: von Dritten für Projekte erbrachte Leistung
# ══════════════════════════════════════════════════════════════════════════
#
# In dieser App, weil derselbe Ablauf folgt wie bei eigener Leistung:
# kontieren, weiterberechnen, als offen ausweisen. Ein eigenes Modell, weil
# eine Fremdleistung Lieferant, Einkaufspreis und Beleg hat und keine Person
# und Uhrzeiten.


def _positionssumme(*, menge: Decimal, einzelpreis: Decimal) -> Decimal:
    """Menge mal Preis auf Cent gerundet, dieselbe Regel wie im Beleg.

    Lokaler Import, damit das Laden dieser Modelle nicht die Services von
    faktura importiert.
    """
    from faktura.services import positionssumme
    return positionssumme(menge=menge, einzelpreis=einzelpreis)


class Eingangsrechnung(MitVersion):
    """Eingangsrechnung, die auf Projekte verteilt wird.

    Der Kopf enthält den geforderten Betrag, die Positionen verteilen ihn
    auf Projekte; der Rest bleibt sichtbar. Netto wie alle Auswertungen.
    Kein Beleg im Sinne von faktura; das Dokument liegt im Archiv
    (Paperless).
    """

    #: Kontakt mit der Rolle Lieferant. Unbekannte Lieferanten legt die
    #: Übernahme aus Archiv oder E-Rechnung als Kontakt an.
    lieferant = models.ForeignKey(
        'faktura.Kontakt',
        on_delete=models.PROTECT,
        related_name='eingangsrechnungen',
        limit_choices_to={'ist_lieferant': True},
        verbose_name='Lieferant',
    )
    nummer = models.CharField(
        'Rechnungsnummer', max_length=50,
        help_text='Die Nummer des Lieferanten, so wie sie auf seinem Beleg '
                  'steht.',
    )
    datum = models.DateField('Rechnungsdatum')
    betrag_netto = models.DecimalField(
        'Rechnungsbetrag netto', max_digits=12, decimal_places=2,
        help_text='Was der Lieferant fordert. Gegen diesen Betrag prüft das '
                  'Programm, ob alle Positionen zugeordnet sind.',
        db_comment='Der Betrag laut fremdem Beleg, die Sollgröße. Die '
                   'Summe der Positionen muss ihn treffen; die Differenz '
                   'steht als Rest am Kopf.',
    )
    notiz = models.TextField('Notiz', blank=True, default='')
    #: Dokument im Archiv, die einzige Verbindung zum PDF. Unique, damit eine
    #: wiederholte Übernahme nichts doppelt anlegt; NULL bei von Hand
    #: erfassten Rechnungen.
    paperless_id = models.PositiveIntegerField(
        'Dokument im Archiv', null=True, blank=True, unique=True,
        help_text='Die Nummer des Dokuments in Paperless. Wird beim '
                  'Übertrag aus dem Archiv gesetzt und bleibt sonst leer.',
    )
    erfasst_am = models.DateTimeField('Erfasst am', auto_now_add=True)

    class Meta:
        verbose_name = 'Eingangsrechnung'
        verbose_name_plural = 'Eingangsrechnungen'
        ordering = ['-datum', '-pk']
        constraints = [
            # Verhindert die doppelte Erfassung einer Rechnung, die per Post
            # und per Mail kam.
            models.UniqueConstraint(
                fields=['lieferant', 'nummer'],
                name='eingangsrechnung_je_lieferant_eindeutig',
            ),
        ]

    def __str__(self) -> str:
        lieferant = self.lieferant.name if self.lieferant_id else 'ohne Lieferant'
        return f'{lieferant} {self.nummer}'

    @property
    def zugeordnet(self) -> Decimal:
        """Auf Projekte verteilter Betrag, Summe der Zeilenbeträge."""
        return sum(
            (p.einkauf_netto for p in self.positionen.all()), Decimal('0.00'))

    @property
    def rest(self) -> Decimal:
        """Noch keinem Projekt zugeordneter Betrag. Negativ, wenn mehr verteilt
        als gefordert ist, meist durch einen Zahlendreher."""
        return self.betrag_netto - self.zugeordnet

    @property
    def ist_vollstaendig(self) -> bool:
        return self.rest == 0

    @property
    def projekte(self) -> list:
        """Projekte der Positionen, ohne Doppelte, nach Nummer.

        Bei einer teilweise verteilten Rechnung der wahrscheinliche Ort des
        Rests. Liest ``positionen.all()``, damit ``prefetch_related(
        'positionen__projekt')`` greift.
        """
        projekte = {p.projekt_id: p.projekt for p in self.positionen.all()}
        return sorted(projekte.values(), key=lambda projekt: projekt.nummer)

    @property
    def archiv_adresse(self) -> str:
        """URL des Dokuments in Paperless, leer ohne ID."""
        if not self.paperless_id:
            return ''
        from faktura import archiv

        return archiv.dokument_adresse(self)

    @property
    def kommt_aus_dem_archiv(self) -> bool:
        """Ob die Rechnung aus dem Archiv übernommen wurde; nur dann darf ein
        Workflow sie aktualisieren."""
        return self.paperless_id is not None


class Fremdleistung(ErhoehtElternversion):
    """Position einer Eingangsrechnung, kontiert auf ein Projekt.

    Enthält den Einkaufspreis, den der Lieferant berechnet hat, von Hand
    erfasst oder aus einer E-Rechnung. Der Preis für den Kunden (wie
    geliefert oder zum Preis der Auftragsposition) entsteht beim Übernehmen
    in die Rechnung und steht an der Rechnungsposition.

    Wie bei der Erfassungszeile ist das Projekt Pflicht und die
    Auftragsposition optional, weil die Zuordnung zu Auftrag oder Nachtrag
    beim Erfassen oft offen ist.
    """

    #: Inline-Änderungen inkrementieren die Version des Elternobjekts.
    version_eltern = ('rechnung',)

    rechnung = models.ForeignKey(
        Eingangsrechnung,
        on_delete=models.CASCADE,
        related_name='positionen',
        verbose_name='Eingangsrechnung',
    )
    projekt = models.ForeignKey(
        'faktura.Projekt',
        on_delete=models.PROTECT,
        related_name='fremdleistungen',
        verbose_name='Projekt',
        help_text='Für welches Projekt diese Position angefallen ist.',
    )
    # Optional; anders als bei der Erfassungszeile liefert die Position hier
    # nur die Zuordnung, der Preis steht auf dem Beleg des Lieferanten.
    auftragsposition = models.ForeignKey(
        'faktura.Belegposition',
        on_delete=models.PROTECT,
        null=True, blank=True,
        limit_choices_to={'beleg__typ': 'auftrag',
                          'beleg__status': 'festgeschrieben',
                          # Auf einen Titel, Text oder Zuschlag wird nicht
                          # gearbeitet.
                          'zeilenart': 'leistung'},
        related_name='fremdkontierungen',
        verbose_name='Auftragsposition',
        help_text='Freiwillig: die beauftragte Leistung, zu der dieser '
                  'Einkauf gehört. Beim Übernehmen in die Rechnung gilt '
                  'dann ihr Preis, wenn die Einheit passt.',
    )
    bezeichnung = models.CharField(
        'Bezeichnung', max_length=300,
        help_text='Wie es auf der Rechnung des Lieferanten heißt; '
                  'Paketnummer, Analysenbezeichnung, Leistung.',
    )
    einheit = models.CharField('Einheit', max_length=20, blank=True, default='Stk')
    menge = models.DecimalField(
        'Menge', max_digits=10, decimal_places=3, default=Decimal('1'),
        db_comment='Dieselben drei Nachkommastellen wie Belegposition.menge; '
                   'die Position wird eines Tages zu einer.',
    )
    leistungsdatum = models.DateField(
        'Leistungsdatum', null=True, blank=True,
        help_text='Wann der Lieferant geleistet hat, z. B. die Probenahme. '
                  'Ergibt beim Übernehmen den Leistungszeitraum der '
                  'Rechnungsposition.',
        db_comment='Geht als leistung_von/leistung_bis (BT-134/135) in die '
                   'Belegposition: kleinstes bis größtes Datum der Gruppe.',
    )
    # Vier Nachkommastellen, weil ein Meterpreis aus "0,85 € je 100 m"
    # 0,0085 € ist.
    einkaufspreis = models.DecimalField(
        'Einkaufspreis netto', max_digits=14, decimal_places=4,
        help_text='Je Einheit, so wie der Lieferant ihn berechnet.',
        db_comment='Einzelpreis laut Lieferant. Maßgeblich für die Kosten ist '
                   'einkauf_netto, nicht Menge mal Preis.',
    )
    einkauf_netto = models.DecimalField(
        'Betrag netto', max_digits=12, decimal_places=2, blank=True,
        help_text='Was der Lieferant für diese Zeile berechnet. Leer lassen '
                  '- dann Menge mal Einkaufspreis. Abweichend eintragen bei '
                  'Rabatt oder Zuschlag auf der Zeile.',
        db_comment='Der Zeilenbetrag laut Lieferant (E-Rechnung: BT-131). '
                   'Belastet das Projektergebnis, auch wenn nichts '
                   'weiterberechnet wird. Die Summe über die Eingangsrechnung '
                   'muss deren Nettobetrag treffen.',
    )
    # Wie Erfassungszeile.abrechenbar, etwa für eine Nachanalyse nach
    # eigenem Fehler, die in den Kosten bleibt.
    weiterberechenbar = models.BooleanField(
        'Weiterberechenbar', default=True,
        help_text='Ausschalten, wenn wir die Kosten selbst tragen. Sie '
                  'bleiben im Projektergebnis stehen.',
    )
    # Verweis auf die Position, wie bei der Erfassungszeile.
    abgerechnet_in = models.ForeignKey(
        'faktura.Belegposition',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='fremdleistungen',
        verbose_name='Abgerechnet in',
        help_text='Wird beim Übernehmen in eine Rechnung gesetzt. Kein '
                  'Eingabefeld.',
    )

    #: Historie wie bei der Erfassungszeile.
    history = HistoricalRecords(verbose_name='Änderung der Fremdleistung')

    class Meta:
        verbose_name = 'Fremdleistung'
        verbose_name_plural = 'Fremdleistungen'
        ordering = ['rechnung', 'pk']

    def __str__(self) -> str:
        projekt = self.projekt.nummer if self.projekt_id else 'ohne Projekt'
        return f'{self.bezeichnung} ({projekt})'

    def save(self, *args, **kwargs):
        """Berechnet den Betrag aus Menge und Preis, wenn keiner eingetragen
        ist oder Menge oder Preis ohne den Betrag geändert wurden. Sonst
        bliebe nach einer Korrektur der Menge der alte Betrag stehen. Ein
        eingetragener Betrag (Rabatt) bleibt erhalten."""
        if self.einkauf_netto is None or self._betrag_veraltet():
            self.einkauf_netto = _positionssumme(
                menge=self.menge, einzelpreis=self.einkaufspreis)
        super().save(*args, **kwargs)

    def _betrag_veraltet(self) -> bool:
        """Ob Menge oder Preis geändert sind, der Betrag aber nicht. Eine
        Abfrage, nur bei gespeicherten Zeilen."""
        if self.pk is None or self._state.adding:
            return False
        alt = (type(self)._base_manager.filter(pk=self.pk)
               .values('menge', 'einkaufspreis', 'einkauf_netto').first())
        if alt is None:
            return False
        grundlage_geaendert = (alt['menge'] != self.menge
                               or alt['einkaufspreis'] != self.einkaufspreis)
        return grundlage_geaendert and alt['einkauf_netto'] == self.einkauf_netto

    @property
    def zustand(self) -> str:
        """Dieselben drei Zustände und dieselbe Reihenfolge wie bei der
        Erfassungszeile."""
        if not self.weiterberechenbar:
            return Zustand.NICHT_ABRECHENBAR
        if self.abgerechnet_in_id:
            return Zustand.ABGERECHNET
        return Zustand.OFFEN

    @property
    def zustand_anzeige(self) -> str:
        return Zustand(self.zustand).label

    @property
    def abgerechneter_beleg(self):
        """Beleg, auf dem die Position abgerechnet ist, oder None."""
        return self.abgerechnet_in.beleg if self.abgerechnet_in_id else None

    @property
    def ist_gesperrt(self) -> bool:
        """Ob die Position auf einer Rechnung steht, Entwürfe eingeschlossen,
        wie bei der Erfassungszeile."""
        return bool(self.abgerechnet_in_id)

    def clean(self):
        super().clean()

        # Verhindert Einkauf auf dem Auftrag eines anderen Kunden, wie bei
        # der Erfassungszeile.
        if self.auftragsposition_id and self.projekt_id:
            auftrag = self.auftragsposition.beleg
            if auftrag.projekt_id != self.projekt_id:
                raise ValidationError({
                    'auftragsposition': f'{auftrag} gehört zu einem anderen '
                                        f'Projekt.',
                })

        if self.einkaufspreis is not None and self.einkaufspreis < 0:
            raise ValidationError({
                'einkaufspreis': 'Ein Einkaufspreis ist nicht negativ. Eine '
                                 'Gutschrift des Lieferanten wird als eigene '
                                 'Eingangsrechnung mit negativem Betrag '
                                 'erfasst.',
            })

        if self.ist_gesperrt and wurde_geaendert(self):
            raise ValidationError(
                f'Diese Position steht auf {self.abgerechneter_beleg} und '
                f'kann nicht geändert werden. Zum Ändern ggf. '
                f'Position aus der Rechnung nehmen.'
            )


class Kostensatz(models.Model):
    """Kosten einer Arbeitsstunde einer Person ab einem Stichtag.

    Lohn, Nebenkosten und Umlage; der Verkaufspreis steht im Katalog. Mit
    Gültigkeitsbeginn, damit die Nachkalkulation des Vorjahres nach einer
    Lohnerhöhung mit den damaligen Kosten rechnet. Ein Satz gilt bis zum
    nächsten derselben Person, deshalb ohne Enddatum.

    Personen ohne Satz verursachen keine Kosten; die Auswertung weist sie
    gesondert aus.
    """

    benutzer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='kostensaetze',
        verbose_name='Person',
    )
    gueltig_ab = models.DateField(
        'Gültig ab',
        help_text='Ab diesem Tag gilt der Satz, bis zum nächsten dieser '
                  'Person. Frühere Stunden bleiben mit dem alten Satz '
                  'gerechnet.',
    )
    satz = models.DecimalField(
        'Kostensatz je Stunde', max_digits=8, decimal_places=2,
        help_text='Netto, in Euro. Lohn samt Nebenkosten und Umlage, was '
                  'die Stunde den Betrieb kostet, nicht was der Kunde zahlt.',
        db_comment='INTERNER Satz je Stunde. Nicht mit '
                   'Katalogposition.einzelpreis verwechseln; das ist der '
                   'Verkaufspreis.',
    )
    notiz = models.TextField('Notiz', blank=True, default='')

    class Meta:
        verbose_name = 'Kostensatz'
        verbose_name_plural = 'Kostensätze'
        ordering = ['benutzer', '-gueltig_ab']
        constraints = [
            models.UniqueConstraint(
                fields=['benutzer', 'gueltig_ab'],
                name='kostensatz_je_person_und_tag_eindeutig',
            ),
        ]

    def __str__(self) -> str:
        # geld() formatiert mit Dezimalkomma ("58,00").
        return f'{geld(self.satz)} €/Std ab {self.gueltig_ab:%d.%m.%Y}'

    def clean(self):
        super().clean()
        if self.satz is not None and self.satz < 0:
            raise ValidationError({
                'satz': 'Ein Kostensatz ist nicht negativ. Eine Person, die '
                        'Geld einbringt, tut das über den Verkaufspreis.',
            })

    @staticmethod
    def verlauf() -> dict[int, list[tuple]]:
        """Alle Sätze je Person, der jüngste zuerst, in einer Abfrage für den
        ganzen Bestand."""
        verlauf: dict[int, list[tuple]] = {}
        for satz in Kostensatz.objects.order_by('benutzer', '-gueltig_ab'):
            verlauf.setdefault(satz.benutzer_id, []).append(
                (satz.gueltig_ab, satz.satz))
        return verlauf

    @staticmethod
    def satz_am(verlauf: dict[int, list[tuple]], benutzer_id: int,
                datum) -> Decimal | None:
        """Am Tag gültiger Satz; None bedeutet unbekannt."""
        for gueltig_ab, satz in verlauf.get(benutzer_id, ()):
            if gueltig_ab <= datum:
                return satz
        return None
