# products/auth/routes.py
# ══════════════════════════════════════════════════════════════════════════════
# Blueprint principal de autenticacion AUREON v3.2
#
# Nuevos endpoints de control:
#   GET /control/dashboard     — sirve el HTML del dashboard
#   GET /control/status        — estado del sistema de control (gates, breakers, registry)
#   GET /control/sessions      — sesiones activas con usuario, IP, dispositivo
#   GET /control/users         — usuarios con sesiones y actividad reciente
#   GET /control/activity      — actividad global reciente
# ══════════════════════════════════════════════════════════════════════════════

import os
import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, g, render_template, session, redirect, send_from_directory

from shared.db import db
from products.auth.models import (
    User, UserIdentity, UserDevice,
    UserSession, UserProduct, UserActivity,
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

_AUTH_DIR    = os.path.dirname(os.path.abspath(__file__))
_STATIC_ADMIN = os.path.abspath(os.path.join(_AUTH_DIR, '..', '..', 'static', 'admin'))

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
_db_gate                   = None


def set_db_gate(gate) -> None:
    global _db_gate
    _db_gate = gate


# ══════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════

def _create_session(user: User, device_info: dict) -> tuple:
    device = None
    if device_info.get("fingerprint"):
        device = UserDevice.query.filter_by(
            user_id=user.id, fingerprint=device_info["fingerprint"]
        ).first()

    if not device:
        device = UserDevice(user_id=user.id, **device_info)
        db.session.add(device)
        db.session.flush()

    device.last_seen_at = datetime.now(timezone.utc)

    sess = UserSession(user_id=user.id, device_id=device.id, ip=device_info["ip"])
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


def _snap_to_dict(snap) -> dict:
    if isinstance(snap, dict):
        return snap
    if hasattr(snap, "to_dict"):
        return snap.to_dict()
    return vars(snap)


def _check_admin_token() -> bool:
    admin_token = os.environ.get("ADMIN_TOKEN", "")
    if not admin_token:
        return False
    incoming = (
        request.headers.get("X-Admin-Token")
        or request.args.get("token")
        or ""
    )
    return incoming == admin_token


# ══════════════════════════════════════════════════════════
# PAGINAS HTML
# ══════════════════════════════════════════════════════════

@auth_bp.route("/login",       methods=["GET"])
def login_page():
    return render_template("login.html", redirect=request.args.get("redirect", "/"))

@auth_bp.route("/register",    methods=["GET"])
def register_page():
    return render_template("register.html", redirect=request.args.get("redirect", "/"))

@auth_bp.route("/consent-page", methods=["GET"])
def consent_page():
    return render_template("consent.html")

@auth_bp.route("/devices-page", methods=["GET"])
def devices_page():
    return render_template("devices.html")


# ══════════════════════════════════════════════════════════
# CONTROL — DASHBOARD
# ══════════════════════════════════════════════════════════

@auth_bp.get("/control/dashboard")
def control_dashboard():
    if not _check_admin_token():
        return jsonify({"error": "No autorizado"}), 403
    return send_from_directory(_STATIC_ADMIN, "control_dashboard.html")


@auth_bp.get("/control/status")
def control_status():
    if not _check_admin_token():
        return jsonify({"error": "No autorizado"}), 403

    from shared.control.registries.base import BreakerRegistry, GateRegistry, EventRegistry
    from products.auth.context import auth_context

    # Breakers
    breakers = []
    for snap in BreakerRegistry.all_snapshots():
        s = _snap_to_dict(snap)
        state = s.get("state")
        breakers.append({
            "name":       s.get("name"),
            "state":      state.value if hasattr(state, "value") else state,
            "gate_name":  s.get("gate_name"),
            "trigger_op": s.get("trigger_op"),
            "forced":     s.get("forced", False),
        })

    # Gates — desde GateRegistry
    gates_map: dict = {}
    for snap in GateRegistry.all_snapshots():
        s    = _snap_to_dict(snap)
        name = s.get("name")
        active = s.get("active_ops") if s.get("active_ops") is not None else s.get("active_calls")
        gates_map[name] = {
            "name":           name,
            "enabled":        s.get("enabled"),
            "pass_count":     s.get("pass_count", 0) or 0,
            "fail_count":     s.get("fail_count", 0) or 0,
            "active_ops":     active,
            "avg_latency_ms": s.get("avg_latency_ms"),
        }

    # Conductor
    conductor_status = None
    if auth_context.conductor:
        try:
            conductor_status = auth_context.conductor.status()
        except Exception as e:
            log.exception("[control/status] conductor.status() fallo")
            conductor_status = {"error": str(e), "type": type(e).__name__}

        # Enriquecer gates con datos del conductor (gates concretos tienen mas campos)
        if conductor_status and isinstance(conductor_status.get("gates"), dict):
            for gate_name, gate_data in conductor_status["gates"].items():
                if not isinstance(gate_data, dict):
                    continue
                active = (
                    gate_data.get("active_ops")
                    if gate_data.get("active_ops") is not None
                    else gate_data.get("active_calls")
                )
                if gate_name not in gates_map:
                    gates_map[gate_name] = {
                        "name":           gate_name,
                        "enabled":        gate_data.get("enabled"),
                        "pass_count":     gate_data.get("pass_count", 0) or 0,
                        "fail_count":     gate_data.get("fail_count", 0) or 0,
                        "active_ops":     active,
                        "avg_latency_ms": gate_data.get("avg_latency_ms"),
                    }
                else:
                    entry = gates_map[gate_name]
                    if entry["active_ops"] is None and active is not None:
                        entry["active_ops"] = active
                    if entry["avg_latency_ms"] is None:
                        entry["avg_latency_ms"] = gate_data.get("avg_latency_ms")
                    if not entry["pass_count"]:
                        entry["pass_count"] = gate_data.get("pass_count", 0) or 0
                    if not entry["fail_count"]:
                        entry["fail_count"] = gate_data.get("fail_count", 0) or 0

    gates = list(gates_map.values())

    # Eventos recientes por gate
    events_by_gate: dict = {}
    try:
        for ev in EventRegistry.recent(limit=200):
            gate_name = ev.get("gate", "unknown")
            if gate_name not in events_by_gate:
                events_by_gate[gate_name] = []
            raw_id = ev.get("event_id", "")
            parts  = raw_id.split("_")
            events_by_gate[gate_name].append({
                "event_id":    raw_id,
                "root_id":     parts[0],
                "path":        parts[1:],
                "op_id":       ev.get("op_id"),
                "state":       ev.get("state"),
                "duration_ms": ev.get("duration_ms"),
                "error":       ev.get("error"),
            })
    except Exception as e:
        log.error("[control/status] events_by_gate error: %s", e)

    # Sesiones activas
    try:
        active_sessions = UserSession.query.filter_by(revoked_at=None).count()
        active_users    = db.session.query(UserSession.user_id)\
                            .filter_by(revoked_at=None).distinct().count()
    except Exception:
        active_sessions = None
        active_users    = None

    return jsonify({
        "breakers":        breakers,
        "gates":           gates,
        "conductor":       conductor_status,
        "context":         auth_context.snapshot(),
        "active_sessions": active_sessions,
        "active_users":    active_users,
        "events_by_gate":  events_by_gate,
    }), 200


@auth_bp.get("/control/sessions")
def control_sessions():
    """Sesiones activas con usuario completo, dispositivo e IP."""
    if not _check_admin_token():
        return jsonify({"error": "No autorizado"}), 403

    try:
        sessions = (
            UserSession.query
            .filter_by(revoked_at=None)
            .order_by(UserSession.last_active_at.desc())
            .limit(200)
            .all()
        )

        result = []
        for sess in sessions:
            user   = sess.user
            device = sess.device
            result.append({
                "session_id":    sess.id,
                "created_at":    sess.created_at.isoformat(),
                "last_active_at": sess.last_active_at.isoformat() if sess.last_active_at else None,
                "ip":            sess.ip,
                "user": {
                    "id":         user.id      if user else None,
                    "name":       user.name    if user else "—",
                    "email":      user.email   if user else "—",
                    "role":       user.role    if user else "—",
                    "is_verified": user.is_verified if user else False,
                    "avatar_url": user.avatar_url if user else None,
                },
                "device": {
                    "id":          device.id          if device else None,
                    "device_name": device.device_name if device else "—",
                    "browser":     device.browser     if device else "—",
                    "os":          device.os          if device else "—",
                    "ip":          device.ip          if device else sess.ip,
                    "country":     device.country     if device else None,
                    "city":        device.city        if device else None,
                    "is_trusted":  device.is_trusted  if device else False,
                    "last_seen_at": device.last_seen_at.isoformat()
                                   if device and device.last_seen_at else None,
                },
            })

        return jsonify({"sessions": result, "total": len(result)}), 200

    except Exception as e:
        log.exception("[control/sessions] error")
        return jsonify({"error": str(e)}), 500


@auth_bp.get("/control/users")
def control_users():
    """Usuarios con sus sesiones activas y actividad reciente."""
    if not _check_admin_token():
        return jsonify({"error": "No autorizado"}), 403

    try:
        users = (
            User.query
            .filter_by(is_active=True)
            .order_by(User.created_at.desc())
            .limit(100)
            .all()
        )

        result = []
        for user in users:
            active_sessions = [s for s in user.sessions if s.is_active]
            last_session    = max(active_sessions, key=lambda s: s.last_active_at, default=None) \
                              if active_sessions else None

            # Actividad reciente (ultimos 10 eventos)
            recent_activity = (
                UserActivity.query
                .filter_by(user_id=user.id)
                .order_by(UserActivity.created_at.desc())
                .limit(10)
                .all()
            )

            result.append({
                "id":              user.id,
                "name":            user.name,
                "email":           user.email,
                "role":            user.role,
                "is_verified":     user.is_verified,
                "avatar_url":      user.avatar_url,
                "created_at":      user.created_at.isoformat(),
                "active_sessions": len(active_sessions),
                "total_devices":   len(user.devices),
                "providers":       list({i.provider for i in user.identities}),
                "products":        [p.product_id for p in user.products],
                "last_seen_at":    last_session.last_active_at.isoformat()
                                   if last_session else None,
                "last_ip":         last_session.ip if last_session else None,
                "last_device":     last_session.device.device_name
                                   if last_session and last_session.device else None,
                "sessions": [
                    {
                        "session_id":    s.id,
                        "ip":            s.ip,
                        "last_active_at": s.last_active_at.isoformat(),
                        "created_at":    s.created_at.isoformat(),
                        "device_name":   s.device.device_name if s.device else "—",
                        "browser":       s.device.browser     if s.device else "—",
                        "os":            s.device.os          if s.device else "—",
                        "country":       s.device.country     if s.device else None,
                        "city":          s.device.city        if s.device else None,
                        "is_trusted":    s.device.is_trusted  if s.device else False,
                    }
                    for s in active_sessions
                ],
                "activity": [a.to_dict() for a in recent_activity],
            })

        return jsonify({"users": result, "total": len(result)}), 200

    except Exception as e:
        log.exception("[control/users] error")
        return jsonify({"error": str(e)}), 500


@auth_bp.get("/control/activity")
def control_activity():
    """Actividad global reciente — todos los usuarios."""
    if not _check_admin_token():
        return jsonify({"error": "No autorizado"}), 403

    try:
        limit = min(int(request.args.get("limit", 100)), 500)
        activities = (
            UserActivity.query
            .order_by(UserActivity.created_at.desc())
            .limit(limit)
            .all()
        )

        result = []
        for act in activities:
            user = act.user
            result.append({
                **act.to_dict(),
                "user": {
                    "id":    user.id    if user else None,
                    "name":  user.name  if user else "—",
                    "email": user.email if user else "—",
                },
            })

        return jsonify({"activity": result, "total": len(result)}), 200

    except Exception as e:
        log.exception("[control/activity] error")
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════
# REGISTER
# ══════════════════════════════════════════════════════════

@auth_bp.route("/register", methods=["POST"])
def register():
    body     = request.get_json(silent=True) or {}
    name     = (body.get("name")     or "").strip()
    email    = (body.get("email")    or "").strip().lower()
    password =  body.get("password") or ""

    if not name or not email or not password:
        return jsonify({"error": "name, email y password son requeridos"}), 400
    if "@" not in email:
        return jsonify({"error": "Email invalido"}), 400

    errors = validate_password_strength(password)
    if errors:
        return jsonify({"error": "Contrasena debil", "details": errors}), 400

    try:
        if _db_gate is not None:
            with _db_gate.scan("OP002_002"):
                if User.query.filter_by(email=email).first():
                    return jsonify({"error": "Este email ya esta registrado"}), 409
                user     = User(name=name, email=email)
                db.session.add(user)
                db.session.flush()
                identity = UserIdentity(user_id=user.id, provider="aureon",
                                        provider_id=email, password_hash=hash_password(password))
                db.session.add(identity)
                db.session.add(UserProduct(user_id=user.id, product_id="lifebound"))
        else:
            if User.query.filter_by(email=email).first():
                return jsonify({"error": "Este email ya esta registrado"}), 409
            user     = User(name=name, email=email)
            db.session.add(user)
            db.session.flush()
            identity = UserIdentity(user_id=user.id, provider="aureon",
                                    provider_id=email, password_hash=hash_password(password))
            db.session.add(identity)
            db.session.add(UserProduct(user_id=user.id, product_id="lifebound"))
    except Exception as e:
        db.session.rollback()
        log.error("Register DB error: %s", e)
        return jsonify({"error": "Error al crear la cuenta"}), 500

    try:
        device_info = parse_device(request)
        if _db_gate is not None:
            with _db_gate.scan("OP002_004"):
                access_token, refresh_token, sess, device = _create_session(user, device_info)
        else:
            access_token, refresh_token, sess, device = _create_session(user, device_info)
    except Exception as e:
        log.error("Register session error: %s", e)
        return jsonify({"error": "Error al crear la sesion"}), 500

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
    body     = request.get_json(silent=True) or {}
    email    = (body.get("email")    or "").strip().lower()
    password =  body.get("password") or ""

    if not email or not password:
        return jsonify({"error": "email y password son requeridos"}), 400

    try:
        if _db_gate is not None:
            with _db_gate.scan("OP001_002"):
                user     = User.query.filter_by(email=email, is_active=True).first()
                identity = UserIdentity.query.filter_by(
                    user_id=user.id, provider="aureon").first() if user else None
        else:
            user     = User.query.filter_by(email=email, is_active=True).first()
            identity = UserIdentity.query.filter_by(
                user_id=user.id, provider="aureon").first() if user else None
    except Exception as e:
        log.error("Login DB error: %s", e)
        return jsonify({"error": "Error al verificar credenciales"}), 500

    if not user or not identity or not verify_password(password, identity.password_hash):
        return jsonify({"error": "Credenciales invalidas"}), 401

    device_info = parse_device(request)
    new_device  = is_new_device(user, device_info)

    try:
        if _db_gate is not None:
            with _db_gate.scan("OP001_003"):
                access_token, refresh_token, sess, device = _create_session(user, device_info)
        else:
            access_token, refresh_token, sess, device = _create_session(user, device_info)
    except Exception as e:
        log.error("Login session error: %s", e)
        return jsonify({"error": "Error al crear la sesion"}), 500

    if new_device:
        send_new_device_alert(user.email, user.name, device_info["device_name"], device_info["ip"])

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
    return jsonify({"message": "Sesion cerrada"}), 200


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
        return jsonify({"error": "Refresh token invalido o expirado"}), 401

    if payload.get("type") != "refresh":
        return jsonify({"error": "Tipo de token invalido"}), 401

    sess = UserSession.query.filter_by(
        refresh_hash=hash_token(refresh_token), revoked_at=None).first()
    if not sess:
        return jsonify({"error": "Sesion invalida o revocada"}), 401

    user = User.query.get(sess.user_id)
    if not user or not user.is_active:
        return jsonify({"error": "Usuario inactivo"}), 401

    new_access          = create_access_token(user.id, sess.id)
    sess.token_hash     = hash_token(new_access)
    sess.last_active_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({"access_token": new_access, "token_type": "Bearer"}), 200


# ══════════════════════════════════════════════════════════
# VERIFICACION DE EMAIL
# ══════════════════════════════════════════════════════════

@auth_bp.route("/verify-email", methods=["GET"])
def verify_email():
    token   = request.args.get("token", "")
    user_id = _verification_tokens.pop(token, None)
    if not user_id:
        return jsonify({"error": "Token invalido o expirado"}), 400
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
        return jsonify({"message": "El email ya esta verificado"}), 200
    token = generate_verification_token()
    _verification_tokens[token] = user.id
    send_verification_email(user.email, user.name, token)
    return jsonify({"message": "Email de verificacion reenviado"}), 200


# ══════════════════════════════════════════════════════════
# RESET DE CONTRASENA
# ══════════════════════════════════════════════════════════

@auth_bp.route("/forgot-password", methods=["POST"])
def forgot_password():
    body  = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    user  = User.query.filter_by(email=email).first()
    if user:
        token = generate_reset_token()
        _reset_tokens[token] = user.id
        send_reset_password_email(user.email, user.name, token)
    return jsonify({"message": "Si el email existe, recibiras instrucciones"}), 200


@auth_bp.route("/reset-password", methods=["POST"])
def reset_password():
    body     = request.get_json(silent=True) or {}
    token    = body.get("token",    "")
    password = body.get("password", "")

    user_id = _reset_tokens.pop(token, None)
    if not user_id:
        return jsonify({"error": "Token invalido o expirado"}), 400

    errors = validate_password_strength(password)
    if errors:
        return jsonify({"error": "Contrasena debil", "details": errors}), 400

    identity = UserIdentity.query.filter_by(user_id=user_id, provider="aureon").first()
    if not identity:
        return jsonify({"error": "Cuenta no encontrada"}), 404

    identity.password_hash = hash_password(password)
    UserSession.query.filter_by(user_id=user_id, revoked_at=None).update(
        {"revoked_at": datetime.now(timezone.utc)})
    db.session.commit()
    log.info("Contrasena reseteada: user=%s", user_id)
    return jsonify({"message": "Contrasena actualizada. Inicia sesion de nuevo."}), 200


# ══════════════════════════════════════════════════════════
# PERFIL
# ══════════════════════════════════════════════════════════

@auth_bp.route("/me", methods=["GET"])
@require_auth
def me():
    user = User.query.get(g.user_id)
    if not user:
        return jsonify({"error": "Usuario no encontrado"}), 404
    data             = user.to_dict()
    data["products"] = [p.to_dict() for p in user.products]
    data["passkeys"] = [pk.to_dict() for pk in user.passkeys]
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
        id=session_id, user_id=g.user_id, revoked_at=None).first()
    if not sess:
        return jsonify({"error": "Sesion no encontrada"}), 404
    sess.revoke()
    db.session.commit()
    return jsonify({"message": "Sesion cerrada"}), 200


@auth_bp.route("/sessions", methods=["DELETE"])
@require_auth
def revoke_all_sessions():
    user = User.query.get(g.user_id)
    UserSession.query.filter_by(user_id=g.user_id, revoked_at=None).update(
        {"revoked_at": datetime.now(timezone.utc)})
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
        user_id=g.user_id).order_by(UserDevice.last_seen_at.desc()).all()
    return jsonify({"devices": [d.to_dict() for d in devices]}), 200


@auth_bp.route("/devices/<device_id>/trust", methods=["PATCH"])
@require_auth
def trust_device(device_id):
    device = UserDevice.query.filter_by(id=device_id, user_id=g.user_id).first()
    if not device:
        return jsonify({"error": "Dispositivo no encontrado"}), 404
    device.is_trusted = True
    db.session.commit()
    return jsonify({"message": "Dispositivo marcado como confiable"}), 200


@auth_bp.route("/devices/<device_id>", methods=["DELETE"])
@require_auth
def delete_device(device_id):
    device = UserDevice.query.filter_by(id=device_id, user_id=g.user_id).first()
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
                    token_hash=hash_token(token), revoked_at=None).first()
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
    existing = UserProduct.query.filter_by(user_id=g.user_id, product_id=product_id).first()
    if not existing:
        db.session.add(UserProduct(user_id=g.user_id, product_id=product_id))
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
<body><script>
  localStorage.setItem('aureon_token',   '{access_token}');
  localStorage.setItem('aureon_refresh', '{refresh_token}');
  var dest = '{final_redirect}';
  if (dest.indexOf('access_token') !== -1) dest = '/';
  window.location.replace(dest);
</script>
<p style="font-family:sans-serif;text-align:center;padding:40px;color:#94a3b8">Conectando con Aureon...</p>
</body></html>"""
    return html, 200, {"Content-Type": "text/html"}