// js/pages/sessions.js
// ── Página "Sesiones Activas" ─────────────────────────────────────────────────

function filterSess(q) {
  State.sessSearch = q.toLowerCase();
  if (State.sessions) renderSess(State.sessions.sessions || [], State.sessSearch);
}

function renderSess(sessions, q) {
  const f = q
    ? sessions.filter(s =>
        (s.user?.name         || "").toLowerCase().includes(q) ||
        (s.user?.email        || "").toLowerCase().includes(q) ||
        (s.ip                 || "").includes(q) ||
        (s.device?.device_name|| "").toLowerCase().includes(q)
      )
    : sessions;

  document.getElementById("sess").innerHTML = `
    <div class="stat-sub" style="margin-bottom:12px">
      ${f.length} sesión${f.length !== 1 ? "es" : ""} activa${f.length !== 1 ? "s" : ""}
    </div>
    <div class="tbl-wrap"><table>
      <thead><tr>
        <th>Usuario</th><th>IP</th><th>Dispositivo</th>
        <th>Browser / OS</th><th>Ubicación</th><th>Última actividad</th><th>Creada</th>
      </tr></thead>
      <tbody>${f.length === 0
        ? `<tr><td colspan="7" class="empty">Sin sesiones activas</td></tr>`
        : f.map(s => {
            const u  = s.user   || {};
            const dv = s.device || {};
            return `<tr class="row-click"
              onclick='showSess(${JSON.stringify(s).replace(/'/g, "&#39;")})'>
              <td><div class="uc">
                <div class="av">${u.avatar_url ? `<img src="${u.avatar_url}">` : initials(u.name)}</div>
                <div><div class="un">${u.name || "—"}</div><div class="ue">${u.email || "—"}</div></div>
              </div></td>
              <td style="font-family:var(--mono);font-size:12px">${s.ip || "—"}</td>
              <td style="color:var(--muted)">${dv.device_name || "—"}</td>
              <td style="color:var(--muted)">${[dv.browser, dv.os].filter(Boolean).join(" / ") || "—"}</td>
              <td style="color:var(--muted)">${[dv.city, dv.country].filter(Boolean).join(", ") || "—"}</td>
              <td style="font-family:var(--mono);font-size:11px;color:var(--muted)">${ftime(s.last_active_at)}</td>
              <td style="font-family:var(--mono);font-size:11px;color:var(--muted)">${fdate(s.created_at)}</td>
            </tr>`;
          }).join("")}
      </tbody>
    </table></div>`;
}