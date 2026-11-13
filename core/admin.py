"""Benutzer, Gruppen, API-Schlüssel und Ereignisregeln im Admin.

Django, DRF, allauth und django-sequences registrieren ihre Modelle selbst,
mit Djangos Widgets. Dieses Modul deregistriert sie und registriert sie neu mit
Unterklassen, die zusätzlich von Unfolds ``ModelAdmin`` erben. Die Klasse der
Bibliothek steht in der MRO vorn, damit ihre Logik gilt.
"""

import requests
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from axes.admin import AccessAttemptAdmin as AxesAccessAttemptAdmin
from axes.admin import IsLockedOutFilter
from axes.models import AccessAttempt, AccessFailureLog, AccessLog
from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.hashers import UNUSABLE_PASSWORD_PREFIX
from django.contrib.auth.models import Group
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.admin import TokenAdmin as DRFTokenAdmin
from rest_framework.authtoken.models import TokenProxy
from sequences.models import Sequence
from unfold.admin import ModelAdmin
from unfold.decorators import action as unfold_action
from unfold.forms import (
    AdminPasswordChangeForm,
    AuthenticationForm,
    UnfoldReadOnlyPasswordHashWidget,
    UserChangeForm,
    UserCreationForm,
)
from unfold.widgets import UnfoldAdminCheckboxSelectMultipleWidget, UnfoldAdminSelectWidget

from . import erweiterungen, webhooks
from .adminhilfen import Kopfleiste, weitere
from .models import Ereignisregel, User

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



class Anmeldeformular(AuthenticationForm):
    """Anmeldung am Admin mit eigener Meldung bei falschen Zugangsdaten.

    Djangos Text verlangt einen „Staff-Account“. Dieselbe Meldung gilt für
    ein Konto ohne Mitarbeiter-Status, damit die Antwort nicht verrät, ob
    der Benutzername existiert. Abgeleitet von Unfolds Formular, das die
    Eingabefelder gestaltet.
    """

    error_messages = {
        **AuthenticationForm.error_messages,
        'invalid_login': 'Benutzername oder Passwort falsch.',
    }


admin.site.login_form = Anmeldeformular
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

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'user':
            kwargs['help_text'] = (
                'Der Schlüssel handelt mit allen Rechten dieses Benutzers, '
                'auch beim Festschreiben. Für Workflows einen Benutzer der '
                'Gruppe „Faktura Dienst“ wählen.')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


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


class EreignisregelForm(forms.ModelForm):
    """Maske einer Ereignisregel. Die Auswahl für Ereignis, Aktionen und
    Typen kommt aus den registrierten Ereignisquellen
    (``core.erweiterungen.ereignisquelle``), weil ``core`` die Fachobjekte
    nicht kennt."""

    quelle = forms.ChoiceField(label='Ereignis', widget=UnfoldAdminSelectWidget)
    aktionen = forms.MultipleChoiceField(
        label='Aktionen', required=False,
        widget=UnfoldAdminCheckboxSelectMultipleWidget,
        help_text='Ohne Auswahl gilt die Regel für alle Aktionen.')
    typen = forms.MultipleChoiceField(
        label='Typen', required=False,
        widget=UnfoldAdminCheckboxSelectMultipleWidget,
        help_text='Ohne Auswahl gilt die Regel für alle Typen.')

    class Meta:
        model = Ereignisregel
        fields = ['name', 'aktiv', 'quelle', 'aktionen', 'typen', 'url', 'token']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        quellen = erweiterungen.ereignisquellen().values()
        self.fields['quelle'].choices = [(q.name, q.titel) for q in quellen]
        self.fields['aktionen'].choices = _vereinigung(q.aktionen for q in quellen)
        self.fields['typen'].choices = _vereinigung(q.typen for q in quellen)

    def clean(self):
        """Aktionen und Typen müssen zur gewählten Quelle gehören."""
        daten = super().clean()
        quelle = erweiterungen.ereignisquellen().get(daten.get('quelle'))
        if quelle is None:
            return daten
        for feld, erlaubt in (('aktionen', quelle.aktionen), ('typen', quelle.typen)):
            werte = {wert for wert, _ in erlaubt}
            fremd = [w for w in daten.get(feld) or [] if w not in werte]
            if fremd:
                self.add_error(feld, f'Gehört nicht zu "{quelle.titel}": '
                                     f'{", ".join(fremd)}.')
        return daten


def _vereinigung(listen) -> list[tuple[str, str]]:
    """Choices mehrerer Quellen ohne Doppelte, in erster Reihenfolge."""
    ergebnis: dict[str, str] = {}
    for liste in listen:
        for wert, titel in liste:
            ergebnis.setdefault(wert, titel)
    return list(ergebnis.items())


@admin.register(Ereignisregel)
class EreignisregelAdmin(Kopfleiste, ModelAdmin):
    """Regeln, die Ereignisse an externe Ziele melden (``docs/webhooks.md``).

    „Test senden“ ruft das Ziel im Request auf und zeigt Status oder Fehler
    als Meldung, weil der Anwender auf das Ergebnis wartet.
    """

    form = EreignisregelForm
    fieldsets = [
        (None, {'fields': [('name', 'aktiv')]}),
        ('Auslöser', {'fields': ['quelle', ('aktionen', 'typen')]}),
        ('Ziel', {'fields': ['url', 'token']}),
    ]
    list_display = ('name', 'aktiv', 'beschreibung', 'url')
    list_filter = ('aktiv',)
    search_fields = ('name', 'url')
    actions_detail = ['detail_test_senden', weitere()]

    @admin.display(description='Auslöser')
    def beschreibung(self, regel) -> str:
        """Filter als Satz, etwa "Rechnung, Angebot: festgeschrieben"."""
        quelle = erweiterungen.ereignisquellen().get(regel.quelle)
        if quelle is None:
            return regel.quelle
        titel_typ = dict(quelle.typen)
        titel_aktion = dict(quelle.aktionen)
        typen = ', '.join(titel_typ.get(t, t) for t in regel.typen) or quelle.titel
        aktionen = ', '.join(titel_aktion.get(a, a) for a in regel.aktionen) or 'jede Aktion'
        return f'{typen}: {aktionen}'

    @unfold_action(description='Test senden', icon='send',
                   permissions=['change'], url_path='test-senden')  # type: ignore
    def detail_test_senden(self, request, object_id):
        regel = Ereignisregel.objects.get(pk=object_id)
        try:
            antwort = webhooks.probe_senden(regel)
        except requests.RequestException as fehler:
            self.message_user(request, f'{regel.url} nicht erreicht: {fehler}',
                              level=messages.ERROR)
        except NotImplementedError as fehler:
            self.message_user(request, str(fehler), level=messages.ERROR)
        else:
            self.message_user(
                request, f'{regel.url} antwortet mit Status {antwort.status_code}.',
                level=messages.SUCCESS if antwort.ok else messages.WARNING)
        return redirect(reverse('admin:core_ereignisregel_change', args=[object_id]))


# Anmeldesperre (django-axes, AXES_* in den Settings). Nur die Fehlversuche
# erscheinen im Admin; Löschen eines Eintrags hebt die Sperre auf.
# AccessLog bleibt leer (AXES_DISABLE_ACCESS_LOG), AccessFailureLog ist
# abgeschaltet.
admin.site.unregister(AccessAttempt)
admin.site.unregister(AccessLog)
admin.site.unregister(AccessFailureLog)


@admin.register(AccessAttempt)
class AccessAttemptAdmin(Kopfleiste, AxesAccessAttemptAdmin, ModelAdmin):
    """Fehlgeschlagene Anmeldungen je Benutzername und IP-Adresse.

    Status, Filter und Aktion ersetzen die von django-axes, deren Texte
    keine deutsche Übersetzung haben. Der Status berücksichtigt
    ``AXES_COOLOFF_TIME``: ``attempt_time`` ist der letzte Fehlversuch, die
    Sperre endet eine Sperrzeit danach.
    """

    class GesperrtFilter(IsLockedOutFilter):
        title = 'Gesperrt'

    list_filter = ['attempt_time', 'path_info', GesperrtFilter]
    actions = ['abgelaufene_entfernen']

    @admin.display(description='Status')
    def status(self, obj):
        rest = settings.AXES_FAILURE_LIMIT - obj.failures_since_start
        if rest > 0:
            return f'noch {rest} Versuche'
        ende = obj.attempt_time + settings.AXES_COOLOFF_TIME
        if ende <= timezone.now():
            return 'Sperre abgelaufen'
        return f'gesperrt bis {timezone.localtime(ende):%H:%M} Uhr'

    @admin.action(description='Abgelaufene Einträge entfernen')
    def abgelaufene_entfernen(self, request, queryset):
        anzahl = self.handler.clean_expired_user_attempts(request=request)
        self.message_user(request, f'{anzahl} abgelaufene Einträge entfernt.')
