// ═══════════════════════════════════════════════════════════════
// store.js — Estado centralizado de Lifebound
//
// REGLA: Nadie toca _state directamente desde afuera.
//        Todo acceso es a través de getters y actions.
// ═══════════════════════════════════════════════════════════════

const _state = {
  // ── Paso 1: Fotos ──────────────────────────────────────────
  validFiles: [],           // File[]

  // ── Paso 2: Info del solicitante ───────────────────────────
  introData: {
    cover:  { name:'', spouse:'', interview_date:'', interview_time:'', office:'', attn:'', title:'', _attn_auto:true, _title_auto:true },
    letter: { name:'', spouse:'', address:'', office:'', closing:'Thank you for reviewing these applications and supporting documents.', sig_applicant:'', sig_spouse:'' },
    id:     { name:'', spouse:'', a_number:'', address:'', interview_date:'', interview_time:'' },
  },
  receipts: {
    cover:  {},  // { 'N-400': 'IOE000...', 'I-751': '' }
    letter: {},
    id:     {},
  },
  docState: {
    letter: [],  // [{ si, ii, checked, textVal }]
    id:     [],
  },

  // ── Paso 3: Agrupación por año ─────────────────────────────
  yearGrouping: {},         // { '2022': [0, 3, 7], '2023': [1, 2] }

  // ── Pasos 4-5: Patrón y cuestionario ──────────────────────
  currentPattern:  null,   // respuesta de /api/slots
  identityMap:     {},     // { 'y2022-f1': { w, h } }
  photoIdToFile:   {},     // { 'y2022-f1': File }
  photoTransforms: {},     // { 'y2022-f1': { scale, offsetX, offsetY } }
  qData:           {},     // { 'page_4_description': '...', ... }
  descMode:        {},     // { 4: 'general' | 'per_photo' }

  // ── Navegación ─────────────────────────────────────────────
  currentStep:    1,
  unlockedSteps:  new Set([1]),

  // ── Sesión ─────────────────────────────────────────────────
  sessionId: null,

  // ── UI temporal (no persiste entre pasos) ──────────────────
  ui: {
    selectMode:  false,
    selectedIdx: new Set(),
    viewMode:    'all',
  },
};

// ═══════════════════════════════════════════════════════════════
// GETTERS — lectura segura del estado
// ═══════════════════════════════════════════════════════════════
export const getters = {
  // Fotos
  photos:          () => [..._state.validFiles],
  photoCount:      () => _state.validFiles.length,
  photoAt:         (i) => _state.validFiles[i],

  // Info
  introData:       () => _state.introData,
  introPage:       (page) => ({ ..._state.introData[page] }),
  receipts:        () => _state.receipts,
  receiptsFor:     (page) => ({ ..._state.receipts[page] }),
  docState:        (page) => [...(_state.docState[page] ?? [])],

  // Agrupación
  yearGrouping:    () => ({ ..._state.yearGrouping }),
  yearsWithPhotos: () => Object.keys(_state.yearGrouping)
    .filter(y => /^\d+$/.test(y) && _state.yearGrouping[y].length > 0)
    .sort((a, b) => parseInt(a) - parseInt(b)),

  // Patrón
  pattern:         () => _state.currentPattern,
  identityMap:     () => _state.identityMap,
  photoFile:       (pid) => _state.photoIdToFile[pid] ?? null,
  transform:       (pid) => _state.photoTransforms[pid] ?? { scale: 1, offsetX: 0, offsetY: 0 },
  qData:           () => ({ ..._state.qData }),
  qField:          (key) => _state.qData[key] ?? '',
  descMode:        (pageNum) => _state.descMode[pageNum] ?? 'general',

  // Navegación
  currentStep:     () => _state.currentStep,
  isUnlocked:      (step) => _state.unlockedSteps.has(step),
  unlockedSteps:   () => new Set(_state.unlockedSteps),

  // Sesión
  sessionId:       () => _state.sessionId,

  // UI
  ui:              () => ({ ..._state.ui, selectedIdx: new Set(_state.ui.selectedIdx) }),
};

// ═══════════════════════════════════════════════════════════════
// ACTIONS — única forma de mutar el estado
// ═══════════════════════════════════════════════════════════════
export const actions = {

  // ── Fotos ──────────────────────────────────────────────────

  setPhotos(files) {
    _state.validFiles = [...files];
    _notify('photos');
  },

  addPhotos(newFiles) {
    const existing = new Set(_state.validFiles.map(f => f.name + f.size));
    const fresh = newFiles.filter(f => !existing.has(f.name + f.size));
    _state.validFiles = [..._state.validFiles, ...fresh].slice(0, 80);
    _notify('photos');
    return fresh.length; // cuántas se agregaron realmente
  },

  removePhoto(index) {
    _state.validFiles.splice(index, 1);
    // Actualizar yearGrouping — quitar el índice y reajustar los mayores
    Object.keys(_state.yearGrouping).forEach(yr => {
      _state.yearGrouping[yr] = _state.yearGrouping[yr]
        .filter(i => i !== index)
        .map(i => i > index ? i - 1 : i);
    });
    _notify('photos');
  },

  replacePhoto(index, file) {
    _state.validFiles[index] = file;
    _notify('photos');
  },

  // ── Info del solicitante ───────────────────────────────────

  setIntroField(page, field, value) {
    _state.introData[page][field] = value;
    // Si el usuario edita manualmente, desactivar auto-sync
    if (field === 'attn')  _state.introData[page]._attn_auto  = false;
    if (field === 'title') _state.introData[page]._title_auto = false;
    _notify('intro');
  },

  autoSetAttnAndTitle(attnStr, titleStr) {
    ['cover', 'letter'].forEach(pg => {
      if (_state.introData[pg]._attn_auto) {
        _state.introData[pg].attn = attnStr;
      }
    });
    if (_state.introData.cover._title_auto) {
      _state.introData.cover.title = titleStr;
    }
    _notify('intro');
  },

  toggleReceipt(page, form, receiptNumber = '') {
    if (_state.receipts[page][form] !== undefined) {
      delete _state.receipts[page][form];
    } else {
      _state.receipts[page][form] = receiptNumber;
    }
    _notify('receipts');
  },

  setReceiptNumber(page, form, value) {
    _state.receipts[page][form] = value;
    _notify('receipts');
  },

  setDocState(page, stateArray) {
    _state.docState[page] = stateArray;
  },

  updateDocItem(page, si, ii, patch) {
    const item = _state.docState[page]?.find(s => s.si === si && s.ii === ii);
    if (item) Object.assign(item, patch);
  },

  // ── Agrupación por año ─────────────────────────────────────

  initYearGrouping(years) {
    const old = { ..._state.yearGrouping };
    _state.yearGrouping = {};
    years.forEach(y => { _state.yearGrouping[y] = old[y] ?? []; });
    _notify('grouping');
  },

  assignToYear(year, photoIndex) {
    if (!_state.yearGrouping[year]) _state.yearGrouping[year] = [];
    if (!_state.yearGrouping[year].includes(photoIndex)) {
      _state.yearGrouping[year].push(photoIndex);
      _notify('grouping');
      return true;
    }
    return false;
  },

  assignManyToYear(year, indices) {
    if (!_state.yearGrouping[year]) _state.yearGrouping[year] = [];
    let added = 0;
    indices.forEach(i => {
      if (!_state.yearGrouping[year].includes(i)) {
        _state.yearGrouping[year].push(i);
        added++;
      }
    });
    if (added) _notify('grouping');
    return added;
  },

  removeFromYear(year, photoIndex) {
    _state.yearGrouping[year] = _state.yearGrouping[year].filter(i => i !== photoIndex);
    _notify('grouping');
  },

  // ── Patrón y transforms ────────────────────────────────────

  setPattern(patternData) {
    _state.currentPattern = patternData;
    _state.identityMap    = patternData.identity_map ?? {};
    _notify('pattern');
  },

  buildPhotoIdMap() {
    // Construye photoIdToFile y photoTransforms a partir de yearGrouping + validFiles
    _state.photoIdToFile   = {};
    _state.photoTransforms = {};
    const activeYears = getters.yearsWithPhotos();
    activeYears.forEach(yr => {
      _state.yearGrouping[yr].forEach((fileIdx, n) => {
        const pid = `y${yr}-f${n + 1}`;
        _state.photoIdToFile[pid]   = _state.validFiles[fileIdx];
        _state.photoTransforms[pid] = { scale: 1, offsetX: 0, offsetY: 0 };
      });
    });
  },

  replacePhotoById(pid, file) {
    _state.photoIdToFile[pid]   = file;
    _state.photoTransforms[pid] = { scale: 1, offsetX: 0, offsetY: 0 };
    // Sincronizar con validFiles via yearGrouping
    const match = pid.match(/^y(\d+)-f(\d+)/);
    if (match) {
      const yr = match[1], n = parseInt(match[2]) - 1;
      const fileIdx = _state.yearGrouping[yr]?.[n];
      if (fileIdx !== undefined) _state.validFiles[fileIdx] = file;
    }
    _notify('photos');
  },

  swapPhotoIds(pidA, pidB) {
    [_state.photoIdToFile[pidA], _state.photoIdToFile[pidB]] =
      [_state.photoIdToFile[pidB], _state.photoIdToFile[pidA]];
    [_state.photoTransforms[pidA], _state.photoTransforms[pidB]] =
      [{ ..._state.photoTransforms[pidB] }, { ..._state.photoTransforms[pidA] }];
  },

  setTransform(pid, patch) {
    const t = _state.photoTransforms[pid] ?? { scale: 1, offsetX: 0, offsetY: 0 };
    _state.photoTransforms[pid] = { ...t, ...patch };
  },

  adjustZoom(pid, delta) {
    const t = _state.photoTransforms[pid] ?? { scale: 1, offsetX: 0, offsetY: 0 };
    t.scale = Math.min(3, Math.max(1, +(t.scale + delta).toFixed(2)));
    _state.photoTransforms[pid] = t;
    return t;
  },

  resetTransform(pid) {
    _state.photoTransforms[pid] = { scale: 1, offsetX: 0, offsetY: 0 };
    return _state.photoTransforms[pid];
  },

  setQField(key, value) {
    _state.qData[key] = value;
    _notify('qdata');
  },

  setQData(dataObject) {
    _state.qData = { ...dataObject };
    _notify('qdata');
  },

  setDescMode(pageNum, mode) {
    _state.descMode[pageNum] = mode;
  },

  swapSlots(pageNum, idxA, idxB) {
    const page = _state.currentPattern?.plan.find(p => p.page === pageNum);
    if (!page) return false;
    [page.slots[idxA].photo_id, page.slots[idxB].photo_id] =
      [page.slots[idxB].photo_id, page.slots[idxA].photo_id];
    [page.slots[idxA].year, page.slots[idxB].year] =
      [page.slots[idxB].year, page.slots[idxA].year];
    return true;
  },

  // ── Navegación ─────────────────────────────────────────────

  setCurrentStep(step) {
    _state.currentStep = step;
    _notify('nav');
  },

  unlockStep(step) {
    _state.unlockedSteps.add(step);
    _notify('nav');
  },

  lockStep(step) {
    _state.unlockedSteps.delete(step);
    _notify('nav');
  },

  // ── Reset parcial (cuando se agregan/eliminan fotos) ───────

  resetFromStep3() {
    _state.currentPattern  = null;
    _state.identityMap     = {};
    _state.photoIdToFile   = {};
    _state.photoTransforms = {};
    _state.qData           = {};
    _state.yearGrouping    = {};
    [3, 4, 5, 6].forEach(s => _state.unlockedSteps.delete(s));
    _notify('reset');
  },

  // ── Sesión ─────────────────────────────────────────────────

  setSessionId(id) {
    _state.sessionId = id;
  },

  // ── UI ─────────────────────────────────────────────────────

  setViewMode(mode) {
    _state.ui.viewMode = mode;
    _notify('ui');
  },

  setSelectMode(active) {
    _state.ui.selectMode = active;
    if (!active) _state.ui.selectedIdx.clear();
    _notify('ui');
  },

  togglePhotoSelection(index) {
    if (_state.ui.selectedIdx.has(index)) {
      _state.ui.selectedIdx.delete(index);
    } else {
      _state.ui.selectedIdx.add(index);
    }
    _notify('ui');
  },

  clearSelection() {
    _state.ui.selectedIdx.clear();
    _notify('ui');
  },
};

// ═══════════════════════════════════════════════════════════════
// SISTEMA DE SUSCRIPCIONES — reactividad sin framework
//
// Uso:
//   import { subscribe } from './store.js';
//   subscribe('photos', () => renderPhotoGrid());
// ═══════════════════════════════════════════════════════════════
const _listeners = {};

function _notify(event) {
  (_listeners[event] ?? []).forEach(fn => fn());
  (_listeners['*'] ?? []).forEach(fn => fn(event));
}

export function subscribe(event, callback) {
  if (!_listeners[event]) _listeners[event] = [];
  _listeners[event].push(callback);
  // Retorna una función de cleanup: const unsub = subscribe(...); unsub();
  return () => {
    _listeners[event] = _listeners[event].filter(fn => fn !== callback);
  };
}

// ═══════════════════════════════════════════════════════════════
// QUERIES — lógica derivada que combina getters
// No mutan estado, solo calculan.
// ═══════════════════════════════════════════════════════════════
export const queries = {

  unassignedPhotos() {
    const assigned = new Set(Object.values(_state.yearGrouping).flat());
    return _state.validFiles
      .map((_, i) => i)
      .filter(i => !assigned.has(i));
  },

  introComplete() {
    const required = { cover: ['name', 'spouse'], id: ['name', 'spouse'] };
    return Object.entries(required).every(([page, fields]) =>
      fields.every(f => (_state.introData[page][f] ?? '').trim())
    );
  },

  photoPageComplete(pageNum) {
    if (_state.descMode[pageNum] === 'per_photo') {
      const page = _state.currentPattern?.plan.find(p => p.page === pageNum);
      if (!page) return false;
      return page.slots.some((_, si) =>
        (_state.qData[`page_${pageNum}_desc_${si}`] ?? '').trim()
      );
    }
    return !!(_state.qData[`page_${pageNum}_description`] ?? '').trim();
  },

  allPagesComplete() {
    const plan = _state.currentPattern?.plan ?? [];
    return queries.introComplete() && plan.every(p => queries.photoPageComplete(p.page));
  },

  photosBadge() {
    const n = _state.validFiles.length;
    return `${n} foto${n !== 1 ? 's' : ''}`;
  },

  totalPdfPages() {
    return 3 + (_state.currentPattern?.photo_pages ?? 0);
  },

  selectedReceiptForms() {
    const all = new Set();
    ['cover', 'letter', 'id'].forEach(pg =>
      Object.keys(_state.receipts[pg]).forEach(f => all.add(f))
    );
    return [...all];
  },

  summaryData() {
    const name = _state.introData.cover.name || _state.introData.id.name || 'No especificado';
    return {
      photos:    _state.validFiles.length,
      pages:     queries.totalPdfPages(),
      applicant: name,
      pattern:   _state.currentPattern?.pattern_id ?? '—',
    };
  },
};