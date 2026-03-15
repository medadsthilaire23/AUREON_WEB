// ═══════════════════════════════════════════════════════════════
// main.js — Punto de entrada de la aplicación
//
// Responsabilidad única: importar todos los módulos,
// inicializarlos en orden y conectar los eventos globales.
//
// Si algo falla al arrancar, el error aparece aquí — no
// enterrado en el medio de una función de 400 líneas.
// ═══════════════════════════════════════════════════════════════

import { initNav, goTo }               from '/lifebound/static/nav.js';
import { initUpload, bindGridEvents }  from '/lifebound/static/upload.js';
import { initApplicant }               from '/lifebound/static/applicant.js';
import { initGrouping }                from '/lifebound/static/grouping.js';
import { initQuestionnaire,
         renderQuestionnaire }         from '/lifebound/static/questionnaire.js';
import { initPreview, buildPreview,
         buildPageIndex,
         closeReplaceModal }           from '/lifebound/static/preview.js';
import { initGenerate, buildSummary }  from '/lifebound/static/generate.js';
import { confirmAccept,
         confirmReject }               from '/lifebound/static/utils.js';
import { subscribe }                   from '/lifebound/static/state.js';

// ───────────────────────────────────────────────────────────────
// ARRANQUE
// ───────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  // 1. Navegación — primero, otros módulos dependen de goTo/unlockStep
  initNav();

  // 2. Pasos en orden
  initUpload();
  bindGridEvents();
  initApplicant();
  initGrouping();
  initQuestionnaire();
  initPreview();
  initGenerate();

  // 3. Eventos globales del DOM que los módulos exponen
  _bindGlobalEvents();

  // 4. Reactividad cross-módulo:
  //    Cuando el patrón llega del servidor (paso 3 → 4),
  //    renderizar el cuestionario automáticamente
  subscribe('pattern', () => {
    renderQuestionnaire();
  });

  //    Cuando se navega al paso 5, reconstruir el preview
  subscribe('nav', () => {
    const step = document.querySelector('.step.active')?.id;
    if (step === 'step5') buildPreview();
    if (step === 'step6') buildSummary();
  });

  console.log('[Lifebound] App inicializada ✓');
});

// ───────────────────────────────────────────────────────────────
// EVENTOS GLOBALES
// Botones del HTML que no pertenecen a un módulo específico
// ───────────────────────────────────────────────────────────────

function _bindGlobalEvents() {
  // Confirm dialog
  document.getElementById('confOkBtn')
    ?.addEventListener('click', confirmAccept);

  document.getElementById('confCancelBtn')
    ?.addEventListener('click', confirmReject);

  // Replace modal — botón cerrar
  document.querySelector('#replaceModal .btn-secondary')
    ?.addEventListener('click', closeReplaceModal);
}