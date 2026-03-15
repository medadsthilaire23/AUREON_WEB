"""
api/transform.py
================
POST /lifebound/api/transform

Convierte las transformaciones de pan/zoom que el usuario aplicó
en el visor del frontend (escala + desplazamiento) a coordenadas
concretas de recorte en píxeles sobre la foto original.

Estas coordenadas (pdf_crop) son las que consume /api/generate para
saber exactamente qué región de cada foto colocar en su slot del PDF.

Concepto de transformación
---------------------------
El visor del frontend muestra cada foto dentro de un slot con tamaño
fijo. El usuario puede hacer zoom y desplazar la foto (pan). Esos
valores CSS no son coordenadas absolutas — son relativos al tamaño
del slot y necesitan convertirse al espacio de píxeles de la foto
original para que el generador PDF haga el recorte correcto.

    scale   > 1  →  zoom acercado  →  región visible más pequeña
    offsetX/Y    →  fracción del ancho/alto de la foto (rango [-0.5, 0.5])

Pipeline de sesión:
    /api/session/start
    /api/session/photos
    /api/pattern
    /api/slots
    /api/transform        ← este módulo
    /api/generate
"""

import logging
from flask import Blueprint, jsonify, request

logger       = logging.getLogger(__name__)
transform_bp = Blueprint("transform", __name__)

# Dimensiones de foto por defecto si el photo_id no está en identity_map
_DEFAULT_DIMS = {"w": 960, "h": 720}


# ═════════════════════════════════════════════════════════════════════════
# Helpers privados
# ═════════════════════════════════════════════════════════════════════════

def _compute_crop(
    photo_w: float,
    photo_h: float,
    scale:   float,
    offset_x: float,
    offset_y: float,
) -> dict:
    """
    Calcula el rectángulo de recorte en píxeles de la foto original
    a partir de los parámetros de transformación CSS del visor.

    Lógica
    ------
    1. La región visible es inversamente proporcional al zoom:
       a mayor scale, menor porción de la foto es visible.

    2. El centro del recorte se desplaza según offsetX/Y.
       Los offsets son fracción del tamaño de la foto (no del slot),
       lo que los hace independientes del DPR y del tamaño del slot.

    3. El rectángulo se acota a los límites de la foto para evitar
       coordenadas negativas o que excedan las dimensiones reales.

    Parámetros
    ----------
    photo_w, photo_h : float
        Dimensiones reales de la foto en píxeles (del identity_map).
    scale : float
        Factor de zoom aplicado (>1 acerca, <1 aleja). Mínimo seguro: 0.01.
    offset_x, offset_y : float
        Desplazamiento del centro como fracción del tamaño de la foto.
        Rango típico: [-0.5, 0.5].

    Retorna
    -------
    dict con claves { x, y, w, h } en píxeles enteros, todos >= 0
    y acotados al tamaño real de la foto.
    """
    # Proteger contra scale=0 que causaría división por cero
    safe_scale = max(scale, 0.01)

    # Región visible: a mayor zoom, menor porción de la foto es visible
    visible_w = photo_w / safe_scale
    visible_h = photo_h / safe_scale

    # Centro del recorte en píxeles de la foto
    center_x = photo_w / 2.0 - offset_x * photo_w
    center_y = photo_h / 2.0 - offset_y * photo_h

    # Esquina superior-izquierda del recorte, acotada a [0, photo_dim]
    crop_x = max(0.0, center_x - visible_w / 2.0)
    crop_y = max(0.0, center_y - visible_h / 2.0)

    # Ancho/alto acotados para no salirse de la foto
    crop_w = min(visible_w, photo_w - crop_x)
    crop_h = min(visible_h, photo_h - crop_y)

    return {
        "x": round(crop_x),
        "y": round(crop_y),
        "w": round(crop_w),
        "h": round(crop_h),
    }


# ═════════════════════════════════════════════════════════════════════════
# Endpoint
# ═════════════════════════════════════════════════════════════════════════

@transform_bp.route("/api/transform", methods=["POST"])
def transform_photos():
    """
    Convierte una lista de transformaciones CSS a recortes en píxeles.

    Body JSON esperado
    ------------------
    {
        "session_id":   "ses_...",           // opcional, para trazabilidad
        "identity_map": {                    // foto_id → dimensiones reales
            "y2022-f1": { "w": 3024, "h": 2268 },
            ...
        },
        "transforms": [
            {
                "photo_id":       "y2022-f1",
                "user_transform": {
                    "scale":   1.4,
                    "offsetX": 0.1,
                    "offsetY": -0.05
                }
            },
            ...
        ]
    }

    Respuesta JSON
    --------------
    {
        "transforms": [
            {
                "photo_id": "y2022-f1",
                "pdf_crop": { "x": 120, "y": 45, "w": 2160, "h": 1620 }
            },
            ...
        ]
    }

    Notas
    -----
    - Si un photo_id no está en identity_map se usa _DEFAULT_DIMS (960×720)
      y se registra un warning — no se aborta el request completo.
    - Si transforms llega vacío se devuelve lista vacía con 200.

    Códigos HTTP
    ------------
    200 — OK, lista de recortes calculados (puede estar vacía)
    400 — Body JSON ausente o malformado
    500 — Error inesperado
    """
    data = request.get_json()
    if data is None:
        return jsonify({"error": "Body JSON requerido"}), 400

    identity_map = data.get("identity_map", {})
    transforms   = data.get("transforms", [])
    session_id   = data.get("session_id", "—")

    if not transforms:
        logger.warning("session=%s — /api/transform recibió lista vacía", session_id)
        return jsonify({"transforms": []})

    results = []

    for tr in transforms:
        pid = tr.get("photo_id", "")
        ut  = tr.get("user_transform", {})

        # Extraer parámetros con valores por defecto seguros
        scale    = float(ut.get("scale",   1.0))
        offset_x = float(ut.get("offsetX", 0.0))
        offset_y = float(ut.get("offsetY", 0.0))

        # Obtener dimensiones reales; avisar si el ID no está en el mapa
        dims = identity_map.get(pid)
        if dims is None:
            logger.warning(
                "session=%s — photo_id '%s' no encontrado en identity_map, usando fallback %s",
                session_id, pid, _DEFAULT_DIMS
            )
            dims = _DEFAULT_DIMS

        photo_w = float(dims["w"])
        photo_h = float(dims["h"])

        pdf_crop = _compute_crop(photo_w, photo_h, scale, offset_x, offset_y)

        results.append({
            "photo_id": pid,
            "pdf_crop": pdf_crop,
        })

    logger.info(
        "session=%s — transform completado: %d fotos procesadas",
        session_id, len(results)
    )

    return jsonify({"transforms": results})
