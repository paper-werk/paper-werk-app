"""Formulare der Admin-Masken lesen und absenden.

Die POST-Daten entstehen aus dem HTML der Maske: alle Felder mit ihren
vorbelegten Werten, Management Form und leere Inline-Zeilen eingeschlossen.
Der Treiber setzt nur die Felder, die ein Benutzer ausfüllt. Ein Feld, das
die Maske nicht anbietet, ist ein Fehler (``FeldFehlt``), weil ein Benutzer
es auch nicht setzen könnte.

Weitere Inline-Zeilen entstehen aus der Vorlage ``<prefix>-__prefix__-*``,
die Django für "Weitere hinzufügen" ausgibt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from django.contrib.messages import get_messages


class FeldFehlt(AssertionError):
    """Die Maske bietet ein Feld nicht an."""


class MaskeAbgelehnt(AssertionError):
    """Die Maske hat die Eingabe nicht angenommen (Formularfehler oder
    Fehlermeldung). ``html`` ist die Antwort, falls vorhanden."""

    def __init__(self, text, html=''):
        super().__init__(text)
        self.html = html


def oeffnen_html(fehler: MaskeAbgelehnt) -> str:
    return fehler.html


@dataclass
class _Form:
    action: str
    method: str
    attrs: dict
    #: Name auf Liste der Werte, in der Reihenfolge des HTML.
    felder: dict[str, list[str]] = field(default_factory=dict)
    #: Alle Feldnamen, auch nicht ausgewählte Checkboxen und Radios.
    bekannt: set[str] = field(default_factory=set)
    #: Mögliche Werte je Auswahlfeld (select, radio, checkbox).
    optionen: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    knoepfe: list[tuple[str, str, str]] = field(default_factory=list)


class _Leser(HTMLParser):
    """Sammelt alle Formulare mit Feldern, Optionen und Knöpfen."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.formulare: list[_Form] = []
        self._form: _Form | None = None
        self._select: str | None = None
        self._select_gewaehlt: list[str] = []
        self._select_erste: str | None = None
        self._select_mehrfach = False
        self._option: tuple[str, bool] | None = None
        self._optiontext = ''
        self._textarea: str | None = None
        self._text = ''
        self._knopf: dict | None = None
        self._knopftext = ''
        self._label_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v if v is not None else '') for k, v in attrs}
        if tag == 'form':
            self._form = _Form(a.get('action', ''),
                               a.get('method', 'get').lower(), a)
            self.formulare.append(self._form)
            return
        form = self._form
        if form is None and tag not in ('input', 'select', 'textarea', 'button'):
            return
        if form is None:
            # Felder mit form="id" außerhalb des Formulars.
            ziel = a.get('form')
            form = next((f for f in self.formulare
                         if f.attrs.get('id') == ziel), None) if ziel else None
            if form is None:
                return
        name = a.get('name')
        if tag == 'input':
            typ = a.get('type', 'text').lower()
            if typ in ('submit', 'image'):
                if name:
                    form.knoepfe.append((name, a.get('value', ''),
                                         a.get('value', '')))
                return
            if not name or typ in ('button', 'reset', 'file'):
                return
            form.bekannt.add(name)
            if typ in ('checkbox', 'radio'):
                form.optionen.setdefault(name, []).append(
                    (a.get('value', 'on'), ''))
                if 'checked' in a:
                    form.felder.setdefault(name, []).append(a.get('value', 'on'))
                return
            form.felder.setdefault(name, []).append(a.get('value', ''))
        elif tag == 'select' and name:
            form.bekannt.add(name)
            self._select = name
            self._select_gewaehlt = []
            self._select_erste = None
            self._select_mehrfach = 'multiple' in a
            self._select_form = form
        elif tag == 'option' and self._select:
            self._option = (a.get('value'), 'selected' in a)
            self._optiontext = ''
        elif tag == 'textarea' and name:
            form.bekannt.add(name)
            self._textarea = name
            self._text = ''
            self._textarea_form = form
        elif tag == 'button':
            if a.get('type', 'submit').lower() == 'submit':
                self._knopf = {'name': a.get('name', ''),
                               'value': a.get('value', ''), 'form': form}
                self._knopftext = ''

    def handle_data(self, data):
        if self._option is not None:
            self._optiontext += data
        if self._textarea is not None:
            self._text += data
        if self._knopf is not None:
            self._knopftext += data

    def handle_endtag(self, tag):
        if tag == 'option' and self._option is not None:
            wert, gewaehlt = self._option
            text = ' '.join(self._optiontext.split())
            wert = text if wert is None else wert
            self._select_form.optionen.setdefault(self._select, []).append(
                (wert, text))
            if self._select_erste is None:
                self._select_erste = wert
            if gewaehlt:
                self._select_gewaehlt.append(wert)
            self._option = None
        elif tag == 'select' and self._select:
            werte = self._select_gewaehlt
            if not werte and not self._select_mehrfach and self._select_erste is not None:
                werte = [self._select_erste]
            if werte:
                self._select_form.felder[self._select] = werte
            self._select = None
        elif tag == 'textarea' and self._textarea:
            # Der Browser entfernt einen führenden Zeilenumbruch.
            text = self._text[1:] if self._text.startswith('\n') else self._text
            self._textarea_form.felder.setdefault(self._textarea, []).append(text)
            self._textarea = None
        elif tag == 'button' and self._knopf is not None:
            k = self._knopf
            k['form'].knoepfe.append((k['name'], k['value'],
                                      ' '.join(self._knopftext.split())))
            self._knopf = None
        elif tag == 'form':
            self._form = None


class Formular:
    """Ein Formular einer Maske mit den Werten, die der Browser senden
    würde."""

    def __init__(self, client, url: str, form: _Form, html: str):
        self.client = client
        self.url = form.action or url
        self._form = form
        self.html = html
        self.werte: dict[str, list[str]] = {k: list(v) for k, v in form.felder.items()}

    # --- Lesen ---

    def __contains__(self, name: str) -> bool:
        return name in self._form.bekannt

    def wert(self, name: str) -> str | None:
        werte = self.werte.get(name)
        return werte[0] if werte else None

    def optionen(self, name: str) -> list[tuple[str, str]]:
        return self._form.optionen.get(name, [])

    def option_mit_text(self, name: str, muster: str) -> str:
        """Wert der Option, deren Text ``muster`` enthält (genau eine)."""
        treffer = [w for w, t in self.optionen(name) if muster in t]
        if len(treffer) != 1:
            raise FeldFehlt(f'{name}: {len(treffer)} Optionen mit "{muster}": '
                            f'{self.optionen(name)}')
        return treffer[0]

    @property
    def knoepfe(self) -> list[tuple[str, str, str]]:
        return list(self._form.knoepfe)

    # --- Setzen ---

    def setzen(self, name: str, wert) -> None:
        if name not in self._form.bekannt:
            raise FeldFehlt(f'Feld {name!r} fehlt in der Maske {self.url}')
        if wert is None or wert is False:
            self.werte.pop(name, None)
        elif wert is True:
            self.werte[name] = ['on']
        elif isinstance(wert, (list, tuple)):
            self.werte[name] = [str(w) for w in wert]
        else:
            self.werte[name] = [str(wert)]

    def zeilen(self, prefix: str) -> int:
        return int(self.wert(f'{prefix}-TOTAL_FORMS') or 0)

    def zeile(self, prefix: str, index: int, **werte) -> None:
        """Setzt Felder einer Inline-Zeile; fehlende Zeilen werden aus der
        Vorlage ``__prefix__`` angelegt."""
        while index >= self.zeilen(prefix):
            self._zeile_anfuegen(prefix)
        for name, wert in werte.items():
            self.setzen(f'{prefix}-{index}-{name}', wert)

    def freie_zeile(self, prefix: str) -> int:
        """Index der ersten Zeile ohne ``id`` und ohne Eingabe in
        ``pruefen``; sonst eine neue Zeile am Ende."""
        initial = int(self.wert(f'{prefix}-INITIAL_FORMS') or 0)
        belegt = getattr(self, '_belegt', set())
        for index in range(initial, self.zeilen(prefix)):
            if (prefix, index) not in belegt:
                belegt.add((prefix, index))
                self._belegt = belegt
                return index
        index = self.zeilen(prefix)
        self._zeile_anfuegen(prefix)
        belegt.add((prefix, index))
        self._belegt = belegt
        return index

    def _zeile_anfuegen(self, prefix: str) -> None:
        index = self.zeilen(prefix)
        vorlage = f'{prefix}-__prefix__-'
        for name in list(self._form.bekannt):
            if name.startswith(vorlage):
                neu = f'{prefix}-{index}-{name[len(vorlage):]}'
                self._form.bekannt.add(neu)
                if name in self._form.optionen:
                    self._form.optionen[neu] = self._form.optionen[name]
                if name in self._form.felder:
                    self.werte[neu] = list(self._form.felder[name])
        self.werte[f'{prefix}-TOTAL_FORMS'] = [str(index + 1)]

    # --- Absenden ---

    def absenden(self, knopf: str | None = None, *, erwartet_weiterleitung=True):
        """Sendet das Formular wie ein Klick auf ``knopf`` (Name des
        Submit-Buttons oder sein Text).

        Mit ``erwartet_weiterleitung`` muss die Antwort ein Redirect sein,
        und es darf keine Fehlermeldung anstehen. Sonst ``MaskeAbgelehnt``
        mit den Fehlern aus dem HTML.
        """
        daten = {k: v for k, v in self.werte.items()
                 if '__prefix__' not in k}
        if knopf is not None:
            passend = [(n, w) for n, w, t in self._form.knoepfe
                       if knopf in (n, t)]
            if not passend:
                raise FeldFehlt(f'Knopf {knopf!r} fehlt in {self.url}: '
                                f'{self._form.knoepfe}')
            name, wert = passend[0]
            if name:
                daten[name] = [wert]
        antwort = self.client.post(self.url, daten)
        meldungen = meldungen_aus(antwort)
        fehler = [m for stufe, m in meldungen if stufe == 'error']
        if erwartet_weiterleitung:
            if antwort.status_code != 302:
                raise MaskeAbgelehnt(
                    f'{self.url}: Status {antwort.status_code}; '
                    f'{formularfehler(antwort) or meldungen}',
                    antwort.content.decode(errors='replace'))
            if fehler:
                raise MaskeAbgelehnt(f'{self.url}: {fehler}')
        antwort.meldungen = meldungen
        return antwort


def meldungen_aus(antwort) -> list[tuple[str, str]]:
    """Meldungen des Messages-Frameworks aus einer Antwort, als (Stufe,
    Text)."""
    anfrage = getattr(antwort, 'wsgi_request', None)
    if anfrage is None:
        return []
    return [(m.level_tag, str(m)) for m in get_messages(anfrage)]


_FEHLER = re.compile(
    r'<ul class="errorlist[^"]*"[^>]*>(.*?)</ul>'
    r'|<p class="errornote[^"]*"[^>]*>(.*?)</p>'
    r'|<div[^>]*class="[^"]*(?:errors|text-red)[^"]*"[^>]*>(.*?)</div>', re.S)
_TAG = re.compile(r'<[^>]+>')


def formularfehler(antwort) -> list[str]:
    """Texte der Fehlerlisten im HTML."""
    html = antwort.content.decode(errors='replace')
    texte = (' '.join(_TAG.sub(' ', ''.join(teile)).split())
             for teile in _FEHLER.findall(html))
    return [t for t in texte if t]


def oeffnen(client, url: str, *, enthaelt: str | None = None) -> Formular:
    """Lädt die Maske und gibt das Formular zurück, das ``enthaelt`` als
    Feld hat; ohne ``enthaelt`` das POST-Formular mit den meisten Feldern.
    """
    antwort = client.get(url)
    if antwort.status_code != 200:
        raise MaskeAbgelehnt(f'GET {url}: Status {antwort.status_code} '
                             f'{antwort.get("Location", "")}; '
                             f'{meldungen_aus(antwort)}')
    html = antwort.content.decode()
    leser = _Leser()
    leser.feed(html)
    # Ohne das Abmeldeformular der Kopfleiste.
    kandidaten = [f for f in leser.formulare
                  if f.method == 'post' and 'logout' not in f.action]
    if enthaelt is not None:
        kandidaten = [f for f in kandidaten if enthaelt in f.bekannt]
    if not kandidaten:
        raise FeldFehlt(f'Kein passendes Formular in {url}')
    form = max(kandidaten, key=lambda f: len(f.bekannt))
    return Formular(client, url, form, html)
