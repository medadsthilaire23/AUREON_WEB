# shared/auth_middleware.py
# ══════════════════════════════════════════════════════════════════════════════
# Middleware desacoplado (sin imports de products).
# Dependencias se inyectan en Fase 2 desde wiring.py.
#
# v3.2 — DbGate en require_auth y optional_auth.
#         Toda verificación de sesión pasa por OP008_002.
#         Esto hace visible el tráfico de lifebound y cualquier
#         producto futuro en el dashboard sin tocar sus archivos.
# v3.1 — g.op_id expuesto desde HttpGate.scan() para que el Tracer
#         pueda llamar record_ok(event_id, op_id) en finish().
# v3   — HttpGate checkpoint en before_request.
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
_http_gate    = None
_db_gate      = None   # ← v3.2: DbGate para require_auth
_wired        = False


def configure_auth_middleware(
    decode_token,
    hash_token,
    user_session_model,
    user_model,
    db_instance,
    conductor = None,
    http_gate = None,
    db_gate   = None,   # ← v3.2: opcional — sin él funciona igual que v3.1
):
    """
    Fase 2 — Wiring.
    Llamar desde wiring.py después de registrar todos los blueprints.
    """
    global _decode_token, _hash_token, _UserSession, _User, _db
    global _conductor, _http_gate, _db_gate, _wired

    _decode_token = decode_token
    _hash_token   = hash_token
    _UserSession  = user_session_model
    _User         = user_model
    _db           = db_instance
    _conductor    = conductor
    _http_gate    = http_gate
    _db_gate      = db_gate
    _wired        = True

    log.info("auth_middleware wired correctamente (db_gate=%s)", db_gate is not None)


def _check_configured():
    if not _wired:
        raise RuntimeError(
            "auth_middleware no está configurado. "
            "Llama configure_auth_middleware() en wiring.py (Fase 2)."
        )


# ══════════════════════════════════════════════════════════
# BEFORE REQUEST — HttpGate checkpoint (v3.1)
# ══════════════════════════════════════════════════════════

def register_http_gate(app) -> None:
    """
    Registra el checkpoint del HttpGate en before_request.
    Llamar desde wiring.py después de configure_auth_middleware().
    """
    @app.before_request
    def _http_gate_checkpoint():
        if _http_gate is None:
            return None

        try:
            result = _http_gate.scan(request)

            g.event_id = getattr(result, "event_id", None)
            g.op_id    = getattr(result, "op_id",    "OP001")

            if not result.allowed:
                log.warning(
                    "[HttpGate] request bloqueada — op=%s event=%s",
                    g.op_id, g.event_id,
                )
                return jsonify({
                    "error":    "Sistema temporalmente no disponible",
                    "code":     "HTTP_GATE_CLOSED",
                    "event_id": g.event_id,
                }), 503

        except Exception as e:
            log.error("[HttpGate] error en checkpoint: %s", e)

        return None


# ══════════════════════════════════════════════════════════
# REQUIRE AUTH — v3.2 con DbGate
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

        # ── OP008_002 — verificación de sesión en DB ──────────────────────
        # Pasa por DbGate si está disponible — hace visible todo el tráfico
        # de lifebound y cualquier producto futuro sin tocar sus archivos.
        try:
            event_id = getattr(g, "event_id", None)

            if _db_gate is not None and event_id:
                with _db_gate.scan("OP008_002"):
                    session = _UserSession.query.filter_by(
                        token_hash=token_hash,
                        revoked_at=None,
                    ).first()

                    if session:
                        session.last_active_at = datetime.now(timezone.utc)
                        _db.session.commit()
            else:
                session = _UserSession.query.filter_by(
                    token_hash=token_hash,
                    revoked_at=None,
                ).first()

                if session:
                    session.last_active_at = datetime.now(timezone.utc)
                    _db.session.commit()

        except Exception as e:
            log.error("[require_auth] DB error: %s", e)
            return jsonify({"error": "Error al verificar sesión"}), 500

        if not session:
            return jsonify({"error": "Sesión inválida o revocada"}), 401

        g.user_id    = payload["sub"]
        g.session_id = payload["session_id"]
        g.session    = session

        return f(*args, **kwargs)

    return decorated


# ══════════════════════════════════════════════════════════
# OPTIONAL AUTH — v3.2 con DbGate
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
            event_id   = getattr(g, "event_id", None)

            if _db_gate is not None and event_id:
                with _db_gate.scan("OP008_002"):
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
            else:
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