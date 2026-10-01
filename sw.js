const CACHE = 'flora-atacama-v6', TILES = 'flora-atacama-tiles', MAX_TILES = 1500;
// Modelo de fotos y motor ONNX: pesados, se guardan al primer uso y sobreviven a actualizaciones de la app.
// Al reentrenar el modelo, subir MODEL_CACHE para forzar la descarga nueva.
const MODEL_CACHE = 'flora-atacama-model-v1';
const ASSETS = ['./', './index.html', './identify.js', './vision.js', './lib/ort/ort.wasm.min.js', './species.json', './manifest.webmanifest', './icon.svg',
  './lib/leaflet.js', './lib/leaflet.css', './lib/images/marker-icon.png', './lib/images/marker-icon-2x.png', './lib/images/marker-shadow.png'];

self.addEventListener('install', e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting())));
self.addEventListener('activate', e => e.waitUntil(
  caches.keys().then(ks => Promise.all(ks.filter(k => ![CACHE, TILES, MODEL_CACHE].includes(k)).map(k => caches.delete(k)))).then(() => self.clients.claim())));

// Guarda las teselas del mapa que ya se vieron, para usarlas sin señal
async function tile(req) {
  const cache = await caches.open(TILES), hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) {
    await cache.put(req, res.clone());
    const keys = await cache.keys();
    for (const k of keys.slice(0, Math.max(0, keys.length - MAX_TILES))) await cache.delete(k);
  }
  return res;
}

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if (url.hostname === 'tile.openstreetmap.org') { e.respondWith(tile(e.request)); return; }
  if (url.origin !== location.origin) return;
  if (/\/(model|lib\/ort)\//.test(url.pathname) && !url.pathname.endsWith('ort.wasm.min.js')) {
    e.respondWith(caches.open(MODEL_CACHE).then(async c => {
      const hit = await c.match(e.request);
      if (hit) return hit;
      const res = await fetch(e.request);
      if (res.ok) e.waitUntil(c.put(e.request, res.clone()));  // no bloquear la barra de progreso
      return res;
    }));
    return;
  }
  // Catálogo: red primero para recibir actualizaciones; caché si no hay señal
  if (url.pathname.endsWith('/species.json')) {
    e.respondWith(fetch(e.request).then(r => { const c = r.clone(); caches.open(CACHE).then(x => x.put(e.request, c)); return r; })
      .catch(() => caches.match(e.request)));
    return;
  }
  e.respondWith(caches.match(e.request).then(x => x || fetch(e.request)));
});
