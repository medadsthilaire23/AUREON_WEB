"""
api/generate.py
===============
POST /lifebound/api/generate

Orquesta la generación del PDF final del álbum de evidencia USCIS.

Pipeline completo de una sesión:
    /api/session/start
    /api/session/photos   ← fotos ya almacenadas en SessionStore
    /api/pattern
    /api/slots
    /api/transform
    /api/generate         ← este módulo

Responsabilidades
-----------------
1. Validar session_id y que las fotos ya fueron recibidas.
2. Verificar que la sesión pertenece al usuario autenticado.
3. Mergear shared + own del payload en un dict unificado para las intro pages.
4. Generar las 3 páginas introductorias (cover, letter, id).
5. Generar cada página de evidencia del plan[].
   - Si una página falla → insertar página de error visual en su lugar.
6. Fusionar todo en un único PDF y devolverlo como descarga.
7. Eliminar la sesión del store al finalizar (liberar memoria).

Payload esperado
----------------
{
    "plan":               [...],
    "shared":             {
        "field_office_name":    "...",
        "field_office_address": "...",
        "attention":            "...",
        "applicant_name":       "...",
        "spouse_name":          "...",
        "address":              "...",
        "receipts_N":           { "N-400": "IOE..." },
        "receipts_I":           { "I-751": "IOE..." },
        "interview_date":       "...",
        "interview_time":       "...",
        "applicant_number":     "..."
    },
    "own":                {
        "page_1_date":        "...",
        "page_1_description": "...",
        "include_tax_years":  "...",
        ...
    }
}

Compatibilidad hacia atrás
--------------------------
Si el payload trae "applicant_info" en vez de "shared", se acepta igual.
Si trae "questionnaire_data" en vez de "own", se acepta igual.
"""

import json
import logging
import time
from io import BytesIO

from flask import Blueprint, jsonify, request, send_file, g

from infrastructure.pdf.pdf_merger_service import PDFMergerService
from modules.session_store import store
from modules.template_manager import TemplateManager
from shared.auth_middleware import require_auth

logger = logging.getLogger(__name__)

generate_bp = Blueprint("generate", __name__)

# ── Servicios stateless ───────────────────────────────────────────────────
_tm     = TemplateManager()
_merger = PDFMergerService()

# ── IDs de las páginas introductorias, en orden fijo ─────────────────────
_INTRO_PAGES = ("cover_page", "cover_letter", "identification_page")


# ═════════════════════════════════════════════════════════════════════════
# Helpers privados
# ═════════════════════════════════════════════════════════════════════════

def _resolve_shared(payload: dict) -> dict:
    """
    Extrae los datos compartidos del payload.
    Acepta tanto el formato nuevo ("shared") como el legado ("applicant_info").
    """
    if "shared" in payload:
        return payload["shared"]

    ai = payload.get("applicant_info", {})
    return {
        "field_office_name":    ai.get("office",         "USCIS Field Office"),
        "field_office_address": ai.get("address",        ""),
        "attention":            "Attn: I-751/N-400 Interview",
        "applicant_name":       ai.get("name",           ""),
        "spouse_name":          ai.get("spouse",         ""),
        "address":              ai.get("address",        ""),
        "receipts_N":           {},
        "receipts_I":           {},
        "interview_date":       ai.get("interview_date", ""),
        "interview_time":       ai.get("interview_time", ""),
        "applicant_number":     ai.get("a_number",       ""),
    }


def _resolve_own(payload: dict) -> dict:
    """
    Extrae los datos propios del payload.
    Acepta tanto el formato nuevo ("own") como el legado ("questionnaire_data").
    """
    return payload.get("own") or payload.get("questionnaire_data", {})


def _build_page_data(page: dict, shared: dict, own: dict, photo_map: dict) -> dict:
    """
    Construye el diccionario de datos para una página de evidencia.
    Merge: shared → own → campos de foto del slot.
    """
    pn        = page["page"]
    page_data = {**shared}

    for field in ("date", "location", "description", "title"):
        value = own.get(f"page_{pn}_{field}")
        if value:
            page_data[field] = value

    page_data["background_color"] = page.get("color", "white")

    for slot in page.get("slots", []):
        pid       = slot.get("photo_id", "")
        slot_num  = slot.get("slot", 1)
        raw_bytes = photo_map.get(pid)

        if raw_bytes:
            page_data[f"photo_{slot_num}"] = BytesIO(raw_bytes)
        else:
            logger.warning(
                "Foto '%s' no encontrada en session store (página %s)", pid, pn
            )

    return page_data


def _generate_error_page(page_num: int, template_id: str, reason: str) -> bytes:
    """Genera una página PDF de error visual cuando una página de evidencia falla."""
    error_data = {
        "page_number":  page_num,
        "template_id":  template_id,
        "error_reason": reason,
    }

    try:
        return _tm.get_template_instance("error_page").generate(error_data)
    except Exception:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        buf = BytesIO()
        c   = canvas.Canvas(buf, pagesize=letter)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(72, 700, f"Error en página {page_num}")
        c.setFont("Helvetica", 11)
        c.drawString(72, 675, f"Plantilla: {template_id}")
        c.drawString(72, 655, f"Motivo: {reason}")
        c.drawString(72, 620, "Por favor revise las fotos asignadas a esta página.")
        c.save()
        buf.seek(0)
        return buf.read()


# ═════════════════════════════════════════════════════════════════════════
# Endpoint
# ═════════════════════════════════════════════════════════════════════════

@generate_bp.route("/api/generate", methods=["POST"])
@require_auth
def generate():
    """
    Genera y devuelve el PDF final del álbum de evidencia USCIS.

    Requiere autenticación Aureon via Authorization: Bearer <token>

    Multipart form-data esperado
    ----------------------------
    session_id : str
    payload    : JSON str

    Respuestas HTTP
    ---------------
    200 — PDF generado
    400 — session_id inválido o fotos no recibidas
    403 — sesión no pertenece al usuario autenticado
    500 — Error interno
    """
    t_start = time.time()

    # ── 1. Validar sesión ─────────────────────────────────────────────────
    sid = request.form.get("session_id")
    if not sid or not store.exists(sid):
        return jsonify({"error": "Invalid or expired session_id"}), 400

    # Verificar que la sesión pertenece al usuario autenticado
    if not store.belongs_to(sid, g.user_id):
        return jsonify({"error": "Unauthorized"}), 403

    session_status = store.get_status(sid)
    if session_status.get("status") != "photos_ready":
        return jsonify({
            "error":          "Photos not ready. Call /api/session/photos first.",
            "current_status": session_status.get("status"),
        }), 400

    # ── 2. Parsear payload ────────────────────────────────────────────────
    try:
        payload = json.loads(request.form.get("payload", "{}"))
    except json.JSONDecodeError as e:
        return jsonify({"error": f"Invalid payload JSON: {e}"}), 400

    plan      = payload.get("plan", [])
    shared    = _resolve_shared(payload)
    own       = _resolve_own(payload)
    photo_map = store.get_photos(sid)

    if not plan:
        return jsonify({"error": "Empty plan. No evidence pages to generate."}), 400

    applicant_name = shared.get("applicant_name") or "Unknown"

    # ── 3. Páginas introductorias ─────────────────────────────────────────
    buffers = []
    try:
        for doc_id in _INTRO_PAGES:
            buffers.append(_tm.get_template_instance(doc_id).generate(shared))
    except Exception as e:
        logger.exception("Error generando páginas introductorias")
        return jsonify({"error": f"Failed to generate intro pages: {e}"}), 500

    # ── 4. Páginas de evidencia ───────────────────────────────────────────
    pages_ok    = 0
    pages_error = 0

    for page in plan:
        template_id = page.get("template", "unknown")
        page_num    = page.get("page", 0)

        try:
            page_data = _build_page_data(page, shared, own, photo_map)
            template  = _tm.get_template_instance(template_id)
            buffers.append(template.generate(page_data))
            pages_ok += 1
        except Exception as e:
            reason = str(e)
            logger.warning(
                "Página %s (%s) falló — insertando error visual. Razón: %s",
                page_num, template_id, reason
            )
            buffers.append(_generate_error_page(page_num, template_id, reason))
            pages_error += 1

    # ── 5. Merge final ────────────────────────────────────────────────────
    try:
        final_pdf = _merger.merge_pages(buffers)
    except Exception as e:
        logger.exception("Error en merge final del PDF")
        return jsonify({"error": f"PDF merge failed: {e}"}), 500

    # ── 6. Limpiar sesión y devolver PDF ──────────────────────────────────
    store.delete(sid)

    elapsed = round(time.time() - t_start, 2)
    logger.info(
        "PDF generado: user=%s solicitante='%s' páginas_ok=%d páginas_error=%d tiempo=%ss",
        g.user_id, applicant_name, pages_ok, pages_error, elapsed
    )

    filename = f"USCIS_Album_{applicant_name.replace(' ', '_')}.pdf"
    return send_file(
        BytesIO(final_pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )