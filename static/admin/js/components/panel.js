// js/components/panel.js
// ── Panel lateral para sesiones y usuarios ────────────────────────────────────

function openPanel() {
  document.getElementById("pov").classList.add("open");
  document.getElementById("side-panel").classList.add("open");
}

function closePanel() {
  document.getElementById("pov").classList.remove("open");
  document.getElementById("side-panel").classList.remove("open");
}

// ── Detalle de sesión ─────────────────────────────────────────────────────────
function showSess(s) {
  const u  = s.user   || {};
  const dv = s.device || {};
  document.getElementById("p-title").textContent = u.name  || "Sesión";
  document.getElementById("p-sub").textContent   = u.email || "";
  document.getElementById("p-body").innerHTML = `
    <div class="psec"><div class="pst">Usuario</div>
      <div class="ir"><span class="ik">ID</span><span class="iv">${u.id || "—"}</span></div>
      <div class="ir"><span class="ik">Rol</span><span class="iv">${rpill(u.role)}</span></div>
      <div class="ir"><span class="ik">Verificado</span>
        <span class="iv">${u.is_verified
          ? '<span class="pill green">sí</span>'
          : '<span class="pill red">no</span>'}</span></div>
    </div>
    <div class="psec"><div class="pst">Sesión</div>
      <div class="ir"><span class="ik">Session ID</span><span class="iv">${s.session_id || "—"}</span></div>
      <div class="ir"><span class="ik">IP</span><span class="iv">${s.ip || "—"}</span></div>
      <div class="ir"><span class="ik">Creada</span><span class="iv">${fdate(s.created_at)}</span></div>
      <div class="ir"><span class="ik">Última actividad</span><span class="iv">${ftime(s.last_active_at)}</span></div>
    </div>
    <div class="psec"><div class="pst">Dispositivo</div>
      <div class="ir"><span class="ik">Nombre</span>
        <span class="iv" style="font-family:var(--font)">${dv.device_name || "—"}</span></div>
      <div class="ir"><span class="ik">Navegador</span>
        <span class="iv" style="font-family:var(--font)">${dv.browser || "—"}</span></div>
      <div class="ir"><span class="ik">OS</span>
        <span class="iv" style="font-family:var(--font)">${dv.os || "—"}</span></div>
      <div class="ir"><span class="ik">IP</span><span class="iv">${dv.ip || s.ip || "—"}</span></div>
      <div class="ir"><span class="ik">Ubicación</span>
        <span class="iv" style="font-family:var(--font)">
          ${[dv.city, dv.country].filter(Boolean).join(", ") || "—"}
        </span></div>
      <div class="ir"><span class="ik">Confiable</span>
        <span class="iv">${dv.is_trusted
          ? '<span class="pill green">sí</span>'
          : '<span class="pill gray">no</span>'}</span></div>
      <div class="ir"><span class="ik">Visto</span>
        <span class="iv">${dv.last_seen_at ? ftime(dv.last_seen_at) : "—"}</span></div>
    </div>`;
  openPanel();
}

// ── Detalle de usuario ────────────────────────────────────────────────────────
function showUser(u) {
  document.getElementById("p-title").textContent = u.name  || "Usuario";
  document.getElementById("p-sub").textContent   = u.email || "";

  const sessHtml = (u.sessions || []).map(s => `
    <div class="sitem">
      <div style="display:flex;justify-content:space-between;margin-bottom:6px">
        <span style="font-size:12px;font-weight:500">${s.device_name || "Dispositivo desconocido"}</span>
        <span class="pill green" style="font-size:10px">activa</span>
      </div>
      <div style="font-size:11px;color:var(--muted)">IP: <span style="font-family:var(--mono)">${s.ip}</span></div>
      <div style="font-size:11px;color:var(--muted)">${s.browser || ""} ${s.os ? "/" + s.os : ""}</div>
      ${s.city || s.country
        ? `<div style="font-size:11px;color:var(--muted)">${[s.city, s.country].filter(Boolean).join(", ")}</div>`
        : ""}
      <div style="font-size:11px;color:var(--muted);margin-top:4px">Última actividad: ${ftime(s.last_active_at)}</div>
    </div>`).join("") || '<div style="color:var(--muted);font-size:12px">Sin sesiones activas</div>';

  const actHtml = (u.activity || []).map(a => `
    <div class="aitem">
      <div class="adot" style="background:${
        a.event_type.includes("fail")  ? "var(--closed)" :
        a.event_type.includes("login") ? "var(--open)"   : "var(--blue)"}"></div>
      <div>
        <div class="al">${a.label || a.event_type}</div>
        <div class="am">${[ftime(a.created_at), a.ip, a.device_name].filter(Boolean).join(" · ")}</div>
      </div>
    </div>`).join("") || '<div style="color:var(--muted);font-size:12px">Sin actividad</div>';

  document.getElementById("p-body").innerHTML = `
    <div class="psec"><div class="pst">Información</div>
      <div class="ir"><span class="ik">ID</span><span class="iv">${u.id}</span></div>
      <div class="ir"><span class="ik">Rol</span><span class="iv">${rpill(u.role)}</span></div>
      <div class="ir"><span class="ik">Verificado</span>
        <span class="iv">${u.is_verified
          ? '<span class="pill green">sí</span>'
          : '<span class="pill red">no</span>'}</span></div>
      <div class="ir"><span class="ik">Proveedores</span>
        <span class="iv" style="font-family:var(--font)">${(u.providers || []).join(", ") || "—"}</span></div>
      <div class="ir"><span class="ik">Productos</span>
        <span class="iv" style="font-family:var(--font)">${(u.products || []).join(", ") || "—"}</span></div>
      <div class="ir"><span class="ik">Registro</span><span class="iv">${fdate(u.created_at)}</span></div>
      <div class="ir"><span class="ik">Última conexión</span>
        <span class="iv">${u.last_seen_at ? ftime(u.last_seen_at) : "—"}</span></div>
      <div class="ir"><span class="ik">Última IP</span><span class="iv">${u.last_ip || "—"}</span></div>
      <div class="ir"><span class="ik">Último dispositivo</span>
        <span class="iv" style="font-family:var(--font)">${u.last_device || "—"}</span></div>
    </div>
    <div class="psec"><div class="pst">Sesiones activas (${(u.sessions || []).length})</div>${sessHtml}</div>
    <div class="psec"><div class="pst">Actividad reciente</div>${actHtml}</div>`;
  openPanel();
}