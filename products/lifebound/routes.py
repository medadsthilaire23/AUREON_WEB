"""
products/lifebound/routes.py
============================
Blueprint principal de Lifebound.

Responsabilidad única de este archivo
--------------------------------------
Registrar los sub-blueprints de cada dominio y exponer las rutas
triviales que no justifican un módulo propio:
  - Servir el frontend (index.html)
  - Listar plantillas disponibles
  - Generar preview de una página individual
  - Exponer estadísticas del catálogo (admin/debug)
  - Regenerar los archivos de patrones pregenerados (admin)

Cada endpoint de negocio vive en su propio módulo bajo api/:
  api/session.py   → /api/session/*
  api/pattern.py   → /api/pattern
  api/slots.py     → /api/slots
  api/transform.py → /api/transform
  api/generate.py  → /api/generate
"""

import logging
import os

from flask import Blueprint, jsonify, request, send_file
from io import BytesIO

from modules.template_manager import TemplateManager
from modules.pattern_service import PatternService
from services.pattern_generator import PatternGenerator

# Sub-blueprints de cada endpoint de negocio
from api.session   import session_bp
from api.pattern   import pattern_bp
from api.slots     import slots_bp
from api.transform import transform_bp
from api.generate  import generate_bp

log = logging.getLogger("lifebound")

_LIFEBOUND_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Blueprint principal ────────────────────────────────────────────────────
lifebound_bp = Blueprint(
    "lifebound",
    __name__,
    url_prefix="/lifebound",
    static_folder=os.path.join(_LIFEBOUND_DIR, "static"),
    static_url_path="/static",
    template_folder=os.path.join(_LIFEBOUND_DIR, "templates"),
)

# ── Registrar sub-blueprints ───────────────────────────────────────────────
# Cada uno trae sus propias rutas bajo /lifebound/api/*
lifebound_bp.register_blueprint(session_bp)
lifebound_bp.register_blueprint(pattern_bp)
lifebound_bp.register_blueprint(slots_bp)
lifebound_bp.register_blueprint(transform_bp)
lifebound_bp.register_blueprint(generate_bp)

# ── Servicios compartidos (solo los que usan rutas de este archivo) ────────
_template_manager = TemplateManager()
_pattern_service  = PatternService()

log.info("Lifebound: %d templates loaded", len(_template_manager.get_template_list()))


# ══════════════════════════════════════════════════════════════════════════
# FRONTEND
# ══════════════════════════════════════════════════════════════════════════

@lifebound_bp.route("/", strict_slashes=False)
def index():
    """Sirve el frontend HTML de Lifebound."""
    html_path = os.path.join(_LIFEBOUND_DIR, "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html"}


# ══════════════════════════════════════════════════════════════════════════
# API — TEMPLATES
# ══════════════════════════════════════════════════════════════════════════

@lifebound_bp.route("/api/templates", methods=["GET"])
def list_templates():
    """
    Devuelve las plantillas disponibles separadas en dos grupos:
      - evidence : plantillas de páginas fotográficas (id empieza con 'evidence_')
      - documents: plantillas de páginas intro (cover, letter, id)

    Respuesta JSON
    --------------
    { "evidence": [...], "documents": [...] }

    Códigos HTTP
    ------------
    200 — OK
    500 — Error al cargar las plantillas
    """
    try:
        templates = _template_manager.get_template_list()
        evidence  = [t for t in templates if t["id"].startswith("evidence_")]
        documents = [t for t in templates if not t["id"].startswith("evidence_")]
        return jsonify({"evidence": evidence, "documents": documents})
    except Exception as e:
        log.exception("Error listando templates")
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════
# API — PREVIEW
# ══════════════════════════════════════════════════════════════════════════

@lifebound_bp.route("/api/preview", methods=["POST"])
def preview_page():
    """
    Genera una página PDF de muestra para una plantilla específica.
    Útil para el editor visual del frontend sin necesidad de fotos reales.

    Body JSON esperado
    ------------------
    {
        "template_id": "evidence_comparison_v1",
        "data": { "background_color": "cream", ... }
    }

    Respuesta
    ---------
    200 — application/pdf con la página generada
    400 — template_id ausente
    500 — Error al generar la página
    """
    body = request.get_json()
    if not body:
        return jsonify({"error": "Body JSON requerido"}), 400

    template_id = body.get("template_id")
    if not template_id:
        return jsonify({"error": "Campo 'template_id' requerido"}), 400

    try:
        data      = body.get("data", {})
        template  = _template_manager.get_template_instance(template_id)
        pdf_bytes = template.generate(data)
        return send_file(BytesIO(pdf_bytes), mimetype="application/pdf")
    except Exception as e:
        log.exception("Error generando preview para '%s'", template_id)
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════
# API — CATALOG STATS  (solo admin/debug)
# ══════════════════════════════════════════════════════════════════════════

@lifebound_bp.route("/api/catalog/stats", methods=["GET"])
def catalog_stats():
    """
    Devuelve estadísticas del catálogo de patrones cargado en memoria.
    Útil para verificar en producción que los JSONs se cargaron correctamente.

    No requiere autenticación pero no expone datos sensibles —
    solo metadatos de configuración.

    Respuesta JSON
    --------------
    {
        "templates_loaded": 12,
        "photo_range":      [15, 80],
    }
    """
    try:
        templates = _template_manager.get_template_list()
        return jsonify({
            "templates_loaded": len(templates),
            "photo_range":      [15, 80],
        })
    except Exception as e:
        log.exception("Error obteniendo catalog stats")
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════
# API — REGENERAR PATRONES  (solo admin)
# ══════════════════════════════════════════════════════════════════════════

@lifebound_bp.route("/api/admin/regenerate-patterns", methods=["POST"])
def regenerate_patterns():
    """
    Regenera los tres archivos de patrones pregenerados en data/.

    Llama al mismo generador que se usa offline, pero desde el servidor
    en runtime. Útil cuando se actualiza pattern_config.json en producción
    sin necesidad de hacer un redeploy ni acceder al servidor por SSH.

    Body JSON opcional
    ------------------
    { "patterns_per_count": 10 }
        Número de patrones únicos a generar por photo_count.
        Si se omite, usa el valor definido en pattern_config.json (30).
        Pasar un número menor acelera la operación (útil para staging).

    Respuesta JSON
    --------------
    {
        "generated_at":   "2025-08-01T14:32:00",
        "total_patterns": 1980,
        "ranges": {
            "LOW":    { "file": "patterns_low.json",    "total_patterns": 480 },
            "MEDIUM": { "file": "patterns_medium.json", "total_patterns": 750 },
            "HIGH":   { "file": "patterns_high.json",   "total_patterns": 750 }
        }
    }

    Códigos HTTP
    ------------
    200 — Regeneración exitosa
    400 — patterns_per_count inválido
    500 — Error durante la generación

    Nota de seguridad
    -----------------
    Este endpoint no requiere autenticación en esta versión.
    Si el servidor es público, protegerlo con un header secreto
    o restringirlo por IP antes de exponerlo en producción.
    """
    body               = request.get_json(silent=True) or {}
    patterns_per_count = body.get("patterns_per_count")

    if patterns_per_count is not None:
        if not isinstance(patterns_per_count, int) or patterns_per_count < 1:
            return jsonify({"error": "'patterns_per_count' debe ser un entero >= 1"}), 400

    try:
        log.info("Regenerando patrones (patterns_per_count=%s)...", patterns_per_count)
        result = PatternGenerator().generate_all(patterns_per_count=patterns_per_count)
        log.info("Patrones regenerados: %d en total", result["total_patterns"])

        # Invalidar cache de PatternService para que lea los nuevos JSONs
        _pattern_service._cache.clear()
        log.info("Cache de PatternService invalidado")

        return jsonify(result), 200
    except FileNotFoundError as e:
        log.error("pattern_config.json no encontrado: %s", e)
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        log.exception("Error regenerando patrones")
        return jsonify({"error": str(e)}), 500