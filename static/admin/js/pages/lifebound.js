// js/pages/lifebound.js
// ── Página "Registry — Lifebound" ────────────────────────────────────────────

function renderLifebound() {
  const evs = State.allEvents
    .filter(ev => opModule(ev.op_id) === "lifebound")
    .slice()
    .reverse();

  if (!evs.length) {
    document.getElementById("lifebound-root").innerHTML =
      `<div class="empty">Sin eventos de Lifebound aún. Los eventos aparecerán aquí cuando los usuarios generen álbumes.</div>`;
    return;
  }

  document.getElementById("lifebound-root").innerHTML = `
    <div class="tbl-wrap"><table>
      <thead><tr>
        <th>Event ID</th><th>Op ID</th><th>Operación</th>
        <th>Estado</th><th>Gate</th><th>Duración</th><th>Error</th>
      </tr></thead>
      <tbody>${evs.map(ev => {
        const isSel = State.selectedEv && State.selectedEv.event_id === ev.event_id;
        return `<tr class="row-click ${isSel ? "row-selected" : ""}"
          onclick='openDrawer(${JSON.stringify(ev).replace(/'/g, "\\'")})'>
          <td>${fmtEvId(ev.event_id)}</td>
          <td style="font-family:var(--mono);font-size:10px;color:var(--muted)">${ev.op_id || "—"}</td>
          <td style="font-size:12px;color:var(--dim)">${opLabel(ev.op_id)}</td>
          <td>${pillState(ev.state)}</td>
          <td style="color:var(--muted)">${ev.gate || "—"}</td>
          <td style="color:var(--muted)">${fmtDur(ev.duration_ms)}</td>
          <td style="color:var(--closed);font-size:11px;font-family:var(--mono)">${ev.error || ""}</td>
        </tr>`;
      }).join("")}</tbody>
    </table></div>`;
}