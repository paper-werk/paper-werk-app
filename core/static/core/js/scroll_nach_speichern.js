/* Erhält die Scroll-Position, wenn das Speichern in derselben Maske endet.
 *
 * Beim Submit werden Pfad und scrollY in sessionStorage abgelegt, beim
 * nächsten Laden einmalig gelesen und entfernt. Wiederhergestellt wird nur
 * nach einem Redirect (POST/Redirect/GET), weil Django ein Formular mit
 * Validierungsfehlern ohne Redirect ausliefert und die Meldung oben sichtbar
 * sein muss. Ziel ist dieselbe Änderungsmaske oder, nach dem ersten
 * Speichern, die Änderungsmaske des neuen Datensatzes.
 *
 * Unfold rendert Meldungen am Seitenanfang. Außer bei reinen Erfolgsmeldungen
 * bleibt die Seite deshalb oben, damit Warnungen sichtbar sind. Unfold
 * unterscheidet die Art einer Meldung nur über die Farbklasse;
 * ``AUFFAELLIGE_MELDUNG`` hängt an diesem Markup, abgesichert durch
 * tests/test_browser_scroll.py.
 *
 * Verworfen: die Position je URL dauerhaft ablegen, weil ein später über die
 * Liste geöffneter Datensatz sonst nicht oben begänne.
 */
'use strict';

(function () {
    const SCHLUESSEL = 'pw-scroll-nach-speichern';
    const AUFFAELLIGE_MELDUNG = 'li[class*="mb-0!"] > div:not(.bg-green-100)';

    function selbeMaske(von, nach) {
        if (!nach.endsWith('/change/')) {
            return false;
        }
        if (von === nach) {
            return true;
        }
        const basis = von.endsWith('/add/') ? von.slice(0, -4) : null;
        return basis !== null && nach.startsWith(basis)
            && /^[^/]+\/change\/$/.test(nach.slice(basis.length));
    }

    function abholen() {
        try {
            const wert = sessionStorage.getItem(SCHLUESSEL);
            sessionStorage.removeItem(SCHLUESSEL);
            return wert ? JSON.parse(wert) : null;
        } catch (fehler) {
            return null;
        }
    }

    document.addEventListener('submit', function (ereignis) {
        const pfad = window.location.pathname;
        if (ereignis.target.method !== 'post' || !/\/(add|change)\/$/.test(pfad)) {
            return;
        }
        try {
            sessionStorage.setItem(SCHLUESSEL, JSON.stringify(
                {pfad: pfad, y: window.scrollY}));
        } catch (fehler) {
            console.warn('scroll_nach_speichern: nicht abgelegt', fehler);
        }
    }, true);

    /* load statt DOMContentLoaded, weil die Seitenhöhe erst mit den
     * initialisierten Widgets feststeht. */
    window.addEventListener('load', function () {
        const stand = abholen();
        const navigation = performance.getEntriesByType('navigation')[0];
        if (stand && navigation && navigation.redirectCount > 0
                && !window.location.hash
                && !document.querySelector(AUFFAELLIGE_MELDUNG)
                && selbeMaske(stand.pfad, window.location.pathname)) {
            window.scrollTo(0, stand.y);
        }
    });
})();
