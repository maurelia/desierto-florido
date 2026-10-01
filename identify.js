// Motor de identificación del Desierto Florido.
// Puntaje aproximadamente bayesiano:  P(S | M, G, T, I) ∝ P(M|S) · P(G|S) · P(T|S) · P(I|S) · P(S)
//   M = respuestas morfológicas/hábitat, G = latitud GPS vs. rango de distribución,
//   T = mes vs. perfil de floración (iNaturalist, corregido por esfuerzo), I = clasificador de fotos en el dispositivo (vision.js).
// Un rasgo desconocido nunca descarta: se trata con la tasa esperada del resto del catálogo.
(function (root) {
  'use strict';

  const QUESTIONS = [
    { key: 'colors', short: 'Color', label: '¿De qué color es la flor?', hint: 'Color dominante de los pétalos. Puedes tocar la foto para sugerirlo.',
      options: [['blanco', 'Blanco', '#f7f7f2'], ['amarillo', 'Amarillo', '#f2c230'], ['naranjo', 'Naranjo', '#ef8a2e'], ['rojo', 'Rojo', '#c9302c'],
        ['rosado', 'Rosado / fucsia', '#e0529c'], ['morado', 'Morado / lila', '#8e5cc4'], ['azul', 'Azul / celeste', '#4f8fd6'], ['verde', 'Verde / café', '#7d8b4a']] },
    { key: 'flower_type', short: 'Flor', label: '¿Cómo es la flor?', hint: 'Cuenta pétalos (o tépalos) y mira su forma.',
      options: [['trimera', '3 o 6 pétalos (tipo lirio)'], ['cruz4', '4 pétalos en cruz'], ['libres5', '5 pétalos'], ['muchos', 'Muchos pétalos (tipo cactus)'],
        ['tubo', 'Campana, tubo o embudo'], ['cabezuela', 'Cabezuela: muchas florcitas juntas (margarita, pompón)'], ['irregular', 'Irregular / amariposada']] },
    { key: 'growth', short: 'Planta', label: '¿Qué tipo de planta es?', hint: 'Porte general.',
      options: [['hierba', 'Hierba (tallos blandos)'], ['arbusto', 'Arbusto o subarbusto (base leñosa)'], ['cactus', 'Cactus'], ['parasita', 'Parásita, sin hojas verdes']] },
    { key: 'habit', short: 'Crecimiento', label: '¿Cómo crece?', hint: '',
      options: [['erecta', 'Erguida'], ['rastrera', 'Rastrera, pegada al suelo'], ['trepadora', 'Trepadora o enredada en otras plantas']] },
    { key: 'geophyte', short: 'Geófita', label: '¿Brota de un bulbo o tubérculo?', hint: 'Hojas basales tipo lirio/cebolla que salen directo del suelo. No desentierres la planta.',
      options: [['si', 'Sí, parece geófita'], ['no', 'No']] },
    { key: 'succulent', short: 'Carnosa', label: '¿Hojas o tallos gruesos y jugosos?', hint: 'Suculentos, carnosos.', positiveOnly: true,
      options: [['si', 'Sí, carnosos'], ['no', 'No, delgados']] },
    { key: 'spiny', short: 'Espinas', label: '¿Tiene espinas?', hint: '', positiveOnly: true, options: [['si', 'Sí'], ['no', 'No']] },
    { key: 'zone', short: 'Zona', label: '¿Dónde está la planta?', hint: '',
      options: [['costa', 'Cerca de la costa, dunas o litoral'], ['interior', 'Interior, cerros o quebradas']] },
    { key: 'cycle', short: 'Ciclo', label: '¿Anual o perenne?', hint: 'Solo si lo sabes: perennes suelen tener base leñosa o restos de años anteriores.',
      options: [['anual', 'Anual'], ['perenne', 'Perenne']] },
  ];
  const QMAP = Object.fromEntries(QUESTIONS.map(q => [q.key, q]));

  // Confusiones plausibles en terreno (respuesta del usuario vs. valor de ficha)
  const CONFUSION = {
    colors: { rosado: { morado: .45, rojo: .35, blanco: .15 }, morado: { rosado: .45, azul: .4 }, azul: { morado: .4 },
      rojo: { rosado: .35, naranjo: .35 }, naranjo: { rojo: .35, amarillo: .35 }, amarillo: { naranjo: .35, blanco: .1 }, blanco: { rosado: .15, amarillo: .1, azul: .1 } },
    flower_type: { libres5: { tubo: .3, trimera: .15, muchos: .1 }, tubo: { libres5: .3 }, trimera: { libres5: .15 },
      cabezuela: { muchos: .3 }, muchos: { cabezuela: .3 }, irregular: { tubo: .2 } },
    growth: { hierba: { arbusto: .35 }, arbusto: { hierba: .35 } },
    habit: { erecta: { trepadora: .1 }, rastrera: { trepadora: .3 }, trepadora: { rastrera: .3 } },
  };
  // Probabilidad mínima si el rasgo contradice la respuesta, según la procedencia del dato
  const EPS = { libro: .03, nombre: .08, por_verificar: .15 };
  // Piso de la verosimilitud de imagen: una foto sola nunca descarta por completo una especie
  const IMAGE_FLOOR = .003;

  function matchValue(key, answer, value) {
    const vals = Array.isArray(value) ? value : [value];
    let best = 0;
    for (const v of vals) {
      if (v === answer || (key === 'zone' && v === 'ambos')) return 1;
      best = Math.max(best, CONFUSION[key]?.[answer]?.[v] ?? 0);
    }
    return best;
  }

  function candidates(species) { return species.filter(s => !s.excluded_reason); }

  // Tasa de coincidencia esperada para especies sin el dato (media sobre las que sí lo tienen)
  function neutralRates(pool) {
    const rates = {};
    for (const q of QUESTIONS) {
      rates[q.key] = {};
      const known = pool.filter(s => s.traits?.[q.key] != null);
      for (const [a] of q.options) {
        rates[q.key][a] = q.positiveOnly ? (a === 'si' ? .35 : 1)
          : known.length ? known.reduce((t, s) => t + matchValue(q.key, a, s.traits[q.key]), 0) / known.length : .5;
      }
    }
    return rates;
  }

  function traitLikelihood(s, key, answer, rates) {
    const v = s.traits?.[key];
    if (v == null) return { L: rates[key][answer], status: 'unknown' };
    const m = QMAP[key].positiveOnly && answer === 'no' ? (v === 'si' ? 0 : 1) : matchValue(key, answer, v);
    const eps = EPS[s.trait_sources?.[key]] ?? .1;
    return { L: eps + (1 - eps) * m, status: m >= 1 ? 'ok' : m > 0 ? 'partial' : 'no', src: s.trait_sources?.[key] };
  }

  function geoLikelihood(s, lat) {
    if (lat == null) return null;
    if (s.lat_min == null) return { L: null, status: 'unknown' };
    const margin = .25, d = Math.max(0, s.lat_min - margin - lat, lat - (s.lat_max + margin));
    return d === 0 ? { L: 1, status: 'ok' } : { L: Math.max(.03, Math.exp(-d / .4)), status: d < .5 ? 'partial' : 'no', distanceDeg: d };
  }

  // Floración: perfil mensual (0-1, corregido por esfuerzo de observación). El piso depende de la solidez del dato:
  // observaciones anotadas "en flor" y abundantes pesan más que observaciones generales o escasas.
  function monthLikelihood(s, month) {
    if (month == null) return null;
    const prof = s.flowering_profile;
    if (!prof) return { L: null, status: 'unknown' };
    const floor = s.flowering_source !== 'inat_floracion' ? .35 : s.flowering_n >= 40 ? .08 : .15;
    const v = prof[month - 1];
    return { L: floor + (1 - floor) * v, status: v >= .5 ? 'ok' : v >= .2 ? 'partial' : 'no', value: v };
  }

  // ctx: { answers: {key: value}, lat, month (null = no filtrar por fecha), image: {bySpecies: {id: p}, neutral} }
  function score(species, ctx) {
    const pool = candidates(species), rates = neutralRates(pool), answers = ctx.answers || {};
    const geo = pool.map(s => geoLikelihood(s, ctx.lat));
    const knownGeo = geo.filter(g => g && g.L != null);
    const geoNeutral = knownGeo.length ? knownGeo.reduce((t, g) => t + g.L, 0) / knownGeo.length : 1;
    const months = pool.map(s => monthLikelihood(s, ctx.month)), knownMonths = months.filter(t => t && t.L != null);
    const monthNeutral = knownMonths.length ? knownMonths.reduce((t, m) => t + m.L, 0) / knownMonths.length : 1;
    const out = pool.map((s, i) => {
      let w = 1;
      const evidence = [];
      for (const [key, a] of Object.entries(answers)) {
        if (a == null || !QMAP[key]) continue;
        const r = traitLikelihood(s, key, a, rates);
        w *= r.L;
        evidence.push({ key, answer: a, value: s.traits?.[key], status: r.status, src: r.src });
      }
      const g = geo[i];
      if (g) { w *= g.L ?? geoNeutral; evidence.push({ key: 'geo', status: g.status, distanceDeg: g.distanceDeg }); }
      const t = months[i];
      if (t) { w *= t.L ?? monthNeutral; evidence.push({ key: 'month', status: t.status, value: t.value }); }
      if (ctx.image) {
        // P(I|S) ∝ probabilidad calibrada del clasificador; especie sin fotos de entrenamiento → valor neutro
        const p = ctx.image.bySpecies[s.id];
        w *= (p ?? ctx.image.neutral) + IMAGE_FLOOR;
        evidence.push({ key: 'image', p, status: p == null ? 'unknown' : p >= .25 ? 'ok' : p >= .05 ? 'partial' : 'no' });
      }
      return { species: s, weight: w, evidence };
    });
    const total = out.reduce((t, r) => t + r.weight, 0) || 1;
    for (const r of out) r.p = r.weight / total;
    return out.sort((a, b) => b.p - a.p);
  }

  function entropy(ps) { return -ps.reduce((h, p) => h + (p > 0 ? p * Math.log2(p) : 0), 0); }

  // Qué tan fácil es responder en terreno (pondera la ganancia de información)
  const EASE = { colors: 1.3, flower_type: 1, growth: 1, habit: .9, spiny: .9, succulent: .8, zone: .8, geophyte: .6, cycle: .35 };

  // Pregunta que más reduce la incertidumbre esperada (ganancia de información × facilidad)
  function rankQuestions(species, ctx) {
    const ranked = score(species, ctx), pool = ranked.map(r => r.species), prior = ranked.map(r => r.p);
    const rates = neutralRates(pool), h0 = entropy(prior), res = [];
    for (const q of QUESTIONS) {
      if (ctx.answers?.[q.key] != null) continue;
      // P(respuesta | especie), normalizada sobre las opciones; modelo de respuesta más nítido que el de puntaje
      const cond = pool.map(s => {
        const v = s.traits?.[q.key];
        const ls = q.options.map(([a]) => v == null ? rates[q.key][a]
          : .03 + (q.positiveOnly && a === 'no' ? +(v !== 'si') : matchValue(q.key, a, v)));
        const t = ls.reduce((x, y) => x + y, 0);
        return ls.map(l => l / t);
      });
      let expected = 0;
      q.options.forEach((_, j) => {
        const joint = prior.map((p, i) => p * cond[i][j]), pa = joint.reduce((x, y) => x + y, 0);
        if (pa > 0) expected += pa * entropy(joint.map(x => x / pa));
      });
      res.push({ key: q.key, gain: h0 - expected, priority: (h0 - expected) * (EASE[q.key] ?? 1) });
    }
    return res.sort((a, b) => b.priority - a.priority);
  }

  // Rasgos conocidos que no se superponen entre dos especies (sirven para distinguirlas)
  function differences(a, b) {
    const diffs = [];
    for (const q of QUESTIONS) {
      const va = a.traits?.[q.key], vb = b.traits?.[q.key];
      if (va == null || vb == null) continue;
      const sa = [].concat(va), sb = [].concat(vb);
      if (!sa.some(x => sb.includes(x))) diffs.push({ key: q.key, a: sa, b: sb });
    }
    if (a.lat_min != null && b.lat_min != null && (a.lat_max < b.lat_min || b.lat_max < a.lat_min)) diffs.push({ key: 'geo' });
    return diffs;
  }

  function optionLabel(key, value) {
    const q = QMAP[key];
    return [].concat(value).map(v => (q?.options.find(o => o[0] === v)?.[1] || v).replace(/ \(.*\)$/, '')).join(' / ');
  }

  // Clasifica un color RGB (0-255) en las categorías de la pregunta de color
  function classifyColor(r, g, b) {
    const mx = Math.max(r, g, b) / 255, mn = Math.min(r, g, b) / 255, d = mx - mn, v = mx, s = mx ? d / mx : 0;
    let h = 0;
    if (d) {
      const R = r / 255, G = g / 255, B = b / 255;
      h = mx === R ? 60 * (((G - B) / d) % 6) : mx === G ? 60 * ((B - R) / d + 2) : 60 * ((R - G) / d + 4);
      if (h < 0) h += 360;
    }
    if (v < .2) return { color: null, reason: 'Zona muy oscura: toca un pétalo iluminado' };
    if (s < .16 && v > .6) return { color: 'blanco' };
    if (s < .16) return { color: null, reason: 'Color grisáceo: toca el centro de un pétalo' };
    if (s < .45 && v > .7 && (h >= 300 || h < 20)) return { color: 'rosado' };
    const color = h < 14 ? 'rojo' : h < 38 ? (v < .55 && s > .5 ? 'verde' : 'naranjo') : h < 68 ? 'amarillo' : h < 160 ? 'verde'
      : h < 250 ? 'azul' : h < 292 ? 'morado' : h < 340 ? 'rosado' : 'rojo';
    return { color, h: Math.round(h), s: +s.toFixed(2), v: +v.toFixed(2) };
  }

  const api = { QUESTIONS, score, rankQuestions, differences, optionLabel, classifyColor, candidates };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.FloraID = api;
})(typeof self !== 'undefined' ? self : globalThis);
