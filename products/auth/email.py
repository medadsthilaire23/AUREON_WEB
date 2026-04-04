"""
products/auth/email.py
======================
Envío de emails transaccionales via Resend.

v3 — ModuleGate checkpoint en _send().
     El gate registra OP007 (email_send) en EventRegistry.
     Si Resend falla, el evento llega a FAILED y el Conductor actúa.
"""

import os
import logging
import resend

log = logging.getLogger("aureon.email")

resend.api_key = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM     = os.environ.get("EMAIL_FROM", "auth@aureon.com")
APP_URL        = os.environ.get("APP_URL",    "https://aureon.com")

# ModuleGate — inyectado en Fase 2 desde wiring.py
# None hasta que wire_auth() lo inyecte.
_module_gate = None


def set_module_gate(gate) -> None:
    """Llamado desde wiring.py en Fase 2."""
    global _module_gate
    _module_gate = gate


# ── Helper interno ─────────────────────────────────────────────────────────

def _send(to: str, subject: str, html: str, op_id: str = "OP007") -> bool:
    """
    Envía el email via Resend.

    v3 — si hay ModuleGate inyectado, registra el intento y el resultado.
    Si no hay gate, funciona igual que v2 (fail-open).

    Args:
        op_id → op_id específico del tipo de email (OP007_001, OP007_002…)
                por defecto OP007 (raíz) si no se especifica.
    """
    # Obtener event_id de Flask g si está disponible (request activa)
    event_id = _get_event_id()

    # Registrar intento en ModuleGate
    if _module_gate is not None and event_id:
        _module_gate.record_pending(event_id, op_id)

    try:
        resend.Emails.send({
            "from":    EMAIL_FROM,
            "to":      [to],
            "subject": subject,
            "html":    html,
        })
        log.info("Email enviado a %s — %s", to, subject)

        # Registrar éxito
        if _module_gate is not None and event_id:
            _module_gate.record_ok(event_id, op_id)

        return True

    except Exception as e:
        log.error("Error enviando email a %s: %s", to, e)

        # Registrar fallo — el Conductor lo procesará en scan_registry()
        if _module_gate is not None and event_id:
            _module_gate.record_fail(event_id, op_id, error=str(e))

        return False


def _get_event_id() -> str | None:
    """
    Intenta obtener el event_id de g (Flask request context).
    Retorna None si no hay request activa (tests, tareas en background).
    """
    try:
        from flask import g
        return getattr(g, "event_id", None)
    except RuntimeError:
        return None


# ── Template base ──────────────────────────────────────────────────────────

def _base_template(content: str) -> str:
    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
    <body style="margin:0;padding:0;background:#f4f4f5;font-family:sans-serif">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr><td align="center" style="padding:40px 16px">
          <table width="480" cellpadding="0" cellspacing="0"
                 style="background:#fff;border-radius:12px;overflow:hidden;
                        box-shadow:0 1px 4px rgba(0,0,0,.08)">
            <tr>
              <td style="background:#16a34a;padding:28px 40px">
                <span style="font-size:22px;font-weight:700;color:#fff;letter-spacing:.5px">
                  Aureon
                </span>
              </td>
            </tr>
            <tr>
              <td style="padding:36px 40px;color:#1a1a1a;font-size:15px;line-height:1.6">
                {content}
              </td>
            </tr>
            <tr>
              <td style="padding:20px 40px;background:#f9fafb;
                         color:#6b7280;font-size:12px;border-top:1px solid #e5e7eb">
                Este email fue enviado desde Aureon. Si no lo solicitaste, ignóralo.<br>
                <a href="{APP_URL}" style="color:#16a34a;text-decoration:none">{APP_URL}</a>
              </td>
            </tr>
          </table>
        </td></tr>
      </table>
    </body>
    </html>
    """


# ══════════════════════════════════════════════════════════
# 1. VERIFICACIÓN DE CUENTA                    OP007_001
# ══════════════════════════════════════════════════════════

def send_verification_email(to: str, name: str, token: str) -> bool:
    url     = f"{APP_URL}/auth/verify-email?token={token}"
    content = f"""
        <h2 style="margin:0 0 16px;color:#16a34a">Bienvenido a Aureon, {name} 👋</h2>
        <p>Confirma tu correo electrónico para activar tu cuenta.</p>
        <p style="margin:28px 0">
          <a href="{url}"
             style="background:#16a34a;color:#fff;padding:12px 28px;
                    border-radius:8px;text-decoration:none;font-weight:600;font-size:15px">
            Confirmar email
          </a>
        </p>
        <p style="color:#6b7280;font-size:13px">
          Este enlace expira en 24 horas.<br>
          Si no creaste esta cuenta, ignora este mensaje.
        </p>
    """
    return _send(to, "Confirma tu cuenta Aureon", _base_template(content), op_id="OP007_001")


# ══════════════════════════════════════════════════════════
# 2. ALERTA DE NUEVO DISPOSITIVO               OP007_002
# ══════════════════════════════════════════════════════════

def send_new_device_alert(to: str, name: str, device_name: str,
                          ip: str, city: str = "", country: str = "") -> bool:
    location    = f"{city}, {country}".strip(", ") or ip
    url_devices = f"{APP_URL}/auth/devices"
    content = f"""
        <h2 style="margin:0 0 16px;color:#d97706">Nuevo acceso detectado</h2>
        <p>Hola {name}, detectamos un inicio de sesión desde un dispositivo nuevo:</p>
        <table style="margin:20px 0;border-collapse:collapse;width:100%">
          <tr>
            <td style="padding:8px 0;color:#6b7280;width:120px">Dispositivo</td>
            <td style="padding:8px 0;font-weight:500">{device_name}</td>
          </tr>
          <tr>
            <td style="padding:8px 0;color:#6b7280">Ubicación</td>
            <td style="padding:8px 0;font-weight:500">{location}</td>
          </tr>
          <tr>
            <td style="padding:8px 0;color:#6b7280">IP</td>
            <td style="padding:8px 0;font-weight:500">{ip}</td>
          </tr>
        </table>
        <p style="margin:24px 0">
          <a href="{url_devices}"
             style="background:#dc2626;color:#fff;padding:12px 28px;
                    border-radius:8px;text-decoration:none;font-weight:600;font-size:15px">
            Administrar dispositivos
          </a>
        </p>
    """
    return _send(to, "Nuevo acceso a tu cuenta Aureon", _base_template(content), op_id="OP007_002")


# ══════════════════════════════════════════════════════════
# 3. RESET DE CONTRASEÑA                       OP007_003
# ══════════════════════════════════════════════════════════

def send_reset_password_email(to: str, name: str, token: str) -> bool:
    url     = f"{APP_URL}/auth/reset-password?token={token}"
    content = f"""
        <h2 style="margin:0 0 16px;color:#1a1a1a">Restablecer contraseña</h2>
        <p>Hola {name}, recibimos una solicitud para restablecer tu contraseña Aureon.</p>
        <p style="margin:28px 0">
          <a href="{url}"
             style="background:#16a34a;color:#fff;padding:12px 28px;
                    border-radius:8px;text-decoration:none;font-weight:600;font-size:15px">
            Restablecer contraseña
          </a>
        </p>
        <p style="color:#6b7280;font-size:13px">
          Este enlace expira en 1 hora.<br>
          Si no solicitaste este cambio, ignóralo.
        </p>
    """
    return _send(to, "Restablecer contraseña Aureon", _base_template(content), op_id="OP007_003")


# ══════════════════════════════════════════════════════════
# 4. SESIONES REVOCADAS                        OP007_004
# ══════════════════════════════════════════════════════════

def send_sessions_revoked_email(to: str, name: str) -> bool:
    content = f"""
        <h2 style="margin:0 0 16px;color:#1a1a1a">Sesiones cerradas</h2>
        <p>Hola {name}, todas tus sesiones activas en Aureon han sido cerradas.</p>
        <p>Si no realizaste esta acción, cambia tu contraseña inmediatamente:</p>
        <p style="margin:28px 0">
          <a href="{APP_URL}/auth/reset-password"
             style="background:#dc2626;color:#fff;padding:12px 28px;
                    border-radius:8px;text-decoration:none;font-weight:600;font-size:15px">
            Cambiar contraseña
          </a>
        </p>
    """
    return _send(to, "Todas tus sesiones han sido cerradas", _base_template(content), op_id="OP007_004")