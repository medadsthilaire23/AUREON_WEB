"""
products/auth/oauth.py
======================
OAuth 2.0 — Google y GitHub.

v3 — ModuleGate checkpoints en:
     - authorize_access_token()   → OP003_002_001 / OP004_002_001
     - userinfo / user/emails     → OP003_002_002 / OP004_002_002 / OP004_002_003
"""

import os
import logging
from datetime import datetime, timezone

import requests
from authlib.integrations.flask_client import OAuth
from flask import Blueprint, g, jsonify, redirect, request, session, url_for

from shared.db import db
from products.auth.models import User, UserIdentity, UserProduct, UserDevice, UserSession
from products.auth.utils import (
    create_access_token, create_refresh_token,
    hash_token, parse_device, is_new_device,
)
from products.auth.email import send_new_device_alert

log = logging.getLogger("aureon.oauth")

oauth_bp = Blueprint("oauth", __name__, url_prefix="/auth/oauth")

APP_URL = os.environ.get("APP_URL", "https://aureon.com")

# ModuleGate — inyectado en Fase 2 desde wiring.py
_module_gate = None


def set_module_gate(gate) -> None:
    """Llamado desde wiring.py en Fase 2."""
    global _module_gate
    _module_gate = gate


# ── Inicializar Authlib OAuth ──────────────────────────────────────────────

oauth = OAuth()


def init_oauth(app):
    oauth.init_app(app)

    oauth.register(
        name="google",
        client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

    oauth.register(
        name="github",
        client_id=os.environ.get("GITHUB_CLIENT_ID"),
        client_secret=os.environ.get("GITHUB_CLIENT_SECRET"),
        access_token_url="https://github.com/login/oauth/access_token",
        authorize_url="https://github.com/login/oauth/authorize",
        api_base_url="https://api.github.com/",
        client_kwargs={"scope": "user:email"},
    )


# ── Helpers de gate ────────────────────────────────────────────────────────

def _event_id() -> str | None:
    try:
        from flask import g
        return getattr(g, "event_id", None)
    except RuntimeError:
        return None


def _gate_pending(op_id: str) -> None:
    if _module_gate and _event_id():
        _module_gate.record_pending(_event_id(), op_id)


def _gate_ok(op_id: str) -> None:
    if _module_gate and _event_id():
        _module_gate.record_ok(_event_id(), op_id)


def _gate_fail(op_id: str, error: str) -> None:
    if _module_gate and _event_id():
        _module_gate.record_fail(_event_id(), op_id, error=error)


# ══════════════════════════════════════════════════════════
# HELPERS INTERNOS
# ══════════════════════════════════════════════════════════

def _get_or_create_user(provider: str, provider_id: str,
                        email: str, name: str, avatar_url: str = None) -> User:
    identity = UserIdentity.query.filter_by(
        provider=provider,
        provider_id=str(provider_id),
    ).first()

    if identity:
        return User.query.get(identity.user_id)

    user = User.query.filter_by(email=email).first()

    if not user:
        user = User(
            name=name,
            email=email,
            avatar_url=avatar_url,
            is_verified=True,
        )
        db.session.add(user)
        db.session.flush()
        db.session.add(UserProduct(user_id=user.id, product_id="lifebound"))

    new_identity = UserIdentity(
        user_id=user.id,
        provider=provider,
        provider_id=str(provider_id),
    )
    db.session.add(new_identity)

    if not user.is_verified:
        user.is_verified = True

    db.session.commit()
    return user


def _create_oauth_session(user: User) -> dict:
    device_info = parse_device(request)
    new_device  = is_new_device(user, device_info)

    device = None
    if device_info.get("fingerprint"):
        device = UserDevice.query.filter_by(
            user_id=user.id,
            fingerprint=device_info["fingerprint"],
        ).first()

    if not device:
        device = UserDevice(user_id=user.id, **device_info)
        db.session.add(device)
        db.session.flush()

    device.last_seen_at = datetime.now(timezone.utc)

    import uuid as _uuid
    session_id = str(_uuid.uuid4())

    access_token  = create_access_token(user.id, session_id)
    refresh_token = create_refresh_token(user.id, session_id)

    user_session = UserSession(
        id=session_id,
        user_id=user.id,
        device_id=device.id,
        ip=device_info["ip"],
        token_hash=hash_token(access_token),
        refresh_hash=hash_token(refresh_token),
    )
    db.session.add(user_session)
    db.session.commit()

    if new_device:
        send_new_device_alert(
            user.email, user.name,
            device_info["device_name"],
            device_info["ip"],
        )

    return {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "token_type":    "Bearer",
        "user":          user.to_dict(),
    }


def _oauth_redirect(tokens: dict):
    raw_redirect = session.pop("oauth_redirect", "/")
    session.pop("oauth_product_id", None)

    from urllib.parse import urlparse
    parsed       = urlparse(raw_redirect)
    clean_redirect = parsed.path or "/"

    session["oauth_access_token"]   = tokens["access_token"]
    session["oauth_refresh_token"]  = tokens["refresh_token"]
    session["oauth_final_redirect"] = clean_redirect
    return redirect(f"{APP_URL}/auth/oauth-complete")


# ══════════════════════════════════════════════════════════
# GOOGLE
# ══════════════════════════════════════════════════════════

@oauth_bp.route("/google")
def google_login():
    session["oauth_product_id"] = request.args.get("product_id", "")
    session["oauth_redirect"]   = request.args.get("redirect",    "/")
    callback_url = f"{APP_URL}/auth/oauth/google/callback"
    return oauth.google.authorize_redirect(callback_url)


@oauth_bp.route("/google/callback")
def google_callback():
    try:
        # OP003_002_001 — token exchange con Google
        _gate_pending("OP003_002_001")
        token = oauth.google.authorize_access_token()
        _gate_ok("OP003_002_001")

        # OP003_002_002 — obtener userinfo
        _gate_pending("OP003_002_002")
        userinfo = token.get("userinfo") or oauth.google.userinfo(token=token)
        _gate_ok("OP003_002_002")

    except Exception as e:
        log.error("Google OAuth error: %s", e)
        _gate_fail("OP003_002_001", str(e))
        return redirect(f"{APP_URL}/auth/login?error=google_failed")

    email       = userinfo.get("email", "").lower()
    name        = userinfo.get("name",  "Unknown")
    provider_id = userinfo.get("sub",   "")
    avatar_url  = userinfo.get("picture")

    if not email:
        return redirect(f"{APP_URL}/auth/login?error=no_email")

    user   = _get_or_create_user("google", provider_id, email, name, avatar_url)
    tokens = _create_oauth_session(user)

    log.info("Google login: %s", email)
    return _oauth_redirect(tokens)


# ══════════════════════════════════════════════════════════
# GITHUB
# ══════════════════════════════════════════════════════════

@oauth_bp.route("/github")
def github_login():
    session["oauth_product_id"] = request.args.get("product_id", "")
    session["oauth_redirect"]   = request.args.get("redirect",    "/")
    callback_url = f"{APP_URL}/auth/oauth/github/callback"
    return oauth.github.authorize_redirect(callback_url)


@oauth_bp.route("/github/callback")
def github_callback():
    try:
        # OP004_002_001 — token exchange con GitHub
        _gate_pending("OP004_002_001")
        oauth.github.authorize_access_token()
        _gate_ok("OP004_002_001")

        # OP004_002_002 — obtener perfil
        _gate_pending("OP004_002_002")
        resp = oauth.github.get("user")
        resp.raise_for_status()
        profile = resp.json()
        _gate_ok("OP004_002_002")

    except Exception as e:
        log.error("GitHub OAuth error: %s", e)
        _gate_fail("OP004_002_001", str(e))
        return redirect(f"{APP_URL}/auth/login?error=github_failed")

    provider_id = str(profile.get("id", ""))
    name        = profile.get("name") or profile.get("login", "Unknown")
    avatar_url  = profile.get("avatar_url")

    email = profile.get("email")
    if not email:
        email = _get_github_primary_email()

    if not email:
        return redirect(f"{APP_URL}/auth/login?error=no_email")

    email  = email.lower()
    user   = _get_or_create_user("github", provider_id, email, name, avatar_url)
    tokens = _create_oauth_session(user)

    log.info("GitHub login: %s", email)
    return _oauth_redirect(tokens)


def _get_github_primary_email() -> str | None:
    try:
        # OP004_002_003 — obtener emails de GitHub
        _gate_pending("OP004_002_003")
        resp = oauth.github.get("user/emails")
        resp.raise_for_status()
        emails = resp.json()
        _gate_ok("OP004_002_003")

        for entry in emails:
            if entry.get("primary") and entry.get("verified"):
                return entry.get("email")
    except Exception as e:
        log.warning("No se pudo obtener email de GitHub: %s", e)
        _gate_fail("OP004_002_003", str(e))
    return None


# ══════════════════════════════════════════════════════════
# IDENTIDADES
# ══════════════════════════════════════════════════════════

@oauth_bp.route("/identities", methods=["GET"])
def list_identities():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Token requerido"}), 401

    from products.auth.utils import decode_token
    try:
        payload = decode_token(auth_header.replace("Bearer ", "", 1).strip())
        user_id = payload["sub"]
    except Exception:
        return jsonify({"error": "Token inválido"}), 401

    identities = UserIdentity.query.filter_by(user_id=user_id).all()
    return jsonify({
        "identities": [
            {"provider": i.provider, "created_at": i.created_at.isoformat()}
            for i in identities
        ]
    }), 200


@oauth_bp.route("/identities/<provider>", methods=["DELETE"])
def unlink_provider(provider):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Token requerido"}), 401

    from products.auth.utils import decode_token
    from products.auth.models import UserPasskey
    try:
        payload = decode_token(auth_header.replace("Bearer ", "", 1).strip())
        user_id = payload["sub"]
    except Exception:
        return jsonify({"error": "Token inválido"}), 401

    identity = UserIdentity.query.filter_by(user_id=user_id, provider=provider).first()
    if not identity:
        return jsonify({"error": "Proveedor no vinculado"}), 404

    total_identities = UserIdentity.query.filter_by(user_id=user_id).count()
    total_passkeys   = UserPasskey.query.filter_by(user_id=user_id).count()

    if total_identities <= 1 and total_passkeys == 0:
        return jsonify({"error": "No puedes desvincular tu único método de login"}), 400

    db.session.delete(identity)
    db.session.commit()

    log.info("Proveedor desvinculado: user=%s provider=%s", user_id, provider)
    return jsonify({"message": f"{provider} desvinculado correctamente"}), 200