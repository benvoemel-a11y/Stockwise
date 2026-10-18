// Filer – offline verfügbar. Bei jedem Update VERSION erhöhen.
const VERSION = "filer-v7";
const FILES = ["./", "index.html", "manifest.json", "apple-touch-icon.png", "icon-192.png", "icon-512.png", "icon-1024.png"];
self.addEventListener("install", e => { e.waitUntil(caches.open(VERSION).then(c => c.addAll(FILES))); self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VERSION).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
// Erst Netz (damit Updates ankommen), sonst Cache (offline)
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  e.respondWith(fetch(e.request).then(r => {
    const copy = r.clone(); caches.open(VERSION).then(c => c.put(e.request, copy)); return r;
  }).catch(() => caches.match(e.request, { ignoreSearch: true }).then(r => r || caches.match("index.html"))));
});
