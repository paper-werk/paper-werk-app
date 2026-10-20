/* Die Auswahl der Auftragsposition hängt am Projekt.
 *
 * Zwei Regeln:
 *
 *   1. Erst das Projekt, dann die Position. Ohne Projekt ist die
 *      Positionsliste leer.
 *   2. Mit gewählter Position keine Katalogleistung. Die Maske blendet das
 *      Feld aus (conditional_fields); das Skript leert es zusätzlich, damit
 *      kein unsichtbarer Wert bleibt.
 *
 * Gefiltert im Browser über data-projekt an jeder Option (gesetzt von
 * AuftragspositionsWidget, wie data-art). Verworfen: ein JSON-Endpunkt für
 * die Positionen eines Projekts, mit Latenz, Fehlerbehandlung und einer
 * zweiten Implementierung der Bedingung "festgeschriebener Auftrag,
 * laufendes Projekt" (wie bei LeistungsAuswahl).
 *
 * Nur Darstellung; Erfassungszeile._pruefe_grundlage lehnt eine Position
 * aus einem anderen Projekt ab.
 */
'use strict';

(function () {
    function felder() {
        return {
            projekt: document.getElementById('id_projekt'),
            position: document.getElementById('id_auftragsposition'),
            leistung: document.getElementById('id_leistung'),
        };
    }

    /* Zeigt nur die Positionen des gewählten Projekts.
     *
     * ``hidden`` und ``disabled``: hidden entfernt die Option aus der
     * Liste, disabled aus der Tastaturbedienung (Pfeiltasten).
     */
    function positionenFiltern(zuruecksetzen) {
        const { projekt, position } = felder();
        if (!projekt || !position) {
            return;
        }
        const vorhaben = projekt.value;

        for (const eintrag of position.options) {
            if (!eintrag.value) {
                continue;   // der leere Eintrag bleibt immer wählbar
            }
            const passt = Boolean(vorhaben) && eintrag.dataset.projekt === vorhaben;
            eintrag.hidden = !passt;
            eintrag.disabled = !passt;
        }

        // Beim Wechsel des Projekts eine nicht mehr passende Position
        // zurücksetzen, damit sie nicht gespeichert und erst danach
        // abgelehnt wird.
        const gewaehlt = position.selectedOptions[0];
        if (zuruecksetzen && gewaehlt && gewaehlt.value && gewaehlt.disabled) {
            position.value = '';
            position.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }

    function katalogLeeren() {
        const { position, leistung } = felder();
        if (position && position.value && leistung && leistung.value) {
            leistung.value = '';
            leistung.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        const { projekt, position } = felder();
        if (!position) {
            return;     // andere Maske, nichts zu tun
        }
        // Beim Laden nicht zurücksetzen, weil die Position einer
        // gespeicherten Zeile gültig ist.
        positionenFiltern(false);
        if (projekt) {
            projekt.addEventListener('change', () => positionenFiltern(true));
        }
        position.addEventListener('change', katalogLeeren);
    });
})();
