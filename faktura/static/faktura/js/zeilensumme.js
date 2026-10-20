/* Berechnet die Spalte "Summe netto" einer Positionszeile bei Eingabe.
 *
 * Der Server liefert die Summe nur für gespeicherte Positionen
 * (BelegpositionInline.zeilensumme).
 *
 * Nur Darstellung; maßgeblich ist services.positionssumme(). Dieselbe
 * Regel: Menge mal Einzelpreis, kaufmännisch auf den Cent, die Hälfte von
 * der Null weg (core/rechnen.py, 0,75 x 89,50 = 67,13). Mit BigInt, weil
 * 0,75 * 89,5 in Gleitkomma 67,12499999... ergibt und einen Cent abwiche.
 *
 * Die Werte stehen im technischen Format ('1.000', '89.50'), weil die
 * Felder <input type="number"> sind (siehe katalog_uebernehmen.js).
 */
'use strict';

(function () {
    /* '89.50' -> {ziffern: 8950n, stellen: 2}; null, wenn keine Zahl. */
    function zerlegen(text) {
        const treffer = /^\s*(-?)(\d*)(?:\.(\d*))?\s*$/.exec(text || '');
        if (!treffer || (treffer[2] + (treffer[3] || '')) === '') {
            return null;
        }
        const nachkomma = treffer[3] || '';
        let ziffern = BigInt((treffer[2] || '0') + nachkomma);
        if (treffer[1]) {
            ziffern = -ziffern;
        }
        return {ziffern: ziffern, stellen: nachkomma.length};
    }

    /* Menge mal Preis in Cent, kaufmännisch gerundet. */
    function summeInCent(menge, preis) {
        const produkt = menge.ziffern * preis.ziffern;
        const stellen = menge.stellen + preis.stellen;
        if (stellen <= 2) {
            return produkt * 10n ** BigInt(2 - stellen);
        }
        const teiler = 10n ** BigInt(stellen - 2);
        const betrag = produkt < 0n ? -produkt : produkt;
        // Die Hälfte aufrunden; am Betrag, dann das Vorzeichen zurück.
        const gerundet = (betrag * 2n + teiler) / (teiler * 2n);
        return produkt < 0n ? -gerundet : gerundet;
    }

    /* 1481472n -> '14.814,72 EUR'; wie formate.geld_mit_waehrung(). */
    function alsGeld(cent) {
        const negativ = cent < 0n;
        const text = (negativ ? -cent : cent).toString().padStart(3, '0');
        const euro = text.slice(0, -2).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
        return (negativ ? '-' : '') + euro + ',' + text.slice(-2) + ' EUR';
    }

    function zeileRechnen(zeile) {
        const ausgabe = zeile.querySelector('td.field-zeilensumme .readonly');
        const menge = zeile.querySelector('input[name$="-menge"]');
        const preis = zeile.querySelector('input[name$="-einzelpreis"]');
        if (!ausgabe || !menge || !preis) {
            return;
        }
        const m = zerlegen(menge.value);
        const p = zerlegen(preis.value);
        ausgabe.textContent = m && p ? alsGeld(summeInCent(m, p)) : '-';
    }

    document.addEventListener('input', function (ereignis) {
        const zeile = ereignis.target.closest && ereignis.target.closest(
            'tr.form-row'
        );
        if (zeile && /-(menge|einzelpreis)$/.test(ereignis.target.name)) {
            zeileRechnen(zeile);
        }
    });

    /* Angefügte Zeilen sofort berechnen, nicht erst bei Eingabe. */
    document.addEventListener('formset:added', function (ereignis) {
        zeileRechnen(ereignis.target);
    });

    /* Beim Laden alle Zeilen berechnen, auch nach einem Validierungsfehler
     * zurückgegebene. */
    function alleRechnen() {
        document.querySelectorAll('tr.form-row').forEach(zeileRechnen);
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', alleRechnen);
    } else {
        alleRechnen();
    }
})();
