# Rechenregister

Verzeichnis aller Berechnungen, deren Ergebnis Paper-Werk anzeigt, druckt
oder exportiert, mit Rechenregel, Implementierung und Teststatus.

Nicht aufgeführt sind Zuteilungen ohne Rechnung (Belegnummern,
Nummernkreise), Zustandsprüfungen (ob ein Beleg festgeschrieben werden darf)
und reine Sortierungen. Für sie gelten die übrigen Tests.

**Teststatus** (Spalte „Test“):

| Zeichen | Bedeutung |
| --- | --- |
| `+` | Ein Test rechnet diese Zahl nach. |
| `~` | Nur mittelbar geprüft: Ein Test durchläuft die Funktion, prüft aber etwas anderes. |
| `-` | Kein Test nennt diese Funktion. |

Derzeit tragen 156 Einträge `+`, 23 `~` und keiner `-`. Die mittelbar
geprüften sind fast alle abgeleitete Aussagen wie `ist_klumpen`, `ist_knapp`
oder `traegt`: ein Vergleich auf einer Zahl, die selbst geprüft ist.

Die Nummern `R-xxx` sind fest und werden in Code und Tests zitiert. Neue
Einträge bekommen die nächste freie Nummer; die Reihenfolge in den Tabellen
folgt dem Sachzusammenhang, nicht der Nummer. Die Testabdeckung der
Rechenmodule misst `pytest --cov` (Einstellungen in `pyproject.toml`).

R-052 bis R-054, R-149 und R-173 rechnen in der Datenbank; die Regel in
Worten ist dieselbe wie auf dem Einzelweg, `*/test_grosse_bestaende.py`
vergleicht beide.

## A. Beleg: Summen, Steuer, Mengen

`faktura/services/`, `faktura/models/`

| Nr | Größe | Rechenregel | Implementierung | Test |
| --- | --- | --- | --- | --- |
| R-001 | Positionsnetto | Menge mal Einzelpreis, **kaufmännisch** auf Cent (ROUND_HALF_UP) | `services.positionssumme` | `+` |
| R-002 | Netto je Steuersatz | Summe der Positionsnetti des jeweiligen Satzes, **ohne optionale Positionen** (R-178) | `services.belegsummen` | `+` |
| R-003 | Steuer je Satz | Nettosumme des Satzes mal Satz durch 100, kaufmännisch auf Cent: **je Satz, nicht je Position**. Wählbar sind 19, 7, 0 und die gesenkten 16 und 5; ein Satz außerhalb der Liste wird trotzdem gerechnet | `services.belegsummen` | `+` |
| R-004 | Netto gesamt | Summe über alle Satzanteile | `services.belegsummen` | `+` |
| R-005 | Brutto gesamt | Netto plus Steuer | `services.belegsummen` | `+` |
| R-006 | Brutto je Satz | Netto plus Steuer des Satzes | `Steueranteil.brutto` | `~` |
| R-007 | Steuersatz als Zahl | Der gespeicherte Text als Dezimalzahl | `Belegposition.steuersatz_dezimal` | `+` |
| R-008 | Abgerechnete Menge je Auftragsposition | Summe der Rechnungspositionen mit Bezug auf sie; nur festgeschrieben, nur `normal` und `schluss`: **ein Abschlag zählt nicht** | `services.abgerechnete_mengen` | `+` |
| R-009 | Abgerechnete Menge, einzeln | Dieselbe Regel für eine Position | `Belegposition.abgerechnete_menge` | `+` |
| R-010 | Offene Menge | Beauftragte minus abgerechnete Menge, **nie negativ** | `Belegposition.offene_menge` | `+` |
| R-011 | Abrechnungsstand | "60 von 100 Std abgerechnet": Text aus R-009 und der Menge; darüber hinaus mit ", 2 mehr als beauftragt" | `Belegposition.abrechnungsstand` | `+` |
| R-157 | Mengenüberschreitung | Je Auftragsposition: R-008 plus die Mengen dieser Rechnung mit Bezug auf sie, minus beauftragt; gemeldet, wenn größer null. Nur `normal` und `schluss`. **Nie an einer optionalen Auftragsposition** (R-178): beauftragt ist dort der Preis, nicht die Menge. Ein Hinweis, festgeschrieben wird mit Bestätigung | `services.mengenueberschreitungen` | `+` |
| R-012 | Abschlagsnummer | Der wievielte Abschlag des Vorhabens, nach Belegdatum | `Beleg.abschlagsnummer` | `+` |
| R-013 | Nachtragsnummer | Der wievielte Nachtrag zu diesem Auftrag | `Beleg.nachtragsnummer` | `+` |
| R-014 | Summe über eine Belegmenge, netto | In SQL: Positionsnetto gerundet, gruppiert nach Beleg und Satz, dann summiert; Lieferscheine bleiben draußen | `services.summe_ueber` | `+` |
| R-015 | Summe über eine Belegmenge, Steuer | Je Gruppe (Beleg, Satz) aus der Nettosumme, kaufmännisch | `services.summe_ueber` | `+` |
| R-016 | Wertbelege und wertlose Belege | Zahl der Belege mit Preisen gegen Lieferscheine | `services.summe_ueber` | `~` |
| R-178 | Optionale Position | Angeboten, nicht Teil der Summe: zählt in **keine** Summe, an zwei Stellen und nur dort ausgenommen, `_summen` (Python, also R-002 bis R-005 und der Auftragswert) und `POSITIONSNETTO` (SQL, also R-014, R-173 und alles darüber). Dazu eine dritte, eigene Summe: das Entgelt der Abnahme (R-170). Ihr eigenes Positionsnetto (R-001) bleibt und steht im PDF in Klammern, bei Menge 0 gar nicht. Nur an Angebot und Auftrag; Menge 0 erlaubt. Eine abgerufene Option zählt über die Rechnungsposition, die auf sie zeigt, wie jede Leistung | `services.belegsummen`, `services.POSITIONSNETTO` | `+` |
| R-173 | Brutto je Beleg einer Menge | In SQL wie R-014/R-015, aber je Beleg statt summiert: Netto je (Beleg, Satz), Steuer je Gruppe kaufmännisch, beides addiert. Ein Beleg ohne Positionen fehlt im Ergebnis. Muss je Beleg auf den Cent R-005 ergeben; R-149 rechnet seit dem Lasttest damit | `services.bruttosummen` | `+` |

## B. Projektauswertung aus den Belegen

`faktura/services/`

| Nr | Größe | Rechenregel | Implementierung | Test |
| --- | --- | --- | --- | --- |
| R-017 | Summe je Belegart | Anzahl, Netto und Brutto je Belegart; **Entwürfe zählen nie mit** | `services.projektakte` | `+` |
| R-018 | Fakturiert netto (ein Projekt) | Summe der Steuerbelege: Rechnung, Storno, Korrektur. **Ohne Mahnung**, sonst stünde jede gemahnte Rechnung doppelt; **ohne Restzeilen** (R-174) | `services.projektakte` | `+` |
| R-019 | Fakturiert brutto (ein Projekt) | Dasselbe brutto | `services.projektakte` | `+` |
| R-020 | Angeboten netto | Summe der Angebote | `services.projektakte` | `+` |
| R-021 | Angeboten (alle Projekte) | In SQL: Summe der Angebotspositionen je Projekt | `services.projektstaende` | `+` |
| R-022 | Beauftragt | Summe der Auftragspositionen je Projekt, Nachträge eingeschlossen | `services.projektstaende` | `+` |
| R-023 | Fakturiert | Summe der Steuerbelege je Projekt. **Abschläge zählen mit**: Frage: was habe ich gestellt. **Ohne die Restzeilen** nicht bezahlter Abschläge (R-174): Der Betrag steht schon im Abschlag | `services.projektstaende` | `+` |
| R-024 | Abgerechnete Leistung | Dasselbe **ohne Abschläge**, ohne das Storno oder die Korrektur eines Abschlags (die Anzahlung steckt im Vorgänger) und **ohne die Abzugszeilen** (R-166) der Schluss- und Teilschlussrechnung. Frage: was ist abgerechnet | `services.projektstaende` | `+` |
| R-025 | Auftragsbestand je Projekt | Beauftragt minus fakturiert, **nie negativ** | `Projektstand.offen` | `+` |
| R-026 | Fortschritt je Projekt | Fakturiert durch beauftragt in Prozent, auf 0 bis 100 begrenzt; ohne Auftrag null | `Projektstand.fortschritt` | `+` |
| R-027 | Fakturaverlauf je Monat | Summe der Steuerbelege je Monat nach **Belegdatum**, ohne Restzeilen (R-174); fehlende Monate mit null aufgefüllt | `services.fakturaverlauf` | `+` |
| R-028 | Fakturiert im Jahr | Summe der Steuerbelege eines Kalenderjahres, ohne Restzeilen (R-174) | `services.fakturiert_im_jahr` | `+` |
| R-029 | Gemahnter Bestand | Anzahl und **Bruttosumme** der Rechnungen mit mindestens einer Mahnung; stornierte bleiben draußen | `services.gemahnte_rechnungen` | `+` |
| R-030 | Auftragseingang je Monat | Summe der Aufträge je Monat nach Belegdatum, Nachträge eingeschlossen | `services.auftragseingang_je_monat` | `+` |
| R-031 | Umsatz je Kunde | Summe der Steuerbelege je Auftraggeber im Zeitraum, ohne Restzeilen (R-174); Kunde vom Beleg, ersatzweise vom Projekt. Die Kundenakte rechnet über `summe_ueber(als_umsatz=True)` | `services.umsatz_je_kunde` | `+` |
| R-032 | Belegzahl je Kunde | Zahl der verschiedenen Belege dahinter | `services.umsatz_je_kunde` | `+` |

## C. Leistungserfassung und Übernahme in die Rechnung

`erfassung/services/`, `erfassung/models.py`

| Nr | Größe | Rechenregel | Implementierung | Test |
| --- | --- | --- | --- | --- |
| R-033 | Erfasste Zeit einer Auswahl | Summe der Minuten, **ohne Aufrundung** | `services.zeitsumme` | `+` |
| R-034 | Zeit des Nachweises | Summe der Minuten der Auswahl | `services.zeitaufstellung` | `+` |
| R-035 | Nicht berechnete Zeit | Summe der Minuten der nicht abrechenbaren Zeilen, **getrennt ausgewiesen, nicht abgezogen** | `services.zeitaufstellung` | `+` |
| R-036 | Mengen des Nachweises | Je Einheit getrennt summiert: km und Stück werden nie verschmolzen | `services.zeitaufstellung` | `+` |
| R-037 | Aufgerundete Stunden | Minuten **aufgerundet auf die Viertelstunde**, ganzzahlig gerechnet | `services.aufgerundete_stunden` | `+` |
| R-038 | Menge je Rechnungsposition | Bei Zeit: R-037 auf die **Summe der Gruppe**, nicht je Zeile. Sonst: Summe der Mengen. Mit `entwuerfe_zaehlen` gilt eine Zeile auf einem Rechnungsentwurf als offen | `services.abrechnungsvorschau` | `+` |
| R-039 | Summe einer Abrechnungsposition | Menge mal Einzelpreis aus dem Katalog, über R-001 | `Abrechnungsposition.summe` | `+` |
| R-040 | Summe einer Fremdposition | Menge mal Einzelpreis, über R-001. Einzelpreis: der der Auftragsposition, wenn eine gewählt ist und die Einheit passt (ohne Groß-/Kleinschreibung, ohne Leerraum); sonst der Einkaufspreis auf Cent. Trifft das den Einkauf (R-041) nicht auf den Cent, wird die Gruppe **eine Pauschale über R-041** | `services._fremdpositionen`, `Fremdposition.summe` | `+` |
| R-041 | Einkauf einer Fremdposition | Summe der Zeilenbeträge (R-156) ihrer Zeilen | `Fremdposition.einkauf` | `+` |
| R-042 | Spanne einer Fremdposition | R-040 minus R-041: nur in der Vorschau | `Fremdposition.spanne` | `+` |
| R-043 | Netto der Vorschau | Summe aller Positionen, eigene und fremde | `Uebernahmevorschau.netto` | `+` |
| R-044 | Fremdkosten der Vorschau | Summe der Einkaufsbeträge | `Uebernahmevorschau.fremdkosten` | `~` |
| R-156 | Zeilenbetrag einer Fremdleistung | Der Betrag laut Lieferant (E-Rechnung: BT-131). Leer: Menge mal Einkaufspreis über R-001. Neu gerechnet, wenn Menge oder Preis sich ändern und der Betrag nicht | `Fremdleistung.save`, `Fremdleistung.einkauf_netto` | `+` |
| R-048 | Zugeordneter Betrag | Summe der Zeilenbeträge (R-156) aller Positionen der Eingangsrechnung | `Eingangsrechnung.zugeordnet` | `+` |
| R-049 | Nicht zugeordneter Rest | Rechnungsbetrag minus R-048; negativ heißt überverteilt | `Eingangsrechnung.rest` | `+` |

## D. Aufwand, Kosten und Auslastung

`erfassung/services/`

| Nr | Größe | Rechenregel | Implementierung | Test |
| --- | --- | --- | --- | --- |
| R-050 | Offene Leistung je Projekt | Über dieselbe Vorschau wie die Rechnung (R-038/R-043), mit `entwuerfe_zaehlen`: **nicht** als SQL-Summe, sonst wiche sie von der Abrechnung ab | `services.offene_leistung_je_projekt` | `+` |
| R-051 | Offene Leistung gesamt | Summe über alle Projekte | `services.offene_leistung_gesamt` | `+` |
| R-052 | Personalkosten je Projekt | Je Zeile: Dauer mal dem Kostensatz, **der an ihrem Tag galt**. Echte Zeit, nicht aufgerundet. Nicht abrechenbare Zeit zählt mit. Gerundet erst am Schluss je Projekt | `services.personalkosten_je_projekt` | `+` |
| R-053 | Personen ohne Kostensatz | Wer gebucht hat, ohne dass ein Satz hinterlegt ist: der Vorbehalt über allen Ergebnissen | `services.personalkosten_je_projekt` | `+` |
| R-054 | Unbewertete Minuten | Die Zeit, die deshalb fehlt | `services.personalkosten_je_projekt` | `+` |
| R-055 | Fremdkosten je Projekt | Summe der Zeilenbeträge (R-156); **alle** Positionen, auch nicht weiterberechenbare | `services.fremdkosten_je_projekt` | `+` |
| R-056 | Offene Fremdleistung je Projekt | Summe der Zeilenbeträge (R-156) der weiterberechenbaren, noch nicht abgerechneten Fremdleistungen: **im Einkauf**, eine Untergrenze; der Aufschlag entsteht erst an der Rechnung | `services.offene_fremdleistung_je_projekt` | `+` |
| R-057 | Offene Fremdleistung gesamt | Summe darüber | `services.offene_fremdleistung_gesamt` | `+` |
| R-058 | Stunden je Projekt | Minuten durch 60, auf zwei Stellen | `services.stunden_je_projekt` | `+` |
| R-059 | Ältester offener Posten | Das früheste Datum unter den offenen Zeilen je Projekt | `services.aeltester_offener_posten_je_projekt` | `+` |
| R-060 | Erfasste Zeit je Monat | Minuten je Monat nach Erfassungsdatum; fehlende Monate mit null | `services.aufwand_je_monat` | `+` |
| R-061 | Stunden für das Diagramm | Minuten durch 60 als Fließkommazahl, zwei Stellen | `Monatsstunden.stunden` | `+` |
| R-062 | Aufwand je Person | Minuten und Zeilenzahl je Person, wahlweise auf einen Auftrag eingeengt | `services.aufwand_je_person` | `+` |
| R-063 | Aufwand je Leistung | Minuten bei Zeitleistungen, Menge bei allem anderen | `services.aufwand_je_leistung` | `+` |
| R-064 | Auslastung: drei Töpfe | Abgerechnet, offen, nicht abrechenbar: in **einer** Abfrage, damit die Summe der Töpfe die Gesamtzeit ergibt. "Abgerechnet" ist `NOCH_NICHT_ABGERECHNET`, negiert | `services.auslastung_je_person` | `+` |
| R-065 | Erfasste Zeit einer Person | Summe der drei Töpfe | `Auslastung.minuten_gesamt` | `+` |
| R-066 | Verkaufbare Zeit | Abgerechnet plus offen | `Auslastung.minuten_verkaufbar` | `~` |
| R-067 | Produktive Quote | Verkaufbare durch gesamte Zeit in Prozent; **unbestimmt** ohne erfasste Zeit | `Auslastung.quote` | `+` |
| R-068 | Offene Leistung nach Alter | Je Projekt der belastbare Gesamtbetrag (R-050), **anteilig** auf die Altersfächer verteilt nach den ungerundeten Zeilenwerten; das letzte Fach bekommt den Rest, damit die Summe exakt aufgeht | `services.offene_leistung_nach_alter` | `+` |
| R-069 | Fachzuordnung | In welches Altersfach eine Zeile nach ihrem Alter in Tagen fällt | `services._fachnummer` | `~` |
| R-070 | Rohwert einer Zeile | Der ungerundete Zeilenwert: nur als Verteilungsschlüssel für R-068 | `services._rohwert` | `~` |

## E. Projektergebnis

`auswertung/ergebnisse.py`

| Nr | Größe | Rechenregel | Implementierung | Test |
| --- | --- | --- | --- | --- |
| R-071 | Noch nicht abgerechnet | Offene eigene plus offene fremde Leistung | `Projektergebnis.nicht_abgerechnet` | `+` |
| R-072 | Leistungswert | Abgerechnete Leistung (R-024, **ohne Abschläge**) plus R-071 | `Projektergebnis.leistungswert` | `+` |
| R-073 | Kosten | Personalkosten plus Fremdkosten | `Projektergebnis.kosten` | `+` |
| R-074 | Ergebnis | Leistungswert minus Kosten | `Projektergebnis.ergebnis` | `+` |
| R-075 | Marge | Ergebnis durch Leistungswert in Prozent, abgerundet; **unbestimmt** ohne Leistungswert | `Projektergebnis.marge` | `+` |
| R-076 | Überschreitung | Leistungswert minus beauftragt, nur wenn positiv; ohne Auftrag null | `Projektergebnis.ueberschreitung` | `+` |
| R-077 | Ausschöpfung | Leistungswert durch beauftragt in Prozent, **ungedeckelt**; ohne Auftrag unbestimmt | `Projektergebnis.ausschoepfung` | `+` |
| R-078 | Ist überzogen | Überschreitung größer null | `Projektergebnis.ist_ueberzogen` | `~` |
| R-079 | Trägt | Ergebnis nicht negativ | `Projektergebnis.traegt` | `~` |
| R-080 | Ergebnis gesamt | Summe über alle Vorhaben | `Ergebnisuebersicht.ergebnis` | `+` |
| R-081 | Kosten gesamt | Summe über alle Vorhaben | `Ergebnisuebersicht.kosten` | `+` |
| R-082 | Nicht abgerechnet gesamt | Summe über alle Vorhaben | `Ergebnisuebersicht.nicht_abgerechnet` | `+` |
| R-083 | Auftragsbestand gesamt | Summe der offenen Beträge (R-025) | `Ergebnisuebersicht.auftragsbestand` | `+` |
| R-084 | Überschreitung gesamt | Summe über alle Vorhaben | `Ergebnisuebersicht.ueberschreitung` | `+` |
| R-085 | Vollständigkeit | Ob alle Stunden bewertet sind: der Vorbehalt über allen Zahlen dieser Gruppe | `Ergebnisuebersicht.vollstaendig` | `+` |

## F. Controlling-Kennzahlen

`auswertung/controlling.py`

| Nr | Größe | Rechenregel | Implementierung | Test |
| --- | --- | --- | --- | --- |
| R-086 | Eigenleistung | Leistungswert minus dem Verkaufswert der zugekauften Leistung | `controlling.lage`, `projektertrag` | `+` |
| R-087 | Erlös je Stunde | Eigenleistung durch geleistete Stunden; **unbestimmt** ohne Stunden | `Stundenertrag.erloes_je_stunde` | `+` |
| R-088 | Kosten je Stunde | Personalkosten durch geleistete Stunden: nach Stunden gewichtet, kein Mittelwert der Sätze | `Stundenertrag.kosten_je_stunde` | `+` |
| R-089 | Faktor | Eigenleistung durch Personalkosten | `Stundenertrag.faktor` | `+` |
| R-090 | Deckung je Stunde | Erlös je Stunde minus Kosten je Stunde | `Stundenertrag.deckung_je_stunde` | `~` |
| R-091 | Deckungsbeitrag I | Leistungswert minus Fremdkosten | `Deckungsbeitrag.db1` | `+` |
| R-092 | Deckungsbeitrag II | DB I minus Personalkosten | `Deckungsbeitrag.db2` | `+` |
| R-093 | DB-Quoten | Der jeweilige Beitrag durch den Leistungswert in Prozent | `Deckungsbeitrag._quote` | `~` |
| R-094 | Wasserfallstufen | Fünf Stufen mit Betrag und Sockel; der Sockel macht aus der Balkenreihe den Wasserfall | `Deckungsbeitrag.stufen` | `+` |
| R-095 | Monatsleistung | Durchschnitt der letzten drei **abgeschlossenen** Monate: der laufende bleibt draußen | `controlling._monatsleistung` | `+` |
| R-096 | Reichweite | Auftragsbestand durch Monatsleistung, eine Nachkommastelle; **unbestimmt** ohne Umsatz | `Reichweite.monate` | `+` |
| R-097 | Reichweite knapp | Unter einem Monat Vorlauf | `Reichweite.ist_knapp` | `~` |
| R-098 | Kundenanteil | Umsatz des Kunden durch Gesamtumsatz in Prozent | `controlling.kundenstruktur` | `+` |
| R-099 | Kumulierter Anteil | Die Summenlinie über die absteigend sortierten Kunden | `controlling.kundenstruktur` | `+` |
| R-100 | Klumpenrisiko | Anteil ab 30 Prozent | `Kundenanteil.ist_klumpen` | `~` |
| R-101 | Anteil der drei Größten | Der kumulierte Anteil an dritter Stelle, auf 100 begrenzt | `Kundenstruktur.anteil_top3` | `+` |
| R-102 | Auftragseingang im Zeitraum | Summe der Monatswerte | `Lage.auftragseingang_summe` | `~` |
| R-103 | Umsatz im Zeitraum | Summe der Monatswerte | `Lage.umsatz_summe` | `~` |
| R-104 | Eingang gegen Umsatz | Auftragseingang durch Umsatz in Prozent: *book-to-bill* | `Lage.eingang_gegen_umsatz` | `+` |
| R-105 | Offene Leistung gesamt (Lage) | Summe über die Altersklassen | `Lage.offene_leistung_gesamt` | `~` |
| R-106 | Lange Liegengebliebenes | Summe der Klassen ohne obere Grenze | `Lage.alt_liegengeblieben` | `+` |

## G. Auftrags- und Projektakte

`auswertung/auftragsakte.py`, `auswertung/projektakte.py`

Die Auftragsakte rechnet nicht selbst: Die Zahlen stehen in
`auswertung.Auftragsstand`, die Seite beschriftet sie. So sind sie ohne
Seitenaufruf prüfbar.

| Nr | Größe | Rechenregel | Implementierung | Test |
| --- | --- | --- | --- | --- |
| R-107 | Auftragswert | Netto des Auftragsbelegs über R-004 | `Auftragsstand.beauftragt` | `+` |
| R-108 | Auf den Auftrag berechnet | Summe der Rechnungspositionen mit Bezug auf ihn über R-001; nur festgeschrieben, nur `normal` und `schluss` | `services.berechneter_wert` | `+` |
| R-109 | Vom Auftrag offen | Auftragswert minus R-108 | `Auftragsstand.offen` | `+` |
| R-110 | Erfasst, nicht berechnet | Netto der Vorschau über die offenen Zeilen dieses Auftrags, **Entwürfe zählen mit** | `auswertung.auftragsstand` | `+` |
| R-111 | Fortschritt des Auftrags | R-108 durch Auftragswert in Prozent, ungedeckelt; ohne Positionen unbestimmt | `Auftragsstand.fortschritt` | `+` |
| R-112 | Positionsfortschritt | Abgerechnete durch beauftragte Menge in Prozent, ungedeckelt | `Auftragsposten.fortschritt` | `+` |
| R-113 | Positionsrest | Beauftragte minus abgerechnete Menge, **nie negativ** | `Auftragsposten.offen` | `+` |
| R-114 | Wert einer Auftragsposition | Menge mal Einzelpreis über R-001 | `Auftragsposten.netto` | `+` |
| R-115 | Klammersumme | Netto je Beleg der Nachtragsklammer | `auftragsakte._klammer` | `~` |
| R-116 | Rechnungsbeträge der Akte | Anteil je Rechnung auf diesen Auftrag, über R-001 summiert | `auftragsakte._rechnungen` | `~` |
| R-117 | Balkenbreiten der Projektakte | Fortschritt und Ausschöpfung, auf 100 begrenzt | `projektakte._zahlen` | `~` |
| R-118 | Wasserfallanteile | Je Stufe Start und Breite in Prozent des größeren von Leistungswert und Kosten, auf 0 bis 100 begrenzt, mit Punkt geschrieben | `darstellung.wasserfall` | `+` |
| R-119 | Kostenstruktur | Eigene Arbeit, Zukauf und Rest als Ringanteile | `projektakte._kostenstruktur` | `~` |
| R-120 | Stärkster Monat | Der Monat mit den meisten Stunden, mit Namen | `darstellung.spitzenmonat` | `+` |

## H. Startseite und Übersichten

`auswertung/dashboard.py`, `auswertung/controllingseite.py`, `auswertung/liegengeblieben.py`

| Nr | Größe | Rechenregel | Implementierung | Test |
| --- | --- | --- | --- | --- |
| R-155 | Kennzahlen der Startseite | Auftragsbestand, nicht Abgerechnetes, offene Forderungen, Reichweite: alle aus den Diensten übernommen | `dashboard._kennzahlen` | `+` |
| R-121 | Spitzenmonat | Der umsatzstärkste Monat des Verlaufs, mit Namen | `darstellung.spitzenmonat` | `+` |
| R-122 | Projektzeilen der Startseite | Die vordersten nach Auftragsbestand, mit Rest als Zahl | `dashboard._projektzeilen` | `+` |
| R-123 | Altersklassen der Karte | Betrag und Anteil je Altersfach | `controllingseite._altersklassen` | `+` |
| R-124 | Kundenzeilen | Anteil, kumulierter Anteil und Klumpenkennzeichnung | `controllingseite._kundenzeilen` | `+` |
| R-125 | Auslastungszeilen | Die drei Töpfe je Person als Balkenanteile | `controllingseite._auslastungszeilen` | `~` |
| R-126 | Blasenradius | Der Radius der Projektblase aus ihrem Wert, gegen den größten | `controllingseite._blasenradius` | `~` |
| R-127 | Liegenposten | Eigene plus fremde offene Leistung je Projekt | `Liegenposten.gesamt` | `+` |
| R-128 | Liegedauer | Tage seit dem ältesten offenen Posten; **unbestimmt** ohne solchen | `Liegenposten.tage` | `+` |
| R-129 | Auffällig alt | Ab sechzig Tagen | `Liegenposten.ist_alt` | `~` |
| R-130 | Summen der Liegenliste | Eigene, fremde und gesamte Summe über alle Posten | `liegengeblieben.liegengeblieben` | `+` |
| R-131 | Nicht zugeordneter Rest | Summe der Reste offener Eingangsrechnungen | `liegengeblieben.liegengeblieben` | `~` |

## I. Formate, PDF und E-Rechnung

`faktura/formate.py`, `faktura/facturx.py`, `erfassung/erechnung.py`

| Nr | Größe | Rechenregel | Implementierung | Test |
| --- | --- | --- | --- | --- |
| R-132 | Geldformat | Zwei Nachkommastellen, Tausenderpunkt, deutsche Schreibweise | `formate.geld` | `+` |
| R-133 | Mengenformat | Bis drei Nachkommastellen, ohne überflüssige Nullen | `formate.menge` | `+` |
| R-154 | Euroformat | Wie R-132, mit €; leer bei fehlendem Wert. Masken und Auswertungen | `formate.euro` | `+` |
| R-134 | Prozentformat | Ganzzahlig, solange der Satz ganzzahlig ist | `formate.prozent` | `+` |
| R-177 | Faktorformat | Zwei Nachkommastellen mit Komma, ohne Tausenderpunkt; leer bei fehlendem Wert. Der Stundenfaktor auf Controlling-Seite und Projektakte | `formate.faktor` | `+` |
| R-135 | Zeilensumme in der Vorlage | Ruft R-001 auf: die Vorlage rechnet nicht selbst | `faktura_extras.zeilensumme` | `+` |
| R-187 | Betrag in der Maske bei Eingabe | Nur Anzeige, vor dem Speichern: R-001 je Leistung und R-180 je Zuschlag **ein zweites Mal in JavaScript**, mit BigInt und derselben Rundung. Neu berechnet bei jeder Änderung von Menge, Preis, Nummer, Zeilenart, Option, Prozentsatz, „auf“ und Löschhaken. Maßgeblich bleibt der Server beim Speichern; der Browsertest vergleicht Anzeige und gespeicherten Wert | `faktura/static/faktura/js/zeilensumme.js` | `+` |
| R-136 | Beträge im Factur-X-XML | Positionssummen, Steueranteile und Gesamtbeträge aus R-001 bis R-005: in beiden Profilen (EN 16931 und XRECHNUNG); das Profil ändert Pflichtfelder, nie Zahlen. Ebenso in den Steuerfällen AE/K/G/O: Steuer 0, Gesamtbetrag = netto (`TestSteuerfaelle`) | `facturx.xml_erzeugen` | `+` |
| R-137 | Gelesene Beträge einer E-Rechnung | Betrag und Summe aus dem eingehenden XML auf Cent. Der **Einzelpreis auf vier Stellen**, nach Teilung durch die Preisbasismenge (BT-149), kaufmännisch über `rechnen.auf_stufe`. Maßgeblich für den Zeilenbetrag ist BT-131, ersatzweise Menge mal Einzelpreis | `erechnung._positionen` | `+` |
| R-138 | Positionsbeträge auf dem Blatt | Jede Positionssumme steht im **gedruckten** PDF, deutsch geschrieben | `pdf/basis.html` | `+` |
| R-139 | Netto und Rechnungsbetrag auf dem Blatt | Beide stehen da; eine Zeile "Steuer gesamt" gibt es bewusst nicht | `pdf/basis.html` | `+` |
| R-140 | Steuerausweis je Satz auf dem Blatt | Je Satz Prozentsatz, Bemessungsgrundlage und Betrag: § 14 Abs. 4 Nr. 8 UStG. Die ausgewiesenen Beträge ergeben zusammen die Gesamtsteuer | `pdf/basis.html` | `+` |

---

## J. Zahlungseingänge und offene Posten

`faktura/models/`, `faktura/services/`

Alle Beträge in diesem Abschnitt sind brutto, weil gefordert und überwiesen
der Bruttobetrag wird.

| Nr | Größe | Rechenregel | Implementierung | Test |
| --- | --- | --- | --- | --- |
| R-141 | Zugeordnete Zahlung | Summe der `betrag` ihrer Zuordnungen: **ohne Skonto**, denn der verbraucht nichts von der Zahlung | `Zahlung.zugeordnet` | `+` |
| R-142 | Rest einer Zahlung | Betrag laut Auszug minus R-141; kann nicht negativ werden (`clean` weist das ab) | `Zahlung.rest` | `+` |
| R-143 | Zahlung vollständig verteilt | R-142 gleich null | `Zahlung.ist_verteilt` | `+` |
| R-144 | Ausgleich einer Zuordnung | Betrag plus Skonto plus Kürzung (R-175): was die Rechnung abnimmt, nicht was floss | `Zahlungszuordnung.ausgleich` | `+` |
| R-145 | Auf eine Rechnung gezahlt | Summe der `betrag` ihrer Zuordnungen: die Frage des Kontoabgleichs | `Beleg.bezahlt` | `+` |
| R-146 | Auf eine Rechnung ausgeglichen | Summe der R-144 ihrer Zuordnungen: die Frage des Mahnlaufs | `Beleg.ausgeglichen` | `+` |
| R-147 | Offener Betrag | Bruttobetrag (R-005) minus R-146 minus R-182, **nie negativ**. Null bei allem, was keine festgeschriebene Rechnung ist: Entwurf, Angebot, Storno. **Beim Abschlag:** null, sobald jede seiner Positionen in einer festgeschriebenen (Teil-)Schlussrechnung abgesetzt ist (die Forderung ist erloschen, R-174); vorher abzüglich der Restzeilen festgeschriebener Teilschlussrechnungen | `services.offener_betrag`, `Beleg.offener_betrag` | `+` |
| R-148 | Rechnung ist bezahlt | R-147 gleich null, und nur an einer festgeschriebenen Rechnung | `Beleg.ist_bezahlt` | `+` |
| R-149 | Offene Posten | Je festgeschriebener Rechnung R-005, R-145 und R-147; wer null offen hat, fällt heraus. Stornierte bleiben draußen, eine festgeschriebene Rechnungskorrektur mindert (R-182), ein abgerechneter Abschlag fällt heraus (`ganz_abgerechnete`) | `services.offene_posten` | `+` |
| R-150 | Tage überfällig | Stichtag minus `faellig_am`; **negativ heißt: noch Zeit**. Ohne Fälligkeit `None`. Dieselbe Regel für einen einzelnen Beleg, wie die Spalte „Fällig“ sie zeigt („+39 T“) | `OffenerPosten.tage_ueberfaellig`, `services.tage_ueber_frist` | `+` |
| R-151 | Summe der offenen Posten | Summe über R-147 aller Posten | `Postenstand.offen` | `+` |
| R-152 | Summe der überfälligen Posten | Dasselbe, beschränkt auf R-150 größer null | `Postenstand.offen_ueberfaellig` | `+` |
| R-153 | Mahnbetrag | Der **offene** Betrag der Rechnung (R-147), nicht ihre Bruttosumme (R-005). Eine ausgeglichene Rechnung wird abgewiesen | `services.mahnung_erstellen` | `+` |
| R-176 | Zahlungsstand einer Rechnung | Nur an einer festgeschriebenen Rechnung, sonst leer (Entwurf, Storno, kein Rechnungsbeleg). R-147 größer null: **über Frist**, wenn R-150 größer null, sonst **offen**. R-147 gleich null: **abgerechnet**, wenn es ein Abschlag ist, den eine festgeschriebene Schlussrechnung ganz absetzt (`ganz_abgerechnete`), sonst **bezahlt**. Dieselbe Frist wie R-152 (Test vergleicht beide) | `services.zahlungsstand` | `+` |

**Nicht gerechnet: Skonto.** Der Abzug steht in der Zuordnung, weil ein
Anwender ihn eingetragen hat. Ob eine Unterzahlung Skonto ist, ein Abzug
wegen Mängeln oder ein Fehler, entscheidet der Betrieb, ebenso wie beim
Steuersatz ohne Gültigkeitszeitraum. `skonto_prozent` und `skonto_tage` am
Kontakt sind deshalb Angaben zum Nachsehen und gehen nicht in
`stammdatenwerte` ein.

**Nicht gerechnet: Ausbuchung einer uneinbringlichen Forderung.** Sie hat
eigene steuerliche Folgen (§ 17 UStG) und gehört in eine
Rechnungskorrektur. Ein nicht bezahlter Rest bleibt offen stehen, sichtbar
wie der Rest an der Eingangsrechnung (R-131).

**Die Kundenakte hat keine eigene Formel.** Ihr Umsatz kommt aus
`services.summe_ueber` (R-014, R-015), ihre offenen Posten aus
`services.offene_posten` (R-149 bis R-152); sie filtert die Ergebnisse auf
einen Kunden. Der Filter ist dabei selbst eine Regel: Ein Beleg hängt am
Kunden oder an einem seiner Projekte (`kunde_oder_projekt_nicht_beides`).
Ein Filter nur auf `kunde=` findet bei Projektarbeit nichts und zeigt
trotzdem eine Zahl. Maßgeblich ist `services.umsatz_je_kunde` mit
`Coalesce(beleg__kunde_id, beleg__projekt__kunde_id)`; dass die Akte auf
dieselbe Zahl kommt, prüft `tests/test_rechenabgleich.py`
(`TestDieKundenakteGegenDieAuftraggeberstruktur`).

Geprüft in `faktura/tests/test_zahlungen.py`, `faktura/tests/test_kundenstamm.py` und
`auswertung/tests/test_kundenakte.py`.

## K. Zuordnung von Leistungen und Rechnungen zu Auftragspositionen

`auswertung/zuordnung.py`, `auswertung/rechnungsakte.py`. Eine Übersicht
in Projekt-, Auftrags- und Rechnungsakte.

| Nr | Größe | Rechenregel | Implementierung | Test |
| --- | --- | --- | --- | --- |
| R-158 | Erfasster Umfang je Auftragsposition und Zustand | Minuten der Zeitzeilen; Mengenzeilen je Einheit, **Mengen in Std als Minuten** (sonst stünde eine Mengenzeile mit 0:00 da). Getrennt nach offen / auf Entwurf / abgerechnet / nicht abrechenbar; "ohne Auftragsposition" als eigene Zeile (nicht im Auftrag) | `zuordnung.Umfang`, `zuordnung._zeiten_eintragen` | `+` |
| R-159 | Zeiten je Person | Dieselben Minuten je Person, die längste zuerst; über alle Zeilen für die Rechnungsakte | `Zuordnungszeile.personen`, `Zuordnung.personen` | `+` |
| R-160 | Fremdleistung je Auftragsposition und Zustand | Summe der Zeilenbeträge (R-156) je Zustand | `zuordnung._fremd_eintragen` | `+` |
| R-161 | Noch offen je Auftragsposition | Offene Stunden über die Vorschau (R-050, Entwürfe zählen als offen) plus offene Fremdleistung im Einkauf | `Zuordnungszeile.offen_gesamt` | `+` |
| R-162 | Abgerechnet je Auftragsposition | Menge nach R-008, netto über `POSITIONSNETTO` mit derselben Auswahl (ohne Abschläge) | `zuordnung._berechnetes_eintragen` | `+` |
| R-163 | Anteil der Rechnung je Auftragsposition | Positionsnetto dieser Rechnung, gruppiert nach Auftragsposition; ohne Bezug in "ohne Auftragsbezug". Summe = Nettobetrag der Rechnung | `zuordnung.fuer_rechnung` | `+` |
| R-164 | Herkunft des Rechnungsbetrags | Positionssumme (R-001) je Position: mit Zeiten: "aus Zeiten", sonst mit Fremdleistungen: "aus Fremdleistungen" (dazu deren Einkauf), sonst "ohne Nachweis". Die drei ergeben den Nettobetrag | `rechnungsakte.herkunft` | `+` |

Geprüft in `auswertung/tests/test_zuordnung.py`, einschließlich der Frage, ob
die Liste hinter jedem Verweis genau die gezählten Zeilen zeigt.

## L. Abnahme, Teilschlussrechnung und Absetzen von Abschlägen

`faktura/services/abschlaege.py`, `faktura/services/abnahme.py`,
`faktura/models/abnahme.py`, `faktura/facturx.py`

Hier geht es um den Zahlbetrag einer Rechnung: Ein Abschlag, der doppelt
oder gar nicht abgesetzt wird, ergibt einen falschen Betrag beim Kunden und,
bei doppeltem Absetzen, zu wenig ausgewiesene Steuer.

| Nr | Größe | Rechenregel | Implementierung | Test |
| --- | --- | --- | --- | --- |
| R-165 | Anrechenbare Abschläge | Abschlagspositionen des Projekts: festgeschrieben (nicht storniert, nicht Entwurf), keine Abzugszeile, noch nicht abgesetzt. Die Teilschlussrechnung nimmt die mit Bezug auf eine Position ihrer Teilleistung, die Schlussrechnung den Rest ohne die Positionen offener Teilleistungen. Sicherheitsnetz: Abschläge, deren Nummer in einer Abzugszeile ohne Verweis steht, gelten als abgesetzt | `abschlaege.anrechenbare_abschlagspositionen` | `+` |
| R-166 | Abzugszeile | Je Abschlagsposition eine Zeile: dieselbe Menge, **negativer** Einzelpreis, derselbe Steuersatz. Gerechnet wie jede Position (R-001, Steuer je Satz R-003). Darunter, wenn nicht voll bezahlt, die Restzeile (R-174). **Im PDF je Abschlag und Satz eine Zeile** (`abzugsblock`); Summe des Blocks = Summe der Abzugszeilen | `abschlaege.abschlaege_absetzen`, `abschlaege.abzugsblock` | `+` |
| R-179 | Leistung der Schlussrechnung aus den Abschlägen | Je Leistung eine Position mit der Gesamtmenge über alle abgesetzten Abschläge. Auf eine Auftragsposition zum Vertragspreis: Summe der Mengen. Auf eine Auftragsposition mit anderem Preis (Teilbetrag): die Auftragsposition mit ihrer offenen Menge (R-008) und ihrem Preis. Ohne Auftragsposition, aber aus Katalog oder Erfassung: Summe der Mengen je Bezeichnung, Einheit, Preis, Satz, Art. Frei getippte Abschlagsbeträge: keine Leistung. Nur Schlussrechnung, nicht Teilschluss (dort R-170) | `abschlaege._leistung_aus_abschlaegen` | `+` |
| R-180 | Zuschlag | Basis = Positionsnetti (R-001) der **Leistungen**, deren Nummer unter `zuschlag_auf` fällt (gleich oder mit „auf.“ beginnend; leer = alle), **ohne optionale** (R-178), ohne Abzugszeilen, **nie ein anderer Zuschlag**. Betrag = Basis × Satz / 100, auf den Cent; steht als Einzelpreis bei Menge 1, zählt damit in R-002 ff. und `POSITIONSNETTO` wie jede Position. Nachgerechnet beim Anlegen, Sichern der Maske, Kopieren, Absetzen und vor dem Festschreiben; nicht im Storno (spiegelt). **Ein optionaler Zuschlag** (nur Angebot und Auftrag, R-178) hat den Betrag 0, im PDF nur Satz und Bezug („50 % auf Pos. 3.1“); er kommt nicht von selbst in die Rechnung, `services.optionale_zuschlaege` nennt die offenen in der Rechnungsmaske | `services.zuschlaege_nachrechnen`, `services.zuschlagsbasis` | `+` |
| R-181 | Titelsumme | Positionsnetti aller Leistungen und Zuschläge, deren Nummer mit „Titelnummer.“ beginnt, ohne optionale, ohne Abzugszeilen. Nur Anzeige im PDF nach der letzten Zeile des Titels, innere Titel zuerst; geht in keine Belegsumme. Titel und Text selbst haben Menge 0 und Preis 0 | `services.titelsummen` | `+` |
| R-182 | Nachlass je Rechnung | Summe der Bruttobeträge (R-005) aller **festgeschriebenen** Rechnungskorrekturen mit `vorgaenger` = diese Rechnung, positiv. Entwürfe und stornierte (`nachlass_stornieren`) zählen nicht; Rechnung, Nachlass und beide Stornos ergeben zusammen null. Mindert R-147 und R-149, steht in der Forderungszeile der Mahnung („Nachlass … EUR“; „bereits bezahlt“ = Brutto − Nachlass − offen). Obergrenze: alle Nachlässe ≤ Rechnungsbrutto (`festschreiben.pruefe_rechnungskorrektur`). Begründung in `entscheidungen.md` | `services.nachlaesse`, `services.nachlass` | `+` |
| R-167 | Genau einmal | Abgesetzt ist, worauf eine Abzugszeile einer **nicht stornierten** Rechnung verweist; **ein Entwurf zählt mit**. Löschen oder Stornieren gibt den Abschlag wieder frei; das Storno selbst setzt nichts ab. Mehrfach aufrufbar, fügt nur Fehlendes ein | `abschlaege.anrechenbare_abschlagspositionen`, `abschlaege.abschlaege_absetzen` | `+` |
| R-171 | Leistungssummen | R-002 bis R-005 **ohne** die Abzugszeilen: die volle Leistung der (Teil-)Schlussrechnung. Ohne Abzugszeilen gleich den Belegsummen | `services.leistungssummen` | `+` |
| R-168 | Vorauszahlung in der E-Rechnung | BT-106/109/110/112 aus R-171; BT-113 = Brutto nach R-171 minus Brutto nach R-005, **als Differenz**, damit BR-CO-16 (BT-115 = BT-112 − BT-113) auf den Cent aufgeht; BT-115 = R-005, derselbe Betrag wie auf dem Blatt und in den offenen Posten | `facturx.xml_erzeugen` | `+` |
| R-169 | Nicht voll bezahlte abgesetzte Abschläge | Je abgesetztem Abschlag sein Brutto (R-005) minus Vereinnahmtes (Betrag plus Skonto, **ohne Kürzung**); gemeldet, wenn größer null. Genau das fordert die Rechnung mit der Restzeile erneut. Ein Hinweis vor dem Festschreiben, keine Sperre | `abschlaege.offene_abgesetzte_abschlaege` | `+` |
| R-170 | Entgelt einer Teilleistung | Summe der Positionsnetti (R-001, **je Position gerundet**) der Auftragspositionen der Abnahme, **ohne optionale** (R-178) | `Abnahme.entgelt_netto` | `+` |
| R-174 | Restzeile eines nicht voll bezahlten Abschlags | Je Abzugszeile: Netto der Abschlagsposition mal (Brutto des Abschlags minus Vereinnahmtes) durch Brutto des Abschlags, **je Position auf den Cent**; Vereinnahmtes = Betrag plus Skonto der Zuordnungen, ohne Kürzung. Positiv, derselbe Steuersatz, `ist_abzug` und `ist_abschlagsrest`, direkt unter der Absetzung. Netto abgesetzt bleibt so das Vereinnahmte (§ 14 Abs. 5 Satz 2 UStG). Gefordert ist der Rest über einen späteren Abschlag oder mit dieser Rechnung; der Text sagt deshalb nur „davon nicht bezahlt, daher nicht abgesetzt“. Im PDF keine eigene Zeile: `abzugsblock` zeigt je Absetzung „gestellt …, bezahlt …“ mit dem Betrag beider Zeilen. Bei jedem „Abschläge absetzen“ abgeglichen; das Festschreiben weist eine veraltete Restzeile ab. **In keiner Umsatzsumme** (R-018, R-023, R-027, R-028, R-031): Der Betrag steht schon im Abschlag | `abschlaege.abschlagsrest`, `abschlaege._reste_abgleichen`, `abschlaege.veraltete_abschlagsreste` | `+` |
| R-175 | Kürzung eines Abschlags | Von Hand an der Zahlungszuordnung, brutto, **nur beim Abschlag**: was der Kunde nicht anerkennt und später gefordert wird. Zählt zum Ausgleich (R-144), nicht zum Vereinnahmten; sie schließt also den offenen Posten, und die Schlussrechnung fordert den Betrag erneut. Anders als Skonto nicht erlassen | `Zahlungszuordnung.kuerzung` | `+` |
| R-172 | Positionen der Teilschlussrechnung | Je Position der Teilleistung ihre **offene Menge** (R-010) zu Preis und Satz aus dem Vertrag; Positionen ohne offene Menge fallen weg, ganz ohne offene Menge entsteht keine Rechnung. Die Schlussrechnung bleibt ohne Positionen | `services.rechnung_aus_abnahme` | `+` |

Geprüft in `faktura/tests/test_abnahme.py` (Regelfall, BT-113, BR-CO-16,
Korrektur, nichts doppelt) und `faktura/tests/test_abschlagsluecken.py` (Ränder:
zwei Entwürfe, gelöschter Entwurf, korrigierter Abschlag, Abschlag im
Entwurf, zwei Steuersätze, Teilzahlung, Rundung des Entgelts, dazu der
Querabgleich mit R-008, R-023, R-028 und R-162). R-024 ohne Absetzungen
prüft `auswertung/tests/test_ergebnisse.py`
(`test_die_absetzung_mindert_die_leistung_nicht`,
`test_das_storno_eines_abschlags_mindert_die_leistung_nicht`).

**Gekürzter Abschlag (R-174, R-175).** Die Abschlagsforderung erlischt mit
der Schlussrechnung. Was am Tag des Absetzens nicht bezahlt ist, fordert die
Schlussrechnung selbst; eine spätere Zahlung gehört auf sie. Beispiel:
Auftrag 120.000, Abschlag 1 über 50.000 nur zu 40.000 bezahlt, Abschlag 2
über 60.000; die Schlussrechnung fordert 20.000. Abzugszeilen ohne Verweis
(Altform, R-165) schließen keinen Abschlag. Geprüft in
`faktura/tests/test_abschlagskuerzung.py`.

**Kumulierte Abschlagsrechnung (R-183 bis R-186).** Ab dem zweiten Abschlag
zeigen PDF, E-Rechnung und Maske den Leistungsstand und ziehen die
gestellten Abschläge ab. Gespeichert bleibt der Zuwachs, die Belegsumme
(R-005) ist also unverändert der Abschlagsbetrag; alle Regeln dieses
Abschnitts und von J rechnen weiter mit den Positionen. Implementiert in
`faktura/services/kumuliert.py`.

| Nr | Größe | Rechenregel | Implementierung | Test |
| --- | --- | --- | --- | --- |
| R-183 | Vorgänger eines Abschlags | Festgeschriebene Abschläge desselben Projekts, die in der Ordnung von R-012 (Belegdatum, pk) vor ihm stehen. **Nicht** Entwürfe, **nicht** stornierte. Ohne Vorgänger und in einem Projekt mit Teilabnahme keine kumulierte Sicht | `kumuliert.vorgaenger_abschlaege`, `kumuliert.ist_kumulierbar` | `+` |
| R-184 | Zeile des Leistungsstands | Über die Positionen der Vorgänger und des Abschlags (ohne Titel, Text, optionale): je Auftragsposition und Satz, sonst je Bezeichnung, Einheit, Satz und Art, ein Zuschlag je Bezeichnung, Prozentsatz, Bezug und Satz. Betrag = **Summe der Positionsnetti** (R-001, je Position gerundet). Gesamtmenge mal Preis nur, wenn alle Positionen der Gruppe denselben Preis und dieselbe Einheit haben und das Produkt auf den Cent den Betrag ergibt; sonst Menge 1, „pausch“, Preis = Betrag | `kumuliert._kumulieren` | `+` |
| R-185 | Vorgängerzeile | Je Vorgänger und Satz dessen Netto (R-002), **negativ**: gestellt, nicht bezahlt, damit ein offener Abschlag nicht ein zweites Mal gefordert wird. Im XML eine Zeile mit Menge −1 und positivem Preis (BR-27), dieselben Zeilen wie im PDF | `kumuliert.kumulierter_abschlag`, `KumulierterAbschlag.xml_zeilen` | `+` |
| R-186 | Abschlagsbetrag kumuliert | Je Satz: Summe R-184 plus Summe R-185 = Netto des Abschlags (R-002), **auf den Cent**. Steuer, Brutto und BT-106 bis BT-115 damit wie bisher; kein BT-113 | `pdf.beleg_als_html`, `facturx.xml_erzeugen` | `+` |

Geprüft in `faktura/tests/test_kumulierter_abschlag.py` (Gruppierung,
Rundung je Position, zwei Steuersätze, drei Abschläge, Storno und Entwurf
als Vorgänger, Teilabnahme, PDF, XML, Maske).


## Regeln für Änderungen

- **Gerundet wird nur über `core/rechnen.py`** (`auf_cent`, `auf_stufe`,
  kaufmännisch mit `ROUND_HALF_UP`). Pythons Vorgabe für `quantize` ist
  `ROUND_HALF_EVEN` und weicht bei halben Cent ab, etwa 0,25 Std zu 78,50 €:
  19,62 statt 19,63. `tests/test_grenzzaun.py` verbietet `quantize` im
  übrigen Produktivcode.
- **SQL-Summen über Positionen verwenden `services.POSITIONSNETTO`**, das je
  Position rundet wie R-001. Eine eigene Summe von `menge * einzelpreis`
  weicht vom Beleg ab.
- **„Abgerechnet“ ist einmal definiert** (`NOCH_NICHT_ABGERECHNET` und seine
  Negation). Auswertungen zählen Zeilen auf einem Rechnungsentwurf als offen
  (`abrechnungsvorschau(entwuerfe_zaehlen=True)`), das Übernehmen in eine
  Rechnung nicht.
- **Eine neue Größe ist eine Frage an jede bestehende Formel.** Mit den
  Zahlungseingängen musste die Mahnung vom Bruttobetrag auf den offenen
  Betrag umgestellt werden (R-153); mit den Abzugszeilen der
  Schlussrechnung mussten sie aus der abgerechneten Leistung herausgenommen
  werden (R-024). Wer eine Zeilenart, einen Betrag oder einen Zustand
  einführt, sieht alle Summen durch, die darüber laufen.
- **Ein Filter ist eine Regel.** Wer eine geprüfte Formel auf eine Teilmenge
  anwendet, prüft auch die Teilmenge (siehe Kundenakte in Abschnitt J).

## Tests

- **Sollwerte:** Beispiele mit von Hand gerechnetem Ergebnis, in den
  Testdateien der jeweiligen App (etwa `faktura/tests/test_auswertung.py`,
  `auswertung/tests/test_controlling.py`); Einträge ohne eigenen Testort in
  `tests/test_rechenluecken.py`.
- **Eigenschaften** (`tests/test_recheneigenschaften.py`, Hypothesis):
  Invarianten über generierte Eingaben ohne Datenbank, etwa „netto plus
  Steuer ergibt brutto“ oder „der Auftragsbestand ist nie negativ“.
- **Querabgleiche** (`tests/test_rechenabgleich.py`): Größen, die an zwei
  Stellen gerechnet werden, etwa in Python über `belegsummen` und in SQL über
  `POSITIONSNETTO`, müssen auf den Cent übereinstimmen.
