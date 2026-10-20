"""Hilfsfunktionen der Admin-Tests von faktura."""

from django.contrib.auth import get_user_model

User = get_user_model()


def kundenformular(**felder) -> dict:
    """POST-Daten eines vollständigen Kundenformulars mit den drei Inlines.

    Als Helper, weil Anschriften, Kontaktwege und Ansprechpartner Inlines
    mit Management Form (``TOTAL_FORMS`` usw.) sind. Fehlt eine, antwortet
    der Admin mit 200 und dem Formular und ohne Redirect, was wie ein
    fachlicher Fehler aussieht.
    """
    daten = {
        'nummer': '',
        'name': 'Ohne Nummer GmbH',
        'aktiv': 'on',
        # Im Browser gesetzt; eine nicht gesendete Checkbox bedeutet "aus".
        'ist_kunde': 'on',
        'ust_id': '',
        'zahlungsziel_tage': '14',
        'skonto_prozent': '0.00',
        'skonto_tage': '0',
        'zustellweg': 'pdf_mail',
        'kaeuferreferenz': '',
        'rechnungsempfaenger': '',
        'notiz': '',
    }
    for block in ('adressen', 'kontaktwege', 'ansprechpartner'):
        daten |= {
            f'{block}-TOTAL_FORMS': '0',
            f'{block}-INITIAL_FORMS': '0',
            f'{block}-MIN_NUM_FORMS': '0',
            f'{block}-MAX_NUM_FORMS': '1000',
        }
    return daten | felder
