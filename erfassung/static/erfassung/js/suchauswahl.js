/* Auswahlfelder der Erfassung mit Suche (Select2).
 *
 * Betrifft jedes <select data-suche>, markiert von
 * FormularMixin.MIT_SUCHE. Gesucht wird in den Optionen im HTML, ohne
 * Autocomplete-Endpunkt, damit Querysets und data-art/data-projekt an
 * einer Stelle bleiben.
 *
 * Zwei Anpassungen an Select2:
 *
 *   1. Optionen mit ``hidden`` erscheinen nicht in der Trefferliste.
 *      erfassungsauswahl.js blendet so die Positionen anderer Projekte
 *      aus; Select2 würde sie sonst nur ausgegraut zeigen.
 *   2. Select2 meldet die Auswahl mit jQuery.trigger('change'), das keine
 *      nativen Listener erreicht. Alpine (x-model der conditional_fields)
 *      und erfassungsauswahl.js hören nativ; daher wird ein natives
 *      'change' nachgereicht. Native Ereignisse haben ``originalEvent``
 *      und werden nicht erneut weitergegeben.
 *
 * Tippen auf dem geschlossenen Feld öffnet die Suche mit dem Zeichen,
 * damit nach Tab sofort gesucht werden kann.
 */
'use strict';

django.jQuery(function ($) {
    const standard = $.fn.select2.defaults.defaults.matcher;

    function passend(angaben, eintrag) {
        if (eintrag.element && eintrag.element.hidden) {
            return null;
        }
        return standard(angaben, eintrag);
    }

    $('select[data-suche]').each(function () {
        const auswahl = this;
        if ($(auswahl).hasClass('select2-hidden-accessible')) {
            return;
        }
        $(auswahl).select2({
            allowClear: !auswahl.required,
            language: 'de',
            matcher: passend,
            placeholder: {id: '', text: '---------'},
            theme: 'admin-autocomplete',
            width: '100%',
        });

        $(auswahl).on('change', function (ereignis) {
            if (!ereignis.originalEvent) {
                auswahl.dispatchEvent(new Event('change', {bubbles: true}));
            }
        });

        $(auswahl).next('.select2').find('.select2-selection')
            .on('keydown', function (ereignis) {
                const taste = ereignis.key;
                if (!taste || taste.length !== 1 || taste === ' '
                        || ereignis.ctrlKey || ereignis.altKey
                        || ereignis.metaKey) {
                    return;
                }
                ereignis.preventDefault();
                /* Weitere Tasten können eintreffen, bevor der Fokus im
                 * Suchfeld liegt; sie hängen an, statt zu überschreiben
                 * (tests/test_browser_erfassung.py,
                 * test_schnell_getippte_zeichen_gehen_nicht_verloren). */
                const offen = $(auswahl).select2('isOpen');
                if (!offen) {
                    $(auswahl).select2('open');
                }
                const suche = document.querySelector(
                    '.select2-container--open .select2-search__field');
                if (suche) {
                    suche.value = offen ? suche.value + taste : taste;
                    suche.focus();
                    suche.dispatchEvent(new Event('input', {bubbles: true}));
                }
            });
    });
});
