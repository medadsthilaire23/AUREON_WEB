// js/pages/users.js
// ── Página "Usuarios" ─────────────────────────────────────────────────────────

function filterUsers(q) {
  State.userSearch = q.toLowerCase();
  if (State.users) renderUsers(State.users.users || [], State.userSearch);
}

function renderUsers(users, q) {
  const f = q
    ? users.filter(u =>
        (u.name  || "").toLowerCase().includes(q) ||
        (u.email || "").toLowerCase().includes(q)
      )
    : users;

  document.getElementById("usrs").innerHTML = `
    <div class="stat-sub" style="margin-bottom:12px">
      ${f.length} usuario${f.length !== 1 ? "s" : ""}
    </div>
    <div class="tbl-wrap"><table>
      <thead><tr>
        <th>Usuario</th><th>Rol</th><th>Proveedores</th><th>Sesiones</th>
        <th>Dispositivos</th><th>Última conexión</th><th>IP</th><th>Registro</th>
      </tr></thead>
      <tbody>${f.length === 0
        ? `<tr><td colspan="8" class="empty">Sin usuarios</td></tr>`
        : f.map(u => `
            <tr class="row-click"
              onclick='showUser(${JSON.stringify(u).replace(/'/g, "&#39;")})'>
              <td><div class="uc">
                <div class="av">${u.avatar_url ? `<img src="${u.avatar_url}">` : initials(u.name)}</div>
                <div><div class="un">${u.name}</div><div class="ue">${u.email}</div></div>
              </div></td>
              <td>${rpill(u.role)}</td>
              <td>${(u.providers || []).map(p => `<span class="pill gray">${p}</span>`).join(" ") || "—"}</td>
              <td><span class="pill ${u.active_sessions > 0 ? "green" : "gray"}">
                ${u.active_sessions} activa${u.active_sessions !== 1 ? "s" : ""}
              </span></td>
              <td style="color:var(--muted)">${u.total_devices}</td>
              <td style="font-family:var(--mono);font-size:11px;color:var(--muted)">
                ${u.last_seen_at ? ftime(u.last_seen_at) : "—"}
              </td>
              <td style="font-family:var(--mono);font-size:11px;color:var(--muted)">${u.last_ip || "—"}</td>
              <td style="font-family:var(--mono);font-size:11px;color:var(--muted)">${fdate(u.created_at)}</td>
            </tr>`).join("")}
      </tbody>
    </table></div>`;
}