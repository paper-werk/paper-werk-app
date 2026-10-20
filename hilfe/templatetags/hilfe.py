from django import template

from ..texte import anleitung

register = template.Library()


@register.inclusion_tag('hilfe/_verweis.html', takes_context=True)
def hilfe_verweis(context):
    """Das „?“ in der Kopfleiste, eingebunden in
    ``templates/unfold/helpers/userlinks.html``.

    Sprungziel ist ``hilfe_anker`` aus dem Kontext (für eigene Seiten ohne
    Modell), sonst ``opts.model_name`` der Admin-Maske. Fehlt der Anker in
    der Anleitung, bleibt die Stelle leer: kein Link auf einen Abschnitt,
    den es nicht gibt.
    """
    opts = context.get('opts')
    anker = context.get('hilfe_anker') or getattr(opts, 'model_name', None)
    if anker not in anleitung().anker:
        anker = None
    return {'anker': anker}
