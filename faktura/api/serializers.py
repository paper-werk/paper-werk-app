"""Wie ein Beleg über die Schnittstelle aussieht.

Zwei Fassungen: Die Liste trägt, was ein Archivierungslauf zum Einordnen
braucht, die Einzelauskunft zusätzlich die Positionen.

Geldbeträge sind Zeichenketten: Eine JSON-Zahl wird in JavaScript zum
``float`` und verliert die Genauigkeit des ``DecimalField``
(``COERCE_DECIMAL_TO_STRING`` in den Settings).
"""

from rest_framework import serializers

from core.optimistic_locking import FELD
from faktura import services
from faktura.models import (
    Adresse,
    Ansprechpartner,
    Beleg,
    Belegposition,
    Kontakt,
    Projekt,
)
from faktura.models import steuersatz as steuersatz_tabelle

from .anbindung import BelegAnbindungSerializer


class BelegpositionSerializer(serializers.ModelSerializer):
    """Eine Zeile des Belegs, mit ihrer eigenen Summe.

    ``summe`` steht dabei, weil je Position gerundet und danach summiert
    wird. Wer selbst nachrechnet, käme sonst auf einen anderen Betrag.
    """

    steuersatz = serializers.SerializerMethodField()
    summe = serializers.SerializerMethodField()

    class Meta:
        model = Belegposition
        fields = [
            'position', 'bezeichnung', 'menge', 'einheit',
            'einzelpreis', 'steuersatz', 'summe',
        ]

    def get_steuersatz(self, position: Belegposition) -> str:
        return steuersatz_tabelle.anzeige(position.steuersatz)

    def get_summe(self, position: Belegposition) -> str:
        return str(services.positionssumme(
            menge=position.menge, einzelpreis=position.einzelpreis,
        ))


class SummenMixin:
    """Die Summen eines Belegs, gerechnet vom Service. Ein zweiter
    Rechenweg hier ginge irgendwann um einen Cent auseinander."""

    def get_summen(self, beleg: Beleg) -> dict:
        summen = services.belegsummen(beleg)
        return {
            'netto': str(summen.netto),
            'steuer': str(summen.steuer),
            'brutto': str(summen.brutto),
            'nach_steuersatz': [
                {
                    'satz': str(anteil.satz),
                    'netto': str(anteil.netto),
                    'steuer': str(anteil.steuer),
                }
                for anteil in summen.anteile
            ],
        }


class BelegListeSerializer(SummenMixin, serializers.ModelSerializer):
    """Die Fassung für Listen und Archivierungsläufe."""

    typ = serializers.CharField(source='get_typ_display', read_only=True)
    typ_kennung = serializers.CharField(source='typ', read_only=True)
    status = serializers.CharField(source='get_status_display', read_only=True)
    status_kennung = serializers.CharField(source='status', read_only=True)

    # Die fachlichen Nummern statt der Datenbankschlüssel: Das Archiv kennt
    # "2026-042", nicht die Zeilennummer 17.
    kunde = serializers.CharField(source='kunde.nummer', default=None, read_only=True)
    kunde_name = serializers.CharField(source='kunde.name', default=None, read_only=True)
    projekt = serializers.CharField(source='projekt.nummer', default=None, read_only=True)
    projekt_bezeichnung = serializers.CharField(
        source='projekt.bezeichnung', default=None, read_only=True)

    summen = serializers.SerializerMethodField()
    archiviert = serializers.SerializerMethodField()
    ist_wertbeleg = serializers.BooleanField(read_only=True)
    # Zusagen der Archiv-Anbindung (anbindung.py), für Workflows, die auf
    # Ereignisse reagieren.
    brutto = serializers.SerializerMethodField()
    # In der Einzelauskunft gefüllt, in der Liste null (wie in der App).
    projektstand = serializers.SerializerMethodField()
    get_projektstand = BelegAnbindungSerializer.get_projektstand

    class Meta:
        model = Beleg
        fields = [
            'id', 'nummer', 'typ', 'typ_kennung', 'status', 'status_kennung',
            'belegdatum', 'steuerliches_leistungsdatum', 'leistungsdatum',
            'leistungsdatum_bis', 'faellig_am',
            'betreff',
            'kunde', 'kunde_name', 'projekt', 'projekt_bezeichnung',
            'empfaenger_name', 'empfaenger_ort',
            'ist_wertbeleg', 'summen',
            'festgeschrieben_am', 'archiviert', 'paperless_id', 'archiviert_am',
            'erechnungsprofil', 'xml_sha256',
            'vorgaenger_id', 'brutto', FELD,
            'projekt_id', 'projektstand',
        ]

    # ``ist_wertbeleg`` sagt, ob die Summen eine Aussage sind: Ein
    # Lieferschein zeigt in Admin und PDF keine Preise. Wer die Summen
    # weiterreicht (etwa als Betragsfeld im Archiv), prüft das hier.

    def get_brutto(self, beleg: Beleg) -> str:
        """Wie ``summen.brutto``, als eigenes Feld der Belegauskunft."""
        return f'{services.belegsummen(beleg).brutto:.2f}'

    def get_archiviert(self, beleg: Beleg) -> bool:
        """Ein Wahrheitswert neben ``paperless_id``, in n8n leichter zu
        verzweigen als "Zahl oder null"."""
        return beleg.paperless_id is not None


class BelegSerializer(BelegListeSerializer):
    """Die Einzelauskunft: alles aus der Liste, dazu die Positionen und der
    Projektstand der Belegauskunft der App."""

    positionen = BelegpositionSerializer(many=True, read_only=True)
    vorgaenger = serializers.CharField(source='vorgaenger.nummer', default=None, read_only=True)

    class Meta(BelegListeSerializer.Meta):
        fields = BelegListeSerializer.Meta.fields + [
            'empfaenger', 'empfaenger_strasse', 'empfaenger_plz',
            'empfaenger_land', 'empfaenger_ust_id',
            'zahlungsziel_tage', 'kopftext', 'fusstext',
            'leitweg_id', 'bestellnummer', 'mahnstufe', 'empfaenger_email',
            'vorgaenger', 'positionen',
            'pdf_sha256', 'vorlagenversion',
        ]


class ArchivvermerkSerializer(serializers.Serializer):
    """Eingabe für ``POST /belege/{id}/archiviert/``.

    Ein Serializer statt Handprüfung, damit die Eingabe in der
    Schnittstellenbeschreibung steht.
    """

    paperless_document_id = serializers.IntegerField(
        min_value=1,
        help_text='Nummer des Dokuments in Paperless, unter der der Beleg '
                  'dort abgelegt wurde.',
    )


class FestschreibenEingabeSerializer(serializers.Serializer):
    """Eingabe für ``POST /belege/{id}/festschreiben/``, freiwillig."""

    mengen_bestaetigt = serializers.BooleanField(
        default=False,
        help_text='Erlaubt, über den Auftrag hinaus abzurechnen. Ohne diese '
                  'Bestätigung antwortet die Schnittstelle mit 409, wenn '
                  'die Rechnung zusammen mit den festgeschriebenen mehr '
                  'abrechnet, als eine Auftragsposition beauftragt hat. '
                  'Die Meldung nennt die Positionen und Zahlen.',
    )


class ProjektSerializer(serializers.ModelSerializer):
    """Ein Projekt, wie das Archiv es braucht.

    Der Kunde mit Nummer und Namen. Der Name landet in Paperless als
    Korrespondent.
    """

    kunde = serializers.CharField(source='kunde.nummer', read_only=True)
    kunde_name = serializers.CharField(source='kunde.name', read_only=True)

    class Meta:
        model = Projekt
        fields = [
            'nummer', 'bezeichnung', 'beschreibung',
            'kunde', 'kunde_name', 'abgeschlossen',
        ]


class ProjekttrefferSerializer(serializers.Serializer):
    """Ein Fund der Auflösung, mit der Angabe wie sicher er ist."""

    nummer = serializers.CharField(source='projekt.nummer')
    bezeichnung = serializers.CharField(source='projekt.bezeichnung')
    kunde = serializers.CharField(source='projekt.kunde.nummer')
    kunde_name = serializers.CharField(source='projekt.kunde.name')
    abgeschlossen = serializers.BooleanField(source='projekt.abgeschlossen')
    fundstelle = serializers.CharField(
        help_text='In welchem Feld der gesuchte Text steckte: nummer, '
                  'bezeichnung oder kunde.')
    guete = serializers.CharField(
        help_text='"exakt" bei vollständiger Übereinstimmung der '
                  'Projektnummer, sonst "teilweise".')


class AufloesungSerializer(serializers.Serializer):
    """Die Antwort der unscharfen Suche.

    Auf ``eindeutig`` verzweigt der Ablauf: wahr heißt zuordnen, falsch
    vorlegen. Ausdrücklich, statt es jeden Aufrufer aus der Trefferzahl
    ableiten zu lassen.
    """

    eindeutig = serializers.BooleanField()
    treffer = ProjekttrefferSerializer(many=True)


class BelegartsummeSerializer(serializers.Serializer):
    anzahl = serializers.IntegerField()
    netto = serializers.CharField()
    brutto = serializers.CharField()


class ProjektakteSerializer(serializers.Serializer):
    """Die Auswertung eines Vorhabens: Belege und Summen an einer Stelle -
    für den Projektakte-Export, der die Archivdokumente schon kennt."""

    projekt = ProjektSerializer()
    belege = BelegListeSerializer(many=True)
    je_belegart = serializers.DictField(child=BelegartsummeSerializer())
    fakturiert_netto = serializers.CharField()
    fakturiert_brutto = serializers.CharField()
    angeboten_netto = serializers.CharField()


class AnsprechpartnerSerializer(serializers.ModelSerializer):
    """Ein Mensch beim Kunden.

    Ohne Notiz: Ein Freitext über eine natürliche Person gehört nicht an
    Automatisierungsläufe. Zum Adressieren reichen Name, Anrede, Adresse.
    """

    name = serializers.CharField(read_only=True)
    briefanrede = serializers.CharField(read_only=True)
    email = serializers.CharField(read_only=True)
    telefon = serializers.CharField(read_only=True)

    class Meta:
        model = Ansprechpartner
        fields = ['name', 'anrede', 'briefanrede', 'funktion',
                  'email', 'telefon', 'ist_standard']


class AdresseSerializer(serializers.ModelSerializer):
    anschrift = serializers.CharField(read_only=True)

    class Meta:
        model = Adresse
        fields = ['verwendung', 'bezeichnung', 'zusatz', 'strasse', 'plz',
                  'ort', 'land', 'ist_standard', 'anschrift']


class KundeSerializer(serializers.ModelSerializer):
    """Der Kunde nach außen: flach, mit den vollständigen Listen daneben.

    ``strasse``, ``plz``, ``ort``, ``land``, ``email`` sind Eigenschaften,
    die aus Standardadresse und Standard-Kontaktweg lesen (daher
    ``ReadOnlyField``). Die n8n-Läufe, die Korrespondenten nach Paperless
    spiegeln, lesen genau diese Namen.
    """

    anschrift = serializers.CharField(source='anschriftfeld', read_only=True)
    strasse = serializers.ReadOnlyField()
    plz = serializers.ReadOnlyField()
    ort = serializers.ReadOnlyField()
    land = serializers.ReadOnlyField()
    email = serializers.ReadOnlyField()
    telefon = serializers.ReadOnlyField()
    adressen = AdresseSerializer(many=True, read_only=True)
    ansprechpartner = AnsprechpartnerSerializer(many=True, read_only=True)

    class Meta:
        model = Kontakt
        fields = [
            'nummer', 'name', 'strasse', 'plz', 'ort', 'land',
            'email', 'telefon', 'ust_id', 'zahlungsziel_tage', 'aktiv',
            'anschrift', 'adressen', 'ansprechpartner',
        ]


class KontaktSerializer(KundeSerializer):
    """Wie ein Kunde, dazu die Rollen und die eigene Kundennummer beim
    Kontakt."""

    rollen = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta(KundeSerializer.Meta):
        fields = [*KundeSerializer.Meta.fields, 'rollen', 'ist_kunde',
                  'ist_lieferant', 'ist_partner', 'ist_interessent',
                  'eigene_kundennummer']


class FestschreibungSerializer(BelegSerializer):
    """Die Antwort auf ``POST /belege/{id}/festschreiben/``.

    Der festgeschriebene Beleg, dazu ``hinweise``: die Warnungen, die der
    Admin als Meldung zeigt (Ausdruck und E-Rechnung nennen verschiedene
    Empfänger). Was der Aufrufer damit tut, ist seine Sache.
    """

    hinweise = serializers.SerializerMethodField()

    class Meta(BelegSerializer.Meta):
        fields = BelegSerializer.Meta.fields + ['hinweise']

    def get_hinweise(self, beleg: Beleg) -> list[str]:
        return services.empfaenger_abweichungen(beleg)
