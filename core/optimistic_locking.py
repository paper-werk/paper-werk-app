"""Optimistic Locking für Modelle mit Spalte ``version``.

``version`` wird bei jedem Update inkrementiert. Das Admin-Formular
sendet die beim Laden gelesene Version mit. Weicht sie beim Speichern
vom Wert in der Datenbank ab, wurde der Datensatz zwischenzeitlich
geändert, und das Speichern scheitert mit ``VersionKonflikt``.

Schnittstelle: ``MitVersion`` (abstrakte Modellbasis),
``ErhoehtElternversion`` (abstrakte Basis für Inline-Zeilen),
``VersionAdminMixin``, ``version_erhoehen`` (für Schreibzugriffe ohne
``save()``), ``VersionKonflikt`` und ``FELD`` (für ``excluded_fields`` von
``HistoricalRecords``). Der Feldname kommt nur in diesem Modul vor,
``tests/test_grenzzaun.py`` prüft das.

Modelle mit ``HistoricalRecords`` schließen ``FELD`` aus: Während
``post_save`` steht in ``version`` noch der ``F()``-Ausdruck, den
simple_history nicht in die History-Tabelle einfügen kann.

Kein ``django-concurrency``: Die Bibliothek prüft in jedem ``save()``,
hier prüft nur das Formular. Services laden mit ``select_for_update``
und inkrementieren ohne Prüfung. Außerdem unterstützte sie im Oktober
2026 Django 6.1 noch nicht. Bei einem Wechsel wird ``MitVersion`` ein
``IntegerVersionField`` mit gleichem Spaltennamen und das Mixin erbt
von ``ConcurrentModelAdmin``. Dann prüfen auch die Services.
"""

from django import forms
from django.apps import apps
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone
from django.utils.html import format_html

#: Spalte am Modell.
FELD = 'version'
#: Verstecktes Formularfeld mit der Version beim Laden.
FORMULARFELD = 'version_beim_laden'


class VersionKonflikt(ValidationError):
    """Die Version beim Laden weicht von der Version in der Datenbank ab."""


class MitVersion(models.Model):
    """Abstrakte Modellbasis mit Spalte ``version``."""

    version = models.PositiveIntegerField(
        'Version', default=0, editable=False,
        db_comment='Optimistic Locking: wird bei jedem Update inkrementiert '
                   'und beim Speichern im Admin mit der Version beim Laden '
                   'verglichen.',
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        """Inkrementiert per ``F() + 1`` in der Datenbank. Ein Inkrement
        im Speicher würde Inkremente aus ``version_erhoehen`` (etwa durch
        Positionen) überschreiben."""
        if self._state.adding:
            return super().save(*args, **kwargs)

        vorher = getattr(self, FELD)
        setattr(self, FELD, F(FELD) + 1)
        felder = kwargs.get('update_fields')
        if felder is not None:
            kwargs['update_fields'] = {*felder, FELD}
        try:
            super().save(*args, **kwargs)
        except BaseException:
            setattr(self, FELD, vorher)
            raise
        self.refresh_from_db(fields=[FELD])


class ErhoehtElternversion(models.Model):
    """Abstrakte Basis für abhängige Zeilen (Inlines): ``save()`` und
    ``delete()`` inkrementieren die Version der Fremdschlüssel in
    ``version_eltern``.

    Der Admin speichert das Elternobjekt ohnehin bei jedem Speichern. Das
    Inkrement hier deckt Schreibzugriffe von Services auf die Zeilen ab.
    """

    #: Namen der Fremdschlüssel auf Modelle mit ``MitVersion``.
    version_eltern: tuple[str, ...] = ()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        for modell, pk in self._eltern():
            version_erhoehen(modell, pk)

    def delete(self, *args, **kwargs):
        eltern = self._eltern()
        ergebnis = super().delete(*args, **kwargs)
        for modell, pk in eltern:
            version_erhoehen(modell, pk)
        return ergebnis

    def _eltern(self):
        return [(self._meta.get_field(name).related_model,
                 getattr(self, self._meta.get_field(name).attname))
                for name in self.version_eltern]


def version_erhoehen(modell, pk) -> None:
    """Inkrementiert die Version per ``UPDATE``. Für Schreibzugriffe ohne
    ``save()`` (``QuerySet.update()``, ``bulk_create``) und für abhängige
    Zeilen wie Belegpositionen."""
    if pk is None:
        return
    modell._meta.concrete_model._base_manager.filter(pk=pk).update(
        **{FELD: F(FELD) + 1})


def _version_gesperrt(instanz) -> int | None:
    """Aktuelle Version mit ``SELECT … FOR UPDATE``.

    ``changeform_view`` läuft in einer Transaktion, der Lock hält also bis
    nach dem Speichern von Kopf und Inlines. Ein paralleler Request wartet
    und liest danach die inkrementierte Version.
    """
    modell = instanz._meta.concrete_model
    with transaction.atomic():
        return (modell._base_manager.select_for_update()
                .filter(pk=instanz.pk)
                .values_list(FELD, flat=True)
                .first())


def _letzter_logeintrag(instanz):
    """Jüngster ``LogEntry`` zum Datensatz über alle Proxy-Modelle.

    Der Admin protokolliert unter dem Content Type des Proxys (Rechnung,
    Angebot), nicht unter dem des konkreten Modells.
    """
    konkret = instanz._meta.concrete_model
    modelle = [m for m in apps.get_models()
               if m._meta.concrete_model is konkret]
    typen = ContentType.objects.get_for_models(
        *modelle, for_concrete_models=False).values()
    return (LogEntry.objects
            .filter(content_type__in=typen, object_id=str(instanz.pk))
            .select_related('user')
            .order_by('-action_time')
            .first())


def konfliktmeldung(instanz) -> str:
    """Text zu ``VersionKonflikt`` als HTML, mit Link auf die
    Änderungsseite per GET (``href=""``).

    "Letzte Änderung" ist der letzte ``LogEntry``. Schreibzugriffe ohne
    ``LogEntry`` (etwa Services ohne Admin) erscheinen dort nicht.
    """
    letzte = ''
    eintrag = _letzter_logeintrag(instanz)
    if eintrag is not None:
        wer = eintrag.user.get_full_name() or eintrag.user.get_username()
        wann = timezone.localtime(eintrag.action_time)
        letzte = f' Letzte Änderung: {wer}, {wann:%d.%m.%Y um %H:%M}.'
    return format_html(
        'Ihre Eingaben konnten nicht gespeichert werden. Die Daten sind '
        'nicht mehr aktuell.{} <a href="" class="underline font-semibold">'
        'Aktuellen Stand laden</a>', letzte)


class VersionAdminMixin:
    """``ModelAdmin``-Mixin für Modelle mit ``MitVersion``.

    Ergänzt das Änderungsformular um ``version_beim_laden`` (Hidden Input)
    und prüft es in ``clean()``. Fehlt das Feld im POST, entfällt die
    Prüfung.

    Belegt ``change_form_before_template``. Eine eigene Vorlage dort muss
    ``admin/version.html`` einbinden.
    """

    change_form_before_template = 'admin/version.html'

    def render_change_form(self, request, context, *args, **kwargs):
        """Bei ``VersionKonflikt``: Formular mit den Eingaben ohne
        Speichern-Buttons, Ausweg ist der Link in der Meldung.

        Ein erneutes Speichern aus diesem Formular scheiterte immer wieder,
        weil ``version_beim_laden`` die alte Version behält. Die Sammelzeile
        "Bitte die unten aufgeführten Fehler korrigieren" entfällt, unten
        gibt es nichts zu korrigieren.
        """
        adminform = context.get('adminform')
        if adminform is not None and adminform.form.has_error(
                NON_FIELD_ERRORS, 'version_konflikt'):
            context['errors'] = []
            context.update(show_save=False, show_save_and_continue=False,
                           show_save_and_add_another=False)
        return super().render_change_form(  # type: ignore[misc]
            request, context, *args, **kwargs)

    def get_form(self, request, obj=None, **kwargs):
        formular = super().get_form(request, obj, **kwargs)  # type: ignore[misc]
        if obj is None:
            return formular

        class MitVersionspruefung(formular):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.fields[FORMULARFELD] = forms.IntegerField(
                    widget=forms.HiddenInput, required=False,
                    initial=getattr(self.instance, FELD))

            def clean(self):
                # Vor den übrigen Prüfungen: Bei einem Konflikt sind deren
                # Meldungen gegenstandslos.
                gesendet = self.cleaned_data.get(FORMULARFELD)
                if gesendet is not None and self.instance.pk is not None:
                    if _version_gesperrt(self.instance) != gesendet:
                        raise VersionKonflikt(konfliktmeldung(self.instance),
                                              code='version_konflikt')
                return super().clean()

        MitVersionspruefung.__name__ = formular.__name__
        MitVersionspruefung.__qualname__ = formular.__qualname__
        return MitVersionspruefung
