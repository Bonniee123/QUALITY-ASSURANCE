/**
 * Losing the connection while a page is open.
 *
 * The page stays exactly as it was -- what was typed, what was selected, where
 * it was scrolled -- and the offline card is laid over it, saying whether the
 * device is offline or the server is not answering. It reconnects on its own
 * (status/_reconnect.js) and gets out of the way when it does; "Keep browsing"
 * tucks it into a small pill so what is on screen can still be read.
 *
 * Two signals: the browser's own offline/online events, and the live poll
 * (realtime.js) reporting that its requests are failing -- which catches the
 * case the browser cannot see, a network that is up with a server that is not.
 */
(function () {
    'use strict';

    var overlay = document.getElementById('qaOfflineOverlay');
    var pill = document.getElementById('qaOfflinePill');
    if (!overlay || !window.qaReconnect) { return; }
    var card = overlay.querySelector('.err-card');
    var title = card.querySelector('[data-offline-title]');
    var text = card.querySelector('[data-offline-text]');
    var dismiss = card.querySelector('[data-offline-dismiss]');
    var retry = card.querySelector('[data-offline-retry]');
    var down = false;
    var minimized = false;
    var failures = 0;
    var lastFocus = null;

    var COPY = {
        offline: ["You're offline",
                  "Your device isn't connected to the internet. Check your Wi-Fi or network cable — this page reconnects on its own, and nothing on it is lost."],
        server: ["Can't reach the server",
                 "Your connection looks fine, but the QA Archiving System isn't answering. It may be restarting — this page reconnects on its own, and nothing on it is lost."]
    };

    var link = window.qaReconnect(card, function () {
        down = false;
        failures = 0;
        hide();
        if (typeof window.qaToast === 'function') { window.qaToast('Back online.', 'success'); }
        document.dispatchEvent(new CustomEvent('qa:reconnected'));
    });

    function show(reason) {
        var copy = COPY[reason] || COPY.offline;
        title.textContent = copy[0];
        text.textContent = copy[1];
        if (down) { return; }
        down = true;
        lastFocus = document.activeElement;
        if (minimized) { pill.hidden = false; }
        else {
            overlay.hidden = false;
            if (retry) { retry.focus({ preventScroll: true }); }
        }
        link.start();
    }

    function hide() {
        overlay.hidden = true;
        if (pill) { pill.hidden = true; }
        minimized = false;
        if (lastFocus && document.contains(lastFocus) && typeof lastFocus.focus === 'function') {
            lastFocus.focus({ preventScroll: true });
        }
    }

    function minimize() {
        minimized = true;
        overlay.hidden = true;
        if (pill) { pill.hidden = false; }
    }

    if (dismiss) { dismiss.addEventListener('click', minimize); }
    overlay.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { e.preventDefault(); minimize(); }
    });
    if (pill) {
        pill.addEventListener('click', function () {
            minimized = false;
            pill.hidden = true;
            overlay.hidden = false;
            if (retry) { retry.focus({ preventScroll: true }); }
        });
    }

    /* Before calling the server unreachable, ask it directly: one failed poll
       is usually a blip, and the overlay should not flash for one. */
    function verify() {
        var done = false;
        var guard = setTimeout(function () { if (!done) { done = true; show('server'); } }, 6000);
        fetch('/healthz/?t=' + Date.now(), { cache: 'no-store', credentials: 'same-origin' })
            .then(function (r) { if (!done) { done = true; clearTimeout(guard); if (!r.ok) { show('server'); } } })
            .catch(function () { if (!done) { done = true; clearTimeout(guard); show(navigator.onLine === false ? 'offline' : 'server'); } });
    }

    window.addEventListener('offline', function () { show('offline'); });
    window.addEventListener('online', function () { if (down) { link.check(); } });

    window.qaConnection = {
        /* Called by the live poll. */
        failed: function () {
            failures += 1;
            if (!down && failures >= 2) { verify(); }
        },
        ok: function () {
            failures = 0;
            if (down) { link.check(); }
        },
        isDown: function () { return down; },
        show: show
    };

    if (navigator.onLine === false) { show('offline'); }
})();
