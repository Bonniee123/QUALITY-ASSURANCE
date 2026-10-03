/**
 * Live badge counts for messages and notifications.
 *
 * The sidebar count and the notification bell are rendered once by the server,
 * so before this they only changed when the user navigated. A message could
 * arrive and leave no trace anywhere in the interface until the next page load.
 *
 * There are no WebSockets in this stack, so the counts are refreshed on a short
 * interval from a single endpoint (/dashboard/live/) that returns the two
 * counts and a fingerprint of the documents in view. The poll pauses
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
        // The repository total is a count of things, not an alert, so it is
        // shown in full.
        var shown = (count > 99 && kind !== 'documents') ? '99+' : String(count);

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

    /* ------------------------------------------------------------------
     * Documents and notifications, live.
     *
     * The poll also carries a fingerprint of the documents this person can
     * see. When it changes -- someone uploaded, deleted, restored, or a
     * processing run finished -- the page is told with a `qa:documents-changed`
     * event, and the parts that show documents refresh themselves: the
     * Repository list, the dashboard figures, the sidebar count. A new
     * notification refreshes the bell's list as well as its number.
     * ------------------------------------------------------------------ */
    var lastStamp = null;
    var lastUnread = null;
    var bellPending = false;

    function refreshBellList() {
        var menu = document.getElementById('qaNotifMenu');
        var url = menu && menu.getAttribute('data-refresh-url');
        if (!url) { return; }
        // Never rebuild the list under someone's pointer: wait for it to close.
        if (menu.classList.contains('show')) {
            if (!bellPending) {
                bellPending = true;
                var host = document.getElementById('qaNotifDropdown');
                if (host) {
                    host.addEventListener('hidden.bs.dropdown', function onHidden() {
                        host.removeEventListener('hidden.bs.dropdown', onHidden);
                        bellPending = false;
                        refreshBellList();
                    });
                }
            }
            return;
        }
        fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { return r.ok ? r.text() : null; })
            .then(function (html) { if (html != null) { menu.innerHTML = html; } })
            .catch(function () {});
    }

    /*
     * Pages that mark themselves `data-live-page` can be re-read in place:
     * the page is fetched again and every `[data-live-region]` and
     * `[data-live-text]` in it replaces its twin here, by id. Only pages
     * whose GET changes nothing opt in -- a page that logs a view would log
     * one on every refresh.
     */
    var regionsBusy = false;
    function refreshLiveRegions() {
        if (regionsBusy || !document.querySelector('[data-live-page]')) { return; }
        regionsBusy = true;
        fetch(window.location.href, { credentials: 'same-origin', headers: { 'X-QA-Live': '1' } })
            .then(function (r) { return r.ok ? r.text() : null; })
            .then(function (html) {
                if (!html) { return; }
                var fresh = new DOMParser().parseFromString(html, 'text/html');
                document.querySelectorAll('[data-live-region][id]').forEach(function (el) {
                    var twin = fresh.getElementById(el.id);
                    if (twin && twin.innerHTML !== el.innerHTML) { el.innerHTML = twin.innerHTML; }
                });
                document.querySelectorAll('[data-live-text][id]').forEach(function (el) {
                    var twin = fresh.getElementById(el.id);
                    if (!twin) { return; }
                    // Headline numbers are shown with thousands separators
                    // (main.js); the page source carries them bare.
                    var value = twin.textContent.trim();
                    if (el.hasAttribute('data-countup')) {
                        el.setAttribute('data-countup', twin.getAttribute('data-countup') || value);
                        var n = parseInt(value.replace(/[^0-9-]/g, ''), 10);
                        if (!isNaN(n)) { value = n.toLocaleString(); }
                    }
                    if (value !== el.textContent.trim()) {
                        el.textContent = value;
                        el.classList.remove('qa-live-flash');
                        void el.offsetWidth;
                        el.classList.add('qa-live-flash');
                    }
                });
            })
            .catch(function () {})
            .then(function () { regionsBusy = false; });
    }
    window.qaRefreshLiveRegions = refreshLiveRegions;

    document.addEventListener('qa:documents-changed', function () { refreshLiveRegions(); });

    function poll() {
        if (document.hidden || window.qaLiveOwner) { return; }
        var qa = window.qaActivity;
        // Marked passive once nobody is at the page, so an unattended screen
        // no longer keeps the session alive (see main.js).
        fetch('/dashboard/live/', {
            credentials: 'same-origin',
            headers: qa ? qa.headers() : {}
        })
            .then(function (r) {
                if (window.qaConnection) { window.qaConnection.ok(); }
                if (qa && qa.expired(r)) { return null; }
                return r.ok ? r.json() : null;
            })
            .then(function (d) {
                if (!d) { return; }
                setBadge('messages', d.unread_messages);
                setBadge('bell', d.unread_notifications);
                if (lastUnread !== null && d.unread_notifications !== lastUnread) { refreshBellList(); }
                lastUnread = d.unread_notifications;
                if (d.documents) {
                    setBadge('documents', d.documents.count);
                    if (lastStamp !== null && d.documents.stamp !== lastStamp) {
                        document.dispatchEvent(new CustomEvent('qa:documents-changed', {
                            detail: { reason: 'remote', count: d.documents.count }
                        }));
                    }
                    lastStamp = d.documents.stamp;
                }
            })
            .catch(function () {
                // No answer at all: the network or the server is down.
                if (window.qaConnection) { window.qaConnection.failed(); }
            });
    }

    // Back online: catch up at once rather than at the next tick.
    document.addEventListener('qa:reconnected', function () { poll(); });

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
