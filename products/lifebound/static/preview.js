// ═══════════════════════════════════════════════════════════════
// preview.js — Paso 5: Previsualización del álbum
//
// Secciones:
//   1. Init & suscripciones
//   2. Build principal (índice + páginas)
//   3. Páginas intro (cover, letter, id)
//   4. Páginas de fotos (slots con pan/zoom)
//   5. Pan & zoom (mouse + touch)
//   6. Replace modal (desde device o mismo año)
//   7. Modo descripción por foto (per-photo)
//   8. Índice lateral + scroll spy
//   9. Vista filtrada (all / intro / photos)
//  10. Completeness hint
// ═══════════════════════════════════════════════════════════════

import { actions, getters, queries, subscribe } from './state.js';
import { readFileAsDataURL, toast, el }          from './utils.js';
import { goTo, unlockStep, markDone }            from './nav.js';

// ───────────────────────────────────────────────────────────────
// CONSTANTES
// ───────────────────────────────────────────────────────────────

const INTRO_PAGES = [
  { id: 'cover',  label: 'Cover Page',     pdfPage: 1, required: ['name', 'spouse'] },
  { id: 'letter', label: 'Cover Letter',   pdfPage: 2, required: [] },
  { id: 'id',     label: 'Identification', pdfPage: 3, required: ['name', 'spouse'] },
];

const TMPL_META = {
  evidence_single_moment_v1:  { name: 'Single Moment'  },
  evidence_single_moment_v2:  { name: 'Single Moment+' },
  evidence_milestone_v1:      { name: 'Milestone'       },
  evidence_comparison_v1:     { name: 'Comparison'      },
  evidence_comparison_v2:     { name: 'Comparison V2'   },
  evidence_before_after_v1:   { name: 'Before / After'  },
  evidence_sequence_v1:       { name: 'Sequence'        },
  evidence_sequence_v2:       { name: 'Sequence V2'     },
  evidence_event_timeline_v1: { name: 'Timeline'        },
  evidence_grid_v1:           { name: 'Photo Grid'      },
  evidence_grid_v2:           { name: 'Grid V2'         },
  evidence_daily_life_v1:     { name: 'Daily Life'      },
};

// ───────────────────────────────────────────────────────────────
// 1. INIT
// ───────────────────────────────────────────────────────────────

export function initPreview() {
  // Botones de vista
  document.getElementById('pvContent')
    ?.parentElement
    ?.querySelectorAll('.vt-btn')
    .forEach(btn => {
      btn.addEventListener('click', () => setViewMode(btn.dataset.mode));
    });

  // Toggle del índice lateral
  document.getElementById('idxToggleBtn')
    ?.addEventListener('click', togglePageIndex);

  // Botón continuar
  document.getElementById('btnNext5')
    ?.addEventListener('click', _proceedToGenerate);

  // Cerrar dropdowns de replace al hacer click fuera
  document.addEventListener('click', e => {
    if (!e.target.closest('.rep-menu-wrap')) _closeAllRepMenus();
  });

  // Reactividad: si introData cambia desde applicant.js, refrescar hints
  subscribe('intro',    updateComplHint);
  subscribe('qdata',    updateComplHint);
}

// ───────────────────────────────────────────────────────────────
// 2. BUILD PRINCIPAL
// ───────────────────────────────────────────────────────────────

export function buildPreview() {
  const total = queries.totalPdfPages();
  const el_   = document.getElementById('pvTotalPages');
  if (el_) el_.textContent = total;

  buildPageIndex();
  _buildPvContent();
  updateComplHint();
  applyViewMode();
}

// ───────────────────────────────────────────────────────────────
// 3. PÁGINAS INTRO
// ───────────────────────────────────────────────────────────────

function _buildPvContent() {
  const content = document.getElementById('pvContent');
  if (!content) return;
  content.innerHTML = '';

  INTRO_PAGES.forEach(pg => _buildIntroPage(content, pg));

  const plan = getters.pattern()?.plan ?? [];
  plan.forEach(page => _buildPhotoPage(content, page));
}

function _buildIntroPage(content, pg) {
  const data   = getters.introPage(pg.id);
  const isOk   = pg.required.length === 0 ||
                 pg.required.every(f => (data[f] ?? '').trim());

  const sec = el('div', { class: 'pv-page' });
  sec.id              = `pvp_intro_${pg.id}`;
  sec.dataset.type    = 'intro';
  sec.dataset.indexId = pg.pdfPage;

  // Header
  const hdr = el('div', { class: 'pv-page-hdr' });
  hdr.innerHTML = `
    <span class="pv-page-num intro">P.${pg.pdfPage}</span>
    <span class="pv-page-title">${pg.label}</span>
    <span class="pv-complete-badge ${isOk ? 'ok' : 'missing'}" id="pvicomp_${pg.id}">
      ${isOk ? '✓ Complete' : 'Required fields missing'}
    </span>
  `;
  sec.appendChild(hdr);

  // Campos editables inline
  const grid = el('div', { class: 'form-grid', style: 'margin-top:4px;' });
  _getIntroPgFields(pg.id).forEach(f => {
    const val  = data[f.key] ?? '';
    const wrap = el('div', { class: `fg${f.full ? ' full' : ''}` });
    wrap.innerHTML = `
      <label>${f.label}${f.req ? ' <span style="color:var(--red)">*</span>' : ''}</label>
    `;
    const inp = el('input', {
      type:        'text',
      id:          `pvif_${pg.id}_${f.key}`,
      placeholder: f.ph,
      value:       val,
      'data-ip':   pg.id,
      'data-if':   f.key,
    });
    inp.addEventListener('input', () => {
      actions.setIntroField(pg.id, f.key, inp.value);
      // Sincronizar con el campo equivalente en paso 2
      const s2 = document.querySelector(
        `#step2 [data-ip="${pg.id}"][data-if="${f.key}"]`
      );
      if (s2) s2.value = inp.value;
      _updatePvIntroComp(pg.id);
      updateComplHint();
    });
    wrap.appendChild(inp);
    grid.appendChild(wrap);
  });
  sec.appendChild(grid);

  content.appendChild(sec);
}

function _getIntroPgFields(pgId) {
  const fields = {
    cover: [
      { key: 'name',           label: 'Applicant Name', req: true,  ph: 'Jane Smith' },
      { key: 'spouse',         label: 'Spouse Name',    req: true,  ph: 'John Smith' },
      { key: 'interview_date', label: 'Interview Date', req: false, ph: 'January 01, 2025' },
      { key: 'interview_time', label: 'Interview Time', req: false, ph: '9:30 AM' },
      { key: 'office',         label: 'USCIS Office',   req: false, ph: 'Boston Field Office', full: true },
    ],
    letter: [
      { key: 'a_number', label: 'A-Number',    req: false, ph: 'A123456789' },
      { key: 'office',   label: 'USCIS Office',req: false, ph: 'Boston Field Office' },
      { key: 'address',  label: 'Address',     req: false, ph: '123 Main St, City, State, ZIP', full: true },
    ],
    id: [
      { key: 'name',           label: 'Applicant Name', req: true,  ph: 'Jane Smith' },
      { key: 'spouse',         label: 'Spouse Name',    req: true,  ph: 'John Smith' },
      { key: 'a_number',       label: 'A-Number',       req: false, ph: 'A123456789' },
      { key: 'interview_date', label: 'Interview Date', req: false, ph: 'January 01, 2025' },
      { key: 'interview_time', label: 'Interview Time', req: false, ph: '9:30 AM' },
      { key: 'address',        label: 'Address',        req: false, ph: '123 Main St, City, State, ZIP', full: true },
    ],
  };
  return fields[pgId] ?? [];
}

function _updatePvIntroComp(pgId) {
  const pg   = INTRO_PAGES.find(p => p.id === pgId);
  if (!pg) return;
  const data = getters.introPage(pgId);
  const isOk = pg.required.length === 0 ||
               pg.required.every(f => (data[f] ?? '').trim());

  const badge = document.getElementById(`pvicomp_${pgId}`);
  if (badge) {
    badge.textContent = isOk ? '✓ Complete' : 'Required fields missing';
    badge.className   = `pv-complete-badge ${isOk ? 'ok' : 'missing'}`;
  }

  const idxItem = document.getElementById(`idxi_${pg.pdfPage}`);
  if (idxItem) {
    idxItem.classList.toggle('complete',   isOk);
    idxItem.classList.toggle('incomplete', !isOk);
  }
}

// ───────────────────────────────────────────────────────────────
// 4. PÁGINAS DE FOTOS
// ───────────────────────────────────────────────────────────────

function _buildPhotoPage(content, page) {
  const pdfPage = page.page + 3;
  const meta    = TMPL_META[page.template] ?? { name: page.template };
  const slots   = page.slots ?? [];
  const years   = [...new Set(slots.map(s => s.year))].filter(Boolean).join(', ') || '—';
  const qData   = getters.qData();
  const pn      = page.page;

  const sec = el('div', { class: 'pv-page' });
  sec.id              = `pvp_photo_${pn}`;
  sec.dataset.type    = 'photo';
  sec.dataset.indexId = pdfPage;

  sec.innerHTML = `
    <div class="pv-page-hdr">
      <span class="pv-page-num">P.${pdfPage}</span>
      <span class="pv-page-title">${meta.name}</span>
      <span class="year-badge" style="margin-left:auto;">${years}</span>
    </div>
  `;

  // Slots de fotos con pan/zoom
  const slotsContainer = el('div', { id: `pvs_${pn}` });
  _renderSlots(slotsContainer, slots, pn);
  sec.appendChild(slotsContainer);

  // Campos inline
  const fieldsDiv = el('div', { class: 'pv-fields' });
  fieldsDiv.innerHTML = `
    <div class="il-field">
      <label>Date</label>
      <input type="text" data-page="${pn}" data-field="date"
        value="${qData[`page_${pn}_date`] ?? ''}" placeholder="e.g. Dec 2022">
    </div>
    <div class="il-field">
      <label>Location</label>
      <input type="text" data-page="${pn}" data-field="location"
        value="${qData[`page_${pn}_location`] ?? ''}" placeholder="e.g. Miami, FL">
    </div>
  `;

  // Delegación para fecha/ubicación
  fieldsDiv.addEventListener('input', e => {
    const inp = e.target.closest('[data-page][data-field]');
    if (!inp) return;
    actions.setQField(`page_${inp.dataset.page}_${inp.dataset.field}`, inp.value);
  });

  // Descripción con modo general / per-photo
  const descWrap = el('div', { class: 'il-field full', id: `descwrap_${pn}` });
  descWrap.appendChild(_buildDescSection(pn, slots, qData));
  fieldsDiv.appendChild(descWrap);

  sec.appendChild(fieldsDiv);
  content.appendChild(sec);
}

// ───────────────────────────────────────────────────────────────
// 5. SLOTS CON PAN & ZOOM
// ───────────────────────────────────────────────────────────────

function _renderSlots(container, slots, pageNum) {
  container.innerHTML = '';
  const row = el('div', { class: 'pv-slots-row' });

  slots.forEach((slot, si) => {
    const wrap    = el('div', { class: 'pv-slot-wrap' });
    const slotDiv = el('div', { class: 'pv-slot' });
    slotDiv.id                = `pvsl_${pageNum}_${si}`;
    slotDiv.dataset.photoId   = slot.photo_id;
    slotDiv.dataset.pageNum   = pageNum;
    slotDiv.dataset.slotIdx   = si;

    // Aspect ratio del slot según identityMap
    const dims = getters.identityMap()[slot.photo_id];
    slotDiv.style.paddingTop = (dims?.w && dims?.h)
      ? `${(dims.h / dims.w * 100).toFixed(2)}%`
      : '75%';

    // Imagen
    const file = getters.photoFile(slot.photo_id);
    if (file) {
      readFileAsDataURL(file).then(dataURL => {
        const img = el('img', { id: `pvimg_${pageNum}_${si}` });
        img.src   = dataURL;
        img.style.transformOrigin = 'center center';
        _applyTransform(img, getters.transform(slot.photo_id));
        slotDiv.appendChild(img);
      }).catch(() => {});
    }

    _setupPanZoom(slotDiv, slot.photo_id, pageNum, si);

    // Controles de zoom + replace
    const t    = getters.transform(slot.photo_id);
    const ctrl = el('div', { class: 'pv-controls' });
    ctrl.innerHTML = `
      <button class="z-btn" data-action="zoom-out" data-pid="${slot.photo_id}" data-pn="${pageNum}" data-si="${si}">−</button>
      <span class="z-val" id="zv_${pageNum}_${si}">${Math.round(t.scale * 100)}%</span>
      <button class="z-btn" data-action="zoom-in"  data-pid="${slot.photo_id}" data-pn="${pageNum}" data-si="${si}">+</button>
      <button class="rst-btn" data-action="reset"  data-pid="${slot.photo_id}" data-pn="${pageNum}" data-si="${si}">↺</button>
      <div class="rep-menu-wrap" id="rmw_${pageNum}_${si}">
        <button class="rep-btn" data-action="rep-menu" data-id="${pageNum}_${si}">Replace ▾</button>
        <div class="rep-dropdown" id="rdd_${pageNum}_${si}">
          <div class="rep-dd-item" data-action="rep-device" data-pid="${slot.photo_id}" data-pn="${pageNum}" data-si="${si}">📁 From Device</div>
          <div class="rep-dd-item" data-action="rep-year"   data-pid="${slot.photo_id}" data-pn="${pageNum}" data-si="${si}">🖼 Same Year</div>
        </div>
      </div>
    `;

    // Un solo listener para todos los controles del slot
    ctrl.addEventListener('click', e => _handleSlotControl(e));

    wrap.appendChild(slotDiv);
    wrap.appendChild(ctrl);
    row.appendChild(wrap);
  });

  container.appendChild(row);
}

export function refreshPhotoPage(pageNum) {
  const pattern = getters.pattern();
  const page    = pattern?.plan.find(p => p.page === pageNum);
  if (!page) return;
  const c = document.getElementById(`pvs_${pageNum}`);
  if (c) _renderSlots(c, page.slots, pageNum);
}

// ── Controles de slot (zoom, reset, replace) ──────────────────

function _handleSlotControl(e) {
  const btn    = e.target.closest('[data-action]');
  if (!btn) return;
  const action = btn.dataset.action;
  const pid    = btn.dataset.pid;
  const pn     = parseInt(btn.dataset.pn);
  const si     = parseInt(btn.dataset.si);

  if (action === 'zoom-in')   _adjustZoom(pid, pn, si, +0.1);
  if (action === 'zoom-out')  _adjustZoom(pid, pn, si, -0.1);
  if (action === 'reset')     _resetTransform(pid, pn, si);
  if (action === 'rep-menu')  _toggleRepMenu(btn.dataset.id);
  if (action === 'rep-device') _replaceFromDevice(pid, pn, si);
  if (action === 'rep-year')   _openRepModal(pid, pn, si);
}

// ── Zoom ──────────────────────────────────────────────────────

function _adjustZoom(pid, pn, si, delta) {
  const t   = actions.adjustZoom(pid, delta);
  const img = document.getElementById(`pvimg_${pn}_${si}`);
  const zv  = document.getElementById(`zv_${pn}_${si}`);
  if (img) _applyTransform(img, t);
  if (zv)  zv.textContent = `${Math.round(t.scale * 100)}%`;
}

function _resetTransform(pid, pn, si) {
  const t   = actions.resetTransform(pid);
  const img = document.getElementById(`pvimg_${pn}_${si}`);
  const zv  = document.getElementById(`zv_${pn}_${si}`);
  if (img) _applyTransform(img, t);
  if (zv)  zv.textContent = '100%';
  toast('Reset', 'success');
}

function _applyTransform(img, t) {
  img.style.transform = `translate(${((t.offsetX ?? 0) * 100).toFixed(2)}%, ${((t.offsetY ?? 0) * 100).toFixed(2)}%) scale(${(t.scale ?? 1).toFixed(3)})`;
}

// ───────────────────────────────────────────────────────────────
// 6. PAN & ZOOM (mouse + touch + wheel)
// ───────────────────────────────────────────────────────────────

function _setupPanZoom(slotDiv, pid, pn, si) {
  let drag = false, sx = 0, sy = 0, sox = 0, soy = 0, lastDist = null;

  // Wheel → zoom
  slotDiv.addEventListener('wheel', e => {
    e.preventDefault();
    const t = actions.adjustZoom(pid, e.deltaY > 0 ? -0.08 : 0.08);
    const img = document.getElementById(`pvimg_${pn}_${si}`);
    const zv  = document.getElementById(`zv_${pn}_${si}`);
    if (img) _applyTransform(img, t);
    if (zv)  zv.textContent = `${Math.round(t.scale * 100)}%`;
    slotDiv.classList.add('panning');
    clearTimeout(slotDiv._zt);
    slotDiv._zt = setTimeout(() => slotDiv.classList.remove('panning'), 700);
  }, { passive: false });

  // Mouse → pan
  slotDiv.addEventListener('mousedown', e => {
    const t = getters.transform(pid);
    if (t.scale <= 1) return;
    drag = true;
    sx   = e.clientX; sy = e.clientY;
    sox  = t.offsetX ?? 0; soy = t.offsetY ?? 0;
    slotDiv.style.cursor = 'grabbing';
    e.preventDefault();
  });

  window.addEventListener('mousemove', e => {
    if (!drag) return;
    const t    = getters.transform(pid);
    const rect = slotDiv.getBoundingClientRect();
    const mx   = (t.scale - 1) / 2;
    actions.setTransform(pid, {
      offsetX: Math.min(mx, Math.max(-mx, sox + (e.clientX - sx) / rect.width)),
      offsetY: Math.min(mx, Math.max(-mx, soy + (e.clientY - sy) / rect.height)),
    });
    const img = document.getElementById(`pvimg_${pn}_${si}`);
    if (img) _applyTransform(img, getters.transform(pid));
  });

  window.addEventListener('mouseup', () => {
    drag = false;
    slotDiv.style.cursor = 'crosshair';
  });

  // Touch → pinch zoom + pan
  slotDiv.addEventListener('touchstart', e => {
    if (e.touches.length === 2) {
      lastDist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
    } else if (e.touches.length === 1) {
      const t = getters.transform(pid);
      sx = e.touches[0].clientX; sy = e.touches[0].clientY;
      sox = t.offsetX ?? 0; soy = t.offsetY ?? 0;
    }
  }, { passive: true });

  slotDiv.addEventListener('touchmove', e => {
    if (e.touches.length === 2) {
      e.preventDefault();
      const d = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      const t = getters.transform(pid);
      actions.setTransform(pid, {
        scale: Math.min(3, Math.max(1, +(t.scale * (d / lastDist)).toFixed(3))),
      });
      lastDist = d;
      const img = document.getElementById(`pvimg_${pn}_${si}`);
      const zv  = document.getElementById(`zv_${pn}_${si}`);
      if (img) _applyTransform(img, getters.transform(pid));
      if (zv)  zv.textContent = `${Math.round(getters.transform(pid).scale * 100)}%`;
    } else if (e.touches.length === 1) {
      const t = getters.transform(pid);
      if (t.scale <= 1) return;
      const rect = slotDiv.getBoundingClientRect();
      const mx   = (t.scale - 1) / 2;
      actions.setTransform(pid, {
        offsetX: Math.min(mx, Math.max(-mx, sox + (e.touches[0].clientX - sx) / rect.width)),
        offsetY: Math.min(mx, Math.max(-mx, soy + (e.touches[0].clientY - sy) / rect.height)),
      });
      const img = document.getElementById(`pvimg_${pn}_${si}`);
      if (img) _applyTransform(img, getters.transform(pid));
    }
  }, { passive: false });
}

// ───────────────────────────────────────────────────────────────
// 7. REPLACE — desde device o mismo año
// ───────────────────────────────────────────────────────────────

let _repTarget = null;

function _replaceFromDevice(pid, pn, si) {
  _closeAllRepMenus();
  const input = document.createElement('input');
  input.type   = 'file';
  input.accept = 'image/*';
  input.addEventListener('change', async e => {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > 15 * 1024 * 1024) { toast('Archivo muy grande (máx 15MB)', 'error'); return; }
    actions.replacePhotoById(pid, file);
    actions.resetTransform(pid);
    refreshPhotoPage(pn);
    _updateQThumb(pid, pn);
    toast('Foto reemplazada ✓', 'success');
  });
  input.click();
}

function _openRepModal(pid, pn, si) {
  _closeAllRepMenus();
  _repTarget = { pid, pn, si };

  const match = pid.match(/^y(\d+)-f/);
  const year  = match?.[1] ?? null;

  document.getElementById('repModalSub').textContent =
    year ? `Replace — la identidad se mantiene, solo cambia la foto` : 'Selecciona una foto';

  const grid = document.getElementById('repGrid');
  const lbl  = document.getElementById('repGridLabel');
  if (lbl)  lbl.textContent = year ? `Fotos del año ${year}` : 'Todas las fotos';
  if (grid) grid.innerHTML  = '';

  const indices = year ? (getters.yearGrouping()[year] ?? []) : getters.photos().map((_, i) => i);

  Promise.allSettled(
    indices.map(async (fileIdx, n) => {
      const cid  = `y${year}-f${n + 1}`;
      const file = getters.photoAt(fileIdx);
      if (!file) return;
      const dataURL = await readFileAsDataURL(file);
      const isCur   = cid === pid;
      const opt     = el('div', { class: `rep-opt${isCur ? ' current' : ''}` });
      opt.innerHTML = `<img src="${dataURL}"><span class="rep-opt-id">${cid}</span>`;
      if (!isCur) opt.addEventListener('click', () => _swapPhotoInPreview(cid));
      grid?.appendChild(opt);
    })
  );

  document.getElementById('repGridWrap').style.display  = 'block';
  document.getElementById('replaceModal').classList.add('show');
}

function _swapPhotoInPreview(newPid) {
  if (!_repTarget) return;
  const { pid: oldPid, pn } = _repTarget;
  actions.swapPhotoIds(oldPid, newPid);
  closeReplaceModal();
  refreshPhotoPage(pn);
  _updateQThumb(oldPid, pn);
  toast('Foto reemplazada ✓', 'success');
}

export function closeReplaceModal() {
  document.getElementById('replaceModal')?.classList.remove('show');
  document.getElementById('repGridWrap').style.display = 'none';
  _repTarget = null;
}

// ── Dropdown helpers ──────────────────────────────────────────

function _toggleRepMenu(id) {
  _closeAllRepMenus();
  document.getElementById(`rdd_${id}`)?.classList.toggle('show');
}

function _closeAllRepMenus() {
  document.querySelectorAll('.rep-dropdown.show')
    .forEach(d => d.classList.remove('show'));
}

// ── Actualizar thumbnail en paso 4 ────────────────────────────

function _updateQThumb(pid, pn) {
  const pattern = getters.pattern();
  const page    = pattern?.plan.find(p => p.page === pn);
  if (!page) return;

  page.slots.forEach((slot, si) => {
    if (slot.photo_id !== pid) return;
    const thumbEl = document.getElementById(`qt_${pn}_${si}`);
    if (!thumbEl) return;
    thumbEl.querySelector('img')?.remove();
    const file = getters.photoFile(pid);
    if (file) {
      readFileAsDataURL(file).then(dataURL => {
        const img = el('img');
        img.src   = dataURL;
        thumbEl.insertBefore(img, thumbEl.firstChild);
      }).catch(() => {});
    }
  });
}

// ───────────────────────────────────────────────────────────────
// 8. DESCRIPCIÓN POR FOTO (per-photo mode)
// ───────────────────────────────────────────────────────────────

function _buildDescSection(pn, slots, qData) {
  const wrapper = document.createElement('div');

  // Barra de modo
  const modeBar = el('div', { class: 'desc-mode-bar' });
  modeBar.innerHTML = `
    <span>Description *</span>
    <div class="desc-mode-btns">
      <button class="desc-mode-btn active" data-mode="general">General</button>
      <button class="desc-mode-btn"        data-mode="per_photo">Per Photo</button>
    </div>
  `;
  modeBar.addEventListener('click', e => {
    const btn = e.target.closest('[data-mode]');
    if (!btn) return;
    setDescMode(pn, btn.dataset.mode);
  });
  wrapper.appendChild(modeBar);

  // General
  const genDiv = el('div', { id: `desc_general_${pn}` });
  const ta = el('textarea', {
    'data-page':  pn,
    'data-field': 'description',
    placeholder:  'Describe este momento…',
    rows:         '2',
  });
  ta.value = qData[`page_${pn}_description`] ?? '';
  ta.addEventListener('input', () => {
    actions.setQField(`page_${pn}_description`, ta.value);
    _updatePageIndexDot(pn + 3, !!ta.value.trim());
    updateComplHint();
  });
  genDiv.appendChild(ta);
  wrapper.appendChild(genDiv);

  // Per-photo (oculto por defecto)
  const ppDiv = el('div', { id: `desc_perphoto_${pn}`, style: 'display:none;' });
  wrapper.appendChild(ppDiv);

  return wrapper;
}

export function setDescMode(pn, mode) {
  actions.setDescMode(pn, mode);

  const wrap = document.getElementById(`descwrap_${pn}`);
  if (!wrap) return;

  wrap.querySelectorAll('.desc-mode-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.mode === mode);
  });

  const genDiv = document.getElementById(`desc_general_${pn}`);
  const ppDiv  = document.getElementById(`desc_perphoto_${pn}`);

  if (mode === 'general') {
    if (genDiv) genDiv.style.display = '';
    if (ppDiv)  ppDiv.style.display  = 'none';
  } else {
    if (genDiv) genDiv.style.display = 'none';
    if (ppDiv) {
      ppDiv.style.display = '';
      _buildPerPhotoDesc(pn, ppDiv);
    }
  }
}

function _buildPerPhotoDesc(pn, container) {
  container.innerHTML = '';
  const pattern = getters.pattern();
  const page    = pattern?.plan.find(p => p.page === pn);
  if (!page) return;

  const wrap = el('div', { class: 'per-photo-desc' });

  page.slots.forEach((slot, si) => {
    const row = el('div', { class: 'per-photo-row' });

    const thumb = el('img', { class: 'per-photo-thumb' });
    const file  = getters.photoFile(slot.photo_id);
    if (file) {
      readFileAsDataURL(file)
        .then(dataURL => { thumb.src = dataURL; })
        .catch(() => {});
    }

    const fieldWrap = el('div', { style: 'flex:1;' });
    const lbl = el('div', { style: 'font-size:.68rem;color:var(--text3);margin-bottom:3px;' },
      `Photo ${si + 1} — ${slot.photo_id}`);

    const ta = el('textarea');
    Object.assign(ta.style, {
      width: '100%', background: 'var(--surface2)',
      border: '1px solid var(--border)', borderRadius: 'var(--r)',
      padding: '6px 9px', color: 'var(--text)',
      fontFamily: 'var(--font-sans)', fontSize: '.8rem',
      resize: 'vertical', minHeight: '44px',
    });
    ta.placeholder = 'Describe esta foto…';
    ta.value       = getters.qField(`page_${pn}_desc_${si}`);

    ta.addEventListener('input', () => {
      actions.setQField(`page_${pn}_desc_${si}`, ta.value);
      // Combinar todas las descripciones en el campo general
      const all = page.slots
        .map((_, j) => getters.qField(`page_${pn}_desc_${j}`))
        .filter(Boolean);
      actions.setQField(`page_${pn}_description`, all.join(' | '));
      _updatePageIndexDot(pn + 3, all.length > 0);
      updateComplHint();
    });

    fieldWrap.appendChild(lbl);
    fieldWrap.appendChild(ta);
    row.appendChild(thumb);
    row.appendChild(fieldWrap);
    wrap.appendChild(row);
  });

  container.appendChild(wrap);
}

// ───────────────────────────────────────────────────────────────
// 9. ÍNDICE LATERAL + SCROLL SPY
// ───────────────────────────────────────────────────────────────

export function buildPageIndex() {
  const idx = document.getElementById('pageIndex');
  if (!idx) return;
  idx.innerHTML = '';

  // Sección intro
  const introSec = el('div', { class: 'idx-section' });
  introSec.innerHTML = '<div class="idx-section-lbl">Intro</div>';

  INTRO_PAGES.forEach(pg => {
    const data = getters.introPage(pg.id);
    const isOk = pg.required.length === 0 ||
                 pg.required.every(f => (data[f] ?? '').trim());

    const item = el('div', {
      class: `idx-item ${isOk ? 'complete' : 'incomplete'}`,
      id:    `idxi_${pg.pdfPage}`,
    });
    item.innerHTML = `
      <span class="idx-num">P.${pg.pdfPage}</span>
      <span class="idx-dot"></span>
      <span class="idx-lbl">${pg.label}</span>
    `;
    item.addEventListener('click', () =>
      document.getElementById(`pvp_intro_${pg.id}`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    );
    introSec.appendChild(item);
  });
  idx.appendChild(introSec);

  // Sección fotos
  const plan = getters.pattern()?.plan ?? [];
  if (plan.length) {
    const photoSec = el('div', { class: 'idx-section' });
    photoSec.innerHTML = '<div class="idx-section-lbl">Photos</div>';

    plan.forEach(page => {
      const pdfPage = page.page + 3;
      const isOk    = queries.photoPageComplete(page.page);
      const years   = [...new Set((page.slots ?? []).map(s => s.year))].filter(Boolean).join('/');

      const item = el('div', {
        class: `idx-item ${isOk ? 'complete' : 'incomplete'}`,
        id:    `idxi_${pdfPage}`,
      });
      item.innerHTML = `
        <span class="idx-num">P.${pdfPage}</span>
        <span class="idx-dot"></span>
        <span class="idx-lbl">${years || '—'}</span>
      `;
      item.addEventListener('click', () =>
        document.getElementById(`pvp_photo_${page.page}`)
          ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      );
      photoSec.appendChild(item);
    });
    idx.appendChild(photoSec);
  }

  _setupScrollSpy();
}

function _updatePageIndexDot(pdfPage, isComplete) {
  const item = document.getElementById(`idxi_${pdfPage}`);
  if (!item) return;
  item.classList.toggle('complete',   isComplete);
  item.classList.toggle('incomplete', !isComplete);
}

function _setupScrollSpy() {
  window._sspy?.disconnect();
  const obs = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (!e.isIntersecting) return;
      const id = e.target.dataset.indexId;
      document.querySelectorAll('.idx-item').forEach(i => i.classList.remove('active'));
      document.getElementById(`idxi_${id}`)?.classList.add('active');
    });
  }, { rootMargin: '-15% 0px -70% 0px', threshold: 0 });

  document.querySelectorAll('.pv-page').forEach(p => obs.observe(p));
  window._sspy = obs;
}

export function togglePageIndex() {
  const idx = document.getElementById('pageIndex');
  const btn = document.getElementById('idxToggleBtn');
  const hidden = idx?.classList.toggle('hidden');
  btn?.classList.toggle('active', !hidden);
}

// ───────────────────────────────────────────────────────────────
// 10. VISTA FILTRADA
// ───────────────────────────────────────────────────────────────

export function setViewMode(mode) {
  actions.setViewMode(mode);
  document.querySelectorAll('.vt-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.mode === mode)
  );
  applyViewMode();
  buildPageIndex();
}

export function applyViewMode() {
  const mode = getters.ui().viewMode;
  document.querySelectorAll('.pv-page').forEach(pg => {
    const type = pg.dataset.type;
    const show = mode === 'all'
      || (mode === 'intro'  && type === 'intro')
      || (mode === 'photos' && type === 'photo');
    pg.classList.toggle('hidden', !show);
  });
}

// ───────────────────────────────────────────────────────────────
// 11. COMPLETENESS HINT
// ───────────────────────────────────────────────────────────────

export function updateComplHint() {
  const el_   = document.getElementById('complHint');
  if (!el_) return;

  const plan   = getters.pattern()?.plan ?? [];
  const doneP  = plan.filter(p => queries.photoPageComplete(p.page)).length;
  const iOk    = queries.introComplete();

  if (iOk && doneP === plan.length) {
    el_.textContent = '✓ Todas las páginas completas — listo para generar';
    el_.style.color = 'var(--green)';
  } else {
    const missing = [];
    if (!iOk)            missing.push('páginas de intro');
    if (doneP < plan.length)
      missing.push(`${plan.length - doneP} descripción${plan.length - doneP > 1 ? 'es' : ''}`);
    el_.textContent = `Faltan: ${missing.join(', ')}`;
    el_.style.color = 'var(--amber)';
  }
}

// ───────────────────────────────────────────────────────────────
// 12. CONTINUAR AL PASO 6
// ───────────────────────────────────────────────────────────────

function _proceedToGenerate() {
  if (!queries.allPagesComplete()) {
    toast('Completa todos los campos requeridos antes de continuar', 'error');
    return;
  }
  markDone(5);
  unlockStep(6);
  goTo(6);
}