"""Benutzermodell des Projekts und Ereignisregeln.

``User`` hat keine eigenen Felder und verhält sich wie Djangos ``User``. Es
existiert, weil sich ``AUTH_USER_MODEL`` nachträglich kaum ändern lässt; so
bleibt etwa die Anmeldung per E-Mail möglich.

Fachliche Daten (Telefon, Kürzel) gehören in ein Profil mit
``OneToOneField``, das sich wieder entfernen lässt.
"""

import secrets
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class User(AbstractUser):
    pass


def ziel_pruefen(url: str) -> None:
    """Ziel einer Ereignisregel: ``http`` oder ``https`` mit Hostname.

    Djangos ``URLValidator`` lehnt Hostnamen ohne Punkt ab, also gerade die
    Dienste im Docker-Netz (``http://n8n:5678``). ``http`` ist nur für
    solche Hostnamen oder mit ``DEBUG`` erlaubt, weil das Token sonst im
    Klartext über fremde Netze ginge.
    """
    teile = urlsplit(url)
    if teile.scheme not in ('http', 'https') or not teile.hostname:
        raise ValidationError('Eine Adresse mit http:// oder https:// und '
                              'Hostname angeben.')
    if (teile.scheme == 'http' and not settings.DEBUG
            and '.' in teile.hostname):
        raise ValidationError('Ziele außerhalb der Installation brauchen '
                              'https.')


def token_erzeugen() -> str:
    """Zufälliges Token für den Header ``X-PaperWerk-Token``."""
    return secrets.token_urlsafe(32)


class Ereignisregel(models.Model):
    """Regel, die Ereignisse einer Quelle per HTTP-POST an eine URL meldet
    (``docs/webhooks.md``).

    ``aktionen`` und ``typen`` sind Listen von Werten der Ereignisquelle
    (``core.erweiterungen.Ereignisquelle``); eine leere Liste lässt alle
    zu. ``core`` kennt die Werte nicht, die Maske holt sie aus der
    Registrierung.
    """

    name = models.CharField('Name', max_length=100)
    aktiv = models.BooleanField('Aktiv', default=True)
    quelle = models.CharField('Ereignis', max_length=30, default='beleg')
    aktionen = models.JSONField('Aktionen', default=list, blank=True)
    typen = models.JSONField('Typen', default=list, blank=True)
    url = models.CharField('Ziel-URL', max_length=500, validators=[ziel_pruefen])
    token = models.CharField(
        'Token', max_length=100, default=token_erzeugen,
        help_text='Wird im Header X-PaperWerk-Token mitgesendet. In n8n '
                  'als „Header Auth“ am Webhook-Knoten prüfen.',
    )

    class Meta:
        verbose_name = 'Ereignisregel'
        verbose_name_plural = 'Ereignisregeln'
        ordering = ['name']

    def __str__(self) -> str:
        return self.name

    def trifft_zu(self, aktion: str, typ: str) -> bool:
        """Ob die Filter der Regel ein Ereignis mit ``aktion`` und ``typ``
        zulassen."""
        return ((not self.aktionen or aktion in self.aktionen)
                and (not self.typen or typ in self.typen))
