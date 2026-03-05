"""
api/session.py
Orquestador de sesión con hilos paralelos.
Cada usuario tiene un session_id único.
"""
import uuid, threading
from flask import Blueprint, request, jsonify
from modules.session_store import SessionStore

session_bp  = Blueprint("session", __name__)
_store      = SessionStore()

@session_bp.route("/api/session/start", methods=["POST"])
def start():
    sid = str(uuid.uuid4())
    _store.create(sid)
    return jsonify({"session_id": sid})

@session_bp.route("/api/session/photos", methods=["POST"])
def receive_photos():
    sid    = request.form.get("session_id")
    photos = request.files.getlist("photos")
    if not sid or not _store.exists(sid):
        return jsonify({"error": "Invalid session_id"}), 400
    photo_map = {}
    for f in photos:
        pid = f.filename.rsplit(".", 1)[0]
        photo_map[pid] = f.read()
    _store.set_photos(sid, photo_map)
    return jsonify({"received": len(photo_map)})

@session_bp.route("/api/session/status/<sid>", methods=["GET"])
def status(sid):
    if not _store.exists(sid):
        return jsonify({"error": "Session not found"}), 404
    return jsonify(_store.get_status(sid))

@session_bp.route("/api/session/clear/<sid>", methods=["DELETE"])
def clear(sid):
    _store.delete(sid)
    return jsonify({"cleared": sid})
