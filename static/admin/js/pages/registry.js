// js/pages/registry.js
// ── Página "Registry — Sistema" ───────────────────────────────────────────────

/** Devuelve los eventos filtrados según el estado de State */
function _getRegEvents() {
  let all = State.allEvents.slice().sort((a, b) => b.event_id.localeCompare(a.event_id));
  if (State.regSearch)   all = all.filter(e =>
    (e.event_id || "").includes(State.regSearch) ||
    (e.op_id    || "").toLowerCase().includes(State.regSearch) ||
    (e.gate     || "").toLowerCase().includes(State.regSearch) ||
    (e.state    || "").toLowerCase().includes(State.regSearch)
  );
  if (State.stateFilter) all = all.filter(e => e.state === State.stateFilter);
  if (State.modFilter)   all = all.filter(e => opModule(e.op_id) === State.modFilter);
  return all;
}

// ── Handlers de filtros ───────────────────────────────────────────────────────
function filterReg(q) { State.regSearch = q.toLowerCase(); renderRegistryTab(); }

function setModFilter(m) {
  State.modFilter = State.modFilter === m ? null : m;
  ["f-all","f-auth","f-lb","f-sys"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.remove("on");
  });
  const map  = { null:"f-all", auth:"f-auth", lifebound:"f-lb", system:"f-sys" };
  const btnEl = document.getElementById(map[String(m)] || "f-all");
  if (btnEl) btnEl.classList.add("on");
  renderRegistryTab();
}

function setStateFilter(s) {
  State.stateFilter = State.stateFilter === s ? null : s;
  const el = document.getElementById("f-failed");
  if (el) el.classList.toggle("on", State.stateFilter === "failed");
  renderRegistryTab();
}

function setRegTab(tab, el) {
  State.regTab = tab;
  document.querySelectorAll("#registry-tabs .mod-tab").forEach(t => t.classList.remove("active"));
  el.classList.add("active");
  renderRegistryTab();
}

// ── Render ────────────────────────────────────────────────────────────────────
function renderRegistryTab() {
  const events = _getRegEvents().filter(ev => {
    const mod = opModule(ev.op_id);
    if (mod === "dashboard") return false;      // Dashboard tiene su propia página
    if (State.regTab === "all") return true;
    return mod === State.regTab;
  });

  const total = events.length;
  document.getElementById("registry-root").innerHTML = `
    <div class="stat-sub" style="margin-bottom:12px">${total} evento${total !== 1 ? "s" : ""}</div>
    <div class="tbl-wrap"><table>
      <thead><tr>
        <th>Hora</th><th>Event ID</th><th>Op ID</th><th>Operación</th>
        <th>Módulo</th><th>Estado</th><th>Gate</th><th>Duración</th><th>Error</th>
      </tr></thead>
      <tbody>${events.length === 0
        ? `<tr><td colspan="9" class="empty">Sin eventos</td></tr>`
        : events.slice(0, 200).map(ev => {
            const mod   = opModule(ev.op_id);
            const isSel = State.selectedEv && State.selectedEv.event_id === ev.event_id;
            return `<tr class="row-click ${isSel ? "row-selected" : ""}"
              onclick='openDrawer(${JSON.stringify(ev).replace(/'/g, "\\'")})'>
              <td style="font-family:var(--mono);font-size:11px;color:var(--muted)">${tsTime(ev.event_id)}</td>
              <td>${fmtEvId(ev.event_id)}</td>
              <td style="font-family:var(--mono);font-size:10px;color:var(--muted)">${ev.op_id || "—"}</td>
              <td style="font-size:12px;color:var(--dim)">${opLabel(ev.op_id)}</td>
              <td>${modBadge(mod)}</td>
              <td>${pillState(ev.state)}</td>
              <td style="color:var(--muted)">${ev.gate || "—"}</td>
              <td style="color:var(--muted)">${fmtDur(ev.duration_ms)}</td>
              <td style="color:var(--closed);font-size:11px;font-family:var(--mono)">${ev.error || ""}</td>
            </tr>`;
          }).join("")}
      </tbody>
    </table></div>`;
}

// ── Export inline (descarga en navegador, sin backend) ────────────────────────
function exportInline(fmt) {
  const events = _getRegEvents();
  let content = "", mime = "text/plain", ext = fmt;

  if (fmt === "json") {
    content = JSON.stringify({ exported_at: new Date().toISOString(), total: events.length, events }, null, 2);
    mime = "application/json";
  } else if (fmt === "csv") {
    const hdr  = "event_id,op_id,gate,state,duration_ms,error,module\n";
    const rows = events.map(e => [
      e.event_id, e.op_id || "", e.gate || "", e.state || "",
      e.duration_ms != null ? e.duration_ms.toFixed(2) : "",
      `"${(e.error || "").replace(/"/g, '""')}"`,
      opModule(e.op_id),
    ].join(","));
    content = hdr + rows.join("\n");
    mime = "text/csv";
  } else {
    content  = `AUREON Event Registry Export\n${new Date().toISOString()}\nTotal: ${events.length}\n\n`;
    content += events.map(e =>
      `[${tsTime(e.event_id)}] ${e.op_id || "?"} | ${e.gate || "?"} | ${e.state || "?"} | ${fmtDur(e.duration_ms)} ${e.error ? "| ERROR: " + e.error : ""}`
    ).join("\n");
  }

  const blob = new Blob([content], { type: mime });
  const a    = document.createElement("a");
  a.href     = URL.createObjectURL(blob);
  a.download = `aureon_registry_${new Date().toISOString().slice(0,19).replace(/:/g,"-")}.${ext}`;
  a.click();
}