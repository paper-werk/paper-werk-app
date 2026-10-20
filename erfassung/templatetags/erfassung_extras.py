"""Template-Filter der Erfassung.

Nur Formatierung. Die Funktionen stehen in ``formate.py`` und sind ohne
Django aufrufbar; hier werden sie registriert.
"""

from django import template

from .. import formate

register = template.Library()

#: Voller Name ("Anna Weber"), etwa für den Leistungsnachweis.
register.filter('person', formate.personenname)

#: Minuten als "h:mm", wie in der Erfassung.
register.filter('dauer', formate.dauer_zeigen)
