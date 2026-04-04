# shared/auth_middleware.py
# ══════════════════════════════════════════════════════════════════════════════
# Middleware desacoplado (sin imports de products).
# Dependencias se inyectan en Fase 2 desde wiring.py.
#
# v3 — añadido HttpGate checkpoint en before_request.
# ══════════════════════════════════════════════════════════════════════════════

import logging
from functools import wraps
from datetime import datetime, timezone

from flask import g, jsonify, request

log = logging.getLogger("aureon.auth")

# ══════════════════════════════════════════════════════════
# DEPENDENCIAS INYECTADAS (Fase 2)
# ══════════════════════════════════════════════════════════

_decode_token = None
_hash_token   = None
_UserSession  = None
_User         = None
_db           = None
_conductor    = None
_http_gate    = None   # ← v3: HttpGate inyectado en Fase 2
_wired        = False


def configure_auth_middleware(
    decode_token,
    hash_token,
    user_session_model,
    user_model,
    db_instance,
    conductor  = None,
    http_gate  = None,   # ← v3: opcional — sin él el middleware funciona igual
):
    """
    Fase 2 — Wiring.
    Llamar desde wiring.py después de registrar todos los blueprints.
    """
    global _decode_token, _hash_token, _UserSession, _User, _db
    global _conductor, _http_gate, _wired

    _decode_token = decode_token
    _hash_token   = hash_token
    _UserSession  = user_session_model
    _User         = user_model
    _db           = db_instance
    _conductor    = conductor
    _http_gate    = http_gate
    _wired        = True

    log.info("auth_middleware wired correctamente")


def _check_configured():
    if not _wired:
        raise RuntimeError(
            "auth_middleware no está configurado. "
            "Llama configure_auth_middleware() en wiring.py (Fase 2)."
        )


# ══════════════════════════════════════════════════════════
# BEFORE REQUEST — HttpGate checkpoint (v3)
# ══════════════════════════════════════════════════════════

def register_http_gate(app) -> None:
    """
    Registra el checkpoint del HttpGate en before_request.
    Llamar desde wiring.py después de configure_auth_middleware().

    El HttpGate:
      1. Genera el event_id de la request (timestamp compacto)
      2. Registra OP001 (o la raíz de la operación HTTP) en EventRegistry
      3. Si el gate está CLOSED, bloquea la request con 503

    El event_id queda en g.event_id — disponible para el resto
    de la cadena (DbGate, ModuleGate).
    """
    @app.before_request
    def _http_gate_checkpoint():
        if _http_gate is None:
            return None   # sin gate inyectado — fail-open

        try:
            result = _http_gate.scan(request)

            # El gate asigna el event_id y lo deja en g
            g.event_id = getattr(result, "event_id", None)

            # Si el gate está CLOSED, bloquea la request
            if not result.allowed:
                log.warning(
                    "[HttpGate] request bloqueada — op=%s event=%s",
                    getattr(result, "op_id", "?"),
                    g.event_id,
                )
                return jsonify({
                    "error":   "Sistema temporalmente no disponible",
                    "code":    "HTTP_GATE_CLOSED",
                    "event_id": g.event_id,
                }), 503

        except Exception as e:
            # El gate nunca debe romper la request — fail-open
            log.error("[HttpGate] error en checkpoint: %s", e)

        return None


# ══════════════════════════════════════════════════════════
# REQUIRE AUTH
# ══════════════════════════════════════════════════════════

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        _check_configured()

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Token requerido"}), 401

        token = auth_header.replace("Bearer ", "", 1).strip()

        try:
            payload = _decode_token(token)
        except Exception:
            return jsonify({"error": "Token inválido o expirado"}), 401

        if payload.get("type") != "access":
            return jsonify({"error": "Tipo de token inválido"}), 401

        token_hash = _hash_token(token)

        session = _UserSession.query.filter_by(
            token_hash=token_hash,
            revoked_at=None,
        ).first()

        if not session:
            return jsonify({"error": "Sesión inválida o revocada"}), 401

        session.last_active_at = datetime.now(timezone.utc)
        _db.session.commit()

        g.user_id    = payload["sub"]
        g.session_id = payload["session_id"]
        g.session    = session

        return f(*args, **kwargs)

    return decorated


# ══════════════════════════════════════════════════════════
# OPTIONAL AUTH
# ══════════════════════════════════════════════════════════

def optional_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        _check_configured()

        g.user_id    = None
        g.session_id = None
        g.session    = None

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return f(*args, **kwargs)

        token = auth_header.replace("Bearer ", "", 1).strip()

        try:
            payload    = _decode_token(token)
            token_hash = _hash_token(token)

            session = _UserSession.query.filter_by(
                token_hash=token_hash,
                revoked_at=None,
            ).first()

            if session and payload.get("type") == "access":
                session.last_active_at = datetime.now(timezone.utc)
                _db.session.commit()

                g.user_id    = payload["sub"]
                g.session_id = payload["session_id"]
                g.session    = session

        except Exception:
            pass

        return f(*args, **kwargs)

    return decorated


# ══════════════════════════════════════════════════════════
# REQUIRE VERIFIED
# ══════════════════════════════════════════════════════════

def require_verified(f):
    @wraps(f)
    @require_auth
    def decorated(*args, **kwargs):
        if not _User:
            return jsonify({"error": "User model not configured"}), 500

        user = _User.query.get(g.user_id)
        if not user or not user.is_verified:
            return jsonify({"error": "Email no verificado"}), 403

        return f(*args, **kwargs)

    return decorated