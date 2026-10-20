"""Import und Export der Erfassung als Tabelle (django-import-export).

Der Import legt nur neue Zeilen an, weil eine Erfassungszeile keine Nummer
hat, über die eine fremde Tabelle sie zuordnen könnte, und abgerechnete
Zeilen nicht änderbar sind. ``skip_row`` überspringt Zeilen, die es mit Tag,
Person, Projekt, Grundlage, Uhrzeiten, Menge und Beschreibung bereits gibt,
und meldet sie; ein zweiter Lauf erzeugt so keine Duplikate.

Es gelten die Regeln der Maske: ``full_clean`` prüft Datum, Uhrzeiten,
Grundlage und Umfang (``Erfassungszeile.clean``). Die zusätzlichen Regeln
von ``zeile_erfassen`` (laufendes Projekt, kontierbare Leistung) und die
Rechte des Formulars prüft ``import_instance``.

Die Spalten verwenden fachliche Schlüssel: Projekt- und Auftragsnummer, Pos.
aus dem Auftrag, Artikelnummer aus dem Katalog, Benutzername der Person.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from import_export import fields, resources, widgets

from faktura.models import Belegposition, BelegStatus, BelegTyp, Katalogposition, Projekt
from faktura.ressourcen import KatalogpositionResource, KommaDezimalWidget

from .admin.gemeinsam import RECHT_FREMDE
from .models import Erfassungszeile
from .services.erfassen import _art_von, _menge


class ProjektWidget(widgets.ForeignKeyWidget):
    """Projekt über seine Nummer, mit verständlicher Meldung, wenn es fehlt."""

    def __init__(self):
        super().__init__(Projekt, 'nummer')

    def clean(self, value, row=None, **kwargs):
        if not str(value or '').strip():
            raise ValueError('Ohne Projektnummer weiß niemand, worauf '
                             'gearbeitet wurde.')
        try:
            return super().clean(str(value).strip(), row, **kwargs)
        except Projekt.DoesNotExist:
            raise ValueError(f'Projekt "{value}" gibt es nicht.') from None


class PersonWidget(widgets.ForeignKeyWidget):
    """Person über den Benutzernamen, ersatzweise über "Vorname Nachname",
    wenn eindeutig. Leer bedeutet der importierende Benutzer."""

    def __init__(self):
        super().__init__(get_user_model(), 'username')

    def clean(self, value, row=None, **kwargs):
        text = str(value or '').strip()
        if not text:
            return None
        Person = get_user_model()
        person = Person.objects.filter(username__iexact=text).first()
        if person is not None:
            return person
        vorname, _, nachname = text.rpartition(' ')
        treffer = list(Person.objects.filter(
            first_name__iexact=vorname, last_name__iexact=nachname)[:2])
        if len(treffer) == 1:
            return treffer[0]
        if treffer:
            raise ValueError(f'"{text}" gibt es mehrfach; bitte den '
                             f'Anmeldenamen eintragen.')
        raise ValueError(f'Person "{text}" gibt es nicht.')


class LeistungWidget(widgets.ForeignKeyWidget):
    """Katalogleistung über die Artikelnummer, ohne Nummer über die
    Bezeichnung, wie beim Katalogimport."""

    def __init__(self):
        super().__init__(Katalogposition, 'nummer')

    def clean(self, value, row=None, **kwargs):
        text = str(value or '').strip()
        if not text:
            return None
        treffer = list(Katalogposition.objects.filter(
            Q(nummer=text) | Q(bezeichnung__iexact=text))[:2])
        if len(treffer) == 1:
            return treffer[0]
        if treffer:
            raise ValueError(f'"{text}" passt auf mehrere Katalogleistungen '
                             f'- bitte die Artikelnummer eintragen.')
        raise ValueError(f'Leistung "{text}" steht nicht im Katalog.')

    def render(self, value, obj=None, **kwargs):
        if value is None:
            return ''
        return value.nummer or value.bezeichnung


class AuftragspositionWidget(widgets.ForeignKeyWidget):
    """Auftragsposition über zwei Spalten: ``auftrag`` (Belegnummer) und
    ``position`` (Pos., auch als Ordnungszahl wie "01.01.0010"). Nur
    festgeschriebene Aufträge, wie in der Maske."""

    def __init__(self):
        super().__init__(Belegposition, 'position')

    def clean(self, value, row=None, **kwargs):
        position = str(value or '').strip()
        auftrag = str((row or {}).get('auftrag') or '').strip()
        if not position and not auftrag:
            return None
        if not (position and auftrag):
            raise ValueError('Auftrag und Position gehören zusammen; '
                             'eines allein trifft keine Auftragsposition.')
        treffer = list(Belegposition.objects.filter(
            beleg__typ=BelegTyp.AUFTRAG,
            beleg__status=BelegStatus.FESTGESCHRIEBEN,
            beleg__nummer=auftrag, position=position,
        ).select_related('beleg')[:2])
        if len(treffer) == 1:
            return treffer[0]
        if treffer:
            raise ValueError(f'Pos. {position} steht in {auftrag} mehrfach.')
        raise ValueError(f'Pos. {position} gibt es in keinem '
                         f'festgeschriebenen Auftrag {auftrag}.')


class ErfassungszeileResource(resources.ModelResource):
    """Resource der Erfassung, eine Tabellenzeile je Erfassungszeile.

    ``user`` übergibt der Admin in ``import_data`` (Probelauf und echter
    Lauf); daraus ergeben sich die Vorgabe für die Person und die
    Rechteprüfung.
    """

    datum = fields.Field(column_name='datum', attribute='datum',
                         widget=widgets.DateWidget())
    person = fields.Field(column_name='person', attribute='benutzer',
                          widget=PersonWidget())
    projekt = fields.Field(column_name='projekt', attribute='projekt',
                           widget=ProjektWidget())
    # Nur für den Export; beim Import liest das Widget der Position die
    # Spalte selbst.
    auftrag = fields.Field(column_name='auftrag', readonly=True)
    position = fields.Field(column_name='position',
                            attribute='auftragsposition',
                            widget=AuftragspositionWidget())
    leistung = fields.Field(column_name='leistung', attribute='leistung',
                            widget=LeistungWidget())
    # Ohne Sekunden, wie in Tabellen üblich.
    von = fields.Field(column_name='von', attribute='von',
                       widget=widgets.TimeWidget(format='%H:%M'))
    bis = fields.Field(column_name='bis', attribute='bis',
                       widget=widgets.TimeWidget(format='%H:%M'))
    menge = fields.Field(column_name='menge', attribute='menge',
                         widget=KommaDezimalWidget())

    class Meta:
        model = Erfassungszeile
        fields = ('datum', 'person', 'projekt', 'auftrag', 'position',
                  'leistung', 'von', 'bis', 'menge', 'beschreibung',
                  'abrechenbar')
        export_order = fields
        # Immer eine neue Zeile, siehe Modul-Docstring.
        force_init_instance = True
        # Dieselben Prüfungen wie in der Maske.
        clean_model_instances = True
        report_skipped = True

    def dehydrate_auftrag(self, zeile):
        position = zeile.auftragsposition
        return position.beleg.nummer if position is not None else ''

    def before_import_row(self, row, **kwargs):
        """Liest Ja/Nein als bool; leer bedeutet abrechenbar."""
        if 'abrechenbar' in row:
            wert = row['abrechenbar']
            row['abrechenbar'] = (True if str(wert or '').strip() == ''
                                  else KatalogpositionResource._wahrheit(wert))

    def import_instance(self, instance, row, **kwargs):
        """Liest die Zeile und prüft die Regeln außerhalb von ``full_clean``.

        Die Fehler einer Zeile werden gesammelt gemeldet, damit sie in einem
        Durchgang korrigiert werden können.
        """
        fehler = {}
        try:
            super().import_instance(instance, row, **kwargs)
        except ValidationError as e:
            fehler = e.update_error_dict(fehler)

        nutzer = kwargs.get('user')
        darf_fremde = nutzer is not None and nutzer.has_perm(RECHT_FREMDE)

        if instance.benutzer_id is None and nutzer is not None:
            instance.benutzer = nutzer
        if (instance.benutzer_id and nutzer is not None and not darf_fremde
                and instance.benutzer_id != nutzer.pk):
            fehler.setdefault('person', []).append(
                'Für andere Personen erfasst nur, wer das Recht dazu hat.')
        # Wie im Formular: "abrechenbar" setzen darf nur, wer für andere
        # erfasst.
        if not instance.abrechenbar and not darf_fremde:
            fehler.setdefault('abrechenbar', []).append(
                'Ohne Berechnung erfasst nur, wer für andere erfassen darf.')

        # Wie ``zeile_erfassen``.
        if instance.projekt_id and instance.projekt.abgeschlossen:
            fehler.setdefault('projekt', []).append(
                f'{instance.projekt} ist abgeschlossen. Darauf wird nichts '
                f'mehr kontiert.')
        if instance.leistung_id and not instance.leistung.kontierbar:
            fehler.setdefault('leistung', []).append(
                f'"{instance.leistung}" ist im Katalog nicht für die '
                f'Erfassung freigegeben.')

        instance.menge = _menge(
            _art_von(instance.leistung, instance.auftragsposition),
            instance.menge)

        if fehler:
            raise ValidationError(fehler)

    def skip_row(self, instance, original, row, import_validation_errors=None):
        """Überspringt Zeilen, die es genau so bereits gibt, damit ein
        zweiter Lauf derselben Datei keine Duplikate erzeugt."""
        if import_validation_errors:
            return False
        return Erfassungszeile.objects.filter(
            datum=instance.datum, benutzer_id=instance.benutzer_id,
            projekt_id=instance.projekt_id,
            auftragsposition_id=instance.auftragsposition_id,
            leistung_id=instance.leistung_id,
            von=instance.von, bis=instance.bis, menge=instance.menge,
            beschreibung=instance.beschreibung,
        ).exists()
