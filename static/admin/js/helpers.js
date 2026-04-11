// shared/static/admin/js/helpers.js
// ══════════════════════════════════════════════════════════════════════════════
// Helpers de formato y render — AUREON v4.0
//
// Cambios v4.0:
//   pillState()  — nuevos estados VALIDATING, EXECUTING, ANOMALY
//   gateTag()    — nuevos aliases S, LG, AG, VG con colores propios
//   fmtEvId()    — soporta aliases de dos letras (LG, AG, VG, OG, OGH, PL)
//   modBadge()   — nuevos módulos: frontend, discovery
//   anomalyBadge() — nuevo: badge para prefijos de anomalía (XX, SA, GB…)
//
// Colores sincronizados con event_state.py STATE_COLORS:
//   create     → blue
//   validating → cyan     (nuevo v4.0)
//   executing  → purple   (nuevo v4.0)
//   pending    → yellow   (compat v3.x)
//   failed     → red
//   processing → orange   (nuevo v4.0 — era var(--warn) en v3)
//   anomaly    → red_critical → var(--closed) + borde rojo pulsante
//   finish     → green
// ══════════════════════════════════════════════════════════════════════════════

// ── Estado → pill ─────────────────────────────────────────────────────────────
// Sincronizado con event_state.py STATE_COLORS
const _STATE_CLASS = {
  create:     "blue",
  validating: "cyan",       // nuevo v4.0
  executing:  "purple",     // nuevo v4.0
  pending:    "yellow",     // compat v3.x
  failed:     "red",
  processing: "orange",     // nuevo v4.0
  anomaly:    "anomaly",    // nuevo v4.0 — clase especial
  finish:     "green",
};

// Etiquetas — sincronizadas con event_state.py STATE_LABELS
const _STATE_LABEL = {
  create:     "CREATE",
  validating: "VALIDATING",
  executing:  "EXECUTING",
  pending:    "PENDING",
  failed:     "FAILED",
  processing: "PROCESSING",
  anomaly:    "ANOMALY ⚠",
  finish:     "FINISH",
};

function pillState(s) {
  const key   = (s || "").toLowerCase();
  const cls   = _STATE_CLASS[key] || "gray";
  const label = _STATE_LABEL[key] || (s || "").toUpperCase();
  return `<span class="pill ${cls}">${label}</span>`;
}

// ── Gate tag ──────────────────────────────────────────────────────────────────
// Aliases v4.0: H D M B S LG AG VG OG OGH PL R
// CSS class por alias — definidos en dashboard.css
const _GATE_TAG_CLASS = {
  H:   "H",
  D:   "D",
  M:   "M",
  B:   "B",
  S:   "S",    // SecurityGate — nuevo v4.0
  LG:  "LG",  // LoginGate    — nuevo v4.0
  AG:  "AG",  // AccessGate   — nuevo v4.0
  VG:  "VG",  // VerificacionGate — nuevo v4.0
};

function gateTag(alias) {
  const cls  = _GATE_TAG_CLASS[alias] ? alias : "def";
  const name = GATE_FULL[alias] || alias;
  return `<span class="gate-tag ${cls}">${name}</span>`;
}

// ── Event path ────────────────────────────────────────────────────────────────
// Soporta aliases de una o dos letras: H, D, M, B, S, LG, AG, VG
function fmtEvId(rawId) {
  if (!rawId) return "—";
  const parts = rawId.split("_");
  const root  = parts[0];

  // Timestamp legible desde root (17 dígitos)
  const short = root.length === 17
    ? `${root.slice(8,10)}:${root.slice(10,12)}:${root.slice(12,14)}.${root.slice(14,17)}`
    : root;

  const path = parts.slice(1);
  let html = `<span class="ev-root">${short}</span>`;
  for (const seg of path) {
    const cls = _GATE_TAG_CLASS[seg] ? seg : "def";
    html += `<span class="ev-sep"> → </span><span class="ev-seg ${cls}">${seg}</span>`;
  }
  return `<div class="ev-path">${html}</div>`;
}

// ── Module badge ──────────────────────────────────────────────────────────────
// v4.0: añadidos frontend y discovery
function modBadge(mod) {
  return `<span class="mod-badge ${mod || 'unknown'}">${mod || '—'}</span>`;
}

// ── Anomaly badge — nuevo v4.0 ────────────────────────────────────────────────
// Muestra el prefijo de anomalía con su nivel de alerta
function anomalyBadge(opId) {
  const meta = getAnomalyMeta(opId);
  if (!meta) return "";
  const prefix = (opId || "").slice(0, 2).toUpperCase();
  return `<span class="pill anomaly" title="${meta.level}">${prefix} — ${meta.label}</span>`;
}

// ── Otros helpers de formato ──────────────────────────────────────────────────

function pillBool(v) {
  return v
    ? `<span class="pill green"><span class="dot"></span>activo</span>`
    : `<span class="pill red"><span class="dot"></span>cerrado</span>`;
}

function rpill(r) {
  const m = { admin:"red", superadmin:"red", user:"gray" };
  return `<span class="pill ${m[r] || 'gray'}">${r || "user"}</span>`;
}

function fmtDur(ms) {
  if (ms == null) return "—";
  if (ms < 1)     return "<1ms";
  if (ms >= 1000) return (ms / 1000).toFixed(2) + "s";
  return Math.round(ms) + "ms";
}

function initials(name) {
  return (name || "?").split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
}

function fdate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("es", {
      day:"2-digit", month:"2-digit", year:"numeric",
    });
  } catch { return iso; }
}

function ftime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("es", { day:"2-digit", month:"2-digit" }) + " " +
           d.toLocaleTimeString("es", { hour:"2-digit", minute:"2-digit", second:"2-digit" });
  } catch { return iso; }
}

function tsTime(eid) {
  const r = (eid || "").split("_")[0];
  if (r.length !== 17) return "—";
  return `${r.slice(8,10)}:${r.slice(10,12)}:${r.slice(12,14)}.${r.slice(14,17)}`;
}

function parseTs(root) {
  if (!root || root.length !== 17) return "—";
  return `${root.slice(6,8)}/${root.slice(4,6)}/${root.slice(0,4)} ` +
         `${root.slice(8,10)}:${root.slice(10,12)}:${root.slice(12,14)}.${root.slice(14,17)}`;
}