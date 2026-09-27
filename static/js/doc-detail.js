/**
 * Open full document details (metadata, AI, preview) in a modal.
 */
(function () {
    'use strict';

    var modalEl = document.getElementById('qaDocDetailModal');
    var bodyEl = document.getElementById('qaDocDetailBody');
    var titleEl = document.getElementById('qaDocDetailModalLabel');
    var subtitleEl = document.getElementById('qaDocDetailSubtitle');
    var panelUrlTemplate = modalEl
        ? (modalEl.getAttribute('data-panel-url-template') || '/documents/0/?panel=1')
        : '/documents/0/?panel=1';
    var loadToken = 0;
    var activeDocId = null;

    function panelUrl(docId) {
        return panelUrlTemplate.replace('/0/', '/' + docId + '/');
    }

    function setLoading() {
        if (!bodyEl) {
            return;
        }
        bodyEl.innerHTML =
            '<div class="text-center py-5 text-muted">' +
            '<div class="spinner-border spinner-border-sm me-2" role="status"></div>Loading…</div>';
    }

    // `downloadUrl` is accepted and ignored: doc-edit.js still passes it, and
    // the panel renders its own Download button from the document it loads.
    function openDetail(docId, title, downloadUrl) {  // eslint-disable-line no-unused-vars
        if (!modalEl || !bodyEl || !docId) {
            return;
        }
        activeDocId = docId;
        modalEl.dataset.activeDocId = docId;
        var token = ++loadToken;
        if (titleEl) {
            titleEl.textContent = 'Document Details';
        }
        if (subtitleEl) {
            subtitleEl.textContent = title || '';
        }
        setLoading();
        if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
            bootstrap.Modal.getOrCreateInstance(modalEl).show();
        }
        fetch(panelUrl(docId), {
            headers: { 'X-Requested-With': 'XMLHttpRequest', Accept: 'text/html' },
            credentials: 'same-origin',
        })
            .then(function (resp) {
                if (!resp.ok) {
                    throw new Error('load_failed');
                }
                return resp.text();
            })
            .then(function (html) {
                if (token !== loadToken) {
                    return;
                }
                bodyEl.innerHTML = html;
            })
            .catch(function () {
                if (token !== loadToken) {
                    return;
                }
                bodyEl.innerHTML =
                    '<div class="alert alert-danger mb-0" style="font-size:13px;">Could not load document details.</div>';
            });
    }

    /* Deciding a duplicate without being thrown out of the modal.

       "Mark as clear" and "Confirm duplicate" are ordinary forms: on the
       standalone document page, and with this script absent, they post and
       redirect exactly as before. Inside the modal that redirect closed the
       modal and dropped the reader on another page -- so here the post is made
       for them, the panel is reloaded in place, and the duplicate badge in the
       table behind the modal is repainted so the row does not keep saying
       "Needs review" after it has been reviewed. */
    function csrfToken(form) {
        var field = form.querySelector('[name=csrfmiddlewaretoken]');
        return field ? field.value : '';
    }

    function repaintRowBadge(docId, badgeHtml) {
        if (!docId || !badgeHtml) {
            return;
        }
        document.querySelectorAll('[data-qa-dup-badge="' + docId + '"]').forEach(function (cell) {
            cell.innerHTML = badgeHtml;
        });
    }

    function reloadPanel(docId) {
        if (!bodyEl || !docId) {
            return;
        }
        fetch(panelUrl(docId), {
            headers: { 'X-Requested-With': 'XMLHttpRequest', Accept: 'text/html' },
            credentials: 'same-origin',
        })
            .then(function (resp) { return resp.ok ? resp.text() : null; })
            .then(function (html) {
                if (html !== null && String(docId) === String(activeDocId)) {
                    bodyEl.innerHTML = html;
                }
            })
            .catch(function () {});
    }

    document.addEventListener('submit', function (e) {
        var form = e.target.closest('.js-qa-duplicate-decision');
        if (!form || !bodyEl || !bodyEl.contains(form)) {
            return;
        }
        e.preventDefault();
        var docId = form.getAttribute('data-doc-id') || activeDocId;
        form.querySelectorAll('button').forEach(function (b) { b.disabled = true; });

        fetch(form.getAttribute('action'), {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': csrfToken(form),
                Accept: 'application/json',
            },
            body: new FormData(form),
        })
            .then(function (resp) { return resp.ok ? resp.json() : null; })
            .then(function (data) {
                if (!data || !data.ok) {
                    throw new Error('decision_failed');
                }
                repaintRowBadge(docId, data.badge);
                if (window.qaToast) {
                    window.qaToast(data.message, 'success');
                }
                reloadPanel(docId);
            })
            .catch(function () {
                form.querySelectorAll('button').forEach(function (b) { b.disabled = false; });
                if (window.qaToast) {
                    window.qaToast('That decision could not be saved. Please try again.', 'error');
                }
            });
    });

    if (modalEl) {
        modalEl.addEventListener('hidden.bs.modal', function () {
            loadToken += 1;
            activeDocId = null;
            delete modalEl.dataset.activeDocId;
            if (bodyEl) {
                bodyEl.innerHTML = '';
            }
        });
    }

    document.addEventListener('click', function (e) {
        var trigger = e.target.closest('.js-qa-doc-detail');
        if (!trigger) {
            return;
        }
        e.preventDefault();
        openDetail(
            trigger.getAttribute('data-doc-id'),
            trigger.getAttribute('data-doc-title'),
            trigger.getAttribute('data-doc-download')
        );
    });

    window.qaOpenDocDetail = openDetail;
})();
