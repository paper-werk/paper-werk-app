"""Import und Export als Tabelle: Leistungskatalog, Kunden, Projekte.

Für vorhandene Kataloge und Kundenlisten (Excel, Altsystem) und
Preisänderungen in größerer Zahl. Ob eine Zeile neu oder vorhanden ist,
bestimmt je Tabelle ``import_id_fields``.

Belege und Fremdleistungen sind ausgenommen, weil sie an Nummernkreisen und
Festschreibung hängen. Erfasste Stunden nur als neue Zeilen, siehe
``erfassung/ressourcen.py``.
"""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ObjectDoesNotExist
from import_export import fields, resources, widgets

from .models import (
    STEUERFREI,
    Katalogposition,
    Kontakt,
    Leistungsart,
    Projekt,
    Steuersatz,
)
from .models import steuersatz as steuersatz_tabelle


class KommaDezimalWidget(widgets.DecimalWidget):
    """Parst "85,00" wie "85.00", für Dateien aus einer deutschen
    Tabellenkalkulation.

    Tausenderpunkte werden nur bei eindeutigem Format erkannt: "1.250,00"
    ist eindeutig, "1.250" nicht und wird als ungültig gemeldet.
    """

    def clean(self, value, row=None, **kwargs):
        if isinstance(value, str) and ',' in value:
            text = value.strip().replace('.', '').replace(',', '.')
            try:
                return Decimal(text)
            except InvalidOperation:
                pass
        return super().clean(value, row, **kwargs)


class LeerIstNichtsWidget(widgets.CharWidget):
    """Leere Zelle als NULL, weil zwei Leerstrings im Unique-Index
    kollidieren, zwei NULL nicht."""

    def clean(self, value, row=None, **kwargs):
        wert = super().clean(value, row, **kwargs)
        if isinstance(wert, str):
            wert = wert.strip()
        return wert or None


class KundenWidget(widgets.ForeignKeyWidget):
    """Sucht den Kunden über seine Nummer; die Fehlermeldung enthält die
    fehlende Nummer (Django: "Kunde matching query does not exist")."""

    def clean(self, value, row=None, **kwargs):
        try:
            return super().clean(value, row, **kwargs)
        except (Kontakt.DoesNotExist, ValueError, ObjectDoesNotExist):
            raise ValueError(
                f'Kundennummer "{value}" gibt es nicht. Erst die Kunden '
                f'einlesen, dann die Projekte.'
            ) from None


class KatalogpositionResource(resources.ModelResource):
    """Leistungskatalog als Tabelle.

    Zuordnung über die Artikelnummer, ohne Nummer über die Bezeichnung.
    Verworfen: die Datenbank-ID, die in fremden Preislisten fehlt; ein
    zweiter Import verdoppelte den Katalog.
    """

    class Meta:
        model = Katalogposition
        import_id_fields = ('nummer', 'bezeichnung')
        fields = ('nummer', 'bezeichnung', 'langtext', 'einheit',
                  'einzelpreis', 'steuersatz', 'art', 'kontierbar')
        export_order = fields
        # Zeigt bei Preisänderungen die Zahl geänderter und unveränderter
        # Zeilen.
        skip_unchanged = True
        report_skipped = True

    nummer = fields.Field(
        column_name='nummer',
        attribute='nummer',
        widget=LeerIstNichtsWidget(),
    )

    einzelpreis = fields.Field(
        column_name='einzelpreis',
        attribute='einzelpreis',
        widget=KommaDezimalWidget(),
    )

    def before_import_row(self, row, **kwargs):
        """Parst Steuersatz und Art auch als Text ("19 %", "Stunde") und
        "kontierbar" als Ja/Nein."""
        if 'steuersatz' in row:
            row['steuersatz'] = self._steuersatz(row['steuersatz'])
        if 'art' in row:
            row['art'] = self._art(row['art'])
        if 'kontierbar' in row:
            row['kontierbar'] = self._wahrheit(row['kontierbar'])

    @staticmethod
    def _steuersatz(wert) -> str:
        """Parst "19 %", "19", "19,00" und "voll" als denselben Satz. Zahlen
        mit Komma oder Punkt (Excel verwendet das Trennzeichen des Systems);
        Wörter werden mit der Bezeichnung in ``Steuersatz`` verglichen.
        "voll" ist die Vorgabe, "frei" 0 %, leer die Vorgabe. Nicht Erkanntes
        bleibt unverändert und schlägt bei der Validierung der Zeile fehl."""
        text = str(wert or '').strip().lower().replace('%', '').strip()
        if not text or text == 'voll':
            return steuersatz_tabelle.vorgabe()
        if text == 'frei':
            return STEUERFREI
        try:
            return steuersatz_tabelle.als_wert(text.replace(',', '.'))
        except InvalidOperation:
            pass
        treffer = Steuersatz.objects.filter(bezeichnung__iexact=text).first()
        return treffer.wert if treffer else wert

    @staticmethod
    def _art(wert) -> str:
        text = str(wert or '').strip().lower()
        bekannt = {
            'zeit': Leistungsart.ZEIT, 'stunde': Leistungsart.ZEIT,
            'stunden': Leistungsart.ZEIT, 'std': Leistungsart.ZEIT,
            'menge': Leistungsart.MENGE, 'stück': Leistungsart.MENGE,
            'stueck': Leistungsart.MENGE,
            'pauschale': Leistungsart.PAUSCHALE,
            'pauschal': Leistungsart.PAUSCHALE,
        }
        return bekannt.get(text, wert or Leistungsart.MENGE)

    @staticmethod
    def _wahrheit(wert) -> bool:
        if isinstance(wert, bool):
            return wert
        return str(wert or '').strip().lower() in {
            'ja', 'j', 'true', 'wahr', '1', 'x', 'y', 'yes'}


# ── Kunden und Projekte ──────────────────────────────────────────────────
#
# Exportiert wird der Datensatz ohne Relationen. Einzige Ausnahme ist der
# Kunde eines Projekts, als Kundennummer ("K-1000"), damit die Datei wieder
# importierbar ist.


#: Flache Anschrift- und Kontaktspalten des Kundenexports; am Modell
#: Properties auf Standardadresse und Standard-Kontaktwege.
FLACHE_KUNDENSPALTEN = ('strasse', 'plz', 'ort', 'land', 'email', 'telefon')


class KontaktResource(resources.ModelResource):
    """Kundenstamm als flache Tabelle mit einer Zeile je Kunde, wie eine
    Adressliste aus Excel, obwohl das Modell vier Tabellen hat.

    Enthalten sind nur die Standardwerte (Standardadresse, Standard-E-Mail
    und -Telefon); weitere Anschriften und Personen werden im Admin
    gepflegt. Beim Import aktualisiert ``after_save_instance`` Anschrift und
    Kontaktwege: Vorhandenes wird geändert, Fehlendes angelegt, nichts
    gelöscht; eine leere Zelle bedeutet "unbekannt".

    Zuordnung über die Kundennummer; ohne Nummer vergibt ``save()`` eine.
    """

    nummer = fields.Field(
        column_name='nummer',
        attribute='nummer',
        widget=LeerIstNichtsWidget(),
    )

    # Gelesen über die Properties am Modell (``readonly``, weil sie keinen
    # Setter haben). Geschrieben in ``_stammdaten_nachziehen``.
    strasse = fields.Field(column_name='strasse', attribute='strasse', readonly=True)
    plz = fields.Field(column_name='plz', attribute='plz', readonly=True)
    ort = fields.Field(column_name='ort', attribute='ort', readonly=True)
    land = fields.Field(column_name='land', attribute='land', readonly=True)
    email = fields.Field(column_name='email', attribute='email', readonly=True)
    telefon = fields.Field(column_name='telefon', attribute='telefon', readonly=True)

    class Meta:
        model = Kontakt
        import_id_fields = ('nummer',)
        fields = ('nummer', 'name', 'strasse', 'plz', 'ort', 'land',
                  'email', 'telefon', 'ust_id', 'zahlungsziel_tage',
                  'kaeuferreferenz')
        export_order = fields
        # Ohne ``skip_unchanged``, weil eine geänderte Straße in einer
        # Kind-Tabelle steht, die django-import-export nicht vergleicht; die
        # Zeile gälte als unverändert.
        skip_unchanged = False
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        """Leeres Land wird 'DE', weil BT-55 der E-Rechnung Pflicht ist."""
        if not (row.get('land') or '').strip():
            row['land'] = 'DE'

    def after_save_instance(self, instance, row, **kwargs):
        """Aktualisiert Anschrift und Kontaktwege nach dem Speichern, weil ein
        neuer Kunde vorher keinen Primärschlüssel hat. Nicht im Dry Run, den
        die Vorschau des Admins verwendet."""
        if kwargs.get('dry_run'):
            return
        _stammdaten_nachziehen(instance, row)


def _stammdaten_nachziehen(kunde, zeile) -> None:
    """Schreibt Anschrift, E-Mail und Telefon aus einer flachen Zeile:
    ändert Vorhandenes, legt Fehlendes an, löscht nichts."""
    from .models import Adresse, Adressverwendung, Kontaktart, Kontaktweg

    def wert(name: str) -> str:
        return str(zeile.get(name) or '').strip()

    strasse, plz, ort = wert('strasse'), wert('plz'), wert('ort')
    if strasse or plz or ort:
        adresse = kunde.adressen.filter(ist_standard=True).first()
        if adresse is None:
            adresse = Adresse(kontakt=kunde,
                              verwendung=Adressverwendung.RECHNUNG,
                              ist_standard=True)
        adresse.strasse = strasse or adresse.strasse
        adresse.plz = plz or adresse.plz
        adresse.ort = ort or adresse.ort
        adresse.land = wert('land') or adresse.land or 'DE'
        adresse.save()

    for spalte, art in (('email', Kontaktart.EMAIL),
                        ('telefon', Kontaktart.TELEFON)):
        neu = wert(spalte)
        if not neu:
            continue
        kontakt = kunde.kontaktwege.filter(art=art, ist_standard=True).first()
        if kontakt is None:
            kontakt = Kontaktweg(kontakt=kunde, art=art, ist_standard=True)
        kontakt.wert = neu
        kontakt.save()


class ProjektResource(resources.ModelResource):
    """Projekte als Tabelle, für die Übernahme laufender Vorhaben aus einem
    Altsystem."""

    kunde = fields.Field(
        column_name='kunde',
        attribute='kunde',
        widget=KundenWidget(Kontakt, 'nummer'),
    )

    class Meta:
        model = Projekt
        import_id_fields = ('nummer',)
        fields = ('nummer', 'bezeichnung', 'kunde', 'beschreibung',
                  'abgeschlossen', 'notiz')
        export_order = fields
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        """Parst Ja/Nein wie True/False, das Format von Excel."""
        if 'abgeschlossen' in row:
            row['abgeschlossen'] = KatalogpositionResource._wahrheit(
                row['abgeschlossen'])
