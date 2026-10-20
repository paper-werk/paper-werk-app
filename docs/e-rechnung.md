# E-Rechnung

Welche E-Rechnungen Paper-Werk erzeugt, wie sie versendet und archiviert
werden und warum diese Formate gewählt sind.

## Überblick

Paper-Werk erzeugt zu jeder Rechnung eine E-Rechnung nach **EN 16931** in der
Syntax **UN/CEFACT CII**. Unternehmenskunden erhalten sie als
ZUGFeRD/Factur-X, eingebettet im PDF (PDF/A-3). Öffentliche Auftraggeber
erhalten eine XRechnung 3.0 als reines XML.

## Formate je Zustellweg

| | Normaler Kunde | Kunde mit Zustellweg „XRechnung“ |
| --- | --- | --- |
| Norm | EN 16931 | EN 16931, CIUS XRechnung 3.0 |
| Syntax | CII | CII |
| Profilkennung im XML | `urn:cen.eu:en16931:2017` | `urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0` |
| Anhang im PDF | `factur-x.xml` | `xrechnung.xml` |
| Profil in den PDF-Metadaten | `EN 16931` | `XRECHNUNG` |
| `Beleg.erechnungsprofil` | `EN 16931` | `XRECHNUNG` |
| Zusätzliche Pflichtfelder | keine | Leitweg-ID (BT-10), Ansprechpartner mit Telefon und E-Mail (BG-6), elektronische Adressen (BT-34: E-Mail der Firma, BT-49: Leitweg-ID mit Schema `0204`), Zahlungsanweisung auch bei Gutschriften (Code `1`) |

**Belegarten:** Rechnung (Typcode 380), Stornorechnung und
Rechnungskorrektur (beide 381, Beträge positiv). Angebot, Auftrag,
Lieferschein und Mahnung haben keine E-Rechnung.

**Wahl des Profils:** Der Zustellweg am Kunden bestimmt das Profil. Beim
Festschreiben wird es daraus abgeleitet und am Beleg eingefroren; eine
spätere Änderung des Zustellwegs wirkt nur auf neue Belege. Die Versandmaske
warnt, wenn das eingefrorene Profil eines festgeschriebenen Belegs nicht mehr
zum Zustellweg passt, und schon vorher, wenn ein Beleg eine Leitweg-ID trägt,
der Kunde aber nicht auf XRechnung steht (`facturx.zustellweg_warnung`). Die
Warnung blockiert den Versand nicht.

## Ablage und Versand

- **Erzeugt wird einmal, beim Festschreiben.** Dieselben Bytes stecken im PDF
  und liegen daneben (`Beleg.xml`), jeweils mit eigener SHA-256-Prüfsumme
  (`pdf_sha256`, `xml_sha256`). Neu erzeugt wird nur über „E-Rechnung neu
  ausstellen“ (siehe unten). Der Befehl `pruefe_belegarchiv` rechnet beide
  Prüfsummen nach.
- **Eine Datei je Beleg.** XRechnung geht als XML hinaus, alles andere als
  PDF, bei Rechnungen mit eingebetteter E-Rechnung. Mail und „Herunterladen“
  liefern dieselbe Datei; maßgeblich ist das eingefrorene Profil
  (`services.versandformat`). Die Versandmaske nennt die Datei und den
  Zustellweg des Kunden. Eine frühere Auswahl der Anhänge wurde entfernt: Ein
  nacktes XML hält jeder Empfänger für eine XRechnung, sodass das
  EN-16931-XML eines ZUGFeRD-Kunden im KoSIT-Validator durchfiel, und „PDF und
  XML“ legte zwei E-Rechnungen mit derselben Nummer in denselben Posteingang.
- **Am Beleg** steht bei ZUGFeRD „E-Rechnung im PDF“ mit Prüfsumme; ein
  eigenes ZUGFeRD-XML zeigt die Oberfläche nicht. Über die Schnittstelle
  (`/api/v1/belege/{id}/xml/`) ist es abrufbar.
- **Archiv:** Paperless-ngx nimmt kein XML an. Das PDF ist deshalb das
  Archivdokument, das XML ist darin eingebettet, auch bei XRechnung.
- **Steuerberater:** Bei XRechnung geht nur das XML hinaus, das XML ist also
  das Original. Im Kanal `duo_paperwerk` hängt der n8n-Workflow
  `sub-duo-versand-paperwerk` (paper-werk, `n8n/`) bei Profil
  XRECHNUNG das XML als zweiten Anhang an die Mail mit dem PDF
  (`GET /api/v1/belege/?paperless_id=…`, dann `…/xml/`). Der Kanal `duo`
  bleibt für Installationen ohne Paper-Werk unverändert; StB-Zip und sevDesk
  schicken nur das PDF.
- **GoBD:** Der ausschließliche XML-Versand ist nur zulässig, wenn das XML
  revisionssicher aufbewahrt wird. Der Hinweis steht in der
  Installationsanleitung (`paper-werk/Kundeninstallation.md`,
  Abschnitt 8) und nicht in der Versandmaske, weil der Versender daran nichts
  ändern kann. Er ist als Bedingung formuliert.

## Steuerfälle: § 13b, EU, Drittland

Der Steuerfall ist am Kunden vorbelegt und am Beleg verbindlich
(`faktura/steuerfall.py`). Außer im Regelfall müssen alle Positionen 0 %
haben, sonst verweigert das Festschreiben.

| Steuerfall | Kategorie | Befreiungscode | Vermerk im PDF |
| --- | --- | --- | --- |
| Regelfall (leer) | `S`, bei 0 % `E` | keiner | keiner (Kleinunternehmer: § 19) |
| § 13b Inland | `AE` | VATEX-EU-AE | Steuerschuldnerschaft des Leistungsempfängers (§ 13b UStG). |
| Dienstleistung EU | `AE` | VATEX-EU-AE | Steuerschuldnerschaft des Leistungsempfängers (Reverse Charge). |
| Warenlieferung EU | `K` | VATEX-EU-IC | Steuerfreie innergemeinschaftliche Lieferung (§ 4 Nr. 1 Buchst. b i. V. m. § 6a UStG). |
| Dienstleistung Drittland | `O` | VATEX-EU-O | Nicht im Inland steuerbare Leistung (Leistungsort im Ausland, § 3a Abs. 2 UStG). |
| Ausfuhr | `G` | VATEX-EU-G | Steuerfreie Ausfuhrlieferung (§ 4 Nr. 1 Buchst. a i. V. m. § 6 UStG). |

Bei `AE` und `K` stehen die USt-IdNr. des Kunden im PDF und im XML, bei `K`,
`G` und der EU-Dienstleistung zusätzlich die eigene. Bei `O` enthält das XML
keine USt-IdNr. (BR-O-02); der Verkäufer wird über Handelsregister oder
Steuernummer identifiziert. Bei `K` enthält das XML das Lieferland
(BR-IC-12). Der Steuerfall hat Vorrang vor der Kleinunternehmerregelung.

**Nicht abgedeckt:** Kleinunternehmer mit Auslandskunden, gemischte
Steuerfälle auf einem Beleg (EN 16931 erlaubt `O` ohnehin nur allein), die
Zusammenfassende Meldung.

## Neuausstellung einer abgewiesenen E-Rechnung

Die Aktion „E-Rechnung neu ausstellen“ an der festgeschriebenen Rechnung
(`services.erechnung_neu_ausstellen`) behält die Nummer. Änderbar sind nur
Leitweg-ID und Bestellnummer sowie die Angaben aus den Stammdaten (Telefon,
E-Mail, Zustellweg und damit das Profil). Positionen und Beträge lassen sich
nicht übergeben. Die alte Fassung bleibt als `Belegfassung` mit beiden
Dateien, Prüfsummen, Archivverweis und Grund erhalten, wird von
`pruefe_belegarchiv` mitgeprüft und ist im Reiter „Status“ herunterladbar.
Die neue Fassung geht als eigenes Dokument ins Archiv. Ob dieselbe Nummer
zulässig ist, legt der Betrieb in seiner Verfahrensdokumentation fest
([Vorlage](verfahrensdokumentation-vorlage.md), Abschnitt 2.3a, mit
Formulierungsvorschlag).

## Begründung der Formate

**Syntax CII statt UBL.** Im PDF erlaubt ZUGFeRD/Factur-X nur CII. Für das
reine XML kennt XRechnung beide Syntaxen, und die Eingangsportale müssen
beide annehmen. Eine Syntax für beide Wege hält den Code einfacher; auch das
Einlesen von Eingangsrechnungen (`erfassung/erechnung.py`) verarbeitet nur
CII, und `drafthorse` unterstützt kein UBL.

**Profile:**

| Profil | Als E-Rechnung in Deutschland zulässig? |
| --- | --- |
| MINIMUM, BASIC WL | Nein. Sie decken EN 16931 nicht ab und gelten seit 2025 als „sonstige Rechnung“. |
| BASIC | Formal ja, enthält aber weniger als EN 16931. Kein Vorteil. |
| **EN 16931** | Ja. Vorgabe für Unternehmenskunden. |
| EXTENDED | Ja, für Sonderfälle wie einen abweichenden Rechnungsempfänger. Derzeit nicht benötigt. |
| **XRECHNUNG** | Ja. Erforderlich für öffentliche Auftraggeber (Leitweg-ID, Regeln BR-DE-*). |

**Reines XML ohne XRechnung** ist unter Unternehmen eine gültige
E-Rechnung. Behördenportale lehnen es ab, weil die Leitweg-ID fehlt.

## Nicht geprüft

- **Schematron.** `drafthorse` prüft gegen das XSD, die eigenen Tests prüfen
  Pflichtfelder und Beträge. Die Schematron-Regeln (EN 16931 und BR-DE)
  laufen nur im KoSIT-Validator. Vor dem ersten echten Versand einer
  Installation eine erzeugte Datei dort prüfen.
- **Annahme durch Portale.** Ob ein Eingangsportal das reine XML annimmt, wie
  Paper-Werk es bei XRechnung verschickt, ist je Portal zu klären; ein PDF
  mit eingebetteter XRechnung wird nicht verschickt.
- **Zuordnung in DATEV Unternehmen online.** Ob DUO den zweiten Anhang
  (XML) der richtigen Rechnung zuordnet, ist an einer echten Rechnung zu
  prüfen.
- **Steuerliche Freigabe.** Ob die Ablage, besonders der reine XML-Versand,
  den Anforderungen genügt, klärt der Betrieb mit seinem Steuerberater.

## Implementierung

| Bereich | Datei |
| --- | --- |
| XML erzeugen, Profile, Pflichtprüfung XRechnung | `faktura/facturx.py` |
| Einbetten ins PDF, Metadaten | `faktura/pdf.py` (`beleg_als_pdf`) |
| Einfrieren und Neuausstellung | `faktura/services/festschreiben.py` (`_dokument_einfrieren`, `erechnung_neu_ausstellen`) |
| Versand | `faktura/services/versand.py` (`versandformat`, `beleg_versenden`) |
| Archivprüfung | `faktura/services/archivierung.py` (`belegarchiv_pruefen`), Befehl `pruefe_belegarchiv` |
| Warnung bei unpassendem Profil | `faktura/facturx.py` (`zustellweg_warnung`) |
| Steuerfälle (Kategorie, Vermerk, Pflichtangaben) | `faktura/steuerfall.py` |
| Versandmaske (Datei, Zustellweg, Herunterladen) | `faktura/templates/admin/faktura/versenden.html`, `faktura/admin/versand.py` |
| Nachweis am Beleg (Prüfsummen, „E-Rechnung im PDF“) | `faktura/admin/dokumente.py` |
| Schnittstelle: XML abrufen, Filter | `faktura/api.py` |
| E-Rechnungen einlesen (Gegenrichtung) | `erfassung/erechnung.py` |
| Weg zum Steuerberater | `paper-werk/n8n/sub-duo-versand-paperwerk.json`, Kanal `duo_paperwerk` |
| Beträge im XML | Rechenregister R-136 |

## Tests

- `faktura/tests/test_pdf.py`: `TestFacturX`, `TestXRechnung`, `TestSteuerfaelle`,
  `TestNeuausstellung`, `TestEinfrieren`.
- `faktura/tests/test_versand.py`: Versandformat und Versandmaske.
- `faktura/tests/test_anbindung.py`: Abruf des XML über die Schnittstelle.

## Rechtlicher Rahmen

- Seit 1.1.2025 müssen inländische Unternehmen E-Rechnungen empfangen können.
- Für den Versand gilt eine Übergangsfrist: Ab 2027 sind Unternehmen mit mehr
  als 800.000 € Vorjahresumsatz verpflichtet, ab 2028 alle.
- Öffentliche Auftraggeber verlangen die XRechnung bereits.
- Bei E-Rechnungen ist der strukturierte Teil maßgeblich. Aufzubewahren ist,
  was verschickt wurde, in dem Format, in dem es verschickt wurde.
