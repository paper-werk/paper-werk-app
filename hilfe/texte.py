"""Die Bedienungsanleitung: Markdown aus ``hilfe/texte/``, gerendert zu HTML.

Alle ``*.md`` ergeben in Reihenfolge der Dateinamen ein Dokument. Die Seite
``/hilfe/`` und das PDF (``manage.py hilfe_pdf``) rendern dasselbe Ergebnis.

Eine Überschrift mit ``{#<model_name>}`` (``attr_list``) ist das Sprungziel
für das „?“ in der Kopfleiste der Admin-Masken, siehe
``templatetags/hilfe.py``. Übrige Überschriften bekommen ihre ``id`` von
``toc``.

Das HTML wird ohne Escaping ausgegeben, weil die Quelle im Repository
liegt und wie Code reviewt wird; Benutzereingaben fließen nicht ein.
"""

import functools
import re
from dataclasses import dataclass
from pathlib import Path

import markdown
from django.conf import settings
from markdown.extensions.toc import slugify_unicode

TEXTE = Path(__file__).resolve().parent / 'texte'


@dataclass(frozen=True)
class Anleitung:
    html: str
    #: ``toc_tokens`` von Python-Markdown: Kapitel (h1) mit ``children`` (h2).
    inhalt: list[dict]
    #: Alle ``id`` im HTML, also die gültigen Sprungziele.
    anker: frozenset[str]


def _rendern() -> Anleitung:
    quelle = '\n\n'.join(datei.read_text(encoding='utf-8')
                         for datei in sorted(TEXTE.glob('*.md')))
    md = markdown.Markdown(
        extensions=['attr_list', 'tables', 'toc'],
        extension_configs={'toc': {'slugify': slugify_unicode,
                                   'toc_depth': '1-2'}})
    html = md.convert(quelle)
    return Anleitung(html=html, inhalt=md.toc_tokens,
                     anker=frozenset(re.findall(r'\bid="([^"]+)"', html)))


_gecacht = functools.cache(_rendern)


def anleitung() -> Anleitung:
    """Die gerenderte Anleitung. Im Betrieb einmal je Prozess gerendert
    (die Texte ändern sich nur mit einem Update), unter ``DEBUG`` bei jedem
    Aufruf, damit Textänderungen ohne Neustart sichtbar sind."""
    return _rendern() if settings.DEBUG else _gecacht()
