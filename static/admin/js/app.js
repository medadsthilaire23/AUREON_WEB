// js/app.js
// ── Init, routing de páginas y auto-refresh ───────────────────────────────────

/** Cambia la página visible y marca el nav-item activo */
function showPage(name, el) {
  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
  document.getElementById("page-" + name).classList.add("active");
  el.classList.add("active");
  closeDrawer();
  closePanel();
}

// ── Arranque ──────────────────────────────────────────────────────────────────
loadAll();
setInterval(loadAll, 15000);