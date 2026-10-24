"""Formulare der Faktura: Belegformular, Positionen, Zwischenseiten.

Vorlagen gelangen auf zwei Wegen in einen Beleg:

* **Leistungskatalog:** Suche über der Positionszeile. JavaScript füllt
  vor, maßgeblich ist ``BelegpositionForm.clean()``; vom Benutzer geänderte
  Felder (``changed_data``) haben Vorrang.
* **Textbausteine:** Menü am Textfeld, das den Text ins Feld kopiert.
  Danach ist es freier Text; die Auswahl wird nicht an den Server
  übertragen.

``forms.Form`` auf Zwischenseiten setzen Unfolds Widgets explizit, weil
Unfold sie nur in einem ModelAdmin austauscht.
"""

import json
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.urls import reverse
from unfold.widgets import (
    UnfoldAdminDecimalFieldWidget,
    UnfoldAdminEmailInputWidget,
    UnfoldAdminSelectWidget,
    UnfoldAdminSingleDateWidget,
    UnfoldAdminTextareaWidget,
    UnfoldAdminTextInputWidget,
    UnfoldBooleanWidget,
)

from . import formate
from .models import (
    Beleg,
    Belegposition,
    Katalogposition,
    Textbaustein,
    TextbausteinVerwendung,
    Zahlungsart,
    Zeilenart,
)
from .models import steuersatz as steuersatz_tabelle
from .positionsnummer import naechste_nummern


def steuersatz_auswahl_eingrenzen(form, *, kurz: bool = False):
    """Macht das Feld ``steuersatz`` eines ModelForms zur Auswahl aus der
    Tabelle: die aktiven Sätze, dazu der gespeicherte, falls dieser
    inzwischen inaktiv ist.

    Das Modellfeld hat keine ``choices`` (siehe ``Belegposition``), der
    ModelForm erzeugt daher ein Textfeld; ersetzt wird es mit Label,
    ``required``, ``disabled`` und Initialwert des ursprünglichen.
    ``initial`` enthält den Callable-Default (``vorgabe``); ohne ihn gilt die
    leere Zeile eines Inline-Formsets als geändert. ``show_hidden_initial``,
    das Django bei einem Callable-Default setzt, bleibt aus, damit wie bei
    einem festen Default mit der Vorgabe verglichen wird. Das Hidden Input
    fehlt in einer im Browser angefügten Zeile."""
    alt = form.fields.get('steuersatz')
    if alt is None:
        return
    aktuell = form.instance.steuersatz if form.instance.pk else None
    form.fields['steuersatz'] = forms.ChoiceField(
        label=alt.label, help_text=alt.help_text, required=alt.required,
        disabled=alt.disabled, initial=alt.initial,
        widget=UnfoldAdminSelectWidget,
        choices=steuersatz_tabelle.angeboten(aktuell, kurz=kurz),
    )


class KatalogpositionForm(forms.ModelForm):
    """Formular des Katalogs, eigenes Formular nur für die Steuersatzauswahl."""

    class Meta:
        model = Katalogposition
        fields = '__all__'  # noqa: DJ007

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        steuersatz_auswahl_eingrenzen(self)


def widget_am_eingabefeld(feld):
    """Widget, das das ``<input>`` oder ``<select>`` rendert.

    Der Admin umgibt Fremdschlüsselfelder mit einem
    ``RelatedFieldWidgetWrapper``, dessen ``__deepcopy__`` die ``attrs`` von
    Wrapper und innerem Widget trennt. Ein ``data-``-Attribut gehört daher an
    das innere Widget.
    """
    return getattr(feld.widget, 'widget', feld.widget)


class MengeWidget(UnfoldAdminDecimalFieldWidget):
    """Menge einer Position ohne nachlaufende Nullen im Feld.

    ``6.000 Std`` wird im Deutschen als sechstausend gelesen. Gekürzt wird
    nur ein gespeicherter Wert (``Decimal``); eine Eingabe, die nach einem
    Validierungsfehler zurückkommt, bleibt unverändert. ``6`` und ``6.000``
    parst Django als denselben Wert (``faktura/tests/test_lokalisierung.py``,
    ``tests/test_browser_positionen.py``, TestWerteInDerMaske).
    """

    def format_value(self, value):
        if isinstance(value, Decimal):
            value = formate.menge_im_feld(value)
        return super().format_value(value)


class BetragWidget(UnfoldAdminDecimalFieldWidget):
    """Geldbetrag in einem Formular mit ``localize=True``.

    Das Feld ist ein ``<input type="number">``, dessen ``value`` einen Punkt
    braucht ("1445.14"); das Komma zeigt der Browser. Mit ``localize=True``
    stünde "1445,14" darin, das der Browser verwirft; das vorbelegte Feld
    bliebe leer (Zahlung vermerken). Geparst wird weiter lokalisiert: Ein
    Wert mit Punkt und zwei Stellen bleibt ein Dezimalpunkt
    (``faktura/tests/test_lokalisierung.py``).
    """

    def format_value(self, value):
        if isinstance(value, Decimal):
            return format(value, 'f')
        return super().format_value(value)


class KatalogsucheWidget(UnfoldAdminSelectWidget):
    """Auswahl einer Katalogposition mit Suche bei Eingabe.

    Das HTML enthält nur die gewählte Position, weil hunderte Leistungen in
    einem Dutzend Zeilen tausende ``<option>`` ergäben, durchsuchbar nur über
    den Namensanfang. Gesucht wird über ``KatalogpositionAdmin.suche``, wie
    in der Katalogliste (Nummer, Bezeichnung, Langtext); die Oberfläche
    richtet katalog_suche.js ein.

    Validiert wird gegen den ganzen Katalog (``queryset`` am Feld); das
    Widget begrenzt nur die Ausgabe.
    """

    def optgroups(self, name, value, attrs=None):
        # Nur Ziffern, weil POST-Daten beliebig sein können und ein Filter
        # mit "abc" auf den Primärschlüssel eine Exception auslöst.
        gewaehlt = [v for v in value if v and str(v).isdigit()]
        self.choices = [('', '')] + [
            (p.pk, str(p))
            for p in Katalogposition.objects.filter(pk__in=gewaehlt)
        ]
        return super().optgroups(name, value, attrs)


class TextfeldMitVorlagen(UnfoldAdminTextareaWidget):
    """Textfeld mit Vorlagenmenü in der Kopfzeile.

    Der gewählte Baustein wird ins Feld kopiert; der Beleg hat keinen
    Fremdschlüssel auf ihn. Das Feld wächst mit dem Inhalt
    (``field-sizing-content``) und ist so breit wie im PDF.
    """

    template_name = 'faktura/widgets/textfeld_mit_vorlagen.html'

    def __init__(self, verwendung, attrs=None, belegart=''):
        #: Verwendung der wählbaren Bausteine (TextbausteinVerwendung).
        self.verwendung = verwendung
        #: Belegart, leer für alle. Der Admin setzt sie je Belegart
        #: (``FormularMixin.formfield_for_dbfield``).
        self.belegart = belegart
        attrs = {**(attrs or {})}
        # Geringe Anfangshöhe, wächst mit dem Inhalt.
        attrs.setdefault('rows', 3)
        attrs['class'] = ' '.join(
            [attrs.get('class', ''), 'field-sizing-content']).strip()
        super().__init__(attrs)

    def get_context(self, name, value, attrs):
        kontext = super().get_context(name, value, attrs)
        # Beim Rendern gelesen, weil Widgets beim Import entstehen und ein
        # neuer Baustein ohne Neustart erscheinen soll.
        kontext['widget']['vorlagen'] = list(
            Textbaustein.fuer(self.verwendung, self.belegart)
            .values('name', 'text')
        )
        return kontext


class NachlassForm(forms.Form):
    """Betrag, Grund und Steuersatz einer Rechnungskorrektur."""

    betrag_netto = forms.DecimalField(
        label='Nachlass netto',
        max_digits=12,
        decimal_places=2,
        min_value=0.01,
        localize=True,
        widget=BetragWidget,
        help_text='Als positiver Betrag angeben; das Vorzeichen setzt das System.',
    )
    grund = forms.CharField(
        label='Grund',
        max_length=300,
        widget=UnfoldAdminTextInputWidget,
        help_text='Erscheint als Positionstext auf dem Beleg, '
                  'z. B. "Nachlass wegen Reklamation".',
    )
    steuersatz = forms.ChoiceField(
        label='Steuersatz',
        choices=steuersatz_tabelle.angeboten,
        initial=steuersatz_tabelle.vorgabe,
        widget=UnfoldAdminSelectWidget,
        help_text='Muss dem Satz der ursprünglichen Leistung entsprechen.',
    )


class NeuausstellungForm(forms.Form):
    """Änderbare Kopfangaben bei der Neuausstellung einer E-Rechnung;
    Stammdaten werden an der Quelle berichtigt."""

    leitweg_id = forms.CharField(
        label='Käuferreferenz / Leitweg-ID',
        max_length=50,
        required=False,
        widget=UnfoldAdminTextInputWidget,
    )
    bestellnummer = forms.CharField(
        label='Bestellnummer des Kunden',
        max_length=50,
        required=False,
        widget=UnfoldAdminTextInputWidget,
    )
    grund = forms.CharField(
        label='Grund',
        widget=UnfoldAdminTextareaWidget(attrs={'rows': 3}),
        help_text='Zum Beispiel die Ablehnung des Portals. Steht dauerhaft '
                  'bei der alten Fassung.',
    )


class VersandForm(forms.Form):
    """Zwischenseite „Versenden". Pflicht ist nur die Adresse; das
    Anschreiben darf leer sein."""

    an = forms.EmailField(
        label='Empfänger',
        widget=UnfoldAdminEmailInputWidget,
    )
    betreff = forms.CharField(
        label='Betreff',
        max_length=200,
        required=False,
        widget=UnfoldAdminTextInputWidget,
    )
    nachricht = forms.CharField(
        label='Nachricht',
        required=False,
        widget=TextfeldMitVorlagen(TextbausteinVerwendung.MAIL,
                                   attrs={'rows': 8}),
    )
    # Kein Feld "Anhang": Die Anhänge folgen aus dem Beleg
    # (``services.versandformat``) und stehen in der Maske über den Buttons.

    # Eine Zwischenseite hat kein ModelAdmin-Media; das Formular liefert das
    # Skript für das Vorlagenmenü, das Template gibt ``{{ form.media }}`` aus.
    class Media:
        js = ['faktura/js/textbaustein_einfuegen.js']

    def __init__(self, *args, belegart: str = '', anlagen=(), **kwargs):
        """``belegart`` für das Vorlagenmenü (eigene Widget-Instanz, weil alle
        Instanzen das Widget der Klasse teilen).

        ``anlagen``: ``(art, titel)`` je anhängbarer Anlage; daraus entsteht
        je eine Checkbox ``anlage_<art>``, standardmäßig aus.
        """
        super().__init__(*args, **kwargs)
        if belegart:
            self.fields['nachricht'].widget = TextfeldMitVorlagen(
                TextbausteinVerwendung.MAIL,
                attrs={'rows': 8},
                belegart=belegart,
            )
        self.anlagenarten = []
        for art, titel in anlagen:
            self.anlagenarten.append(art)
            self.fields[f'anlage_{art}'] = forms.BooleanField(
                label=f'{titel} anhängen', required=False,
                widget=UnfoldBooleanWidget)

    def anzuhaengende_anlagen(self) -> list[str]:
        """Arten der ausgewählten Anlagen."""
        return [art for art in self.anlagenarten
                if self.cleaned_data.get(f'anlage_{art}')]


class BelegForm(forms.ModelForm):
    """Belegformular mit Anschriftfeld und Textfeldern mit Vorlagenmenü."""

    class Meta:
        model = Beleg
        # Nur im Admin verwendet; die Felder bestimmen dessen fieldsets
        # (daher DJ007 unterdrückt).
        fields = '__all__'  # noqa: DJ007
        widgets = {
            # Unfolds Widget explizit, weil ein eigenes ``forms.Textarea``
            # Unfolds Austausch verhindert. Fünf Zeilen wie das Anschriftfeld
            # nach DIN 5008, so schmal wie die übrigen Felder.
            'empfaenger': UnfoldAdminTextareaWidget(
                attrs={'rows': 5, 'class': '!max-w-2xl'},
            ),
            'kopftext': TextfeldMitVorlagen(TextbausteinVerwendung.BELEGTEXT),
            'fusstext': TextfeldMitVorlagen(TextbausteinVerwendung.BELEGTEXT),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Nur beim Anlegen überschreibt das Übernahme-Skript auch Felder mit
        # Default (14 Tage, 'DE'), wie der Server beim Speichern. In der
        # Änderungsansicht überschriebe ein Kundenwechsel sonst die ganze
        # Anschrift. Das Attribut gehört an das innere Widget
        # (``widget_am_eingabefeld``).
        if self.instance.pk is None:
            for name in ('kunde', 'projekt'):
                if name in self.fields:
                    widget_am_eingabefeld(
                        self.fields[name]).attrs['data-neuanlage'] = '1'


class BelegpositionForm(forms.ModelForm):
    """Positionszeile mit Katalogauswahl; die Werte werden kopiert, ohne
    Fremdschlüssel."""

    # Formularfeld ohne Modellfeld, das Unfolds Austausch nicht erfasst;
    # daher das Widget explizit.
    katalog = forms.ModelChoiceField(
        queryset=Katalogposition.objects.all(),
        required=False,
        label='Aus dem Katalog',
        widget=KatalogsucheWidget,
    )

    #: Felder aus dem Katalog, mit denselben Namen im JSON-Endpunkt
    #: (``KatalogpositionAdmin.daten``) und in katalog_uebernehmen.js.
    KATALOGFELDER = ('bezeichnung', 'langtext', 'einheit', 'einzelpreis',
                     'steuersatz')

    class Meta:
        model = Belegposition
        # Siehe BelegForm.
        fields = '__all__'  # noqa: DJ007
        widgets = {
            # Eine Zeile, die mit dem Text wächst (faktura_admin.css). Der
            # Langtext steht ohne Label unter der Positionszeile; der
            # Platzhalter bezeichnet ihn.
            'langtext': UnfoldAdminTextareaWidget(attrs={
                'rows': 1,
                'placeholder': 'Langtext, erscheint im PDF unter der '
                               'Bezeichnung',
            }),
            # Die Zeile zeigt keinen help_text; der Platzhalter nennt die
            # Bedeutung des leeren Felds.
            'zuschlag_auf': UnfoldAdminTextInputWidget(attrs={
                'placeholder': 'leer: alle Leistungen, sonst Titel oder '
                               'Position',
            }),
            # Spinner mit Schrittweite 1.
            'menge': MengeWidget(attrs={'step': '1'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        katalogfeld = widget_am_eingabefeld(self.fields['katalog'])
        katalogfeld.attrs['data-katalog-url'] = reverse(
            'admin:faktura_katalogposition_daten')
        katalogfeld.attrs['data-katalog-suche'] = reverse(
            'admin:faktura_katalogposition_suche')
        # Bezeichnung und Preis werden erst in clean() verlangt, nach der
        # Katalogübernahme. Der Lieferschein hat kein Preisfeld.
        for name in ('bezeichnung', 'einzelpreis'):
            if name in self.fields:
                self.fields[name].required = False
        # Den Initialwert (nächste Nummer nach der höchsten,
        # faktura/positionsnummer.py) setzt das Formset, in einer im Browser
        # angefügten Zeile positionsnummer.js; sonst stünde überall der
        # Default 10. Leere Nummern vergibt das Formset beim Speichern.
        self.fields['position'].required = False
        self.fields['position'].initial = None
        # Ohne Angabe (Zeile ohne das Feld, älteres Formular) eine Leistung.
        if 'zeilenart' in self.fields:
            self.fields['zeilenart'].required = False
            # Für zeilenart.js, das beim Umstellen dasselbe im Browser tut.
            # Nur Felder dieser Maske, weil etwa das Angebot keinen Zeitraum
            # je Position hat.
            vorhanden = {*self.fields, *self.NUR_ANGEZEIGT}
            widget_am_eingabefeld(self.fields['zeilenart']).attrs[
                'data-felder-ohne-bedeutung'] = json.dumps({
                    art: [name for name in self.felder_ohne_bedeutung(art)
                          if name in vorhanden]
                    for art in Zeilenart.values})
        # ``disabled`` ignoriert den gesendeten Wert und behält den
        # gespeicherten oder den Default; ein Hidden Input wirkt damit
        # ebenfalls nicht.
        self.ohne_bedeutung = self.felder_ohne_bedeutung(self._zeilenart())
        for name in self.ohne_bedeutung:
            if name in self.fields:
                self.fields[name].disabled = True
        self.fields['position'].widget.attrs['data-positionsnummer'] = ''
        # Kurz ("19 %", ohne "(Regelsteuersatz)"), damit die Spalte schmal
        # bleibt.
        steuersatz_auswahl_eingrenzen(self, kurz=True)

    #: Readonly-Spalten des Admins (``BelegpositionInline``), nicht in
    #: ``fields``; auch sie blendet zeilenart.js aus.
    NUR_ANGEZEIGT = ('zeilensumme',)

    @staticmethod
    def felder_ohne_bedeutung(art: str) -> tuple[str, ...]:
        """``Zeilenart.felder_ohne_bedeutung`` zuzüglich der Felder, die nur
        das Formular hat: die Katalogsuche, die nur Leistungen liefert, und
        der Betrag, den Titel und Text nicht haben."""
        art = art or Zeilenart.LEISTUNG
        felder = Zeilenart.felder_ohne_bedeutung(art)
        if art != Zeilenart.LEISTUNG:
            felder += ('katalog',)
        if art in Zeilenart.ohne_betrag():
            felder += ('zeilensumme',)
        return felder

    def _zeilenart(self) -> str:
        """Maßgebliche Zeilenart: die gesendete, wenn das Formular gebunden
        ist, sonst die gespeicherte."""
        if self.is_bound and 'zeilenart' in self.fields:
            return self._zeilenart_eingabe() or Zeilenart.LEISTUNG
        return self.instance.zeilenart or Zeilenart.LEISTUNG

    def has_changed(self):
        """Eine neue Zeile, in der nur die vorbelegte Nummer steht, ist leer.

        Sonst verlangte jede ungenutzte Zeile eine Bezeichnung, weil die
        Nummer in einer im Browser angefügten Zeile immer vom (leeren)
        Initialwert abweicht. Nach dem Löschen einer nicht gespeicherten Zeile
        rücken die übrigen auf und tragen eine Nummer, die nicht zu ihrem
        Index passt."""
        if self.instance.pk is None:
            return any(name not in ('position', 'zeilenart')
                       for name in self.changed_data) or (
                'zeilenart' in self.changed_data
                and self._zeilenart_eingabe() not in ('', Zeilenart.LEISTUNG))
        return super().has_changed()

    def _zeilenart_eingabe(self) -> str:
        """Wert des Feldes Zeilenart. "Leistung" (Default) allein gilt nicht
        als Eingabe; ein Titel ohne Bezeichnung wird gemeldet."""
        return self.data.get(self.add_prefix('zeilenart'), '') or ''

    def clean(self):
        daten = super().clean()

        katalog = daten.get('katalog')
        if katalog:
            for name in self.KATALOGFELDER:
                # Unabhängig davon, ob das Feld leer ist, weil Einheit und
                # Steuersatz einen Default haben. Unverändert gilt der
                # Katalog, geändert die Eingabe.
                if name not in self.changed_data:
                    daten[name] = getattr(katalog, name)

            # Die Art hat kein Formularfeld; die Leistungserfassung braucht
            # sie, um Zeit und Menge zu unterscheiden.
            self.instance.art = katalog.art

        # Leer bedeutet automatische Vergabe durch das Formset, das alle
        # Zeilen kennt.
        daten['position'] = (daten.get('position') or '').strip()

        zeilenart = daten.get('zeilenart') or Zeilenart.LEISTUNG
        if 'zeilenart' in self.fields:
            daten['zeilenart'] = zeilenart
            self.instance.zeilenart = zeilenart
        if zeilenart != Zeilenart.LEISTUNG:
            # Titel und Text haben keinen Preis, den des Zuschlags berechnet
            # ``services.zuschlaege_nachrechnen``.
            if daten.get('einzelpreis') in (None, ''):
                daten['einzelpreis'] = Decimal('0.00')
                self.instance.einzelpreis = Decimal('0.00')
            if zeilenart in Zeilenart.ohne_betrag():
                daten['menge'] = Decimal('0')
                self.instance.menge = Decimal('0')
            if (zeilenart == Zeilenart.ZUSCHLAG
                    and daten.get('zuschlag_prozent') is None):
                self.add_error('zuschlag_prozent',
                               'Ein Zuschlag braucht seinen Satz in Prozent.')

        for name in ('bezeichnung', 'einzelpreis'):
            if name in self.fields and daten.get(name) in (None, ''):
                self.add_error(
                    name,
                    'Angeben oder eine Katalogposition auswählen.',
                )
        return daten


class BelegpositionFormSet(forms.BaseInlineFormSet):
    """Setzt in leeren Zeilen die nächsten Positionsnummern als Initialwert
    und vergibt beim Speichern die noch leeren, beides nach
    ``positionsnummer.naechste_nummern``. Eingegebene Nummern bleiben."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Leere Zeilen zeigen die Nummer, die sie beim Speichern erhielten,
        # damit beim Einfügen die Position erkennbar ist.
        vorhanden = [p.position for p in self.get_queryset()]
        vorhanden += self._verborgene_nummern()
        self.initial_extra = [
            {'position': nummer}
            for nummer in naechste_nummern(vorhanden, self.extra)
        ]

    def clean(self):
        # Zuerst nummerieren, damit Djangos Unique-Prüfung die endgültigen
        # Nummern prüft.
        self._nummern_vergeben()
        super().clean()
        self._zuschlagsbezug_pruefen()

    def _zuschlagsbezug_pruefen(self):
        """Fehler am Feld, wenn "auf" eines Zuschlags keine Zeile des Formsets
        trifft. Im Formset, weil ``Belegposition.clean`` die mitgespeicherten
        Zeilen nicht kennt."""
        from .services import bezugsfehler, ohne_bezug
        zeilen = {}
        for formular in self.forms:
            daten = getattr(formular, 'cleaned_data', None)
            if not daten or daten.get('DELETE'):
                continue
            if formular.instance.pk is None and not formular.has_changed():
                continue
            zeilen[id(formular.instance)] = formular
        for zuschlag in ohne_bezug(f.instance for f in zeilen.values()):
            zeilen[id(zuschlag)].add_error('zuschlag_auf',
                                           bezugsfehler(zuschlag))

    def save(self, commit=True):
        """Danach die Zuschläge, deren Betrag von den eben gespeicherten
        Positionen abhängt (R-180)."""
        ergebnis = super().save(commit)
        if commit and self.instance.pk:
            from .services import zuschlaege_nachrechnen
            zuschlaege_nachrechnen(self.instance)
        return ergebnis

    def _verborgene_nummern(self) -> list[str]:
        """Nummern der Positionen, die das Formular nicht enthält (Abzugszeilen
        der Schlussrechnung, ``SchlusspositionInline``). Sie sind vergeben und
        werden berücksichtigt, damit keine vorhandene Nummer vorgeschlagen
        wird."""
        if self.instance is None or self.instance.pk is None:
            return []
        return list(
            Belegposition.objects.filter(beleg=self.instance)
            .exclude(pk__in=self.get_queryset().values('pk'))
            .values_list('position', flat=True))

    def _nummern_vergeben(self):
        vergeben = list(self._verborgene_nummern())
        offen = []
        for formular in self.forms:
            daten = getattr(formular, 'cleaned_data', None)
            if not daten or daten.get('DELETE'):
                continue
            if daten.get('position'):
                vergeben.append(daten['position'])
            elif formular.has_changed():
                offen.append(formular)

        nummern = naechste_nummern(vergeben, len(offen))
        for formular, nummer in zip(offen, nummern, strict=True):
            # cleaned_data für die Eindeutigkeitsprüfung, instance für die
            # Datenbank.
            formular.cleaned_data['position'] = nummer
            formular.instance.position = nummer


class StandardZeileForm(forms.ModelForm):
    """Zeile eines ``EinStandardFormSet`` ohne eigene Prüfung des
    Standard-Constraints.

    Die einzelne Zeile prüfte gegen die Datenbank, in der der alte Standard
    noch gesetzt ist, auch wenn derselbe POST ihn zurücknimmt. Den ganzen
    Satz prüft das Formset. Ausgenommen sind nur die Constraints, deren
    Bedingung ``ist_standard`` enthält; die übrigen prüft die Zeile.

    Regression: Ein Wechsel des Standards ließ sich nicht speichern.
    """

    def validate_constraints(self):
        ausnahmen = self._get_validation_exclusions() | {'ist_standard'}
        try:
            self.instance.validate_constraints(exclude=ausnahmen)
        except ValidationError as fehler:
            self._update_errors(fehler)


class EinStandardFormSet(forms.BaseInlineFormSet):
    """Höchstens ein "Standard" je Gruppe, als Formularfehler.

    Der Constraint am Modell greift erst in der Datenbank, ohne Fehler am
    Feld. Zwei gesetzte Standards werden abgelehnt, damit sich keine andere
    Zeile unbemerkt ändert.

    Die Zeilen brauchen ``StandardZeileForm`` (``form`` am Inline), weil
    sonst jede Zeile einen Wechsel des Standards ablehnt.
    """

    #: Feld, je Wert dessen höchstens ein Standard gilt, bei ``Kontaktweg``
    #: die ``art``. Leer: einer im ganzen Formset.
    gruppieren_nach = ''

    #: Bezeichnung der Checkbox im Fehlertext.
    kennzeichen = 'Standard'

    def clean(self):
        super().clean()
        # Keine weitere Meldung, wenn das Formset bereits Fehler hat.
        if any(self.errors):
            return

        gezaehlt: dict[str, int] = {}
        for formular in self._bleibende():
            if formular.cleaned_data.get('ist_standard'):
                gruppe = self._gruppe(formular)
                gezaehlt[gruppe] = gezaehlt.get(gruppe, 0) + 1

        doppelt = [g for g, anzahl in gezaehlt.items() if anzahl > 1]
        if not doppelt:
            return

        if self.gruppieren_nach:
            # Label der Choice ("Telefon") für die Meldung.
            feld = self.model._meta.get_field(self.gruppieren_nach)
            benennung = dict(feld.choices or [])
            namen = ', '.join(str(benennung.get(g, g)) for g in sorted(doppelt))
            raise forms.ValidationError(
                f'Je Art darf nur eine Zeile "{self.kennzeichen}" sein. '
                f'Betroffen: {namen}. Bitte das Häkchen bei den übrigen '
                f'Zeilen dieser Art entfernen.')
        raise forms.ValidationError(
            f'Es darf nur eine Zeile "{self.kennzeichen}" sein. Bitte das '
            f'Häkchen bei den übrigen entfernen.')

    def _bleibende(self):
        """Zeilen, die nach dem Speichern bestehen."""
        for formular in self.forms:
            daten = getattr(formular, 'cleaned_data', None)
            if daten and not daten.get('DELETE'):
                yield formular

    def _gruppe(self, formular) -> str:
        if not self.gruppieren_nach:
            return ''
        return str(formular.cleaned_data.get(self.gruppieren_nach) or '')

    def save(self, commit=True):
        """Speichert einen Wechsel des Standards in einer Reihenfolge, die der
        partielle Index in der Datenbank zulässt.

        Zuerst wird der Standard an den abgebenden Zeilen entfernt, weil sonst
        kurzzeitig zwei Standards in der Tabelle stünden. Setzt das Formset
        für eine Gruppe selbst einen Standard, unterbleibt die Vorgabe in
        ``save()`` am Modell ("erste Zeile wird Standard"), die sonst die eben
        abgewählte Zeile wieder setzte, weil die neue noch nicht gespeichert
        ist.
        """
        if commit:
            abgebende = [
                formular.instance.pk for formular in self.initial_forms
                if formular.instance.pk
                and formular.initial.get('ist_standard')
                and (formular in self.deleted_forms
                     or not formular.cleaned_data.get('ist_standard'))]
            if abgebende:
                self.model.objects.filter(pk__in=abgebende).update(
                    ist_standard=False)
            mit_standard = {self._gruppe(f) for f in self._bleibende()
                            if f.cleaned_data.get('ist_standard')}
            for formular in self._bleibende():
                if self._gruppe(formular) in mit_standard:
                    formular.instance.standard_festgelegt = True
        return super().save(commit)


class KontaktwegFormSet(EinStandardFormSet):
    """Ein Standard je Art, also je einer für E-Mail und Telefon."""

    gruppieren_nach = 'art'


class AdresseFormSet(EinStandardFormSet):
    kennzeichen = 'Standardanschrift'


class ZahlungForm(forms.Form):
    """Zwischenseite „Zahlung vermerken", vollständig vorbelegt.

    Das Datum ist ein Feld, weil es die Überfälligkeit bestimmt und selten
    dem Tag der Erfassung entspricht.
    """

    datum = forms.DateField(
        label='Eingegangen am',
        widget=UnfoldAdminSingleDateWidget,
        help_text='Das Datum vom Kontoauszug, nicht das der Erfassung.',
    )
    betrag = forms.DecimalField(
        label='Betrag',
        max_digits=12,
        decimal_places=2,
        min_value=0,
        localize=True,
        widget=BetragWidget,
        help_text='Was tatsächlich geflossen ist. Vorbelegt mit dem offenen '
                  'Betrag der Rechnung.',
    )
    skonto = forms.DecimalField(
        label='Skonto',
        max_digits=12,
        decimal_places=2,
        min_value=0,
        required=False,
        localize=True,
        widget=BetragWidget,
        help_text='Nur wenn der Kunde etwas abgezogen hat. Der Betrag, den '
                  'er abgezogen hat, nicht der Prozentsatz.',
    )
    #: Nur beim Abschlag; sonst entfernt die Zwischenseite das Feld.
    kuerzung = forms.DecimalField(
        label='Gekürzt',
        max_digits=12,
        decimal_places=2,
        min_value=0,
        required=False,
        localize=True,
        widget=BetragWidget,
        help_text='Was der Kunde (noch) nicht anerkennt, brutto. Der Betrag '
                  'wird nicht gemahnt; die Schlussrechnung fordert ihn, '
                  'ebenso alles, was bis dahin sonst nicht bezahlt ist. '
                  'Nicht für Skonto; Skonto ist erlassen.',
    )
    zahlungsart = forms.ChoiceField(
        label='Art',
        choices=Zahlungsart,
        initial=Zahlungsart.UEBERWEISUNG,
        widget=UnfoldAdminSelectWidget,
    )
    verwendungszweck = forms.CharField(
        label='Verwendungszweck',
        max_length=300,
        required=False,
        widget=UnfoldAdminTextInputWidget,
        help_text='Wie er auf dem Kontoauszug steht. Leer bedeutet: die '
                  'Rechnungsnummer.',
    )

    def __init__(self, *args, mit_kuerzung: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        if not mit_kuerzung:
            del self.fields['kuerzung']

    def clean_skonto(self):
        """Leeres Feld ergibt 0 (kein ``None``)."""
        return self.cleaned_data.get('skonto') or Decimal('0.00')

    def clean_kuerzung(self):
        return self.cleaned_data.get('kuerzung') or Decimal('0.00')
