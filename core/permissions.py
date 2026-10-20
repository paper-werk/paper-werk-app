"""Rechteprüfung der API.

Die API prüft dieselben Modellrechte wie der Admin: Wer ein Modell im Admin
sehen darf, darf es über die API lesen. Eine eigene Rechteliste gibt es
nicht. Vergeben werden die Rechte über Gruppen, wie ``manage.py
faktura_rechte`` sie anlegt.
"""

from rest_framework.permissions import DjangoModelPermissions


class Modellrechte(DjangoModelPermissions):
    """``DjangoModelPermissions`` mit ``view_``-Recht für lesende Zugriffe.

    ``DjangoModelPermissions`` prüft nur schreibende Zugriffe; für GET ist
    ``perms_map`` leer. Ein Dienstbenutzer, der Belege abholen soll, könnte
    damit auch Kundenanschriften und Kalkulationen lesen.

    Geprüft wird deshalb ``view_``, das Recht, das Django zu jedem Modell
    anlegt und der Admin für Liste und Detailansicht prüft. Auch ``OPTIONS``
    verlangt es, weil die Feldliste eines Modells Auskunft über die Daten
    gibt.
    """

    perms_map = {
        'GET': ['%(app_label)s.view_%(model_name)s'],
        'OPTIONS': ['%(app_label)s.view_%(model_name)s'],
        'HEAD': ['%(app_label)s.view_%(model_name)s'],
        'POST': ['%(app_label)s.add_%(model_name)s'],
        'PUT': ['%(app_label)s.change_%(model_name)s'],
        'PATCH': ['%(app_label)s.change_%(model_name)s'],
        'DELETE': ['%(app_label)s.delete_%(model_name)s'],
    }
