"""Rechte der Dienstgruppe "Faktura Dienst".

``faktura_rechte`` legt die Gruppe an; sie gehört zum Kern, weil die
Archiv-Anbindung sie verwendet.
"""

import pytest

# ---------------------------------------------------------------------------
# Rechte eines Dienstzugangs
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDienstgruppe:
    """Rechte der Gruppe "Faktura Dienst" nach faktura_rechte.

    Ein Automatisierungslauf darf lesen und die Archivfelder setzen, sonst
    nichts.
    """

    @pytest.fixture(autouse=True)
    def gruppen(self):
        from io import StringIO

        from django.core.management import call_command

        call_command('faktura_rechte', stdout=StringIO())

    @property
    def dienst(self):
        from django.contrib.auth.models import Group

        return Group.objects.get(name='Faktura Dienst')

    def _hat(self, codename: str) -> bool:
        return self.dienst.permissions.filter(codename=codename).exists()

    def test_darf_belege_lesen(self):
        assert self._hat('view_beleg')
        assert self._hat('view_projekt')
        assert self._hat('view_kontakt')

    def test_darf_die_ablage_vermerken(self):
        assert self._hat('archivieren_beleg')

    def test_darf_belege_nicht_aendern(self):
        """Ohne ``change_beleg`` und damit ohne Festschreiben, weil
        versehentlich festgeschriebene Rechnungen nur noch storniert werden
        können."""
        assert not self._hat('change_beleg')

    def test_darf_nichts_anlegen_und_nichts_loeschen(self):
        verboten = self.dienst.permissions.filter(
            codename__regex=r'^(add|delete|change)_').values_list('codename', flat=True)

        assert list(verboten) == []

    def test_sieht_die_firmendaten_nicht(self):
        """Ohne Zugriff auf die Firma, weil ein Dienstzugang diese Angaben über
        das PDF erhält."""
        assert not self._hat('view_firma')

    def test_waechst_mit_neuen_modellen_mit(self):
        """Die Lesegruppe leitet ihre Rechte aus derselben Modellliste ab wie
        die Arbeitsgruppe; ein neues Modell dort erhält das View-Recht."""
        from faktura.management.commands.faktura_rechte import OHNE_DIENST, VOLL

        erwartet = {f'view_{modell}' for modell in VOLL if modell not in OHNE_DIENST}
        vorhanden = set(self.dienst.permissions.values_list('codename', flat=True))

        assert erwartet <= vorhanden
