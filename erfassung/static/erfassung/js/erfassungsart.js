/* Erfassungsart der gewählten Leistung.
 *
 * Antwort: 'zeit', 'menge', 'pauschale' oder '', solange nichts gewählt
 * ist. Die Art steht als data-art an jeder Option, gesetzt von
 * LeistungsAuswahl im Admin.
 *
 * Verwendet von ``conditional_fields`` am ErfassungszeileAdmin, dessen
 * Ausdrücke Alpine zum Ein- und Ausblenden der Felder auswertet.
 *
 * Über data-art, weil Alpine nur die Werte der Felder kennt (beim
 * Leistungsfeld den Primärschlüssel). Verworfen: die Schlüssel aller
 * Zeitleistungen im Ausdruck, eine Liste, die mit dem Katalog veraltet.
 *
 * Nur Darstellung; die Validierung erfolgt in Erfassungszeile.clean().
 */
/* Zwei Auswahllisten: Auftragsposition (Regelfall) und Katalogleistung
 * (Ausnahme). Genau eine ist gefüllt (Erfassungszeile._pruefe_grundlage);
 * geprüft werden beide, weil der Benutzer beim Ausfüllen wechseln kann.
 *
 * Eine Auftragsposition ohne Katalogbezug hat keine Art; dann gilt
 * 'menge', wie in Erfassungszeile.leistungsart. Die Regel steht hier ein
 * zweites Mal, damit die Maske ohne Request auskommt; weichen beide ab,
 * zeigt die Maske das falsche Feld, und clean() lehnt ab.
 */
'use strict';

window.erfassungsart = function () {
    for (const name of ['id_auftragsposition', 'id_leistung']) {
        const auswahl = document.getElementById(name);
        const gewaehlt = auswahl && auswahl.value && auswahl.selectedOptions[0];
        if (gewaehlt) {
            return gewaehlt.dataset.art || 'menge';
        }
    }
    return '';
};
