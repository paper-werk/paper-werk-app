# Prüfprotokoll Lasttest Paper-Werk

**Prüfgegenstand:** Paper-Werk, Entwicklungsstand vom 4. Oktober 2026 nach
Version 0.1.7 (Angebote, Aufträge, Rechnungen, Zeiterfassung)
**Datum der Prüfung:** Bestand erzeugt am 3. Oktober 2026, gemessen am 4. Oktober 2026
**Frage:** Bleiben Anzeige und Bedienung zügig, wenn ein Büro zehn Jahre
lang mit Paper-Werk arbeitet? Bremst die Änderungsgeschichte der erfassten
Zeiten Anzeige oder Ausführung?

## 1. Szenario

Ingenieurbüro, **zehn Beschäftigte**, arbeitet seit Oktober 2016 mit Paper-Werk.
Dazu eine zweite Stufe mit der
**dreifachen Größe** (dreißig Beschäftigte) über denselben Zeitraum.

| Vorgang                                                                                          |                                   je Monat |
| ------------------------------------------------------------------------------------------------ | -----------------------------------------: |
| neue Vorhaben mit Angebot und Auftrag (70 % klein, 25 % mittel, 5 % groß)                        |                                         10 |
| Angebote ohne Auftrag                                                                            |                                          7 |
| neue Kunden (jeder fünfte als Stammkunde mit achtfacher Auftragshäufigkeit)                      |                                        2,5 |
| Zeiterfassung: je Person und Werktag zwei Blöcke auf Vorhaben, meist zwei Stunden interne Arbeit |                            rund 620 Zeilen |
| nachträgliche Änderung erfasster Zeilen am Folgetag                                              | jede vierte Zeile, jede zwanzigste zweimal |
| Eingangsrechnungen über Fremdleistung (Laboranalytik), auf Vorhaben verteilt                     |                                         21 |
| Abrechnung der erfassten Leistungen                                                              |        am Monatsende je laufendem Vorhaben |
| Abschlagsrechnungen großer Vorhaben, Schlussrechnung mit Absetzung                               |                       je Quartal, zum Ende |
| Zahlungseingänge                                                                                 |               8 bis 150 Tage nach Rechnung |
| Mahnungen                                                                                        |                    bei Verzug, zwei Stufen |
| Rechnungskorrektur (Storno und neue Rechnung)                                                    |                                          1 |

**Umsatz netto je Jahr** (2017 bis 2025): 1,08 bis 1,23 Mio € bei zehn
Beschäftigten, 3,26 bis 3,67 Mio € in der dreifachen Stufe.

**Wie der Bestand entsteht.** Ein Generator stellt die Uhr der Anwendung
Werktag für Werktag von Oktober 2016 bis Oktober 2026 vor und ruft dabei
dieselben Funktionen auf, die auch die Bedienoberfläche aufruft: Zeile
erfassen, Zeile ändern, in Rechnung übernehmen, festschreiben, Zahlung
verbuchen, mahnen. Belegnummern, Belegdaten, Fälligkeiten und die Einträge
der Änderungsgeschichte entstehen dadurch so wie im Betrieb. Die Erzeugung
dauerte 18 Minuten (zehn Beschäftigte) und 50 Minuten (dreifache Stufe).

**Vereinfachungen.**

- Kunden, Beschäftigte und Lieferanten tragen Nummernnamen („Kunde 0042“,
  Vorname „Mitarbeiter“).
- Je Belegart wurde ein PDF erzeugt; alle weiteren Belege dieser Art
  verweisen auf dieselbe Datei. Die Zahl der Dateien im Ablageordner ist
  deshalb nicht aussagekräftig, die Zahl der Belege mit PDF schon.
- Keine Archivierung im Dokumentenarchiv (Paperless-ngx), kein Versand,
  keine E-Rechnungs-XML.
- Die Stunden großer Vorhaben sind als nicht abrechenbar erfasst, weil diese
  Vorhaben über Abschläge und Schlussrechnung abrechnen.

## 2. Testumgebung

|                  |                                                                                                   |
| ---------------- | ------------------------------------------------------------------------------------------------- |
| Rechner          | Intel Core i5-9400 (6 Kerne, 2,9 GHz), 48 GB RAM, Windows 11 Pro                                  |
| Container        | Docker 29.6.1 (Docker Desktop), 6 CPUs und 23 GB für Container                                    |
| Datenbank        | PostgreSQL 18.4 im Container, Standardeinstellungen; parallele Abfragen schaltet die Anwendung ab |
| Anwendung        | Paper-Werk (siehe oben), Python 3.13.11, Django 6.1, django-simple-history 3.13.0                 |
| Anwendungsserver | gunicorn, 3 Prozesse                                                                              |
| Betriebsart      | Produktionseinstellungen (DEBUG aus), eigene Installation nur für diese Prüfung                   |

Während der Messungen lief auf dem Rechner keine weitere Paper-Werk- oder
Paperless-Installation. Ein fremder Container-Stack lief ohne Last mit.

## 3. Testverfahren

**Seiten.** 30 Seiten der Anwendung: Startseite, Controlling, die
Arbeitsliste „Nicht abgerechnet“, die wichtigen Listen (mit Suche, Filter
und letzter Seite), Bearbeitungsmasken, die Akten und fünf Listen der
Programmierschnittstelle (API). Detailseiten werden **immer am größten
Objekt** gemessen: dem Kunden mit den meisten Belegen, dem Projekt mit den
meisten Erfassungszeilen, der gewöhnlichen Rechnung mit den meisten
Positionen und der Zeile mit der längsten Änderungsgeschichte.

Die Erfassung wird zweimal durchsucht. Die **Suche nach Person** verwendet
einen Begriff, der im Namen jeder beschäftigten Person steckt, und trifft
damit jede Zeile des Bestands; das ist der ungünstigste Fall. Die **Suche
nach Projekt** verwendet die Nummer des größten Projekts.

Je Seite ein Aufwärmaufruf, in dem die SQL-Abfragen gezählt werden, dann
15 gemessene Aufrufe. Angegeben sind Median und 95. Perzentil (p95). Die
Zeit reicht von der Anfrage bis zur fertigen Seite in der Anwendung, ohne
Netz und ohne Browser.

**Aktionen.** Fünf schreibende Vorgänge, je 15 Läufe (Festschreiben mit PDF:
5 Läufe). Jeder Lauf läuft in einer eigenen Transaktion, die danach
zurückgenommen wird; der Bestand bleibt so für alle Messungen derselbe.

**Mit und ohne Änderungsgeschichte.** Die Tabellen der Änderungsgeschichte
werden in einer Transaktion geleert, ausgewählte Seiten und Aktionen erneut
gemessen und die Leerung danach zurückgenommen.

**Über HTTP.** Sechs Seiten zusätzlich von außen über den Anwendungsserver,
je ein Aufwärmaufruf und zehn gemessene Aufrufe mit curl.

**Messpunkte.** Ein fortlaufender Bestand, gemessen nach 1, 3, 5 und 10
Jahren, dazu die dreifache Stufe nach 10 Jahren. Jeder Messpunkt wurde
zweimal gemessen. Angegeben ist je Seite der Lauf mit dem kleineren Median,
da Störungen auf dem Messrechner Messungen nur verlängern. **Ein \* am
Wert** bedeutet: Die beiden Läufe weichen um mehr als 30 % voneinander ab.

## 4. Mengengerüst

|                        | Jahr 1 | Jahr 3 | Jahr 5 | Jahr 10 | Jahr 10, dreifach |
| ---------------------- | -----: | -----: | -----: | ------: | ----------------: |
| Kunden                 |    177 |    237 |    291 |     443 |             1.365 |
| Projekte               |    126 |    367 |    606 |   1.197 |             3.560 |
| Belege                 |    628 |  1.964 |  3.302 |   6.562 |            19.470 |
| Belegpositionen        |  2.822 |  9.215 | 15.298 |  30.857 |            91.568 |
| Erfassungszeilen       |  7.463 | 22.537 | 37.700 |  75.497 |           226.199 |
| Historie der Erfassung |  8.892 | 26.993 | 45.182 |  90.454 |           271.218 |
| Eingangsrechnungen     |    242 |    735 |  1.235 |   2.490 |             7.581 |
| Zahlungen              |    188 |    752 |  1.296 |   2.656 |             7.853 |
| Belege mit PDF         |    504 |  1.601 |  2.702 |   5.376 |            15.921 |
| Datenbank (MB)         |     18 |     29 |     39 |      65 |               169 |
| Media-Ordner (Dateien) |     10 |     10 |     10 |      10 |                10 |

Die größte Tabelle ist nach zehn Jahren die Änderungsgeschichte der
Erfassung (24 MB bei zehn Beschäftigten), vor den Erfassungszeilen selbst
(16 MB).

## 5. Seiten

### Median in ms, in Klammern die Zahl der SQL-Abfragen

|                                            |     Jahr 1 |   Jahr 3 |   Jahr 5 |    Jahr 10 | Jahr 10, dreifach |
| ------------------------------------------ | ---------: | -------: | -------: | ---------: | ----------------: |
| Startseite                                 |   114 (20) | 128 (20) | 154 (20) |   140 (20) |          353 (20) |
| Controlling                                |   102 (16) | 112 (16) | 131 (16) |   120 (17) |          292 (17) |
| Nicht abgerechnet                          |     42 (9) |   48 (9) |   54 (9) |     71 (9) |           157 (9) |
| Rechnungen, Liste                          |   199 (13) | 211 (13) | 214 (13) |   231 (13) |          291 (13) |
| Rechnungen, letzte Seite                   |    86 (13) | 105 (13) | 149 (13) |   144 (13) |          262 (13) |
| Rechnungen, Suche                          |    71 (13) |  92 (13) | 108 (13) |   148 (13) |          269 (13) |
| Rechnungen, Filter festgeschrieben         |   208 (13) | 208 (13) | 213 (13) |   231 (13) |          292 (13) |
| Angebote, Liste                            |   188 (12) | 189 (12) | 191 (12) |   203 (12) |          250 (12) |
| Aufträge, Liste                            |   201 (13) | 218 (13) | 239 (13) |   289 (13) |          490 (13) |
| Mahnungen, Liste                           |    89 (13) | 170 (13) | 173 (13) |   177 (13) |          202 (13) |
| Kunden, Liste                              |    159 (7) |  167 (7) |  177 (7) |    207 (7) |           295 (7) |
| Projekte, Liste                            |     66 (6) |   67 (6) |   63 (6) |     68 (6) |           131 (6) |
| Erfassung, Liste                           |   229 (11) | 276 (11) | 325 (11) |   441 (11) |          989 (11) |
| Erfassung, Suche nach Person               |   331 (11) | 553 (11) | 756 (11) | 1.302 (11) |        8.224 (11) |
| Erfassung, Suche nach Projekt              |   250 (11) | 278 (11) | 306 (11) |   375 (11) |        1.456 (11) |
| Erfassung, neue Zeile (Formular)           |     82 (8) | 82\* (8) |   76 (8) |     82 (8) |           141 (8) |
| Erfassung, Zeile bearbeiten                |    92 (13) |  93 (13) |  96 (13) |   111 (13) |          192 (13) |
| Erfassung, Änderungsgeschichte einer Zeile |    46 (11) |  46 (11) |  48 (11) |    46 (11) |           46 (11) |
| Eingangsrechnungen, Liste                  |   168 (11) | 166 (11) | 167 (11) |   166 (11) |          177 (11) |
| Zahlungen, Liste                           |    153 (9) |  153 (9) |  155 (9) |    154 (9) |           166 (9) |
| Rechnung bearbeiten                        | 161\* (26) | 162 (26) | 169 (26) |   168 (26) |          168 (26) |
| Rechnungsakte                              |    59 (20) |  57 (20) |  60 (20) |    58 (20) |           59 (20) |
| Kundenakte, größter Kunde                  |    70 (22) |  71 (22) |  71 (19) |    77 (19) |          102 (19) |
| Projektakte, größtes Projekt               |   117 (29) | 130 (29) | 136 (29) |   157 (29) |          172 (29) |
| Auftragsakte, größtes Projekt              |   109 (28) | 113 (29) | 108 (27) |   111 (28) |          115 (29) |
| API, belege                                |     31 (5) |   36 (5) |   39 (5) |     48 (5) |            82 (5) |
| API, eingangsrechnungen                    |     16 (6) |   17 (6) |   18 (6) |     18 (6) |            22 (6) |
| API, projekte                              |      7 (4) |    8 (4) |    7 (4) |      7 (4) |             7 (4) |
| API, kunden                                |     22 (7) |   21 (7) |   20 (7) |     21 (7) |            20 (7) |
| API, kontakte                              |     22 (7) |   22 (7) |   23 (7) |     24 (7) |            22 (7) |

Die Endpunkte `projekte`, `kunden` und `kontakte` gehören nicht zum Kern;
sie wurden mit einer zum Zeitpunkt der Prüfung installierten Erweiterung
gemessen.

### 95. Perzentil in ms

|                                            | Jahr 1 | Jahr 3 | Jahr 5 | Jahr 10 | Jahr 10, dreifach |
| ------------------------------------------ | -----: | -----: | -----: | ------: | ----------------: |
| Startseite                                 |    170 |    142 |    164 |     160 |               410 |
| Controlling                                |    112 |    129 |    136 |     174 |               318 |
| Nicht abgerechnet                          |     46 |     52 |     55 |      78 |               216 |
| Rechnungen, Liste                          |    273 |    296 |    288 |     268 |               373 |
| Rechnungen, letzte Seite                   |    102 |    112 |    156 |     165 |               337 |
| Rechnungen, Suche                          |     79 |     97 |    118 |     153 |               278 |
| Rechnungen, Filter festgeschrieben         |    223 |    284 |    292 |     303 |               411 |
| Angebote, Liste                            |    273 |    208 |    201 |     304 |               329 |
| Aufträge, Liste                            |    244 |    310 |    251 |     376 |               605 |
| Mahnungen, Liste                           |    172 |    188 |    248 |     187 |               316 |
| Kunden, Liste                              |    174 |    179 |    213 |     296 |               337 |
| Projekte, Liste                            |     78 |    186 |     70 |      71 |               139 |
| Erfassung, Liste                           |    238 |    338 |    333 |     483 |             1.046 |
| Erfassung, Suche nach Person               |    345 |    602 |    844 |   1.495 |             8.924 |
| Erfassung, Suche nach Projekt              |    355 |    294 |    387 |     439 |             1.508 |
| Erfassung, neue Zeile (Formular)           |     90 |    151 |     81 |     102 |               202 |
| Erfassung, Zeile bearbeiten                |    110 |    101 |    114 |     115 |               205 |
| Erfassung, Änderungsgeschichte einer Zeile |     52 |     49 |     58 |      50 |                57 |
| Eingangsrechnungen, Liste                  |    247 |    191 |    254 |     234 |               243 |
| Zahlungen, Liste                           |    166 |    220 |    168 |     158 |               214 |
| Rechnung bearbeiten                        |    170 |    177 |    203 |     181 |               178 |
| Rechnungsakte                              |     78 |     69 |     82 |      63 |                76 |
| Kundenakte, größter Kunde                  |    140 |     74 |    152 |      83 |               171 |
| Projektakte, größtes Projekt               |    128 |    192 |    165 |     229 |               212 |
| Auftragsakte, größtes Projekt              |    143 |    157 |    170 |     154 |               178 |
| API, belege                                |     38 |     44 |     45 |     118 |                89 |
| API, eingangsrechnungen                    |     21 |     84 |     24 |      26 |                28 |
| API, projekte                              |     13 |     12 |      9 |      12 |                 8 |
| API, kunden                                |     91 |     26 |     25 |      26 |                27 |
| API, kontakte                              |     29 |     27 |     27 |      29 |                92 |

## 6. Aktionen

Median in ms, in Klammern die Zahl der SQL-Abfragen.

|                                             |   Jahr 1 |   Jahr 3 |   Jahr 5 |  Jahr 10 | Jahr 10, dreifach |
| ------------------------------------------- | -------: | -------: | -------: | -------: | ----------------: |
| Zeile erfassen                              |   7 (10) |   6 (10) |   6 (10) |   6 (10) |            6 (10) |
| Zeile ändern (schreibt Historie)            |   9 (13) |   9 (13) |   9 (13) | 9\* (13) |           10 (13) |
| Abrechnen: 40 Zeilen in Rechnung übernehmen |  22 (19) |  19 (19) |  20 (19) |  21 (19) |           20 (19) |
| Festschreiben mit echtem PDF (7 Positionen) | 434 (19) | 439 (19) | 418 (19) | 426 (19) |          429 (19) |
| Zahlung verbuchen                           |  14 (17) |  14 (17) |  14 (17) |  14 (17) |           14 (17) |

## 7. Mit und ohne Änderungsgeschichte

Median in ms. „Ohne“ heißt: Die Tabellen der Änderungsgeschichte sind leer.

| Stand             |                          Seite oder Aktion | mit | ohne |
| ----------------- | -----------------------------------------: | --: | ---: |
| Jahr 1            |                                 Startseite | 114 |  116 |
| Jahr 1            |                                Controlling | 102 |  103 |
| Jahr 1            |                           Erfassung, Liste | 229 |  231 |
| Jahr 1            |                Erfassung, Zeile bearbeiten |  92 |   90 |
| Jahr 1            | Erfassung, Änderungsgeschichte einer Zeile |  46 |   35 |
| Jahr 1            |               Projektakte, größtes Projekt | 117 |  112 |
| Jahr 1            |                             Zeile erfassen |   7 |    6 |
| Jahr 1            |           Zeile ändern (schreibt Historie) |   9 |  9\* |
| Jahr 10           |                                 Startseite | 140 |  143 |
| Jahr 10           |                                Controlling | 120 |  119 |
| Jahr 10           |                           Erfassung, Liste | 441 |  446 |
| Jahr 10           |                Erfassung, Zeile bearbeiten | 111 |  111 |
| Jahr 10           | Erfassung, Änderungsgeschichte einer Zeile |  46 |   37 |
| Jahr 10           |               Projektakte, größtes Projekt | 157 |  158 |
| Jahr 10           |                             Zeile erfassen |   6 |    6 |
| Jahr 10           |           Zeile ändern (schreibt Historie) | 9\* |    9 |
| Jahr 10, dreifach |                                 Startseite | 353 |  362 |
| Jahr 10, dreifach |                                Controlling | 292 |  296 |
| Jahr 10, dreifach |                           Erfassung, Liste | 989 |  987 |
| Jahr 10, dreifach |                Erfassung, Zeile bearbeiten | 192 |  196 |
| Jahr 10, dreifach | Erfassung, Änderungsgeschichte einer Zeile |  46 |   36 |
| Jahr 10, dreifach |               Projektakte, größtes Projekt | 172 |  170 |
| Jahr 10, dreifach |                             Zeile erfassen |   6 |    6 |
| Jahr 10, dreifach |           Zeile ändern (schreibt Historie) |  10 |    9 |

Die Werte für Jahr 3 und Jahr 5 liegen in den Rohdaten vor.

## 8. Über HTTP

Median und p95 in ms, gemessen über gunicorn und das Netz von Docker
Desktop. Gegenüber Abschnitt 5 kommen Netz, Auslieferung und die Prüfung
der Sitzung hinzu.

|                              |      Jahr 1 |    Jahr 3 |    Jahr 5 |   Jahr 10 | Jahr 10, dreifach |
| ---------------------------- | ----------: | --------: | --------: | --------: | ----------------: |
| Startseite                   |   275 / 307 | 293 / 352 | 322 / 389 | 318 / 443 |       571 / 1.095 |
| Controlling                  |   247 / 307 | 266 / 338 | 282 / 334 | 268 / 476 |         452 / 609 |
| Rechnungen, Liste            |   329 / 370 | 334 / 465 | 332 / 443 | 357 / 444 |         406 / 584 |
| Erfassung, Liste             | 337 / 1.051 | 382 / 537 | 443 / 509 | 554 / 617 |     1.123 / 1.779 |
| Kundenakte, größter Kunde    |   210 / 237 | 217 / 235 | 217 / 431 | 229 / 308 |         253 / 331 |
| Projektakte, größtes Projekt |   256 / 370 | 289 / 352 | 279 / 296 | 309 / 360 |         336 / 389 |

## 9. Abgleich mit den Zielwerten

Zielwerte der Prüfung: Seiten unter 1 s im p95, Aktionen unter 2 s.

| Stand             | über 1 s im p95, in der Anwendung                                             | über 1 s im p95, über HTTP   | Aktionen über 2 s |
| ----------------- | ----------------------------------------------------------------------------- | ---------------------------- | ----------------- |
| Jahr 1            | keine                                                                         | Erfassung, Liste             | keine             |
| Jahr 3            | keine                                                                         | keine                        | keine             |
| Jahr 5            | keine                                                                         | keine                        | keine             |
| Jahr 10           | Erfassung, Suche nach Person                                                  | keine                        | keine             |
| Jahr 10, dreifach | Erfassung, Liste; Erfassung, Suche nach Person; Erfassung, Suche nach Projekt | Startseite; Erfassung, Liste | keine             |

Festschreiben mit PDF lag an allen Messpunkten zwischen 418 und 439 ms.

## 10. Rohdaten und Wiederholung

Die Messwerte jedes Laufs (JSON und TSV), die Werkzeuge (Generator,
Messskript, Auswertung) und die Bestände aller Messpunkte als
Datenbankabzug liegen außerhalb dieses Repos. Die Bestände lassen sich
erneut laden und messen.
