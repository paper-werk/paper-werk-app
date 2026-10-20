"""Belege: ein Modell für alle Belegarten, dazu Positionen und frühere
Fassungen.

Invarianten:

1. **Entwurf und festgeschriebener Beleg.** Ein Entwurf hat keine Nummer
   und ist änderbar. Das Festschreiben vergibt die Nummer und sperrt den
   Beleg. Angebot und Auftrag lassen sich wieder öffnen; sie werden wieder
   Entwurf und behalten die Nummer.
2. **Stammdaten werden kopiert.** Anschrift, Steuersatz, Preise und Texte
   stehen als Werte am Beleg, damit eine alte Rechnung die damalige
   Anschrift zeigt.

Angebot, Auftrag, Rechnung usw. sind Proxy-Modelle derselben Tabelle, für
eigene Menüpunkte und Rechte je Belegart.
"""

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from core.exceptions import FachlicherFehler
from core.optimistic_locking import ErhoehtElternversion, MitVersion

from .. import steuerfall as steuerfall_modul
from ..positionsnummer import sortierschluessel
from ..steuerfall import Steuerfall
from . import steuersatz as steuersatz_tabelle
from .stammdaten import Ansprechpartner, Kontakt, Projekt

#: Bezeichnung je Mahnstufe auf dem Beleg, im Admin und in Meldungen. Die
#: Gebühr ist an der Firma konfiguriert (``services.mahngebuehr``).
MAHNTEXT = {
    1: 'Zahlungserinnerung',
    2: 'Mahnung',
    3: 'Letzte Mahnung',
}


class BelegTyp(models.TextChoices):
    """Die Belegarten. Der gespeicherte Wert ist lesbar ('rechnung'), damit
    SQL-Abfragen verständlich bleiben.

    Die Mengen unten sind explizit aufgezählt, weil eine Ableitung wie
    "alle außer Steuerbelegen" die Mahnung falsch einordnete.
    """

    ANGEBOT = 'angebot', 'Angebot'
    #: Beleg, gegen dessen Positionen abgerechnet wird. Die
    #: Auftragsbestätigung ist seine Ausgabe als PDF.
    AUFTRAG = 'auftrag', 'Auftrag'
    LIEFERSCHEIN = 'lieferschein', 'Lieferschein'
    RECHNUNG = 'rechnung', 'Rechnung'
    STORNO = 'storno', 'Stornorechnung'
    GUTSCHRIFT = 'gutschrift', 'Rechnungskorrektur'
    MAHNUNG = 'mahnung', 'Mahnung'

    @classmethod
    def wertbelege(cls) -> set[str]:
        """Belegarten mit Preisen und Steuer: alle außer dem Lieferschein, der
        nur die Lieferung nachweist."""
        return {cls.ANGEBOT, cls.AUFTRAG, cls.RECHNUNG,
                cls.STORNO, cls.GUTSCHRIFT, cls.MAHNUNG}

    @classmethod
    def mit_optionen(cls) -> set[str]:
        """Belegarten mit optionalen Positionen. Eine Rechnung enthält nur
        erbrachte Leistungen, ein Lieferschein keine Preise."""
        return {cls.ANGEBOT, cls.AUFTRAG}

    @classmethod
    def steuerbelege(cls) -> set[str]:
        """Belegarten mit den Pflichtangaben nach § 14 UStG; nur sie verlangen
        Leistungsdatum und Empfängeranschrift."""
        return {cls.RECHNUNG, cls.STORNO, cls.GUTSCHRIFT}

    @classmethod
    def mit_zahlungsziel(cls) -> set[str]:
        """Belegarten, bei denen aus dem Zahlungsziel ein Datum wird.

        Die Steuerbelege und die Mahnung, die kein Steuerbeleg ist, aber eine
        Frist braucht.
        """
        return cls.steuerbelege() | {cls.MAHNUNG}

    @classmethod
    def entsperrbar(cls) -> set[str]:
        """Belegarten, die sich nach dem Festschreiben wieder öffnen lassen.

        Angebot und Auftrag sind Antrag und Vertrag, keine Buchungsbelege.
        Der Lieferschein bleibt gesperrt, weil das Leistungsdatum der
        Rechnung auf ihm beruht. Siehe ``services.beleg_wiedereroeffnen``.
        """
        return {cls.ANGEBOT, cls.AUFTRAG}

    @classmethod
    def mit_dokument(cls) -> set[str]:
        """Belegarten, deren PDF beim Festschreiben gespeichert wird.

        Alle außer dem Auftrag, der intern die Grundlage des Projekts ist;
        seine Auftragsbestätigung wird bei Bedarf aus dem aktuellen Stand
        erzeugt. Für den Auftrag entfallen daher PDF und Prüfsumme beim
        Festschreiben, Archiv-Upload, Prüfung durch ``belegarchiv_pruefen``
        und der Button zum Versenden.
        """
        return {cls.ANGEBOT, cls.LIEFERSCHEIN, cls.RECHNUNG, cls.STORNO,
                cls.GUTSCHRIFT, cls.MAHNUNG}


class Rechnungsart(models.TextChoices):
    """Gewöhnliche, Abschlags- oder Schlussrechnung, als Feld neben dem
    Belegtyp.

    Gleiche Felder, Nummernkreis und Pflichtangaben; rund zehn Stellen
    (Storno, Mahnung, Übernahme, E-Rechnung) filtern auf
    ``BelegTyp.RECHNUNG`` und gelten damit für alle Arten. Als Feld lässt
    sich die Art eines Entwurfs ändern. Eigene Menüpunkte entstehen über
    Proxy-Modelle, die auf Typ und Art filtern.
    """

    NORMAL = 'normal', 'Rechnung'
    ABSCHLAG = 'abschlag', 'Abschlagsrechnung'
    SCHLUSS = 'schluss', 'Schlussrechnung'
    #: Rechnet eine gesondert abgenommene Teilleistung endgültig ab.
    #: Entsteht nur aus einer Teilabnahme (``services.rechnung_aus_abnahme``),
    #: nie durch Auswahl.
    TEILSCHLUSS = 'teilschluss', 'Teilschlussrechnung'

    @classmethod
    def endgueltige(cls) -> tuple[str, ...]:
        """Arten, die Leistung endgültig abrechnen und das Kontingent des
        Auftrags verbrauchen: alle außer dem Abschlag, der eine Anzahlung
        ist. An einer Stelle definiert, damit eine neue Art überall
        berücksichtigt wird."""
        return (cls.NORMAL, cls.SCHLUSS, cls.TEILSCHLUSS)


class BelegStatus(models.TextChoices):
    ENTWURF = 'entwurf', 'Entwurf'
    FESTGESCHRIEBEN = 'festgeschrieben', 'Festgeschrieben'
    STORNIERT = 'storniert', 'Storniert'


class Leistungsart(models.TextChoices):
    """Ermittlung der Menge einer Leistung; bestimmt die Erfassungsmaske:
    zwei Uhrzeiten, eine Zahl oder immer 1."""

    ZEIT = 'zeit', 'Zeit (von/bis)'
    MENGE = 'menge', 'Menge'
    PAUSCHALE = 'pauschale', 'Pauschale'


class Zeilenart(models.TextChoices):
    """Art einer Belegzeile.

    Titel und Text haben weder Menge noch Preis und fallen damit aus jeder
    Summe, in Python wie in SQL. Der Zuschlag hat seinen berechneten Betrag
    als Einzelpreis bei Menge 1, damit Summen, SQL und E-Rechnung ihn ohne
    Sonderfall verarbeiten (``services.zuschlaege``).
    """

    LEISTUNG = 'leistung', 'Leistung'
    TITEL = 'titel', 'Titel'
    TEXT = 'text', 'Text'
    ZUSCHLAG = 'zuschlag', 'Zuschlag'

    @classmethod
    def ohne_betrag(cls) -> tuple[str, ...]:
        """Zeilen ohne Menge und Preis; ausgenommen von E-Rechnung, Absetzung
        und Kontierung."""
        return (cls.TITEL, cls.TEXT)

    @classmethod
    def felder_ohne_bedeutung(cls, art: str) -> tuple[str, ...]:
        """Felder einer Position ohne Bedeutung für diese Zeilenart.

        Einzige Definition dieser Regel: Das Formular sperrt und verbirgt
        die Felder (``BelegpositionForm.ohne_bedeutung``), gespeichert wird
        der Wert aus ``Belegposition.save()`` oder der Default. Ein Titel hat
        so keine Menge, ein Zuschlag keine eingegebene Einheit in der
        E-Rechnung.
        """
        zuschlag = ('zuschlag_prozent', 'zuschlag_auf')
        if art in cls.ohne_betrag():
            return ('menge', 'einheit', 'einzelpreis', 'steuersatz',
                    'optional', 'leistung_von', 'leistung_bis', *zuschlag)
        if art == cls.ZUSCHLAG:
            # Menge 1 und der berechnete Betrag als Preis
            # (services.zuschlaege); der Steuersatz gilt für den Zuschlag.
            # Optional zulässig, etwa "Samstag 50 %" im Angebot.
            return ('menge', 'einheit', 'einzelpreis')
        return zuschlag


class Beleg(MitVersion):
    HELP_TEXT_P_K = 'Verknüpfung zu Projekt/Kunde.'

    typ = models.CharField('Belegart', max_length=20, choices=BelegTyp)

    #: Nur bei Rechnungen gefüllt, dort immer (``save()`` setzt 'normal').
    rechnungsart = models.CharField(
        'Art der Rechnung', max_length=20, choices=Rechnungsart,
        blank=True, default='',
        help_text='Abschlag, Schlussrechnung oder gewöhnliche Rechnung. '
                  'Solange die Rechnung Entwurf ist, änderbar.',
        db_comment='Nur bei typ=rechnung gefüllt. Kein eigener Belegtyp: '
                   'gleiche Felder, gleicher Nummernkreis, gleiche '
                   'Pflichtangaben, und umwidmen bleibt möglich.',
    )
    status = models.CharField(
        'Status', max_length=20, choices=BelegStatus, default=BelegStatus.ENTWURF
    )

    # Erst beim Festschreiben gesetzt, weil ein verworfener Entwurf mit
    # Nummer eine Lücke im Nummernkreis hinterließe.
    nummer = models.CharField(
        'Belegnummer', max_length=30, unique=True, null=True, blank=True
    )

    # Kunde oder Projekt oder keins von beiden (Anschrift von Hand), nie
    # beides; erzwungen in clean() und als Constraint.
    kunde = models.ForeignKey(
        Kontakt,
        on_delete=models.PROTECT,
        related_name='belege',
        limit_choices_to={'ist_kunde': True},
        verbose_name='Kunde',
        null=True, blank=True,
        help_text= HELP_TEXT_P_K,
    )
    projekt = models.ForeignKey(
        Projekt,
        on_delete=models.PROTECT,
        related_name='belege',
        verbose_name='Projekt',
        null=True, blank=True,
        help_text=HELP_TEXT_P_K,
    )
    #: Ansprechpartner beim Kunden, nur für die Navigation; auf dem Beleg
    #: steht "z. Hd." als Text. SET_NULL, damit eine Löschung nach DSGVO
    #: nicht an alten Belegen scheitert.
    ansprechpartner = models.ForeignKey(
        Ansprechpartner,
        on_delete=models.SET_NULL,
        related_name='belege',
        verbose_name='Ansprechpartner',
        null=True, blank=True,
        help_text='Wer beim Kunden gemeint ist. Wird beim Anlegen '
                  'vorbelegt; auf dem Beleg erscheint die Zeile "z. Hd." '
                  'im Empfängerfeld.',
    )

    # --- Kopierte Stammdaten, unabhängig von späteren Änderungen ---

    # Freies Textfeld, weil das Anschriftfeld eines Briefs keine feste Form
    # hat (Postfach, "z. Hd.", Auslandsformate). Zeilengetreu im PDF.
    empfaenger = models.TextField(
        'Empfänger', blank=True, default='',
        help_text='Erscheint zeilengetreu im Anschriftfeld des Belegs. '
                  'Wird beim Auswählen des Kunden gefüllt, wenn es leer ist.',
    )

    # Strukturierte Felder nur für die E-Rechnung (EN 16931, BT-44 ff.),
    # redundant zum freien Empfängerfeld; nicht im PDF.
    empfaenger_name = models.CharField(
        'Name (E-Rechnung)', max_length=200, blank=True, default='')
    empfaenger_strasse = models.CharField(
        'Straße (E-Rechnung)', max_length=200, blank=True, default='')
    empfaenger_plz = models.CharField(
        'PLZ (E-Rechnung)', max_length=10, blank=True, default='')
    empfaenger_ort = models.CharField(
        'Ort (E-Rechnung)', max_length=100, blank=True, default='')
    empfaenger_land = models.CharField('Land', max_length=2, default='DE')
    #: Vorgesehene Empfängeradresse; die tatsächliche steht in
    #: ``versendet_an``.
    empfaenger_email = models.EmailField(
        'E-Mail des Empfängers', blank=True, default='')
    empfaenger_ust_id = models.CharField('USt-IdNr.', max_length=20, blank=True, default='')
    zahlungsziel_tage = models.PositiveSmallIntegerField('Zahlungsziel (Tage)', default=14)

    # --- Pflichtangaben nach § 14 UStG ---
    belegdatum = models.DateField('Belegdatum', null=True, blank=True)
    # Ein Feldpaar mit je nach Belegart anderer Bedeutung und Beschriftung
    # (``BelegAdmin.LEISTUNGSFELDER``, Druckvorlage):
    #
    #   Rechnung, Storno, Korrektur  Leistungsdatum, Pflicht nach
    #                                § 14 Abs. 4 Nr. 6 UStG
    #   Lieferschein                 Lieferdatum
    #   Angebot, Auftrag             geplanter Ausführungszeitraum
    #   Mahnung                      ohne Bedeutung, ausgeblendet
    #
    # Ein Feld, damit der Termin beim Umwandeln vom Angebot in die Rechnung
    # übernommen wird.
    leistungsdatum = models.DateField(
        'Leistung von',
        null=True,
        blank=True,
        help_text='Zeitpunkt oder Beginn des Zeitraums, in dem geleistet '
                  'wird. Was er im einzelnen Beleg bedeutet, steht an der '
                  'jeweiligen Belegart.',
    )
    leistungsdatum_bis = models.DateField('Leistung bis', null=True, blank=True)
    #: BT-72 bei Rechnung, Storno und Korrektur. Eigenes Feld, damit keine
    #: steuerliche Angabe nur aus dem Zeitraum abgeleitet wird; vorbelegt in
    #: ``save()``. Der Abschlag hat keines.
    steuerliches_leistungsdatum = models.DateField(
        'Leistungsdatum', null=True, blank=True,
        help_text='Der Tag, an dem die Leistung vollendet bzw. abgenommen '
                  'ist, die Pflichtangabe nach § 14 Abs. 4 Nr. 6 UStG. '
                  'Leer gelassen, gilt das Ende des Zeitraums. Ein Abschlag '
                  'hat keines.',
        db_comment='BT-72. Bei Abschlägen immer leer (Anzahlung).',
    )

    # Herkunft des Belegs, etwa Angebot, Auftrag, Rechnung, Storno.
    vorgaenger = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='nachfolger',
        verbose_name='Vorgängerbeleg',
    )

    # Ein Nachtrag ist ein Auftrag mit Verweis auf den Hauptauftrag. Die
    # Hierarchie ist flach: Ein Nachtrag verweist immer auf den
    # Hauptauftrag, damit die Summe des Beauftragten nicht von der Tiefe
    # einer Kette abhängt. Zu unterscheiden von ``vorgaenger`` (Herkunft).
    #: Nur bei Schluss- und Teilschlussrechnung: die zugrunde liegende
    #: Abnahme, Quelle von Leistungsdatum und Zeitraum.
    abnahme = models.ForeignKey(
        'faktura.Abnahme',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='rechnungen',
        verbose_name='Abnahme',
    )
    nachtrag_zu = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True, blank=True,
        limit_choices_to={'typ': 'auftrag'},
        related_name='nachtraege',
        verbose_name='Nachtrag zu',
        help_text='Nur bei Aufträgen: der Hauptauftrag, zu dem '
                  'dieser Nachtrag gehört. Leer lassen beim Hauptauftrag '
                  'selbst.',
        db_comment='Die Klammer um einen Auftrag samt seiner Nachträge. '
                   'Flach: zeigt immer auf den Hauptauftrag, nie auf einen '
                   'anderen Nachtrag. Nicht zu verwechseln mit vorgaenger '
                   '(woraus ein Beleg entstanden ist).',
    )

    betreff = models.CharField('Betreff', max_length=200, blank=True, default='')
    kopftext = models.TextField('Text über den Positionen', blank=True, default='')
    fusstext = models.TextField('Text unter den Positionen', blank=True, default='')

    # --- Nur bei Mahnungen gefüllt ---
    mahnstufe = models.PositiveSmallIntegerField(
        'Mahnstufe', null=True, blank=True,
        choices=list(MAHNTEXT.items()),
    )
    faellig_am = models.DateField(
        'Zahlbar bis', null=True, blank=True,
        help_text='Wird bei der Festschreibung aus dem Zahlungsziel berechnet.',
    )

    # --- E-Rechnung ---
    #: Aus dem Kunden vorbelegt, am Beleg maßgeblich, weil derselbe Kunde
    #: eine Beratung (Reverse Charge) und eine Warenlieferung erhalten kann.
    steuerfall = models.CharField(
        'Steuerfall', max_length=30, choices=Steuerfall, blank=True,
        default=Steuerfall.REGULAER,
        help_text='Außer beim Regelfall: alle Positionen mit 0 %, dazu der '
                  'gesetzliche Vermerk auf dem Beleg und in der E-Rechnung.',
    )
    # BT-10 "Buyer reference". Der Feldname ist enger als der Inhalt, weil
    # die Leitweg-ID nur die Form für Behörden ist; er bleibt, weil die API
    # (/api/v1/belege/) ihn verwendet.
    leitweg_id = models.CharField(
        'Käuferreferenz', max_length=50, blank=True, default='',
        help_text='BT-10 der E-Rechnung. Bei öffentlichen Auftraggebern die '
                  'Leitweg-ID, sonst die Referenz des Kunden. Wird aus den '
                  'Kundenstammdaten vorbelegt.',
    )
    # Abgekürzt, damit die Beschriftung samt "(BT-13)" in der Maske nicht
    # umbricht.
    bestellnummer = models.CharField(
        'Bestellnr. des Kunden', max_length=50, blank=True, default=''
    )

    # --- Gespeichertes Dokument ---
    # Beim Festschreiben einmal erzeugt, danach nur ausgeliefert, damit eine
    # Änderung am Template alte Rechnungen nicht ändert.
    pdf = models.FileField('PDF', upload_to='belege/%Y/%m/', blank=True, null=True)
    pdf_sha256 = models.CharField(
        'Prüfsumme', max_length=64, blank=True, default='',
        help_text='SHA-256 des PDF. Weist nach, dass die Datei seit der '
                  'Festschreibung unverändert ist.',
    )
    # Dieselben Bytes wie im PDF. Beim Versand nur als XML (Rechnungsportal)
    # ist es das Original und bleibt unverändert; archiviert wird das PDF.
    # Leer bei Belegarten ohne E-Rechnung.
    xml = models.FileField('XML', upload_to='belege/%Y/%m/', blank=True,
                           null=True)
    xml_sha256 = models.CharField(
        'Prüfsumme XML', max_length=64, blank=True, default='',
        help_text='SHA-256 des XML. Weist nach, dass die E-Rechnung seit der '
                  'Festschreibung unverändert ist.',
    )
    # Mit dem XML gespeichert, weil es aus dem änderbaren Zustellweg des
    # Kunden folgt.
    erechnungsprofil = models.CharField(
        'E-Rechnungsprofil', max_length=20, blank=True, default='',
        help_text='"EN 16931" oder "XRECHNUNG": wie das XML beim '
                  'Festschreiben entstanden ist.',
    )
    vorlagenversion = models.CharField(
        'Vorlagenversion', max_length=20, blank=True, default='',
        help_text='Mit welcher Fassung der Druckvorlage der Beleg erzeugt '
                  'wurde. Ohne diese Angabe lässt sich später nicht mehr '
                  'nachvollziehen, warum ein Beleg anders aussieht.',
    )

    # --- Archiv (Paperless) ---
    # Rückverweis zum Belegverweis in Paperless; zeigt ohne Abfrage im
    # Archiv, ob der Beleg archiviert ist.
    paperless_id = models.PositiveIntegerField(
        'Dokument-ID im Archiv', null=True, blank=True, unique=True,
        help_text='Nummer des Dokuments in Paperless. Wird vom '
                  'Archivierungslauf gesetzt, nicht von Hand.',
    )
    archiviert_am = models.DateTimeField('Archiviert am', null=True, blank=True)
    # Task-ID eines Uploads, dessen Dokumentnummer aussteht. Paperless
    # verhindert keine Duplikate; solange ein Task offen ist, wird sein
    # Status abgefragt und nicht erneut hochgeladen.
    paperless_task_id = models.CharField(
        'Aufgabennummer im Archiv', max_length=64, blank=True, default='',
        help_text='Quittung für einen laufenden Upload. Wird geleert, sobald '
                  'die Dokument-ID feststeht.',
    )

    erstellt_am = models.DateTimeField('Angelegt am', auto_now_add=True)
    #: Zeitpunkt und Adresse des ersten Versands. Ein erneuter Versand
    #: überschreibt ihn nicht, weil er als Nachweis dient; weitere Versände
    #: stehen im Verlauf (LogEntry). Leer bedeutet: nie per E-Mail
    #: versendet; Post oder Portal werden nicht erfasst.
    versendet_am = models.DateTimeField('Erstmals versendet am', null=True,
                                        blank=True)
    versendet_an = models.EmailField('Erstmals versendet an', blank=True,
                                     default='')
    festgeschrieben_am = models.DateTimeField('Festgeschrieben am', null=True, blank=True)

    # Benutzer der Festschreibung. PROTECT, weil ein Konto mit Belegen
    # deaktiviert wird und der Nachweis erhalten bleiben muss. Leer bei
    # Festschreibungen aus Shell, Import oder Seed.
    festgeschrieben_von = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name='+',
        verbose_name='Festgeschrieben von',
    )

    # Gesetzt, wenn ein festgeschriebener Beleg wieder Entwurf wurde, und
    # dauerhaft gespeichert, weil die GoBD verlangen, dass Änderungen
    # erkennbar bleiben.
    geaendert_am = models.DateTimeField(
        'Wiedereröffnet am', null=True, blank=True,
        help_text='Gesetzt, sobald ein festgeschriebener Beleg wieder zum '
                  'Entwurf gemacht wurde. Leer heißt: seit der '
                  'Festschreibung unverändert.',
    )
    geaendert_von = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name='+',
        verbose_name='Wiedereröffnet von',
    )

    class Meta:
        verbose_name = 'Beleg'
        verbose_name_plural = 'Belege'
        ordering = ['-erstellt_am']
        permissions = [
            # Für den Archivierungslauf: Archivfelder setzen ohne
            # ``change_beleg``.
            ('archivieren_beleg', 'Kann den Archivvermerk setzen'),
            # Startseite und Controlling. Eigenes Recht, damit Rechnungen
            # ohne Marge und Kostensätze sichtbar sein können.
            ('controlling_ansehen', 'Kann die Auswertungen sehen'),
            # Getrennt von ``change_beleg``, weil das Wiedereröffnen
            # versendeter Belege eigens erlaubt sein soll.
            ('beleg_wiedereroeffnen', 'Kann Belege wieder öffnen'),
        ]
        constraints = [
            # In der Datenbank, damit auch Skripte und Importe gebunden
            # sind. Ohne Nummer keine Festschreibung ...
            models.CheckConstraint(
                condition=models.Q(status='entwurf')
                | models.Q(nummer__isnull=False),
                name='nummer_ab_der_festschreibung',
            ),
            # ... und ein Entwurf mit Nummer nur nach Wiedereröffnung, damit
            # kein Skript eine Nummer außerhalb des Nummernkreises setzt.
            models.CheckConstraint(
                condition=~models.Q(status='entwurf')
                | models.Q(nummer__isnull=True)
                | models.Q(geaendert_am__isnull=False),
                name='entwurf_mit_nummer_nur_wiedereroeffnet',
            ),
            models.CheckConstraint(
                condition=models.Q(kunde__isnull=True)
                | models.Q(projekt__isnull=True),
                name='kunde_oder_projekt_nicht_beides',
            ),
        ]

    def __str__(self) -> str:
        bezeichnung = self.get_typ_display()
        if self.nummer:
            return f'{bezeichnung} {self.nummer}'
        return f'{bezeichnung} (Entwurf {self.pk})'

    def save(self, *args, **kwargs):
        """Verhindert Änderungen an festgeschriebenen Belegen.

        Änderungen laufen über die Services; diese Prüfung greift bei
        Admin, Shell und Importen. Einzige zulässige Änderung ist der Wechsel
        nach STORNIERT. Wiedereröffnen sowie Archiv- und Versandfelder
        verwenden ``queryset.update()`` und umgehen ``save()``, damit die
        Sperre keine Ausnahmen braucht.

        Die Nummer ist auch am wiedereröffneten Beleg geschützt, weil sie dem
        Kunden vorliegt. Eine Rechnung ohne Art erhält 'normal', damit sie in
        den Rechnungslisten erscheint.
        """
        if self.typ == BelegTyp.RECHNUNG and not self.rechnungsart:
            self.rechnungsart = Rechnungsart.NORMAL

        # Ein Abschlag hat nie ein Leistungsdatum, auch nach Änderung der Art
        # einer Rechnung, damit er nicht als Teilleistung gilt.
        vorher = self.steuerliches_leistungsdatum
        if self.rechnungsart == Rechnungsart.ABSCHLAG:
            self.steuerliches_leistungsdatum = None
        else:
            self._leistungsdatum_vorbelegen()
        # Mit ``update_fields`` gelangte die Vorbelegung sonst nur in die
        # Instanz und nicht in die Datenbank.
        felder = kwargs.get('update_fields')
        if (felder is not None
                and self.steuerliches_leistungsdatum != vorher):
            kwargs['update_fields'] = {*felder, 'steuerliches_leistungsdatum'}

        if self.pk:
            alt = (
                Beleg.objects.filter(pk=self.pk)
                .values('status', 'nummer')
                .first()
            )
            if alt and alt['status'] != BelegStatus.ENTWURF:
                erlaubt = (
                    alt['status'] == BelegStatus.FESTGESCHRIEBEN
                    and self.status == BelegStatus.STORNIERT
                )
                if not erlaubt:
                    raise BelegNichtAenderbar(
                        f'{self} ist festgeschrieben und kann nicht mehr '
                        f'geändert werden.'
                    )
            if alt and alt['nummer'] and self.nummer != alt['nummer']:
                raise BelegNichtAenderbar(
                    f'Die Belegnummer {alt["nummer"]} ist vergeben und bleibt '
                    f'stehen. Auch ein wiedereröffneter Beleg behält sie; '
                    f'sie ist außer Haus.'
                )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Löscht nur Belege, die nie eine Nummer hatten.

        Geprüft wird die Nummer, weil die Lückenlosigkeit des Nummernkreises
        geschützt ist, unabhängig davon, wie ein Entwurf zu einer Nummer
        kam.
        """
        if not self.ist_entwurf:
            raise BelegNichtAenderbar(
                f'{self} ist festgeschrieben und darf nicht gelöscht werden. '
                f'Für eine Korrektur wird storniert.'
            )
        if self.nummer:
            raise BelegNichtAenderbar(
                f'{self} trägt die Nummer {self.nummer}; sie ist vergeben '
                f'und außer Haus. Ein wiedereröffneter Beleg lässt sich '
                f'nicht löschen; er wird wieder festgeschrieben oder '
                f'storniert.'
            )
        return super().delete(*args, **kwargs)

    def clean(self):
        """Validierung über mehrere Felder.

        Kunde oder Projekt, höchstens eins davon; der Constraint liefert einen
        Datenbankfehler, hier steht der Fehler am Feld. Ein
        Leistungszeitraum endet nicht vor seinem Beginn. Dazu Nachtrag und
        Rechnungsart.
        """
        super().clean()

        if self.kunde_id and self.projekt_id:
            raise ValidationError({
                'projekt': 'Entweder ein Kunde oder ein Projekt; nicht '
                           'beides. Das Projekt bringt seinen Kunden schon '
                           'mit; wer den Kunden direkt zuordnen will, lässt '
                           'das Projekt leer.',
            })

        if (self.leistungsdatum and self.leistungsdatum_bis
                and self.leistungsdatum_bis < self.leistungsdatum):
            raise ValidationError({
                'leistungsdatum_bis': 'Das Ende des Zeitraums liegt vor '
                                      'seinem Beginn.',
            })

        self._pruefe_nachtrag()
        self._pruefe_rechnungsart()

    def _pruefe_rechnungsart(self) -> None:
        """Nur eine Rechnung hat eine Rechnungsart; prüft den Fall, dass der
        Wert beim Umwandeln mitkopiert wurde."""
        if self.typ != BelegTyp.RECHNUNG and self.rechnungsart:
            raise ValidationError({
                'rechnungsart': f'{self.get_typ_display()} kennt keine Rechnungsart.',
            })
        self._pruefe_abnahme()

    def _pruefe_abnahme(self) -> None:
        """Teilschlussrechnung nur mit Teilabnahme und umgekehrt, damit keine
        versehentlich entsteht. Die Gesamtabnahme gehört zur
        Schlussrechnung."""
        from .abnahme import Abnahmeart
        if self.rechnungsart == Rechnungsart.TEILSCHLUSS and not (
                self.abnahme_id and self.abnahme.art == Abnahmeart.TEIL):
            raise ValidationError(
                'Eine Teilschlussrechnung entsteht nur aus einer '
                'Teilabnahme; in der Auftragsakte unter "Abnahmen".')
        if self.abnahme_id:
            passend = (Rechnungsart.TEILSCHLUSS
                       if self.abnahme.art == Abnahmeart.TEIL
                       else Rechnungsart.SCHLUSS)
            if self.rechnungsart != passend:
                raise ValidationError(
                    f'Zu einer {self.abnahme.get_art_display()} gehört eine '
                    f'{passend.label}.')

    def _pruefe_nachtrag(self) -> None:
        """Regeln für die Verknüpfung von Auftrag und Nachtrag.

        In Python, weil sie einen zweiten Datensatz lesen und daher kein
        Constraint sein können.
        """
        if not self.nachtrag_zu_id:
            return

        if self.typ != BelegTyp.AUFTRAG:
            raise ValidationError({
                'nachtrag_zu': 'Nur ein Auftrag kann ein Nachtrag sein. Was '
                               'aus einem Beleg entstanden ist, steht im '
                               'Feld "Vorgängerbeleg".',
            })

        if self.pk and self.nachtrag_zu_id == self.pk:
            raise ValidationError({
                'nachtrag_zu': 'Ein Auftrag ist kein Nachtrag zu sich selbst.',
            })

        haupt = self.nachtrag_zu
        if haupt.typ != BelegTyp.AUFTRAG:
            raise ValidationError({
                'nachtrag_zu': f'{haupt} ist kein Auftrag.',
            })

        if haupt.nachtrag_zu_id:
            raise ValidationError({
                'nachtrag_zu': f'{haupt} ist selbst ein Nachtrag. Nachträge '
                               f'zeigen alle auf denselben Hauptauftrag.',
            })

        if self.projekt_id != haupt.projekt_id:
            raise ValidationError({
                'nachtrag_zu': 'Hauptauftrag und Nachtrag gehören zu '
                               'verschiedenen Projekten.',
            })

    @property
    def empfaenger_kurz(self) -> str:
        """Erste Zeile des Empfängers für Listen und Meldungen."""
        return self.empfaenger.splitlines()[0] if self.empfaenger else ''

    @property
    def ist_nachtrag(self) -> bool:
        return bool(self.nachtrag_zu_id)

    @property
    def nachtragsnummer(self) -> int | None:
        """Laufende Nummer des Nachtrags zum Hauptauftrag (1, 2, 3).

        Berechnet, damit Löschen oder Umdatieren keine inkonsistenten Werte
        hinterlässt. Reihenfolge nach Belegdatum, dann nach Anlage.
        """
        if not self.nachtrag_zu_id:
            return None
        geschwister = list(
            Beleg.objects
            .filter(nachtrag_zu_id=self.nachtrag_zu_id)
            .order_by('belegdatum', 'pk')
            .values_list('pk', flat=True)
        )
        return geschwister.index(self.pk) + 1 if self.pk in geschwister else None

    @property
    def auftragsbezeichnung(self) -> str:
        """"Hauptauftrag" oder "1. Nachtrag"."""
        if not self.ist_nachtrag:
            return 'Hauptauftrag'
        nummer = self.nachtragsnummer
        return f'{nummer}. Nachtrag' if nummer else 'Nachtrag'

    @property
    def abschlagsnummer(self) -> int | None:
        """Laufende Nummer des Abschlags im Projekt (1, 2, 3).

        Je Projekt, weil eine Rechnung Positionen mehrerer Aufträge enthalten
        kann. Berechnet wie ``nachtragsnummer``; Entwürfe zählen mit, nach
        dem Löschen eines Entwurfs rücken die folgenden auf.
        """
        if self.rechnungsart != Rechnungsart.ABSCHLAG or not self.projekt_id:
            return None
        geschwister = list(
            Beleg.objects
            .filter(projekt_id=self.projekt_id,
                    rechnungsart=Rechnungsart.ABSCHLAG)
            .order_by('belegdatum', 'pk')
            .values_list('pk', flat=True)
        )
        return geschwister.index(self.pk) + 1 if self.pk in geschwister else None

    @property
    def rechnungsbezeichnung(self) -> str:
        """Überschrift einer Rechnung, etwa "2. Abschlagsrechnung".

        Leer für andere Belegarten. Ohne Projekt nur "Abschlagsrechnung".
        """
        if not self.rechnungsart:
            return ''
        if self.rechnungsart != Rechnungsart.ABSCHLAG:
            return Rechnungsart(self.rechnungsart).label
        nummer = self.abschlagsnummer
        return f'{nummer}. Abschlagsrechnung' if nummer else 'Abschlagsrechnung'

    # --- Leistungsdaten ---
    #
    # Drei Angaben der E-Rechnung, drei Felder:
    #
    #   BT-72     steuerliches_leistungsdatum   Vollendung bzw. Abnahme;
    #                                           beim Abschlag keines, weil er
    #                                           eine Anzahlung auf eine
    #                                           unvollendete Leistung ist (§ 13
    #                                           Abs. 1 Nr. 1a Satz 4 UStG)
    #   BT-73/74  leistungsdatum, _bis          Zeitraum; beim Abschlag
    #                                           Pflicht als Angabe des
    #                                           Leistungsstands

    @property
    def ist_anzahlung(self) -> bool:
        """Ob der Beleg eine Anzahlung abrechnet: der Abschlag sowie sein
        Storno und seine Korrektur, die selbst keine Rechnungsart haben; maßgeblich
        ist der Vorgänger."""
        if self.rechnungsart == Rechnungsart.ABSCHLAG:
            return True
        return (self.typ in (BelegTyp.STORNO, BelegTyp.GUTSCHRIFT)
                and self.vorgaenger_id is not None
                and self.vorgaenger.rechnungsart == Rechnungsart.ABSCHLAG)

    @property
    def leistungszeitraum(self) -> tuple[date, date] | None:
        """Beginn und Ende (BT-73/74), None bei einem einzelnen Tag. Bei der
        Anzahlung immer gesetzt, weil der Zeitraum ohne Leistungsdatum ihre
        einzige Angabe ist."""
        if (self.leistungsdatum and self.leistungsdatum_bis
                and (self.leistungsdatum_bis != self.leistungsdatum
                     or self.ist_anzahlung)):
            return self.leistungsdatum, self.leistungsdatum_bis
        return None

    def _leistungsdatum_vorbelegen(self) -> None:
        """Setzt BT-72, solange es leer ist, auf das Ende des Zeitraums bzw.
        den einzelnen Tag; gespeichert und in der Maske sichtbar. Ein
        eingetragener Wert wird nie überschrieben.

        Bei jedem Speichern, weil die Rechnung oft vor dem Zeitraum entsteht
        (aus der Erfassung, aus dem Angebot). Das Storno eines Abschlags
        erhält keines (``ist_anzahlung``)."""
        if (self.steuerliches_leistungsdatum
                or self.typ not in BelegTyp.steuerbelege()
                or self.ist_anzahlung):
            return
        self.steuerliches_leistungsdatum = (self.leistungsdatum_bis
                                            or self.leistungsdatum)

    @property
    def vorlagenname(self) -> str:
        """Name des Templates für das PDF.

        Der Typ, außer bei Abschlags- und Schlussrechnung, die eigene
        Templates mit Überschrift und Abzugsblock haben.
        """
        if self.typ == BelegTyp.RECHNUNG and self.rechnungsart in (
                Rechnungsart.ABSCHLAG, Rechnungsart.SCHLUSS):
            return str(self.rechnungsart)
        # Gemeinsames Template: volle Leistung, darunter die abgesetzten
        # Abschläge. Die Überschrift kommt aus ``rechnungsbezeichnung``.
        if self.rechnungsart == Rechnungsart.TEILSCHLUSS:
            return str(Rechnungsart.SCHLUSS)
        return str(self.typ)

    @property
    def steuervermerk(self) -> str:
        """Pflichtvermerk des Steuerfalls für das PDF, leer im Regelfall."""
        return steuerfall_modul.vermerk(self.steuerfall)

    @property
    def ist_wertbeleg(self) -> bool:
        """Ob Preise und Steuer zu diesem Beleg gehören."""
        return self.typ in BelegTyp.wertbelege()

    @property
    def mahntext(self) -> str:
        """Bezeichnung der Mahnstufe ("Zahlungserinnerung", "Mahnung", "Letzte
        Mahnung"); leer bei anderen Belegarten, "Mahnung" bei unbekannter
        Stufe."""
        if self.typ != BelegTyp.MAHNUNG:
            return ''
        return MAHNTEXT.get(self.mahnstufe, 'Mahnung')

    @property
    def zahlbar_bis(self) -> date | None:
        """Frist: am festgeschriebenen Beleg ``faellig_am``, am Entwurf nach
        derselben Regel wie ``beleg_festschreiben`` berechnet (Belegdatum,
        sonst heute, plus Zahlungsziel).

        Gebraucht für die Mahnung, deren Text auf "das unten genannte Datum"
        verweist, auch im Entwurf.
        """
        if self.faellig_am:
            return self.faellig_am
        if self.typ not in BelegTyp.mit_zahlungsziel():
            return None
        from datetime import timedelta

        from django.utils import timezone
        start = self.belegdatum or timezone.localdate()
        return start + timedelta(days=self.zahlungsziel_tage or 0)

    @property
    def ist_entwurf(self) -> bool:
        return self.status == BelegStatus.ENTWURF

    @property
    def ist_aenderbar(self) -> bool:
        """Nur ein Entwurf ist änderbar. Ein wiedereröffneter Beleg ist ein
        Entwurf; einen dritten Zustand gibt es nicht."""
        return self.ist_entwurf

    @property
    def ist_geaendert(self) -> bool:
        """Ob der Beleg nach einer Festschreibung wieder geöffnet wurde."""
        return self.geaendert_am is not None

    # -- Zahlungsstand: berechnet, nie gespeichert --------------------------
    #
    # Ein gespeicherter offener Betrag wäre nach jeder Änderung einer
    # Zuordnung inkonsistent, und jeder Zahlungseingang schriebe in einen
    # gesperrten Beleg.

    @property
    def bezahlt(self) -> Decimal:
        """Eingegangene Zahlungen ohne Skonto."""
        return sum((z.betrag for z in self.zahlungszuordnungen.all()),
                   Decimal('0.00'))

    @property
    def ausgeglichen(self) -> Decimal:
        """Ausgeglichener Teil der Forderung: Zahlungen plus gewährter Skonto."""
        return sum((z.ausgleich for z in self.zahlungszuordnungen.all()),
                   Decimal('0.00'))

    @property
    def offener_betrag(self) -> Decimal:
        """Offener Betrag. Eine Abfrage je Aufruf; für Listen
        ``services.offene_posten()`` verwenden."""
        from .. import services

        return services.offener_betrag(self)

    @property
    def ist_bezahlt(self) -> bool:
        """Ob nichts mehr offen ist. ``False`` für alles außer festgeschriebenen
        Rechnungen."""
        if self.typ != BelegTyp.RECHNUNG or self.status != BelegStatus.FESTGESCHRIEBEN:
            return False
        return self.offener_betrag <= 0


class Belegfassung(models.Model):
    """Ersetzte Fassung von PDF und XML.

    Entsteht, wenn die E-Rechnung mit derselben Nummer neu ausgestellt wird
    (``services.erechnung_neu_ausstellen``), etwa weil ein Portal sie wegen
    der Leitweg-ID ablehnt. Beträge und Positionen bleiben gesperrt; die alte
    Fassung bleibt als Nachweis. Die Zulässigkeit derselben Nummer gehört in
    die Verfahrensdokumentation des Betriebs.
    """

    beleg = models.ForeignKey(
        'Beleg', on_delete=models.PROTECT, related_name='fassungen',
        verbose_name='Beleg',
    )
    pdf = models.FileField('PDF', upload_to='belege/%Y/%m/', blank=True,
                           null=True)
    pdf_sha256 = models.CharField('Prüfsumme PDF', max_length=64, blank=True,
                                  default='')
    xml = models.FileField('XML', upload_to='belege/%Y/%m/', blank=True,
                           null=True)
    xml_sha256 = models.CharField('Prüfsumme XML', max_length=64, blank=True,
                                  default='')
    erechnungsprofil = models.CharField('E-Rechnungsprofil', max_length=20,
                                        blank=True, default='')
    vorlagenversion = models.CharField('Vorlagenversion', max_length=20,
                                       blank=True, default='')
    #: Kopfangaben dieser Fassung, die bei der Neuausstellung änderbar sind.
    leitweg_id = models.CharField('Käuferreferenz', max_length=50,
                                  blank=True, default='')
    bestellnummer = models.CharField('Bestellnummer des Kunden',
                                     max_length=50, blank=True, default='')
    #: Anders als am Beleg nicht unique, weil mehrere Fassungen auf
    #: dieselbe ID verweisen können.
    paperless_id = models.PositiveIntegerField(
        'Dokument-ID im Archiv', null=True, blank=True)
    abgeloest_am = models.DateTimeField('Abgelöst am', auto_now_add=True)
    abgeloest_von = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True,
        blank=True, related_name='+', verbose_name='Abgelöst von',
    )
    grund = models.TextField('Grund der Neuausstellung')

    class Meta:
        verbose_name = 'Frühere Fassung'
        verbose_name_plural = 'Frühere Fassungen'
        ordering = ['beleg', 'abgeloest_am']

    def __str__(self) -> str:
        return f'{self.beleg} - Fassung bis {self.abgeloest_am:%d.%m.%Y %H:%M}'


class Belegposition(ErhoehtElternversion):
    """Zeile eines Belegs. Bezeichnung, Langtext, Preis, Einheit,
    Steuersatz und Art sind Kopien aus dem Katalog."""

    #: Inline-Änderungen inkrementieren die Version des Elternobjekts.
    version_eltern = ('beleg',)

    beleg = models.ForeignKey(
        Beleg, on_delete=models.CASCADE, related_name='positionen', verbose_name='Beleg'
    )
    #: Text, damit auch Ordnungszahlen aus dem Leistungsverzeichnis wie
    #: "01.01.0010" möglich sind. Sortiert wird nach ``sortierung``.
    position = models.CharField('Pos.', max_length=30, default='10')
    #: Aus ``position`` gebildet (``faktura.positionsnummer``), damit "9"
    #: vor "10" steht. Gesetzt in ``save()``; bei ``bulk_create`` vom
    #: Aufrufer zu setzen.
    sortierung = models.CharField(max_length=120, editable=False,
                                  default='', db_index=True)

    bezeichnung = models.CharField('Bezeichnung', max_length=300)
    langtext = models.TextField(
        'Langtext', blank=True, default='',
        help_text='Ausführliche Beschreibung unter der Bezeichnung. Kommt '
                  'aus dem Katalog und ist hier frei änderbar.',
    )
    #: Mindestens 0,001, an einer optionalen Position auch 0 (``clean``).
    menge = models.DecimalField(
        'Menge', max_digits=10, decimal_places=3, default=Decimal('1.000'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    einheit = models.CharField('Einheit', max_length=20, blank=True, default='Stk')
    einzelpreis = models.DecimalField('Einzelpreis netto', max_digits=12, decimal_places=2)
    #: Wertkopie aus der Tabelle ``Steuersatz`` (``models/steuersatz.py``).
    #: Ohne ``choices``, weil Djangos System-Check Callable-``choices`` beim
    #: Start auswertet, vor jeder Migration. Die Auswahl setzt das Formular
    #: (``forms.steuersatz_auswahl_eingrenzen``).
    steuersatz = models.CharField(
        'Steuersatz', max_length=5, default=steuersatz_tabelle.vorgabe,
    )
    #: Zeitraum der Position (BT-134/135), bei der Übernahme aus den Tagen
    #: der erfassten Tätigkeiten vorbelegt, änderbar. Nur bei Rechnungen in
    #: der Maske. In die E-Rechnung geht nur dieser Zeitraum, nie das
    #: Tätigkeitsdatum.
    leistung_von = models.DateField('Leistung von', null=True, blank=True)
    leistung_bis = models.DateField('Leistung bis', null=True, blank=True)

    #: Angeboten ohne Anteil an der Summe; der Kunde kann sie zum genannten
    #: Preis hinzunehmen (im Bauwesen "Eventualposition"). Nur an Angebot
    #: und Auftrag; in keiner Summe (R-178), auch nicht im Auftragswert.
    #: Menge 0 erlaubt.
    optional = models.BooleanField(
        'Optional', default=False,
        help_text='Zählt nicht in die Summe. Im PDF steht der Betrag in '
                  'Klammern, bei Menge 0 gar nicht.',
    )

    #: Leistung, Titel, Text oder Zuschlag. Ein Titel gliedert über die
    #: Nummer: Titel "01" fasst alles mit "01." zusammen, die Titelsumme
    #: steht im PDF (``services.titelsummen``).
    zeilenart = models.CharField(
        'Zeilenart', max_length=10, choices=Zeilenart,
        default=Zeilenart.LEISTUNG,
        help_text='Titel: Überschrift mit Summe über alle Positionen, deren '
                  'Nummer mit der Titelnummer und einem Punkt beginnt. Text: '
                  'freier Absatz ohne Preis. Zuschlag: Prozent auf die '
                  'Positionen darüber.',
    )
    #: Nur am Zuschlag: Prozentsatz ...
    zuschlag_prozent = models.DecimalField(
        'Zuschlag %', max_digits=6, decimal_places=2, null=True, blank=True,
        help_text='Nur bei einem Zuschlag: der Satz in Prozent, z. B. 3 für '
                  'Nebenkosten 3 %.',
    )
    #: ... und Bezug als Präfix der Positionsnummer. Leer bedeutet alle
    #: Leistungen des Belegs, "01" den Titel 01, "01.0020" genau diese
    #: Position. Ein Zuschlag bezieht sich nie auf einen anderen.
    zuschlag_auf = models.CharField(
        'Zuschlag auf', max_length=30, blank=True, default='',
        help_text='Leer: auf alle Leistungen. Eine Titelnummer (01): auf '
                  'diesen Titel. Eine Positionsnummer (01.0020): auf genau '
                  'diese Position.',
    )

    #: Bestimmt die Maske der Leistungserfassung (Uhrzeiten oder Menge) bei
    #: Kontierung auf diese Auftragsposition. Leer bei frei eingegebenen
    #: Positionen; die Erfassung behandelt das wie MENGE.
    art = models.CharField(
        'Art', max_length=20, choices=Leistungsart, blank=True, default='',
        help_text='Kommt aus dem Katalog. Leer bei frei eingetragenen '
                  'Positionen.',
    )

    #: Abgerechnete Auftragsposition. An der Position, weil eine Rechnung
    #: Positionen mehrerer Aufträge enthalten kann. Leer für nicht
    #: Beauftragtes (Regie, Nebenkosten). Der Auftrag ergibt sich über
    #: ``auftragsposition.beleg``.
    auftragsposition = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True, blank=True,
        limit_choices_to={'beleg__typ': 'auftrag',
                          'beleg__status': 'festgeschrieben',
                          'zeilenart__in': ('leistung', 'zuschlag')},
        related_name='abrechnungen',
        verbose_name='Auftragsposition',
        help_text='Die beauftragte Leistung, die hier abgerechnet wird. '
                  'Leer lassen, wenn die Position zu keinem Auftrag gehört.',
        db_comment='Zeigt von der Rechnungs- auf die Auftragsposition. Der '
                   'Auftrag ergibt sich über auftragsposition.beleg; kein '
                   'zweites Feld dafür.',
    )

    #: Absetzung eines Abschlags in der Schlussrechnung, für die Darstellung
    #: unter der Summe. Berechnet wie jede Position mit negativem Preis
    #: (§ 14 Abs. 5 Satz 2 UStG). Eigenes Feld, weil auch Stornopositionen
    #: negativ sind.
    ist_abzug = models.BooleanField(
        'Abzugszeile', default=False,
        help_text='Absetzung eines geleisteten Abschlags. Steht im PDF unter '
                  'den Leistungen, nicht zwischen ihnen.',
    )
    #: Nur an Abzugszeilen: die abgesetzte Position des Abschlags. Daraus
    #: folgt "bereits abgesetzt", damit ein Abschlag genau einmal angerechnet
    #: wird (``services.abschlaege_absetzen``). Je Position, weil sich ein
    #: Abschlag über Teil- und Restleistung auf Teilschluss- und
    #: Schlussrechnung verteilt.
    abgesetzte_position = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='absetzungen',
        verbose_name='Abgesetzte Abschlagsposition',
    )
    #: Nur an Abzugszeilen: der nicht bezahlte und daher nicht abgesetzte
    #: Teil des Abschlags, positiv, direkt unter der Absetzung. Gefordert
    #: wird er über einen späteren Abschlag oder mit dieser Rechnung. Netto
    #: abgesetzt wird nur Vereinnahmtes (§ 14 Abs. 5 Satz 2 UStG); mit der
    #: Schlussrechnung erlischt die Abschlagsforderung. Die Umsatzsummen
    #: lassen diese Zeile aus, weil der Betrag im Abschlag enthalten ist
    #: (Rechenregister R-174).
    ist_abschlagsrest = models.BooleanField(
        'Nicht bezahlter Abschlag', default=False,
        help_text='Der nicht bezahlte Teil eines Abschlags, der deshalb '
                  'nicht abgesetzt wird. Wird beim Absetzen errechnet.',
    )

    class Meta:
        verbose_name = 'Position'
        verbose_name_plural = 'Positionen'
        ordering = ['sortierung', 'pk']
        constraints = [
            models.UniqueConstraint(
                fields=['beleg', 'position'], name='eindeutige_position_je_beleg'
            ),
        ]

    def __str__(self) -> str:
        return f'{self.position}. {self.bezeichnung}'

    def save(self, *args, **kwargs):
        if self.beleg_id:
            self._pruefe_aenderbarkeit()
        if self.zeilenart in Zeilenart.ohne_betrag():
            # Ohne Menge und Preis, damit die Zeile ohne Sonderfall aus jeder
            # Summe fällt.
            self.menge = Decimal('0')
            self.einzelpreis = Decimal('0.00')
            self.einheit = ''
            self.optional = False
            self.auftragsposition = None
        if self.zeilenart == Zeilenart.ZUSCHLAG:
            # Der Betrag ist der Einzelpreis; berechnet in
            # ``services.zuschlaege_nachrechnen``.
            self.menge = Decimal('1')
            self.einheit = ''
        else:
            self.zuschlag_prozent = None
            self.zuschlag_auf = ''
        self.zuschlag_auf = (self.zuschlag_auf or '').strip()
        self.position = str(self.position).strip()
        self.sortierung = sortierschluessel(self.position)
        if kwargs.get('update_fields') and 'position' in kwargs['update_fields']:
            kwargs['update_fields'] = {*kwargs['update_fields'], 'sortierung'}
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._pruefe_aenderbarkeit()
        return super().delete(*args, **kwargs)

    def clean(self):
        """Abrechnung nur gegen die Position eines festgeschriebenen Auftrags.
        Die Menge wird beim Festschreiben erzwungen."""
        super().clean()
        if (self.leistung_von and self.leistung_bis
                and self.leistung_bis < self.leistung_von):
            raise ValidationError({
                'leistung_bis': 'Das Ende des Zeitraums liegt vor seinem '
                                'Beginn.'})
        if self.zeilenart == Zeilenart.ZUSCHLAG:
            if self.zuschlag_prozent is None:
                raise ValidationError({
                    'zuschlag_prozent': 'Ein Zuschlag braucht seinen Satz '
                                        'in Prozent.'})
        if self.zeilenart in Zeilenart.ohne_betrag():
            return
        if self.menge is not None and self.menge <= 0 and not self.optional:
            raise ValidationError({
                'menge': 'Mindestens 0,001; nur eine optionale Position '
                         'darf die Menge 0 haben.'})
        if (self.optional and self.beleg_id
                and self.beleg.typ not in BelegTyp.mit_optionen()):
            raise ValidationError({
                'optional': f'Optionale Positionen gibt es nur in Angebot '
                            f'und Auftrag, nicht in {self.beleg.get_typ_display()}.'})
        if not self.auftragsposition_id:
            return

        ziel = self.auftragsposition
        if ziel.beleg.typ != BelegTyp.AUFTRAG:
            raise ValidationError({
                'auftragsposition': f'{ziel.beleg} ist kein Auftrag. '
                                    f'Abgerechnet wird gegen Beauftragtes.',
            })
        if ziel.beleg.status != BelegStatus.FESTGESCHRIEBEN:
            raise ValidationError({
                'auftragsposition': f'{ziel.beleg} ist noch ein Entwurf. '
                                    f'Solange der Auftrag nicht steht, gibt '
                                    f'es nichts, wogegen abgerechnet würde.',
            })
        if self.pk and ziel.pk == self.pk:
            raise ValidationError({
                'auftragsposition': 'Eine Position rechnet nicht sich selbst ab.',
            })

    @property
    def abgerechnete_menge(self) -> Decimal:
        """Bereits abgerechnete Menge dieser Auftragsposition.

        Eine Abfrage je Aufruf; für Listen ``services.abgerechnete_mengen()``.
        """
        from .. import services

        return services.abgerechnete_mengen([self.pk]).get(
            self.pk, Decimal('0'))

    @property
    def offene_menge(self) -> Decimal:
        """Noch abzurechnende Menge der Auftragsposition, nie negativ."""
        rest = self.menge - self.abgerechnete_menge
        return rest if rest > 0 else Decimal('0')

    @property
    def abrechnungsstand(self) -> str:
        """Abrechnungsstand wie "60 von 100 Std abgerechnet"; leer, wenn die
        Position keine Auftragsposition ist."""
        if (self.beleg.typ != BelegTyp.AUFTRAG
                or self.zeilenart in Zeilenart.ohne_betrag()):
            return ''
        abgerechnet = self.abgerechnete_menge
        stand = (f'{abgerechnet.normalize():f} von '
                 f'{self.menge.normalize():f} {self.einheit} abgerechnet'
                 ).replace('  ', ' ')
        # Überschreitung möglich, weil die Mengenprüfung nur warnt; deshalb
        # eigens ausgewiesen. Nicht an einer Option, bei der der Preis
        # beauftragt ist und die Menge offen (R-157).
        if abgerechnet > self.menge and not self.optional:
            stand += (f', {(abgerechnet - self.menge).normalize():f} mehr '
                      f'als beauftragt')
        return stand

    @property
    def steuersatz_dezimal(self) -> Decimal:
        return Decimal(self.steuersatz)

    def _pruefe_aenderbarkeit(self):
        """Liest den Belegstatus aus der Datenbank.

        ``self.beleg`` genügt nicht, weil ``beleg.positionen.all()`` die
        Elterninstanz aus dem Speicher setzt, deren Status nach einem
        Festschreiben über die Services noch "entwurf" sein kann.
        """
        zustand = (
            Beleg.objects.filter(pk=self.beleg_id)
            .values('status', 'typ')
            .first()
        )
        if zustand is None or zustand['status'] == BelegStatus.ENTWURF:
            return

        ausweg = (
            ' Für eine Änderung den Beleg wieder öffnen.'
            if zustand['typ'] in BelegTyp.entsperrbar() else ''
        )
        raise BelegNichtAenderbar(
            f'Beleg {self.beleg_id} ist festgeschrieben; '
            f'Positionen sind gesperrt.{ausweg}'
        )


class BelegNichtAenderbar(FachlicherFehler):
    """Änderungsversuch an einem festgeschriebenen Beleg.

    Im Modul der Modelle, weil diese sie auslösen. 409, weil der Request
    gültig ist und nur der Zustand des Belegs ihn verhindert.
    """

    http_status = 409


# ── Proxy-Modelle: eine Tabelle, eine Sicht je Belegart ────────────────
#
# Je Belegart ein eigener Menüpunkt und eigene Rechte im Admin.
# ``Beleg.objects`` liefert alle Belege.


class TypManager(models.Manager):
    """Beschränkt Abfragen auf eine Belegart und ggf. eine Rechnungsart."""

    def __init__(self, typ, rechnungsart=''):
        super().__init__()
        self.typ = typ
        self.rechnungsart = rechnungsart

    def get_queryset(self):
        abfrage = super().get_queryset().filter(typ=self.typ)
        if self.rechnungsart:
            abfrage = abfrage.filter(rechnungsart=self.rechnungsart)
        return abfrage


class Angebot(Beleg):
    objects = TypManager(BelegTyp.ANGEBOT)

    class Meta:
        proxy = True
        verbose_name = 'Angebot'
        verbose_name_plural = 'Angebote'


class Auftrag(Beleg):
    """Verbindlicher Auftrag, Grundlage jeder Abrechnung.

    Entsteht aus einem angenommenen Angebot; Erweiterungen sind Nachträge
    (``nachtrag_zu``). Abgerechnet wird über die Positionen:
    Rechnungspositionen verweisen per ``auftragsposition`` hierher, und über
    alle Rechnungen darf nicht mehr abgerechnet werden als beauftragt.
    """

    objects = TypManager(BelegTyp.AUFTRAG)

    class Meta:
        proxy = True
        verbose_name = 'Auftrag'
        verbose_name_plural = 'Aufträge'


class Lieferschein(Beleg):
    objects = TypManager(BelegTyp.LIEFERSCHEIN)

    class Meta:
        proxy = True
        verbose_name = 'Lieferschein'
        verbose_name_plural = 'Lieferscheine'


class Rechnung(Beleg):
    """Gewöhnliche Rechnung, auch als Teilleistungsabrechnung mit
    Positionsbezug und Teilmenge."""

    objects = TypManager(BelegTyp.RECHNUNG, Rechnungsart.NORMAL)

    class Meta:
        proxy = True
        verbose_name = 'Rechnung'
        verbose_name_plural = 'Rechnungen'


class Abschlagsrechnung(Beleg):
    """Fordert Geld auf eine noch nicht vollendete Leistung an.

    Steuerlich eine Anzahlung (§ 13 Abs. 1 Nr. 1a Satz 4 UStG); die
    Schlussrechnung setzt die Abschläge ab.
    """

    objects = TypManager(BelegTyp.RECHNUNG, Rechnungsart.ABSCHLAG)

    class Meta:
        proxy = True
        verbose_name = 'Abschlagsrechnung'
        verbose_name_plural = 'Abschlagsrechnungen'


class Schlussrechnung(Beleg):
    """Führt die volle Leistung auf und setzt die Abschläge ab, netto und
    Steuer je Satz (§ 14 Abs. 5 Satz 2 UStG). Ohne Absetzung ist die Steuer
    doppelt geschuldet (§ 14c).

    Die Abzugszeilen sind Positionen mit negativem Preis und
    ``ist_abzug=True``, erzeugt von ``services.abschlaege_absetzen``. In
    der E-Rechnung stehen sie als BT-113.
    """

    objects = TypManager(BelegTyp.RECHNUNG, Rechnungsart.SCHLUSS)

    class Meta:
        proxy = True
        verbose_name = 'Schlussrechnung'
        verbose_name_plural = 'Schlussrechnungen'


class Teilschlussrechnung(Beleg):
    """Rechnet eine gesondert abgenommene Teilleistung endgültig ab, mit
    eigenem Leistungsdatum und Steuersatz. Sie verbraucht das Kontingent und
    entsteht nur aus einer Teilabnahme (``Abnahme``).
    """

    objects = TypManager(BelegTyp.RECHNUNG, Rechnungsart.TEILSCHLUSS)

    class Meta:
        proxy = True
        verbose_name = 'Teilschlussrechnung'
        verbose_name_plural = 'Teilschlussrechnungen'


class Stornorechnung(Beleg):
    objects = TypManager(BelegTyp.STORNO)

    class Meta:
        proxy = True
        verbose_name = 'Stornorechnung'
        verbose_name_plural = 'Stornorechnungen'


class Rechnungskorrektur(Beleg):
    """Nachträglicher Nachlass auf eine Rechnung, Entgeltminderung nach
    § 17 UStG. Die Stornorechnung hebt die Rechnung vollständig auf.

    Der Name vermeidet "Gutschrift", weil das UStG damit die Abrechnung
    durch den Leistungsempfänger bezeichnet (§ 14 Abs. 2).
    """

    objects = TypManager(BelegTyp.GUTSCHRIFT)

    class Meta:
        proxy = True
        verbose_name = 'Rechnungskorrektur'
        verbose_name_plural = 'Rechnungskorrekturen'


class Mahnung(Beleg):
    objects = TypManager(BelegTyp.MAHNUNG)

    class Meta:
        proxy = True
        verbose_name = 'Mahnung'
        verbose_name_plural = 'Mahnungen'


def proxy_fuer(typ: str, rechnungsart: str = '') -> type[Beleg]:
    """Proxy-Modell zu einer Belegart (``'rechnung'`` ergibt ``Rechnung``).

    Der Admin-Verlauf eines Belegs filtert über den ContentType des Proxys;
    ein LogEntry am Basismodell erschiene dort nicht. Aus den vorhandenen
    Klassen abgeleitet, damit ein neuer Proxy automatisch erfasst wird. Ohne
    passenden Proxy ``Beleg``.
    """
    passende = [k for k in Beleg.__subclasses__()
                if getattr(k.objects, 'typ', None) == typ]
    if len(passende) > 1:
        passende = [k for k in passende
                    if getattr(k.objects, 'rechnungsart', '') == rechnungsart] \
            or passende
    return passende[0] if passende else Beleg
