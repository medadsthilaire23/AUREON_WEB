"""
api/slots.py
============
POST /lifebound/api/slots

Recibe el patrón de plantillas + agrupación por año + DPR del dispositivo.
Devuelve el patrón enriquecido con:
  - plan[]        : páginas con slots resueltos (photo_id, año, dimensiones px)
  - identity_map  : { photo_id → { w, h, year, page, slot } }

Las dimensiones de cada slot se leen desde data/template_slots.json,
que es la fuente única derivada de evidence_templates.py.
Si las plantillas cambian, solo hay que actualizar ese JSON.

Pipeline de sesión:
    /api/session/start
    /api/session/photos
    /api/pattern          ← genera template_sequence
    /api/slots            ← este módulo, enriquece con dimensiones px
    /api/transform
    /api/generate
"""

import json
import logging
import os
from pathlib import Path

from flask import Blueprint, jsonify, request

logger   = logging.getLogger(__name__)
slots_bp = Blueprint("slots", __name__)

# ── Cargar dimensiones desde JSON al iniciar el módulo ────────────────────
# Se carga una sola vez en memoria; no hay I/O por request.
_SLOTS_JSON_PATH = Path(__file__).parent.parent / "data" / "template_slots.json"

def _load_slot_dimensions() -> dict:
    """
    Carga y valida el archivo template_slots.json.

    Retorna un dict { template_id → [ {slot, w, h} ] }.
    Lanza RuntimeError si el archivo no existe o está malformado,
    para que el error sea evidente al arrancar el servidor y no
    silencioso en el primer request.
    """
    if not _SLOTS_JSON_PATH.exists():
        raise RuntimeError(
            f"template_slots.json no encontrado en {_SLOTS_JSON_PATH}. "
            "Ejecuta el script de generación de dimensiones."
        )
    with open(_SLOTS_JSON_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # Filtrar claves de metadata (empiezan con "_")
    return {k: v for k, v in raw.items() if not k.startswith("_")}


# Dimensiones en puntos por plantilla: { template_id: [{slot, w, h}, ...] }
_SLOT_DIMS_PT: dict = _load_slot_dimensions()

# Fallback si una plantilla no está en el JSON
_DEFAULT_SLOT = [{"slot": 1, "w": 360, "h": 432}]


# ── Constantes ────────────────────────────────────────────────────────────

# Páginas 1-3 son siempre intro (cover, letter, id).
# Las páginas de evidencia empiezan en la página 4.
_EVIDENCE_PAGE_OFFSET = 3


# ═════════════════════════════════════════════════════════════════════════
# Helpers privados
# ═════════════════════════════════════════════════════════════════════════

def _pt_to_px(points: float, dpr: float) -> int:
    """
    Convierte puntos tipográficos a píxeles de pantalla.

    Usa 150 DPI como resolución base (estándar para previews de PDF),
    luego multiplica por DPR para pantallas de alta densidad.
    El resultado se redondea al entero par más cercano para evitar
    renders con subpíxeles en pantallas de alta densidad.

    Parámetros
    ----------
    points : float  — dimensión en puntos (1 pt = 1/72 inch)
    dpr    : float  — device pixel ratio del cliente (1, 1.5, 2, 3…)

    Retorna
    -------
    int par — dimensión en píxeles de pantalla
    """
    px = points * (150 * dpr) / 72
    return round(px / 2) * 2   # redondear a par


def _build_photo_queue(year_grouping: dict) -> list[dict]:
    """
    Construye la cola lineal ordenada de photo_ids a partir del agrupamiento por año.

    El orden es cronológico: primero el año más antiguo, dentro de cada
    año las fotos se numeran desde f1.

    Parámetros
    ----------
    year_grouping : dict
        { "2020": 5, "2021": 8 }  →  año (str) → cantidad de fotos (int)

    Retorna
    -------
    list de dicts { photo_id: "y2020-f1", year: 2020 }
    """
    queue = []
    for year in sorted(year_grouping.keys(), key=lambda y: int(y)):
        count = int(year_grouping[year])
        for i in range(1, count + 1):
            queue.append({
                "photo_id": f"y{year}-f{i}",
                "year":     int(year),
            })
    return queue


def _validate_request(data: dict) -> str | None:
    """
    Valida los campos requeridos del body del request.

    Retorna un mensaje de error si hay problema, None si todo está bien.
    """
    if not data.get("pattern"):
        return "Campo 'pattern' requerido"
    if not data.get("pattern", {}).get("template_sequence"):
        return "pattern.template_sequence no puede estar vacío"
    if not data.get("year_grouping"):
        return "Campo 'year_grouping' requerido y no puede estar vacío"
    return None


# ═════════════════════════════════════════════════════════════════════════
# Endpoint
# ═════════════════════════════════════════════════════════════════════════

@slots_bp.route("/api/slots", methods=["POST"])
def get_slots():
    """
    Enriquece el patrón de plantillas con dimensiones reales en píxeles.

    Body JSON esperado
    ------------------
    {
        "pattern": {
            "template_sequence": ["evidence_single_moment_v1", ...],
            "color_scheme": { "page_colors": ["white", "cream", ...] }
        },
        "year_grouping": { "2020": 5, "2021": 8 },
        "dpr": 2
    }

    Respuesta JSON
    --------------
    {
        ...campos del pattern original...,
        "plan": [
            {
                "page":     4,
                "template": "evidence_single_moment_v1",
                "color":    "white",
                "slots": [
                    {
                        "slot":     1,
                        "photo_id": "y2020-f1",
                        "year":     2020,
                        "w":        720,
                        "h":        864
                    }
                ]
            }
        ],
        "identity_map": {
            "y2020-f1": { "w": 720, "h": 864, "year": 2020, "page": 4, "slot": 1 }
        },
        "total_photos": 13
    }

    Códigos HTTP
    ------------
    200 — OK
    400 — Body inválido o campos requeridos ausentes
    500 — Error inesperado
    """
    try:
        data = request.get_json()
        if data is None:
            return jsonify({"error": "Body JSON requerido"}), 400

        # ── Validar campos requeridos ──────────────────────────────────────
        error_msg = _validate_request(data)
        if error_msg:
            return jsonify({"error": error_msg}), 400

        pattern       = data["pattern"]
        year_grouping = data["year_grouping"]
        dpr           = float(data.get("dpr", 1))

        template_seq = pattern["template_sequence"]
        color_seq    = pattern.get("color_scheme", {}).get("page_colors", [])

        # ── Construir cola de fotos ordenada por año ───────────────────────
        photo_queue = _build_photo_queue(year_grouping)
        cursor      = 0   # índice sobre photo_queue

        plan         = []
        identity_map = {}

        for page_idx, template_id in enumerate(template_seq):
            # Páginas de evidencia empiezan en página 4 (1-3 son intro)
            page_number = page_idx + 1 + _EVIDENCE_PAGE_OFFSET

            slots_pt = _SLOT_DIMS_PT.get(template_id)
            if slots_pt is None:
                logger.warning(
                    "Template '%s' no encontrado en template_slots.json — usando fallback",
                    template_id
                )
                slots_pt = _DEFAULT_SLOT

            page_slots = []

            for slot_def in slots_pt:
                if cursor >= len(photo_queue):
                    # Se agotaron las fotos antes de llenar todos los slots
                    logger.warning(
                        "Cola de fotos agotada en página %d, slot %d",
                        page_number, slot_def["slot"]
                    )
                    break

                photo  = photo_queue[cursor]
                cursor += 1

                # Convertir dimensiones pt → px para el frontend
                w_px = _pt_to_px(slot_def["w"], dpr)
                h_px = _pt_to_px(slot_def["h"], dpr)

                slot_entry = {
                    "slot":     slot_def["slot"],
                    "photo_id": photo["photo_id"],
                    "year":     photo["year"],
                    "w":        w_px,
                    "h":        h_px,
                }
                page_slots.append(slot_entry)

                # Registrar en identity_map para que transform y generate
                # puedan localizar cada foto por su ID
                identity_map[photo["photo_id"]] = {
                    "w":    w_px,
                    "h":    h_px,
                    "year": photo["year"],
                    "page": page_number,
                    "slot": slot_def["slot"],
                }

            plan.append({
                "page":     page_number,
                "template": template_id,
                "color":    color_seq[page_idx] if page_idx < len(color_seq) else "white",
                "slots":    page_slots,
            })

        # ── Construir respuesta enriquecida ────────────────────────────────
        enriched = {
            **pattern,               # reenviar todos los campos del patrón original
            "plan":         plan,
            "identity_map": identity_map,
            "total_photos": len(identity_map),
        }

        logger.info(
            "Slots resueltos: %d páginas, %d fotos asignadas",
            len(plan), len(identity_map)
        )

        return jsonify(enriched)

    except Exception as e:
        logger.exception("Error inesperado en /api/slots")
        return jsonify({"error": str(e)}), 500