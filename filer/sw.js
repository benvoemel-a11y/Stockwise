// Filer – offline verfügbar. Bei jedem Update VERSION erhöhen.
const VERSION = "filer-v16";
const FILES = ["./", "index.html", "manifest.json", "apple-touch-icon.png", "icon-192.png", "icon-512.png", "icon-1024.png"];
self.addEventListener("install", e => { e.waitUntil(caches.open(VERSION).then(c => c.addAll(FILES.map(f => new Request(f, { cache: "reload" }))))); self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VERSION).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
// Erst Netz (damit Updates ankommen), sonst Cache (offline).
// Der Zeitstempel umgeht GitHubs 10-Minuten-Zwischenspeicher, so kommt jede neue Version sofort an.
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  const fresh = url.origin === location.origin ? (url.searchParams.set("_", Date.now()), url.href) : e.request.url;
  e.respondWith(fetch(fresh, { cache: "no-store" }).then(r => {
    if (r.ok) { const copy = r.clone(); caches.open(VERSION).then(c => c.put(e.request, copy)); }
    return r;
  }).catch(() => caches.match(e.request, { ignoreSearch: true }).then(r => r || caches.match("index.html"))));
});
