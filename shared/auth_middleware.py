# shared/auth_middleware.py
# ══════════════════════════════════════════════════════════════════════════════
# Middleware desacoplado (sin imports de products).
# Dependencias se inyectan en Fase 2 desde wiring.py.
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
_wired        = False


def configure_auth_middleware(
    decode_token,
    hash_token,
    user_session_model,
    user_model,
    db_instance,
    conductor=None,       # ← opcional — no rompe llamadas sin él
):
    """
    Fase 2 — Wiring.
    Llamar desde wiring.py después de registrar todos los blueprints.

    conductor es opcional — si se inyecta, permite que el middleware
    reporte fallos de sesión al subsistema de control en el futuro.
    """
    global _decode_token, _hash_token, _UserSession, _User, _db, _conductor, _wired

    _decode_token = decode_token
    _hash_token   = hash_token
    _UserSession  = user_session_model
    _User         = user_model
    _db           = db_instance
    _conductor    = conductor
    _wired        = True

    log.info("auth_middleware wired correctamente")


def _check_configured():
    if not _wired:
        raise RuntimeError(
            "auth_middleware no está configurado. "
            "Llama configure_auth_middleware() en wiring.py (Fase 2)."
        )


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