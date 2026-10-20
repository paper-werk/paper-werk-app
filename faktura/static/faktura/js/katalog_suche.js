/* Macht die Katalogauswahl über der Positionszeile durchsuchbar.
 *
 * Das HTML enthält nur die gewählte Position (KatalogsucheWidget); die
 * Treffer liefert der Endpunkt in data-katalog-suche
 * (KatalogpositionAdmin.suche), dieselbe Suche wie in der Katalogliste
 * (Nummer, Bezeichnung, Langtext), mit Pagination.
 *
 * Die Übernahme nach der Auswahl steht in katalog_uebernehmen.js; Select2
 * löst ein 'change' am <select> aus.
 *
 * Neue Zeilen: Unfold löst 'formset:added' an der Positionszeile aus, die
 * Katalogsuche steht in der Zeile darüber; daher Suche im ganzen tbody.
 * Die Vorlage für neue Zeilen (__prefix__) wird nicht initialisiert, weil
 * ihre Kopie ein nicht funktionierendes Select2 enthielte.
 */
'use strict';

django.jQuery(function ($) {
    function einrichten(bereich) {
        $(bereich).find('select[data-katalog-suche]').each(function () {
            if (this.id.indexOf('__prefix__') !== -1
                    || $(this).hasClass('select2-hidden-accessible')) {
                return;
            }
            $(this).select2({
                ajax: {
                    url: this.dataset.katalogSuche,
                    dataType: 'json',
                    delay: 250,
                    data: function (angaben) {
                        return {term: angaben.term, page: angaben.page};
                    },
                },
                allowClear: true,
                language: 'de',
                placeholder: 'Leistung suchen: Nummer, Bezeichnung oder '
                    + 'Stichwort aus dem Langtext',
                theme: 'admin-autocomplete',
                width: '100%',
            });
        });
    }

    einrichten(document);

    document.addEventListener('formset:added', function (ereignis) {
        einrichten($(ereignis.target).closest('tbody.form-group'));
    });
});
