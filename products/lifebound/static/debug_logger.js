/**
 * debug-logger.js — Lifebound Frontend Tracer
 * ─────────────────────────────────────────────
 * Cómo usar:
 *   1. Abre DevTools (F12) → pestaña Console
 *   2. Pega TODO este archivo y presiona Enter
 *   3. Usa la app normalmente — todo quedará trazado en consola
 *   4. Para detener: escribe  __LB_STOP__()  en la consola
 *
 * También puedes cargarlo como script en index.html (antes del cierre </body>):
 *   <script src="/lifebound/static/debug-logger.js"></script>
 */

(function () {
  if (window.__LB_LOGGER_ACTIVE__) {
    console.warn('[LB-DEBUG] Logger ya activo. Detén primero con __LB_STOP__()');
    return;
  }
  window.__LB_LOGGER_ACTIVE__ = true;

  // ── Paleta de colores por categoría ──────────────────────────────────────
  const C = {
    click:   'background:#1a3a5c;color:#7ec8e3;padding:2px 6px;border-radius:3px;font-weight:bold',
    input:   'background:#1a3a1a;color:#7ee37e;padding:2px 6px;border-radius:3px;font-weight:bold',
    change:  'background:#3a2a1a;color:#e3b97e;padding:2px 6px;border-radius:3px;font-weight:bold',
    nav:     'background:#3a1a5c;color:#c87ef5;padding:2px 6px;border-radius:3px;font-weight:bold',
    event:   'background:#1a3a3a;color:#7ee3e3;padding:2px 6px;border-radius:3px;font-weight:bold',
    fetch:   'background:#3a3a1a;color:#e3e37e;padding:2px 6px;border-radius:3px;font-weight:bold',
    error:   'background:#5c1a1a;color:#f57e7e;padding:2px 6px;border-radius:3px;font-weight:bold',
    warn:    'background:#3a2a00;color:#ffcc44;padding:2px 6px;border-radius:3px;font-weight:bold',
    state:   'background:#2a1a3a;color:#d0a0ff;padding:2px 6px;border-radius:3px;font-weight:bold',
    module:  'background:#003a2a;color:#00e5a0;padding:2px 6px;border-radius:3px;font-weight:bold',
  };

  const listeners = [];   // para poder limpiarlos al detener
  const origDispatch = document.dispatchEvent.bind(document);

  function ts() {
    const d = new Date();
    return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}.${String(d.getMilliseconds()).padStart(3,'0')}`;
  }

  function label(cat) { return `%c[LB ${ts()}] ${cat.toUpperCase()}`; }

  // ── 1. CLICKS ─────────────────────────────────────────────────────────────
  function onGlobalClick(e) {
    const t = e.target;
    const id   = t.id   ? `#${t.id}`   : '';
    const cls  = t.className && typeof t.className === 'string'
      ? '.' + t.className.trim().split(/\s+/).join('.') : '';
    const text = t.textContent?.trim().slice(0, 40) || '';
    const tag  = t.tagName.toLowerCase();
    console.log(
      label('click') + ` ${tag}${id}${cls}`,
      C.click,
      { text, disabled: t.disabled || false, el: t }
    );
  }
  document.addEventListener('click', onGlobalClick, true);
  listeners.push(['click', onGlobalClick, true]);

  // ── 2. INPUTS ─────────────────────────────────────────────────────────────
  function onGlobalInput(e) {
    const t = e.target;
    const id    = t.id ? `#${t.id}` : '';
    const name  = t.name  ? `[name=${t.name}]`  : '';
    const ip    = t.dataset?.ip ? `[data-ip=${t.dataset.ip}]` : '';
    const fi    = t.dataset?.if ? `[data-if=${t.dataset.if}]` : '';
    const val   = t.value?.slice(0, 80) || '';
    console.log(
      label('input') + ` ${t.tagName.toLowerCase()}${id}${name}${ip}${fi}`,
      C.input,
      { value: val, el: t }
    );
  }
  document.addEventListener('input', onGlobalInput, true);
  listeners.push(['input', onGlobalInput, true]);

  // ── 3. CHANGE (selects, checkboxes, file inputs) ──────────────────────────
  function onGlobalChange(e) {
    const t = e.target;
    const id  = t.id ? `#${t.id}` : '';
    let val;
    if (t.type === 'checkbox')   val = t.checked;
    else if (t.type === 'file')  val = `[${t.files.length} file(s)]`;
    else                         val = t.value?.slice(0, 80);
    console.log(
      label('change') + ` ${t.tagName.toLowerCase()}${id} [${t.type || 'select'}]`,
      C.change,
      { value: val, el: t }
    );
  }
  document.addEventListener('change', onGlobalChange, true);
  listeners.push(['change', onGlobalChange, true]);

  // ── 4. DRAG & DROP ────────────────────────────────────────────────────────
  ['dragover','dragleave','drop'].forEach(evt => {
    const fn = e => {
      const t = e.target;
      const id = t.id ? `#${t.id}` : t.className?.toString().slice(0,30) || '';
      console.log(label('event') + ` ${evt} → ${id}`, C.event,
        evt === 'drop' ? { files: e.dataTransfer?.files?.length } : {});
    };
    document.addEventListener(evt, fn, true);
    listeners.push([evt, fn, true]);
  });

  // ── 5. CUSTOM EVENTS (app:*) ──────────────────────────────────────────────
  const _origDispatch = document.dispatchEvent;
  document.dispatchEvent = function (evt) {
    if (evt.type.startsWith('app:') || evt.type.startsWith('grouping:')) {
      console.log(label('event') + ` CustomEvent: ${evt.type}`, C.event,
        evt.detail ? { detail: evt.detail } : {});
    }
    return _origDispatch.call(this, evt);
  };

  // ── 6. FETCH intercept ────────────────────────────────────────────────────
  const _origFetch = window.fetch;
  window.fetch = async function (...args) {
    const url    = typeof args[0] === 'string' ? args[0] : args[0]?.url || '?';
    const method = args[1]?.method || 'GET';
    const t0     = performance.now();
    console.log(label('fetch') + ` ▶ ${method} ${url}`, C.fetch);
    try {
      const res  = await _origFetch(...args);
      const ms   = (performance.now() - t0).toFixed(0);
      const ok   = res.ok;
      console.log(
        label('fetch') + ` ${ok ? '✅' : '❌'} ${method} ${url} → ${res.status} (${ms}ms)`,
        ok ? C.fetch : C.error
      );
      return res;
    } catch (err) {
      const ms = (performance.now() - t0).toFixed(0);
      console.error(label('fetch') + ` 💥 ${method} ${url} FAILED (${ms}ms)`, C.error, err);
      throw err;
    }
  };

  // ── 7. ERRORES JS no capturados ───────────────────────────────────────────
  function onError(e) {
    console.error(
      label('error') + ` Uncaught: ${e.message}`,
      C.error,
      { file: e.filename, line: e.lineno, col: e.colno, error: e.error }
    );
  }
  window.addEventListener('error', onError);
  listeners.push(['__window_error__', onError]);

  function onUnhandledRejection(e) {
    console.error(
      label('error') + ` Unhandled Promise Rejection`,
      C.error,
      { reason: e.reason }
    );
  }
  window.addEventListener('unhandledrejection', onUnhandledRejection);
  listeners.push(['__unhandled_rejection__', onUnhandledRejection]);

  // ── 8. ESTADO — snapshot de S cada vez que cambia el step ────────────────
  function onStepChange() {
    const appS = window.S || window._app?.S;
    if (!appS) return;
    console.groupCollapsed(
      label('state') + ` S snapshot @ step ${appS.currentStep}`,
      C.state
    );
    console.log('validFiles:',       appS.validFiles?.length);
    console.log('yearGrouping:',     appS.yearGrouping);
    console.log('currentPattern:',   appS.currentPattern?.pattern_id || null);
    console.log('introData:',        appS.introData);
    console.log('receipts:',         appS.receipts);
    console.log('qData:',            appS.qData);
    console.log('unlockedSteps:',    [...(appS.unlockedSteps || [])]);
    console.groupEnd();
  }

  // Hookeamos los eventos de navegación de step
  const stepEvts = ['app:step2Done','app:step3Done','app:step4Done','app:step5Done','app:step6Done','app:buildPreview'];
  stepEvts.forEach(evt => {
    const fn = () => setTimeout(onStepChange, 50);
    document.addEventListener(evt, fn);
    listeners.push([evt, fn]);
  });

  // ── 9. MÓDULOS — rastreo de init ─────────────────────────────────────────
  const _orig_addEventListener = document.addEventListener.bind(document);
  // (ya hookeamos lo que necesitamos; esto es informativo)

  // ── 10. MUTATION OBSERVER — detecta cambios de paso activo ───────────────
  const stepObs = new MutationObserver(mutations => {
    mutations.forEach(m => {
      if (m.type === 'attributes' && m.attributeName === 'class') {
        const el = m.target;
        if (el.classList.contains('step') && el.classList.contains('active')) {
          const id = el.id || el.className;
          console.log(label('nav') + ` Step activado: ${id}`, C.nav, { el });
        }
        if (el.classList.contains('nav-item') && el.classList.contains('active')) {
          const id = el.id || el.textContent?.trim().slice(0,30);
          console.log(label('nav') + ` NavItem activo: ${id}`, C.nav);
        }
      }
    });
  });
  stepObs.observe(document.body, { subtree: true, attributes: true, attributeFilter: ['class'] });

  // ── STOP ──────────────────────────────────────────────────────────────────
  window.__LB_STOP__ = function () {
    listeners.forEach(([evt, fn, capture]) => {
      if (evt === '__window_error__')        window.removeEventListener('error', fn);
      else if (evt === '__unhandled_rejection__') window.removeEventListener('unhandledrejection', fn);
      else document.removeEventListener(evt, fn, capture);
    });
    document.dispatchEvent = _origDispatch;
    window.fetch            = _origFetch;
    stepObs.disconnect();
    window.__LB_LOGGER_ACTIVE__ = false;
    console.log('%c[LB-DEBUG] Logger detenido ✓', 'color:#aaa');
  };

  // ── Banner inicial ────────────────────────────────────────────────────────
  console.log(
    '%c[LB-DEBUG] Logger activo ✓',
    'background:#1a1a2e;color:#7ec8e3;font-size:13px;padding:4px 10px;border-radius:4px;font-weight:bold'
  );
  console.log('%c  Rastreando: clicks · inputs · change · drag/drop · fetch · app:events · errores JS · cambios de step',
    'color:#888;font-size:11px');
  console.log('%c  Para detener: __LB_STOP__()', 'color:#888;font-size:11px');

})();