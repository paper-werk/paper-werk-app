/* Deutsche Zahlen in den Chart.js-Diagrammen (Controlling-Seite).
 *
 * Unfolds app.js zeichnet die Diagramme und schreibt die Achse fest als
 * `${value} €` ("100000 €" ohne Tausenderpunkt), die Tooltips mit Punkt
 * als Dezimalzeichen. Über die Einstellungen kommt man daran nicht heran
 * (JSON trägt keine Funktionen). Dieses Skript stellt nach dem Zeichnen
 * Achse und Tooltips JEDES Chart.js-Diagramms auf deutsche Schreibweise um.
 *
 * Startseite und Projektakte zeichnen Säulen als HTML
 * (admin/_saeulen.html). Die Controlling-Seite verwendet Chart.js für
 * Balken und Linie in einem Diagramm (auswertung/controllingseite.py,
 * _verlaufsdaten).
 *
 * Ohne Chart.js oder Diagramm ohne Wirkung. Eingebunden über
 * UNFOLD['SCRIPTS'] in paperwerk/settings/unfold.py.
 */
(function () {
    'use strict';

    var zahl = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 2 });

    function suffix(diagramm) {
        var reihe = diagramm.data.datasets.find(function (r) { return r.suffixYAxis; });
        return reihe ? ' ' + reihe.suffixYAxis.trim() : '';
    }

    function eindeutschen(diagramm) {
        // In die ROHEN Optionen (config.options), aus denen Chart.js beim
        // ersten Zeichnen auflöst; nicht in die aufgelösten
        // (diagramm.options), weil diese ein Proxy sind und eine Zuweisung
        // "Maximum call stack size exceeded" auslöste.
        // Kein update(): "afterInit" kommt vor dem ersten Zeichnen.
        // Nur Balken und Linien. Die Landkarte (Blasen) auf der
        // Controlling-Seite setzt ihren eigenen Tooltip
        // (admin/controlling.html).
        if (['bar', 'line'].indexOf(diagramm.config.type) === -1) {
            return;
        }
        var optionen = diagramm.config.options || {};
        var einheit = suffix(diagramm);
        var achse = optionen.scales && optionen.scales.y;
        if (achse) {
            achse.ticks = achse.ticks || {};
            achse.ticks.callback = function (wert) { return zahl.format(wert) + einheit; };
        }
        optionen.plugins = optionen.plugins || {};
        optionen.plugins.tooltip = optionen.plugins.tooltip || {};
        optionen.plugins.tooltip.callbacks = optionen.plugins.tooltip.callbacks || {};
        optionen.plugins.tooltip.callbacks.label = function (kontext) {
            var wert = kontext.parsed.y !== undefined ? kontext.parsed.y : kontext.parsed;
            var name = kontext.dataset.label ? kontext.dataset.label + ': ' : '';
            return name + zahl.format(wert) + einheit;
        };
    }

    // Als Chart.js-Plugin, weil Unfold die Diagramme erst nach "load"
    // erzeugt (geprüft); das Plugin erfasst jedes Diagramm bei seiner
    // Erzeugung. Chart.js wird im head vor diesem Skript geladen.
    if (typeof window.Chart === 'undefined') {
        return;
    }
    window.Chart.register({
        id: 'paperwerkDeutscheZahlen',
        afterInit: eindeutschen
    });
})();
