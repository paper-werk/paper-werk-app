/* Setzt Felder ohne Bedeutung für die gewählte Zeilenart disabled und
 * blendet sie aus.
 *
 * Die Auswahl steht in der ersten Zeile jeder Position links neben der
 * Katalogsuche; die betroffenen Felder liefert sie als
 * ``data-felder-ohne-bedeutung`` aus Zeilenart.felder_ohne_bedeutung. Das
 * Skript bildet im Browser nach, was BelegpositionForm beim Speichern tut:
 * Ein disabled-Feld wird nicht gesendet und vom Server ignoriert.
 *
 * Nur Darstellung: Ohne Skript sind die Felder sichtbar, zählen aber nicht.
 * Festgeschriebene Positionen haben keine Auswahl; dort blendet der Filter
 * ``lesewert`` aus.
 */
'use strict';

(function () {
    const AUSWAHL = 'select[name$="-zeilenart"]';
    const VERBORGEN = 'pw-ohne-bedeutung';

    function angleichen(auswahl) {
        const gruppe = auswahl.closest('.form-group');
        if (!gruppe) {
            return;
        }
        const jeArt = JSON.parse(auswahl.dataset.felderOhneBedeutung || '{}');
        const weg = new Set(jeArt[auswahl.value || 'leistung'] || []);
        const alle = new Set(Object.values(jeArt).flat());

        alle.forEach(function (name) {
            const stellen = gruppe.querySelectorAll(
                ':scope > tr.form-row > td.field-' + name + ', '
                + ':scope > tr.form-row-zusatzzeile .zusatzzeile-feld.field-'
                + name
            );
            stellen.forEach(function (stelle) {
                stelle.classList.toggle(VERBORGEN, weg.has(name));
                stelle.querySelectorAll('input, select, textarea')
                    .forEach(function (feld) {
                        feld.disabled = weg.has(name);
                    });
            });
        });
    }

    function alleAngleichen() {
        document.querySelectorAll(AUSWAHL).forEach(angleichen);
    }

    document.addEventListener('change', function (ereignis) {
        if (ereignis.target.matches(AUSWAHL)) {
            angleichen(ereignis.target);
        }
    });
    document.addEventListener('formset:added', alleAngleichen);
    document.addEventListener('DOMContentLoaded', alleAngleichen);
})();
