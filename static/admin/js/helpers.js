// js/helpers.js
// ── Utilidades de formato y UI puras (sin efectos secundarios) ───────────────

/** Pill coloreada por estado de evento */
function pillState(s) {
  const m = { create:"blue", pending:"yellow", failed:"red", processing:"purple", finish:"green" };
  return `<span class="pill ${m[s] || "gray"}">${(s || "").toUpperCase()}</span>`;
}

/** Pill verde/rojo para booleanos (gate activo/cerrado) */
function pillBool(v) {
  return v
    ? `<span class="pill green"><span class="dot"></span>activo</span>`
    : `<span class="pill red"><span class="dot"></span>cerrado</span>`;
}

/** Pill de rol de usuario */
function rpill(r) {
  const m = { admin: "red", superadmin: "red", user: "gray" };
  return `<span class="pill ${m[r] || "gray"}">${r || "user"}</span>`;
}

/** Badge de módulo coloreado */
function modBadge(mod) {
  return `<span class="mod-badge ${mod || "unknown"}">${mod || "—"}</span>`;
}

/** Formatea duración en ms de forma legible */
function fmtDur(ms) {
  if (ms == null) return "—";
  if (ms < 1)     return "<1ms";
  if (ms >= 1000) return (ms / 1000).toFixed(2) + "s";
  return Math.round(ms) + "ms";
}

/** Extrae HH:MM:SS.mmm del event_id (raíz de 17 chars) */
function tsTime(eid) {
  const r = (eid || "").split("_")[0];
  if (r.length !== 17) return "—";
  return `${r.slice(8,10)}:${r.slice(10,12)}:${r.slice(12,14)}.${r.slice(14,17)}`;
}

/** Extrae timestamp completo del root_id de 17 chars */
function parseTs(root) {
  if (!root || root.length !== 17) return "—";
  return `${root.slice(6,8)}/${root.slice(4,6)}/${root.slice(0,4)} ` +
         `${root.slice(8,10)}:${root.slice(10,12)}:${root.slice(12,14)}.${root.slice(14,17)}`;
}

/** Formatea un event_id como árbol de segmentos coloreados */
function fmtEvId(rawId) {
  const parts = rawId.split("_");
  const root  = parts[0];
  const short = root.length === 17
    ? `${root.slice(8,10)}:${root.slice(10,12)}:${root.slice(12,14)}.${root.slice(14,17)}`
    : root;
  let html = `<span class="ev-root">${short}</span>`;
  for (const seg of parts.slice(1))
    html += `<span class="ev-sep"> → </span><span class="ev-seg ${seg}">${seg}</span>`;
  return `<div class="ev-path">${html}</div>`;
}

/** Formatea fecha ISO → DD/MM/YYYY */
function fdate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString("es", { day:"2-digit", month:"2-digit", year:"numeric" }); }
  catch { return iso; }
}

/** Formatea fecha ISO → DD/MM HH:MM:SS */
function ftime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("es", { day:"2-digit", month:"2-digit" }) + " " +
           d.toLocaleTimeString("es", { hour:"2-digit", minute:"2-digit", second:"2-digit" });
  } catch { return iso; }
}

/** Iniciales de un nombre (máximo 2 letras) */
function initials(name) {
  return (name || "?").split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
}