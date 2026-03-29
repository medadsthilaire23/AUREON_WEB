"""
api/session.py
==============
Orquestador de sesión.
Cada usuario tiene un session_id único.

Protección:
    Todos los endpoints requieren autenticación Aureon.
    El user_id se almacena en la sesión para aislar datos entre usuarios.
"""
import uuid
from flask import Blueprint, request, jsonify, g
from modules.session_store import store
from shared.auth_middleware import require_auth

session_bp = Blueprint("session", __name__)


@session_bp.route("/api/session/start", methods=["POST"])
@require_auth
def start():
    sid = str(uuid.uuid4())
    store.create(sid, user_id=g.user_id)
    return jsonify({"session_id": sid})


@session_bp.route("/api/session/photos", methods=["POST"])
@require_auth
def receive_photos():
    sid    = request.form.get("session_id")
    photos = request.files.getlist("photos")

    if not sid or not store.exists(sid):
        return jsonify({"error": "Invalid session_id"}), 400

    # Verificar que la sesión pertenece al usuario autenticado
    if not store.belongs_to(sid, g.user_id):
        return jsonify({"error": "Unauthorized"}), 403

    photo_map = {}
    for f in photos:
        pid = f.filename.rsplit(".", 1)[0]
        photo_map[pid] = f.read()
    store.set_photos(sid, photo_map)
    return jsonify({"received": len(photo_map)})


@session_bp.route("/api/session/status/<sid>", methods=["GET"])
@require_auth
def status(sid):
    if not store.exists(sid):
        return jsonify({"error": "Session not found"}), 404

    if not store.belongs_to(sid, g.user_id):
        return jsonify({"error": "Unauthorized"}), 403

    return jsonify(store.get_status(sid))


@session_bp.route("/api/session/clear/<sid>", methods=["DELETE"])
@require_auth
def clear(sid):
    if not store.belongs_to(sid, g.user_id):
        return jsonify({"error": "Unauthorized"}), 403

    store.delete(sid)
    return jsonify({"cleared": sid})