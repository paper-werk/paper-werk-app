"""Seitenleiste aus den Einträgen der Apps.

Jede App registriert ihre Einträge in ``ready()``. Geprüft wird das von
Unfold zusammengesetzte Ergebnis (``AdminSite.get_sidebar_list``);
``ERWARTET`` enthält die Seitenleiste Zeile für Zeile.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()

#: (Abschnittstitel, separator, collapsible, [(Titel, Icon, URL-Name), ...])
ERWARTET = [
    ('Übersicht', False, False, [
        ('Startseite', 'dashboard', 'admin:index'),
        ('Controlling', 'monitoring', 'controlling'),
    ]),
    ('Projekte', True, False, [
        ('Projekte', 'construction', 'admin:faktura_projekt_changelist'),
        ('Angebote', 'request_quote', 'admin:faktura_angebot_changelist'),
        ('Aufträge', 'handshake', 'admin:faktura_auftrag_changelist'),
        ('Abnahmen', 'task_alt', 'admin:faktura_abnahme_changelist'),
        ('Lieferscheine', 'local_shipping',
         'admin:faktura_lieferschein_changelist'),
    ]),
    ('Rechnungen', True, False, [
        ('Rechnungen', 'receipt_long', 'admin:faktura_rechnung_changelist'),
        ('Abschlagsrechnungen', 'hourglass_top',
         'admin:faktura_abschlagsrechnung_changelist'),
        ('Schlussrechnungen', 'done_all',
         'admin:faktura_schlussrechnung_changelist'),
        ('Mahnungen', 'notification_important',
         'admin:faktura_mahnung_changelist'),
        ('Zahlungseingänge', 'payments', 'admin:faktura_zahlung_changelist'),
    ]),
    # Eingeklappt.
    ('Weitere Rechnungsarten', True, True, [
        ('Teilschlussrechnungen', 'rule',
         'admin:faktura_teilschlussrechnung_changelist'),
        ('Stornorechnungen', 'undo',
         'admin:faktura_stornorechnung_changelist'),
        ('Rechnungskorrekturen', 'edit_document',
         'admin:faktura_rechnungskorrektur_changelist'),
    ]),
    ('Leistung', True, False, [
        ('Erfassung', 'schedule',
         'admin:erfassung_erfassungszeile_changelist'),
        ('Nicht abgerechnet', 'savings', 'liegengeblieben'),
        ('Eingangsrechnungen', 'receipt_long',
         'admin:erfassung_eingangsrechnung_changelist'),
    ]),
    ('Stammdaten', True, True, [
        ('Kontakte', 'groups', 'admin:faktura_kontakt_changelist'),
        ('Leistungskatalog', 'format_list_bulleted',
         'admin:faktura_katalogposition_changelist'),
        ('Textbausteine', 'notes', 'admin:faktura_textbaustein_changelist'),
        ('Kostensätze', 'payments', 'admin:erfassung_kostensatz_changelist'),
        ('Steuersätze', 'percent', 'admin:faktura_steuersatz_changelist'),
        ('Eigene Firma', 'apartment', 'admin:faktura_firma_changelist'),
    ]),
    ('Verwaltung', True, True, [
        ('Benutzer', 'person', 'admin:core_user_changelist'),
        ('Gruppen', 'shield_person', 'admin:auth_group_changelist'),
        ('API-Schlüssel', 'key', 'admin:authtoken_tokenproxy_changelist'),
    ]),
    # Aus hilfe/apps.py.
    ('Hilfe', True, False, [
        ('Bedienungsanleitung', 'help', 'hilfe'),
    ]),
]


@pytest.fixture
def verwalterin(db):
    """Superuser, für den ``has_perm`` immer wahr ist, sodass jeder Eintrag
    erscheint."""
    return User.objects.create_superuser(
        'chefin', 'chefin@example.invalid', 'geheim')


@pytest.mark.django_db
def test_die_seitenleiste_ist_unveraendert(client, verwalterin):
    client.force_login(verwalterin)

    antwort = client.get(reverse('admin:index'))
    abschnitte = antwort.context['sidebar_navigation']

    ergebnis = [
        (
            abschnitt['title'],
            bool(abschnitt.get('separator')),
            bool(abschnitt.get('collapsible')),
            [(eintrag['title'], eintrag['icon'], str(eintrag['link']))
             for eintrag in abschnitt['items']],
        )
        for abschnitt in abschnitte
    ]
    erwartet = [
        (titel, separator, collapsible,
         [(titel_e, icon, reverse(name))
          for titel_e, icon, name in eintraege])
        for titel, separator, collapsible, eintraege in ERWARTET
    ]

    assert ergebnis == erwartet


@pytest.mark.django_db
def test_der_zaehler_nennt_die_entwuerfe(client, verwalterin):
    """Zähler an "Rechnungen", in der gerenderten Seitenleiste geprüft. Ohne
    Entwurf kein Zähler, mit einem 1."""
    import re

    from faktura import services
    from faktura.models import BelegTyp, Kontakt

    client.force_login(verwalterin)

    def zaehler():
        seite = client.get(reverse('admin:index')).content.decode()
        return re.findall(r'class="sidebar-badge[^"]*"[^>]*>\s*(\S+)\s*<', seite)

    assert zaehler() == []

    kunde = Kontakt.anlegen(nummer='K-1', name='Muster', strasse='Weg 1',
                            plz='80331', ort='München')
    services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG)

    assert zaehler() == ['1']


@pytest.mark.django_db
def test_jede_rechnungsart_zaehlt_ihre_eigenen_entwuerfe(client, verwalterin):
    """Zähler je Rechnungsart, auch an Abschlags-, Schluss- und
    Teilschlussrechnungen.

    Getrennt je Art: Zwei Abschlagsentwürfe zählen bei
    "Abschlagsrechnungen". Gelesen in der Reihenfolge der Seitenleiste
    (Rechnungen, Abschlag, Schluss, eingeklappter Teilschluss). Die
    Teilschlussrechnung wird direkt angelegt, ohne Abnahme.
    """
    import re

    from faktura import services
    from faktura.models import Beleg, BelegStatus, BelegTyp, Kontakt, Rechnungsart

    client.force_login(verwalterin)

    def zaehler():
        seite = client.get(reverse('admin:index')).content.decode()
        return re.findall(r'class="sidebar-badge[^"]*"[^>]*>\s*(\S+)\s*<', seite)

    kunde = Kontakt.anlegen(nummer='K-1', name='Muster', strasse='Weg 1',
                            plz='80331', ort='München')
    for art, anzahl in ((Rechnungsart.ABSCHLAG, 2), (Rechnungsart.SCHLUSS, 3)):
        for _ in range(anzahl):
            services.beleg_anlegen(kunde=kunde, typ=BelegTyp.RECHNUNG,
                                   rechnungsart=art)
    Beleg.objects.create(typ=BelegTyp.RECHNUNG, status=BelegStatus.ENTWURF,
                         rechnungsart=Rechnungsart.TEILSCHLUSS, kunde=kunde)

    assert zaehler() == ['2', '3', '1']
