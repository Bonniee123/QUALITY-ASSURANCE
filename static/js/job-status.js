/**
 * Poll background jobs and show a non-blocking progress pill in the navbar.
 * Dispatches qaJobStatusUpdate / qaJobStatusFinished for page-level batch UI.
 */
(function () {
    'use strict';

    var POLL_MS = 2500;
    var pill = document.getElementById('qaJobStatusPill');
    var statusUrlTemplate = pill
        ? (pill.getAttribute('data-job-status-url-template') || '/documents/jobs/0/status/')
        : '/documents/jobs/0/status/';
    var repositoryUrl = pill
        ? (pill.getAttribute('data-repository-url') || '/documents/repository/')
        : '/documents/repository/';
    var trackedIds = new Set();
    var finishedIds = new Set();
    var pollTimer = null;

    function statusUrl(jobId) {
        return statusUrlTemplate.replace('/0/', '/' + jobId + '/');
    }

    function readStoredJobId() {
        try {
            var id = sessionStorage.getItem('qaActiveBulkJobId');
            if (id) {
                trackedIds.add(String(id));
            }
        } catch (e) { /* ignore */ }
    }

    function storeJobMeta(jobId, meta) {
        try {
            sessionStorage.setItem('qaActiveBulkJobId', String(jobId));
            if (meta && meta.filenames && meta.filenames.length) {
                sessionStorage.setItem('qaActiveBulkFilenames', JSON.stringify(meta.filenames));
            }
        } catch (e) { /* ignore */ }
    }

    function clearStoredJobMeta() {
        try {
            sessionStorage.removeItem('qaActiveBulkJobId');
            sessionStorage.removeItem('qaActiveBulkFilenames');
        } catch (e) { /* ignore */ }
    }

    function dispatchUpdate(job) {
        document.dispatchEvent(new CustomEvent('qaJobStatusUpdate', { detail: { job: job } }));
    }

    function dispatchFinished(job) {
        document.dispatchEvent(new CustomEvent('qaJobStatusFinished', { detail: { job: job } }));
    }

    function showPill(text) {
        if (!pill) {
            return;
        }
        pill.textContent = text;
        pill.classList.remove('d-none');
        pill.setAttribute('aria-hidden', 'false');
    }

    function hidePill() {
        if (!pill) {
            return;
        }
        pill.classList.add('d-none');
        pill.setAttribute('aria-hidden', 'true');
    }

    function formatJobLabel(job) {
        var total = job.total_count || 0;
        var done = job.processed_count || 0;
        if (job.job_type === 'bulk_upload_process' && total > 0) {
            if (job.status === 'pending') {
                return 'Preparing ' + total + ' file(s)…';
            }
            return 'Processing ' + total + ' file(s)… (' + done + '/' + total + ')';
        }
        return 'Processing your files…';
    }

    function notifyFinished(job) {
        var id = String(job.id);
        if (finishedIds.has(id)) {
            return;
        }
        finishedIds.add(id);
        trackedIds.delete(id);
        if (trackedIds.size === 0) {
            clearStoredJobMeta();
            hidePill();
            stopPolling();
        }
        dispatchFinished(job);
        if (window.qaToast) {
            if (job.status === 'completed') {
                window.qaToast('Processing complete', 'success');
            } else if (job.status === 'failed') {
                window.qaToast('Processing failed', 'error');
            }
        }
    }

    function pollJob(jobId) {
        var base = { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
        var qa = window.qaActivity;
        return fetch(statusUrl(jobId), {
            headers: qa ? qa.headers(base) : base,
            credentials: 'same-origin',
        }).then(function (resp) {
            if (qa && qa.expired(resp)) { return null; }
            if (!resp.ok) {
                trackedIds.delete(String(jobId));
                return null;
            }
            return resp.json();
        });
    }

    function poll() {
        if (trackedIds.size === 0) {
            hidePill();
            clearStoredJobMeta();
            stopPolling();
            return;
        }
        var ids = Array.from(trackedIds);
        Promise.all(ids.map(pollJob))
            .then(function (results) {
                var activeJobs = [];
                results.forEach(function (job) {
                    if (!job) {
                        return;
                    }
                    dispatchUpdate(job);
                    if (job.status === 'completed' || job.status === 'failed') {
                        notifyFinished(job);
                    } else {
                        activeJobs.push(job);
                    }
                });
                if (activeJobs.length === 0) {
                    if (trackedIds.size === 0) {
                        hidePill();
                        clearStoredJobMeta();
                        stopPolling();
                    }
                    return;
                }
                showPill(formatJobLabel(activeJobs[0]));
            })
            .catch(function () { /* silent */ });
    }

    function startPolling() {
        if (pollTimer) {
            poll();
            return;
        }
        poll();
        pollTimer = setInterval(poll, POLL_MS);
    }

    function stopPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    if (pill) {
        pill.addEventListener('click', function () {
            window.location.href = repositoryUrl;
        });
    }

    window.qaJobStatus = {
        trackJob: function (jobId, meta) {
            if (!jobId) {
                return;
            }
            trackedIds.add(String(jobId));
            storeJobMeta(jobId, meta || {});
            startPolling();
            pollJob(jobId).then(function (job) {
                if (job) {
                    dispatchUpdate(job);
                }
            });
        },
        fetchJob: pollJob,
        refresh: poll,
        getStoredJobId: function () {
            try {
                return sessionStorage.getItem('qaActiveBulkJobId');
            } catch (e) {
                return null;
            }
        },
        clearStoredJob: clearStoredJobMeta,
    };

    readStoredJobId();
    if (trackedIds.size > 0) {
        startPolling();
    }
})();
