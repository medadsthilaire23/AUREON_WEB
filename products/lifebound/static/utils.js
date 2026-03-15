// ═══════════════════════════════════════════════════════════════
// utils.js — Herramientas base compartidas por todos los módulos
//
// Ninguna función aquí toca el DOM de la app ni el store.
// Son utilidades puras e independientes.
// ═══════════════════════════════════════════════════════════════

// ───────────────────────────────────────────────────────────────
// FILE READER — FileReader con Promises y manejo de errores
// El monolito tenía ~15 instancias de FileReader sin .onerror
// ───────────────────────────────────────────────────────────────

/**
 * Lee un File y devuelve un data URL (base64).
 * @param {File} file
 * @returns {Promise<string>} data URL
 */
export function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = e => resolve(e.target.result);
    reader.onerror = () => reject(new Error(`No se pudo leer el archivo: ${file.name}`));
    reader.readAsDataURL(file);
  });
}

/**
 * Lee múltiples archivos en paralelo.
 * @param {File[]} files
 * @returns {Promise<{file: File, dataURL: string}[]>}
 */
export async function readFilesAsDataURLs(files) {
  return Promise.all(
    files.map(async file => ({
      file,
      dataURL: await readFileAsDataURL(file),
    }))
  );
}

// ───────────────────────────────────────────────────────────────
// IMAGE PROCESSOR — Compresión y resize de imágenes para el PDF
// Antes vivía dentro de generatePDF(), imposible de testear sola
// ───────────────────────────────────────────────────────────────

/**
 * Comprime un File de imagen a las dimensiones del identity map.
 * Mantiene el aspect ratio con cover (recorta, no deforma).
 *
 * @param {File}   file     - Archivo de imagen original
 * @param {{ w: number, h: number }} dims - Dimensiones destino
 * @param {number} [quality=0.88] - Calidad JPEG (0-1)
 * @returns {Promise<Blob>} - Blob JPEG comprimido
 */
export function compressImage(file, dims, quality = 0.88) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const objectURL = URL.createObjectURL(file);

    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width  = dims.w;
      canvas.height = dims.h;

      const ctx = canvas.getContext('2d');
      const scale = Math.max(dims.w / img.width, dims.h / img.height);
      const drawW = img.width  * scale;
      const drawH = img.height * scale;
      const offsetX = (dims.w - drawW) / 2;
      const offsetY = (dims.h - drawH) / 2;

      ctx.drawImage(img, offsetX, offsetY, drawW, drawH);

      canvas.toBlob(
        blob => {
          URL.revokeObjectURL(objectURL);
          if (blob) resolve(blob);
          else reject(new Error(`No se pudo comprimir: ${file.name}`));
        },
        'image/jpeg',
        quality
      );
    };

    img.onerror = () => {
      URL.revokeObjectURL(objectURL);
      reject(new Error(`Imagen inválida: ${file.name}`));
    };

    img.src = objectURL;
  });
}

/**
 * Comprime un mapa de { photoId: File } en paralelo.
 * Salta los IDs sin dimensiones en el identityMap.
 *
 * @param {Object} photoIdToFile   - { pid: File }
 * @param {Object} identityMap     - { pid: { w, h } }
 * @param {number} [quality=0.88]
 * @returns {Promise<Object>}      - { pid: Blob }
 */
export async function compressAllImages(photoIdToFile, identityMap, quality = 0.88) {
  const entries = Object.entries(photoIdToFile).filter(([pid]) => identityMap[pid]);

  const results = await Promise.all(
    entries.map(async ([pid, file]) => {
      const blob = await compressImage(file, identityMap[pid], quality);
      return [pid, blob];
    })
  );

  return Object.fromEntries(results);
}

// ───────────────────────────────────────────────────────────────
// TOAST — Notificaciones no bloqueantes
// ───────────────────────────────────────────────────────────────

const TOAST_ICONS = {
  success: '✅',
  error:   '❌',
  warn:    '⚠️',
  info:    '◈',
};

/**
 * Muestra una notificación temporal.
 * @param {string} msg
 * @param {'success'|'error'|'warn'|'info'} [type='info']
 * @param {number} [duration=3500]
 */
export function toast(msg, type = 'info', duration = 3500) {
  const stack = document.getElementById('toastStack');
  if (!stack) return;

  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<span>${TOAST_ICONS[type] ?? '◈'}</span><span>${msg}</span>`;

  stack.appendChild(el);
  setTimeout(() => el.remove(), duration);
}

// ───────────────────────────────────────────────────────────────
// CONFIRM — Diálogo de confirmación como Promise
// Antes el monolito usaba S._confResolve, un callback global frágil
// ───────────────────────────────────────────────────────────────

let _activeResolve = null;

/**
 * Muestra el diálogo de confirmación y devuelve una Promise.
 * @param {string} title
 * @param {string} message
 * @param {string} [okLabel='Continuar']
 * @returns {Promise<boolean>}
 */
export function confirm(title, message, okLabel = 'Continuar') {
  return new Promise(resolve => {
    _activeResolve = resolve;

    const overlay = document.getElementById('confOv');
    const titleEl = document.getElementById('confTitle');
    const msgEl   = document.getElementById('confMsg');
    const okBtn   = document.getElementById('confOkBtn');

    if (!overlay) { resolve(false); return; }

    titleEl.textContent = title;
    msgEl.textContent   = message;
    okBtn.textContent   = okLabel;

    overlay.classList.add('show');
  });
}

/** Llamado por el botón OK del diálogo. */
export function confirmAccept() {
  document.getElementById('confOv')?.classList.remove('show');
  _activeResolve?.(true);
  _activeResolve = null;
}

/** Llamado por el botón Cancelar del diálogo. */
export function confirmReject() {
  document.getElementById('confOv')?.classList.remove('show');
  _activeResolve?.(false);
  _activeResolve = null;
}

// ───────────────────────────────────────────────────────────────
// LOADING OVERLAY
// ───────────────────────────────────────────────────────────────

export function showLoad(title, subtitle = '') {
  const ov = document.getElementById('loadOv');
  if (!ov) return;
  document.getElementById('loadTitle').textContent = title;
  document.getElementById('loadSub').textContent   = subtitle;
  ov.classList.add('show');
}

export function hideLoad() {
  document.getElementById('loadOv')?.classList.remove('show');
}

// ───────────────────────────────────────────────────────────────
// DOM HELPERS
// ───────────────────────────────────────────────────────────────

/**
 * Crea un elemento con atributos y contenido opcionales.
 * @param {string} tag
 * @param {Object} [attrs={}]
 * @param {string} [innerHTML='']
 * @returns {HTMLElement}
 *
 * @example
 * const btn = el('button', { class: 'btn btn-primary' }, 'Guardar');
 */
export function el(tag, attrs = {}, innerHTML = '') {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => {
    if (k === 'class') node.className = v;
    else if (k === 'data') Object.entries(v).forEach(([dk, dv]) => node.dataset[dk] = dv);
    else node.setAttribute(k, v);
  });
  if (innerHTML) node.innerHTML = innerHTML;
  return node;
}

export function clearEl(target) {
  const node = typeof target === 'string' ? document.querySelector(target) : target;
  if (node) node.innerHTML = '';
}

export function setDisabled(id, disabled) {
  const btn = document.getElementById(id);
  if (btn) btn.disabled = disabled;
}

// ───────────────────────────────────────────────────────────────
// VALIDATION HELPERS
// ───────────────────────────────────────────────────────────────

/**
 * Valida que un archivo sea imagen JPG/PNG y no supere el tamaño máximo.
 * @param {File} file
 * @param {number} [maxMB=15]
 * @returns {{ valid: boolean, reason?: string }}
 */
export function validateImageFile(file, maxMB = 15) {
  const allowed = ['image/jpeg', 'image/png'];
  if (!allowed.includes(file.type)) {
    return { valid: false, reason: `Formato no soportado: ${file.name}` };
  }
  if (file.size > maxMB * 1024 * 1024) {
    return { valid: false, reason: `Archivo muy grande (máx ${maxMB}MB): ${file.name}` };
  }
  return { valid: true };
}

/**
 * Filtra una lista de Files, retornando solo los válidos.
 * Llama a toast() por cada archivo rechazado.
 * @param {File[]} files
 * @returns {File[]}
 */
export function filterValidImages(files) {
  return Array.from(files).filter(file => {
    const { valid, reason } = validateImageFile(file);
    if (!valid) toast(reason, 'error');
    return valid;
  });
}