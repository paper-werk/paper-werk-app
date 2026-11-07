"""Wonach sich Belege einschränken lassen.

Über fachliche Nummern, nicht Datenbankschlüssel: ``?kunde=K-1024``, nicht
``?kunde=17``. Die Gegenstelle kennt die Nummern aus den Belegen.
"""

from django_filters import rest_framework as filters

from faktura.models import Beleg, BelegStatus, BelegTyp

from .anbindung import BelegAnbindungFilter


class BelegFilter(BelegAnbindungFilter):
    """Die Filter der Anbindung (Belegnummer, Dokument-ID, Profil, XML),
    dazu die für Archivierungsläufe und Auswertungen."""

    typ = filters.ChoiceFilter(choices=BelegTyp.choices)
    status = filters.ChoiceFilter(choices=BelegStatus.choices)

    kunde = filters.CharFilter(
        field_name='kunde__nummer', lookup_expr='iexact',
        label='Kundennummer',
    )
    projekt = filters.CharFilter(
        field_name='projekt__nummer', lookup_expr='iexact',
        label='Projektnummer',
    )
    belegdatum_ab = filters.DateFilter(
        field_name='belegdatum', lookup_expr='gte', label='Belegdatum ab')
    belegdatum_bis = filters.DateFilter(
        field_name='belegdatum', lookup_expr='lte', label='Belegdatum bis')

    # IsoDateTimeFilter: Der "letzte Lauf" ist ein ISO-8601-Zeitstempel mit
    # Zeitzone; DateTimeFilter würfe einen Teil davon still weg.
    festgeschrieben_ab = filters.IsoDateTimeFilter(
        field_name='festgeschrieben_am', lookup_expr='gte',
        label='Festgeschrieben ab (ISO-8601)',
    )
    festgeschrieben_bis = filters.IsoDateTimeFilter(
        field_name='festgeschrieben_am', lookup_expr='lte',
        label='Festgeschrieben bis (ISO-8601)',
    )

    archiviert = filters.BooleanFilter(
        method='nach_archivierung',
        label='Liegt bereits im Archiv',
    )

    class Meta:
        model = Beleg
        fields = []

    def nach_archivierung(self, queryset, name, wert):
        """``?archiviert=false`` liefert, was noch abzulegen ist."""
        return queryset.filter(paperless_id__isnull=not wert)
