/* Hält die Zusatzzeilen einer Position an ihrer Zeilennummer.
 *
 * Katalogsuche und Langtext stehen in eigenen Tabellenzeilen über und
 * unter der Positionszeile (templates/unfold/helpers/edit_inline/
 * tabular_group.html).
 *
 * Beim Löschen einer nicht gespeicherten Zeile nummeriert Unfold die Felder
 * um ('positionen-2-menge' wird 'positionen-1-menge'), weil Django lückenlose
 * Indizes von 0 bis TOTAL_FORMS-1 verlangt, aber nur innerhalb von
 * '.form-row' (app.js, deleteInlineTemplateHandler). Die Zusatzzeilen sind
 * Geschwister davon und behielten den alten Index; Langtext oder
 * Katalogauswahl gehörten beim Speichern ohne Fehlermeldung zu einer
 * anderen Position.
 *
 * Umnummeriert wird über die Attribute der Felder, nicht über innerHTML,
 * weil eingegebene Werte in der Property 'value' stehen und innerHTML sie
 * verwürfe.
 *
 * Beim Hinzufügen einer Zeile nichts zu tun, weil Unfold
 * '<prefix>-__prefix__' im ganzen tbody ersetzt.
 */
'use strict';

(function () {
    /* Unfold löst das Event nach dem eigenen Umnummerieren aus; danach
     * übernehmen die Zusatzzeilen den Index der Positionszeile. */
    document.addEventListener('formset:removed', function (ereignis) {
        const prefix = ereignis.detail && ereignis.detail.formsetName;
        if (prefix) {
            nummernAngleichen(prefix);
        }
    });

    function nummernAngleichen(prefix) {
        const muster = new RegExp(prefix + '-\\d+-');

        document.querySelectorAll('.form-group').forEach(function (gruppe) {
            const zusatzzeilen = gruppe.querySelectorAll(
                ':scope > .form-row-zusatzzeile'
            );
            if (!zusatzzeilen.length) {
                return;
            }

            const vorbild = gruppe.querySelector(
                ':scope > .form-row [name^="' + prefix + '-"]'
            );
            if (!vorbild) {
                return;
            }

            const treffer = vorbild.name.match(muster);
            if (!treffer) {
                return;
            }

            zusatzzeilen.forEach(function (zeile) {
                zeile.querySelectorAll('[name], [id], [for]').forEach(
                    function (feld) {
                        ['name', 'id', 'htmlFor'].forEach(
                            function (eigenschaft) {
                                const wert = feld[eigenschaft];
                                if (wert) {
                                    feld[eigenschaft] = wert.replace(
                                        muster, treffer[0]
                                    );
                                }
                            }
                        );
                    }
                );
            });
        });
    }
})();
