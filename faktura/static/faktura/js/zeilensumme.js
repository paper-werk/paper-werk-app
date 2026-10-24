/* Berechnet die Spalte "Betrag" der Positionen bei Eingabe, auch den
 * Betrag der Zuschläge.
 *
 * Der Server liefert den Betrag nur für gespeicherte Positionen
 * (BelegpositionInline.zeilensumme) und rechnet Zuschläge erst beim
 * Speichern nach (services.zuschlaege_nachrechnen).
 *
 * Nur Darstellung; maßgeblich sind services.positionssumme() (R-001) und
 * services.zuschlagsbasis() (R-180). Dieselben Regeln:
 *
 * - Leistung: Menge mal Einzelpreis, kaufmännisch auf den Cent, die Hälfte
 *   von der Null weg (core/rechnen.py, 0,75 x 89,50 = 67,13).
 * - Zuschlag: Basis mal Satz durch 100, ebenso gerundet. Basis sind die
 *   Beträge der Leistungen, deren Nummer unter "auf" fällt (gleich oder mit
 *   "auf." beginnend, leer = alle), ohne optionale, ohne gelöschte, nie ein
 *   anderer Zuschlag. Ein optionaler Zuschlag hat keinen Betrag.
 * - Titel und Text: kein Betrag.
 *
 * Mit BigInt, weil 0,75 * 89,5 in Gleitkomma 67,12499999... ergibt und
 * einen Cent abwiche. Weil jede Zeile die Zuschläge ändern kann, wird bei
 * jeder Eingabe die ganze Maske neu berechnet.
 *
 * Die Werte stehen im technischen Format ('1.000', '89.50'), weil die
 * Felder <input type="number"> sind (siehe katalog_uebernehmen.js).
 */
'use strict';

(function () {
    const GRUPPE = 'tbody.form-group';
    const AUSLOESER = /-(menge|einzelpreis|position|zuschlag_prozent|zuschlag_auf|zeilenart|optional|DELETE)$/;

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

    /* zaehler / nenner, kaufmännisch gerundet: die Hälfte von der Null weg;
     * am Betrag, dann das Vorzeichen zurück. */
    function gerundet(zaehler, nenner) {
        const betrag = zaehler < 0n ? -zaehler : zaehler;
        const ergebnis = (betrag * 2n + nenner) / (nenner * 2n);
        return zaehler < 0n ? -ergebnis : ergebnis;
    }

    /* Menge mal Preis in Cent. */
    function summeInCent(menge, preis) {
        const produkt = menge.ziffern * preis.ziffern;
        const stellen = menge.stellen + preis.stellen;
        if (stellen <= 2) {
            return produkt * 10n ** BigInt(2 - stellen);
        }
        return gerundet(produkt, 10n ** BigInt(stellen - 2));
    }

    /* Basis in Cent mal Prozentsatz durch 100, in Cent. */
    function zuschlagInCent(basis, prozent) {
        return gerundet(basis * prozent.ziffern,
                        100n * 10n ** BigInt(prozent.stellen));
    }

    /* 1481472n -> '14.814,72 EUR'; wie formate.geld_mit_waehrung(). */
    function alsGeld(cent) {
        const negativ = cent < 0n;
        const text = (negativ ? -cent : cent).toString().padStart(3, '0');
        const euro = text.slice(0, -2).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
        return (negativ ? '-' : '') + euro + ',' + text.slice(-2) + ' EUR';
    }

    /* Wie services.gehoert_zu: "01" trifft "01" und "01.0010", nicht
     * "010"; leer trifft alle. */
    function gehoertZu(nummer, anfang) {
        return !anfang || nummer === anfang || nummer.startsWith(anfang + '.');
    }

    function feld(gruppe, name) {
        return gruppe.querySelector('[name$="-' + name + '"]');
    }

    function wert(gruppe, name) {
        const element = feld(gruppe, name);
        return element ? element.value.trim() : '';
    }

    function angehakt(gruppe, name) {
        const element = feld(gruppe, name);
        return Boolean(element && element.checked);
    }

    /* Die Angaben einer Position aus der Maske; null für die Vorlage
     * angefügter Zeilen und Gruppen ohne Betragsspalte. */
    function zeile(gruppe) {
        const ausgabe = gruppe.querySelector('td.field-zeilensumme .readonly');
        if (!ausgabe || gruppe.classList.contains('empty-form')) {
            return null;
        }
        const menge = zerlegen(wert(gruppe, 'menge'));
        const preis = zerlegen(wert(gruppe, 'einzelpreis'));
        return {
            ausgabe: ausgabe,
            art: wert(gruppe, 'zeilenart') || 'leistung',
            nummer: wert(gruppe, 'position'),
            optional: angehakt(gruppe, 'optional'),
            geloescht: angehakt(gruppe, 'DELETE'),
            auf: wert(gruppe, 'zuschlag_auf'),
            prozent: zerlegen(wert(gruppe, 'zuschlag_prozent')),
            netto: menge && preis ? summeInCent(menge, preis) : null,
        };
    }

    function alleRechnen() {
        const zeilen = Array.from(document.querySelectorAll(GRUPPE))
            .map(zeile).filter(Boolean);
        const leistungen = zeilen.filter(function (z) {
            return z.art === 'leistung' && !z.optional && !z.geloescht
                && z.netto !== null;
        });

        zeilen.forEach(function (z) {
            if (z.art === 'titel' || z.art === 'text') {
                z.ausgabe.textContent = '';
            } else if (z.art === 'zuschlag') {
                if (z.optional) {
                    z.ausgabe.textContent = '';
                    return;
                }
                const basis = leistungen
                    .filter(function (l) { return gehoertZu(l.nummer, z.auf); })
                    .reduce(function (summe, l) { return summe + l.netto; }, 0n);
                z.ausgabe.textContent = alsGeld(
                    z.prozent ? zuschlagInCent(basis, z.prozent) : 0n);
            } else {
                z.ausgabe.textContent = z.netto !== null ? alsGeld(z.netto) : '-';
            }
        });
    }

    function beiEingabe(ereignis) {
        if (ereignis.target.name && AUSLOESER.test(ereignis.target.name)) {
            alleRechnen();
        }
    }

    document.addEventListener('input', beiEingabe);
    document.addEventListener('change', beiEingabe);
    /* Angefügte und entfernte Zeilen sofort berücksichtigen. */
    document.addEventListener('formset:added', alleRechnen);
    document.addEventListener('formset:removed', alleRechnen);

    /* Beim Laden alles berechnen, auch nach einem Validierungsfehler
     * zurückgegebene Zeilen. */
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', alleRechnen);
    } else {
        alleRechnen();
    }
})();
