/**
 * Edit document metadata in a modal (loads edit_panel.html via ?panel=1).
 */
(function () {
    'use strict';

    var modalEl = document.getElementById('qaDocEditModal');
    var bodyEl = document.getElementById('qaDocEditBody');
    var titleEl = document.getElementById('qaDocEditModalLabel');
    var subtitleEl = document.getElementById('qaDocEditSubtitle');
    var editUrlTemplate = modalEl
        ? (modalEl.getAttribute('data-edit-url-template') || '/documents/0/edit/')
        : '/documents/0/edit/';
    var loadToken = 0;

    function editUrl(docId) {
        return editUrlTemplate.replace('/0/', '/' + docId + '/');
    }

    function truncateTitle(text, maxLen) {
        var s = text || '';
        if (s.length <= maxLen) {
            return s;
        }
        return s.slice(0, maxLen - 1) + '\u2026';
    }

    function setLoading() {
        if (!bodyEl) {
            return;
        }
        bodyEl.innerHTML =
            '<div class="text-center py-5 text-muted">' +
            '<div class="spinner-border spinner-border-sm me-2" role="status"></div>Loading…</div>';
    }

    function setSubmitting(form, submitting) {
        var btn = form.querySelector('#qaDocEditSubmit');
        if (!btn) {
            return;
        }
        btn.disabled = submitting;
        var label = btn.querySelector('.qa-edit-submit-label');
        var spinner = btn.querySelector('.qa-edit-submit-spinner');
        if (label) {
            label.classList.toggle('d-none', submitting);
        }
        if (spinner) {
            spinner.classList.toggle('d-none', !submitting);
        }
    }

    function bindForm(container) {
        var form = container.querySelector('#qaDocEditForm');
        if (!form || form.dataset.qaBound === '1') {
            return;
        }
        form.dataset.qaBound = '1';
        form.addEventListener('submit', function (e) {
            e.preventDefault();
            setSubmitting(form, true);
            fetch(form.action, {
                method: 'POST',
                body: new FormData(form),
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin',
            })
                .then(function (resp) {
                    var ct = resp.headers.get('Content-Type') || '';
                    if (resp.ok && ct.indexOf('application/json') !== -1) {
                        return resp.json().then(function (data) {
                            if (typeof bootstrap !== 'undefined' && bootstrap.Modal && modalEl) {
                                bootstrap.Modal.getOrCreateInstance(modalEl).hide();
                            }
                            if (window.qaToast) {
                                window.qaToast(data.message || 'Document updated.', 'success');
                            }
                            document.dispatchEvent(
                                new CustomEvent('qa-document-updated', { detail: data.document || {} })
                            );
                        });
                    }
                    return resp.text().then(function (html) {
                        if (bodyEl) {
                            bodyEl.innerHTML = html;
                            bindForm(bodyEl);
                        }
                        if (window.qaToast) {
                            window.qaToast('Please fix the errors below.', 'warning');
                        }
                    });
                })
                .catch(function () {
                    if (window.qaToast) {
                        window.qaToast('Could not save changes. Please try again.', 'error');
                    }
                })
                .finally(function () {
                    setSubmitting(form, false);
                });
        });
    }

    function openEdit(docId, title) {
        if (!modalEl || !bodyEl || !docId) {
            return;
        }
        var token = ++loadToken;
        if (titleEl) {
            titleEl.textContent = 'Edit Document';
        }
        if (subtitleEl) {
            subtitleEl.textContent = title || '';
        }
        setLoading();
        if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
            bootstrap.Modal.getOrCreateInstance(modalEl).show();
        }
        fetch(editUrl(docId) + '?panel=1', {
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
                bindForm(bodyEl);
            })
            .catch(function () {
                if (token !== loadToken) {
                    return;
                }
                bodyEl.innerHTML =
                    '<div class="alert alert-danger mb-0" style="font-size:13px;">Could not load the edit form.</div>';
            });
    }

    if (modalEl) {
        modalEl.addEventListener('hidden.bs.modal', function () {
            loadToken += 1;
            if (bodyEl) {
                bodyEl.innerHTML = '';
            }
        });
    }

    document.addEventListener('click', function (e) {
        var trigger = e.target.closest('.js-qa-doc-edit');
        if (!trigger) {
            return;
        }
        e.preventDefault();
        openEdit(
            trigger.getAttribute('data-doc-id'),
            trigger.getAttribute('data-doc-title')
        );
    });

    document.addEventListener('qa-document-updated', function (e) {
        var doc = e.detail || {};
        if (!doc.id) {
            return;
        }
        var idStr = String(doc.id);

        document.querySelectorAll('.js-qa-doc-detail[data-doc-id="' + idStr + '"]').forEach(function (link) {
            if (doc.title) {
                link.setAttribute('data-doc-title', doc.title);
            }
        });

        document.querySelectorAll('tr.doc-row[data-doc-id="' + idStr + '"]').forEach(function (row) {
            var titleLink = row.querySelector('a.js-qa-doc-detail');
            if (titleLink && doc.title) {
                titleLink.textContent = truncateTitle(doc.title, 35);
                titleLink.setAttribute('data-doc-title', doc.title);
            }
            var yearCell = row.querySelector('.js-doc-year');
            if (yearCell && doc.year != null) {
                yearCell.textContent = doc.year;
            }
        });

        var detailModal = document.getElementById('qaDocDetailModal');
        if (
            detailModal &&
            detailModal.classList.contains('show') &&
            detailModal.dataset.activeDocId === idStr &&
            window.qaOpenDocDetail
        ) {
            var dl = document.getElementById('qaDocDetailDownload');
            window.qaOpenDocDetail(doc.id, doc.title, dl ? dl.href : null);
        }
    });

    window.qaOpenDocEdit = openEdit;
})();
