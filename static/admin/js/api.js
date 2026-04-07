// js/api.js
// ── Capa de datos: fetch al backend + estado global ───────────────────────────
// Todas las funciones que hacen fetch viven aquí.
// El estado global también se centraliza aquí para que todos los módulos
// lo lean/escriban desde el mismo objeto.

const TOKEN = new URLSearchParams(location.search).get("token") || "";
const H     = { "X-Admin-Token": TOKEN };

// ── Estado global ─────────────────────────────────────────────────────────────
const State = {
  data:         null,   // último payload de /status
  sessions:     null,   // último payload de /sessions
  users:        null,   // último payload de /users
  activity:     null,   // último payload de /activity

  allEvents:    [],     // todos los eventos aplanados (con .gate)

  expandedGate: null,   // nombre del gate con panel desplegado
  selectedEv:   null,   // evento actualmente en el drawer

  regTab:       "all",  // tab activa en Registry
  regSearch:    "",     // texto del buscador
  modFilter:    null,   // filtro de módulo
  stateFilter:  null,   // filtro de estado ("failed" | null)
  sessSearch:   "",     // buscador de sesiones
  userSearch:   "",     // buscador de usuarios
};

// ── Helpers de fetch ──────────────────────────────────────────────────────────
async function jfetch(url) {
  const r = await fetch(url, { headers: H });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}

// ── loadAll ───────────────────────────────────────────────────────────────────
async function loadAll() {
  const si = document.getElementById("spin-icon");
  si.innerHTML = '<div class="spinner"></div>';
  await Promise.all([loadStatus(), loadSessions(), loadUsers(), loadActivity()]);
  si.textContent = "↻";
  document.getElementById("last-upd").textContent = new Date().toLocaleTimeString("es");
}

// ── loadStatus ────────────────────────────────────────────────────────────────
async function loadStatus() {
  try {
    const res  = await fetch(`/auth/control/status?token=${TOKEN}`, { headers: H });
    const data = await res.json();
    if (!res.ok) { showApiErr(data.error || `HTTP ${res.status}`); return; }

    State.data = data;
    State.allEvents = [];
    for (const [gate, evs] of Object.entries(data.events_by_gate || {}))
      for (const ev of evs) State.allEvents.push({ ...ev, gate });

    // Renderizar páginas que dependen de /status
    renderControl(data);
    renderRegistryTab();
    renderLifebound();
    renderDashboard();

    // Mantener drawer fresco si estaba abierto
    if (State.selectedEv) {
      const fresh = State.allEvents.find(e => e.event_id === State.selectedEv.event_id);
      if (fresh) openDrawer(fresh, false);
    }
    if (State.expandedGate) restoreGatePanel();

  } catch(e) { showApiErr(e.message); }
}

async function loadSessions() {
  try {
    State.sessions = await jfetch(`/auth/control/sessions?token=${TOKEN}`);
    renderSess(State.sessions.sessions || [], State.sessSearch);
  } catch(e) {
    document.getElementById("sess").innerHTML =
      `<div class="empty" style="color:var(--closed)">Error: ${e.message}</div>`;
  }
}

async function loadUsers() {
  try {
    State.users = await jfetch(`/auth/control/users?token=${TOKEN}`);
    renderUsers(State.users.users || [], State.userSearch);
  } catch(e) {
    document.getElementById("usrs").innerHTML =
      `<div class="empty" style="color:var(--closed)">Error: ${e.message}</div>`;
  }
}

async function loadActivity() {
  try {
    State.activity = await jfetch(`/auth/control/activity?token=${TOKEN}&limit=150`);
    renderAct(State.activity.activity || []);
  } catch(e) {
    document.getElementById("act").innerHTML =
      `<div class="empty" style="color:var(--closed)">Error: ${e.message}</div>`;
  }
}

/** Exportar registry vía backend (PDF/JSON/CSV/TXT por módulo) */
function exportRegistry() {
  const fmt = document.getElementById("export-fmt").value;
  const mod = document.getElementById("export-mod").value;
  window.location.href = `/auth/control/export?token=${TOKEN}&format=${fmt}&module=${mod}&limit=2000`;
}

function showApiErr(msg) {
  document.getElementById("control-root").innerHTML =
    `<div style="color:var(--closed);padding:20px">Error: ${msg}</div>`;
}