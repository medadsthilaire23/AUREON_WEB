// ═══════════════════════════════════════════════════════════════
// api.js — Capa de red: todos los fetch a /lifebound/api/*
//
// Responsabilidades:
//   - Centralizar las URLs de la API en un solo lugar
//   - Manejar errores HTTP de forma uniforme
//   - Exponer funciones con nombres de negocio, no de HTTP
//   - Inyectar el token Aureon en todos los requests
//
// NINGÚN otro módulo llama fetch() directamente.
// ═══════════════════════════════════════════════════════════════

// ───────────────────────────────────────────────────────────────
// BASE & HELPERS INTERNOS
// ───────────────────────────────────────────────────────────────

const BASE = '/lifebound/api';

/**
 * Devuelve el header Authorization con el token Aureon.
 * Si no hay token, devuelve objeto vacío (el backend devolverá 401).
 */
function _authHeader() {
  const token = localStorage.getItem('aureon_token');
  return token ? { 'Authorization': `Bearer ${token}` } : {};
}

/**
 * fetch con manejo de errores HTTP centralizado.
 * Inyecta automáticamente el token Aureon en cada request.
 *
 * @param {string} url
 * @param {RequestInit} [options={}]
 * @returns {Promise<any>} — JSON parseado
 */
async function _fetch(url, options = {}) {
  // Merge del header de auth con los headers existentes
  options.headers = {
    ..._authHeader(),
    ...(options.headers || {}),
  };

  const res = await fetch(url, options);

  if (!res.ok) {
    let message = `Error ${res.status}`;
    try {
      const body = await res.json();
      message = body.error ?? body.message ?? message;
    } catch { /* el body no era JSON, usar el status */ }
    throw new Error(message);
  }

  return res.json();
}

/**
 * fetch igual que _fetch pero devuelve el Response crudo.
 * Usado para la descarga del PDF (necesitamos el Blob, no JSON).
 */
async function _fetchRaw(url, options = {}) {
  // Merge del header de auth con los headers existentes
  options.headers = {
    ..._authHeader(),
    ...(options.headers || {}),
  };

  const res = await fetch(url, options);

  if (!res.ok) {
    let message = `Error ${res.status}`;
    try {
      const body = await res.json();
      message = body.error ?? body.message ?? message;
    } catch { /* ignorar */ }
    throw new Error(message);
  }

  return res;
}

const JSON_POST = body => ({
  method:  'POST',
  headers: { 'Content-Type': 'application/json' },
  body:    JSON.stringify(body),
});

// ───────────────────────────────────────────────────────────────
// SESSION
// ───────────────────────────────────────────────────────────────

/**
 * Crea una nueva sesión en el servidor.
 * @returns {Promise<{ session_id: string }>}
 */
export async function createSession() {
  return _fetch(`${BASE}/session/start`, JSON_POST({}));
}

// ───────────────────────────────────────────────────────────────
// PATTERN — calcular el patrón de páginas según cantidad de fotos
// ───────────────────────────────────────────────────────────────

/**
 * Calcula el patrón de álbum para un número de fotos y años.
 *
 * @param {{ photo_count: number, num_years: number }} params
 * @returns {Promise<PatternResponse>}
 *
 * @typedef {Object} PatternResponse
 * @property {string} pattern_id
 * @property {number} photo_pages
 * @property {number} total_pages
 * @property {string} range_type
 * @property {Object[]} plan
 */
export async function fetchPattern({ photo_count, num_years }) {
  return _fetch(`${BASE}/pattern`, JSON_POST({ photo_count, num_years }));
}

// ───────────────────────────────────────────────────────────────
// SLOTS — asignar fotos a slots del patrón
// ───────────────────────────────────────────────────────────────

/**
 * Asigna fotos a los slots del patrón calculado.
 *
 * @param {{ pattern: PatternResponse, year_grouping: Object, dpr: number }} params
 * @returns {Promise<SlotsResponse>}
 *
 * @typedef {Object} SlotsResponse
 * @property {Object[]} plan          — igual que PatternResponse.plan pero con photo_id en cada slot
 * @property {Object}   identity_map  — { photo_id: { w, h } }
 * @property {string}   pattern_id
 * @property {number}   photo_pages
 * @property {number}   total_pages
 * @property {string}   range_type
 */
export async function fetchSlots({ pattern, year_grouping, dpr }) {
  return _fetch(`${BASE}/slots`, JSON_POST({
    pattern,
    year_grouping,
    dpr: dpr ?? window.devicePixelRatio ?? 1,
  }));
}

// ───────────────────────────────────────────────────────────────
// TRANSFORM — convertir transforms del CSS al espacio del PDF
// ───────────────────────────────────────────────────────────────

/**
 * Envía los transforms de zoom/pan del usuario y recibe
 * los equivalentes para el motor PDF del servidor.
 *
 * @param {{ transforms: Object[], identity_map: Object, session_id: string }} params
 * @returns {Promise<{ transforms: Object[] }>}
 */
export async function convertTransforms({ transforms, identity_map, session_id }) {
  return _fetch(`${BASE}/transform`, JSON_POST({
    transforms,
    identity_map,
    session_id,
  }));
}

// ───────────────────────────────────────────────────────────────
// GENERATE — generar el PDF final
// ───────────────────────────────────────────────────────────────

/**
 * Envía todas las fotos comprimidas + payload de datos
 * y recibe el PDF como Blob para descarga.
 *
 * @param {Object} compressedPhotos  — { pid: Blob }
 * @param {Object} payload           — datos del álbum (ver monolito generatePDF)
 * @returns {Promise<Blob>}          — PDF listo para descargar
 */
export async function generateAlbumPDF(compressedPhotos, payload) {
  const fd = new FormData();

  // session_id como campo separado — el backend lo lee con request.form.get()
  fd.append('session_id', payload.session_id ?? '');

  // Adjuntar cada foto comprimida como archivo JPEG
  Object.entries(compressedPhotos).forEach(([pid, blob]) => {
    fd.append('photos', blob, `${pid}.jpg`);
  });

  // El resto del payload va como JSON
  const payloadWithoutSid = { ...payload };
  delete payloadWithoutSid.session_id;
  fd.append('payload', JSON.stringify(payloadWithoutSid));

  // Para FormData NO poner Content-Type — el browser lo pone solo con el boundary
  // pero SÍ inyectar el token de auth
  const res = await _fetchRaw(`${BASE}/generate`, {
    method: 'POST',
    body:   fd,
  });

  return res.blob();
}

// ───────────────────────────────────────────────────────────────
// HELPERS DE ALTO NIVEL
// Orquestan múltiples llamadas API — usados por grouping.js
// ───────────────────────────────────────────────────────────────

/**
 * Flujo completo de preparación del álbum:
 *   1. Crear sesión
 *   2. Calcular patrón
 *   3. Asignar fotos a slots
 *
 * @param {{ photoCount: number, activeYears: string[], yearCounts: Object }} params
 * @returns {Promise<{ sessionId: string, slots: SlotsResponse }>}
 */
export async function prepareAlbum({ photoCount, activeYears, yearCounts }) {
  // 1. Sesión
  const { session_id } = await createSession();

  // 2. Patrón
  const pattern = await fetchPattern({
    photo_count: photoCount,
    num_years:   activeYears.length,
  });

  // 3. Slots
  const slots = await fetchSlots({
    pattern,
    year_grouping: yearCounts,
    dpr: window.devicePixelRatio ?? 1,
  });

  return { sessionId: session_id, slots };
}

// ───────────────────────────────────────────────────────────────
// SESSION PHOTOS — subir fotos comprimidas a la sesión
// Paso obligatorio antes de /api/generate
// ───────────────────────────────────────────────────────────────

/**
 * Sube las fotos comprimidas al servidor y las asocia a la sesión.
 * El servidor las almacena en memoria hasta que /api/generate las use.
 *
 * @param {string} sessionId
 * @param {Object} compressedPhotos — { pid: Blob }
 * @returns {Promise<{ received: number }>}
 */
export async function uploadSessionPhotos(sessionId, compressedPhotos) {
  const fd = new FormData();
  fd.append('session_id', sessionId);

  Object.entries(compressedPhotos).forEach(([pid, blob]) => {
    fd.append('photos', blob, `${pid}.jpg`);
  });

  return _fetch(`${BASE}/session/photos`, {
    method: 'POST',
    body:   fd,
  });
}