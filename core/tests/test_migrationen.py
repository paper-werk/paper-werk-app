"""Prüft, dass zu jeder Modelländerung eine Migration existiert.

Sonst fiele eine fehlende Migration erst im Betrieb auf: Der Container
migriert beim Start, findet nichts, und das Schema passt nicht zum Code.
"""

from io import StringIO

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_keine_migration_fehlt():
    ausgabe = StringIO()
    try:
        call_command('makemigrations', '--check', '--dry-run', stdout=ausgabe)
    except SystemExit:
        pytest.fail(f'Es fehlt eine Migration:\n{ausgabe.getvalue()}')
