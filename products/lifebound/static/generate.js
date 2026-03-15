// ═══════════════════════════════════════════════════════════════
// generate.js — Paso 6: Generar y descargar el PDF
// ═══════════════════════════════════════════════════════════════

import { getters, queries, actions }      from '/lifebound/static/state.js';
import { showLoad, hideLoad, toast,
         compressAllImages }              from '/lifebound/static/utils.js';
import { convertTransforms,
         uploadSessionPhotos,
         generateAlbumPDF }              from '/lifebound/static/api.js';
import { markDone }                       from '/lifebound/static/nav.js';

// ───────────────────────────────────────────────────────────────
// NOMBRES DE PATRÓN
// ───────────────────────────────────────────────────────────────

const PATTERN_NAMES = [
  'The Journey','Our Story','Milestones','Together',
  'Through the Years','A Life Shared','Moments','Side by Side',
  'Our Chapter','The Path','Building Together','Always',
  'Hand in Hand','Every Season','Home',
];

function _patternAlias(patternId) {
  let hash = 0;
  for (let i = 0; i < patternId.length; i++)
    hash = (hash * 31 + patternId.charCodeAt(i)) & 0xffffffff;
  return PATTERN_NAMES[Math.abs(hash) % PATTERN_NAMES.length];
}

// ───────────────────────────────────────────────────────────────
// INIT
// ───────────────────────────────────────────────────────────────

export function initGenerate() {
  document.getElementById('btnGenerate')
    ?.addEventListener('click', generatePDF);
}

// ───────────────────────────────────────────────────────────────
// SUMMARY
// ───────────────────────────────────────────────────────────────

export function buildSummary() {
  const data  = queries.summaryData();
  const total = queries.totalPdfPages();
  _setText('sumPhotos',    `${data.photos} fotos`);
  _setText('sumPages',     `${data.pages} páginas`);
  _setText('sumApplicant', data.applicant);
  _setText('sumPattern',   _patternAlias(data.pattern));
  _setText('sumLastPage',  total);
}

// ───────────────────────────────────────────────────────────────
// GENERAR PDF — flujo principal corregido
//
// Orden correcto según el backend:
//   1. Comprimir fotos
//   2. Subir fotos a la sesión  ← /api/session/photos (NUEVO)
//   3. Convertir transforms     ← /api/transform
//   4. Generar PDF              ← /api/generate
// ───────────────────────────────────────────────────────────────

export async function generatePDF() {
  const btnGenerate = document.getElementById('btnGenerate');
  if (btnGenerate) btnGenerate.disabled = true;

  try {
    // ── 1. Comprimir fotos ──────────────────────────────────
    showLoad('Comprimiendo fotos…', 'Optimizando imágenes para el PDF');

    const photoIdToFile = _buildPhotoIdToFileMap();
    const compressed    = await compressAllImages(photoIdToFile, getters.identityMap());

    // ── 2. Subir fotos a la sesión ──────────────────────────
    showLoad('Subiendo fotos…', 'Enviando imágenes al servidor');

    const { received } = await uploadSessionPhotos(getters.sessionId(), compressed);
    console.log(`[generate] ${received} fotos recibidas por el servidor`);

    // ── 3. Convertir transforms ─────────────────────────────
    showLoad('Convirtiendo ajustes…', 'Traduciendo posiciones de fotos para el motor PDF');

    const transformPayload = _buildTransformPayload();
    const { transforms: convertedTransforms } = await convertTransforms({
      transforms:   transformPayload,
      identity_map: getters.identityMap(),
      session_id:   getters.sessionId(),
    });

    // ── 4. Generar PDF ──────────────────────────────────────
    showLoad('Generando PDF…', 'Ensamblando tu álbum de evidencia USCIS');

    const payload  = _buildGeneratePayload(convertedTransforms);
    const pdfBlob  = await generateAlbumPDF(compressed, payload);
    _downloadBlob(pdfBlob);

    hideLoad();
    toast('¡Álbum descargado exitosamente! 🎉', 'success');
    markDone(6);

  } catch (err) {
    hideLoad();
    toast(`Error: ${err.message}`, 'error');
    console.error('[generate] Error:', err);
  } finally {
    if (btnGenerate) btnGenerate.disabled = false;
  }
}

// ───────────────────────────────────────────────────────────────
// BUILDERS
// ───────────────────────────────────────────────────────────────

function _buildTransformPayload() {
  const pattern = getters.pattern();
  const payload = [];
  (pattern?.plan ?? []).forEach(page => {
    (page.slots ?? []).forEach((slot, si) => {
      const slotEl = document.getElementById(`pvsl_${page.page}_${si}`);
      const rect   = slotEl
        ? slotEl.getBoundingClientRect()
        : { x: 0, y: 0, width: 0, height: 0 };
      payload.push({
        photo_id:       slot.photo_id,
        template:       page.template,
        slot_index:     si,
        device_dpr:     window.devicePixelRatio ?? 1,
        slot_rect_css:  { x: rect.x, y: rect.y, w: rect.width, h: rect.height },
        user_transform: getters.transform(slot.photo_id),
      });
    });
  });
  return payload;
}

function _buildPhotoIdToFileMap() {
  const pattern = getters.pattern();
  const map     = {};
  (pattern?.plan ?? []).forEach(page => {
    (page.slots ?? []).forEach(slot => {
      const file = getters.photoFile(slot.photo_id);
      if (file) map[slot.photo_id] = file;
    });
  });
  return map;
}

function _buildGeneratePayload(convertedTransforms) {
  const pattern  = getters.pattern();
  const intro    = getters.introData();
  const receipts = getters.receipts();

  // Construir "shared" con los nombres exactos que espera el backend
  const shared = {
    field_office_name:    intro.cover.office         || intro.letter.office || '',
    field_office_address: intro.letter.address       || intro.id.address    || '',
    attention:            intro.cover.attn           || '',
    applicant_name:       intro.cover.name           || intro.id.name       || '',
    spouse_name:          intro.cover.spouse         || intro.id.spouse     || '',
    address:              intro.letter.address       || intro.id.address    || '',
    n400_receipt:         _findReceipt(receipts, 'N-400'),
    i751_receipt:         _findReceipt(receipts, 'I-751'),
    interview_date:       intro.cover.interview_date || intro.id.interview_date || '',
    interview_time:       intro.cover.interview_time || intro.id.interview_time || '',
    applicant_number:     intro.id.a_number          || intro.letter.a_number   || '',
  };

  // "own" = questionnaire data (descripciones, fechas, ubicaciones por página)
  const own = getters.qData();

  return {
    plan:                 pattern.plan,
    shared,
    own,
    converted_transforms: convertedTransforms,
    session_id:           getters.sessionId(),
  };
}

/**
 * Busca el número de receipt de un form en cualquiera de las tres páginas.
 * Prioridad: cover → letter → id
 */
function _findReceipt(receipts, form) {
  return receipts.cover[form]
      ?? receipts.letter[form]
      ?? receipts.id[form]
      ?? '';
}

// ───────────────────────────────────────────────────────────────
// DESCARGA
// ───────────────────────────────────────────────────────────────

function _downloadBlob(blob) {
  const intro = getters.introData();
  const name  = (intro.cover.name || intro.id.name || 'album')
    .replace(/\s+/g, '_');
  const url = URL.createObjectURL(blob);
  const a   = document.createElement('a');
  a.href     = url;
  a.download = `USCIS_Album_${name}.pdf`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function _setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value ?? '—';
}