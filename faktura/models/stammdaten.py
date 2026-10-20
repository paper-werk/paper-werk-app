"""Stammdaten: die eigene Firma, Kunden mit Adressen, Personen und
Kontaktwegen, Projekte.

Änderungen wirken nur auf künftige Belege. Ein Beleg kopiert beim Anlegen
Anschrift und Konditionen; der Fremdschlüssel auf Kunde oder Projekt dient
nur der Navigation.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone
from sequences import get_next_value

from core.optimistic_locking import ErhoehtElternversion, MitVersion

from ..steuerfall import Steuerfall


class Firma(models.Model):
    """Eigene Firma als Absender.

    Ein Modell, weil der Betrieb Bankverbindung, Anschrift und Logo im Admin
    pflegt. Alte Belege bleiben unverändert, weil ihr PDF beim
    Festschreiben gespeichert wird.

    Genau ein Datensatz. Ein Fremdschlüssel vom Beleg hierher brächte
    Mandantenfähigkeit; verworfen, solange es nur einen Mandanten gibt.
    """

    name = models.CharField('Firmenname', max_length=200)
    zusatz = models.CharField('Namenszusatz', max_length=200, blank=True, default='')

    strasse = models.CharField('Straße', max_length=200)
    plz = models.CharField('PLZ', max_length=10)
    ort = models.CharField('Ort', max_length=100)
    land = models.CharField(
        'Ländercode', max_length=2, default='DE',
        help_text='Zwei Buchstaben nach ISO 3166, wird für die E-Rechnung gebraucht.',
    )

    telefon = models.CharField('Telefon', max_length=50, blank=True, default='')
    email = models.EmailField('E-Mail', blank=True, default='')
    web = models.CharField('Web', max_length=100, blank=True, default='')

    # Eine Rechnung braucht Steuernummer oder USt-IdNr. (§ 14 Abs. 4 Nr. 2
    # UStG) für den Vorsteuerabzug des Empfängers.
    steuernummer = models.CharField('Steuernummer', max_length=30, blank=True, default='')
    ust_id = models.CharField('USt-IdNr.', max_length=20, blank=True, default='')

    kleinunternehmer = models.BooleanField(
        'Kleinunternehmer nach § 19 UStG',
        default=False,
        help_text='Wenn gesetzt, wird keine Umsatzsteuer ausgewiesen und der '
                  'vorgeschriebene Hinweis auf den Beleg gedruckt.',
    )

    bank = models.CharField('Kreditinstitut', max_length=100, blank=True, default='')
    iban = models.CharField('IBAN', max_length=34, blank=True, default='')
    bic = models.CharField('BIC', max_length=11, blank=True, default='')

    # Pflichtangaben im Geschäftsbrief von Kapitalgesellschaften
    # (§ 35a GmbHG, § 125a HGB).
    geschaeftsfuehrung = models.CharField(
        'Geschäftsführung', max_length=200, blank=True, default=''
    )
    registergericht = models.CharField(
        'Registergericht', max_length=100, blank=True, default=''
    )
    handelsregister = models.CharField(
        'Handelsregisternummer', max_length=50, blank=True, default=''
    )

    logo = models.ImageField('Logo', upload_to='firma/', blank=True, null=True)

    standard_fusstext = models.TextField(
        'Standardtext unter den Positionen', blank=True, default='',
        help_text='Wird verwendet, wenn am Beleg selbst kein Fußtext steht.',
    )

    # --- Mahngebühren ---
    #: Je Mahnstufe konfigurierbar, weil als Verzugsschaden nur Sachkosten
    #: ersetzt werden und die Mahnung, die den Verzug auslöst, gar nicht.
    #: Die Defaults sind Vorschläge ohne rechtliche Gewähr.
    mahngebuehr_erinnerung = models.DecimalField(
        'Gebühr Zahlungserinnerung', max_digits=8, decimal_places=2,
        default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0'))],
    )
    mahngebuehr_mahnung = models.DecimalField(
        'Gebühr Mahnung', max_digits=8, decimal_places=2,
        default=Decimal('2.50'), validators=[MinValueValidator(Decimal('0'))],
    )
    mahngebuehr_letzte = models.DecimalField(
        'Gebühr Letzte Mahnung', max_digits=8, decimal_places=2,
        default=Decimal('2.50'), validators=[MinValueValidator(Decimal('0'))],
    )

    class Meta:
        verbose_name = 'Firma'
        verbose_name_plural = 'Firma'

    def __str__(self) -> str:
        return self.name

    @classmethod
    def aktuelle(cls) -> 'Firma | None':
        """Die Firma oder None, solange keine angelegt ist.

        Ohne Exception, damit eine neue Installation vor vollständigen
        Stammdaten bedienbar ist. Das Festschreiben prüft die Angaben
        explizit.
        """
        return cls.objects.first()

    @property
    def anschrift_einzeilig(self) -> str:
        """Für die Absenderzeile über dem Anschriftfeld (DIN 5008)."""
        return f'{self.name} - {self.strasse} - {self.plz} {self.ort}'

    @property
    def steuerangabe(self) -> str:
        """Steuerliche Kennung für den Beleg."""
        if self.ust_id:
            return f'USt-IdNr. {self.ust_id}'
        if self.steuernummer:
            return f'Steuernummer {self.steuernummer}'
        return ''


# ── Kunden- und Projektnummern ───────────────────────────────────────────
#
# Ohne Lückenlosigkeit, anders als Belegnummern
# (``services.naechste_belegnummer``), weil eine Kundennummer nur eine ID ist.
#
# Je Nummer zwei Funktionen: ``naechste_*`` inkrementiert den Zähler und
# verbraucht eine Nummer (``save()`` ohne Formular: Shell, Import, Seed).
# ``*_vorschlag`` liest nur den Bestand und ist Initialwert im leeren
# Formular, damit ein abgebrochenes Anlegen keine Lücke hinterlässt.

#: Startwert 1000, damit Nummern nicht mit "K-1" beginnen.
KUNDENNUMMER_KREIS = 'kundennummer'
KUNDENNUMMER_START = 1000


def naechste_kundennummer() -> str:
    """Nächste freie Kundennummer aus dem Zähler (K-1000, K-1001, …).

    ``django-sequences`` sperrt die Zählerzeile, damit gleichzeitige Anlagen
    verschiedene Nummern erhalten. Die Schleife überspringt bereits
    vergebene Nummern (aus dem Seed oder manuell).
    """
    while True:
        nummer = f'K-{get_next_value(KUNDENNUMMER_KREIS, initial_value=KUNDENNUMMER_START)}'
        if not Kontakt.objects.filter(nummer=nummer).exists():
            return nummer


#: Ein Zähler je Jahr, weil das Jahr Teil der Nummer ist.
PROJEKTNUMMER_KREIS = 'projekt'


def naechste_projektnummer(jahr: int | None = None) -> str:
    """Nächste freie Projektnummer aus dem Zähler (2026-125, 2026-126, …).

    Der Startwert kommt aus dem Bestand, damit der Zähler nicht bei eins
    beginnt und alle vergebenen Nummern des Jahres durchläuft. Die Schleife
    überspringt manuell vergebene Nummern.
    """
    jahr = jahr or timezone.localdate().year
    start = _hoechste_projektnummer(jahr) + 1
    while True:
        laufend = get_next_value(f'{PROJEKTNUMMER_KREIS}-{jahr}',
                                 initial_value=start)
        nummer = f'{jahr}-{laufend:03d}'
        if not Projekt.objects.filter(nummer=nummer).exists():
            return nummer


def projektnummer_vorschlag(jahr: int | None = None) -> str:
    """Initialwert im leeren Formular, ohne den Zähler zu inkrementieren."""
    jahr = jahr or timezone.localdate().year
    return f'{jahr}-{_hoechste_projektnummer(jahr) + 1:03d}'


def _hoechste_projektnummer(jahr: int) -> int:
    """Höchste vergebene laufende Nummer dieses Jahres.

    Nummern außerhalb des Musters ("BV-Halle-Nord") werden ignoriert.
    """
    hoechste = 0
    for nummer in (Projekt.objects
                   .filter(nummer__startswith=f'{jahr}-')
                   .values_list('nummer', flat=True)):
        rest = nummer[len(str(jahr)) + 1:]
        if rest.isdigit():
            hoechste = max(hoechste, int(rest))
    return hoechste


def kundennummer_vorschlag() -> str:
    """Initialwert im leeren Formular, ohne den Zähler zu inkrementieren.

    Zwei gleichzeitig offene Formulare zeigen dieselbe Nummer; das zweite
    erhält beim Speichern "existiert bereits". Diese Meldung im seltenen
    Fall wird in Kauf genommen, damit im Regelfall keine Lücken entstehen.
    """
    return f'K-{_hoechste_kundennummer() + 1}'


def _hoechste_kundennummer() -> int:
    """Höchste vergebene Zahl im Muster ``K-NNNN``, mindestens Startwert
    minus 1.

    Nummern außerhalb des Musters ("DEBITOR-4711") werden ignoriert.
    """
    hoechste = KUNDENNUMMER_START - 1
    for nummer in (Kontakt.objects
                   .filter(nummer__startswith='K-')
                   .values_list('nummer', flat=True)):
        rest = nummer[2:]
        if rest.isdigit():
            hoechste = max(hoechste, int(rest))
    return hoechste


class Anrede(models.TextChoices):
    """Nur für die Briefanrede.

    Ohne Anrede gilt "Sehr geehrte Damen und Herren".
    """

    KEINE = '', 'ohne (neutral anschreiben)'
    FRAU = 'frau', 'Frau'
    HERR = 'herr', 'Herr'


class Adressverwendung(models.TextChoices):
    """Zweck, für den eine Adresse vorgeschlagen wird.

    Beispiel: Ein Landratsamt erhält das Angebot im Fachamt und die Rechnung
    in der zentralen Buchhaltung. Die Verwendung ist ein Vorschlag;
    maßgeblich ist das freie Empfängerfeld am Beleg.
    """

    RECHNUNG = 'rechnung', 'Rechnungsanschrift'
    POST = 'post', 'Postanschrift'
    LIEFERUNG = 'lieferung', 'Lieferanschrift'
    SONSTIGE = 'sonstige', 'Sonstige'


class Kontaktart(models.TextChoices):
    """E-Mail, Telefon, Mobil, Fax, Web in einer Tabelle, weil sie sich nur
    in dieser Spalte unterscheiden."""

    EMAIL = 'email', 'E-Mail'
    TELEFON = 'telefon', 'Telefon'
    MOBIL = 'mobil', 'Mobil'
    FAX = 'fax', 'Fax'
    WEB = 'web', 'Web'
    #: Slack, LinkedIn, Teams, Kundenportal: Der Dienst steht in
    #: ``bezeichnung``, damit keine Liste von Diensten zu pflegen ist.
    WEITERE = 'weitere', 'Weitere'


class Zustellweg(models.TextChoices):
    """Gewünschter Zustellweg für Rechnungen.

    Information für den Versand. Nur ``XRECHNUNG`` hat technische Wirkung:
    Das XML entsteht beim Festschreiben im Profil XRechnung
    (``facturx.ist_xrechnung``).
    """

    PDF_MAIL = 'pdf_mail', 'PDF per E-Mail'
    ERECHNUNG = 'erechnung', 'E-Rechnung als PDF (ZUGFeRD)'
    XRECHNUNG = 'xrechnung', 'XRechnung (XML, z. B. für ein Rechnungsportal)'
    POST = 'post', 'Papier per Post'


class Kontakt(MitVersion):
    """Geschäftspartner: Kunde, Lieferant, Partner oder Interessent, auch
    mehreres zugleich. Anschriften stehen in ``Adresse``, E-Mail und Telefon
    in ``Kontaktweg``, Personen in ``Ansprechpartner``.

    Belege, Projekte und Zahlungen verweisen mit dem Feld ``kunde`` hierher,
    auf den Kontakt in der Rolle Kunde.

    ``kontakt.strasse``, ``kontakt.email`` usw. sind Read-only-Properties auf
    die Standardadresse und den Standard-Kontaktweg, ohne eigene Spalte.
    """

    # blank=True, damit das Formular sie leer lassen darf; gesetzt in
    # save(). Ohne null=True, weil nach dem Speichern immer eine Nummer
    # vorhanden ist.
    nummer = models.CharField(
        'Kundennummer', max_length=20, unique=True, blank=True,
        help_text='Leer lassen, wird dann vergeben (K-1000 aufwärts). Eine '
                  'eigene Nummer aus einem bestehenden System wird '
                  'übernommen, wenn sie eingetragen wird.',
    )
    name = models.CharField('Name', max_length=200)
    ust_id = models.CharField('USt-IdNr.', max_length=20, blank=True, default='')

    #: Rollen, auch mehrere (gegenseitige Beauftragung ergibt Kunde und
    #: Lieferant). Belege, Projekte und Zahlungen bieten nur Kunden an,
    #: Eingangsrechnungen nur Lieferanten.
    ist_kunde = models.BooleanField('Kunde', default=True)
    ist_lieferant = models.BooleanField('Lieferant', default=False)
    ist_partner = models.BooleanField('Partner', default=False)
    ist_interessent = models.BooleanField('Interessent', default=False)

    eigene_kundennummer = models.CharField(
        'Eigene Kundennummer', max_length=50, blank=True, default='',
        help_text='Unter dieser Nummer führt uns der Kontakt, für '
                  'Rückfragen und Bestellungen.',
    )

    #: Anderer Kunde als Rechnungsempfänger (Hausverwaltung, Konzernmutter,
    #: Versicherung). Personen sind ``Ansprechpartner``.
    rechnungsempfaenger = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        related_name='zahlt_fuer',
        limit_choices_to={'ist_kunde': True},
        verbose_name='Abweichender Rechnungsempfänger',
        null=True, blank=True,
        help_text='Nur setzen, wenn die Rechnung an einen anderen Kunden '
                  'geht, etwa Hausverwaltung, Konzernmutter, Versicherung. '
                  'Für Ansprechpartner ist dieses Feld nicht gedacht.',
    )

    zahlungsziel_tage = models.PositiveSmallIntegerField('Zahlungsziel (Tage)', default=14)

    #: Skonto in zwei Feldern, die nur zusammen gelten. Keine automatische
    #: Berechnung; Skonto wird bei der Zuordnung einer Zahlung erfasst.
    skonto_prozent = models.DecimalField(
        'Skonto (%)', max_digits=4, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text='0 heißt: kein Skonto vereinbart.',
    )
    skonto_tage = models.PositiveSmallIntegerField(
        'Skontofrist (Tage)', default=0,
        help_text='Innerhalb wie vieler Tage der Abzug gilt.',
    )

    #: Vorbelegung für neue Belege (§ 13b, EU, Drittland); maßgeblich ist
    #: der Wert am Beleg. Siehe ``faktura/steuerfall.py``.
    steuerfall = models.CharField(
        'Steuerfall', max_length=30, choices=Steuerfall, blank=True,
        default=Steuerfall.REGULAER,
        help_text='Vorbelegung für neue Belege. Bei allem außer dem '
                  'Regelfall gehen die Positionen mit 0 % hinaus, und der '
                  'Beleg trägt den gesetzlichen Vermerk.',
    )

    zustellweg = models.CharField(
        'Zustellweg', max_length=20, choices=Zustellweg,
        default=Zustellweg.PDF_MAIL,
        help_text='Wie dieser Kunde Rechnungen bekommen will. Bei '
                  '"XRechnung" entsteht das XML seiner Rechnungen im Profil '
                  'XRechnung; dafür braucht es die Leitweg-ID.',
    )

    #: BT-10 der EN 16931: bei Behörden die Leitweg-ID, sonst Kostenstelle
    #: oder Lieferantennummer, ein Feld, weil beides in BT-10 geht.
    #: Vorbelegung; maßgeblich ist ``Beleg.leitweg_id``, weil Leitweg-IDs oft
    #: je Amt verschieden sind.
    kaeuferreferenz = models.CharField(
        'Käuferreferenz', max_length=50, blank=True, default='',
        help_text='Vorbelegung für neue Belege (BT-10 der E-Rechnung). Bei '
                  'öffentlichen Auftraggebern die Leitweg-ID, sonst die '
                  'Referenz, unter der dieser Kunde die Rechnung zuordnet.',
    )

    #: Deaktivieren als Ersatz für Löschen, weil ``Beleg.kunde`` und
    #: ``Projekt.kunde`` PROTECT sind.
    aktiv = models.BooleanField(
        'Aktiv', default=True,
        help_text='Inaktive Kunden stehen in den Auswahllisten nicht mehr '
                  'zur Wahl. Ihre Belege und Projekte bleiben unberührt.',
    )

    notiz = models.TextField('Notiz', blank=True, default='')

    class Meta:
        verbose_name = 'Kontakt'
        verbose_name_plural = 'Kontakte'
        ordering = ['name']
        constraints = [
            # Als Constraint, weil Import und Shell clean() umgehen.
            models.CheckConstraint(
                condition=(models.Q(ist_kunde=True) | models.Q(ist_lieferant=True)
                           | models.Q(ist_partner=True)
                           | models.Q(ist_interessent=True)),
                name='kontakt_hat_eine_rolle',
                violation_error_message='Ein Kontakt braucht mindestens eine '
                                        'Rolle: Kunde, Lieferant, Partner '
                                        'oder Interessent.',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.nummer} {self.name}'

    def save(self, *args, **kwargs):
        """Vergibt die Nummer, wenn keine eingetragen ist.

        Im Modell, weil auch Shell, Import und Services über ``save()``
        schreiben. ``atomic``, damit eine gezogene Nummer immer verwendet
        wird.
        """
        if not self.nummer:
            with transaction.atomic():
                self.nummer = naechste_kundennummer()
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)

    def clean(self):
        """Verbietet den Kunden als eigenen Rechnungsempfänger.

        Nur der direkte Selbstverweis, weil ``rechnungsanschrift`` nur eine
        Stufe auflöst und Zyklen dadurch folgenlos sind.
        """
        if (self.rechnungsempfaenger_id
                and self.pk
                and self.rechnungsempfaenger_id == self.pk):
            raise ValidationError({
                'rechnungsempfaenger':
                    'Ein Kunde kann nicht sein eigener Rechnungsempfänger sein.',
            })

    #: Rolle und Anzeige, in der Reihenfolge des Formulars.
    ROLLEN = {'ist_kunde': 'Kunde', 'ist_lieferant': 'Lieferant',
              'ist_partner': 'Partner', 'ist_interessent': 'Interessent'}

    @property
    def rollen(self) -> list[str]:
        """Gesetzte Rollen als Text, etwa "Kunde, Lieferant"."""
        return [name for feld, name in self.ROLLEN.items()
                if getattr(self, feld)]

    # -- Anlegen -------------------------------------------------------------

    @classmethod
    def anlegen(cls, *, strasse='', plz='', ort='', land='DE', email='',
                telefon='', **felder) -> 'Kontakt':
        """Legt einen Kunden mit Standardadresse, E-Mail und Telefon aus einer
        flachen Zeile an (Excel-Import, Altsystem, Demodaten, Tests).

        Leere Angaben erzeugen nichts: ohne Straße und Ort keine Adresse,
        ohne E-Mail kein Kontaktweg. Aufgerufen von ``KundeResource``.
        """
        kunde = cls.objects.create(**felder)
        if strasse or plz or ort:
            Adresse.objects.create(
                kontakt=kunde,
                verwendung=Adressverwendung.RECHNUNG,
                strasse=strasse, plz=plz, ort=ort, land=land or 'DE',
                ist_standard=True,
            )
        if email:
            Kontaktweg.objects.create(
                kontakt=kunde, art=Kontaktart.EMAIL, wert=email,
                ist_standard=True)
        if telefon:
            Kontaktweg.objects.create(
                kontakt=kunde, art=Kontaktart.TELEFON, wert=telefon,
                ist_standard=True)
        return kunde

    # -- Adressen ------------------------------------------------------------
    #
    # Gelesen über ``.all()`` und Filter in Python, damit
    # ``prefetch_related`` in Listen greift. Ohne ``pk`` leer, weil
    # ``Kunde()`` ohne Primärschlüssel vorkommt (``UebernahmeMixin``) und
    # Django beim Zugriff auf eine Relation dann eine Exception auslöst.

    @property
    def standardadresse(self) -> 'Adresse | None':
        """Standardanschrift oder None."""
        if not self.pk:
            return None
        for adresse in self.adressen.all():
            if adresse.ist_standard:
                return adresse
        return None

    def adresse_fuer(self, verwendung: str) -> 'Adresse | None':
        """Anschrift für diesen Zweck, sonst die Standardadresse."""
        if not self.pk:
            return None
        for adresse in self.adressen.all():
            if adresse.verwendung == verwendung:
                return adresse
        return self.standardadresse

    @property
    def rechnungsanschrift(self) -> 'Adresse | None':
        """Rechnungsanschrift, bei abweichendem Rechnungsempfänger dessen
        Anschrift (eine Stufe)."""
        if self.rechnungsempfaenger_id:
            return self.rechnungsempfaenger.adresse_fuer(
                Adressverwendung.RECHNUNG)
        return self.adresse_fuer(Adressverwendung.RECHNUNG)

    # Read-only-Properties auf die Standardadresse.
    @property
    def strasse(self) -> str:
        adresse = self.standardadresse
        return adresse.strasse if adresse else ''

    @property
    def plz(self) -> str:
        adresse = self.standardadresse
        return adresse.plz if adresse else ''

    @property
    def ort(self) -> str:
        adresse = self.standardadresse
        return adresse.ort if adresse else ''

    @property
    def land(self) -> str:
        """'DE' ohne Adresse, weil BT-55 der E-Rechnung Pflicht ist."""
        adresse = self.standardadresse
        return adresse.land if adresse else 'DE'

    @property
    def anschrift(self) -> str:
        adresse = self.standardadresse
        return adresse.anschrift if adresse else ''

    def anschriftfeld_fuer(self, person: 'Ansprechpartner | None' = None) -> str:
        """Anschriftfeld zeilenweise, wie es in ``Beleg.empfaenger`` kopiert
        wird: Name, "z. Hd.", Zusatz, Straße, PLZ Ort.

        Verwendet die Rechnungsanschrift. Die Person steht nach DIN 5008
        unter dem Namen der Organisation. Leere Teile entfallen.
        """
        adresse = self.rechnungsanschrift
        name = (self.rechnungsempfaenger.name if self.rechnungsempfaenger_id
                else self.name)
        zeilen = [name]
        if person is not None:
            zeilen.append(person.anschriftzusatz)
        if adresse:
            zeilen += adresse.zeilen
        return '\n'.join(zeile for zeile in zeilen if zeile)

    @property
    def anschriftfeld(self) -> str:
        """Anschriftfeld ohne Personenzeile."""
        return self.anschriftfeld_fuer(None)

    # -- Kontaktwege ---------------------------------------------------------

    def kontaktweg(self, art: str) -> str:
        """Standardwert dieser Art, sonst der erste, sonst leer.

        Der Fallback greift, wenn ein einzelner Eintrag nicht als Standard
        markiert ist.
        """
        if not self.pk:
            return ''
        passende = [k for k in self.kontaktwege.all() if k.art == art]
        for kontakt in passende:
            if kontakt.ist_standard:
                return kontakt.wert
        return passende[0].wert if passende else ''

    @property
    def email(self) -> str:
        """E-Mail-Adresse für Rechnungen. Für eine bestimmte Person
        ``Ansprechpartner.email``."""
        return self.kontaktweg(Kontaktart.EMAIL)

    @property
    def telefon(self) -> str:
        return self.kontaktweg(Kontaktart.TELEFON)

    # -- Ansprechpartner ------------------------------------------------------

    @property
    def standardansprechpartner(self) -> 'Ansprechpartner | None':
        """Standard-Ansprechpartner unter den aktiven, ohne Markierung der
        erste aktive."""
        if not self.pk:
            return None
        aktive = [a for a in self.ansprechpartner.all() if a.aktiv]
        for person in aktive:
            if person.ist_standard:
                return person
        return aktive[0] if aktive else None


class Adresse(ErhoehtElternversion):
    """Anschrift eines Kunden; ein Kunde hat meist mehrere.

    Quelle für die Kopie beim Anlegen eines Belegs. Nach einem Umzug des
    Kunden bleibt die Anschrift alter Rechnungen unverändert.
    """

    #: Inline-Änderungen inkrementieren die Version des Elternobjekts.
    version_eltern = ('kontakt',)

    kontakt = models.ForeignKey(
        Kontakt,
        on_delete=models.CASCADE,
        related_name='adressen',
        verbose_name='Kontakt',
    )
    verwendung = models.CharField(
        'Verwendung', max_length=20, choices=Adressverwendung,
        default=Adressverwendung.RECHNUNG,
        help_text='Wofür diese Anschrift vorgeschlagen wird.',
    )
    bezeichnung = models.CharField(
        'Bezeichnung', max_length=100, blank=True, default='',
        help_text='Zur Unterscheidung in der Liste: "Zentrale", '
                  '"Niederlassung Landshut". Steht auf keinem Beleg.',
    )
    #: "z. Hd. Buchhaltung", "Postfach 1120". Anders als die Bezeichnung
    #: Teil der Anschrift und auf dem Beleg sichtbar.
    zusatz = models.CharField(
        'Adresszusatz', max_length=200, blank=True, default='',
        help_text='Erscheint im Anschriftfeld über der Straße.',
    )
    strasse = models.CharField('Straße', max_length=200, blank=True, default='')
    plz = models.CharField('PLZ', max_length=10, blank=True, default='')
    ort = models.CharField('Ort', max_length=100, blank=True, default='')
    land = models.CharField(
        'Ländercode', max_length=2, default='DE',
        help_text='Zwei Buchstaben nach ISO 3166. Pflichtangabe der E-Rechnung.',
    )
    ist_standard = models.BooleanField(
        'Standardanschrift', default=False,
        help_text='Die Anschrift, die gilt, wenn keine andere genannt ist. '
                  'Genau eine je Kunde.',
    )

    class Meta:
        verbose_name = 'Adresse'
        verbose_name_plural = 'Adressen'
        ordering = ['-ist_standard', 'verwendung', 'ort']
        constraints = [
            # Zusätzlich als partieller Index, weil bei zwei
            # Standardadressen die Sortierung der Datenbank entschiede.
            models.UniqueConstraint(
                fields=['kontakt'],
                condition=models.Q(ist_standard=True),
                name='eine_standardadresse_je_kunde',
                violation_error_message=(
                    'Es kann nur eine Standardanschrift je Kunde geben. '
                    'Bitte bei genau einer Anschrift das Häkchen setzen.'),
            ),
        ]

    def __str__(self) -> str:
        teile = [self.bezeichnung or self.get_verwendung_display()]
        if self.ort:
            teile.append(f'{self.plz} {self.ort}'.strip())
        return ' - '.join(teile)

    def save(self, *args, **kwargs):
        """Die erste Anschrift eines Kunden wird seine Standardanschrift.

        Sonst hätte ein per Shell oder Import angelegter Kunde keine, und
        ``anschriftfeld`` lieferte nur den Namen. Entfällt bei
        ``standard_festgelegt``, siehe ``Kontaktweg.save``.
        """
        if (not self.ist_standard and self.kontakt_id
                and not getattr(self, 'standard_festgelegt', False)):
            andere = Adresse.objects.filter(
                kontakt_id=self.kontakt_id, ist_standard=True)
            if self.pk:
                andere = andere.exclude(pk=self.pk)
            if not andere.exists():
                self.ist_standard = True
        return super().save(*args, **kwargs)

    @property
    def zeilen(self) -> list[str]:
        """Anschrift zeilenweise ohne Namen: Zusatz, Straße, Ort."""
        return [teil for teil in
                (self.zusatz, self.strasse, f'{self.plz} {self.ort}'.strip())
                if teil]

    @property
    def anschrift(self) -> str:
        return '\n'.join(self.zeilen)


class Ansprechpartner(MitVersion, ErhoehtElternversion):
    """Person beim Kunden (Bauleitung, Buchhaltung, Geschäftsführung).

    Eigenes Modell, weil eine Person als Kunde eine Kundennummer erhielte und
    in Kundenauswahl und Umsatzauswertung erschiene. Personenbezogene Daten
    im Sinne der DSGVO, daher ``erfasst_am`` und CASCADE mit dem Kunden.
    Belege enthalten nur Text und sind nicht betroffen.
    """

    #: Inline-Änderungen inkrementieren die Version des Elternobjekts.
    version_eltern = ('kontakt',)

    kontakt = models.ForeignKey(
        Kontakt,
        on_delete=models.CASCADE,
        related_name='ansprechpartner',
        verbose_name='Kontakt',
    )
    anrede = models.CharField(
        'Anrede', max_length=10, choices=Anrede, blank=True, default='')
    titel = models.CharField(
        'Titel', max_length=30, blank=True, default='',
        help_text='"Dr.", "Prof."; steht vor dem Namen.')
    vorname = models.CharField('Vorname', max_length=100, blank=True, default='')
    nachname = models.CharField('Nachname', max_length=100)
    funktion = models.CharField(
        'Funktion', max_length=100, blank=True, default='',
        help_text='"Bauleitung", "Buchhaltung", "Projektsteuerung": wofür '
                  'diese Person zuständig ist.')
    #: SET_NULL, weil die Person beim Löschen der Adresse bestehen bleibt.
    adresse = models.ForeignKey(
        Adresse,
        on_delete=models.SET_NULL,
        related_name='ansprechpartner',
        verbose_name='Anschrift',
        null=True, blank=True,
        help_text='Nur bei mehreren Standorten nötig.',
    )
    ist_standard = models.BooleanField(
        'Hauptansprechpartner', default=False,
        help_text='Wer gemeint ist, wenn kein anderer genannt wird. '
                  'Höchstens einer je Kunde.',
    )
    #: Ausgeschieden oder nicht mehr zuständig. Deaktivieren als Ersatz für
    #: Löschen, damit "z. Hd." auf alten Belegen zuordenbar bleibt.
    aktiv = models.BooleanField('Aktiv', default=True)
    notiz = models.TextField('Notiz', blank=True, default='')
    erfasst_am = models.DateTimeField('Erfasst am', auto_now_add=True)

    class Meta:
        verbose_name = 'Ansprechpartner'
        verbose_name_plural = 'Ansprechpartner'
        ordering = ['-ist_standard', 'nachname', 'vorname']
        constraints = [
            models.UniqueConstraint(
                fields=['kontakt'],
                condition=models.Q(ist_standard=True),
                name='ein_hauptansprechpartner_je_kunde',
                violation_error_message=(
                    'Es kann nur einen Hauptansprechpartner je Kunde geben. '
                    'Bitte bei genau einer Person das Häkchen setzen.'),
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def name(self) -> str:
        """Name mit Titel, ohne Anrede ("Dr. Anna Müller")."""
        return ' '.join(teil for teil in
                        (self.titel, self.vorname, self.nachname) if teil)

    @property
    def briefanrede(self) -> str:
        """Briefanrede mit Komma ("Sehr geehrte Frau Dr. Müller,").

        Ohne Anrede die neutrale Form; nie aus dem Vornamen abgeleitet.
        """
        nachname = ' '.join(teil for teil in (self.titel, self.nachname) if teil)
        if self.anrede == Anrede.FRAU:
            return f'Sehr geehrte Frau {nachname},'
        if self.anrede == Anrede.HERR:
            return f'Sehr geehrter Herr {nachname},'
        return 'Sehr geehrte Damen und Herren,'

    @property
    def anschriftzusatz(self) -> str:
        """Zeile für das Anschriftfeld ("z. Hd. Frau Dr. Anna Müller")."""
        anrede = self.get_anrede_display() if self.anrede else ''
        return ' '.join(teil for teil in ('z. Hd.', anrede, self.name) if teil)

    @property
    def email(self) -> str:
        return self.kontaktweg(Kontaktart.EMAIL)

    @property
    def telefon(self) -> str:
        return self.kontaktweg(Kontaktart.TELEFON)

    def kontaktweg(self, art: str) -> str:
        """Wie ``Kontakt.kontaktweg``: Standard, sonst der erste."""
        if not self.pk:
            return ''
        passende = [k for k in self.kontaktwege.all() if k.art == art]
        for kontakt in passende:
            if kontakt.ist_standard:
                return kontakt.wert
        return passende[0].wert if passende else ''


class Kontaktweg(ErhoehtElternversion):
    """E-Mail-Adresse, Telefonnummer, Fax oder Webseite.

    Gehört zum Kunden oder zu einer Person, nie zu beiden (``info@`` zum
    Betrieb, die Durchwahl zur Person). Als Constraint, weil Shell, Import
    und API ``clean()`` umgehen.
    """

    #: Inline-Änderungen inkrementieren die Version des Elternobjekts.
    version_eltern = ('kontakt', 'ansprechpartner')

    kontakt = models.ForeignKey(
        Kontakt,
        on_delete=models.CASCADE,
        related_name='kontaktwege',
        verbose_name='Kontakt',
        null=True, blank=True,
    )
    ansprechpartner = models.ForeignKey(
        Ansprechpartner,
        on_delete=models.CASCADE,
        related_name='kontaktwege',
        verbose_name='Ansprechpartner',
        null=True, blank=True,
    )
    art = models.CharField('Art', max_length=20, choices=Kontaktart)
    #: Spalte ``wert``; das Formular zeigt ein sprechendes Label.
    wert = models.CharField(
        'Nummer oder Adresse', max_length=200,
        help_text='Die Telefonnummer, die E-Mail-Adresse, der Link.')
    bezeichnung = models.CharField(
        'Wofür', max_length=100, blank=True, default='',
        help_text='"Zentrale", "Buchhaltung", "Durchwahl", und bei der Art '
                  '"Weitere" der Dienst selbst: "Slack", "LinkedIn".')
    ist_standard = models.BooleanField(
        'Standard', default=False,
        help_text='Der Weg, der genommen wird, wenn keiner genannt ist. '
                  'Höchstens einer je Art.',
    )

    class Meta:
        verbose_name = 'Kontaktweg'
        verbose_name_plural = 'Kontaktwege'
        ordering = ['art', '-ist_standard', 'bezeichnung']
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(kontakt__isnull=False, ansprechpartner__isnull=True)
                    | models.Q(kontakt__isnull=True, ansprechpartner__isnull=False)
                ),
                name='kontaktweg_hat_genau_einen_traeger',
                violation_error_message=(
                    'Ein Kontaktdatensatz gehört entweder einem Kunden oder '
                    'einem Ansprechpartner; nicht beiden und nicht keinem.'),
            ),
            # Zwei partielle Indizes, weil in einem gemeinsamen Index die
            # NULL-Spalte des anderen Trägers in Postgres nie kollidiert und
            # beliebig viele Standards zuließe.
            models.UniqueConstraint(
                fields=['kontakt', 'art'],
                condition=models.Q(ist_standard=True),
                name='ein_standardkontakt_je_kunde_und_art',
                violation_error_message=(
                    'Je Art kann nur ein Eintrag der Standard sein. Bitte '
                    'das Häkchen bei den übrigen Zeilen derselben Art '
                    'entfernen.'),
            ),
            models.UniqueConstraint(
                fields=['ansprechpartner', 'art'],
                condition=models.Q(ist_standard=True),
                name='ein_standardkontakt_je_person_und_art',
                violation_error_message=(
                    'Je Art kann nur ein Eintrag der Standard sein. Bitte '
                    'das Häkchen bei den übrigen Zeilen derselben Art '
                    'entfernen.'),
            ),
        ]

    def __str__(self) -> str:
        if self.bezeichnung:
            return f'{self.get_art_display()} {self.bezeichnung}: {self.wert}'
        return f'{self.get_art_display()}: {self.wert}'

    def save(self, *args, **kwargs):
        """Der erste Kontaktweg einer Art wird Standard, wie bei ``Adresse``.

        Entfällt bei ``standard_festgelegt``, weil dann das Formset den
        Standard setzt (``EinStandardFormSet.save``)."""
        if not self.ist_standard and not getattr(self, 'standard_festgelegt', False):
            geschwister = Kontaktweg.objects.filter(
                art=self.art, ist_standard=True)
            if self.kontakt_id:
                geschwister = geschwister.filter(kontakt_id=self.kontakt_id)
            elif self.ansprechpartner_id:
                geschwister = geschwister.filter(
                    ansprechpartner_id=self.ansprechpartner_id)
            else:
                geschwister = geschwister.none()
            if self.pk:
                geschwister = geschwister.exclude(pk=self.pk)
            if not geschwister.exists():
                self.ist_standard = True
        return super().save(*args, **kwargs)

    def clean(self):
        """Validiert bei der Art E-Mail eine E-Mail-Adresse.

        Die Regel zum Träger steht nur als Constraint, weil Django im Inline
        den Fremdschlüssel erst beim Speichern setzt und ``clean()`` jede neue
        Zeile ohne Träger sähe. ``full_clean()`` prüft den Constraint, sobald
        seine Felder gefüllt sind.
        """
        if self.art == Kontaktart.EMAIL and self.wert:
            EmailValidator(
                message='Das ist keine gültige E-Mail-Adresse.')(self.wert)


class Projekt(MitVersion):
    """Vorhaben, das Angebote, Aufträge und Rechnungen zusammenfasst.

    Genau ein Kunde, damit das Projekt den Empfänger bestimmt. Die Nummer
    ist ein Vorschlag, weil Projektnummern oft extern vorgegeben sind
    (Bauherr, Ausschreibung).
    """

    nummer = models.CharField(
        'Projektnummer', max_length=30, unique=True, blank=True,
        help_text='Vorgeschlagen wird die nächste freie Nummer des Jahres. '
                  'Frei überschreibbar, muss aber eindeutig sein; '
                  'z. B. "2026-042" oder "BV-Halle-Nord".',
    )
    bezeichnung = models.CharField(
        'Bezeichnung', max_length=200,
        help_text='Kurz und wiedererkennbar; erscheint in jeder Auswahlliste.',
    )
    beschreibung = models.TextField(
        'Beschreibung', blank=True, default='',
        help_text='Nur zur internen Erläuterung; steht auf keinem Beleg.',
    )
    kunde = models.ForeignKey(
        Kontakt,
        on_delete=models.PROTECT,
        related_name='projekte',
        limit_choices_to={'ist_kunde': True},
        verbose_name='Kunde',
        help_text='Der Auftraggeber. Belege dieses Projekts übernehmen '
                  'seine Anschrift, solange am Beleg selbst kein anderer '
                  'Kunde steht.',
    )
    # Boolean, weil nur feststeht, dass ein abgeschlossenes Projekt nicht
    # mehr in der Auswahl erscheint. Verworfen: ein Status mit Stufen.
    abgeschlossen = models.BooleanField(
        'Abgeschlossen', default=False,
        help_text='Abgeschlossene Projekte stehen in den Auswahllisten '
                  'nicht mehr zur Wahl. Ihre Belege bleiben unberührt.',
    )
    notiz = models.TextField('Notiz', blank=True, default='')

    class Meta:
        verbose_name = 'Projekt'
        verbose_name_plural = 'Projekte'
        ordering = ['-nummer']

    def __str__(self) -> str:
        return f'{self.nummer} {self.bezeichnung}'

    def save(self, *args, **kwargs):
        """Vergibt die Nummer, wenn keine eingetragen ist, wie ``Kunde.save``."""
        if not self.nummer:
            with transaction.atomic():
                self.nummer = naechste_projektnummer()
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)
