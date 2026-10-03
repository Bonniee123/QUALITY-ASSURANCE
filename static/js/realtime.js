/**
 * Live badge counts for messages and notifications.
 *
 * The sidebar count and the notification bell are rendered once by the server,
 * so before this they only changed when the user navigated. A message could
 * arrive and leave no trace anywhere in the interface until the next page load.
 *
 * There are no WebSockets in this stack, so the counts are refreshed on a short
 * interval from a single endpoint that returns two integers. The poll pauses
 * while the tab is hidden and fires immediately when it comes back, so the
 * numbers are current the moment the user looks at them.
 *
 * The Messages page runs its own richer sync and sets `window.qaLiveOwner`, so
 * this poller stands down there rather than asking for the same thing twice.
 * The floating Messages dock does the same for as long as it is open, and hands
 * the counts it receives back to `setBadge`.
 */
(function () {
    'use strict';

    var POLL_MS = 5000;
    var timer = null;

    /**
     * Set a badge to `count`, creating or removing it as needed.
     *
     * The server omits the badge element entirely when the count is zero, so
     * going from 0 to 1 has to build it rather than update it.
     */
    function setBadge(kind, count) {
        // Every host of that kind, not just the first one. The unread message
        // count now appears in two places at once -- the sidebar item and the
        // floating Messages button -- and querySelector only ever found the
        // sidebar, so the floating one kept whatever number the page was
        // rendered with until the next full page load.
        var hosts = document.querySelectorAll('[data-live-badge="' + kind + '"]');
        if (!hosts.length) { return; }

        var isBell = kind === 'bell';
        var selector = isBell ? '.qa-count-badge' : '.sidebar-badge';
        // Above ninety-nine the exact figure stops being the point, and the
        // pill would grow wide enough to drag itself off the bell it is
        // pinned to. The full number stays available to a screen reader.
        var shown = count > 99 ? '99+' : String(count);

        Array.prototype.forEach.call(hosts, function (host) {
            var badge = host.querySelector(selector);

            if (!count) {
                if (badge) { badge.remove(); }
                return;
            }
            if (!badge) {
                badge = document.createElement('span');
                badge.className = isBell
                    ? 'qa-count-badge qa-count-badge-pin'
                    : 'sidebar-badge';
                host.appendChild(badge);
            }
            // Rewrite the number in place. Replacing the element instead made
            // the badge vanish and reappear on every poll, which reads as a
            // flash even when the count has not changed.
            // textContent, not innerHTML: the number comes from the network.
            if (badge.firstChild && badge.firstChild.nodeType === 3) {
                if (badge.firstChild.nodeValue !== shown) {
                    badge.firstChild.nodeValue = shown;
                }
            } else {
                badge.textContent = shown;
            }
            if (isBell) {
                var sr = badge.querySelector('.visually-hidden');
                if (!sr) {
                    sr = document.createElement('span');
                    sr.className = 'visually-hidden';
                    badge.appendChild(sr);
                }
                // The exact figure, even when the badge reads "99+".
                sr.textContent = ' unread notifications (' + count + ')';
            }
        });
    }

    window.qaSetBadge = setBadge;

    function poll() {
        if (document.hidden || window.qaLiveOwner) { return; }
        var qa = window.qaActivity;
        // Marked passive once nobody is at the page, so an unattended screen
        // no longer keeps the session alive (see main.js).
        fetch('/messages/sync/?counts=1', {
            credentials: 'same-origin',
            headers: qa ? qa.headers() : {}
        })
            .then(function (r) {
                if (qa && qa.expired(r)) { return null; }
                return r.ok ? r.json() : null;
            })
            .then(function (d) {
                if (!d) { return; }
                setBadge('messages', d.unread_messages);
                setBadge('bell', d.unread_notifications);
            })
            .catch(function () {});
    }

    function start() {
        clearInterval(timer);
        timer = setInterval(poll, POLL_MS);
    }

    document.addEventListener('visibilitychange', function () {
        if (!document.hidden) { poll(); }
    });

    if (document.querySelector('[data-live-badge]')) {
        start();
        poll();
    }
})();
