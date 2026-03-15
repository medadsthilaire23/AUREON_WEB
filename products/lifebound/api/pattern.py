"""
api/pattern.py
==============
POST /lifebound/api/pattern

Recibe la cantidad de fotos y devuelve un patrón de plantillas
seleccionado aleatoriamente desde los JSONs pre-generados.

El patrón define qué plantillas se usarán en cada página del álbum
y cuántas fotos consume cada una (template_sequence, slot_sequence).

Pipeline de sesión:
    /api/session/start
    /api/session/photos
    /api/pattern          ← este módulo
    /api/slots
    /api/transform
    /api/generate
"""

import logging

from flask import Blueprint, jsonify, request

from modules.pattern_service import PatternService

logger     = logging.getLogger(__name__)
pattern_bp = Blueprint("pattern", __name__)

# Instancia única del servicio — carga JSONs en memoria al primer uso
_svc = PatternService()

# Rango válido de fotos definido por los patrones disponibles en data/
_MIN_PHOTOS = 15
_MAX_PHOTOS = 80


@pattern_bp.route("/api/pattern", methods=["POST"])
def get_pattern():
    """
    Selecciona y devuelve un patrón de plantillas para el álbum.

    Body JSON esperado
    ------------------
    {
        "photo_count": 32
    }

    Respuesta JSON
    --------------
    {
        "pattern_id":        "pattern_medium_32p_v1",
        "photo_count":       32,
        "photo_pages":       18,
        "total_pages":       21,
        "range_type":        "MEDIUM",
        "template_sequence": ["evidence_single_moment_v1", ...],
        "slot_sequence":     [1, 2, 3, ...],
        "color_scheme":      { "page_colors": [...] }
    }

    Códigos HTTP
    ------------
    200 — Patrón seleccionado correctamente
    400 — photo_count ausente, no numérico o fuera del rango 15-80
    500 — Error al cargar los JSONs de patrones o sin coincidencias
    """
    data = request.get_json()

    # ── Validar presencia y tipo de photo_count ───────────────────────────
    raw_count = data.get("photo_count") if data else None
    if raw_count is None:
        return jsonify({"error": "Campo 'photo_count' requerido"}), 400

    try:
        photo_count = int(raw_count)
    except (TypeError, ValueError):
        return jsonify({"error": f"'photo_count' debe ser un entero, recibido: {raw_count!r}"}), 400

    # ── Validar rango permitido ───────────────────────────────────────────
    if not (_MIN_PHOTOS <= photo_count <= _MAX_PHOTOS):
        return jsonify({
            "error": f"photo_count debe estar entre {_MIN_PHOTOS} y {_MAX_PHOTOS}, recibido: {photo_count}"
        }), 400

    # ── Seleccionar patrón ────────────────────────────────────────────────
    try:
        pattern = _svc.select(photo_count)
        logger.info("Patrón seleccionado: id=%s photo_count=%d", pattern.get("pattern_id"), photo_count)
        return jsonify(pattern)

    except ValueError as e:
        # Sin patrones disponibles para ese photo_count exacto
        logger.warning("Sin patrones para photo_count=%d: %s", photo_count, e)
        return jsonify({"error": str(e)}), 400

    except Exception as e:
        logger.exception("Error inesperado en /api/pattern")
        return jsonify({"error": str(e)}), 500