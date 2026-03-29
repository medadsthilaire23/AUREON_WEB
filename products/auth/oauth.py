"""
products/auth/oauth.py
======================
OAuth 2.0 — Google y GitHub como métodos de login de respaldo.

Flujo por proveedor (2 pasos):
    1. GET  /auth/oauth/<provider>           → redirige al proveedor
    2. GET  /auth/oauth/<provider>/callback  → procesa respuesta y crea sesión

Proveedores soportados:
    - google
    - github

Si el email ya existe en Aureon (por cualquier proveedor),
se vincula automáticamente al mismo user_id — una sola cuenta.

Dependencia:
    pip install authlib requests
"""

import os
import logging
from datetime import datetime, timezone

import requests
from authlib.integrations.flask_client import OAuth
from flask import Blueprint, jsonify, redirect, request, session, url_for

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

# ── Inicializar Authlib OAuth ──────────────────────────────
oauth = OAuth()


def init_oauth(app):
    """
    Registra los proveedores OAuth en la app Flask.
    Llamar desde app.py después de crear la app.

        from products.auth.oauth import init_oauth
        init_oauth(app)
    """
    oauth.init_app(app)

    # ── Google ─────────────────────────────────────────────
    oauth.register(
        name="google",
        client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid email profile",
        },
    )

    # ── GitHub ─────────────────────────────────────────────
    oauth.register(
        name="github",
        client_id=os.environ.get("GITHUB_CLIENT_ID"),
        client_secret=os.environ.get("GITHUB_CLIENT_SECRET"),
        access_token_url="https://github.com/login/oauth/access_token",
        authorize_url="https://github.com/login/oauth/authorize",
        api_base_url="https://api.github.com/",
        client_kwargs={
            "scope": "user:email",
        },
    )


# ══════════════════════════════════════════════════════════
# HELPERS INTERNOS
# ══════════════════════════════════════════════════════════

def _get_or_create_user(provider: str, provider_id: str,
                        email: str, name: str, avatar_url: str = None) -> User:
    """
    Busca o crea un usuario Aureon a partir de los datos del proveedor OAuth.

    Lógica:
        1. Buscar UserIdentity por (provider, provider_id) → usuario ya vinculado
        2. Buscar User por email → vincular proveedor a cuenta existente
        3. Crear usuario nuevo → primera vez con este proveedor
    """
    # 1. Buscar identity existente
    identity = UserIdentity.query.filter_by(
        provider=provider,
        provider_id=str(provider_id),
    ).first()

    if identity:
        return User.query.get(identity.user_id)

    # 2. Buscar usuario por email (cuenta Aureon o de otro proveedor)
    user = User.query.filter_by(email=email).first()

    if not user:
        # 3. Crear usuario nuevo
        user = User(
            name=name,
            email=email,
            avatar_url=avatar_url,
            is_verified=True,  # OAuth ya verificó el email
        )
        db.session.add(user)
        db.session.flush()

        # Dar acceso a Lifebound por defecto
        db.session.add(UserProduct(user_id=user.id, product_id="lifebound"))

    # Vincular el proveedor OAuth al usuario
    new_identity = UserIdentity(
        user_id=user.id,
        provider=provider,
        provider_id=str(provider_id),
    )
    db.session.add(new_identity)

    # Marcar como verificado si no lo estaba
    if not user.is_verified:
        user.is_verified = True

    db.session.commit()
    return user


def _create_oauth_session(user: User) -> dict:
    """Crea sesión y retorna tokens tras login OAuth."""
    device_info = parse_device(request)
    new_device  = is_new_device(user, device_info)

    # Buscar o crear dispositivo
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

    # Generar session_id antes del INSERT para poder crear tokens sin flush
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

    # Alerta si es dispositivo nuevo
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
    """
    Guarda tokens en sesión Flask y redirige a /auth/oauth-complete
    que los mueve a localStorage limpiamente, sin tokens en la URL.
    """
    raw_redirect = session.pop("oauth_redirect", "/")
    session.pop("oauth_product_id", None)

    # Limpiar tokens acumulados en el redirect — tomar solo el path base
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(raw_redirect)
    clean_redirect = parsed.path  # solo el path, sin query params

    session["oauth_access_token"]   = tokens["access_token"]
    session["oauth_refresh_token"]  = tokens["refresh_token"]
    session["oauth_final_redirect"] = clean_redirect or "/"
    return redirect(f"{APP_URL}/auth/oauth-complete")


# ══════════════════════════════════════════════════════════
# GOOGLE
# ══════════════════════════════════════════════════════════

@oauth_bp.route("/google")
def google_login():
    """
    Inicia el flujo OAuth con Google.

    Query params opcionales:
        product_id  — producto que solicita el acceso
        redirect    — URL de retorno tras autenticación
    """
    session["oauth_product_id"] = request.args.get("product_id", "")
    session["oauth_redirect"]   = request.args.get("redirect",    "/")

    callback_url = url_for("oauth.google_callback", _external=True)
    return oauth.google.authorize_redirect(callback_url)


@oauth_bp.route("/google/callback")
def google_callback():
    """Procesa la respuesta de Google y crea sesión Aureon."""
    try:
        token    = oauth.google.authorize_access_token()
        userinfo = token.get("userinfo") or oauth.google.userinfo(token=token)
    except Exception as e:
        log.error("Google OAuth error: %s", e)
        return redirect(f"{APP_URL}/auth/login?error=google_failed")

    email      = userinfo.get("email", "").lower()
    name       = userinfo.get("name",  "Unknown")
    provider_id= userinfo.get("sub",   "")
    avatar_url = userinfo.get("picture")

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
    """
    Inicia el flujo OAuth con GitHub.

    Query params opcionales:
        product_id  — producto que solicita el acceso
        redirect    — URL de retorno tras autenticación
    """
    session["oauth_product_id"] = request.args.get("product_id", "")
    session["oauth_redirect"]   = request.args.get("redirect",    "/")

    callback_url = url_for("oauth.github_callback", _external=True)
    return oauth.github.authorize_redirect(callback_url)


@oauth_bp.route("/github/callback")
def github_callback():
    """Procesa la respuesta de GitHub y crea sesión Aureon."""
    try:
        oauth.github.authorize_access_token()
        resp = oauth.github.get("user")
        resp.raise_for_status()
        profile = resp.json()
    except Exception as e:
        log.error("GitHub OAuth error: %s", e)
        return redirect(f"{APP_URL}/auth/login?error=github_failed")

    provider_id = str(profile.get("id", ""))
    name        = profile.get("name") or profile.get("login", "Unknown")
    avatar_url  = profile.get("avatar_url")

    # GitHub puede no devolver email público — buscarlo en /user/emails
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
    """
    Obtiene el email primario verificado de GitHub cuando
    el perfil no lo expone públicamente.
    """
    try:
        resp = oauth.github.get("user/emails")
        resp.raise_for_status()
        emails = resp.json()
        for entry in emails:
            if entry.get("primary") and entry.get("verified"):
                return entry.get("email")
    except Exception as e:
        log.warning("No se pudo obtener email de GitHub: %s", e)
    return None


# ══════════════════════════════════════════════════════════
# LISTAR IDENTIDADES VINCULADAS
# ══════════════════════════════════════════════════════════

@oauth_bp.route("/identities", methods=["GET"])
def list_identities():
    """
    Lista los proveedores vinculados a la cuenta del usuario.
    Requiere Authorization header con Bearer token.
    """
    from shared.auth_middleware import require_auth
    from flask import g

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Token requerido"}), 401

    from products.auth.utils import decode_token, hash_token as ht
    from products.auth.models import UserSession
    try:
        payload    = decode_token(auth_header.replace("Bearer ", "", 1).strip())
        user_id    = payload["sub"]
    except Exception:
        return jsonify({"error": "Token inválido"}), 401

    identities = UserIdentity.query.filter_by(user_id=user_id).all()
    return jsonify({
        "identities": [
            {
                "provider":    i.provider,
                "created_at":  i.created_at.isoformat(),
            }
            for i in identities
        ]
    }), 200


# ══════════════════════════════════════════════════════════
# DESVINCULAR PROVEEDOR
# ══════════════════════════════════════════════════════════

@oauth_bp.route("/identities/<provider>", methods=["DELETE"])
def unlink_provider(provider):
    """
    Desvincula un proveedor OAuth de la cuenta.
    Protege contra dejar la cuenta sin ningún método de login.
    """
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

    identity = UserIdentity.query.filter_by(
        user_id=user_id, provider=provider
    ).first()

    if not identity:
        return jsonify({"error": "Proveedor no vinculado"}), 404

    # Contar métodos de login restantes
    total_identities = UserIdentity.query.filter_by(user_id=user_id).count()
    total_passkeys   = UserPasskey.query.filter_by(user_id=user_id).count()

    if total_identities <= 1 and total_passkeys == 0:
        return jsonify({
            "error": "No puedes desvincular tu único método de login"
        }), 400

    db.session.delete(identity)
    db.session.commit()

    log.info("Proveedor desvinculado: user=%s provider=%s", user_id, provider)
    return jsonify({"message": f"{provider} desvinculado correctamente"}), 200