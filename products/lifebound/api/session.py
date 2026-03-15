"""
api/session.py
==============
Orquestador de sesión.
Cada usuario tiene un session_id único.
"""
import uuid
from flask import Blueprint, request, jsonify
from modules.session_store import store

session_bp = Blueprint("session", __name__)


@session_bp.route("/api/session/start", methods=["POST"])
def start():
    sid = str(uuid.uuid4())
    store.create(sid)
    return jsonify({"session_id": sid})


@session_bp.route("/api/session/photos", methods=["POST"])
def receive_photos():
    sid    = request.form.get("session_id")
    photos = request.files.getlist("photos")
    if not sid or not store.exists(sid):
        return jsonify({"error": "Invalid session_id"}), 400
    photo_map = {}
    for f in photos:
        pid = f.filename.rsplit(".", 1)[0]
        photo_map[pid] = f.read()
    store.set_photos(sid, photo_map)
    return jsonify({"received": len(photo_map)})


@session_bp.route("/api/session/status/<sid>", methods=["GET"])
def status(sid):
    if not store.exists(sid):
        return jsonify({"error": "Session not found"}), 404
    return jsonify(store.get_status(sid))


@session_bp.route("/api/session/clear/<sid>", methods=["DELETE"])
def clear(sid):
    store.delete(sid)
    return jsonify({"cleared": sid})