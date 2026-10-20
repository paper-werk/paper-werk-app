"""Standard-Textbausteine.

Regression: Manuell angelegte Bausteine gingen beim Neuaufsetzen der
Datenbank verloren; jetzt stehen sie im Code.

Geprüft wird nicht der Wortlaut, den der Betrieb ändern darf, sondern: je
Belegart eine Einleitung, Anrede und Grußformel für alle Belegarten,
Platzhalter in den Anschreiben, idempotenter Befehl.
"""

import re

import pytest
from django.core.management import call_command

from faktura import standardtexte
from faktura.models import (
    BelegTyp,
    Firma,
    Textbaustein,
    TextbausteinVerwendung,
)


@pytest.mark.django_db
def test_legt_alle_bausteine_an(firma):
    """Zwanzig Bausteine: zwölf für den Beleg, acht Anschreiben.

    Die Tabelle wird zuerst geleert, weil Migration 0047 die drei Bausteine
    der Mahnung bereits anlegt.
    """
    Textbaustein.objects.all().delete()
    neu = standardtexte.anlegen(firma)

    assert neu == 20
    assert Textbaustein.objects.count() == 20
    # Zwölf für den Beleg, acht Anschreiben für den Versand.
    assert Textbaustein.objects.filter(
        verwendung=TextbausteinVerwendung.BELEGTEXT).count() == 12
    assert Textbaustein.objects.filter(
        verwendung=TextbausteinVerwendung.MAIL).count() == 8


@pytest.mark.django_db
@pytest.mark.parametrize('belegart', [
    BelegTyp.ANGEBOT, BelegTyp.AUFTRAG, BelegTyp.LIEFERSCHEIN,
    BelegTyp.RECHNUNG,
])
def test_jede_belegart_hat_eine_einleitung(firma, belegart):
    """Jede Belegart hat eine eigene Einleitung.

    ``fuer()`` liefert spezifische und allgemeine Bausteine; geprüft wird
    der spezifische Teil.
    """
    standardtexte.anlegen(firma)

    passend = Textbaustein.objects.filter(belegart=belegart)
    assert passend.exists(), f'keine Einleitung für {belegart}'


@pytest.mark.django_db
def test_anrede_und_grussformel_gelten_ueberall(firma):
    """Anrede und Grußformel ohne Belegart, damit sie für alle gelten."""
    standardtexte.anlegen(firma)

    for name in ('Anrede', 'Grußformel'):
        assert Textbaustein.objects.get(name=name).belegart == ''

    # Damit erscheinen sie in jeder Auswahlliste.
    namen = {b.name for b in Textbaustein.fuer(
        TextbausteinVerwendung.BELEGTEXT, BelegTyp.ANGEBOT)}
    assert {'Anrede', 'Grußformel'} <= namen


@pytest.mark.django_db
def test_grussformel_traegt_den_firmennamen(firma):
    """Die Grußformel enthält den Firmennamen, weil Belegtexte keine
    Platzhalter haben."""
    standardtexte.anlegen(firma)

    text = Textbaustein.objects.get(name='Grußformel').text
    assert text == 'Mit freundlichen Grüßen\nWerkstatt Amper GmbH'


@pytest.mark.django_db
def test_ohne_firma_bleibt_die_formel_fuer_sich():
    """Ohne Firma entsteht die Formel ohne Namenszeile und ohne Platzhalter.

    Die Firma wird gelöscht, weil ``faktura/conftest.py`` sie per
    ``autouse`` für jeden Test anlegt.
    """
    Firma.objects.all().delete()

    standardtexte.anlegen()

    assert Textbaustein.objects.get(
        name='Grußformel').text == 'Mit freundlichen Grüßen'


@pytest.mark.django_db
def test_zweiter_lauf_aendert_nichts(firma):
    """Ein zweiter Lauf ändert nichts; geänderter Wortlaut bleibt."""
    standardtexte.anlegen(firma)
    eigener = Textbaustein.objects.get(name='Anrede')
    eigener.text = 'Guten Tag,'
    eigener.save()

    neu = standardtexte.anlegen(firma)

    assert neu == 0
    assert Textbaustein.objects.count() == 20
    assert Textbaustein.objects.get(name='Anrede').text == 'Guten Tag,'


@pytest.mark.django_db
def test_befehl_laeuft_auf_leerer_anlage(capsys):
    """``faktura_textbausteine`` läuft auf einer leeren Installation."""
    Firma.objects.all().delete()
    # Leer, auch ohne die Bausteine aus Migration 0047.
    Textbaustein.objects.all().delete()

    call_command('faktura_textbausteine')

    assert Textbaustein.objects.count() == 20
    ausgabe = capsys.readouterr().out
    assert '20' in ausgabe
    # Ohne Firma gibt der Befehl den Hinweis zur Grußformel aus.
    assert 'Grußformel' in ausgabe


@pytest.mark.django_db
def test_die_grundausstattung_ist_vollstaendig(firma):
    """Alle Belegtexte sind vorhanden.

    Die Textbausteine sind Grundausstattung ohne Bezug zu einem Betrieb;
    Demodaten liegen außerhalb des Repos.
    """
    standardtexte.anlegen(firma)

    vorhanden = set(Textbaustein.objects.values_list('name', flat=True))
    erwartet = {name for name, _, _ in standardtexte.BAUSTEINE}
    erwartet.add(standardtexte.GRUSSFORMEL)
    assert erwartet <= vorhanden

    assert 'Werkstatt Amper GmbH' in Textbaustein.objects.get(
        name='Grußformel').text


@pytest.mark.django_db
def test_die_anschreiben_tragen_ihre_platzhalter(firma):
    """Die Anschreiben enthalten bekannte Platzhalter.

    Anschreiben entstehen bei jedem Versand neu und sind die einzige
    Verwendung mit Platzhaltern. Geprüft wird, dass Platzhalter vorkommen
    und keine unbekannten, weil etwa "{kunde}" unverändert im Brief
    stünde.
    """
    from faktura.models import MAIL_PLATZHALTER

    standardtexte.anlegen(firma)

    anschreiben = Textbaustein.objects.filter(
        verwendung=TextbausteinVerwendung.MAIL)
    assert anschreiben.count() == 8

    erlaubt = set(MAIL_PLATZHALTER)
    for baustein in anschreiben:
        gefunden = set(re.findall(r'\{(\w+)\}', baustein.text))
        assert gefunden, f'{baustein.name} hat keinen Platzhalter'
        assert gefunden <= erlaubt, (
            f'{baustein.name} nennt {gefunden - erlaubt}; das bliebe so '
            f'im Kundenbrief stehen')

    # Ohne {betrag} beim Lieferschein, weil er nur die Lieferung nachweist.
    assert '{betrag}' not in Textbaustein.objects.get(
        name='Lieferschein', verwendung=TextbausteinVerwendung.MAIL).text
