/* Vorschläge für "Zuschlag auf": Titel und Leistungen in der Maske, auch
 * nicht gespeicherte.
 *
 * Eine ``datalist``, damit freie Eingabe möglich bleibt (ein Präfix ohne
 * eigenen Titel) und ein Wert bei geänderter Nummer nicht verschwindet.
 * Verworfen: ``select``. Aufgebaut bei Fokus, damit sie den aktuellen
 * Zeilen entspricht. Den Bezug prüft der Server (BelegpositionFormSet,
 * services.ohne_bezug).
 */
'use strict';

(function () {
    const FELD = 'input[name$="-zuschlag_auf"]';
    const LISTE = 'pw-zuschlag-ziele';
    const ZIELE = {titel: 'Titel', leistung: ''};

    function wert(gruppe, name) {
        const feld = gruppe.querySelector('[name$="-' + name + '"]');
        return feld ? feld.value.trim() : '';
    }

    function geloescht(gruppe) {
        const haken = gruppe.querySelector('input[name$="-DELETE"]');
        return Boolean(haken && haken.checked);
    }

    function ziele(ausser) {
        const ergebnis = [];
        document.querySelectorAll('.form-group').forEach(function (gruppe) {
            // Die Vorlage für angefügte Zeilen ist auch eine Gruppe.
            if (gruppe === ausser || geloescht(gruppe)
                    || gruppe.classList.contains('empty-form')) {
                return;
            }
            const art = wert(gruppe, 'zeilenart') || 'leistung';
            const nummer = wert(gruppe, 'position');
            if (!(art in ZIELE) || !nummer) {
                return;
            }
            const text = [ZIELE[art], wert(gruppe, 'bezeichnung')]
                .filter(Boolean).join(' ');
            ergebnis.push({nummer: nummer, text: text});
        });
        return ergebnis;
    }

    function liste() {
        let element = document.getElementById(LISTE);
        if (!element) {
            element = document.createElement('datalist');
            element.id = LISTE;
            document.body.appendChild(element);
        }
        return element;
    }

    document.addEventListener('focusin', function (ereignis) {
        const feld = ereignis.target;
        if (!feld.matches(FELD)) {
            return;
        }
        const element = liste();
        element.replaceChildren(...ziele(feld.closest('.form-group'))
            .map(function (ziel) {
                const option = document.createElement('option');
                option.value = ziel.nummer;
                option.label = ziel.text;
                return option;
            }));
        feld.setAttribute('list', LISTE);
        feld.setAttribute('autocomplete', 'off');
    });
})();
