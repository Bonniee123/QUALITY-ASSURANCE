/*
 * The QA Archiving System's service worker. One job: when a page cannot be
 * loaded because there is no connection, show the offline page in its place
 * instead of the browser's own error.
 *
 * Network first, always. Nothing the app shows is cached -- documents, lists
 * and dashboards are only ever fetched live -- and only page navigations are
 * touched: downloads, form posts, API calls and static files pass straight
 * through. The offline page is stored once, at install.
 */
const CACHE = 'qa-offline-{{ version }}';
const OFFLINE_URL = '/offline/';

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE).then((cache) => cache.add(new Request(OFFLINE_URL, { cache: 'reload' })))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(keys.filter((k) => k.startsWith('qa-offline-') && k !== CACHE).map((k) => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (event) => {
    const request = event.request;
    if (request.mode !== 'navigate' || request.method !== 'GET') {
        return;
    }
    event.respondWith(
        fetch(request).catch(() => caches.open(CACHE).then((cache) => cache.match(OFFLINE_URL)))
    );
});
