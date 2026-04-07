// js/pages/dashboard_reg.js
// ── Página "Dashboard Registry" ───────────────────────────────────────────────
// Muestra los eventos internos del panel de control (OP099*).
// Estos eventos NO se suman al conteo del sistema (ver renderControl).

function renderDashboard() {
  const evs = State.allEvents
    .filter(ev => opModule(ev.op_id) === "dashboard")
    .slice()
    .reverse();

  if (!evs.length) {
    document.getElementById("dashboard-root").innerHTML =
      `<div class="empty">Sin eventos del dashboard aún</div>`;
    return;
  }

  document.getElementById("dashboard-root").innerHTML = `
    <div style="margin-bottom:10px;font-size:12px;color:var(--muted)">
      ${evs.length} eventos — NO se suman al registry del sistema
    </div>
    <div class="tbl-wrap"><table>
      <thead><tr>
        <th>Event ID</th><th>Op ID</th><th>Endpoint</th><th>Estado</th><th>Duración</th>
      </tr></thead>
      <tbody>${evs.map(ev => {
        const isSel = State.selectedEv && State.selectedEv.event_id === ev.event_id;
        return `<tr class="row-click ${isSel ? "row-selected" : ""}"
          onclick='openDrawer(${JSON.stringify(ev).replace(/'/g, "\\'")})'>
          <td>${fmtEvId(ev.event_id)}</td>
          <td style="font-family:var(--mono);font-size:10px;color:var(--purple)">${ev.op_id || "—"}</td>
          <td style="font-size:12px;color:var(--dim)">${opLabel(ev.op_id)}</td>
          <td>${pillState(ev.state)}</td>
          <td style="color:var(--muted)">${fmtDur(ev.duration_ms)}</td>
        </tr>`;
      }).join("")}</tbody>
    </table></div>`;
}