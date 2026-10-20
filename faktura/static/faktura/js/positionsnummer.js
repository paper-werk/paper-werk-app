/* Setzt die Nummer einer im Browser angefügten Position.
 *
 * Beim Laden vorhandene Zeilen belegt der Server vor
 * (BelegpositionFormSet). Eine Zeile aus "Weitere Position hinzufügen"
 * entsteht aus einer leeren Vorlage und hätte ohne dieses Skript bis zum
 * Speichern keine Nummer.
 *
 * Dieselbe Regel wie naechste_nummern() in faktura/positionsnummer.py: Bei
 * ganzen Zahlen nach der größten in Zehnerschritten, solange alle
 * Vielfache von 10 sind, sonst in Einerschritten. Sonst ("01.01.0010")
 * wird die letzte Ziffernfolge der höchsten Nummer in derselben Breite
 * inkrementiert, um 10, wenn sie auf 0 endet, sonst um 1.
 *
 * Nur Darstellung: Eine Zeile nur mit dieser Nummer gilt beim Speichern als
 * leer (BelegpositionForm.has_changed).
 */
'use strict';

(function () {
    const STELLEN = 10;

    function schluessel(nummer) {
        return nummer.trim().toLowerCase().replace(/\d+/g, function (ziffern) {
            return ziffern.padStart(STELLEN, '0');
        });
    }

    function naechste(vorige) {
        const text = vorige.trim();
        const treffer = /(\d+)(\D*)$/.exec(text);
        if (!treffer) {
            return '';
        }
        const ziffern = treffer[1];
        const schritt = ziffern.endsWith('0') ? 10 : 1;
        const neu = String(parseInt(ziffern, 10) + schritt)
            .padStart(ziffern.length, '0');
        return text.slice(0, treffer.index) + neu + treffer[2];
    }

    function naechsteNummer(vergeben) {
        if (vergeben.every(function (n) { return /^\d+$/.test(n); })) {
            const zahlen = vergeben.map(function (n) { return parseInt(n, 10); });
            const schritt = zahlen.every(function (z) {
                return z % 10 === 0;
            }) ? 10 : 1;
            return String(Math.max.apply(null, [0].concat(zahlen)) + schritt);
        }
        const belegt = new Set(vergeben.map(schluessel));
        let letzte = '0';
        vergeben.forEach(function (n) {
            if (naechste(n) && schluessel(n) > schluessel(letzte)) {
                letzte = n;
            }
        });
        let nummer = naechste(letzte);
        while (belegt.has(schluessel(nummer))) {
            nummer = naechste(nummer);
        }
        return nummer;
    }

    document.addEventListener('formset:added', function (ereignis) {
        const prefix = ereignis.detail && ereignis.detail.formsetName;
        const feld = ereignis.target.querySelector('[data-positionsnummer]');
        if (!prefix || !feld || feld.value) {
            return;
        }

        const vergeben = [];
        document.querySelectorAll(
            '[data-positionsnummer][name^="' + prefix + '-"]'
        ).forEach(function (anderes) {
            if (anderes !== feld && anderes.value.trim()) {
                vergeben.push(anderes.value.trim());
            }
        });

        feld.value = naechsteNummer(vergeben);
    });
})();
