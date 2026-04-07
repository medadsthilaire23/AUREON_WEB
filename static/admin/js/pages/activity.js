// js/pages/activity.js
// ── Página "Actividad Global" ─────────────────────────────────────────────────

const ACT_COLORS = {
  login_success:  "green",
  login_failed:   "red",
  logout:         "gray",
  register:       "blue",
  password_change:"yellow",
  profile_update: "blue",
  session_revoked:"yellow",
  product_access: "purple",
  oauth_linked:   "green",
  oauth_unlinked: "yellow",
};

function renderAct(items) {
  document.getElementById("act").innerHTML = `
    <div class="tbl-wrap"><table>
      <thead><tr>
        <th>Evento</th><th>Usuario</th><th>IP</th><th>Dispositivo</th><th>Hora</th>
      </tr></thead>
      <tbody>${items.length === 0
        ? `<tr><td colspan="5" class="empty">Sin actividad registrada</td></tr>`
        : items.map(a => {
            const u   = a.user || {};
            const cls = ACT_COLORS[a.event_type] || "gray";
            return `<tr>
              <td><span class="pill ${cls}">${a.label || a.event_type}</span></td>
              <td>
                <div style="font-size:13px">${u.name || "—"}</div>
                <div style="font-size:11px;color:var(--muted)">${u.email || ""}</div>
              </td>
              <td style="font-family:var(--mono);font-size:11px;color:var(--muted)">${a.ip || "—"}</td>
              <td style="color:var(--muted)">${a.device_name || "—"}</td>
              <td style="font-family:var(--mono);font-size:11px;color:var(--muted)">${ftime(a.created_at)}</td>
            </tr>`;
          }).join("")}
      </tbody>
    </table></div>`;
}