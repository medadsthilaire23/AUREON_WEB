// ═══════════════════════════════════════════════════════════════
// questionnaire.js — Paso 4: Detalles del álbum
//
// Responsabilidades:
//   - Renderizar una sección por cada página del patrón
//   - Mostrar thumbnails de las fotos asignadas a cada página
//   - Campos de fecha, ubicación y descripción por página
//   - Swap de fotos entre slots
//   - Validación (descripción requerida en todas las páginas)
//   - Pasar al paso 5
// ═══════════════════════════════════════════════════════════════

import { actions, getters, queries } from './state.js';
import { readFileAsDataURL, toast }  from './utils.js';
import { goTo, unlockStep, markDone } from './nav.js';

// ───────────────────────────────────────────────────────────────
// METADATOS DE PLANTILLAS
// Nombre legible y número de fotos por tipo de plantilla
// ───────────────────────────────────────────────────────────────

const TMPL_META = {
  evidence_single_moment_v1:  { name: 'Single Moment',   photos: 1 },
  evidence_single_moment_v2:  { name: 'Single Moment+',  photos: 1 },
  evidence_milestone_v1:      { name: 'Milestone',        photos: 1 },
  evidence_comparison_v1:     { name: 'Comparison',       photos: 2 },
  evidence_comparison_v2:     { name: 'Comparison V2',    photos: 2 },
  evidence_before_after_v1:   { name: 'Before / After',   photos: 2 },
  evidence_sequence_v1:       { name: 'Sequence',         photos: 3 },
  evidence_sequence_v2:       { name: 'Sequence V2',      photos: 3 },
  evidence_event_timeline_v1: { name: 'Timeline',         photos: 3 },
  evidence_grid_v1:           { name: 'Photo Grid',       photos: 4 },
  evidence_grid_v2:           { name: 'Grid V2',          photos: 4 },
  evidence_daily_life_v1:     { name: 'Daily Life',       photos: 4 },
};

// ───────────────────────────────────────────────────────────────
// INIT
// ───────────────────────────────────────────────────────────────

export function initQuestionnaire() {
  document.getElementById('btnNext4')
    ?.addEventListener('click', _validateAndProceed);
}

// ───────────────────────────────────────────────────────────────
// RENDER PRINCIPAL
// Llamado desde grouping.js después de recibir el patrón de la API
// ───────────────────────────────────────────────────────────────

export function renderQuestionnaire() {
  const pattern   = getters.pattern();
  const container = document.getElementById('qContainer');
  if (!pattern || !container) return;

  // Info del patrón en el header
  _renderPatternInfo(pattern);

  container.innerHTML = '';
  (pattern.plan ?? []).forEach(page => _renderPageSection(container, page));
}

// ───────────────────────────────────────────────────────────────
// HEADER DE PATRÓN
// ───────────────────────────────────────────────────────────────

function _renderPatternInfo(pattern) {
  const info = document.getElementById('patternInfo');
  if (!info) return;

  info.style.display = 'block';
  _setText('patternId',    pattern.pattern_id);
  _setText('patternPages', pattern.photo_pages);
  _setText('patternTotal', pattern.total_pages);
  _setText('patternRange', pattern.range_type);
}

// ───────────────────────────────────────────────────────────────
// SECCIÓN POR PÁGINA
// ───────────────────────────────────────────────────────────────

function _renderPageSection(container, page) {
  const meta  = TMPL_META[page.template] ?? { name: page.template, photos: 1 };
  const slots = page.slots ?? [];
  const years = [...new Set(slots.map(s => s.year))].filter(Boolean).join(', ') || '—';

  const qData = getters.qData();
  const pn    = page.page;

  const sec = document.createElement('div');
  sec.className  = 'page-section';
  sec.id         = `qsec_${pn}`;

  // ── Header ──
  sec.innerHTML = `
    <div class="page-hdr">
      <div class="page-num-badge">${pn}</div>
      <h3>Page ${pn}</h3>
      <span class="tmpl-badge">${meta.name}</span>
      <span class="year-badge">${years}</span>
    </div>
  `;

  // ── Thumbnails + swap buttons ──
  const thumbRow = document.createElement('div');
  thumbRow.className = 'q-photos';
  thumbRow.id        = `qphotos_${pn}`;

  slots.forEach((slot, si) => {
    // Thumb container
    const thumb = document.createElement('div');
    thumb.className = 'q-thumb';
    thumb.id        = `qt_${pn}_${si}`;

    const lbl = document.createElement('span');
    lbl.className   = 'q-thumb-lbl';
    lbl.textContent = slot.year ?? '—';
    thumb.appendChild(lbl);
    thumbRow.appendChild(thumb);

    // Swap button entre slots consecutivos
    if (si < slots.length - 1) {
      const swapBtn = document.createElement('button');
      swapBtn.className   = 'swap-btn';
      swapBtn.title       = 'Intercambiar fotos';
      swapBtn.textContent = '⇄';
      swapBtn.addEventListener('click', () => swapSlots(pn, si, si + 1));
      thumbRow.appendChild(swapBtn);
    }
  });

  sec.appendChild(thumbRow);

  // ── Campos de texto ──
  const fields = document.createElement('div');
  fields.style.cssText = 'display:flex;flex-direction:column;gap:10px;';

  // Fecha y ubicación en una fila
  const metaRow = document.createElement('div');
  metaRow.className = 'form-row';

  metaRow.appendChild(_makeField({
    label:       'Date',
    sublabel:    '(optional)',
    name:        `page_${pn}_date`,
    value:       qData[`page_${pn}_date`] ?? '',
    placeholder: 'e.g. Dec 2022',
    onInput:     v => actions.setQField(`page_${pn}_date`, v),
  }));

  metaRow.appendChild(_makeField({
    label:       'Location',
    sublabel:    '(optional)',
    name:        `page_${pn}_location`,
    value:       qData[`page_${pn}_location`] ?? '',
    placeholder: 'e.g. Miami, FL',
    onInput:     v => actions.setQField(`page_${pn}_location`, v),
  }));

  fields.appendChild(metaRow);

  // Descripción — textarea requerido
  const descWrap = document.createElement('div');
  descWrap.className = 'fg';
  descWrap.innerHTML = `
    <label>Description <span style="color:var(--red)">*</span></label>
  `;

  const textarea = document.createElement('textarea');
  textarea.name        = `page_${pn}_description`;
  textarea.rows        = 2;
  textarea.required    = true;
  textarea.placeholder = 'Briefly describe this moment…';
  textarea.value       = qData[`page_${pn}_description`] ?? '';

  textarea.addEventListener('input', () => {
    textarea.classList.remove('err');
    actions.setQField(`page_${pn}_description`, textarea.value);
  });

  descWrap.appendChild(textarea);
  fields.appendChild(descWrap);
  sec.appendChild(fields);
  container.appendChild(sec);

  // Cargar thumbnails de forma asíncrona (no bloquea el render)
  _loadThumbs(slots, pn);
}

// ───────────────────────────────────────────────────────────────
// CARGAR THUMBNAILS
// ───────────────────────────────────────────────────────────────

async function _loadThumbs(slots, pageNum) {
  await Promise.allSettled(
    slots.map(async (slot, si) => {
      const el = document.getElementById(`qt_${pageNum}_${si}`);
      if (!el) return;

      const file = getters.photoFile(slot.photo_id);
      if (!file) return;

      try {
        const dataURL = await readFileAsDataURL(file);
        const img     = document.createElement('img');
        img.src       = dataURL;
        // Insertar antes del label
        el.insertBefore(img, el.firstChild);
      } catch { /* thumb no crítico, ignorar */ }
    })
  );
}

// ───────────────────────────────────────────────────────────────
// SWAP DE SLOTS
// ───────────────────────────────────────────────────────────────

export function swapSlots(pageNum, idxA, idxB) {
  const swapped = actions.swapSlots(pageNum, idxA, idxB);
  if (!swapped) return;

  const pattern = getters.pattern();
  const page    = pattern.plan.find(p => p.page === pageNum);
  if (!page) return;

  // Actualizar ambos thumbs
  [idxA, idxB].forEach(si => {
    const el   = document.getElementById(`qt_${pageNum}_${si}`);
    if (!el) return;

    // Quitar imagen anterior
    el.querySelector('img')?.remove();
    // Actualizar año
    el.querySelector('.q-thumb-lbl').textContent = page.slots[si].year ?? '—';

    // Cargar nueva imagen
    const file = getters.photoFile(page.slots[si].photo_id);
    if (file) {
      readFileAsDataURL(file)
        .then(dataURL => {
          const img = document.createElement('img');
          img.src   = dataURL;
          el.insertBefore(img, el.firstChild);
        })
        .catch(() => {});
    }
  });

  toast('Fotos intercambiadas', 'success');
}

// ───────────────────────────────────────────────────────────────
// VALIDAR Y CONTINUAR
// ───────────────────────────────────────────────────────────────

function _validateAndProceed() {
  const pattern  = getters.pattern();
  const plan     = pattern?.plan ?? [];

  // Marcar campos vacíos con clase err
  let allValid = true;
  plan.forEach(page => {
    const textarea = document.querySelector(
      `[name="page_${page.page}_description"]`
    );
    if (!textarea) return;
    if (!textarea.value.trim()) {
      textarea.classList.add('err');
      textarea.addEventListener('input', () => textarea.classList.remove('err'), { once: true });
      allValid = false;
    }
  });

  if (!allValid) {
    toast('Por favor llena todas las descripciones requeridas', 'error');
    // Scroll al primer campo vacío
    document.querySelector('#qContainer textarea.err')
      ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    return;
  }

  // Persistir todos los valores al store
  // (ya se guardan en tiempo real con onInput, esto es por si acaso)
  document.querySelectorAll('#qContainer input, #qContainer textarea')
    .forEach(f => {
      if (f.name) actions.setQField(f.name, f.value);
    });

  markDone(4);
  unlockStep(5);
  goTo(5);
}

// ───────────────────────────────────────────────────────────────
// HELPERS DOM
// ───────────────────────────────────────────────────────────────

function _makeField({ label, sublabel, name, value, placeholder, onInput }) {
  const wrap = document.createElement('div');
  wrap.className = 'fg';

  const lbl = document.createElement('label');
  lbl.innerHTML = sublabel
    ? `${label} <span style="color:var(--text3)">${sublabel}</span>`
    : label;

  const inp = document.createElement('input');
  inp.type        = 'text';
  inp.name        = name;
  inp.value       = value;
  inp.placeholder = placeholder ?? '';
  inp.addEventListener('input', () => onInput(inp.value));

  wrap.appendChild(lbl);
  wrap.appendChild(inp);
  return wrap;
}

function _setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value ?? '—';
}