/* Füllt eine Positionszeile, sobald dort eine Katalogposition gewählt wird.
 *
 * Nur Darstellung; BelegpositionForm.clean() übernimmt die Werte beim
 * Speichern mit dem Vorrang über changed_data. Im Browser wird bei der
 * Auswahl gefüllt; spätere Eingaben bleiben, weil das Speichern nur
 * unveränderte Felder füllt.
 *
 * Event Delegation am document, weil Zeilen über "Weitere Position
 * hinzufügen" erst nach dem Laden entstehen.
 *
 * Der Preis kommt mit Punkt ('10.00'), weil das Preisfeld ein
 * <input type="number"> mit technischem Format ist; das Komma zeigt der
 * Browser. Das Preisfeld des ModelForm ist nicht lokalisiert, '1234,56'
 * würde abgelehnt (geprüft).
 */
'use strict';

django.jQuery(function ($) {
    $(document).on('change', 'select[data-katalog-url]', function () {
        const auswahl = this;
        if (!auswahl.value) {
            return;
        }

        /* 'positionen-2-katalog' ergibt 'positionen-2', das Präfix der Zeile
         * mit der Auswahl. */
        const zeile = auswahl.name.replace(/-katalog$/, '');

        fetch(auswahl.dataset.katalogUrl + '?katalog='
                + encodeURIComponent(auswahl.value), {
            credentials: 'same-origin',
        })
            .then(function (antwort) {
                if (!antwort.ok) {
                    throw new Error('Katalog nicht abrufbar');
                }
                return antwort.json();
            })
            .then(function (daten) {
                ['bezeichnung', 'langtext', 'einheit', 'einzelpreis',
                    'steuersatz']
                    .forEach(function (name) {
                        const feld = document.getElementById(
                            'id_' + zeile + '-' + name
                        );
                        if (!feld || !(name in daten)) {
                            return;
                        }
                        feld.value = daten[name];
                        /* Ein gesetzter Wert löst kein Event aus; die Summe netto
                         * (zeilensumme.js) wartet auf 'input'. */
                        feld.dispatchEvent(
                            new Event('input', {bubbles: true})
                        );
                        $(feld).css({
                            transition: 'background-color 1.2s',
                            backgroundColor: '#fff6c8',
                        });
                        window.setTimeout(function () {
                            $(feld).css('background-color', '');
                        }, 700);
                    });
            })
            .catch(function (fehler) {
                /* Ausgabe in der Konsole (siehe kunde_uebernehmen.js). Das
                 * Speichern übernimmt die Werte auch ohne dieses Skript;
                 * nur das Formular wird nicht gefüllt. */
                console.error('Katalogposition nicht uebernommen:', fehler);
            });
    });
});
