// js/components/drawer.js
// ── Drawer de detalle de evento ───────────────────────────────────────────────

function openDrawer(ev, scroll = true) {
  State.selectedEv = ev;

  const root    = ev.root_id || (ev.event_id || "").split("_")[0];
  const path    = ev.path    || (ev.event_id || "").split("_").slice(1);
  const op      = OPS[ev.op_id] || {};
  const opName  = op.name   || ev.op_id || "—";
  const opGates = op.gates  || [];
  const chain   = buildOpChain(ev.op_id);
  const mod     = op.module || "auth";

  // Eventos del mismo request (mismo root)
  const siblings = State.allEvents
    .filter(e => (e.root_id || (e.event_id || "").split("_")[0]) === root)
    .sort((a, b) => (a.event_id < b.event_id ? -1 : 1));

  document.getElementById("drawer-title").textContent = opName;
  document.getElementById("drawer-sub").textContent   = ev.event_id;

  // ── Camino de gates ──────────────────────────────────────────────────────
  const pathHtml = path.length === 0
    ? `<div style="font-size:12px;color:var(--muted)">Evento raíz — ningún gate intermediario</div>`
    : `<div class="ev-path" style="font-size:14px;gap:6px;margin-bottom:10px">
         <span class="ev-seg H" style="font-size:14px">H</span>
         ${path.map(seg =>
           `<span class="ev-sep" style="font-size:14px">→</span>` +
           `<span class="ev-seg ${seg}" style="font-size:14px">${seg}</span>`
         ).join("")}
       </div>
       <div style="display:flex;flex-wrap:wrap;gap:6px">
         ${["H", ...path].map(g => gateTag(g)).join("")}
       </div>`;

  // ── Árbol de operación ───────────────────────────────────────────────────
  const chainHtml = chain.map((item, i) => `
    <div class="op-node" style="padding-left:${i * 14}px">
      ${i > 0 ? `<span class="op-connector">└─</span>` : ""}
      <div class="op-info">
        <div class="op-id-badge">${item.id}</div>
        <div class="op-name ${item.id === ev.op_id ? "current" : "ancestor"}">${item.name}</div>
        <div class="op-gates-list">${item.gates.map(g => gateTag(g)).join("")}</div>
      </div>
    </div>`).join("");

  // ── Eventos hermanos ─────────────────────────────────────────────────────
  const sibHtml = siblings.length === 0
    ? `<div style="font-size:12px;color:var(--muted)">Sin eventos relacionados</div>`
    : siblings.map(sib => {
        const sibPath  = sib.path || (sib.event_id || "").split("_").slice(1);
        const isCur    = sib.event_id === ev.event_id;
        const depth    = sibPath.length;
        const depthStr = depth === 0 ? "●" : "  ".repeat(depth - 1) + "└─";
        const sibObj   = JSON.stringify(sib).replace(/'/g, "\\'");
        return `<div class="sib-row ${isCur ? "current" : ""}"
          onclick='${isCur ? "" : "openDrawer(" + sibObj + ")"}'>
          <div class="sib-depth">${depthStr}</div>
          <div>
            <div>${fmtEvId(sib.event_id)}</div>
            <div class="sib-op">${sib.op_id || "—"} · ${opLabel(sib.op_id)}</div>
          </div>
          <div style="font-size:11px;color:var(--muted)">${fmtDur(sib.duration_ms)}</div>
          <div>${pillState(sib.state)}</div>
        </div>`;
      }).join("");

  document.getElementById("drawer-body").innerHTML = `
    <div class="ds">
      <div class="ds-title">Identidad</div>
      <div class="dr"><span class="dk">Event ID</span><span class="dv">${ev.event_id}</span></div>
      <div class="dr"><span class="dk">Root ID</span><span class="dv">${root}</span></div>
      <div class="dr"><span class="dk">Timestamp</span><span class="dv">${parseTs(root)}</span></div>
      <div class="dr"><span class="dk">Módulo</span><span class="dv">${modBadge(mod)}</span></div>
      <div class="dr"><span class="dk">Gate origen</span><span class="dv">${ev.gate || "—"}</span></div>
      <div class="dr"><span class="dk">Estado</span><span class="dv">${pillState(ev.state)}</span></div>
      <div class="dr"><span class="dk">Duración</span><span class="dv">${fmtDur(ev.duration_ms)}</span></div>
      ${ev.error ? `<div class="dr"><span class="dk" style="color:var(--closed)">Error</span>
        <span class="dv" style="color:var(--closed)">${ev.error}</span></div>` : ""}
    </div>
    <div class="ds">
      <div class="ds-title">Camino de gates</div>
      ${pathHtml}
    </div>
    <div class="ds">
      <div class="ds-title">Patrón de operación</div>
      <div class="op-tree">${chainHtml}</div>
      <div style="margin-top:8px">
        <div class="dr"><span class="dk">Op ID</span><span class="dv">${ev.op_id || "—"}</span></div>
        <div class="dr"><span class="dk">Módulo</span><span class="dv">${mod}</span></div>
        <div class="dr"><span class="dk">Gates requeridos</span>
          <span class="dv" style="display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end">
            ${opGates.map(g => gateTag(g)).join("") || "—"}
          </span>
        </div>
      </div>
    </div>
    <div class="ds">
      <div class="ds-title">Eventos del request · root ${root.slice(-6)}</div>
      <div class="siblings-list">${sibHtml}</div>
    </div>`;

  document.getElementById("overlay").classList.add("open");
  document.getElementById("drawer").classList.add("open");
  if (scroll) document.getElementById("drawer").scrollTop = 0;
}

function closeDrawer() {
  State.selectedEv = null;
  document.getElementById("overlay").classList.remove("open");
  document.getElementById("drawer").classList.remove("open");
}