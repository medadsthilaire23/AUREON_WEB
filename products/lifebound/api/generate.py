"""
api/generate.py
POST /lifebound/api/generate
Recibe session_id + payload → ensambla PDF.
"""
import json, time
from io import BytesIO
from flask import Blueprint, request, jsonify, send_file
from modules.session_store import SessionStore
from modules.template_manager import TemplateManager
from infrastructure.pdf.pdf_merger_service import PDFMergerService

generate_bp = Blueprint("generate", __name__)
_store      = SessionStore()
_tm         = TemplateManager()
_merger     = PDFMergerService()

@generate_bp.route("/api/generate", methods=["POST"])
def generate():
    t0      = time.time()
    sid     = request.form.get("session_id")
    payload = json.loads(request.form.get("payload", "{}"))

    if not sid or not _store.exists(sid):
        return jsonify({"error": "Invalid session_id"}), 400

    plan           = payload.get("plan", [])
    applicant_info = payload.get("applicant_info", {})
    q_data         = payload.get("questionnaire_data", {})
    photo_map      = _store.get_photos(sid)
    name           = applicant_info.get("name", "Unknown")

    cover_data = {
        "field_office_name":    applicant_info.get("office", "USCIS Field Office"),
        "field_office_address": applicant_info.get("address", ""),
        "attention":            "Attn: I-751/N-400 Interview",
        "applicant_name":       name,
        "spouse_name":          applicant_info.get("spouse", ""),
        "address":              applicant_info.get("address", ""),
        "n400_receipt":         applicant_info.get("receipt_n400", "IOE0000000000"),
        "i751_receipt":         applicant_info.get("receipt_i751", "IOE0000000000"),
        "interview_date":       applicant_info.get("interview_date", ""),
        "interview_time":       applicant_info.get("interview_time", ""),
        "applicant_number":     applicant_info.get("a_number", ""),
    }

    buffers = []
    for doc_id in ("cover_page", "cover_letter", "identification_page"):
        buffers.append(_tm.get_template_instance(doc_id).generate(cover_data))

    for page in plan:
        tid       = page["template"]
        pn        = page["page"]
        page_data = {k: q_data[f"page_{pn}_{k}"]
                     for k in ("date","location","description","title")
                     if q_data.get(f"page_{pn}_{k}")}
        page_data["background_color"] = page.get("color", "white")
        for slot in page["slots"]:
            pid = slot["photo_id"]
            if pid in photo_map:
                page_data[f"photo_{slot['slot']}"] = BytesIO(photo_map[pid])
        try:
            buffers.append(_tm.get_template_instance(tid).generate(page_data))
        except Exception:
            pass

    final = _merger.merge_pages(buffers)
    _store.delete(sid)
    return send_file(BytesIO(final), mimetype="application/pdf",
                     as_attachment=True,
                     download_name=f"USCIS_Album_{name.replace(' ','_')}.pdf")
