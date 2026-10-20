"""Benutzermodell des Projekts.

Ohne eigene Felder, verhält sich wie Djangos ``User``. Es existiert, weil
sich ``AUTH_USER_MODEL`` nachträglich kaum ändern lässt; so bleibt etwa die
Anmeldung per E-Mail möglich.

Fachliche Daten (Telefon, Kürzel) gehören in ein Profil mit
``OneToOneField``, das sich wieder entfernen lässt.
"""

from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    pass
