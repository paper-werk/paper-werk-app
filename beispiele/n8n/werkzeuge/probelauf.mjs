// Probelauf der Workflows ohne n8n: Code-Knoten und n8n-Ausdrücke laufen
// wirklich, HTTP-Aufrufe, Mail und Data Tables sind ersetzt.
//
// Jedes Szenario in szenarien.mjs nennt Workflow, Startknoten, Ereignis und
// die Antworten der ersetzten Knoten. Der Probelauf folgt der Kette über den
// ersten Ausgang, wie n8n bei linearen Workflows, und hält an, wenn ein
// Knoten keine Items liefert. Geprüft wird, was hinausgeht: Mails,
// HTTP-Aufrufe und geschriebene Zeilen.
//
// Aufruf aus der Wurzel des Repos:  node werkzeuge/probelauf.mjs

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { szenarien } from './szenarien.mjs';

const WURZEL = join(dirname(fileURLToPath(import.meta.url)), '..');
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

function zugriff(ausgaben) {
  return (name) => {
    const items = ausgaben[name];
    if (!items) throw new Error(`Knoten "${name}" ist im Lauf nicht ausgeführt worden.`);
    return { first: () => items[0], last: () => items.at(-1), all: () => items, item: items[0] };
  };
}

// "={{ a }}/x/{{ b }}" auswerten; ein einzelner Ausdruck liefert den Wert selbst.
function ausdruck(wert, ausgaben, json) {
  if (typeof wert !== 'string' || !wert.startsWith('=')) return wert;
  const text = wert.slice(1);
  const rechne = (code) => new Function('$', '$json', `return (${code});`)(zugriff(ausgaben), json);
  const allein = text.match(/^\{\{([\s\S]*)\}\}$/);
  if (allein && !allein[1].includes('}}')) return rechne(allein[1]);
  return text.replace(/\{\{([\s\S]*?)\}\}/g, (_, code) => String(rechne(code)));
}

async function lauf(szenario) {
  const wf = JSON.parse(readFileSync(join(WURZEL, 'workflows', `${szenario.workflow}.json`), 'utf8'));
  const knoten = Object.fromEntries(wf.nodes.map((k) => [k.name, k]));
  const ausgaben = {};
  const ergebnis = { mails: [], aufrufe: [], zeilen: [], letzter: null };

  const start = szenario.start ?? 'Webhook';
  ausgaben[start] = [{ json: start === 'Webhook' ? { body: szenario.ereignis } : {} }];
  let name = start;

  while (true) {
    const weiter = wf.connections[name]?.main?.[0]?.[0]?.node;
    if (!weiter) break;
    const k = knoten[weiter];
    const eingabe = ausgaben[name];
    const json = eingabe[0]?.json ?? {};
    const p = k.parameters;
    let aus;

    switch (k.type) {
      case 'n8n-nodes-base.executeWorkflow':
        aus = [{ json: szenario.einstellungen ?? {} }];
        break;
      case 'n8n-nodes-base.code': {
        const helpers = {
          prepareBinaryData: async (puffer, fileName, mimeType) =>
            ({ data: Buffer.from(puffer).toString('base64'), fileName, mimeType }),
        };
        const $input = { first: () => eingabe[0], all: () => eingabe, item: eingabe[0] };
        const fn = new AsyncFunction('$', '$input', p.jsCode);
        aus = await fn.call({ helpers }, zugriff(ausgaben), $input);
        break;
      }
      case 'n8n-nodes-base.wait':
        ergebnis.wartezeit = ausdruck(p.amount, ausgaben, json);
        aus = eingabe;
        break;
      case 'n8n-nodes-base.httpRequest': {
        const aufruf = { knoten: k.name, methode: p.method ?? 'GET', url: ausdruck(p.url, ausgaben, json) };
        if (p.jsonBody) aufruf.body = ausdruck(p.jsonBody, ausgaben, json);
        if (p.contentType === 'binaryData') aufruf.binaer = eingabe[0].binary?.[p.inputDataFieldName];
        ergebnis.aufrufe.push(aufruf);
        const antwort = szenario.http?.[k.name];
        aus = [{ json: typeof antwort === 'function' ? antwort(aufruf) : (antwort ?? {}) }];
        if (p.options?.response?.response?.responseFormat === 'file') {
          aus[0].binary = { [p.options.response.response.outputPropertyName]: { data: 'UERG', fileName: 'beleg.pdf' } };
        }
        break;
      }
      case 'n8n-nodes-base.emailSend': {
        const mail = Object.fromEntries(['fromEmail', 'toEmail', 'subject', 'html']
          .map((f) => [f, ausdruck(p[f], ausgaben, json)]));
        mail.anhang = p.options?.attachments ? eingabe[0].binary?.[p.options.attachments] : undefined;
        ergebnis.mails.push(mail);
        aus = eingabe;
        break;
      }
      case 'n8n-nodes-base.dataTable':
        if (p.resource === 'table') aus = [{ json: { name: p.tableName } }];
        else if (p.operation === 'get') {
          const zeilen = szenario.tabellen?.[p.dataTableId.value] ?? [];
          aus = zeilen.map((z) => ({ json: z }));
          if (!aus.length && k.alwaysOutputData) aus = [{ json: {} }];
        } else {
          ergebnis.zeilen.push(...eingabe.map((i) => ({ tabelle: p.dataTableId.value, operation: p.operation, ...i.json })));
          aus = eingabe;
        }
        break;
      default:
        throw new Error(`Knotentyp ${k.type} (${k.name}) wird im Probelauf nicht nachgebildet.`);
    }

    ausgaben[k.name] = aus;
    ergebnis.letzter = k.name;
    if (!aus.length) break;
    name = k.name;
  }
  return ergebnis;
}

let fehler = 0;
for (const szenario of szenarien) {
  let meldung = null;
  try {
    const ergebnis = await lauf(szenario);
    if (szenario.fehler) meldung = `erwartet Fehler "${szenario.fehler}", lief durch`;
    else szenario.pruefe(ergebnis);
  } catch (e) {
    if (!(szenario.fehler && String(e.message).includes(szenario.fehler))) meldung = e.stack ?? String(e);
  }
  if (meldung) {
    fehler++;
    console.log(`FEHLER  ${szenario.workflow}: ${szenario.titel}\n        ${meldung}`);
  } else {
    console.log(`ok      ${szenario.workflow}: ${szenario.titel}`);
  }
}
console.log(`${szenarien.length} Szenarien, ${fehler} Fehler.`);
process.exit(fehler ? 1 : 0);
