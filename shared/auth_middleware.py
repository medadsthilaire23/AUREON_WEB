"""
shared/auth_middleware.py
=========================
Decorator require_auth importable desde cualquier producto AUREON.

Uso:
    from shared.auth_middleware import require_auth

    @lifebound_bp.route("/api/generate", methods=["POST"])
    @require_auth
    def generate():
        user_id    = g.user_id
        session_id = g.session_id
        ...
"""

import logging
from functools import wraps
from datetime import datetime, timezone

import jwt
from flask import g, jsonify, request

from products.auth.utils import decode_token, hash_token
from products.auth.models import UserSession
from shared.db import db

log = logging.getLogger("aureon.auth")


# ══════════════════════════════════════════════════════════
# REQUIRE AUTH — falla si no hay token válido
# ══════════════════════════════════════════════════════════

def require_auth(f):
    """
    Protege un endpoint — devuelve 401 si el token es inválido,
    expirado o la sesión fue revocada.
    Inyecta en g: user_id, session_id, session.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # 1. Extraer token del header Authorization: Bearer <token>
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Token requerido"}), 401

        token = auth_header.replace("Bearer ", "", 1).strip()

        # 2. Decodificar y verificar JWT
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expirado"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Token inválido"}), 401

        # 3. Verificar que sea un access token (no refresh)
        if payload.get("type") != "access":
            return jsonify({"error": "Tipo de token inválido"}), 401

        # 4. Verificar que la sesión existe y no fue revocada
        token_hash = hash_token(token)
        session    = UserSession.query.filter_by(
            token_hash=token_hash,
            revoked_at=None,
        ).first()

        if not session:
            return jsonify({"error": "Sesión inválida o revocada"}), 401

        # 5. Actualizar last_active_at
        session.last_active_at = datetime.now(timezone.utc)
        db.session.commit()

        # 6. Inyectar en contexto Flask
        g.user_id    = payload["sub"]
        g.session_id = payload["session_id"]
        g.session    = session

        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════════════════════
# OPTIONAL AUTH — no falla si no hay token
# ══════════════════════════════════════════════════════════

def optional_auth(f):
    """
    Como require_auth pero no falla si no hay token.
    g.user_id = None si el usuario no está autenticado.

    Útil para endpoints públicos que tienen comportamiento
    diferente si hay sesión activa (ej. pantalla de consent).
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        g.user_id    = None
        g.session_id = None
        g.session    = None

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return f(*args, **kwargs)

        token = auth_header.replace("Bearer ", "", 1).strip()

        try:
            payload    = decode_token(token)
            token_hash = hash_token(token)
            session    = UserSession.query.filter_by(
                token_hash=token_hash,
                revoked_at=None,
            ).first()

            if session and payload.get("type") == "access":
                session.last_active_at = datetime.now(timezone.utc)
                db.session.commit()
                g.user_id    = payload["sub"]
                g.session_id = payload["session_id"]
                g.session    = session

        except Exception:
            pass  # token inválido o expirado — continuar como anónimo

        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════════════════════
# REQUIRE VERIFIED — falla si el email no está verificado
# ══════════════════════════════════════════════════════════

def require_verified(f):
    """
    Combina require_auth + verifica que el email esté confirmado.
    Útil para endpoints sensibles como generar PDFs o cambiar contraseña.
    """
    @wraps(f)
    @require_auth
    def decorated(*args, **kwargs):
        from products.auth.models import User
        user = User.query.get(g.user_id)
        if not user or not user.is_verified:
            return jsonify({"error": "Email no verificado"}), 403
        return f(*args, **kwargs)
    return decorated