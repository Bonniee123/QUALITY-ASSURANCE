/* QA Archiving System - Main JavaScript */

/* ------------------------------------------------------------------------
   Is anyone actually at this page?

   The session signs people out after an hour of inactivity, judged on the
   server by when the last request arrived. But every open page makes requests
   on its own -- badge counts every five seconds, upload and job progress, the
   Messages sync -- so the server saw "activity" every few seconds for as long
   as a tab stayed open, and the hour never ran out. A screen left signed in
   stayed signed in.

   So the page records when the person last did something, and its automatic
   requests carry `X-QA-Passive: 1` once nobody has for a minute. The server
   then stops counting them as activity. Defined before any poller loads.
   ------------------------------------------------------------------------ */
(function () {
    'use strict';

    var QUIET_AFTER_MS = 60 * 1000;
    var lastInput = Date.now();

    function mark() { lastInput = Date.now(); }
    ['keydown', 'mousedown', 'mousemove', 'pointerdown', 'wheel', 'touchstart', 'scroll']
        .forEach(function (type) {
            window.addEventListener(type, mark, { capture: true, passive: true });
        });

    window.qaActivity = {
        /* Headers for an automatic request: `extra`, plus the passive flag once
           the page has been left alone. */
        headers: function (extra) {
            var h = {};
            if (extra) { for (var k in extra) { h[k] = extra[k]; } }
            if (Date.now() - lastInput > QUIET_AFTER_MS) { h['X-QA-Passive'] = '1'; }
            return h;
        },
        /* The server ended the session while the page sat idle: go to sign-in,
           which shows why, instead of leaving the last screen on display. */
        expired: function (response) {
            if (!response || response.status !== 401) { return false; }
            window.location.href = response.headers.get('X-QA-Login') || '/accounts/login/';
            return true;
        }
    };
})();

document.addEventListener('DOMContentLoaded', function() {
    // Sidebar toggle for mobile
    const sidebarToggle = document.getElementById('sidebarToggle');
    const sidebarClose = document.getElementById('sidebarClose');
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');

    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', function() {
            sidebar.classList.add('open');
            overlay.classList.add('active');
        });
    }

    function closeSidebar() {
        sidebar.classList.remove('open');
        overlay.classList.remove('active');
    }

    if (sidebarClose) sidebarClose.addEventListener('click', closeSidebar);
    if (overlay) overlay.addEventListener('click', closeSidebar);

    // Sidebar collapse toggle (desktop mini mode)
    const collapseBtn = document.getElementById('sidebarCollapse');
    if (collapseBtn && sidebar) {
        // Restore saved state
        if (localStorage.getItem('sidebar-collapsed') === 'true') {
            sidebar.classList.add('collapsed');
        }

        collapseBtn.addEventListener('click', function() {
            sidebar.classList.toggle('collapsed');
            const isCollapsed = sidebar.classList.contains('collapsed');
            localStorage.setItem('sidebar-collapsed', isCollapsed);
        });
    }

    /* Auto-dismiss confirmations; leave problems on screen.

       Every alert used to close itself after five seconds. Five is short for a
       confirmation that arrives with a whole new page -- "changes saved" was
       gone before the reader had finished looking at what changed -- and it is
       plainly wrong for an error, which vanished before it could be acted on.
       Confirmations now stay for ten seconds; warnings and errors stay until
       they are dismissed. */
    document.querySelectorAll('.alert-dismissible').forEach(function(alert) {
        if (alert.classList.contains('alert-danger') ||
            alert.classList.contains('alert-error') ||
            alert.classList.contains('alert-warning')) {
            return;
        }
        setTimeout(function() {
            var bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            bsAlert.close();
        }, 10000);
    });

    // Confirm before delete
    document.querySelectorAll('[data-confirm]').forEach(function(el) {
        el.addEventListener('click', function(e) {
            if (!confirm(el.dataset.confirm || 'Are you sure?')) {
                e.preventDefault();
            }
        });
    });
});

// CSRF token helper for AJAX
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

const csrftoken = getCookie('csrftoken');

function qaEscapeHtml(s) {
    // Quotes too: this text may be placed inside an attribute.
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
}

/**
 * Show a compact Bootstrap toast (bottom-right). Variants: success, error, warning, info, primary.
 */
window.qaToast = function (message, variant) {
    variant = variant || 'info';
    // Bootstrap's `text-bg-info` and `text-bg-warning` paint the toast in
    // #0dcaf0 and #ffc107 -- two colours that appear nowhere else in this
    // system, which uses #1a7b93, #12784a, #8a6300 and #b02a21. The toast now
    // takes the page's own surface with a rail and an icon in the semantic
    // colour, so the meaning is carried by the icon and the words as well as
    // the colour, and the text sits on white at full contrast.
    const themes = {
        success: { theme: 'success', icon: 'bi-check-circle-fill', role: 'status' },
        error:   { theme: 'danger',  icon: 'bi-x-circle-fill',     role: 'alert' },
        danger:  { theme: 'danger',  icon: 'bi-x-circle-fill',     role: 'alert' },
        warning: { theme: 'warning', icon: 'bi-exclamation-triangle-fill', role: 'status' },
        info:    { theme: 'info',    icon: 'bi-info-circle-fill',  role: 'status' },
        primary: { theme: 'info',    icon: 'bi-info-circle-fill',  role: 'status' },
    };
    const spec = themes[variant] || themes.info;
    const container = document.getElementById('qaToastContainer');
    if (!container || !message) {
        return;
    }
    let text = String(message).replace(/\s+/g, ' ').trim();
    if (text.length > 90) {
        text = text.slice(0, 87) + '…';
    }
    const el = document.createElement('div');
    el.className = 'toast border-0 mb-2 qa-toast-item qa-toast--' + spec.theme;
    // Only a failure interrupts. Every toast used to be role="alert", which is
    // assertive, so "4 file(s) uploaded" cut across whatever a screen-reader
    // user was listening to.
    el.setAttribute('role', spec.role);
    el.innerHTML =
        '<div class="qa-toast-row">' +
        '<i class="bi ' + spec.icon + ' qa-toast-icon" aria-hidden="true"></i>' +
        '<div class="toast-body">' +
        qaEscapeHtml(text) +
        '</div>' +
        '<button type="button" class="btn-close" data-bs-dismiss="toast" aria-label="Dismiss this message"></button>' +
        '</div>';
    container.appendChild(el);
    const t = new bootstrap.Toast(el, { autohide: true, delay: 4500 });
    el.addEventListener('hidden.bs.toast', function () {
        el.remove();
    });
    t.show();
};

document.addEventListener('click', function (e) {
    const trigger = e.target.closest('.js-qa-delete-confirm');
    if (!trigger) {
        return;
    }
    e.preventDefault();
    const url = trigger.getAttribute('data-qa-delete-url');
    const title = trigger.getAttribute('data-qa-delete-title') || 'this document';
    const body = document.getElementById('qaDeleteDocumentBody');
    const form = document.getElementById('qaDeleteDocumentForm');
    const modalEl = document.getElementById('qaDeleteDocumentModal');
    if (!url || !form || !modalEl || !body) {
        return;
    }
    body.textContent = 'Delete "' + title + '"? You can undo this for ten seconds afterwards.';
    form.action = url;
    if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
});

// A row action menu is pinned with position:fixed so the panel's overflow cannot
// clip it. The cost of leaving the flow is that scrolling the table underneath
// would slide the row out from under its own menu, so the menu closes on any
// scroll that does not come from inside it. Capture phase: a table scrolls in
// its own container, and those events do not bubble to the document.
document.addEventListener('scroll', function (e) {
    const open = document.querySelector('.qa-row-menu-toggle.show');
    if (!open || (e.target instanceof Element && e.target.closest('.qa-row-menu'))) {
        return;
    }
    if (typeof bootstrap !== 'undefined' && bootstrap.Dropdown) {
        bootstrap.Dropdown.getOrCreateInstance(open).hide();
    }
}, true);

// Thousands separators for headline numbers (they used to count up; see below).
//
// Handles both number styles in the system:
//   .stat-value               - shared stat-card component (AI Processing, etc.),
//                               target read from the element's own text
//   .nx-num[data-countup]     - dashboard KPI cards, target read from the attribute
//
// The dashboard used to carry its own byte-identical copy of this routine inline.
(function () {
    function animate(el, target) {
        // The number is shown, not counted up to.
        //
        // These figures used to ease from zero over 900ms, so for most of a
        // second a card read "57" directly above its own caption saying "58 of
        // 58 processed by AI", while the sidebar, the donut and the calendar
        // all said 58. Anyone looking at the page as it opened saw the dashboard
        // contradict itself, with no way to tell the figure was mid-flight; a
        // screenshot caught it for good. requestAnimationFrame is also paused in
        // a background tab, which could leave the wrong number on screen
        // indefinitely. The server renders the true value -- this only adds the
        // thousands separators.
        el.textContent = Math.round(target).toLocaleString();
    }

    function initCountUp() {
        document.querySelectorAll('.stat-value').forEach(function (el) {
            if (el.dataset.countupDone) { return; }
            var raw = (el.textContent || '').trim().replace(/,/g, '');
            if (!/^\d+$/.test(raw)) { return; }
            el.dataset.countupDone = '1';
            animate(el, parseInt(raw, 10));
        });

        document.querySelectorAll('.nx-num[data-countup]').forEach(function (el) {
            if (el.dataset.countupDone) { return; }
            el.dataset.countupDone = '1';
            animate(el, parseFloat(el.getAttribute('data-countup')) || 0);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initCountUp);
    } else {
        initCountUp();
    }
})();

/**
 * Give a scroll panel whatever vertical space is actually left below it.
 *
 * The repository table was capped with `min(78vh, 100vh - 240px)`, a rule that
 * cannot know where on the page the panel starts. On a 900px viewport the panel
 * began 542px down, so a 660px panel ran 302px past the fold: the table looked
 * about five rows tall and the whole page scrolled as well as the table.
 *
 * Measuring the panel's own position and filling the remainder means the table
 * ends at the bottom of the window, scrolls internally, and the page itself does
 * not need a second scrollbar. Opt in with `data-fill-viewport`; the CSS
 * max-height stays as the fallback if this never runs.
 */
(function () {
    'use strict';

    // Below this a panel is not worth showing; a very short window scrolls the
    // page instead, which is the lesser evil.
    var MIN_HEIGHT = 280;

    function sizePanels() {
        document.querySelectorAll('[data-fill-viewport]').forEach(function (el) {
            // Cleared first so the stylesheet's own value can be read back, and
            // so a previous pass cannot feed its answer into the next one.
            el.style.maxHeight = '';

            var cssMax = parseFloat(window.getComputedStyle(el).maxHeight);
            if (!isFinite(cssMax)) { cssMax = 0; }

            var scrollY = window.pageYOffset || document.documentElement.scrollTop || 0;
            var rect = el.getBoundingClientRect();
            var top = rect.top + scrollY;
            var bottom = rect.bottom + scrollY;
            var tail = Math.max(0, document.documentElement.scrollHeight - bottom);
            var available = window.innerHeight - top - tail;

            // The panel ends at the bottom of the window.
            //
            // This was previously grow-only, letting the panel run past the fold
            // so the page scrolled as well as the table. That is what allowed the
            // sticky header to be scrolled away: the header sticks to the *panel*,
            // so once the page scrolls, the panel travels up and takes the header
            // with it. Ending at the fold means the page has nothing to scroll and
            // the header cannot leave.
            //
            // The earlier objection to this -- that it made the table shorter --
            // was true when rows were up to 105px tall and only a couple fitted.
            // Rows are a uniform 52px now, so fitting the window costs a row or
            // two of at-rest height and buys a header that is always on screen.
            var target = available;
            if (target < MIN_HEIGHT) { target = MIN_HEIGHT; }
            if (target > 0) { el.style.maxHeight = Math.round(target) + 'px'; }
        });
    }

    var pending = null;
    function schedule() {
        if (pending) { return; }
        pending = window.requestAnimationFrame(function () {
            pending = null;
            sizePanels();
        });
    }

    if (document.querySelector('[data-fill-viewport]')) {
        // The main container reserves 104px at the foot so the floating
        // assistant button never sits on top of content. A filled panel ends at
        // the window edge instead and scrolls internally, so that reservation is
        // dead space directly below the table -- worth more than a row of data.
        // The clearance moves inside the panel (see .is-filled in style.css).
        var main = document.querySelector('.main-content');
        if (main) { main.classList.add('has-filled-panel'); }
        document.querySelectorAll('[data-fill-viewport]').forEach(function (el) {
            el.classList.add('is-filled');
        });

        schedule();
        // requestAnimationFrame does not fire in a background tab, so the first
        // measurement also runs on a timer: a panel that opens unmeasured would
        // keep the CSS fallback height and overflow the fold.
        setTimeout(sizePanels, 0);
        window.addEventListener('load', schedule);
        window.addEventListener('resize', schedule);
        window.addEventListener('orientationchange', schedule);
        // The filter bar changes height when chips are added or a select wraps,
        // which moves the panel; re-measure when that happens.
        if (window.ResizeObserver) {
            var bar = document.querySelector('.repo-filter-bar');
            if (bar) { new ResizeObserver(schedule).observe(bar); }
        }
        window.qaSizeScrollPanels = sizePanels;
    }
})();
