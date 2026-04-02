"""
products/auth/account.py
========================
Endpoints del panel de cuenta Aureon.

Rutas:
    GET  /auth/account              — página HTML del panel
    GET  /auth/account/data         — datos del usuario (JSON)
    PUT  /auth/account/profile      — actualizar nombre
    GET  /auth/account/activity     — historial de actividad
    GET  /auth/account/stats        — métricas del panel
"""

import logging
from flask import Blueprint, jsonify, render_template, request, g

from shared.db import db
from products.auth.models import User, UserActivity, UserSession, UserProduct, log_activity
from products.auth.middleware import require_auth

log = logging.getLogger("aureon.account")

account_bp = Blueprint(
    "account",
    __name__,
    url_prefix="/auth/account",
)


# ══════════════════════════════════════════════════════════
# PÁGINA HTML
# ══════════════════════════════════════════════════════════

@account_bp.route("")
@require_auth
def account_page():
    """
    Sirve el panel de cuenta.
    El tema visual se inyecta via query param ?theme=lifebound
    Si no se pasa theme, usa el tema base Aureon.
    """
    theme = request.args.get("theme", "aureon")
    return render_template("account.html", theme=theme)


# ══════════════════════════════════════════════════════════
# DATOS DEL USUARIO
# ══════════════════════════════════════════════════════════

@account_bp.route("/data")
@require_auth
def account_data():
    """Retorna todos los datos del panel en una sola llamada."""
    user = g.current_user

    # Sesiones activas
    sessions = UserSession.query.filter_by(
        user_id=user.id
    ).order_by(UserSession.created_at.desc()).limit(10).all()

    # Productos
    products = UserProduct.query.filter_by(user_id=user.id).all()

    # Actividad reciente
    activities = UserActivity.query.filter_by(
        user_id=user.id
    ).order_by(UserActivity.created_at.desc()).limit(20).all()

    # Stats
    active_sessions = sum(1 for s in sessions if s.is_active)

    return jsonify({
        "user":            user.to_dict(),
        "sessions":        [s.to_dict() for s in sessions],
        "products":        [p.to_dict() for p in products],
        "activity":        [a.to_dict() for a in activities],
        "stats": {
            "active_sessions": active_sessions,
            "total_products":  len(products),
            "total_activity":  UserActivity.query.filter_by(user_id=user.id).count(),
        }
    }), 200


# ══════════════════════════════════════════════════════════
# ACTUALIZAR PERFIL
# ══════════════════════════════════════════════════════════

@account_bp.route("/profile", methods=["PUT"])
@require_auth
def update_profile():
    """Actualiza el nombre del usuario."""
    user = g.current_user
    data = request.get_json() or {}

    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "El nombre no puede estar vacío"}), 400
    if len(name) > 255:
        return jsonify({"error": "Nombre demasiado largo"}), 400

    old_name = user.name
    user.name = name
    db.session.commit()

    log_activity(
        user_id=user.id,
        event_type="profile_update",
        ip=request.remote_addr,
        metadata=f"name: {old_name} → {name}",
    )
    db.session.commit()

    log.info("Profile updated: user=%s name=%s", user.id, name)
    return jsonify({"message": "Perfil actualizado", "user": user.to_dict()}), 200


# ══════════════════════════════════════════════════════════
# HISTORIAL DE ACTIVIDAD
# ══════════════════════════════════════════════════════════

@account_bp.route("/activity")
@require_auth
def activity():
    """Retorna historial paginado de actividad."""
    user   = g.current_user
    page   = request.args.get("page", 1, type=int)
    limit  = min(request.args.get("limit", 20, type=int), 100)
    offset = (page - 1) * limit

    activities = UserActivity.query.filter_by(
        user_id=user.id
    ).order_by(
        UserActivity.created_at.desc()
    ).offset(offset).limit(limit).all()

    total = UserActivity.query.filter_by(user_id=user.id).count()

    return jsonify({
        "activity": [a.to_dict() for a in activities],
        "total":    total,
        "page":     page,
        "pages":    (total + limit - 1) // limit,
    }), 200
