/**
 * account.js
 * ==========
 * Lógica base del panel de cuenta Aureon.
 * No depende de ningún tema — funciona con cualquier theme.css.
 */

const TOKEN_KEY = "aureon_access_token";

// ── Utilidades ────────────────────────────────────────────

function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function timeAgo(isoString) {
  const diff = Date.now() - new Date(isoString).getTime();
  const mins  = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days  = Math.floor(diff / 86400000);
  if (mins < 1)   return "Ahora mismo";
  if (mins < 60)  return `Hace ${mins} min`;
  if (hours < 24) return `Hace ${hours}h`;
  if (days < 7)   return `Hace ${days} días`;
  return new Date(isoString).toLocaleDateString("es-MX", { day: "numeric", month: "short" });
}

function dotClass(eventType) {
  const success = ["login_success", "register", "oauth_linked"];
  const warning = ["login_failed"];
  const danger  = ["session_revoked", "oauth_unlinked"];
  if (success.includes(eventType)) return "success";
  if (warning.includes(eventType)) return "warning";
  if (danger.includes(eventType))  return "danger";
  return "";
}

function initials(name) {
  return (name || "?")
    .split(" ")
    .map(w => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function formatDate(isoString) {
  return new Date(isoString).toLocaleDateString("es-MX", {
    year: "numeric", month: "long", day: "numeric"
  });
}

// ── Fetch autenticado ─────────────────────────────────────

async function authFetch(url, options = {}) {
  const token = getToken();
  if (!token) {
    window.location.href = "/auth/login?redirect=/auth/account";
    return null;
  }
  const res = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`,
      ...(options.headers || {}),
    },
  });
  if (res.status === 401) {
    window.location.href = "/auth/login?redirect=/auth/account";
    return null;
  }
  return res;
}

// ── Renderizado ───────────────────────────────────────────

function renderActivity(items, listEl) {
  if (!items.length) {
    listEl.innerHTML = '<li style="color:var(--theme-muted);font-size:13px;padding:12px 0">Sin actividad registrada.</li>';
    return;
  }
  listEl.innerHTML = items.map(a => `
    <li class="activity-item">
      <div class="activity-dot ${dotClass(a.event_type)}"></div>
      <div class="activity-body">
        <div class="activity-label">${a.label}</div>
        <div class="activity-sub">${[a.device_name, a.ip].filter(Boolean).join(" · ")}</div>
      </div>
      <div class="activity-time">${timeAgo(a.created_at)}</div>
    </li>
  `).join("");
}

function renderSessions(sessions) {
  const list = document.getElementById("session-list");
  if (!sessions.length) {
    list.innerHTML = '<li style="color:var(--theme-muted);font-size:13px;padding:12px 0">No hay sesiones.</li>';
    return;
  }
  list.innerHTML = sessions.map(s => `
    <li class="session-item">
      <div class="session-icon">💻</div>
      <div class="session-body">
        <div class="session-name">
          ${s.device?.device_name || "Dispositivo desconocido"}
          <span class="pill ${s.is_active ? "" : "inactive"}">${s.is_active ? "Activa" : "Inactiva"}</span>
        </div>
        <div class="session-sub">${s.ip} · ${timeAgo(s.created_at)}</div>
      </div>
      ${s.is_active ? `<button class="btn-ghost" onclick="revokeSession('${s.id}')">Revocar</button>` : ""}
    </li>
  `).join("");
}

function renderProducts(products) {
  const PRODUCT_META = {
    lifebound: { name: "Lifebound", desc: "USCIS Evidence Builder", icon: "📋" },
  };
  const list = document.getElementById("product-list");
  if (!products.length) {
    list.innerHTML = '<li style="color:var(--theme-muted);font-size:13px;padding:12px 0">Sin productos asignados.</li>';
    return;
  }
  list.innerHTML = products.map(p => {
    const meta = PRODUCT_META[p.product_id] || { name: p.product_id, desc: "", icon: "📦" };
    return `
      <li class="product-item">
        <div class="product-icon">${meta.icon}</div>
        <div class="product-body">
          <div class="product-name">${meta.name}</div>
          <div class="product-sub">${meta.desc}</div>
        </div>
        <span class="pill">Activo</span>
      </li>
    `;
  }).join("");
}

// ── Cargar datos ──────────────────────────────────────────

async function loadAccountData() {
  const res = await authFetch("/auth/account/data");
  if (!res) return;
  const data = await res.json();

  // Hero
  const { user, sessions, products, activity, stats } = data;
  document.getElementById("user-name").textContent  = user.name;
  document.getElementById("user-email").textContent = user.email;
  document.getElementById("user-role").textContent  = user.role;

  const avatar = document.getElementById("user-avatar");
  if (user.avatar_url) {
    avatar.innerHTML = `<img src="${user.avatar_url}" alt="${user.name}">`;
  } else {
    avatar.textContent = initials(user.name);
  }

  // Stats
  document.getElementById("stat-sessions").textContent = stats.active_sessions;
  document.getElementById("stat-products").textContent = stats.total_products;
  document.getElementById("stat-activity").textContent = stats.total_activity;

  // Actividad reciente (overview)
  renderActivity(activity.slice(0, 5), document.getElementById("overview-activity"));

  // Actividad completa
  renderActivity(activity, document.getElementById("full-activity"));

  // Sesiones
  renderSessions(sessions);

  // Productos
  renderProducts(products);

  // Perfil
  document.getElementById("profile-name").value  = user.name;
  document.getElementById("profile-email").value  = user.email;
  document.getElementById("profile-role").value   = user.role;
  document.getElementById("profile-since").value  = formatDate(user.created_at);
}

// ── Guardar perfil ────────────────────────────────────────

async function saveProfile() {
  const name = document.getElementById("profile-name").value.trim();
  const msg  = document.getElementById("save-msg");

  if (!name) { msg.textContent = "El nombre no puede estar vacío."; return; }

  const res = await authFetch("/auth/account/profile", {
    method: "PUT",
    body: JSON.stringify({ name }),
  });
  if (!res) return;

  if (res.ok) {
    const data = await res.json();
    document.getElementById("user-name").textContent = data.user.name;
    document.getElementById("user-avatar").textContent = initials(data.user.name);
    msg.textContent = "✓ Guardado correctamente";
    setTimeout(() => msg.textContent = "", 3000);
  } else {
    const err = await res.json();
    msg.textContent = err.error || "Error al guardar.";
    msg.style.color = "#e24b4a";
  }
}

// ── Revocar sesión ────────────────────────────────────────

async function revokeSession(sessionId) {
  const res = await authFetch(`/auth/sessions/${sessionId}`, { method: "DELETE" });
  if (res && res.ok) loadAccountData();
}

// ── Navegación por tabs ───────────────────────────────────

function initTabs() {
  document.querySelectorAll(".nav-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      const name = tab.dataset.tab;
      document.querySelectorAll(".nav-tab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".tab-section").forEach(s => s.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById(`tab-${name}`)?.classList.add("active");
    });
  });
}

// ── Init ──────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  loadAccountData();
  document.getElementById("save-profile")?.addEventListener("click", saveProfile);
});
