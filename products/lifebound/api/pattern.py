"""
api/pattern.py
POST /lifebound/api/pattern
Selecciona un patrón aleatorio del JSON según photo_count.
"""
from flask import Blueprint, request, jsonify
from modules.pattern_service import PatternService

pattern_bp = Blueprint("pattern", __name__)
_svc = PatternService()

@pattern_bp.route("/api/pattern", methods=["POST"])
def get_pattern():
    data = request.get_json()
    photo_count = int(data.get("photo_count", 0))
    if not (15 <= photo_count <= 80):
        return jsonify({"error": "photo_count must be 15-80"}), 400
    try:
        pattern = _svc.select(photo_count)
        return jsonify(pattern)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
