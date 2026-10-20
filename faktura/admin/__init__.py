"""Admin von faktura, die Oberfläche der Anwendung.

Zwei Regeln: Festgeschriebene Belege werden schreibgeschützt angezeigt, und
fachliche Vorgänge laufen über Aktionen, die die Services aufrufen; ein
Status wird nie von Hand gesetzt.

Jede Admin-Klasse wird hier importiert, weil Django die Registrierungen nur
über dieses Paket lädt; eine nicht importierte Klasse fehlt ohne
Fehlermeldung im Menü.
"""

from .abnahme import AbnahmeAdmin
from .beleg import BelegAdmin
from .belegarten import (
    AngebotAdmin,
    AuftragAdmin,
    AuftragspositionInline,
    LieferscheinAdmin,
    MahnungAdmin,
    RechnungskorrekturAdmin,
    StornorechnungAdmin,
)
from .gemeinsam import (
    DESCRIPTION_TEXT,
    AktionNachDemSichern,
    ArchiviertFilter,
    BelegpositionInline,
    KontaktAktivFilter,
    LieferpositionInline,
    ProjektAbgeschlossenFilter,
    VersandstandFilter,
    ZahlungsstandFilter,
    adresse_im_admin,
    verweis_auf,
)
from .rechnung import (
    AbschlagsrechnungAdmin,
    RechnungAdmin,
    SchlussrechnungAdmin,
    TeilschlussrechnungAdmin,
)
from .stammdaten import (
    AnsprechpartnerAdmin,
    FirmaAdmin,
    KatalogpositionAdmin,
    KontaktAdmin,
    ProjektAdmin,
    SteuersatzAdmin,
    TextbausteinAdmin,
)
from .zahlungen import (
    ZahlungAdmin,
    ZahlungszuordnungAdmin,
)

__all__ = [
    'AbnahmeAdmin',
    'TeilschlussrechnungAdmin',
    'AbschlagsrechnungAdmin',
    'AktionNachDemSichern',
    'AngebotAdmin',
    'AnsprechpartnerAdmin',
    'ArchiviertFilter',
    'AuftragAdmin',
    'AuftragspositionInline',
    'BelegAdmin',
    'BelegpositionInline',
    'DESCRIPTION_TEXT',
    'FirmaAdmin',
    'KatalogpositionAdmin',
    'KontaktAdmin',
    'KontaktAktivFilter',
    'LieferpositionInline',
    'LieferscheinAdmin',
    'MahnungAdmin',
    'ProjektAbgeschlossenFilter',
    'ProjektAdmin',
    'RechnungAdmin',
    'RechnungskorrekturAdmin',
    'SchlussrechnungAdmin',
    'StornorechnungAdmin',
    'SteuersatzAdmin',
    'TextbausteinAdmin',
    'VersandstandFilter',
    'ZahlungAdmin',
    'ZahlungsstandFilter',
    'ZahlungszuordnungAdmin',
    'adresse_im_admin',
    'verweis_auf',
]
