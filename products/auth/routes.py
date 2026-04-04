# products/auth/routes.py
# ══════════════════════════════════════════════════════════════════════════════
# Blueprint principal de autenticación AUREON.
# ══════════════════════════════════════════════════════════════════════════════

import os
import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, g, render_template, session, redirect

from shared.db import db
from products.auth.models import (
    User, UserIdentity, UserDevice,
    UserSession, UserProduct,
)
from products.auth.utils import (
    create_access_token, create_refresh_token,
    decode_token, hash_token,
    hash_password, verify_password,
    validate_password_strength,
    generate_verification_token, generate_reset_token,
    parse_device, is_new_device,
)
from products.auth.email import (
    send_verification_email,
    send_new_device_alert,
    send_reset_password_email,
    send_sessions_revoked_email,
)

log = logging.getLogger("aureon.auth")

_AUTH_DIR = os.path.dirname(os.path.abspath(__file__))

auth_bp = Blueprint(
    "auth",
    __name__,
    url_prefix="/auth",
    template_folder=os.path.join(_AUTH_DIR, "templates"),
    static_folder=os.path.join(_AUTH_DIR, "static"),
    static_url_path="/auth/static",
)

from shared.auth_middleware import require_auth, require_verified  # noqa: E402

_verification_tokens: dict = {}
_reset_tokens: dict        = {}


# ══════════════════════════════════════════════════════════
# HELPERS INTERNOS
# ══════════════════════════════════════════════════════════

def _create_session(user: User, device_info: dict) -> tuple:
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

    sess = UserSession(
        user_id=user.id,
        device_id=device.id,
        ip=device_info["ip"],
    )
    db.session.add(sess)
    db.session.flush()

    access_token  = create_access_token(user.id, sess.id)
    refresh_token = create_refresh_token(user.id, sess.id)

    sess.token_hash   = hash_token(access_token)
    sess.refresh_hash = hash_token(refresh_token)

    db.session.commit()

    return access_token, refresh_token, sess, device


def _tokens_response(access_token: str, refresh_token: str, user: User) -> dict:
    return {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "token_type":    "Bearer",
        "user":          user.to_dict(),
    }


# ══════════════════════════════════════════════════════════
# PÁGINAS HTML
# ══════════════════════════════════════════════════════════

@auth_bp.route("/login", methods=["GET"])
def login_page():
    return render_template("login.html", redirect=request.args.get("redirect", "/"))


@auth_bp.route("/register", methods=["GET"])
def register_page():
    return render_template("register.html", redirect=request.args.get("redirect", "/"))


@auth_bp.route("/consent-page", methods=["GET"])
def consent_page():
    return render_template("consent.html")


@auth_bp.route("/devices-page", methods=["GET"])
def devices_page():
    return render_template("devices.html")


# ══════════════════════════════════════════════════════════
# CONTROL — inspección del subsistema en vivo
# ══════════════════════════════════════════════════════════

def _snap_to_dict(snap) -> dict:
    """
    Convierte un snapshot a dict de forma segura.
    Acepta tanto objetos con atributos como dicts planos.
    """
    if isinstance(snap, dict):
        return snap
    if hasattr(snap, "to_dict"):
        return snap.to_dict()
    return vars(snap)


def _check_admin_token() -> bool:
    """
    Verifica el ADMIN_TOKEN via X-Admin-Token header o ?token= query param.
    Si la variable de entorno no está configurada, bloquea siempre.
    """
    admin_token = os.environ.get("ADMIN_TOKEN", "")
    if not admin_token:
        return False
    incoming = (
        request.headers.get("X-Admin-Token")
        or request.args.get("token")
        or ""
    )
    return incoming == admin_token


@auth_bp.get("/control/status")
def control_status():
    """
    Estado en vivo del subsistema de control (breakers + gates).
    Protegido con ADMIN_TOKEN via X-Admin-Token header o ?token= query param.
    """
    if not _check_admin_token():
        return jsonify({"error": "No autorizado"}), 403

    from shared.control.registries.base import BreakerRegistry, GateRegistry
    from products.auth.context import auth_context

    # ── Breakers ──────────────────────────────────────────
    breakers = []
    for snap in BreakerRegistry.all_snapshots():
        s = _snap_to_dict(snap)
        breakers.append({
            "name":        s.get("name"),
            "state":       s.get("state").value if hasattr(s.get("state"), "value") else s.get("state"),
            "failures":    s.get("failure_count", s.get("failures")),
            "successes":   s.get("success_count", s.get("successes")),
            "retry_after": round(s["retry_after"], 1) if s.get("retry_after") else None,
            "opened_at":   s.get("opened_at"),
        })

    # ── Gates ─────────────────────────────────────────────
    gates = []
    for snap in GateRegistry.all_snapshots():
        s = _snap_to_dict(snap)
        gates.append({
            "name":    s.get("name"),
            "enabled": s.get("enabled"),
        })

    # ── Conductor — captura el error real para diagnóstico ────────────────
    conductor_status = None
    if auth_context.conductor:
        try:
            conductor_status = auth_context.conductor.status()
        except Exception as e:
            # Loguea el traceback completo en el servidor
            log.exception("[control/status] conductor.status() falló")
            # Devuelve el error real al cliente admin para diagnóstico
            conductor_status = {
                "error": str(e),
                "type":  type(e).__name__,
            }

    # ── Sesiones activas ──────────────────────────────────
    try:
        active_sessions = UserSession.query.filter_by(revoked_at=None).count()
        active_users    = db.session.query(UserSession.user_id)\
                            .filter_by(revoked_at=None)\
                            .distinct().count()
    except Exception as e:
        log.exception("[control/status] error consultando sesiones")
        active_sessions = None
        active_users    = None

    return jsonify({
        "breakers":        breakers,
        "gates":           gates,
        "conductor":       conductor_status,
        "context":         auth_context.snapshot(),
        "active_sessions": active_sessions,
        "active_users":    active_users,
    }), 200


# ══════════════════════════════════════════════════════════
# REGISTER
# ══════════════════════════════════════════════════════════

@auth_bp.route("/register", methods=["POST"])
def register():
    body = request.get_json(silent=True) or {}

    name     = (body.get("name")     or "").strip()
    email    = (body.get("email")    or "").strip().lower()
    password =  body.get("password") or ""

    if not name or not email or not password:
        return jsonify({"error": "name, email y password son requeridos"}), 400

    if "@" not in email:
        return jsonify({"error": "Email inválido"}), 400

    errors = validate_password_strength(password)
    if errors:
        return jsonify({"error": "Contraseña débil", "details": errors}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Este email ya está registrado"}), 409

    user = User(name=name, email=email)
    db.session.add(user)
    db.session.flush()

    identity = UserIdentity(
        user_id=user.id,
        provider="aureon",
        provider_id=email,
        password_hash=hash_password(password),
    )
    db.session.add(identity)

    product = UserProduct(user_id=user.id, product_id="lifebound")
    db.session.add(product)

    device_info = parse_device(request)
    access_token, refresh_token, sess, device = _create_session(user, device_info)

    token = generate_verification_token()
    _verification_tokens[token] = user.id
    send_verification_email(email, name, token)

    log.info("Usuario registrado: %s", email)
    return jsonify(_tokens_response(access_token, refresh_token, user)), 201


# ══════════════════════════════════════════════════════════
# LOGIN
# ══════════════════════════════════════════════════════════

@auth_bp.route("/login", methods=["POST"])
def login():
    body = request.get_json(silent=True) or {}

    email    = (body.get("email")    or "").strip().lower()
    password =  body.get("password") or ""

    if not email or not password:
        return jsonify({"error": "email y password son requeridos"}), 400

    user = User.query.filter_by(email=email, is_active=True).first()
    if not user:
        return jsonify({"error": "Credenciales inválidas"}), 401

    identity = UserIdentity.query.filter_by(
        user_id=user.id, provider="aureon"
    ).first()
    if not identity or not verify_password(password, identity.password_hash):
        return jsonify({"error": "Credenciales inválidas"}), 401

    device_info = parse_device(request)
    new_device  = is_new_device(user, device_info)
    access_token, refresh_token, sess, device = _create_session(user, device_info)

    if new_device:
        send_new_device_alert(
            user.email, user.name,
            device_info["device_name"],
            device_info["ip"],
        )

    log.info("Login exitoso: %s", email)
    return jsonify(_tokens_response(access_token, refresh_token, user)), 200


# ══════════════════════════════════════════════════════════
# LOGOUT
# ══════════════════════════════════════════════════════════

@auth_bp.route("/logout", methods=["POST"])
@require_auth
def logout():
    g.session.revoke()
    db.session.commit()
    log.info("Logout: user=%s session=%s", g.user_id, g.session_id)
    return jsonify({"message": "Sesión cerrada"}), 200


# ══════════════════════════════════════════════════════════
# REFRESH TOKEN
# ══════════════════════════════════════════════════════════

@auth_bp.route("/refresh", methods=["POST"])
def refresh():
    body          = request.get_json(silent=True) or {}
    refresh_token = body.get("refresh_token", "")

    if not refresh_token:
        return jsonify({"error": "refresh_token requerido"}), 400

    try:
        payload = decode_token(refresh_token)
    except Exception:
        return jsonify({"error": "Refresh token inválido o expirado"}), 401

    if payload.get("type") != "refresh":
        return jsonify({"error": "Tipo de token inválido"}), 401

    refresh_hash = hash_token(refresh_token)
    sess = UserSession.query.filter_by(
        refresh_hash=refresh_hash,
        revoked_at=None,
    ).first()

    if not sess:
        return jsonify({"error": "Sesión inválida o revocada"}), 401

    user = User.query.get(sess.user_id)
    if not user or not user.is_active:
        return jsonify({"error": "Usuario inactivo"}), 401

    new_access          = create_access_token(user.id, sess.id)
    sess.token_hash     = hash_token(new_access)
    sess.last_active_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({"access_token": new_access, "token_type": "Bearer"}), 200


# ══════════════════════════════════════════════════════════
# VERIFICACIÓN DE EMAIL
# ══════════════════════════════════════════════════════════

@auth_bp.route("/verify-email", methods=["GET"])
def verify_email():
    token   = request.args.get("token", "")
    user_id = _verification_tokens.pop(token, None)

    if not user_id:
        return jsonify({"error": "Token inválido o expirado"}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "Usuario no encontrado"}), 404

    user.is_verified = True
    db.session.commit()

    log.info("Email verificado: %s", user.email)
    return jsonify({"message": "Email verificado correctamente"}), 200


@auth_bp.route("/resend-verification", methods=["POST"])
@require_auth
def resend_verification():
    user = User.query.get(g.user_id)
    if user.is_verified:
        return jsonify({"message": "El email ya está verificado"}), 200

    token = generate_verification_token()
    _verification_tokens[token] = user.id
    send_verification_email(user.email, user.name, token)
    return jsonify({"message": "Email de verificación reenviado"}), 200


# ══════════════════════════════════════════════════════════
# RESET DE CONTRASEÑA
# ══════════════════════════════════════════════════════════

@auth_bp.route("/forgot-password", methods=["POST"])
def forgot_password():
    body  = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()

    user = User.query.filter_by(email=email).first()
    if user:
        token = generate_reset_token()
        _reset_tokens[token] = user.id
        send_reset_password_email(user.email, user.name, token)

    return jsonify({"message": "Si el email existe, recibirás instrucciones"}), 200


@auth_bp.route("/reset-password", methods=["POST"])
def reset_password():
    body     = request.get_json(silent=True) or {}
    token    = body.get("token",    "")
    password = body.get("password", "")

    user_id = _reset_tokens.pop(token, None)
    if not user_id:
        return jsonify({"error": "Token inválido o expirado"}), 400

    errors = validate_password_strength(password)
    if errors:
        return jsonify({"error": "Contraseña débil", "details": errors}), 400

    identity = UserIdentity.query.filter_by(
        user_id=user_id, provider="aureon"
    ).first()
    if not identity:
        return jsonify({"error": "Cuenta no encontrada"}), 404

    identity.password_hash = hash_password(password)

    UserSession.query.filter_by(
        user_id=user_id, revoked_at=None
    ).update({"revoked_at": datetime.now(timezone.utc)})

    db.session.commit()
    log.info("Contraseña reseteada: user=%s", user_id)
    return jsonify({"message": "Contraseña actualizada. Inicia sesión de nuevo."}), 200


# ══════════════════════════════════════════════════════════
# PERFIL
# ══════════════════════════════════════════════════════════

@auth_bp.route("/me", methods=["GET"])
@require_auth
def me():
    user = User.query.get(g.user_id)
    if not user:
        return jsonify({"error": "Usuario no encontrado"}), 404

    data = user.to_dict()
    data["products"] = [p.to_dict() for p in user.products]
    data["passkeys"]  = [pk.to_dict() for pk in user.passkeys]
    return jsonify(data), 200


# ══════════════════════════════════════════════════════════
# SESIONES
# ══════════════════════════════════════════════════════════

@auth_bp.route("/sessions", methods=["GET"])
@require_auth
def list_sessions():
    sessions = UserSession.query.filter_by(
        user_id=g.user_id, revoked_at=None
    ).order_by(UserSession.last_active_at.desc()).all()

    return jsonify({
        "sessions":        [s.to_dict() for s in sessions],
        "current_session": g.session_id,
    }), 200


@auth_bp.route("/sessions/<session_id>", methods=["DELETE"])
@require_auth
def revoke_session(session_id):
    sess = UserSession.query.filter_by(
        id=session_id, user_id=g.user_id, revoked_at=None
    ).first()

    if not sess:
        return jsonify({"error": "Sesión no encontrada"}), 404

    sess.revoke()
    db.session.commit()
    return jsonify({"message": "Sesión cerrada"}), 200


@auth_bp.route("/sessions", methods=["DELETE"])
@require_auth
def revoke_all_sessions():
    user = User.query.get(g.user_id)

    UserSession.query.filter_by(
        user_id=g.user_id, revoked_at=None
    ).update({"revoked_at": datetime.now(timezone.utc)})

    db.session.commit()
    send_sessions_revoked_email(user.email, user.name)
    log.info("Todas las sesiones revocadas: user=%s", g.user_id)
    return jsonify({"message": "Todas las sesiones han sido cerradas"}), 200


# ══════════════════════════════════════════════════════════
# DISPOSITIVOS
# ══════════════════════════════════════════════════════════

@auth_bp.route("/devices", methods=["GET"])
@require_auth
def list_devices():
    devices = UserDevice.query.filter_by(
        user_id=g.user_id
    ).order_by(UserDevice.last_seen_at.desc()).all()

    return jsonify({"devices": [d.to_dict() for d in devices]}), 200


@auth_bp.route("/devices/<device_id>/trust", methods=["PATCH"])
@require_auth
def trust_device(device_id):
    device = UserDevice.query.filter_by(
        id=device_id, user_id=g.user_id
    ).first()

    if not device:
        return jsonify({"error": "Dispositivo no encontrado"}), 404

    device.is_trusted = True
    db.session.commit()
    return jsonify({"message": "Dispositivo marcado como confiable"}), 200


@auth_bp.route("/devices/<device_id>", methods=["DELETE"])
@require_auth
def delete_device(device_id):
    device = UserDevice.query.filter_by(
        id=device_id, user_id=g.user_id
    ).first()

    if not device:
        return jsonify({"error": "Dispositivo no encontrado"}), 404

    for sess in device.sessions:
        if sess.is_active:
            sess.revoke()

    db.session.delete(device)
    db.session.commit()
    return jsonify({"message": "Dispositivo eliminado y sesiones cerradas"}), 200


# ══════════════════════════════════════════════════════════
# SSO CONSENT
# ══════════════════════════════════════════════════════════

@auth_bp.route("/consent", methods=["GET"])
def consent():
    product_id  = request.args.get("product_id", "")
    redirect_to = request.args.get("redirect", "/")

    user = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            token   = auth_header.replace("Bearer ", "", 1).strip()
            payload = decode_token(token)
            if payload.get("type") == "access":
                sess = UserSession.query.filter_by(
                    token_hash=hash_token(token), revoked_at=None
                ).first()
                if sess:
                    user = User.query.get(payload["sub"])
        except Exception:
            pass

    return jsonify({
        "product_id":    product_id,
        "redirect":      redirect_to,
        "authenticated": user is not None,
        "user":          user.to_dict() if user else None,
    }), 200


@auth_bp.route("/grant-product", methods=["POST"])
@require_auth
def grant_product():
    body       = request.get_json(silent=True) or {}
    product_id = body.get("product_id", "").strip()

    if not product_id:
        return jsonify({"error": "product_id requerido"}), 400

    existing = UserProduct.query.filter_by(
        user_id=g.user_id, product_id=product_id
    ).first()

    if not existing:
        up = UserProduct(user_id=g.user_id, product_id=product_id)
        db.session.add(up)
        db.session.commit()

    return jsonify({"message": f"Acceso concedido a {product_id}"}), 200


# ══════════════════════════════════════════════════════════
# OAUTH COMPLETE
# ══════════════════════════════════════════════════════════

@auth_bp.route("/oauth-complete", methods=["GET"])
def oauth_complete():
    access_token   = session.pop("oauth_access_token",   "")
    refresh_token  = session.pop("oauth_refresh_token",  "")
    final_redirect = session.pop("oauth_final_redirect", "/")

    if not access_token:
        return redirect("/auth/login")

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Conectando...</title></head>
<body>
<script>
  localStorage.setItem('aureon_token',   '{access_token}');
  localStorage.setItem('aureon_refresh', '{refresh_token}');
  var dest = '{final_redirect}';
  if (dest.indexOf('access_token') !== -1) dest = '/';
  window.location.replace(dest);
</script>
<p style="font-family:sans-serif;text-align:center;padding:40px;color:#94a3b8">
  Conectando con Aureon...
</p>
</body></html>"""
    return html, 200, {"Content-Type": "text/html"}