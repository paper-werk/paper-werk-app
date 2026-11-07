// Szenarien für probelauf.mjs. Ereignisse im Format von docs/webhooks.md
// (paper-werk-app).

import assert from 'node:assert/strict';

const EINSTELLUNGEN = {
  paperwerk_url: 'http://paper-werk-app:8000/',
  paperless_url: 'http://paperless:8000',
  mail_betrieb: 'buero@example.invalid',
  mail_absender: 'paper-werk@example.invalid',
  instanz: 'muster',
  chat_webhook_url: 'https://chat.example/hooks/abc',
};

const beleg = (felder = {}) => ({
  id: 4711, typ: 'rechnung', nummer: 'RE-2026-0042', betreff: 'Planung Halle 3',
  brutto: '1487.50', faellig_am: '2026-11-16', kunde: { name: 'Muster GmbH' },
  projekt: null, vorgaenger: null, version: 7,
  admin_url: 'https://pw.example/admin/faktura/rechnung/4711/change/',
  api_url: 'https://pw.example/api/v1/belege/4711/',
  ...felder,
});
const ereignis = (aktion, felder) => ({ ereignis: 'beleg', aktion, zeit: '2026-11-02T14:03:11+01:00', beleg: beleg(felder) });
const angebot = { id: 17, typ: 'angebot', nummer: 'AN-2026-0017', faellig_am: null, brutto: '4200.00' };
const auftrag = { id: 18, typ: 'auftrag', nummer: 'AB-2026-0009', faellig_am: null, brutto: '4200.00' };
const projekt = { id: 3, nummer: '2026-003', bezeichnung: 'Halle 3' };

const keineAusgabe = (e) => {
  assert.equal(e.mails.length, 0, 'keine Mail');
  assert.equal(e.zeilen.length, 0, 'keine Zeile');
  assert.ok(!e.aufrufe.some((a) => a.methode !== 'GET'), 'kein schreibender Aufruf');
};

export const szenarien = [
  // -- beleg-angebot-nachfassen -------------------------------------------
  {
    workflow: 'beleg-angebot-nachfassen', titel: 'ohne Nachfolger geht eine Mail',
    ereignis: ereignis('versendet', angebot), einstellungen: EINSTELLUNGEN,
    http: { 'Nachfolger laden': { count: 0, results: [] } },
    pruefe: (e) => {
      assert.equal(e.wartezeit, 14);
      assert.equal(e.aufrufe[0].url, 'http://paper-werk-app:8000/api/v1/belege/?vorgaenger=17');
      assert.equal(e.mails[0].toEmail, 'buero@example.invalid');
      assert.match(e.mails[0].subject, /Angebot AN-2026-0017 nachfassen: Muster GmbH/);
      assert.match(e.mails[0].html, /4\.200,00/);
    },
  },
  {
    workflow: 'beleg-angebot-nachfassen', titel: 'mit Auftrag bleibt es still',
    ereignis: ereignis('versendet', angebot), einstellungen: EINSTELLUNGEN,
    http: { 'Nachfolger laden': { count: 1, results: [{ id: 18 }] } },
    pruefe: keineAusgabe,
  },
  {
    workflow: 'beleg-angebot-nachfassen', titel: 'Testaufruf endet in der Konfiguration',
    ereignis: { ereignis: 'beleg', aktion: 'test', beleg: beleg(angebot) }, einstellungen: EINSTELLUNGEN,
    pruefe: (e) => { assert.equal(e.letzter, 'Konfiguration'); keineAusgabe(e); },
  },
  {
    workflow: 'beleg-angebot-nachfassen', titel: 'fehlender pw_config-Wert bricht mit Meldung ab',
    ereignis: ereignis('versendet', angebot), einstellungen: { ...EINSTELLUNGEN, mail_betrieb: '' },
    fehler: 'pw_config: "mail_betrieb" fehlt',
  },

  // -- beleg-team-nachricht ----------------------------------------------------
  {
    workflow: 'beleg-team-nachricht', titel: 'angenommenes Angebot als Text',
    ereignis: ereignis('angelegt', { ...auftrag, nummer: null, vorgaenger: { id: 17, typ: 'angebot', nummer: 'AN-2026-0017' }, projekt }),
    einstellungen: EINSTELLUNGEN,
    pruefe: (e) => {
      const a = e.aufrufe[0];
      assert.equal(a.methode, 'POST');
      assert.equal(a.url, 'https://chat.example/hooks/abc');
      assert.match(a.body.text, /^Angebot AN-2026-0017 angenommen: neuer Auftrag für Muster GmbH \(Projekt 2026-003 Halle 3\) über 4\.200,00/);
    },
  },
  {
    workflow: 'beleg-team-nachricht', titel: 'versendete Rechnung als Teams-Karte',
    ereignis: ereignis('versendet'), einstellungen: { ...EINSTELLUNGEN, chat_format: 'teams' },
    pruefe: (e) => {
      const karte = e.aufrufe[0].body.attachments[0].content;
      assert.equal(karte.type, 'AdaptiveCard');
      assert.match(karte.body[0].text, /Rechnung RE-2026-0042 an Muster GmbH versendet: 1\.487,50\s€, fällig am 16\.11\.2026/);
      assert.equal(karte.actions[0].url, beleg().admin_url);
    },
  },
  {
    workflow: 'beleg-team-nachricht', titel: 'festgeschriebene Rechnung wird nicht gemeldet',
    ereignis: ereignis('festgeschrieben'), einstellungen: EINSTELLUNGEN,
    pruefe: keineAusgabe,
  },
  {
    workflow: 'beleg-team-nachricht', titel: 'unbekanntes chat_format bricht ab',
    ereignis: ereignis('versendet'), einstellungen: { ...EINSTELLUNGEN, chat_format: 'matrix' },
    fehler: 'chat_format "matrix" ist unbekannt',
  },

  // -- beleg-belegbuch ---------------------------------------------------------
  {
    workflow: 'beleg-belegbuch', titel: 'Zeile mit den Eigenschaften des Belegs',
    ereignis: ereignis('festgeschrieben', { projekt }),
    pruefe: (e) => {
      const z = e.zeilen[0];
      assert.equal(z.tabelle, 'pw_belegbuch');
      assert.equal(z.operation, 'insert');
      assert.deepEqual(
        { aktion: z.aktion, typ: z.typ, beleg_id: z.beleg_id, nummer: z.nummer, kunde: z.kunde, projekt: z.projekt, brutto: z.brutto },
        { aktion: 'festgeschrieben', typ: 'rechnung', beleg_id: 4711, nummer: 'RE-2026-0042', kunde: 'Muster GmbH', projekt: '2026-003 Halle 3', brutto: 1487.5 });
    },
  },
  {
    workflow: 'beleg-belegbuch', titel: 'Entwurf ohne Nummer und Fälligkeit',
    ereignis: ereignis('angelegt', { nummer: null, faellig_am: null, kunde: null }),
    pruefe: (e) => {
      assert.equal(e.zeilen[0].nummer, '');
      assert.equal(e.zeilen[0].faellig_am, '');
      assert.equal(e.zeilen[0].kunde, '');
    },
  },
  {
    workflow: 'beleg-belegbuch', titel: 'geändert wird nicht verbucht',
    ereignis: ereignis('geaendert'),
    pruefe: keineAusgabe,
  },
];
