# Verwaltung

Die Gruppe „Verwaltung“ ist für Administratoren: Benutzer, Gruppen und
API-Schlüssel. Wer hier nichts sieht, braucht hier nichts.

## Benutzer {#user}

Jede Person, die mit Paper-Werk arbeitet, hat ein Konto. Es gibt zwei Wege
der Anmeldung:

- **Mit Microsoft**, wenn die Installation an Microsoft Entra ID
  angebunden ist. Das Konto entsteht bei der ersten Anmeldung von selbst.
  Welche Gruppen es hat, bestimmt die Rolle, die der Person in Entra
  zugewiesen ist (siehe [Gruppen](#group)); ohne eine dieser Rollen kommt
  niemand herein.
- **Mit Benutzername und Passwort**: Diese Konten legt ein Administrator
  hier an. Der lokale Zugang bleibt auch bei Microsoft-Anbindung erhalten,
  als Notfallweg, falls das Verzeichnis nicht antwortet.

Selbst registrieren kann sich niemand.

**Die Liste** zeigt Benutzername, E-Mail, Vorname, Nachname, Mitarbeiter-
Status und Aktiv.

**Anlegen:** „+“, dann **Benutzername**, **Passwort** zweimal, E-Mail,
Vorname und Nachname. Nach dem Sichern öffnet sich die volle Maske:

- **Persönliche Informationen**: Name und E-Mail. Der Name steht in der
  Erfassung, im Leistungsnachweis und im Verlauf.
- **Berechtigungen**:
  - **Aktiv**: Ohne den Haken kann sich das Konto nicht anmelden.
  - **Mitarbeiter-Status**: nötig, um Paper-Werk überhaupt zu betreten.
  - **Administrator-Status**: hat alle Rechte, ohne dass sie einzeln
    vergeben sind.
  - **Gruppen**: Über sie bekommt das Konto seine Rechte. Vergeben Sie
    Rechte über Gruppen, nicht einzeln unter „Benutzerberechtigungen“.
- **Wichtige Daten**: letzte Anmeldung und Mitglied seit.

**Passwort:** Im Feld „Passwort“ der Maske führt der Knopf **Passwort
zurücksetzen** (bei Konten ohne Passwort **Passwort setzen**) zu einer
eigenen Seite. Jeder
Benutzer ändert sein eigenes Passwort über seinen Namen unten in der
Seitenleiste.

**Ausscheidende Mitarbeiter** deaktivieren Sie (Haken „Aktiv“ heraus),
statt sie zu löschen. Ihr Name hängt an Belegen, die sie festgeschrieben
haben, und an erfassten Stunden; ein solches Konto lässt sich auch gar
nicht löschen.

**Den letzten Administrator** schützt Paper-Werk: Ein Konto, das als
einziges aktiv ist und Mitarbeiter- und Administrator-Status hat, lässt
sich weder herabstufen noch deaktivieren noch löschen. Die Meldung sagt,
was zuerst zu tun ist: einem anderen Konto diese Rechte geben.

Bei Microsoft-Konten werden Gruppen, Mitarbeiter- und Administrator-Status
bei jeder Anmeldung aus den Rollen in Entra neu gesetzt. Eine Änderung
hier hält also nur bis zur nächsten Anmeldung; ändern Sie die Rolle in
Entra.

## Gruppen {#group}

Gruppen bündeln Rechte. Paper-Werk bringt diese Gruppen mit:

| Gruppe | Für wen | Darf |
|---|---|---|
| paper-werk-buero | Büro | Kontakte, Projekte, Katalog, Textbausteine, alle Belege und Zahlungen anlegen, ändern und löschen; Eigene Firma und Steuersätze ändern; die eigenen Stunden erfassen |
| paper-werk-projektleitung | Projektleitung | wie das Büro, dazu die Stunden aller sehen und für andere erfassen, Eingangsrechnungen und Kostensätze |
| paper-werk-superuser | Verwaltung | Administrator, alle Rechte |
| Faktura Dienst | Automatisierung (n8n) | Belege, Kunden und Projekte lesen, den Archivvermerk setzen; kein Zugang zur Oberfläche |
| Belegübernahme | Automatisierung | Eingangsrechnungen aus dem Archiv anlegen |

Zu den Rechten der Büro-Gruppe gehören auch das Controlling und das
Wiederöffnen von Angebot und Aufträgen.

Die Namen der paper-werk-Gruppen sind zugleich die Namen der Rollen in
Microsoft Entra ID und der Gruppen in Paperless: Wer einer Person in Entra
die Rolle „paper-werk-buero“ gibt, findet sie in beiden Anwendungen in
dieser Gruppe wieder.

Die Maske einer Gruppe zeigt ihren Namen und zwei Listen: verfügbare und
gewählte Rechte. Ändern Sie die Rechte der mitgelieferten Gruppen nicht
von Hand: Ein Update setzt sie auf den mitgelieferten Stand zurück. Soll
eine Gruppe anders zugeschnitten sein, sprechen Sie mit dem Betreuer
Ihrer Installation.

## API-Schlüssel {#tokenproxy}

Über die Schnittstelle greifen andere Programme auf Paper-Werk zu, etwa
n8n, um Eingangsrechnungen aus dem Archiv zu übernehmen oder das XML einer
Rechnung an den Steuerberater zu schicken. Sie melden sich mit einem
API-Schlüssel an.

Jedes Konto hat höchstens einen Schlüssel. **Anlegen:** „+“, Benutzer
wählen, sichern; der Schlüssel entsteht beim Sichern und steht danach zum
Kopieren da. Der Schlüssel ist unbegrenzt gültig und darf, was sein Konto
darf. Löschen Sie ihn, wenn er nicht mehr gebraucht wird oder in falsche
Hände geraten sein könnte; danach legen Sie einen neuen an und tragen ihn
im anderen Programm ein.

Dienstzugänge für die Automatisierung richtet in der Regel der Betreuer
der Installation ein: als eigenes Konto ohne Passwort, ohne Zugang zur
Oberfläche und mit Rechten nur über die Gruppe „Faktura Dienst“.
