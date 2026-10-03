/**
 * Notification bell: mark all read without leaving the current page.
 */
(function () {
    'use strict';

    document.addEventListener('click', function (e) {
        var btn = e.target.closest('.js-notif-mark-all-read');
        if (!btn) {
            return;
        }
        e.preventDefault();
        e.stopPropagation();

        var wrap = document.getElementById('qaNotifDropdown');
        var url = wrap ? wrap.getAttribute('data-mark-all-url') : '';
        if (!url) {
            return;
        }

        btn.disabled = true;
        var token = typeof getCookie === 'function' ? getCookie('csrftoken') : '';

        fetch(url, {
            method: 'POST',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': token || '',
            },
            credentials: 'same-origin',
        })
            .then(function (resp) {
                if (!resp.ok) {
                    throw new Error('mark_all_failed');
                }
                return resp.json();
            })
            .then(function () {
                if (wrap) {
                    // The bell's badge is a .qa-count-badge; looking for
                    // `.badge` found nothing, so the number stayed up after
                    // everything had been marked read.
                    if (typeof window.qaSetBadge === 'function') {
                        window.qaSetBadge('bell', 0);
                    } else {
                        var badge = wrap.querySelector('.notif-bell .qa-count-badge');
                        if (badge) {
                            badge.remove();
                        }
                    }
                    wrap.querySelectorAll('.dropdown-item.fw-semibold').forEach(function (item) {
                        item.classList.remove('fw-semibold');
                    });
                    var markAllWrap = document.getElementById('qaNotifMarkAllWrap');
                    if (markAllWrap) {
                        markAllWrap.remove();
                    }
                }
            })
            .catch(function () {
                if (typeof window.qaToast === 'function') {
                    window.qaToast('Could not mark notifications as read.', 'error');
                }
                btn.disabled = false;
            });
    });
})();
