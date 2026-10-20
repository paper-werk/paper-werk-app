/* Die Auftragsposition einer Fremdleistung hängt am Projekt der Zeile.
 *
 * Wie in der Erfassung (erfassungsauswahl.js): Jede Option hat ihr Projekt
 * als data-projekt (AuftragspositionsWidget), angezeigt werden nur die zum
 * Projekt der Zeile. Anders als dort hat die Eingangsrechnung viele Zeilen
 * mit eigenem Projekt, und "Weitere hinzufügen" fügt neue an.
 *
 * Das Projektfeld ist ein Select2-Autocomplete, das Änderungen über jQuery
 * meldet, nicht als natives Event. Deshalb ein delegierter Handler über
 * django.jQuery, falls vorhanden, der beide Arten erfasst.
 *
 * Nur Darstellung; Fremdleistung.clean() lehnt eine Position aus einem
 * anderen Projekt ab.
 */
'use strict';

(function () {
    /* Feldname in der Eingangsrechnung "positionen-0-projekt", in der
     * Einzelmaske einer Fremdleistung "projekt". Regression: Nur der erste
     * wurde behandelt, und die Einzelmaske zeigte alle Aufträge. */
    const PROJEKT = /(^|-)projekt$/;
    const ALLE_PROJEKTFELDER = 'select[name="projekt"], select[name$="-projekt"]';

    function positionsfeldZu(projektfeld) {
        const name = projektfeld.name.replace(/projekt$/, 'auftragsposition');
        return document.querySelector(`select[name="${name}"]`);
    }

    /* hidden und disabled wie in erfassungsauswahl.js: hidden entfernt die
     * Option aus der Liste, disabled aus der Tastaturbedienung. */
    function filtern(projektfeld, zuruecksetzen) {
        const position = positionsfeldZu(projektfeld);
        if (!position) {
            return;
        }
        const vorhaben = projektfeld.value;
        for (const eintrag of position.options) {
            if (!eintrag.value) {
                continue;   // der leere Eintrag bleibt immer wählbar
            }
            const passt = Boolean(vorhaben) && eintrag.dataset.projekt === vorhaben;
            eintrag.hidden = !passt;
            eintrag.disabled = !passt;
        }
        const gewaehlt = position.selectedOptions[0];
        if (zuruecksetzen && gewaehlt && gewaehlt.value && gewaehlt.disabled) {
            position.value = '';
        }
    }

    function alleFiltern() {
        document.querySelectorAll(ALLE_PROJEKTFELDER).forEach(
            (feld) => filtern(feld, false));
    }

    function beiWechsel(ereignis) {
        const feld = ereignis.target;
        if (feld && feld.name && PROJEKT.test(feld.name)) {
            filtern(feld, true);
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        // Beim Laden nicht zurücksetzen, weil gespeicherte Zeilen gültig
        // sind.
        alleFiltern();

        if (window.django && window.django.jQuery) {
            window.django.jQuery(document).on('change', 'select', beiWechsel);
            // Eine neue Zeile ("Weitere hinzufügen") hat noch kein Projekt;
            // ihre Positionsliste bleibt leer, bis eines gewählt ist.
            window.django.jQuery(document).on('formset:added', alleFiltern);
        } else {
            document.addEventListener('change', beiWechsel);
        }
    });
})();
