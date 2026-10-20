"""Benutzer, Gruppen und API-Schlüssel im Admin.

Django, DRF, allauth und django-sequences registrieren ihre Modelle selbst,
mit Djangos Widgets. Dieses Modul deregistriert sie und registriert sie neu mit
Unterklassen, die zusätzlich von Unfolds ``ModelAdmin`` erben. Die Klasse der
Bibliothek steht in der MRO vorn, damit ihre Logik gilt.
"""

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from django import forms
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.hashers import UNUSABLE_PASSWORD_PREFIX
from django.contrib.auth.models import Group
from rest_framework.authtoken.admin import TokenAdmin as DRFTokenAdmin
from rest_framework.authtoken.models import TokenProxy
from sequences.models import Sequence
from unfold.admin import ModelAdmin
from unfold.forms import (
    AdminPasswordChangeForm,
    UnfoldReadOnlyPasswordHashWidget,
    UserChangeForm,
    UserCreationForm,
)

from .adminhilfen import Kopfleiste
from .models import User

#: Flags, die ein Konto für den Admin und die Benutzerverwaltung braucht. Ohne
#: ``is_active`` oder ``is_staff`` ist kein Login in den Admin möglich, ohne
#: ``is_superuser`` antwortet die Benutzerverwaltung mit 403.
VERWALTER = {'is_active': True, 'is_staff': True, 'is_superuser': True}

#: Fehlermeldung beim Herabstufen und beim Löschen des letzten Verwalters.
OHNE_VERWALTER = (
    'Danach gäbe es kein aktives Konto mit Administrator- und '
    'Mitarbeiter-Status mehr, und damit niemanden, der das über diese '
    'Oberfläche wieder rückgängig machen könnte. Zuerst einem anderen Konto '
    'diese Rechte geben.'
)


def bleibt_ein_verwalter(ohne) -> bool:
    """True, wenn es außer den Konten in ``ohne`` noch einen Verwalter gibt."""
    return (User.objects.filter(**VERWALTER)
            .exclude(pk__in=[konto.pk for konto in ohne])
            .exists())


class PasswortKnopf(UnfoldReadOnlyPasswordHashWidget):
    """Ersetzt die Anzeige von Algorithmus, Salt und Hash durch einen Link zur
    Passwortmaske.

    Die Beschriftung ist deutsch, weil Django 6.1 sie nicht übersetzt.
    """

    template_name = 'core/widgets/passwort_knopf.html'

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        nutzbar = value and not value.startswith(UNUSABLE_PASSWORD_PREFIX)
        context['button_label'] = ('Passwort zurücksetzen' if nutzbar
                                   else 'Passwort setzen')
        return context


class BenutzerAendernForm(UserChangeForm):
    """Unfolds ``UserChangeForm`` mit Schutz des letzten Verwalters.

    Django erlaubt dem letzten Verwalter, sich selbst die Rechte zu entziehen.
    Danach hilft nur ``manage.py createsuperuser`` auf dem Server.

    Abgelehnt wird der Übergang von Verwalter zu Nicht-Verwalter. Konten, die
    schon kein Verwalter sind, bleiben bearbeitbar. Die Prüfung liegt in
    ``clean()``, damit die Meldung im Formular erscheint; der Ausgangszustand
    wird aus der Datenbank gelesen.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'password' in self.fields:
            self.fields['password'].widget = PasswortKnopf()
            # Djangos Hilfetext ist in 6.1 nicht übersetzt und wiederholt die
            # Beschriftung des Links.
            self.fields['password'].help_text = ''

    def clean(self):
        daten = super().clean()
        war_verwalter = User.objects.filter(pk=self.instance.pk, **VERWALTER).exists()
        bleibt_verwalter = all(
            daten.get(feld, getattr(self.instance, feld)) for feld in VERWALTER
        )
        if (war_verwalter and not bleibt_verwalter
                and not bleibt_ein_verwalter(ohne=[self.instance])):
            raise forms.ValidationError(OHNE_VERWALTER, code='letzter_verwalter')
        return daten


@admin.register(User)
class UserAdmin(Kopfleiste, BaseUserAdmin, ModelAdmin):
    """Djangos ``UserAdmin`` mit Unfold-Oberfläche.

    ``BaseUserAdmin`` steht in der MRO vor Unfolds ``ModelAdmin``, weil sonst
    Unfolds ``get_fieldsets`` greift und die Anlegemaske keine Passwortfelder
    hat. ``form``, ``add_form`` und ``change_password_form`` sind explizit
    gesetzt, weil sonst Djangos Formulare gelten.
    """

    form = BenutzerAendernForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm

    # Dazu ``is_active``: Konten ausgeschiedener Mitarbeiter werden
    # deaktiviert, weil ``Beleg.festgeschrieben_von`` (PROTECT) das Löschen
    # verhindert.
    list_display = BaseUserAdmin.list_display + ('is_active',)

    def get_deleted_objects(self, objs, request):
        """Verhindert das Löschen des letzten Verwalters.

        Django ruft die Methode auf der Löschseite und bei der Sammelaktion
        auf. Ist ``protected`` nicht leer, wird nicht gelöscht; der Eintrag
        enthält die Meldung.
        """
        geloescht, anzahl, rechte, geschuetzt = super().get_deleted_objects(objs, request)
        konten = list(objs)
        verwalter = [k for k in konten
                     if User.objects.filter(pk=k.pk, **VERWALTER).exists()]
        if verwalter and not bleibt_ein_verwalter(ohne=konten):
            geschuetzt = [*geschuetzt,
                          *(f'{k} - {OHNE_VERWALTER}' for k in verwalter)]
        return geloescht, anzahl, rechte, geschuetzt

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2', 'email', 'first_name', 'last_name'),
        }),
    )

    # Dieselben Auswahlfelder wie im GroupAdmin, daher dieselbe Stildatei.
    class Media:
        css = {'all': ['core/css/auswahlfelder.css']}


admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(Kopfleiste, BaseGroupAdmin, ModelAdmin):
    """Djangos ``GroupAdmin`` mit Unfold-Oberfläche.

    Die Stildatei setzt die Höhe der Auswahlfelder. Ohne ``size``-Attribut
    zeigt der Browser von rund zweihundert Rechten nur vier Zeilen.
    """

    class Media:
        css = {'all': ['core/css/auswahlfelder.css']}


# Die Nummernkreise aus django-sequences (faktura.services.NUMMERNKREIS).
admin.site.unregister(Sequence)


@admin.register(Sequence)
class SequenceAdmin(Kopfleiste, ModelAdmin):
    list_display = ('name', 'last')

    # Schreibgeschützt, weil ein geänderter Zähler doppelte oder
    # übersprungene Rechnungsnummern erzeugt.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# Die API-Schlüssel (DRFs TokenProxy).
admin.site.unregister(TokenProxy)


@admin.register(TokenProxy)
class TokenProxyAdmin(Kopfleiste, DRFTokenAdmin, ModelAdmin):
    """API-Schlüssel anlegen, ansehen, einem anderen Benutzer zuordnen, löschen.

    ``TokenProxy.pk`` ist die Benutzer-ID. DRFs ``TokenAdmin`` setzt sie in
    ``get_object``, in den Links der Liste und in ``delete_model`` in den
    Schlüssel um. Ohne diese Basisklasse leitet der Admin nach dem Anlegen
    auf einen Schlüssel "5" weiter und landet auf der Startseite.

    ``Token.save`` erzeugt den Schlüssel. Beim Anlegen wird nur der Benutzer
    gewählt, danach zeigt die Maske den Schlüssel.
    """

    list_display = ('key', 'user', 'created')
    list_select_related = ('user',)
    ordering = ('-created',)
    readonly_fields = ('key', 'created')

    def get_fields(self, request, obj=None):
        if obj is None:
            return ['user']
        return ['user', 'key', 'created']


# Modelle von allauth (Anmeldung über Microsoft, core/anmeldung.py).
#
# Drei der vier Modelle erscheinen nicht im Admin:
#   SocialApp     Der Anbieter ist in SOCIALACCOUNT_PROVIDERS konfiguriert
#                 (Settings, aus der .env). Ein Eintrag im Admin würde nicht
#                 wirken.
#   SocialToken   Wird nicht gespeichert (allauth-Vorgabe
#                 SOCIALACCOUNT_STORE_TOKENS = False).
#   EmailAddress  allauths Adressverwaltung; die Mailadresse steht am User.
admin.site.unregister(SocialApp)
admin.site.unregister(SocialToken)
admin.site.unregister(EmailAddress)

admin.site.unregister(SocialAccount)


@admin.register(SocialAccount)
class SocialAccountAdmin(Kopfleiste, ModelAdmin):
    """Zuordnung von User zu Microsoft-Konto, schreibgeschützt.

    Einträge entstehen nur bei der Anmeldung. Eine von Hand geänderte ``uid``
    würde das Konto mit einem fremden Microsoft-Konto verknüpfen.
    """

    list_display = ('user', 'provider', 'last_login', 'date_joined')
    list_select_related = ('user',)
    readonly_fields = ('user', 'provider', 'uid', 'last_login',
                       'date_joined', 'extra_data')
    ordering = ('-last_login',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
