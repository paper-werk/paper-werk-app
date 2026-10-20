# Mitarbeit

Einrichtung der Entwicklungsumgebung: [README](README.md#einstieg).

## Ablauf

- Pull Requests gehen gegen `dev`. `main` enthält nur ausgelieferte
  Versionen.
- Größere Änderungen vorher in einem Issue abstimmen, Änderungen am Layout der
  Belegmaske immer ([Belegansicht](docs/belegansicht.md)).
- Vor dem Pull Request `./pruefen.sh` (ruff, Django-Prüfungen, offene
  Migrationen, Tests). Die CI führt dieselben Schritte aus, dazu einen Lauf
  ohne die App `auswertung`.
- Für Beiträge ist die Zustimmung zur Lizenzvereinbarung (siehe unten)
  Voraussetzung.
- Sicherheitslücken nicht als Issue melden, sondern wie in
  [SECURITY.md](SECURITY.md) beschrieben.

## Sprache

Paper-Werk bildet deutsches Rechnungs- und Steuerrecht ab und ist deshalb
ein deutschsprachiges Projekt.

- Fachbegriffe in Code, Oberfläche und Doku sind deutsch: `Beleg`,
  `festschreiben`, `abschlaege`, `Steuerfall`.
- Django- und Infrastrukturbegriffe bleiben englisch, wie Django sie nennt:
  `permissions`, `pagination`, `exception_handler`, `optimistic_locking`.
- In Bezeichnern Umlaute ausschreiben (`ae`, `oe`, `ue`, `ss`), in Texten,
  Kommentaren und Commit-Nachrichten echte Umlaute.
- Commit-Nachrichten und Issues auf Deutsch.

## Regeln im Code

- **Berechnungen** stehen in den Services (`faktura/services/`,
  `erfassung/services/`, `auswertung/ergebnisse.py`,
  `auswertung/controlling.py`), nicht in Admin, Views oder Templates.
  `tests/test_grenzzaun.py` prüft das.
- **Jede neue oder geänderte Berechnung** bekommt einen Eintrag im
  [Rechenregister](docs/rechenregister.md) mit Test. Dort stehen
  auch die Regeln für Änderungen an bestehenden Formeln.
- **Abhängigkeiten zwischen den Apps** gehen nur in eine Richtung:
  `core` ← `faktura` ← `erfassung` ← `auswertung`. Obere Apps melden sich
  über `core/erweiterungen.py` an (`tests/test_richtung.py`).
- **Kernfunktionen** wie Festschreiben und Versenden hängen an keiner
  Einstellung ([Entscheidungen](docs/entscheidungen.md#grundsätze)).
- **Kommentare** erklären, warum etwas so gebaut ist. Wie es dazu kam, steht
  in der Git-Historie.

## Lizenz und Mitwirkung

Paper-Werk ist freie Software unter der [AGPL-3.0](LICENSE).

Damit die Rechte an der Codebasis gebündelt bleiben, gilt für jeden Beitrag:

- Mit dem Einreichen eines Pull Requests bestätigst du, dass der eingereichte
  Code dein eigenes Werk ist oder du über die dafür erforderlichen Rechte
  verfügst.
- Du räumst Horst Amper / KI-Werkstatt das dauerhafte, weltweite und unentgeltliche
  Recht ein, deinen Beitrag unter der AGPLv3 sowie unter alternativen (auch
  kommerziellen) Lizenzen zu nutzen und zu vertreiben.
- Deine Urheberschaft in der Git-Historie und in den Release-Notizen bleibt
  selbstverständlich erhalten.
