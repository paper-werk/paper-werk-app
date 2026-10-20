/* Textvorlagen: fügt den im Menü gewählten Text in das Feld ein.
 *
 * Die Bausteine stehen mit Vorschau im Formular. Verworfen: ein eigenes
 * Fenster nach dem Muster von Djangos Fremdschlüssel-Lookups (window.name,
 * Callback im öffnenden Dokument), für wenige kurze Stammdaten zu
 * aufwendig.
 *
 * Der Text wird kopiert; die Auswahl wird nicht an den Server übertragen,
 * der Feldinhalt ist beim Speichern eine gewöhnliche Eingabe.
 *
 * Ohne JavaScript gibt es keine Auswahl; das Textfeld bleibt bedienbar.
 */
'use strict';

/* Hebt das Feld kurz hervor, wie bei der Übernahme der Stammdaten,
 * damit die Änderung sichtbar ist. */
function hervorheben(feld) {
    feld.style.transition = 'background-color 1.2s';
    feld.style.backgroundColor = '#fff6c8';
    window.setTimeout(function () {
        feld.style.backgroundColor = '';
    }, 700);
}

/* Event Delegation am document, weil das Menü per x-teleport am body
 * hängt und erst entsteht, wenn Alpine es rendert. */
document.addEventListener('click', function (ereignis) {
    const eintrag = ereignis.target.closest('[data-vorlage]');
    if (!eintrag) {
        return;
    }
    ereignis.preventDefault();

    const ziel = document.getElementById(eintrag.dataset.ziel);
    if (!ziel) {
        /* Ein Eintrag ohne Zielfeld ist ein Fehler zwischen Template und
         * Skript und wird gemeldet. */
        console.error(
            'Textvorlage ohne Zielfeld: ' + eintrag.dataset.ziel
        );
        return;
    }

    const text = eintrag.dataset.text;

    /* Bei vorhandenem Text anhängen, nicht ersetzen, damit ein
     * versehentlicher Klick keinen eingegebenen Text löscht. Damit lassen
     * sich auch mehrere Bausteine nacheinander einfügen. */
    const vorhanden = ziel.value.trim();
    ziel.value = vorhanden ? vorhanden + '\n\n' + text : text;

    /* Ein per JavaScript gesetzter Wert löst kein Event aus; das
     * 'input'-Event informiert Listener am Formular, etwa die Warnung vor
     * nicht gespeicherten Änderungen. */
    ziel.dispatchEvent(new Event('change', {bubbles: true}));

    /* Cursor ans Ende, damit direkt weitergeschrieben werden kann. */
    ziel.focus();
    ziel.setSelectionRange(ziel.value.length, ziel.value.length);

    hervorheben(ziel);
});
