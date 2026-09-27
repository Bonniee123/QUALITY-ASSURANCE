/**
 * Open document preview in a Bootstrap modal (iframe) instead of a new tab.
 */
(function () {
    'use strict';

    var modalEl = document.getElementById('qaDocPreviewModal');
    var frameEl = document.getElementById('qaDocPreviewFrame');
    var titleEl = document.getElementById('qaDocPreviewModalLabel');
    var downloadEl = document.getElementById('qaDocPreviewDownload');

    if (!modalEl || !frameEl) {
        return;
    }

    function openPreview(url, title, downloadUrl) {
        if (!url) {
            return;
        }
        if (titleEl) {
            titleEl.textContent = title || 'Document Preview';
        }
        if (downloadEl) {
            if (downloadUrl) {
                downloadEl.href = downloadUrl;
                downloadEl.classList.remove('d-none');
            } else {
                downloadEl.classList.add('d-none');
            }
        }
        frameEl.src = url;
        if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
            bootstrap.Modal.getOrCreateInstance(modalEl).show();
        }
    }

    modalEl.addEventListener('hidden.bs.modal', function () {
        frameEl.src = 'about:blank';
    });

    document.addEventListener('click', function (e) {
        var trigger = e.target.closest('.js-qa-doc-preview');
        if (!trigger) {
            return;
        }
        e.preventDefault();
        openPreview(
            trigger.getAttribute('data-qa-preview-url'),
            trigger.getAttribute('data-qa-preview-title'),
            trigger.getAttribute('data-qa-download-url')
        );
    });

    window.qaOpenDocPreview = openPreview;
})();
