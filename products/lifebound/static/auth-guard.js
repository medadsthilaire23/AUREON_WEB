/**
 * auth-guard.js
 * =============
 * Verifica que el usuario tenga sesión Aureon válida antes
 * de mostrar el producto. Si no tiene sesión, redirige al
 * flujo SSO con el consent y vuelve al origen.
 *
 * Uso — agregar en el <head> de index.html de cada producto:
 *   <script src="/lifebound/static/auth-guard.js"></script>
 *
 * Configurar antes de cargar el script:
 *   window.AUREON_PRODUCT_ID = "lifebound";   ← id del producto
 *   window.AUREON_RETURN_URL = "/lifebound";  ← URL de retorno
 */

(async function () {
  const PRODUCT_ID = window.AUREON_PRODUCT_ID || "lifebound";
  const RETURN_URL = window.AUREON_RETURN_URL  || location.pathname;

  const consentUrl = `/auth/consent-page?product_id=${PRODUCT_ID}&redirect=${encodeURIComponent(RETURN_URL)}`;
  const loginUrl   = `/auth/login?redirect=${encodeURIComponent(consentUrl)}`;

  // ── Ocultar contenido mientras verificamos ──────────
  document.documentElement.style.visibility = "hidden";

  async function tryRefresh() {
    const refresh = localStorage.getItem("aureon_refresh");
    if (!refresh) return false;
    try {
      const res = await fetch("/auth/refresh", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ refresh_token: refresh }),
      });
      if (res.ok) {
        const data = await res.json();
        localStorage.setItem("aureon_token", data.access_token);
        return true;
      }
    } catch {}
    return false;
  }

  async function verify(token) {
    try {
      const res = await fetch("/auth/me", {
        headers: { Authorization: "Bearer " + token },
      });
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  let token = localStorage.getItem("aureon_token");

  // Sin token → ir a login
  if (!token) {
    window.location.replace(loginUrl);
    return;
  }

  let user = await verify(token);

  // Token expirado → intentar refresh
  if (!user) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      token = localStorage.getItem("aureon_token");
      user  = await verify(token);
    }
  }

  // Sin usuario válido → ir a login
  if (!user) {
    localStorage.removeItem("aureon_token");
    localStorage.removeItem("aureon_refresh");
    window.location.replace(loginUrl);
    return;
  }

  // Sin acceso al producto → ir a consent
  const hasAccess = (user.products || []).some(p => p.product_id === PRODUCT_ID);
  if (!hasAccess) {
    window.location.replace(consentUrl);
    return;
  }

  // ✓ Todo OK — mostrar el producto
  document.documentElement.style.visibility = "visible";

  // Exponer usuario globalmente para que el producto lo use
  window.AUREON_USER  = user;
  window.AUREON_TOKEN = token;

})();