// Reconocimiento de fotos en el dispositivo (sin conexión una vez descargado).
// model/vision.onnx: codificador de imagen → embedding normalizado.
// model/head.json: clasificador lineal entrenado con fotos GBIF/iNaturalist de las especies del catálogo.
(function (root) {
  'use strict';
  const MODEL = 'model/vision.onnx', HEAD = 'model/head.json';
  let session = null, head = null, loading = null;

  // `expected`: tamaño descomprimido. No usar content-length: el hosting puede enviar el archivo comprimido (gzip)
  // y el navegador entrega más bytes de los que indica la cabecera.
  async function fetchWithProgress(url, expected, onProgress) {
    const r = await fetch(url);
    if (!r.ok) throw Error(`No se pudo descargar ${url} (${r.status})`);
    if (!r.body) return new Uint8Array(await r.arrayBuffer());
    const reader = r.body.getReader(), chunks = [];
    let got = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value); got += value.length;
      if (expected) onProgress?.(Math.min(1, got / expected));
    }
    const buf = new Uint8Array(got);
    let at = 0;
    for (const c of chunks) { buf.set(c, at); at += c.length; }
    return buf;
  }

  function load(onProgress) {
    if (loading) return loading;
    loading = (async () => {
      if (!root.ort) throw Error('Motor ONNX no disponible');
      ort.env.wasm.wasmPaths = new URL('lib/ort/', location.href).href;
      ort.env.wasm.numThreads = root.crossOriginIsolated ? Math.min(4, navigator.hardwareConcurrency || 1) : 1;
      head = await (await fetch(HEAD)).json();
      const bytes = await fetchWithProgress(MODEL, head.model_mb * 1e6, onProgress);
      session = await ort.InferenceSession.create(bytes, { executionProviders: ['wasm'], graphOptimizationLevel: 'all' });
      return head;
    })();
    loading.catch(() => { loading = null; });
    return loading;
  }

  // Redimensiona el lado corto a `size` y recorta el centro, como en el entrenamiento
  function tensorFrom(img, flip) {
    const n = head.input_size, c = document.createElement('canvas');
    c.width = c.height = n;
    const g = c.getContext('2d', { willReadFrequently: true });
    g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
    const k = n / Math.min(img.width, img.height), w = img.width * k, h = img.height * k;
    if (flip) { g.translate(n, 0); g.scale(-1, 1); }
    g.drawImage(img, (n - w) / 2, (n - h) / 2, w, h);
    const px = g.getImageData(0, 0, n, n).data, out = new Float32Array(3 * n * n), [m0, m1, m2] = head.mean, [s0, s1, s2] = head.std;
    for (let i = 0, j = 0; i < px.length; i += 4, j++) {
      out[j] = (px[i] / 255 - m0) / s0;
      out[j + n * n] = (px[i + 1] / 255 - m1) / s1;
      out[j + 2 * n * n] = (px[i + 2] / 255 - m2) / s2;
    }
    return new ort.Tensor('float32', out, [1, 3, n, n]);
  }

  function softmax(z, T) {
    const m = Math.max(...z), e = z.map(v => Math.exp((v - m) / T)), s = e.reduce((a, b) => a + b, 0);
    return e.map(v => v / s);
  }

  async function embed(img, flip) {
    const out = await session.run({ [session.inputNames[0]]: tensorFrom(img, flip) });
    return out[session.outputNames[0]].data;
  }

  // Devuelve la probabilidad por clase (promedio de la foto y su espejo)
  async function classifyImage(img) {
    const probs = [];
    for (const flip of [false, true]) {
      const e = await embed(img, flip);
      const z = head.W.map((row, k) => row.reduce((t, w, i) => t + w * e[i], head.b[k]));
      probs.push(softmax(z, head.temperature));
    }
    return probs[0].map((p, k) => (p + probs[1][k]) / 2);
  }

  function imageFrom(src) {
    return new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = () => rej(Error('Foto ilegible')); im.src = src; });
  }

  // Varias fotos de la misma planta: se multiplican las evidencias (media geométrica)
  async function classify(photoSrcs) {
    await load();
    const logs = new Array(head.classes.length).fill(0);
    for (const src of photoSrcs) {
      const p = await classifyImage(await imageFrom(src));
      p.forEach((v, k) => logs[k] += Math.log(v + 1e-6) / photoSrcs.length);
    }
    const p = softmax(logs, 1);
    const bySpecies = {};
    head.classes.forEach((c, k) => { for (const id of c.species_ids) bySpecies[id] = p[k]; });
    const top = p.map((v, k) => [v, head.classes[k]]).sort((a, b) => b[0] - a[0]).slice(0, 3);
    return { bySpecies, neutral: 1 / head.classes.length, top: top.map(([v, c]) => ({ p: v, name: c.name, species_ids: c.species_ids })) };
  }

  async function isCached() {
    try { return !!(await caches.match(MODEL)); } catch { return false; }
  }

  root.FloraVision = { load, classify, isCached, get ready() { return !!session; }, get info() { return head; } };
})(typeof self !== 'undefined' ? self : globalThis);
