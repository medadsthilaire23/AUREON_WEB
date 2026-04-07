// js/pages/control.js
// ── Página "Control del Sistema" ──────────────────────────────────────────────

function renderControl(d) {
  const c   = d.conductor || {};
  const reg = c.registry  || {};
  const bs  = reg.by_state  || {};
  const bg  = reg.by_gate   || {};
  const bm  = reg.by_module || {};
  const gates    = d.gates    || [];
  const breakers = d.breakers || [];

  // Los eventos del dashboard no se suman al conteo del sistema
  const dashCount = bm["dashboard"] || 0;
  const sysTotal  = (reg.total || 0) - dashCount;
  const cap       = reg.capacity || 5000;
  const capPct    = Math.round(sysTotal / cap * 100);
  const capCls    = capPct > 80 ? "red" : capPct > 50 ? "yellow" : "";

  const gatesRows = gates.map(gt => {
    const ev  = bg[gt.name] || 0;
    const tot = (gt.pass_count || 0) + (gt.fail_count || 0);
    const fp  = tot > 0 ? Math.round((gt.fail_count || 0) / tot * 100) : 0;
    const isSel = State.expandedGate === gt.name;
    return `<tr class="row-click ${isSel ? "row-selected" : ""}"
      id="gate-row-${gt.name}" onclick="toggleGatePanel('${gt.name}')">
      <td><strong>${gt.name}</strong>${ev > 0 ? `<span style="font-size:10px;color:var(--blue);margin-left:4px">▾</span>` : ""}</td>
      <td>${pillBool(gt.enabled !== false)}</td>
      <td><span style="color:${ev > 0 ? "var(--blue)" : "inherit"};font-weight:${ev > 0 ? 600 : 400}">${ev}</span></td>
      <td style="color:var(--open)">${(gt.pass_count || 0).toLocaleString()}</td>
      <td style="color:${fp > 0 ? "var(--closed)" : "var(--muted)"}">${(gt.fail_count || 0).toLocaleString()}</td>
      <td style="color:var(--muted)">${gt.avg_latency_ms != null ? gt.avg_latency_ms + "ms" : "—"}</td>
      <td style="color:var(--muted)">${gt.active_ops != null ? gt.active_ops : "—"}</td>
    </tr>`;
  }).join("");

  const modSummary = Object.entries(bm)
    .filter(([m]) => m !== "dashboard")
    .sort((a, b) => b[1] - a[1])
    .map(([m, n]) => `<span class="mod-badge ${m}" style="margin-right:6px">${m}: ${n}</span>`)
    .join("");

  document.getElementById("control-root").innerHTML = `
    <div class="grid">
      <div class="card">
        <div class="card-title">Sesiones activas</div>
        <div class="stat">${d.active_sessions ?? "—"}</div>
        <div class="stat-sub">${d.active_users ?? "—"} usuarios distintos</div>
      </div>
      <div class="card">
        <div class="card-title">Eventos del sistema</div>
        <div class="stat">${sysTotal.toLocaleString()}</div>
        <div style="margin-top:7px">
          <div class="bw"><div class="b ${capCls}" style="width:${capPct}%"></div></div>
          <div class="stat-sub">${capPct}% de ${cap.toLocaleString()} · excl. dashboard (${dashCount})</div>
        </div>
      </div>
      <div class="card">
        <div class="card-title">Eventos activos</div>
        <div class="stat">${reg.active || 0}</div>
        <div class="stat-sub">${(c.timer_watching || []).length > 0 ? "Timer observando" : "Sin colas activas"}</div>
      </div>
      <div class="card">
        <div class="card-title">Decisiones</div>
        <div class="stat">${c.decisions ?? 0}</div>
        <div class="stat-sub">${c.last_decision ? `Última: ${c.last_decision.action}` : "Sin decisiones"}</div>
      </div>
    </div>

    ${modSummary ? `<div style="margin-bottom:12px">${modSummary}</div>` : ""}

    <div class="state-grid">
      ${["create","pending","failed","processing","finish"].map(s =>
        `<div class="sc ${s}"><div class="v">${(bs[s] || 0).toLocaleString()}</div><div class="l">${s}</div></div>`
      ).join("")}
    </div>

    <div class="sec-title">Gates <span class="sec-hint">↓ click en una fila para ver sus eventos</span></div>
    <div class="tbl-wrap"><table>
      <thead><tr>
        <th>Gate</th><th>Estado</th><th>Eventos</th><th>Pass</th><th>Fail</th><th>Latencia avg</th><th>Activos</th>
      </tr></thead>
      <tbody id="gates-tbody">${gatesRows}</tbody>
    </table></div>

    ${breakers.length > 0 ? `
    <div class="sec-title">Breakers</div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Breaker</th><th>Estado</th><th>Gate</th><th>Trigger op</th><th>Forzado</th></tr></thead>
      <tbody>${breakers.map(b => `<tr>
        <td><strong>${b.name}</strong></td>
        <td>${pillBool(b.state !== "open")}</td>
        <td style="color:var(--muted)">${b.gate_name || "—"}</td>
        <td style="font-family:var(--mono);font-size:11px;color:var(--muted)">${b.trigger_op || "—"}</td>
        <td>${b.forced ? `<span class="pill red">sí</span>` : `<span class="pill gray">no</span>`}</td>
      </tr>`).join("")}</tbody>
    </table></div>` : ""}

    ${Object.keys(bg).length > 0 ? `
    <div class="sec-title">Distribución por gate</div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Gate</th><th>Eventos</th><th>Distribución</th></tr></thead>
      <tbody>${Object.entries(bg).sort((a, b) => b[1] - a[1]).map(([name, count]) => {
        const pct = Math.round(count / (reg.total || 1) * 100);
        return `<tr><td>${name}</td><td>${count}</td>
          <td style="width:150px"><div style="display:flex;align-items:center;gap:8px">
            <div class="bw" style="flex:1"><div class="b" style="width:${pct}%"></div></div>
            <span style="font-size:11px;color:var(--muted)">${pct}%</span>
          </div></td></tr>`;
      }).join("")}</tbody>
    </table></div>` : ""}
  `;
}

// ── Gate panel inline ─────────────────────────────────────────────────────────

function toggleGatePanel(gateName) {
  if (State.expandedGate === gateName) { collapseGatePanel(); return; }
  State.expandedGate = gateName;
  document.querySelectorAll("#gates-tbody .row-click").forEach(r => r.classList.remove("row-selected"));
  const row = document.getElementById("gate-row-" + gateName);
  if (row) row.classList.add("row-selected");
  removeGatePanel();
  if (row && State.data) {
    const pr = document.createElement("tr");
    pr.id = "gate-panel-row"; pr.className = "gate-events-row";
    pr.innerHTML = `<td colspan="7">${buildGatePanel(gateName)}</td>`;
    row.insertAdjacentElement("afterend", pr);
    pr.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

function collapseGatePanel() {
  State.expandedGate = null;
  document.querySelectorAll("#gates-tbody .row-click").forEach(r => r.classList.remove("row-selected"));
  removeGatePanel();
}

function removeGatePanel() {
  const o = document.getElementById("gate-panel-row");
  if (o) o.remove();
}

function restoreGatePanel() {
  if (!State.expandedGate || !State.data) return;
  removeGatePanel();
  const row = document.getElementById("gate-row-" + State.expandedGate);
  if (!row) return;
  row.classList.add("row-selected");
  const pr = document.createElement("tr");
  pr.id = "gate-panel-row"; pr.className = "gate-events-row";
  pr.innerHTML = `<td colspan="7">${buildGatePanel(State.expandedGate)}</td>`;
  row.insertAdjacentElement("afterend", pr);
}

function buildGatePanel(gateName) {
  const events = (State.data.events_by_gate || {})[gateName] || [];
  const rows = events.length === 0
    ? `<div class="empty">Sin eventos recientes para ${gateName}</div>`
    : events.map(ev => {
        const isSel = State.selectedEv && State.selectedEv.event_id === ev.event_id;
        const evObj = { ...ev, gate: gateName };
        const mod   = opModule(ev.op_id);
        return `<div class="ev-row ${isSel ? "ev-selected" : ""}"
          onclick='openDrawer(${JSON.stringify(evObj).replace(/'/g, "\\'")})'>
          <div style="display:flex;align-items:center;gap:8px">${fmtEvId(ev.event_id)}${modBadge(mod)}</div>
          <div class="ev-op">${ev.op_id || "—"} · ${opLabel(ev.op_id)}</div>
          <div class="ev-dur">${fmtDur(ev.duration_ms)}</div>
          <div>${pillState(ev.state)}</div>
        </div>`;
      }).join("");

  return `<div class="gate-panel">
    <div class="gate-panel-header">
      <span>Eventos — <strong>${gateName}</strong>
        <span style="font-weight:400;margin-left:6px">${events.length} registros</span>
      </span>
      <button class="panel-close-btn" onclick="collapseGatePanel()">✕</button>
    </div>
    <div class="events-scroll">${rows}</div>
  </div>`;
}