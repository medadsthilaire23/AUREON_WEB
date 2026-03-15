// ═══════════════════════════════════════════════════════════════
// applicant.js — Paso 2: Información del solicitante
//
// Comportamiento clave:
//   Cuando el usuario llena un campo compartido en cualquier tab,
//   el mismo valor se copia automáticamente a los campos idénticos
//   de las otras tabs — sin que el usuario tenga que repetirlo.
// ═══════════════════════════════════════════════════════════════

import { actions, getters, queries, subscribe } from '/lifebound/static/state.js';
import { el, toast }                            from '/lifebound/static/utils.js';
import { goTo, unlockStep, markDone }           from '/lifebound/static/nav.js';

// ───────────────────────────────────────────────────────────────
// CONSTANTES
// ───────────────────────────────────────────────────────────────

const N_FORMS = ['N-400', 'N-600', 'N-565', 'N-336'];
const I_FORMS = ['I-130', 'I-131', 'I-485', 'I-751', 'I-765', 'I-90', 'I-129F', 'I-864'];
const ALL_PAGES = ['cover', 'letter', 'id'];

// Campos que se comparten entre páginas y a cuáles se propagan
const SHARED_FIELDS = {
  name:           ['cover', 'letter', 'id'],
  spouse:         ['cover', 'letter', 'id'],
  address:        ['cover', 'letter', 'id'],
  interview_date: ['cover', 'id'],
  interview_time: ['cover', 'id'],
  a_number:       ['letter', 'id'],
  office:         ['cover', 'letter'],
};

const REQUIRED = {
  cover:  ['name', 'spouse'],
  letter: [],
  id:     ['name', 'spouse'],
};

const DOC_SECTIONS = {
  letter: [
    { label: '1. Identification Documents', items: [
      { label: 'Permanent Resident Card',        type: 'item' },
      { label: 'EAD & I-512 ID Card',            type: 'text', placeholder: 'Card #' },
      { label: 'Driver License',                 type: 'item' },
      { label: 'Foreign Passport',               type: 'item' },
      { label: 'Birth Certificate',              type: 'item' },
      { label: 'Social Security Card',           type: 'item' },
    ]},
    { label: '2. Joint Financials & Cohabitation', items: [
      { label: 'Joint Tax Returns',              type: 'text', placeholder: 'e.g. 2020-2024' },
      { label: 'Joint Bank Account Statements',  type: 'item' },
      { label: 'Health & Life Insurance',        type: 'item' },
      { label: 'Car Insurance',                  type: 'item' },
      { label: 'Joint Mortgage / Rent Receipts', type: 'item' },
    ]},
    { label: '3. Photographic Evidence', items: [] },
  ],
  id: [
    { label: '— Applicant', items: [
      { label: 'Permanent Resident Card',        type: 'item' },
      { label: 'EAD & I-512 ID Card',            type: 'text', placeholder: 'Card #' },
      { label: 'Driver License',                 type: 'item' },
      { label: 'Foreign Passport',               type: 'item' },
      { label: 'Birth Certificate',              type: 'item' },
      { label: 'Social Security Card',           type: 'item' },
    ]},
    { label: '— USC Spouse', items: [
      { label: 'Driver License',                 type: 'item' },
      { label: 'Birth Certificate',              type: 'item' },
      { label: 'US Passport',                    type: 'item' },
      { label: 'Social Security Card',           type: 'item' },
    ]},
    { label: '4. Marriage Certificate', items: [] },
  ],
};

// ───────────────────────────────────────────────────────────────
// INIT
// ───────────────────────────────────────────────────────────────

export function initApplicant() {
  // Un solo listener para todos los campos de texto del paso 2
  document.getElementById('step2')
    ?.addEventListener('input', e => {
      const inp = e.target.closest('[data-ip][data-if]');
      if (inp) _saveIntroField(inp);
    });

  // Tabs
  document.getElementById('step2')
    ?.addEventListener('click', e => {
      const tab = e.target.closest('.info-tab[data-tab]');
      if (tab) switchInfoTab(tab.dataset.tab);

      // Botones de navegación entre tabs (← Cover Page, etc.)
      const navBtn = e.target.closest('button[data-tab]:not(.info-tab)');
      if (navBtn) switchInfoTab(navBtn.dataset.tab);
    });

  document.getElementById('btnNext2')?.addEventListener('click', _proceedStep2);
  document.getElementById('btnBack2')?.addEventListener('click', () => goTo(1));

  // Receipts y doc-lists
  ALL_PAGES.forEach(pgId => _buildReceiptToggles(pgId));
  ['letter', 'id'].forEach(pgId => _buildDocList(pgId));

  // Reactividad
  subscribe('receipts', _autoUpdateAttnAndTitle);
  subscribe('receipts', () => ALL_PAGES.forEach(_updateCompleteness));
  subscribe('intro',    () => ALL_PAGES.forEach(_updateCompleteness));

  ALL_PAGES.forEach(_updateCompleteness);
}

// ───────────────────────────────────────────────────────────────
// GUARDAR CAMPO — propaga automáticamente a otras tabs si es compartido
// ───────────────────────────────────────────────────────────────

function _saveIntroField(input) {
  const page  = input.dataset.ip;
  const field = input.dataset.if;
  const value = input.value;

  // Guardar en la página actual
  actions.setIntroField(page, field, value);

  // Si el campo es compartido, propagarlo a las otras páginas
  const sharedPages = SHARED_FIELDS[field];
  if (sharedPages) {
    sharedPages.forEach(pg => {
      if (pg === page) return;

      // Actualizar el store
      actions.setIntroField(pg, field, value);

      // Actualizar el input en el DOM de la otra tab
      document.querySelectorAll(
        `#step2 [data-ip="${pg}"][data-if="${field}"]`
      ).forEach(otherInput => {
        if (otherInput !== input) otherInput.value = value;
      });
    });
  }

  _updateCompleteness(page);
}

// ───────────────────────────────────────────────────────────────
// TABS
// ───────────────────────────────────────────────────────────────

export function switchInfoTab(tabId) {
  document.querySelectorAll('.info-tab[data-tab]').forEach(t =>
    t.classList.toggle('active', t.dataset.tab === tabId)
  );
  document.querySelectorAll('.info-page').forEach(p =>
    p.classList.toggle('active', p.id === `ipage_${tabId}`)
  );
}

// ───────────────────────────────────────────────────────────────
// COMPLETENESS
// ───────────────────────────────────────────────────────────────

function _updateCompleteness(pgId) {
  const required = REQUIRED[pgId] ?? [];
  const data     = getters.introPage(pgId);
  const isOk     = required.length === 0 ||
                   required.every(f => (data[f] ?? '').trim());
  const optional = required.length === 0;

  const badge = document.getElementById(`icomp_${pgId}`);
  if (badge) {
    badge.textContent = optional ? 'Optional fields'
      : isOk ? '✓ Complete' : 'Required fields missing';
    badge.className = `info-completeness ${isOk || optional ? 'ok' : 'partial'}`;
  }

  const tab = document.getElementById(`itab_${pgId}`);
  if (tab) {
    tab.classList.toggle('complete', isOk || optional);
    tab.classList.toggle('partial',  !isOk && !optional);
  }
}

// ───────────────────────────────────────────────────────────────
// RECEIPTS
// ───────────────────────────────────────────────────────────────

function _buildReceiptToggles(pgId) {
  ['n', 'i'].forEach(series => {
    const forms    = series === 'n' ? N_FORMS : I_FORMS;
    const btnsEl   = document.getElementById(`${series}btns_${pgId}`);
    const fieldsEl = document.getElementById(`${series}fields_${pgId}`);
    if (!btnsEl || !fieldsEl) return;

    btnsEl.innerHTML = '';
    forms.forEach(form => {
      const isOn = getters.receiptsFor(pgId)[form] !== undefined;
      const btn  = el('button', {
        class: `receipt-toggle${isOn ? ' on' : ''}`,
        type:  'button',
      }, form);

      btn.addEventListener('click', () => {
        // Togglear en TODAS las páginas para mantenerlas sincronizadas
        ALL_PAGES.forEach(pg => actions.toggleReceipt(pg, form));
        btn.classList.toggle('on');
        // Refrescar los campos de receipt en TODAS las tabs
        ALL_PAGES.forEach(pg => {
          ['n', 'i'].forEach(s => {
            const fe = document.getElementById(`${s}fields_${pg}`);
            if (fe) _renderReceiptFields(pg, s, fe);
            _updateReceiptCount(pg, s);
          });
        });
      });

      btnsEl.appendChild(btn);
    });

    _renderReceiptFields(pgId, series, fieldsEl);
    _updateReceiptCount(pgId, series);
  });
}

function _renderReceiptFields(pgId, series, fieldsEl) {
  const forms    = series === 'n' ? N_FORMS : I_FORMS;
  const receipts = getters.receiptsFor(pgId);
  fieldsEl.innerHTML = '';

  forms.filter(f => receipts[f] !== undefined).forEach(form => {
    const row = el('div', { class: 'receipt-field-row' });
    const lbl = el('span', { class: 'receipt-field-label' }, form);
    const inp = el('input', {
      type:        'text',
      class:       'receipt-field-input',
      placeholder: 'IOE0000000000',
      value:       receipts[form] ?? '',
    });

    inp.addEventListener('input', () => {
      // Actualizar en TODAS las páginas simultáneamente
      ALL_PAGES.forEach(pg => actions.setReceiptNumber(pg, form, inp.value));
      // Sincronizar el valor en los otros inputs del mismo form
      ALL_PAGES.forEach(pg => {
        if (pg === pgId) return;
        document.querySelectorAll(`#${pg === 'cover' ? 'ipage_cover' : pg === 'letter' ? 'ipage_letter' : 'ipage_id'} .receipt-field-input`)
          .forEach(otherInp => {
            if (otherInp !== inp &&
                otherInp.closest('.receipt-field-row')
                  ?.querySelector('.receipt-field-label')
                  ?.textContent === form) {
              otherInp.value = inp.value;
            }
          });
      });
    });

    row.appendChild(lbl);
    row.appendChild(inp);
    fieldsEl.appendChild(row);
  });
}

function _updateReceiptCount(pgId, series) {
  const forms    = series === 'n' ? N_FORMS : I_FORMS;
  const receipts = getters.receiptsFor(pgId);
  const count    = forms.filter(f => receipts[f] !== undefined).length;
  const countEl  = document.getElementById(`${series}count_${pgId}`);
  if (countEl) countEl.textContent = count === 0 ? '0 selected' : `${count} selected`;
}

// ───────────────────────────────────────────────────────────────
// AUTO ATTN & TITLE
// ───────────────────────────────────────────────────────────────

function _autoUpdateAttnAndTitle() {
  const selected = queries.selectedReceiptForms();
  if (!selected.length) return;

  const nSelected = selected.filter(f => N_FORMS.includes(f));
  const iSelected = selected.filter(f => I_FORMS.includes(f));
  const parts     = [...nSelected, ...iSelected];

  actions.autoSetAttnAndTitle(
    `${parts.join('/')} Interview`,
    `${parts.join(' and ').toUpperCase()} COMBO INTERVIEW DOCUMENTS`
  );
}

// ───────────────────────────────────────────────────────────────
// DOC LISTS
// ───────────────────────────────────────────────────────────────

function _buildDocList(pgId) {
  const container = document.getElementById(`doclist_${pgId}`);
  if (!container) return;

  const sections = DOC_SECTIONS[pgId] ?? [];
  const initial  = [];
  sections.forEach((sec, si) => {
    sec.items.forEach((item, ii) => {
      initial.push({ si, ii, checked: true, textVal: item.placeholder ?? '' });
    });
  });
  actions.setDocState(pgId, initial);
  container.innerHTML = '';

  sections.forEach((sec, si) => {
    const secDiv = el('div', { class: 'doc-section' });
    const secLbl = el('div', { class: 'doc-section-label' });
    const secInp = el('input');
    Object.assign(secInp.style, {
      background: 'transparent', border: 'none',
      borderBottom: '1px dashed var(--border2)',
      color: 'var(--text)', fontFamily: 'var(--font-sans)',
      fontSize: '.82rem', fontWeight: '600',
      padding: '1px 4px', flex: '1', minWidth: '0',
    });
    secInp.value = sec.label;
    secInp.addEventListener('focus', () => secInp.style.borderBottomColor = 'var(--accent)');
    secInp.addEventListener('blur',  () => secInp.style.borderBottomColor = 'var(--border2)');
    secInp.addEventListener('input', () => { sec.label = secInp.value; });
    secLbl.appendChild(secInp);
    secDiv.appendChild(secLbl);

    const list = el('div', { class: 'doc-list' });
    sec.items.forEach((item, ii) => list.appendChild(_buildDocItem(pgId, si, ii, item)));

    const addRow = el('div', { class: 'doc-add-row' });
    const addInp = el('input', { class: 'doc-add-input', placeholder: 'Add item…' });
    const addBtn = el('button', { class: 'doc-add-btn', type: 'button' }, '+ Add');
    const doAdd  = () => {
      const label = addInp.value.trim();
      if (!label) return;
      const ii = sec.items.length;
      sec.items.push({ label, type: 'item' });
      const ds = getters.docState(pgId);
      ds.push({ si, ii, checked: true, textVal: '' });
      actions.setDocState(pgId, ds);
      list.appendChild(_buildDocItem(pgId, si, ii, sec.items[ii]));
      addInp.value = '';
    };
    addInp.addEventListener('keydown', e => { if (e.key === 'Enter') doAdd(); });
    addBtn.addEventListener('click', doAdd);
    addRow.appendChild(addInp);
    addRow.appendChild(addBtn);

    secDiv.appendChild(list);
    secDiv.appendChild(addRow);
    container.appendChild(secDiv);
    if (si < sections.length - 1)
      container.appendChild(el('div', { class: 'receipt-divider' }));
  });
}

function _buildDocItem(pgId, si, ii, item) {
  const state = getters.docState(pgId).find(s => s.si === si && s.ii === ii);
  const row   = el('div', { class: `doc-item${state?.checked ? ' checked' : ''}` });

  const cb = el('input', { type: 'checkbox' });
  cb.checked = state?.checked !== false;

  const lbl     = el('span', { class: 'doc-item-label' });
  let textInp   = null;

  if (item.type === 'text') {
    lbl.textContent = item.label;
    textInp = el('input', { class: 'doc-item-text', placeholder: item.placeholder ?? '' });
    textInp.value    = state?.textVal ?? '';
    textInp.disabled = !cb.checked;
    textInp.style.opacity = cb.checked ? '1' : '0.4';
    textInp.addEventListener('input', () =>
      actions.updateDocItem(pgId, si, ii, { textVal: textInp.value })
    );
  } else {
    const labelInp = el('input');
    Object.assign(labelInp.style, {
      background: 'transparent', border: 'none',
      color: 'var(--text2)', fontFamily: 'var(--font-sans)',
      fontSize: '.84rem', flex: '1', minWidth: '0', padding: '0',
    });
    labelInp.value = item.label;
    labelInp.addEventListener('focus', () => labelInp.style.color = 'var(--text)');
    labelInp.addEventListener('blur',  () => labelInp.style.color = 'var(--text2)');
    labelInp.addEventListener('input', () => { item.label = labelInp.value; });
    lbl.style.flex = '1';
    lbl.appendChild(labelInp);
  }

  cb.addEventListener('change', () => {
    actions.updateDocItem(pgId, si, ii, { checked: cb.checked });
    row.classList.toggle('checked', cb.checked);
    if (textInp) {
      textInp.disabled      = !cb.checked;
      textInp.style.opacity = cb.checked ? '1' : '0.4';
    }
  });

  const remBtn = el('button', { class: 'doc-item-remove', type: 'button', title: 'Remove' }, '✕');
  remBtn.addEventListener('click', () => {
    row.remove();
    const ds = getters.docState(pgId).filter(s => !(s.si === si && s.ii === ii));
    ds.filter(s => s.si === si && s.ii > ii).forEach(s => s.ii--);
    actions.setDocState(pgId, ds);
    DOC_SECTIONS[pgId]?.[si]?.items.splice(ii, 1);
  });

  row.appendChild(cb);
  row.appendChild(lbl);
  if (textInp) row.appendChild(textInp);
  row.appendChild(remBtn);
  return row;
}

// ───────────────────────────────────────────────────────────────
// VALIDAR Y CONTINUAR
// ───────────────────────────────────────────────────────────────

function _proceedStep2() {
  if (!queries.introComplete()) {
    toast('Please fill in the required fields on Cover Page and Identification', 'error');
    ALL_PAGES.filter(pg => REQUIRED[pg]?.length).forEach(pg => {
      const data = getters.introPage(pg);
      REQUIRED[pg].forEach(field => {
        document.querySelectorAll(
          `#step2 [data-ip="${pg}"][data-if="${field}"]`
        ).forEach(inp => {
          if (!(data[field] ?? '').trim()) {
            inp.classList.add('err');
            inp.addEventListener('input', () => inp.classList.remove('err'), { once: true });
          }
        });
      });
    });
    return;
  }
  markDone(2);
  unlockStep(3);
  goTo(3);
}