/**
 * The undo queue: one toast per bulk delete, each with its own countdown.
 *
 * A bulk delete stays undoable for a few seconds (DELETE_UNDO_SECONDS on the
 * server). The page used to keep a single offer, so a second delete replaced
 * the first one's Undo and restarted its clock. Every delete is now a batch
 * on the server with its own expiry, and every batch gets its own toast here:
 * deleting 10 and then 5 shows two toasts and "15 documents can be undone",
 * each running down from its own deadline. Undoing one leaves the other alone.
 *
 * The server is the source of truth. The queue is rebuilt from
 * /documents/deletions/pending/ on every page load, so the offer follows the
 * person from page to page while its time is running, and nothing here can
 * extend it: an undo that arrives late is refused by the server.
 */
(function () {
    'use strict';

    var root = document.getElementById('qaUndoQueue');
    if (!root) { return; }

    var pendingUrl = root.getAttribute('data-pending-deletions-url');
    var undoTemplate = root.getAttribute('data-undo-url-template') || '';
    var DISMISSED_KEY = 'qaUndoDismissed';
    var items = {};      // batch id -> item
    var order = [];      // batch ids, oldest first
    var ticker = null;

    var summary = document.createElement('div');
    summary.className = 'qa-undo-summary';
    summary.hidden = true;
    root.appendChild(summary);

    function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }

    function dismissed() {
        try { return JSON.parse(sessionStorage.getItem(DISMISSED_KEY) || '[]'); } catch (e) { return []; }
    }
    function rememberDismissed(id) {
        try {
            var list = dismissed().filter(function (x) { return x !== id; });
            list.push(id);
            sessionStorage.setItem(DISMISSED_KEY, JSON.stringify(list.slice(-50)));
        } catch (e) { /* storage blocked: a dismissed toast may come back on the next page */ }
    }

    function csrf() {
        var input = document.querySelector('[name=csrfmiddlewaretoken]');
        if (input && input.value) { return input.value; }
        var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }

    /* ------------------------------------------------------------------ */

    function build(item) {
        var el = document.createElement('div');
        el.className = 'qa-undo-item';
        el.setAttribute('role', 'status');
        el.setAttribute('data-batch-id', String(item.id));
        el.innerHTML =
            '<span class="qa-undo-icon" aria-hidden="true"><i class="bi bi-trash3"></i></span>' +
            '<div class="qa-undo-text">' +
            '<strong class="qa-undo-title"></strong>' +
            '<span class="qa-undo-status"></span>' +
            '</div>' +
            '<button type="button" class="qa-undo-btn"><i class="bi bi-arrow-counterclockwise" aria-hidden="true"></i><span>Undo</span></button>' +
            '<button type="button" class="qa-undo-close" aria-label="Dismiss">&times;</button>' +
            '<span class="qa-undo-progress" aria-hidden="true"><i></i></span>';
        el.querySelector('.qa-undo-title').textContent = plural(item.count, 'document', 'documents') + ' deleted';
        el.querySelector('.qa-undo-btn').addEventListener('click', function () { undo(item); });
        el.querySelector('.qa-undo-close').addEventListener('click', function () {
            rememberDismissed(item.id);
            remove(item);
        });
        return el;
    }

    function add(batch) {
        if (!batch || !batch.id || items[batch.id]) { return; }
        if (dismissed().indexOf(batch.id) !== -1) { return; }
        // Run the countdown off the server's clock: a phone whose clock is a
        // minute out must not show time the server will not honour.
        var skew = (batch.server_now_ms || Date.now()) - Date.now();
        var item = {
            id: batch.id,
            count: batch.count,
            expires: batch.expires_at_ms - skew,
            total: Math.max(1, batch.expires_at_ms - (batch.server_now_ms || Date.now())),
            state: 'pending'
        };
        if (item.expires <= Date.now()) { return; }
        // A batch created on an earlier page started its window then, so its
        // bar starts part-drained rather than full.
        if (batch.window_ms) { item.total = batch.window_ms; }
        item.el = build(item);
        items[item.id] = item;
        order.push(item.id);
        root.appendChild(item.el);   // newest nearest the corner
        tick();
        if (!ticker) { ticker = setInterval(tick, 250); }
    }

    function remove(item, delay) {
        if (!items[item.id]) { return; }
        delete items[item.id];
        order = order.filter(function (id) { return id !== item.id; });
        setTimeout(function () {
            item.el.classList.add('is-leaving');
            setTimeout(function () { item.el.remove(); }, 220);
        }, delay || 0);
        updateSummary();
        if (!order.length && ticker) { clearInterval(ticker); ticker = null; }
    }

    function setStatus(item, text, kind) {
        item.el.querySelector('.qa-undo-status').textContent = text;
        item.el.classList.remove('is-restoring', 'is-restored', 'is-error', 'is-expired');
        if (kind) { item.el.classList.add('is-' + kind); }
    }

    function tick() {
        var now = Date.now();
        order.slice().forEach(function (id) {
            var item = items[id];
            if (!item || item.state !== 'pending') { return; }
            var left = item.expires - now;
            if (left <= 0) {
                item.state = 'expired';
                item.el.querySelector('.qa-undo-btn').disabled = true;
                item.el.querySelector('.qa-undo-progress i').style.width = '0%';
                setStatus(item, 'Permanently deleted', 'expired');
                remove(item, 1600);
                return;
            }
            var secs = Math.ceil(left / 1000);
            setStatus(item, 'Undo available · ' + secs + 's');
            item.el.querySelector('.qa-undo-progress i').style.width =
                Math.max(0, Math.min(100, (left / item.total) * 100)) + '%';
        });
        updateSummary();
    }

    function updateSummary() {
        var undoable = order.map(function (id) { return items[id]; })
            .filter(function (item) { return item && item.state === 'pending'; });
        if (undoable.length < 2) { summary.hidden = true; return; }
        var total = undoable.reduce(function (n, item) { return n + item.count; }, 0);
        summary.textContent = plural(total, 'document', 'documents') + ' can be undone';
        summary.hidden = false;
    }

    /* ------------------------------------------------------------------ */

    function undo(item) {
        if (!item || item.state !== 'pending') { return; }   // one request per batch
        item.state = 'restoring';
        var button = item.el.querySelector('.qa-undo-btn');
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span><span>Restoring…</span>';
        setStatus(item, 'Restoring…', 'restoring');

        var body = new FormData();
        body.append('csrfmiddlewaretoken', csrf());
        var url = undoTemplate.replace(/0\/undo\/$/, item.id + '/undo/');
        fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            body: body
        })
            .then(function (r) {
                if (window.qaActivity && window.qaActivity.expired(r)) { return null; }
                return r.json().catch(function () { return {}; }).then(function (data) {
                    return { status: r.status, ok: r.ok, data: data || {} };
                });
            })
            .then(function (res) {
                if (!res) { return; }
                if (res.ok && res.data.ok) {
                    item.state = 'restored';
                    button.innerHTML = '<i class="bi bi-check2" aria-hidden="true"></i><span>Restored</span>';
                    setStatus(item, res.data.message || 'Restored', 'restored');
                    item.el.querySelector('.qa-undo-progress i').style.width = '0%';
                    remove(item, 2200);
                    document.dispatchEvent(new CustomEvent('qa:documents-restored', {
                        detail: { batch: item.id, ids: res.data.ids || [], restored: res.data.restored }
                    }));
                    document.dispatchEvent(new CustomEvent('qa:documents-changed', { detail: { reason: 'restore' } }));
                    return;
                }
                failed(item, res.status, res.data);
            })
            .catch(function () { failed(item, 0, {}); });
    }

    function failed(item, status, data) {
        var message = window.qaRequestError
            ? window.qaRequestError(status, data, 'undo')
            : (data && data.error) || 'The documents could not be restored.';
        var button = item.el.querySelector('.qa-undo-btn');
        // Offline or a server hiccup with time still on the clock: let them
        // try again. Anything else is final.
        var canRetry = (status === 0 || status >= 500) && item.expires > Date.now();
        if (canRetry) {
            item.state = 'pending';
            button.disabled = false;
            button.innerHTML = '<i class="bi bi-arrow-counterclockwise" aria-hidden="true"></i><span>Retry</span>';
            setStatus(item, message, 'error');
            return;
        }
        item.state = 'failed';
        button.innerHTML = '<i class="bi bi-x-lg" aria-hidden="true"></i><span>Not restored</span>';
        setStatus(item, message, 'error');
        remove(item, 6000);
    }

    /* ------------------------------------------------------------------ */

    function refresh() {
        if (!pendingUrl) { return; }
        fetch(pendingUrl, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (data) {
                if (!data || !data.batches) { return; }
                data.batches.forEach(function (batch) {
                    batch.window_ms = parseInt(root.getAttribute('data-undo-seconds'), 10) * 1000 || null;
                    add(batch);
                });
            })
            .catch(function () { /* offline: the queue fills in when the connection is back */ });
    }

    // Ctrl+Z / Cmd+Z undoes the most recent deletion that is still undoable,
    // unless the person is typing.
    document.addEventListener('keydown', function (e) {
        var key = (e.key || '').toLowerCase();
        if (key !== 'z' || !(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey) { return; }
        var el = document.activeElement;
        if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) { return; }
        for (var i = order.length - 1; i >= 0; i--) {
            var item = items[order[i]];
            if (item && item.state === 'pending') {
                e.preventDefault();
                undo(item);
                return;
            }
        }
    });

    document.addEventListener('visibilitychange', function () { if (!document.hidden) { refresh(); } });
    window.addEventListener('online', refresh);
    document.addEventListener('qa:reconnected', refresh);

    window.qaUndoQueue = { add: add, refresh: refresh };
    refresh();
})();
