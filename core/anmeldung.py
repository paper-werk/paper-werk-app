"""Single Sign-on über einen OIDC-Anbieter.

Eingerichtet für Microsoft Entra ID über allauths generischen
OIDC-Provider, damit ein anderer Anbieter (etwa Authentik) nur eine andere
Discovery-URL und Client-ID in der ``.env`` braucht.

Das Modul regelt:

* **Zugang.** Entra lehnt Konten ab, die der Anwendung nicht zugewiesen
  sind. Zusätzlich lehnt ``pre_social_login`` Konten ohne bekannte Rolle
  ab, bevor sie angelegt oder angemeldet werden. Das greift, wenn im
  Portal „Zuweisung erforderlich“ ausgeschaltet ist.
* **Rechte.** Bei jeder Anmeldung werden die Rollen aus dem Verzeichnis auf
  Gruppen und Admin-Zugang übertragen (``rollen_uebernehmen``). Rolle und
  Gruppe heißen gleich (``core/gruppen.py``). Das geschieht im Adapter aus
  den Settings, nicht über ein Signal.
* **Registrierung.** Selbstregistrierung ist abgeschaltet; lokale Konten
  legt ein Verwalter an.

Der lokale Login bleibt erhalten, als Zugang bei nicht erreichbarem
Anbieter.
"""

import logging
from functools import wraps

import requests
from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.contrib.auth.models import Group
from django.shortcuts import render
from django.urls import reverse

from . import gruppen

logger = logging.getLogger(__name__)


def ansprueche(extra_data: dict) -> dict:
    """Claims des Anbieters aus ``extra_data``, zusammengeführt.

    Das ID-Token hat Vorrang und wird deshalb zuletzt eingemischt: Bei
    Microsoft stehen ``email`` und ``roles`` nur dort (daher
    ``fetch_userinfo`` = False).

    Seit allauth 65.11 liegen die Claims unter ``id_token`` und
    ``userinfo``, davor direkt in ``extra_data``. Beide Formen werden
    gelesen.
    """
    if 'id_token' in extra_data or 'userinfo' in extra_data:
        return {
            **(extra_data.get('userinfo') or {}),
            **(extra_data.get('id_token') or {}),
        }
    return dict(extra_data)


def bekannte_rollen(extra_data: dict) -> list[str]:
    """Rollen des Kontos, zu denen eine gleichnamige Gruppe existiert.

    Berücksichtigt werden Rollen mit dem Präfix ``paper-werk-``, deren Gruppe
    existiert. Rollen anderer Anwendungen im Verzeichnis fallen damit heraus,
    und eine neue Gruppe mit Präfix wird ohne Codeänderung erkannt.
    """
    rollen = ansprueche(extra_data).get('roles') or []
    if isinstance(rollen, str):
        rollen = [rollen]
    kandidaten = [r for r in rollen if r.startswith(gruppen.PRAEFIX)]
    vorhanden = set(Group.objects.filter(name__in=kandidaten)
                    .values_list('name', flat=True))
    return [r for r in kandidaten if r in vorhanden]


def rollen_uebernehmen(user, rollen: list[str]) -> None:
    """Gleicht Gruppen, ``is_staff`` und ``is_superuser`` mit den Rollen ab.

    Betrifft nur Gruppen mit Präfix; andere (etwa "Faktura Dienst") bleiben.
    Jede Rolle setzt ``is_staff``, ``paper-werk-superuser`` setzt
    ``is_superuser``. Fehlt die Rolle, werden die Flags entfernt. Der Schutz
    des letzten Verwalters (``core/admin.py``) gilt hier nicht, weil das
    Verzeichnis maßgeblich ist; als Zugang bleibt der lokale Superuser aus
    ``setup.sh``.
    """
    if not user.is_active:
        # allauth prüft ``is_active`` erst danach. Ohne diese Abfrage hätte
        # ein deaktiviertes Konto nach dem Reaktivieren die Rechte schon.
        logger.info('Anmeldung von %s: Konto deaktiviert, Rollen nicht übertragen.', user)
        return

    verwaltet = Group.objects.filter(name__startswith=gruppen.PRAEFIX)
    user.groups.remove(*verwaltet.exclude(name__in=rollen))
    user.groups.add(*verwaltet.filter(name__in=rollen))

    user.is_superuser = gruppen.SUPERUSER in rollen
    user.is_staff = user.is_superuser or bool(rollen)
    user.save(update_fields=['is_staff', 'is_superuser'])


class KontoAdapter(DefaultAccountAdapter):
    """Keine Selbstregistrierung."""

    def is_open_for_signup(self, request):
        return False


class AnmeldeAdapter(DefaultSocialAccountAdapter):
    """Anlegen und Prüfen von Konten, die über den Anbieter kommen."""

    def is_open_for_signup(self, request, sociallogin):
        # Verzeichnis und pre_social_login haben das Konto bereits
        # zugelassen.
        return True

    def pre_social_login(self, request, sociallogin):
        """Lehnt Konten ohne bekannte Rolle mit 403 ab.

        Läuft vor dem Anlegen und vor dem Anmelden; ein abgelehntes Konto
        wird nicht angelegt. Bei bestehenden Konten überträgt die Methode
        außerdem die Rollen.
        """
        rollen = bekannte_rollen(sociallogin.account.extra_data)
        if not rollen:
            raise ImmediateHttpResponse(render(
                request, 'admin/sso_kein_zugang.html',
                {'anbieter': settings.SSO_NAME,
                 'anmeldung': reverse('admin:login')},
                status=403,
            ))
        # allauth hat ein bestehendes Konto mit lookup() geladen und die
        # aktuellen Claims eingetragen. Neue Konten behandelt save_user.
        if sociallogin.is_existing:
            rollen_uebernehmen(sociallogin.user, rollen)

    def save_user(self, request, sociallogin, form=None):
        """Speichert ein neues Konto und überträgt danach die Rollen."""
        user = super().save_user(request, sociallogin, form)
        rollen_uebernehmen(user, bekannte_rollen(sociallogin.account.extra_data))
        return user

    def populate_user(self, request, sociallogin, data):
        """Setzt ``username`` auf die Anmeldeadresse aus dem Verzeichnis.

        allauth bildet sonst Namen wie ``erika``, ``erika2``, die sich keinem
        Konto im Verzeichnis zuordnen lassen.
        """
        user = super().populate_user(request, sociallogin, data)
        a = ansprueche(sociallogin.account.extra_data)
        kennung = a.get('preferred_username') or a.get('email')
        if kennung:
            user.username = kennung
        if not user.email and a.get('email'):
            user.email = a['email']
        return user


def sso_anmeldung(request):
    """Kontextprozessor: Button für SSO auf der Anmeldeseite, falls konfiguriert."""
    if not settings.SSO_CLIENT_ID:
        return {}
    return {'sso_anmeldung': {
        'name': settings.SSO_NAME,
        'adresse': reverse('openid_connect_login',
                           kwargs={'provider_id': settings.SSO_PROVIDER_ID}),
    }}


def anbieter_erreichbar(view):
    """Decorator für die Login-Views von allauth: 503 mit Hinweisseite bei
    nicht erreichbarem Anbieter.

    allauth fängt Netzwerkfehler beim Discovery-Abruf nicht ab; der Benutzer
    erhielte eine 500 ohne Hinweis auf den lokalen Login. Abgefangen wird nur
    ``requests.RequestException``, damit andere Fehler sichtbar bleiben.
    """
    @wraps(view)
    def eingehuellt(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except requests.RequestException:
            logger.exception('Anmeldung: %s nicht erreichbar.', settings.SSO_NAME)
            return render(
                request, 'admin/sso_nicht_erreichbar.html',
                {'anbieter': settings.SSO_NAME,
                 'anmeldung': reverse('admin:login')},
                status=503,
            )
    return eingehuellt
