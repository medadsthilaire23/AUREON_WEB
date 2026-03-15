// ═══════════════════════════════════════════════════════════════
// nav.js — Navegación entre pasos y estado de la sidebar
//
// Responsabilidades:
//   - Mover el usuario entre pasos (goTo, tryGoTo)
//   - Actualizar la sidebar, progress bar y topbar
//   - Manejar el toggle del sidebar
//   - Marcar pasos como completados
//
// NO contiene lógica de negocio de ningún paso.
// ═══════════════════════════════════════════════════════════════

import { actions, getters, subscribe } from './state.js';

// ───────────────────────────────────────────────────────────────
// CONSTANTES
// ───────────────────────────────────────────────────────────────

const STEP_NAMES = [
  '',                // índice 0 no existe
  'Upload Photos',
  'Applicant Info',
  'Group by Year',
  'Questionnaire',
  'Preview',
  'Generate',
];

const TOTAL_STEPS = 6;

// ───────────────────────────────────────────────────────────────
// NAVEGACIÓN PRINCIPAL
// ───────────────────────────────────────────────────────────────

/**
 * Intenta navegar a un paso. Si está bloqueado, no hace nada.
 * Es la función que usan los nav-items del sidebar.
 * @param {number} step
 */
export function tryGoTo(step) {
  if (!getters.isUnlocked(step)) return;
  goTo(step);
}

/**
 * Navega incondicionalmente a un paso (uso interno de los pasos).
 * @param {number} step
 */
export function goTo(step) {
  // Ocultar todos los pasos, mostrar el activo
  for (let i = 1; i <= TOTAL_STEPS; i++) {
    document.getElementById(`step${i}`)?.classList.toggle('active', i === step);
  }

  actions.setCurrentStep(step);
  _updateSidebar(step);
  _updateTopbar(step);
  _updateProgressBar(step);

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/**
 * Desbloquea un paso y lo hace navegable en el sidebar.
 * @param {number} step
 */
export function unlockStep(step) {
  actions.unlockStep(step);
  document.getElementById(`nav${step}`)?.classList.remove('locked');
}

/**
 * Marca un paso como completado (muestra ✓ en el sidebar).
 * @param {number} step
 */
export function markDone(step) {
  const chk = document.getElementById(`chk${step}`);
  if (chk) chk.textContent = '✓';

  const seg = document.getElementById(`ps${step}`);
  seg?.classList.remove('active');
  seg?.classList.add('done');
}

// ───────────────────────────────────────────────────────────────
// SIDEBAR TOGGLE
// ───────────────────────────────────────────────────────────────

export function toggleSidebar() {
  const sidebar   = document.getElementById('sidebar');
  const mainWrap  = document.getElementById('mainWrap');
  const spans     = document.getElementById('sbToggle')?.querySelectorAll('span') ?? [];

  const collapsed = sidebar.classList.toggle('collapsed');
  mainWrap.classList.toggle('expanded', collapsed);

  if (collapsed) {
    spans[0].style.cssText = 'transform:translateY(5.5px) rotate(45deg)';
    spans[1].style.cssText = 'opacity:0;transform:scaleX(0)';
    spans[2].style.cssText = 'transform:translateY(-5.5px) rotate(-45deg)';
  } else {
    spans.forEach(s => s.style.cssText = '');
  }
}

// ───────────────────────────────────────────────────────────────
// ACTUALIZACIONES DE UI — privadas, solo llamadas por goTo()
// ───────────────────────────────────────────────────────────────

function _updateSidebar(activeStep) {
  const unlocked = getters.unlockedSteps();

  for (let i = 1; i <= TOTAL_STEPS; i++) {
    const item = document.getElementById(`nav${i}`);
    if (!item) continue;

    item.classList.remove('active', 'locked');

    if (i === activeStep) {
      item.classList.add('active');
    } else if (!unlocked.has(i)) {
      item.classList.add('locked');
    }
  }
}

function _updateTopbar(step) {
  const stepInd  = document.getElementById('stepInd');
  const stepName = document.getElementById('stepName');
  const pLabel   = document.getElementById('pLabel');

  const label = `Step ${step} of ${TOTAL_STEPS}`;
  if (stepInd)  stepInd.textContent  = label;
  if (pLabel)   pLabel.textContent   = label;
  if (stepName) stepName.textContent = STEP_NAMES[step] ?? '';
}

function _updateProgressBar(activeStep) {
  for (let i = 1; i <= TOTAL_STEPS; i++) {
    const seg = document.getElementById(`ps${i}`);
    if (!seg) continue;

    seg.classList.remove('active', 'done');

    // Un segmento es 'done' si ya tiene el checkmark (markDone lo puso)
    const chk = document.getElementById(`chk${i}`);
    const isDone = chk?.textContent === '✓';

    if (isDone && i !== activeStep) {
      seg.classList.add('done');
    } else if (i === activeStep) {
      seg.classList.add('active');
    }
  }
}

// ───────────────────────────────────────────────────────────────
// REACTIVIDAD — sincronizar el badge de fotos con el store
// ───────────────────────────────────────────────────────────────

subscribe('photos', () => {
  const badge = document.getElementById('photoBadge');
  if (badge) badge.textContent = getters.photoCount() + ' fotos';
});

// ───────────────────────────────────────────────────────────────
// INIT — conectar eventos del DOM al módulo
// Llamar una vez desde el script principal (main.js o index.html)
// ───────────────────────────────────────────────────────────────

export function initNav() {
  // Botón hamburguesa
  document.getElementById('sbToggle')
    ?.addEventListener('click', toggleSidebar);

  // Nav items del sidebar — delegación de eventos
  document.getElementById('sidebar')
    ?.addEventListener('click', e => {
      const item = e.target.closest('.nav-item');
      if (!item) return;
      const step = parseInt(item.id.replace('nav', ''));
      if (step) tryGoTo(step);
    });
}