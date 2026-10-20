/* Speichert den Beleg vor einer Detailaktion in der Kopfleiste.
 *
 * Die Detailaktionen (Versenden, Auftrag erzeugen, Nachtrag, Wieder öffnen)
 * sind Links. Ohne Speichern arbeitete die Aktion mit dem gespeicherten
 * Stand und verwürfe die Eingaben; beim Versenden erhielte der Kunde ein
 * PDF ohne die Korrektur, und der Beleg wäre festgeschrieben.
 *
 * Ablauf: Klick abfangen, Formular senden, danach die Aktion. Das Feld
 * "_danach" nennt dem Server die Aktion
 * (AktionNachDemSichern.response_change).
 *
 * Neuer Tab (PDF anzeigen, target="_blank"): Gespeichert wird per fetch
 * (derselbe POST mit "_danach"), dann öffnet sich das Ziel im neuen Tab, und
 * die Maske wird neu geladen, weil das nächste Speichern sonst mit der
 * alten Version am Optimistic Locking scheiterte. Der Tab wird im
 * Klick-Handler geöffnet, damit der Popup-Blocker nicht greift; schlägt das
 * Speichern fehl (Validierung), schließt er sich, und das Formular wird
 * normal gesendet, um die Fehler anzuzeigen.
 *
 * Ohne Rückfrage, weil eine Aktion am Beleg immer den angezeigten Stand
 * meint. Verworfen: eine Rückfrage mit Erkennung von Änderungen.
 *
 * Das Skript wird mit defer eingebunden (AktionNachDemSichern.media) und
 * liest das DOM erst im Klick, weil Django Media im <head> einbindet.
 * Regression: Ohne defer lief es vor dem Formular und endete ohne Fehler.
 */
'use strict';

(function () {
    function setzeFeld(formular, name, wert) {
        var feld = formular.querySelector('input[name="' + name + '"]');
        /* Nur ein Hidden Input wird überschrieben, weil es '_continue' auch
         * als Button gibt, dessen 'value' sein Label ist. */
        if (!feld || feld.type !== 'hidden') {
            feld = document.createElement('input');
            feld.type = 'hidden';
            feld.name = name;
            formular.appendChild(feld);
        }
        feld.value = wert;
    }

    function imNeuenReiterNachDemSichern(formular, pfad, ziel) {
        var reiter = window.open('about:blank', '_blank');
        var daten = new FormData(formular);
        daten.set('_danach', pfad);
        daten.set('_continue', '1');

        fetch(formular.action || window.location.href, {
            method: 'POST',
            body: daten,
            credentials: 'same-origin',
            /* Ein erfolgreiches Speichern liefert einen Redirect; ohne
             * Folgen, weil das Ziel das PDF ist. */
            redirect: 'manual'
        }).then(function (antwort) {
            if (antwort.type === 'opaqueredirect') {
                if (reiter) {
                    reiter.location.href = ziel;
                } else {
                    window.open(ziel, '_blank');
                }
                /* Unfold entfernt seine Warnung "Webseite verlassen?" beim
                 * submit-Event; gespeichert ist bereits. */
                formular.dispatchEvent(new Event('submit', {cancelable: true}));
                window.location.reload();
                return;
            }
            if (reiter) {
                reiter.close();
            }
            setzeFeld(formular, '_continue', '1');
            formular.requestSubmit();
        }).catch(function (fehler) {
            console.warn('aktion_erst_speichern: Sichern gescheitert', fehler);
            if (reiter) {
                reiter.close();
            }
        });
    }

    document.addEventListener('click', function (ereignis) {
        var verweis = ereignis.target.closest
            ? ereignis.target.closest('a[href]')
            : null;
        if (!verweis) {
            return;
        }

        /* Nur im Änderungsformular eines Datensatzes. */
        var stelle = window.location.pathname;
        var treffer = stelle.match(/^(.*\/)change\/$/);
        if (!treffer) {
            return;
        }
        var basis = treffer[1];

        var ziel;
        try {
            ziel = new URL(verweis.href, window.location.origin);
        } catch (fehler) {
            console.warn('aktion_erst_speichern: Verweis unlesbar', fehler);
            return;
        }
        if (ziel.origin !== window.location.origin) {
            return;
        }
        if (ziel.pathname.indexOf(basis) !== 0 || ziel.pathname === stelle) {
            return;
        }

        /* '/admin/faktura/angebot/565/versenden/' ergibt 'versenden'. Pfade
         * mit weiterem Schrägstrich gehören nicht zu diesem Datensatz.
         * Ausgenommen sind Löschen (eigene Rückfrage) und der Verlauf
         * ('history' von Django, 'verlauf' aus "Weitere …"). */
        var pfad = ziel.pathname.slice(basis.length).replace(/\/$/, '');
        if (!pfad || pfad.indexOf('/') !== -1
            || pfad === 'delete' || pfad === 'history'
            || pfad === 'verlauf') {
            return;
        }

        var formular = document.querySelector('form.warn-unsaved-form');
        if (!formular) {
            return;
        }

        /* Ohne Button zum Speichern ist der Beleg readonly
         * (festgeschrieben); ein POST ergäbe 403.
         *
         * Gesucht wird im Dokument, nicht im Formular, weil Unfold die
         * Leiste zum Speichern sticky außerhalb des Formulars rendert und
         * über das HTML5-Attribut form="angebot_form" verbindet:
         *
         *     <button type="submit" form="angebot_form" name="_save" ...>
         *
         * Regression: ``formular.querySelector('[name="_save"]')`` fand
         * den Button nicht, und das Skript endete jedes Mal ohne Fehler. */
        var sichern = formular.querySelector('[name="_save"]')
            || (formular.id
                && document.querySelector(
                    '[name="_save"][form="' + formular.id + '"]'));
        if (!sichern) {
            return;
        }

        ereignis.preventDefault();
        /* In der Capture-Phase, damit htmx den Dialog nicht öffnet, weil
         * Aktionen mit Dialog die Seite nicht verlassen und der Browser
         * dann nicht warnt. */
        ereignis.stopPropagation();

        if (verweis.target === '_blank') {
            imNeuenReiterNachDemSichern(formular, pfad, ziel.href);
            return;
        }

        setzeFeld(formular, '_danach', pfad);
        /* Bei unbekanntem Ziel zurück auf den Beleg, nicht in die Liste. */
        setzeFeld(formular, '_continue', '1');

        /* requestSubmit, weil nur dieses das submit-Event auslöst, bei dem
         * Unfold die Warnung "Webseite verlassen?" entfernt. */
        formular.requestSubmit();
    }, true);
})();
