# products/auth/wiring.py
# ══════════════════════════════════════════════════════════════════════════════
# Fase 2 (Wiring) del módulo auth — AUREON v3.0
#
# Cambios respecto a versión anterior:
#   - _get_or_create_gate no silencia excepciones — falla explícitamente
#   - wire_registry se llama siempre, incluso si el gate ya existía
#   - _wire_control_layer eliminado — los breakers v2 (failure_threshold,
#     recovery_timeout) no son compatibles con BreakerBase v3
#     Los breakers v3 los gestiona el Conductor + Timer, no parámetros fijos
#   - Los feature-flag gates (oauth_google, etc.) se mantienen en GateRegistry
# ══════════════════════════════════════════════════════════════════════════════

from shared.db                      import db
from shared.auth_middleware         import configure_auth_middleware, register_http_gate
from shared.control.registries.base import GateRegistry, BreakerRegistry, event_registry

from products.auth.context import auth_context


# ── Feature-flag gates (killswitches por funcionalidad) ───────────────────
# Distintos de los gates concretos (HttpGate, DbGate, ModuleGate).
# Estos controlan si una funcionalidad específica está habilitada.

_FEATURE_GATES = [
    ("oauth_google",  True),
    ("oauth_github",  True),
    ("passkey_login", True),
    ("registration",  True),
]


def _ensure_feature_gates(app) -> None:
    """Registra los feature-flag gates si no existen."""
    from shared.control.gates.base import Gate
    for name, enabled in _FEATURE_GATES:
        if name not in GateRegistry:
            GateRegistry.register(Gate(name=name, enabled=enabled))
    app.logger.info("  [✓] Feature gates: %s", [n for n, _ in _FEATURE_GATES])


def _get_or_create_concrete_gate(app, gate_class, gate_name: str):
    """
    Devuelve el gate concreto si ya está en GateRegistry,
    o lo crea, registra e inyecta wire_registry.

    No silencia excepciones — un gate concreto que falla al crearse
    es un error crítico de wiring.

    Llama wire_registry siempre — aunque el gate ya existiera,
    garantiza que el EventRegistry esté inyectado.
    """
    if gate_name in GateRegistry:
        gate = GateRegistry.get(gate_name)
    else:
        gate = gate_class(name=gate_name)
        GateRegistry.register(gate)
        app.logger.info("      GATE    %-20s  created", gate_name)

    # Siempre inyectar — idempotente si ya estaba inyectado
    if hasattr(gate, "wire_registry"):
        gate.wire_registry(event_registry)

    return gate


# ── Punto de entrada principal ─────────────────────────────────────────────

def wire_auth(app, conductor) -> None:

    # ═══════════════════════════════════════════════════════
    # IMPORTS LOCALES (rompen ciclos de importación)
    # ═══════════════════════════════════════════════════════

    from products.auth.models import (
        User, UserIdentity, UserDevice, UserSession, UserProduct,
    )
    from products.auth.utils import (
        create_access_token, create_refresh_token, decode_token,
        hash_token, hash_password, verify_password,
        validate_password_strength, parse_device, is_new_device,
    )
    from products.auth.email import (
        send_verification_email, send_new_device_alert,
        send_reset_password_email, send_sessions_revoked_email,
        set_module_gate as email_set_gate,
    )
    from products.auth.oauth   import set_module_gate as oauth_set_gate
    from products.auth.passkey import set_module_gate as passkey_set_gate

    from shared.control.gates.http_gate   import HttpGate
    from shared.control.gates.db_gate     import DbGate
    from shared.control.gates.module_gate import ModuleGate

    # ═══════════════════════════════════════════════════════
    # FEATURE GATES
    # ═══════════════════════════════════════════════════════

    _ensure_feature_gates(app)

    # ═══════════════════════════════════════════════════════
    # GATES CONCRETOS v3
    # ═══════════════════════════════════════════════════════

    http_gate   = _get_or_create_concrete_gate(app, HttpGate,   "HttpGate")
    db_gate     = _get_or_create_concrete_gate(app, DbGate,     "DbGate")
    module_gate = _get_or_create_concrete_gate(app, ModuleGate, "ModuleGate")

    app.logger.info(
        "  [✓] Gates concretos — HttpGate, DbGate, ModuleGate (registry inyectado)"
    )

    # ═══════════════════════════════════════════════════════
    # INYECCIÓN EN MÓDULOS EXTERNOS
    # ═══════════════════════════════════════════════════════

    oauth_set_gate(module_gate)
    passkey_set_gate(module_gate)
    email_set_gate(module_gate)
    app.logger.info("  [✓] ModuleGate inyectado en oauth, passkey, email")

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
    auth_context.gate_registry               = GateRegistry
    auth_context.breaker_registry            = BreakerRegistry

    # ═══════════════════════════════════════════════════════
    # MIDDLEWARE — HttpGate incluido
    # ═══════════════════════════════════════════════════════

    configure_auth_middleware(
        decode_token       = decode_token,
        hash_token         = hash_token,
        user_session_model = UserSession,
        user_model         = User,
        db_instance        = db,
        conductor          = conductor,
        http_gate          = http_gate,
    )

    register_http_gate(app)

    # ═══════════════════════════════════════════════════════
    # VALIDACIÓN DEL CONTEXTO
    # ═══════════════════════════════════════════════════════

    auth_context.validate()

    # ═══════════════════════════════════════════════════════
    # REGISTRO EN CONDUCTOR
    # ═══════════════════════════════════════════════════════

    conductor.register_product("auth", {
        "status":  "active",
        "version": "1.0",
        "healthy": True,
        "gates":   ["HttpGate", "DbGate", "ModuleGate"] + [n for n, _ in _FEATURE_GATES],
    })

    app.logger.info("  [✓] Auth wired")