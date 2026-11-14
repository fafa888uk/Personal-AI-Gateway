/* Minimal service worker for Personal AI Gateway (PWA shell).
 * - Cache-first for same-origin static assets (/_next/static, icons).
 * - Network-first for /api and navigation (never serve stale chat data).
 * - skipWaiting + clients.claim on activate; SKIP_WAITING message handler.
 * Versioned cache name: bump CACHE_NAME when the shell changes.
 */
const CACHE_NAME = "pag-v1";
const STATIC_PREFIXES = ["/_next/static/", "/icon-180.png", "/icon.svg", "/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(["/icon.svg", "/manifest.webmanifest"])).catch(() => undefined),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))),
    ).then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Network-first: API calls and navigations must always be fresh.
  if (url.pathname.startsWith("/api") || request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() => caches.match(request)),
    );
    return;
  }

  // Cache-first for versioned same-origin static assets.
  if (STATIC_PREFIXES.some((prefix) => url.pathname.startsWith(prefix))) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        });
      }),
    );
  }
});
