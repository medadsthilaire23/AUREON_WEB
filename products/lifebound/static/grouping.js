// ═══════════════════════════════════════════════════════════════
// grouping.js — Paso 3: Agrupar fotos por año
//
// Responsabilidades:
//   - Generar los botones de año a partir del rango
//   - Modos asignar / revisar / selección múltiple
//   - Click en foto → asignar al año activo
//   - Llamar a la API y guardar el patrón en el store
// ═══════════════════════════════════════════════════════════════

import { actions, getters, queries, subscribe } from './state.js';
import { readFileAsDataURL, toast, showLoad, hideLoad } from './utils.js';
import { goTo, unlockStep, markDone } from './nav.js';
import { prepareAlbum } from './api.js';

// ───────────────────────────────────────────────────────────────
// ESTADO LOCAL DEL PASO — no va al store porque es UI temporal
// ───────────────────────────────────────────────────────────────

const local = {
  selYear:     null,   // año activo seleccionado
  revMode:     false,  // true = modo revisión (click quita foto del año)
};

// ───────────────────────────────────────────────────────────────
// INIT
// ───────────────────────────────────────────────────────────────

export function initGrouping() {
  document.getElementById('btnGenerateYears')
    ?.addEventListener('click', generateYearButtons);

  document.getElementById('btnNext3')
    ?.addEventListener('click', _confirmAndPrepare);

  document.getElementById('btnSelMode')
    ?.addEventListener('click', _toggleSelectMode);

  document.getElementById('btnAssignSel')
    ?.addEventListener('click', _assignSelectionToYear);

  document.getElementById('btnSelectAll')
    ?.addEventListener('click', _selectAllVisible);

  document.getElementById('btnClearSel')
    ?.addEventListener('click', () => { actions.clearSelection(); _renderGrid(); });

  // Reactividad: cuando cambia la selección, actualizar toolbar
  subscribe('ui', _updateSelToolbar);
  subscribe('grouping', _updateYearCounts);
}

// ───────────────────────────────────────────────────────────────
// GENERAR BOTONES DE AÑO
// ───────────────────────────────────────────────────────────────

export function generateYearButtons() {
  const start = parseInt(document.getElementById('yearStart')?.value);
  const end   = parseInt(document.getElementById('yearEnd')?.value);

  if (!start || !end || start > end || (end - start) > 20) {
    toast('Rango inválido (máximo 20 años)', 'error');
    return;
  }

  const years = [];
  for (let y = start; y <= end; y++) years.push(String(y));

  actions.initYearGrouping(years);

  // Construir botones
  const container = document.getElementById('yearButtons');
  if (!container) return;
  container.innerHTML = '';

  years.forEach(yr => {
    const btn = document.createElement('button');
    btn.className   = 'year-btn';
    btn.id          = `yb_${yr}`;
    btn.innerHTML   = `<span>${yr}</span><span class="ybc" id="yc_${yr}">0</span>`;
    btn.addEventListener('click', () => _toggleYearSel(yr));
    container.appendChild(btn);
  });

  document.getElementById('yearBtnsWrap').style.display  = 'block';
  document.getElementById('groupingWrap').style.display  = 'block';

  _resetSelYear();
  _renderGrid();
  toast('Selecciona un año y luego haz click en las fotos para asignarlas', 'success');
}

// ───────────────────────────────────────────────────────────────
// SELECCIÓN DE AÑO
// ───────────────────────────────────────────────────────────────

function _toggleYearSel(year) {
  const ui = getters.ui();

  if (local.selYear === year) {
    if (local.revMode) {
      // Segundo click en modo revisión → salir
      local.revMode   = false;
      local.selYear   = null;
      _clearYearBtnHighlight();
      _updateModeIndicator();
      _renderGrid();
    } else {
      // Primer click en año ya seleccionado → modo revisión
      const count = getters.yearGrouping()[year]?.length ?? 0;
      if (!count) { toast(`No hay fotos en ${year}`, 'error'); return; }
      local.revMode = true;
      _updateModeIndicator();
      _renderYearPhotos(year);
    }
  } else {
    local.selYear = year;
    local.revMode = false;
    _clearYearBtnHighlight();
    document.getElementById(`yb_${year}`)?.classList.add('selected');
    _updateModeIndicator();
    _renderGrid();
  }
}

function _clearYearBtnHighlight() {
  document.querySelectorAll('.year-btn').forEach(b => b.classList.remove('selected'));
}

function _resetSelYear() {
  local.selYear = null;
  local.revMode = false;
  _clearYearBtnHighlight();
}

// ───────────────────────────────────────────────────────────────
// INDICADOR DE MODO
// ───────────────────────────────────────────────────────────────

function _updateModeIndicator() {
  const el = document.getElementById('modeInd');
  if (!el) return;

  const { selectMode } = getters.ui();

  if (!local.selYear && !selectMode) {
    el.style.display = 'none';
    return;
  }

  el.style.display = 'block';

  if (selectMode) {
    el.className = 'mode-ind assign';
    el.innerHTML = `<strong>✓ Selección múltiple:</strong> Selecciona fotos y asígnalas a <strong>${local.selYear ?? 'un año'}</strong>`;
  } else if (local.revMode) {
    el.className = 'mode-ind review';
    el.innerHTML = `<strong>Revisión:</strong> Fotos en ${local.selYear} · click para quitar`;
  } else {
    el.className = 'mode-ind assign';
    el.innerHTML = `<strong>Asignar:</strong> Click en una foto para añadirla a <strong>${local.selYear}</strong> · click al año de nuevo para revisar`;
  }
}

// ───────────────────────────────────────────────────────────────
// GRID DE FOTOS NO ASIGNADAS
// ───────────────────────────────────────────────────────────────

async function _renderGrid() {
  const grid      = document.getElementById('groupingPhotos');
  const emptyEl   = document.getElementById('emptyState');
  const leftEl    = document.getElementById('photosLeft');
  const titleEl   = document.getElementById('photosTitle');
  const nextBtn   = document.getElementById('btnNext3');

  if (!grid) return;

  const unassigned = queries.unassignedPhotos();
  const { selectedIdx } = getters.ui();

  if (titleEl) titleEl.textContent = 'Fotos disponibles';
  if (leftEl)  leftEl.textContent  = unassigned.length;

  if (!unassigned.length) {
    grid.style.display    = 'none';
    if (emptyEl) emptyEl.style.display = 'block';
    if (nextBtn) nextBtn.disabled = false;
    _exitSelectMode();
    return;
  }

  grid.style.display    = 'grid';
  if (emptyEl) emptyEl.style.display = 'none';
  if (nextBtn) nextBtn.disabled = true;

  grid.innerHTML = '';

  await Promise.allSettled(
    unassigned.map(idx => _renderGroupingThumb(grid, idx, selectedIdx))
  );
}

async function _renderGroupingThumb(grid, fileIdx, selectedIdx) {
  const file = getters.photoAt(fileIdx);
  if (!file) return;

  let dataURL;
  try { dataURL = await readFileAsDataURL(file); }
  catch { return; }

  const { selectMode } = getters.ui();
  const isSelected = selectedIdx.has(fileIdx);

  const div = document.createElement('div');
  div.className   = `grouping-photo${isSelected ? ' sel-multi' : ''}`;
  div.dataset.idx = fileIdx;
  div.innerHTML   = `<img src="${dataURL}" alt="">`;

  div.addEventListener('click', () => {
    if (selectMode) {
      actions.togglePhotoSelection(fileIdx);
    } else {
      _assignPhotoToYear(fileIdx);
    }
  });

  grid.appendChild(div);
}

// ───────────────────────────────────────────────────────────────
// GRID DE REVISIÓN — fotos ya asignadas a un año
// ───────────────────────────────────────────────────────────────

async function _renderYearPhotos(year) {
  const grid    = document.getElementById('groupingPhotos');
  const leftEl  = document.getElementById('photosLeft');
  const titleEl = document.getElementById('photosTitle');
  if (!grid) return;

  const indices = getters.yearGrouping()[year] ?? [];

  if (titleEl) titleEl.textContent = `Fotos en ${year}`;
  if (leftEl)  leftEl.textContent  = indices.length;

  grid.style.display = 'grid';
  grid.innerHTML = '';

  await Promise.allSettled(
    indices.map(async idx => {
      const file = getters.photoAt(idx);
      if (!file) return;

      let dataURL;
      try { dataURL = await readFileAsDataURL(file); }
      catch { return; }

      const div = document.createElement('div');
      div.className = 'grouping-photo removing';
      div.innerHTML = `<img src="${dataURL}" alt="">`;
      div.addEventListener('click', () => _removeFromYear(year, idx));
      grid.appendChild(div);
    })
  );
}

// ───────────────────────────────────────────────────────────────
// ASIGNAR / QUITAR FOTOS
// ───────────────────────────────────────────────────────────────

function _assignPhotoToYear(fileIdx) {
  if (!local.selYear) {
    toast('Selecciona un año primero', 'error');
    return;
  }
  if (local.revMode) return;

  const added = actions.assignToYear(local.selYear, fileIdx);
  if (added) toast(`Asignada a ${local.selYear}`, 'success');
  _renderGrid();
}

function _removeFromYear(year, fileIdx) {
  actions.removeFromYear(year, fileIdx);
  const remaining = getters.yearGrouping()[year]?.length ?? 0;

  if (!remaining) {
    local.revMode = false;
    local.selYear = null;
    _clearYearBtnHighlight();
    _updateModeIndicator();
    _renderGrid();
  } else {
    _renderYearPhotos(year);
  }
  toast(`Foto quitada de ${year}`, 'success');
}

// ───────────────────────────────────────────────────────────────
// SELECCIÓN MÚLTIPLE
// ───────────────────────────────────────────────────────────────

function _toggleSelectMode() {
  const { selectMode } = getters.ui();
  if (selectMode) {
    _exitSelectMode();
  } else {
    actions.setSelectMode(true);
    document.getElementById('selToolbar').style.display  = 'flex';
    const btn = document.getElementById('btnSelMode');
    if (btn) { btn.textContent = 'Cancelar'; btn.style.color = 'var(--red)'; }
    _updateModeIndicator();
  }
}

function _exitSelectMode() {
  actions.setSelectMode(false);
  document.getElementById('selToolbar').style.display = 'none';
  const btn = document.getElementById('btnSelMode');
  if (btn) { btn.textContent = 'Seleccionar'; btn.style.color = ''; }
  _updateModeIndicator();
}

function _selectAllVisible() {
  const unassigned = queries.unassignedPhotos();
  unassigned.forEach(i => actions.togglePhotoSelection(i));
  _renderGrid();
}

function _assignSelectionToYear() {
  if (!local.selYear) { toast('Selecciona un año primero', 'error'); return; }

  const { selectedIdx } = getters.ui();
  const added = actions.assignManyToYear(local.selYear, [...selectedIdx]);

  _exitSelectMode();
  _renderGrid();
  toast(`${added} foto${added !== 1 ? 's' : ''} asignada${added !== 1 ? 's' : ''} a ${local.selYear}`, 'success');
}

function _updateSelToolbar() {
  const { selectedIdx } = getters.ui();
  const n = selectedIdx.size;
  const countEl = document.getElementById('selCount');
  const assignBtn = document.getElementById('btnAssignSel');
  if (countEl)   countEl.textContent = `${n} seleccionada${n !== 1 ? 's' : ''}`;
  if (assignBtn) {
    assignBtn.disabled  = n === 0 || !local.selYear;
    assignBtn.textContent = local.selYear ? `Asignar a ${local.selYear}` : 'Asignar';
  }
}

function _updateYearCounts() {
  const grouping = getters.yearGrouping();
  Object.entries(grouping).forEach(([yr, indices]) => {
    const el = document.getElementById(`yc_${yr}`);
    if (el) el.textContent = indices.length;
  });
}

// ───────────────────────────────────────────────────────────────
// CONTINUAR → llamar API y pasar al paso 4
// ───────────────────────────────────────────────────────────────

async function _confirmAndPrepare() {
  const activeYears = getters.yearsWithPhotos();

  if (!activeYears.length) {
    toast('Asigna al menos una foto a un año', 'error');
    return;
  }

  showLoad('Preparando álbum…', 'Calculando layouts y dimensiones');

  try {
    // Construir yearCounts: { '2022': 3, '2023': 5 }
    const grouping    = getters.yearGrouping();
    const yearCounts  = {};
    activeYears.forEach(yr => { yearCounts[yr] = grouping[yr].length; });

    const { sessionId, slots } = await prepareAlbum({
      photoCount:  getters.photoCount(),
      activeYears,
      yearCounts,
    });

    // Guardar en el store
    actions.setSessionId(sessionId);
    actions.setPattern(slots);
    actions.buildPhotoIdMap();

    hideLoad();
    markDone(3);
    unlockStep(4);
    goTo(4);

  } catch (err) {
    hideLoad();
    toast(`Error: ${err.message}`, 'error');
  }
}