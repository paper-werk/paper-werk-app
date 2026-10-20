/* Die dreistufige Auswahl der Seite "Erbrachte Leistungen hinzufügen".
 *
 * Checkboxen auf vier Ebenen: Auftrag, Auftragsposition, Person und
 * Erfassungszeile. Die Ebenen bleiben konsistent, damit erkennbar ist, was
 * übernommen wird.
 *
 * Zwei Regeln:
 *
 *   nach unten:  Eine Ebene auswählen wählt alle darunter.
 *   nach oben:   Eine Ebene ist ausgewählt, wenn alle darunter es sind,
 *                teilweise (``indeterminate``) bei einigen, sonst leer.
 *
 * Gesendet werden nur die Zeilen, weil nur sie ein ``name`` haben; die
 * Ebenen darüber sind reine Bedienelemente, und der Server muss sie nicht
 * prüfen.
 *
 * Nur Darstellung; was übernommen werden darf, prüft
 * ``in_rechnung_uebernehmen``, und die Maske beschränkt die IDs auf das
 * Projekt des Belegs.
 */
'use strict';

(function () {
    /* Checkboxen unter einer Checkbox: alle im nächstgelegenen Block. Über
     * die Verschachtelung im HTML, damit eine weitere Ebene keinen Code
     * braucht. Verworfen: Zuordnung über IDs. */
    function bereich(kasten) {
        const label = kasten.closest('label');
        return label ? label.parentElement : null;
    }

    function zeilenUnter(kasten) {
        const raum = bereich(kasten);
        if (!raum) {
            return [];
        }
        return Array.from(raum.querySelectorAll('input[data-ebene="zeile"]'));
    }

    function nachObenNachziehen(formular) {
        const ebenen = ['person', 'position', 'auftrag'];
        for (const ebene of ebenen) {
            for (const kasten of formular.querySelectorAll(`input[data-ebene="${ebene}"]`)) {
                const zeilen = zeilenUnter(kasten);
                const gesetzt = zeilen.filter((z) => z.checked).length;
                kasten.checked = zeilen.length > 0 && gesetzt === zeilen.length;
                kasten.indeterminate = gesetzt > 0 && gesetzt < zeilen.length;
            }
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        const formular = document.querySelector('form[data-leistungsauswahl]');
        if (!formular) {
            return;
        }

        formular.addEventListener('change', function (ereignis) {
            const kasten = ereignis.target;
            if (!kasten.dataset || !kasten.dataset.ebene) {
                return;
            }
            if (kasten.dataset.ebene !== 'zeile') {
                for (const zeile of zeilenUnter(kasten)) {
                    zeile.checked = kasten.checked;
                }
            }
            nachObenNachziehen(formular);
        });

        nachObenNachziehen(formular);
    });
})();
