"""Template-Filter für die Belege.

Die Formatierung steht in ``faktura/formate.py``, weil der Admin sie auch
ohne Template verwendet. Hier werden die Funktionen nur als Filter
registriert.
"""

import re
from decimal import Decimal

from django import template
from django.utils.safestring import mark_safe

from .. import formate, services

register = template.Library()

register.filter('geld', formate.geld)
register.filter('menge', formate.menge)
register.filter('prozent', formate.prozent)


@register.filter
def zeilensumme(position) -> Decimal:
    """Nettosumme einer Position, berechnet im Service.

    Verworfen: Berechnung im Template, weil die Rundungsregel dann an einer
    zweiten Stelle stünde.
    """
    return services.positionssumme(
        menge=position.menge, einzelpreis=position.einzelpreis
    )


#: Format aus ``facturx.mit_bt`` ("Preis (Netto) (BT-146)"). Zerlegt für
#: die Spaltenköpfe der Positionen (``tabular_heading.html``) und ihre
#: schmalen Datumsfelder: Label oben, Nummer klein darunter oder im
#: ``title``.
_MIT_BT = re.compile(r'^(?P<text>.*?)\s*\((?P<bt>BT-\d+)\)$')


@register.filter
def ohne_bt(beschriftung):
    """Label ohne BT-Nummer: "Leistung von (BT-134)" ergibt "Leistung von"."""
    treffer = _MIT_BT.match(str(beschriftung))
    return treffer['text'] if treffer else beschriftung


@register.filter
def nur_bt(beschriftung) -> str:
    """Nur die BT-Nummer: "Leistung von (BT-134)" ergibt "BT-134", sonst
    leer."""
    treffer = _MIT_BT.match(str(beschriftung))
    return treffer['bt'] if treffer else ''


#: Formatierung der Readonly-Werte einer Position wie im PDF. Django
#: zeigte sonst "40,000", "1450,00" und den vollen Text der Choice ("19 %
#: (Regelsteuersatz)").
_LESEFORMAT = {
    'menge': formate.menge,
    'einzelpreis': formate.geld,
    'steuersatz': formate.prozent,
}


#: Wert von ``lesewert`` für ein Feld ohne Bedeutung; nicht leer, weil
#: Unfold für leere Werte "-" ausgibt.
OHNE_BEDEUTUNG = mark_safe('<span class="pw-ohne-bedeutung"></span>')


def _ohne_bedeutung(feld, name) -> bool:
    """Ob das Feld für die Zeilenart dieser Position ohne Bedeutung ist
    (``BelegpositionForm.ohne_bedeutung``), etwa die Menge eines Titels am
    festgeschriebenen Beleg, wo kein JavaScript das Feld ausblendet."""
    return name in getattr(feld.form, 'ohne_bedeutung', ())


@register.filter
def lesewert(feld) -> str:
    """Anzeigewert eines Readonly-Feldes einer Belegposition.

    Leer bedeutet: Unfold zeigt den Standardwert von Django
    (``field_readonly_value.html`` verwendet ``value`` nur, wenn er nicht
    leer ist). Gelesen am Objekt, weil ``feld.contents`` bereits
    formatierter Text ist.
    """
    if not getattr(feld, 'is_readonly', False):
        return ''
    name = feld.field.get('name') if isinstance(feld.field, dict) else None
    if _ohne_bedeutung(feld, name):
        return OHNE_BEDEUTUNG
    formatieren = _LESEFORMAT.get(name)
    objekt = getattr(feld.form, 'instance', None)
    # Das Template gilt für jedes Tabular Inline; nur Belegpositionen sind
    # gemeint.
    if (formatieren is None or objekt is None or objekt.pk is None
            or objekt._meta.model_name != 'belegposition'):
        return ''
    wert = getattr(objekt, name, None)
    return formatieren(wert) if wert not in (None, '') else ''


@register.filter
def hat_lesewert(feld) -> bool:
    """Ob ein Readonly-Feld einen anzuzeigenden Wert hat. ``contents``
    genügt nicht, weil es für leere Werte "-" enthält. Eine nicht gesetzte
    Checkbox ("Optional") gilt als leer."""
    objekt = getattr(feld.form, 'instance', None)
    name = feld.field.get('name') if isinstance(feld.field, dict) else None
    if _ohne_bedeutung(feld, name):
        return False
    if objekt is None or name is None:
        return bool(feld.contents)
    wert = getattr(objekt, name, None)
    # "is False", weil 0 == False gilt und 0 ein Wert ist.
    return wert is not False and wert not in (None, '')
