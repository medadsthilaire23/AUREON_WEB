// ═══════════════════════════════════════════════════════════════
// upload.js — Paso 1: Subir fotos
//
// Responsabilidades:
//   - Drag & drop y selección de archivos
//   - Validación (JPG/PNG, max 15MB, 15-80 fotos)
//   - Renderizado del grid de thumbnails
//   - Reemplazar y eliminar fotos individuales
//   - Habilitar/deshabilitar el botón "Continuar"
//
// NO contiene lógica de pasos posteriores.
// ═══════════════════════════════════════════════════════════════

import { actions, getters, subscribe }  from '/lifebound/static/state.js';
import { readFileAsDataURL, filterValidImages,
         toast, confirm }               from '/lifebound/static/utils.js';
import { goTo, unlockStep, markDone }   from '/lifebound/static/nav.js';

// ───────────────────────────────────────────────────────────────
// INIT — punto de entrada, llamar una vez al cargar la página
// ───────────────────────────────────────────────────────────────

export function initUpload() {
  _bindDropZone();
  _bindFileInput();
  _bindContinueButton();

  // Cada vez que cambian las fotos, re-renderizar
  subscribe('photos', renderPhotoGrid);
  subscribe('photos', _updateHint);
  subscribe('photos', _updateContinueButton);
  subscribe('reset',  renderPhotoGrid);
}

// ───────────────────────────────────────────────────────────────
// MANEJO DE ARCHIVOS ENTRANTES
// ───────────────────────────────────────────────────────────────

/**
 * Punto de entrada principal para archivos nuevos.
 * Valida, deduplica, confirma reset si hace falta, y agrega al store.
 * @param {FileList|File[]} incoming
 */
export async function handleFiles(incoming) {
  const valid = filterValidImages(incoming);
  if (!valid.length) return;

  const currentCount  = getters.photoCount();
  const wouldChange   = currentCount !== (currentCount + valid.length);
  const hasPattern    = !!getters.pattern();

  // Si ya hay un patrón calculado, agregar fotos lo resetea
  if (hasPattern && wouldChange) {
    const ok = await confirm(
      'El patrón se va a resetear',
      'Agregar fotos borra el patrón actual y las respuestas del cuestionario.',
      'Resetear y continuar'
    );
    if (!ok) return;
    actions.resetFromStep3();
  }

  const added = actions.addPhotos(valid);

  if (!added) {
    toast('Esas fotos ya están agregadas', 'warn');
  } else {
    const total = getters.photoCount();
    toast(`${added} foto${added !== 1 ? 's' : ''} agregada${added !== 1 ? 's' : ''} — ${total} en total`, 'success');
  }
}

// ───────────────────────────────────────────────────────────────
// ELIMINAR FOTO
// ───────────────────────────────────────────────────────────────

async function _removePhoto(index) {
  if (getters.pattern()) {
    const ok = await confirm(
      'El patrón se va a resetear',
      'Eliminar una foto borra el patrón actual y las respuestas del cuestionario.',
      'Eliminar y resetear'
    );
    if (!ok) return;
    actions.resetFromStep3();
  }

  actions.removePhoto(index);
  toast('Foto eliminada', 'success');
}

// ───────────────────────────────────────────────────────────────
// REEMPLAZAR FOTO (desde el grid de upload, no desde preview)
// ───────────────────────────────────────────────────────────────

function _replacePhoto(index) {
  const input = document.createElement('input');
  input.type   = 'file';
  input.accept = 'image/*';

  input.onchange = async e => {
    const file = e.target.files[0];
    if (!file) return;

    const { valid, reason } = _validateSingleFile(file);
    if (!valid) { toast(reason, 'error'); return; }

    actions.replacePhoto(index, file);

    // Si ya hay un patrón, actualizar también el photoIdToFile
    if (getters.pattern()) {
      const grouping = getters.yearGrouping();
      for (const [yr, indices] of Object.entries(grouping)) {
        const n = indices.indexOf(index);
        if (n !== -1) {
          actions.replacePhotoById(`y${yr}-f${n + 1}`, file);
          break;
        }
      }
    }

    toast('Foto reemplazada ✓', 'success');
  };

  input.click();
}

// ───────────────────────────────────────────────────────────────
// RENDERIZADO DEL GRID
// ───────────────────────────────────────────────────────────────

/**
 * Renderiza el grid de thumbnails completo.
 * Llamado reactivamente por el store cuando cambian las fotos.
 */
export async function renderPhotoGrid() {
  const grid       = document.getElementById('pgrid');
  const processArea = document.getElementById('processArea');
  const countEl    = document.getElementById('photoCount');
  const files      = getters.photos();

  if (!grid) return;

  grid.innerHTML = '';
  const count = files.length;

  if (countEl) countEl.textContent = count;
  if (processArea) processArea.style.display = count > 0 ? 'block' : 'none';

  // Cargar todas las thumbnails en paralelo
  await Promise.allSettled(
    files.map((file, i) => _renderThumb(grid, file, i))
  );
}

async function _renderThumb(grid, file, index) {
  let dataURL;
  try {
    dataURL = await readFileAsDataURL(file);
  } catch {
    toast(`No se pudo cargar: ${file.name}`, 'error');
    return;
  }

  const thumb = document.createElement('div');
  thumb.className = 'photo-thumb';
  thumb.dataset.index = index;

  thumb.innerHTML = `
    <img src="${dataURL}" alt="${file.name}">
    <button class="photo-delete" title="Eliminar" data-action="remove" data-index="${index}">×</button>
    <button class="photo-rep-btn" title="Reemplazar" data-action="replace" data-index="${index}">↺</button>
    <div class="pip">✓</div>
  `;

  grid.appendChild(thumb);
}

// ───────────────────────────────────────────────────────────────
// HINT DE CANTIDAD
// ───────────────────────────────────────────────────────────────

function _updateHint() {
  const hint = document.getElementById('photoHint');
  if (!hint) return;

  const count = getters.photoCount();

  if (count < 15) {
    hint.textContent = `Faltan ${15 - count} fotos`;
    hint.style.color = 'var(--amber)';
  } else if (count > 80) {
    hint.textContent = 'Máximo 80 alcanzado';
    hint.style.color = 'var(--red)';
  } else {
    hint.textContent = `${count}/80 listas ✓`;
    hint.style.color = 'var(--green)';
  }
}

// ───────────────────────────────────────────────────────────────
// BOTÓN CONTINUAR
// ───────────────────────────────────────────────────────────────

function _updateContinueButton() {
  const btn   = document.getElementById('btnNext1');
  const count = getters.photoCount();
  if (btn) btn.disabled = !(count >= 15 && count <= 80);
}

function _bindContinueButton() {
  document.getElementById('btnNext1')
    ?.addEventListener('click', _proceedStep1);
}

function _proceedStep1() {
  markDone(1);
  unlockStep(2);
  goTo(2);
}

// ───────────────────────────────────────────────────────────────
// DRAG & DROP
// ───────────────────────────────────────────────────────────────

function _bindDropZone() {
  const zone = document.getElementById('uploadZone');
  if (!zone) return;

  zone.addEventListener('click', () =>
    document.getElementById('fileInput')?.click()
  );

  zone.addEventListener('dragover', e => {
    e.preventDefault();
    zone.classList.add('drag-over');
  });

  zone.addEventListener('dragleave', () =>
    zone.classList.remove('drag-over')
  );

  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    handleFiles(e.dataTransfer.files);
  });
}

// ───────────────────────────────────────────────────────────────
// FILE INPUT (click para seleccionar)
// ───────────────────────────────────────────────────────────────

function _bindFileInput() {
  const input = document.getElementById('fileInput');
  if (!input) return;

  input.addEventListener('change', e => {
    handleFiles(e.target.files);
    // Reset para permitir seleccionar el mismo archivo de nuevo
    e.target.value = '';
  });
}

// ───────────────────────────────────────────────────────────────
// DELEGACIÓN DE EVENTOS EN EL GRID
// Un solo listener para todos los botones de eliminar/reemplazar
// En vez de poner onclick en cada thumbnail (patrón del monolito)
// ───────────────────────────────────────────────────────────────

export function bindGridEvents() {
  const grid = document.getElementById('pgrid');
  if (!grid) return;

  grid.addEventListener('click', e => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;

    const action = btn.dataset.action;
    const index  = parseInt(btn.dataset.index);

    if (action === 'remove')  _removePhoto(index);
    if (action === 'replace') _replacePhoto(index);
  });
}

// ───────────────────────────────────────────────────────────────
// VALIDACIÓN INTERNA
// ───────────────────────────────────────────────────────────────

function _validateSingleFile(file, maxMB = 15) {
  const allowed = ['image/jpeg', 'image/png'];
  if (!allowed.includes(file.type)) {
    return { valid: false, reason: `Formato no soportado: ${file.name}` };
  }
  if (file.size > maxMB * 1024 * 1024) {
    return { valid: false, reason: `Archivo muy grande (máx ${maxMB}MB): ${file.name}` };
  }
  return { valid: true };
}