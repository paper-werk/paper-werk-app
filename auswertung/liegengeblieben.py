"""Seite "Nicht abgerechnet": erbrachte Leistung ohne Rechnung.

Arbeitsliste nach Betrag sortiert, je Vorhaben mit dem Alter des ältesten
Postens und einem Link auf die Stelle, an der er erledigt wird.

Zwei Blöcke: oben erbrachte, nicht berechnete Leistung (wird zu einer
Ausgangsrechnung), unten bezahlte Eingangsrechnungen ohne Vorhaben (werden
zugeordnet).

Das Modul rechnet nicht selbst, wie dashboard.py und projektakte.py; die
Zahlen kommen aus den Services, die auch die Rechnung erzeugen.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from erfassung import services as erfassung_services
from faktura.models import Projekt

NULL = Decimal('0.00')


@dataclass(frozen=True)
class Liegenposten:
    """Vorhaben mit nicht abgerechneter Leistung."""

    projekt: object
    eigene: Decimal
    fremde: Decimal
    seit: object | None

    @property
    def gesamt(self) -> Decimal:
        return self.eigene + self.fremde

    @property
    def tage(self) -> int | None:
        """Alter des ältesten Postens in Tagen, ``None`` ohne Posten."""
        if self.seit is None:
            return None
        return (timezone.localdate() - self.seit).days

    @property
    def ist_alt(self) -> bool:
        """Ob der älteste Posten älter als sechzig Tage ist.

        Festgelegt, nicht hergeleitet: Bei monatlicher Abrechnung wird die
        Grenze nicht erreicht, und nach zwei Monaten lässt sich ein Posten
        noch aufklären.
        """
        return self.tage is not None and self.tage >= 60


def liegengeblieben(request):
    """Seite "Nicht abgerechnet", Recht ``faktura.view_rechnung``.

    Ohne das Recht ist die ganze Seite gesperrt, weil sie nur aus Beträgen
    besteht; die Projektakte zeigt ohne das Recht einen Teil.
    """
    if not request.user.has_perm('faktura.view_rechnung'):
        raise PermissionDenied

    eigene = erfassung_services.offene_leistung_je_projekt()
    fremde = erfassung_services.offene_fremdleistung_je_projekt()
    seit = erfassung_services.aeltester_offener_posten_je_projekt()

    projekte = {
        p.pk: p for p in Projekt.objects
        .filter(pk__in=set(eigene) | set(fremde))
        .select_related('kunde')
    }

    posten = [
        Liegenposten(
            projekt=projekt,
            eigene=eigene.get(kennung, NULL),
            fremde=fremde.get(kennung, NULL),
            seit=seit.get(kennung),
        )
        for kennung, projekt in projekte.items()
    ]
    # Größter Betrag zuerst, bei Gleichstand das ältere Vorhaben.
    posten.sort(key=lambda p: (-p.gesamt, p.seit or timezone.localdate()))

    offene_rechnungen = erfassung_services.unvollstaendige_eingangsrechnungen()

    return render(request, 'admin/liegengeblieben.html', {
        **admin.site.each_context(request),
        'title': 'Nicht abgerechnet',
        'hilfe_anker': 'liegengeblieben',
        'posten': posten,
        'summe_eigene': sum((p.eigene for p in posten), NULL),
        'summe_fremde': sum((p.fremde for p in posten), NULL),
        'summe_gesamt': sum((p.gesamt for p in posten), NULL),
        'offene_rechnungen': offene_rechnungen,
        'summe_nicht_zugeordnet': sum(
            (r.rest for r in offene_rechnungen), NULL),
        'erfassung_url': reverse(
            'admin:erfassung_erfassungszeile_changelist'),
    })
