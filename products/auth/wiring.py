# products/auth/wiring.py
# ══════════════════════════════════════════════════════════════════════════════
# Fase 2 (Wiring) del módulo auth.
#
# Responsabilidades:
#   - Inyectar dependencias en AuthContext
#   - Configurar middleware desacoplado
#   - Registrar breakers y gates del módulo
#   - Registrar módulo en Conductor
#   - Validar consistencia del módulo
# ══════════════════════════════════════════════════════════════════════════════

from shared.db                      import db
from shared.auth_middleware         import configure_auth_middleware
from shared.control.registries.base import BreakerRegistry, GateRegistry

from products.auth.context import auth_context


# ── Configuración del subsistema de control ────────────────────────────────

_BREAKERS = [
    # name                  failure_threshold   recovery_timeout
    ("google_oauth",        5,                  60.0),
    ("github_oauth",        5,                  60.0),
    ("passkey_verify",      3,                  30.0),
    ("email_send",          4,                  120.0),
]

_GATES = [
    # name                  enabled
    ("oauth_google",        True),
    ("oauth_github",        True),
    ("passkey_login",       True),
    ("registration",        True),
]


def _wire_control_layer(app) -> None:
    """
    Registra circuit breakers y gates del módulo auth.
    Idempotente: si ya existen (hot-reload en dev) no lanza error.
    """
    for name, threshold, timeout in _BREAKERS:
        if name not in BreakerRegistry:
            BreakerRegistry.get(name,
                failure_threshold=threshold,
                recovery_timeout=timeout,
            )

    for name, enabled in _GATES:
        if name not in GateRegistry:
            GateRegistry.get(name, enabled=enabled)

    # ── Confirmación en arranque ──────────────────────────
    app.logger.info("  [✓] Control layer wired")

    for name, threshold, timeout in _BREAKERS:
        snap = BreakerRegistry.get(name).snapshot()
        app.logger.info(
            "      BREAKER %-20s  state=%-9s  threshold=%d  timeout=%.0fs",
            name, snap.state.value, threshold, timeout,
        )

    for name, enabled in _GATES:
        app.logger.info(
            "      GATE    %-20s  enabled=%s",
            name, enabled,
        )


# ── Punto de entrada principal ─────────────────────────────────────────────

def wire_auth(app, conductor) -> None:
    """
    Ejecuta el cableado completo del módulo auth.
    """

    # ═══════════════════════════════════════════════════════
    # IMPORTS LOCALES (ROMPEN CICLOS)
    # ═══════════════════════════════════════════════════════

    from products.auth.models import (
        User,
        UserIdentity,
        UserDevice,
        UserSession,
        UserProduct,
    )

    from products.auth.utils import (
        create_access_token,
        create_refresh_token,
        decode_token,
        hash_token,
        hash_password,
        verify_password,
        validate_password_strength,
        parse_device,
        is_new_device,
    )

    from products.auth.email import (
        send_verification_email,
        send_new_device_alert,
        send_reset_password_email,
        send_sessions_revoked_email,
    )

    # ═══════════════════════════════════════════════════════
    # SUBSISTEMA DE CONTROL
    # ═══════════════════════════════════════════════════════

    _wire_control_layer(app)

    # ═══════════════════════════════════════════════════════
    # INYECCIÓN EN CONTEXTO
    # ═══════════════════════════════════════════════════════

    auth_context.User                        = User
    auth_context.UserIdentity                = UserIdentity
    auth_context.UserDevice                  = UserDevice
    auth_context.UserSession                 = UserSession
    auth_context.UserProduct                 = UserProduct

    auth_context.create_access_token         = create_access_token
    auth_context.create_refresh_token        = create_refresh_token
    auth_context.decode_token                = decode_token
    auth_context.hash_token                  = hash_token

    auth_context.hash_password               = hash_password
    auth_context.verify_password             = verify_password
    auth_context.validate_password_strength  = validate_password_strength

    auth_context.parse_device                = parse_device
    auth_context.is_new_device               = is_new_device

    auth_context.send_verification_email     = send_verification_email
    auth_context.send_new_device_alert       = send_new_device_alert
    auth_context.send_reset_password_email   = send_reset_password_email
    auth_context.send_sessions_revoked_email = send_sessions_revoked_email

    auth_context.conductor                   = conductor
    auth_context.breaker_registry            = BreakerRegistry
    auth_context.gate_registry               = GateRegistry

    # ═══════════════════════════════════════════════════════
    # CONFIGURAR MIDDLEWARE (DESACOPLADO)
    # ═══════════════════════════════════════════════════════

    configure_auth_middleware(
        decode_token       = decode_token,
        hash_token         = hash_token,
        user_session_model = UserSession,
        user_model         = User,
        db_instance        = db,
        conductor          = conductor,
    )

    # ═══════════════════════════════════════════════════════
    # VALIDACIÓN DEL CONTEXTO (BOOT SAFETY)
    # ═══════════════════════════════════════════════════════

    auth_context.validate()

    # ═══════════════════════════════════════════════════════
    # REGISTRO EN CONDUCTOR
    # ═══════════════════════════════════════════════════════

    conductor.register_product("auth", {
        "status":   "active",
        "version":  "1.0",
        "healthy":  True,
        "breakers": [name for name, *_ in _BREAKERS],
        "gates":    [name for name, *_ in _GATES],
    })

    # ═══════════════════════════════════════════════════════
    # LOGGING DE ARRANQUE
    # ═══════════════════════════════════════════════════════

    app.logger.info(
        "  [✓] Auth wired — breakers=%d gates=%d",
        len(_BREAKERS), len(_GATES),
    )