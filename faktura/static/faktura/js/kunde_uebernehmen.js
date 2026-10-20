/* Füllt das Empfängerfeld bei Auswahl eines Kunden oder Projekts im
 * Belegformular, damit das Ergebnis vor dem Speichern sichtbar ist.
 *
 * Nur Darstellung; die Übernahme steht in services.stammdaten_uebernehmen()
 * und läuft beim Speichern für alle leeren Felder. Ohne JavaScript entsteht
 * derselbe Beleg.
 *
 * Ein Endpunkt für Kunde und Projekt; der Parameter ist der Feldname
 * ('kunde' oder 'projekt'), wie bei den Textvorlagen, damit ein weiteres
 * Feld ohne Codeänderung funktioniert.
 *
 * Kunde oder Projekt, nie beides: Eine Auswahl leert die andere, wie
 * Beleg.clean() und ein Constraint verlangen; das Skript zeigt das vor dem
 * Speichern.
 *
 * Zwei Regeln. Verworfen: eine Rückfrage bei jedem "Sichern und weiter
 * bearbeiten".
 *
 * 1. Gefüllt wird nur bei einer Auswahl durch den Benutzer. Bei
 *    Autocomplete-Feldern daher select2:select, weil change auch beim
 *    Laden ausgelöst wird, wenn Select2 den gespeicherten Kunden setzt. Bei
 *    einem gewöhnlichen <select> genügt change.
 * 2. Gefüllt wird nur ein Feld, das der Benutzer nicht selbst ausgefüllt
 *    hat, ohne Rückfrage. Für eine neue Übernahme das Feld leeren und neu
 *    wählen.
 *
 * Zu Regel 2: Beim Anlegen gilt ein unveränderter Default als leer
 * (Zahlungsziel 14, Land 'DE'), weil der Server beim Speichern den Wert
 * des Kunden einträgt (30 Tage, 'AT'). Verglichen wird mit defaultValue,
 * wie changed_data auf dem Server.
 *
 * In der Änderungsansicht nicht, deshalb setzt der Server data-neuanlage
 * nur beim Anlegen; dort hat jedes gespeicherte Feld seinen defaultValue,
 * und ein Kundenwechsel überschriebe die ganze Anschrift.
 */
'use strict';

django.jQuery(function ($) {
    /* Die zu füllenden Felder ergeben sich aus der Response.
     *
     * Der Server liefert die Felder, die er beim Speichern einträgt
     * (services.stammdatenwerte()), und das Skript übernimmt deren Namen;
     * ein neues Stammdatenfeld braucht keine Änderung hier. Verworfen: eine
     * eigene Liste im Skript. */

    /* Die URL steht als Attribut am Feld, weil jede Belegart eine eigene
     * hat und eine relative URL je nach Seite verschieden wäre (add/ oder
     * 5/change/). Gesetzt in BelegAdmin.formfield_for_foreignkey(). */
    const zuordnungsfelder = $('select[data-stammdaten-url]');
    if (!zuordnungsfelder.length) {
        return;
    }

    const neuanlage = zuordnungsfelder.filter('[data-neuanlage="1"]').length > 0;

    function istFrei(eingabefeld) {
        const feld = eingabefeld[0];
        if (String(feld.value).trim() === '') {
            return true;
        }
        return neuanlage && feld.value === feld.defaultValue;
    }

    /* Leert die jeweils andere Zuordnung, ohne erneutes Füllen, weil der
     * Handler bei leerem Wert endet und select2:select bei programmatisch
     * gesetztem Wert nicht ausgelöst wird. */
    function andereZuordnungLeeren(gewaehlt) {
        zuordnungsfelder.each(function () {
            if (this === gewaehlt) {
                return;
            }
            $(this).val(null).trigger('change');
        });
    }

    function uebernehmen(auswahlfeld) {
        const wert = auswahlfeld.value;
        if (!wert) {
            return;
        }
        andereZuordnungLeeren(auswahlfeld);

        /* Der Feldname ist der Parametername, siehe oben. */
        const adresse = auswahlfeld.dataset.stammdatenUrl
            + '?' + encodeURIComponent(auswahlfeld.name)
            + '=' + encodeURIComponent(wert);

        fetch(adresse, {credentials: 'same-origin'})
            .then(function (antwort) {
                if (!antwort.ok) {
                    throw new Error('Stammdaten nicht abrufbar');
                }
                return antwort.json();
            })
            .then(function (daten) {
                Object.keys(daten).forEach(function (name) {
                    const eingabefeld = $('#id_' + name);
                    if (!eingabefeld.length || !istFrei(eingabefeld)) {
                        return;
                    }
                    eingabefeld.val(daten[name]);
                    /* Kurz hervorheben, damit die automatische Änderung sichtbar
                     * ist. */
                    eingabefeld.css({
                        transition: 'background-color 1.2s',
                        backgroundColor: '#fff6c8',
                    });
                    window.setTimeout(function () {
                        eingabefeld.css('background-color', '');
                    }, 700);
                });
            })
            .catch(function (fehler) {
                /* Ausgabe in der Konsole, ohne Dialog, damit der Benutzer
                 * weiterarbeiten kann; das Speichern trägt die Werte nach.
                 * Regression: Ein leerer catch verbarg einen Fehler. */
                console.error('Stammdaten nicht uebernommen:', fehler);
            });
    }

    zuordnungsfelder.each(function () {
        /* Autocomplete-Felder haben die Klasse von Djangos Widget. Bei ihnen
         * wird change auch beim Laden ausgelöst (Regel 1 oben), bei einem
         * gewöhnlichen <select> nicht. */
        const ereignis = $(this).hasClass('admin-autocomplete')
            ? 'select2:select'
            : 'change';
        $(this).on(ereignis, function () {
            uebernehmen(this);
        });
    });
});
