/*
 * Reconnect: the shared logic behind the offline card.
 *
 * Checks /healthz/ -- a tiny answer that needs no database and no session --
 * on a widening interval (3, 6, 12, then every 15 seconds), at once when the
 * browser reports the network is back, and whenever Retry is pressed. The
 * card's status line says what is happening, and a second Retry while one
 * check is running does nothing.
 *
 * window.qaReconnect(card, onBack) -> { start(), stop(), check() }
 * Inline in the offline page and in base.html, so the offline page needs no
 * file from the server it cannot reach.
 */
(function () {
    'use strict';
    if (window.qaReconnect) { return; }
    window.qaReconnect = function (card, onBack) {
        var status = card.querySelector('[data-offline-status]');
        var retry = card.querySelector('[data-offline-retry]');
        var label = retry ? retry.querySelector('span') : null;
        var icon = retry ? retry.querySelector('svg') : null;
        var delays = [3, 6, 12, 15];
        var attempt = 0, timer = null, tick = null, busy = false, running = false;

        function say(state, text) {
            if (!status) { return; }
            status.setAttribute('data-state', state);
            status.textContent = text;
        }
        function setBusy(on) {
            busy = on;
            if (!retry) { return; }
            retry.disabled = on;
            if (label) { label.textContent = on ? 'Checking…' : 'Retry connection'; }
            if (icon) { icon.classList.toggle('err-spin', on); }
        }
        function schedule() {
            clearTimeout(timer); clearInterval(tick);
            if (!running) { return; }
            var wait = delays[Math.min(attempt, delays.length - 1)];
            var left = wait;
            var offline = navigator.onLine === false;
            var base = offline ? 'No internet connection' : 'Server not reachable';
            say('offline', base + ' · retrying in ' + left + 's');
            tick = setInterval(function () {
                left -= 1;
                if (left > 0) { say('offline', base + ' · retrying in ' + left + 's'); }
            }, 1000);
            timer = setTimeout(check, wait * 1000);
        }
        function check() {
            if (busy) { return; }
            clearTimeout(timer); clearInterval(tick);
            setBusy(true);
            say('checking', 'Checking connection…');
            var done = false;
            var guard = setTimeout(function () { if (!done) { done = true; failed(); } }, 8000);
            fetch('/healthz/?t=' + Date.now(), { cache: 'no-store', credentials: 'same-origin' })
                .then(function (r) {
                    if (done) { return; }
                    done = true; clearTimeout(guard);
                    if (r.ok) { back(); } else { failed(); }
                })
                .catch(function () {
                    if (done) { return; }
                    done = true; clearTimeout(guard);
                    failed();
                });
        }
        function failed() {
            setBusy(false);
            attempt += 1;
            schedule();
        }
        function back() {
            setBusy(false);
            running = false;
            attempt = 0;
            say('online', 'Connected');
            if (typeof onBack === 'function') { onBack(); }
        }
        if (retry) { retry.addEventListener('click', check); }
        window.addEventListener('online', function () { if (running) { check(); } });

        return {
            start: function () { if (running) { return; } running = true; attempt = 0; schedule(); },
            stop: function () { running = false; clearTimeout(timer); clearInterval(tick); setBusy(false); },
            check: function () { running = true; check(); },
            isRunning: function () { return running; }
        };
    };
})();
