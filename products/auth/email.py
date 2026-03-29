"""
products/auth/email.py
======================
Envío de emails transaccionales via Resend.

Emails que maneja:
    - Verificación de cuenta al registrarse
    - Alerta de nuevo dispositivo / login sospechoso
    - Reset de contraseña
    - Confirmación de cierre de todas las sesiones
"""

import os
import logging
import resend

log = logging.getLogger("aureon.email")

resend.api_key = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM     = os.environ.get("EMAIL_FROM", "auth@aureon.com")
APP_URL        = os.environ.get("APP_URL", "https://aureon.com")


# ── Helper interno ─────────────────────────────────────────
def _send(to: str, subject: str, html: str) -> bool:
    try:
        resend.Emails.send({
            "from":    EMAIL_FROM,
            "to":      [to],
            "subject": subject,
            "html":    html,
        })
        log.info("Email enviado a %s — %s", to, subject)
        return True
    except Exception as e:
        log.error("Error enviando email a %s: %s", to, e)
        return False


def _base_template(content: str) -> str:
    """Wrapper HTML base para todos los emails."""
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
            <!-- Header -->
            <tr>
              <td style="background:#16a34a;padding:28px 40px">
                <span style="font-size:22px;font-weight:700;color:#fff;letter-spacing:.5px">
                  Aureon
                </span>
              </td>
            </tr>
            <!-- Content -->
            <tr>
              <td style="padding:36px 40px;color:#1a1a1a;font-size:15px;line-height:1.6">
                {content}
              </td>
            </tr>
            <!-- Footer -->
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
# 1. VERIFICACIÓN DE CUENTA
# ══════════════════════════════════════════════════════════

def send_verification_email(to: str, name: str, token: str) -> bool:
    url     = f"{APP_URL}/auth/verify-email?token={token}"
    content = f"""
        <h2 style="margin:0 0 16px;color:#16a34a">Bienvenido a Aureon, {name} 👋</h2>
        <p>Confirma tu correo electrónico para activar tu cuenta y acceder
           a todos los productos del ecosistema Aureon.</p>
        <p style="margin:28px 0">
          <a href="{url}"
             style="background:#16a34a;color:#fff;padding:12px 28px;
                    border-radius:8px;text-decoration:none;font-weight:600;
                    font-size:15px">
            Confirmar email
          </a>
        </p>
        <p style="color:#6b7280;font-size:13px">
          Este enlace expira en 24 horas.<br>
          Si no creaste esta cuenta, ignora este mensaje.
        </p>
    """
    return _send(to, "Confirma tu cuenta Aureon", _base_template(content))


# ══════════════════════════════════════════════════════════
# 2. ALERTA DE NUEVO DISPOSITIVO
# ══════════════════════════════════════════════════════════

def send_new_device_alert(to: str, name: str, device_name: str,
                          ip: str, city: str = "", country: str = "") -> bool:
    location = f"{city}, {country}".strip(", ") or ip
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
        <p>¿No fuiste tú? Cierra la sesión inmediatamente:</p>
        <p style="margin:24px 0">
          <a href="{url_devices}"
             style="background:#dc2626;color:#fff;padding:12px 28px;
                    border-radius:8px;text-decoration:none;font-weight:600;
                    font-size:15px">
            Administrar dispositivos
          </a>
        </p>
        <p style="color:#6b7280;font-size:13px">
          Si fuiste tú, puedes ignorar este mensaje.
        </p>
    """
    return _send(to, "Nuevo acceso a tu cuenta Aureon", _base_template(content))


# ══════════════════════════════════════════════════════════
# 3. RESET DE CONTRASEÑA
# ══════════════════════════════════════════════════════════

def send_reset_password_email(to: str, name: str, token: str) -> bool:
    url     = f"{APP_URL}/auth/reset-password?token={token}"
    content = f"""
        <h2 style="margin:0 0 16px;color:#1a1a1a">Restablecer contraseña</h2>
        <p>Hola {name}, recibimos una solicitud para restablecer
           la contraseña de tu cuenta Aureon.</p>
        <p style="margin:28px 0">
          <a href="{url}"
             style="background:#16a34a;color:#fff;padding:12px 28px;
                    border-radius:8px;text-decoration:none;font-weight:600;
                    font-size:15px">
            Restablecer contraseña
          </a>
        </p>
        <p style="color:#6b7280;font-size:13px">
          Este enlace expira en 1 hora.<br>
          Si no solicitaste este cambio, ignora este mensaje —
          tu contraseña no será modificada.
        </p>
    """
    return _send(to, "Restablecer contraseña Aureon", _base_template(content))


# ══════════════════════════════════════════════════════════
# 4. CONFIRMACIÓN DE CIERRE DE TODAS LAS SESIONES
# ══════════════════════════════════════════════════════════

def send_sessions_revoked_email(to: str, name: str) -> bool:
    content = f"""
        <h2 style="margin:0 0 16px;color:#1a1a1a">Sesiones cerradas</h2>
        <p>Hola {name}, todas tus sesiones activas en Aureon han sido cerradas
           exitosamente.</p>
        <p>Si no realizaste esta acción, cambia tu contraseña inmediatamente:</p>
        <p style="margin:28px 0">
          <a href="{APP_URL}/auth/reset-password"
             style="background:#dc2626;color:#fff;padding:12px 28px;
                    border-radius:8px;text-decoration:none;font-weight:600;
                    font-size:15px">
            Cambiar contraseña
          </a>
        </p>
    """
    return _send(to, "Todas tus sesiones han sido cerradas", _base_template(content))