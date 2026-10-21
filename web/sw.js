/* Service worker: la app abre sin conexion con los ultimos datos descargados.
   - Interfaz (html, css, js, iconos): primero cache, se actualiza en segundo plano.
   - Datos (data/*.json): primero red, y si no hay conexion, lo ultimo guardado.
   - /api/*: nunca se cachea (modo local). */
const VERSION = "esoferta-v5";
const INTERFAZ = [
  "./", "index.html", "app.css", "app.js", "manifest.webmanifest",
  "icons/icon.svg", "icons/icon-192.png", "icons/icon-512.png",
  "fonts/geist-normal.woff2", "fonts/geist-mono-normal.woff2",
  "fonts/instrument-serif-italic.woff2", "fonts/instrument-serif-normal.woff2",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(INTERFAZ)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((claves) => Promise.all(claves.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.includes("/api/")) return;

  if (url.pathname.includes("/data/")) {
    e.respondWith(
      fetch(e.request)
        .then((r) => {
          const copia = r.clone();
          caches.open(VERSION).then((c) => c.put(e.request, copia));
          return r;
        })
        .catch(() => caches.match(e.request)),
    );
    return;
  }

  e.respondWith(
    caches.match(e.request, { ignoreSearch: true }).then((guardada) => {
      const red = fetch(e.request)
        .then((r) => {
          if (r.ok) {
            const copia = r.clone();
            caches.open(VERSION).then((c) => c.put(e.request, copia));
          }
          return r;
        })
        .catch(() => guardada);
      return guardada || red;
    }),
  );
});
