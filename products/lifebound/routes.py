"""
products/lifebound/routes.py
Blueprint de Lifebound — todas las rutas bajo /lifebound/*
"""

import os, sys, json, time, uuid, threading, logging
from io import BytesIO
from flask import Blueprint, request, jsonify, send_file

LIFEBOUND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIFEBOUND_DIR)

from modules.template_manager import TemplateManager
from infrastructure.pdf.pdf_merger_service import PDFMergerService

log = logging.getLogger('lifebound')

lifebound_bp = Blueprint(
    'lifebound', __name__,
    url_prefix='/lifebound',
    static_folder=os.path.join(LIFEBOUND_DIR, 'static'),
    static_url_path='/lifebound/static',
    template_folder=os.path.join(LIFEBOUND_DIR, 'templates'),
)

template_manager = TemplateManager()
pdf_merger       = PDFMergerService()
log.info(f"Lifebound: {len(template_manager.get_template_list())} templates loaded")

# ── Session store en memoria (thread-safe) ────────────────────────────────
_sessions      = {}
_sessions_lock = threading.Lock()
SESSION_TTL    = 3600  # 1 hora

def _session_create(sid):
    with _sessions_lock:
        _sessions[sid] = {"created_at": time.time(), "photos": {}}

def _session_exists(sid):
    with _sessions_lock:
        s = _sessions.get(sid)
        if not s: return False
        if time.time() - s["created_at"] > SESSION_TTL:
            del _sessions[sid]; return False
        return True

def _session_set_photos(sid, photo_map):
    with _sessions_lock:
        if sid in _sessions:
            _sessions[sid]["photos"] = photo_map

def _session_get_photos(sid):
    with _sessions_lock:
        return _sessions.get(sid, {}).get("photos", {})

def _session_delete(sid):
    with _sessions_lock:
        _sessions.pop(sid, None)

# ── Dimensiones slots en puntos tipograficos ──────────────────────────────
TEMPLATE_PHOTO_COUNT = {
    "evidence_single_moment_v1":1,"evidence_single_moment_v2":1,
    "evidence_milestone_v1":1,"evidence_comparison_v1":2,
    "evidence_comparison_v2":2,"evidence_before_after_v1":2,
    "evidence_sequence_v1":3,"evidence_sequence_v2":3,
    "evidence_event_timeline_v1":3,"evidence_grid_v1":4,
    "evidence_grid_v2":4,"evidence_daily_life_v1":4,
}

TEMPLATE_SLOTS_PT = {
    "evidence_single_moment_v1":  [{"w":468,"h":432}],
    "evidence_single_moment_v2":  [{"w":468,"h":360}],
    "evidence_milestone_v1":      [{"w":468,"h":396}],
    "evidence_comparison_v1":     [{"w":234,"h":396},{"w":234,"h":396}],
    "evidence_comparison_v2":     [{"w":468,"h":198},{"w":468,"h":198}],
    "evidence_before_after_v1":   [{"w":234,"h":396},{"w":234,"h":396}],
    "evidence_sequence_v1":       [{"w":156,"h":360}]*3,
    "evidence_sequence_v2":       [{"w":288,"h":396},{"w":180,"h":192},{"w":180,"h":192}],
    "evidence_event_timeline_v1": [{"w":156,"h":288}]*3,
    "evidence_grid_v1":           [{"w":234,"h":198}]*4,
    "evidence_grid_v2":           [{"w":117,"h":360}]*4,
    "evidence_daily_life_v1":     [{"w":288,"h":396},{"w":180,"h":126},{"w":180,"h":126},{"w":180,"h":126}],
}

def build_pattern(photo_count, num_years):
    rt       = "LOW" if photo_count <= 30 else ("MEDIUM" if photo_count <= 55 else "HIGH")
    rotation = [
        "evidence_single_moment_v1","evidence_comparison_v1",
        "evidence_sequence_v1","evidence_grid_v1",
        "evidence_before_after_v1","evidence_sequence_v2",
        "evidence_daily_life_v1","evidence_event_timeline_v1",
        "evidence_comparison_v2","evidence_single_moment_v2",
        "evidence_grid_v2","evidence_milestone_v1",
    ]
    seq, rem, idx = [], photo_count, 0
    while rem > 0:
        tid = rotation[idx % len(rotation)]
        n   = TEMPLATE_PHOTO_COUNT[tid]
        if n <= rem: seq.append(tid); rem -= n
        else:        seq.append("evidence_single_moment_v1"); rem -= 1
        idx += 1
    return {
        "pattern_id":        f"{rt.lower()}_{photo_count}p_{num_years}y",
        "range_type":        rt,
        "photo_count":       photo_count,
        "num_years":         num_years,
        "photo_pages":       len(seq),
        "total_pages":       len(seq) + 3,
        "template_sequence": seq,
        "slot_sequence":     [TEMPLATE_PHOTO_COUNT[t] for t in seq],
        "color_scheme":      {"page_colors": ["white"] * len(seq)},
    }

# ══════════════════════════════════════════════════════════
# FRONTEND
# ══════════════════════════════════════════════════════════

@lifebound_bp.route("/", strict_slashes=False)
def index():
    html_path = os.path.join(LIFEBOUND_DIR, "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html"}

# ══════════════════════════════════════════════════════════
# API — SESSION
# ══════════════════════════════════════════════════════════

@lifebound_bp.route("/api/session/start", methods=["POST"])
def session_start():
    sid = str(uuid.uuid4())
    _session_create(sid)
    log.info(f"Session created: {sid[:8]}...")
    return jsonify({"session_id": sid})

@lifebound_bp.route("/api/session/photos", methods=["POST"])
def session_photos():
    sid    = request.form.get("session_id")
    if not sid or not _session_exists(sid):
        return jsonify({"error": "Invalid or expired session_id"}), 400
    photos = request.files.getlist("photos")
    photo_map = {}
    for f in photos:
        pid = os.path.splitext(f.filename)[0]
        photo_map[pid] = f.read()
    _session_set_photos(sid, photo_map)
    log.info(f"Session {sid[:8]}: {len(photo_map)} photos received")
    return jsonify({"received": len(photo_map)})

@lifebound_bp.route("/api/session/status/<sid>", methods=["GET"])
def session_status(sid):
    if not _session_exists(sid):
        return jsonify({"error": "Session not found"}), 404
    with _sessions_lock:
        s = _sessions.get(sid, {})
    return jsonify({"photos": len(s.get("photos", {}))})

# ══════════════════════════════════════════════════════════
# API — TEMPLATES
# ══════════════════════════════════════════════════════════

@lifebound_bp.route("/api/templates", methods=["GET"])
def list_templates():
    try:
        templates = template_manager.get_template_list()
        evidence  = [t for t in templates if t["id"].startswith("evidence_")]
        docs      = [t for t in templates if not t["id"].startswith("evidence_")]
        return jsonify({"evidence": evidence, "documents": docs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════════════════════
# API — PATTERN
# ══════════════════════════════════════════════════════════

@lifebound_bp.route("/api/pattern", methods=["POST"])
def get_pattern():
    try:
        data        = request.get_json()
        photo_count = int(data.get("photo_count", 0))
        num_years   = int(data.get("num_years", 1))
        if not (15 <= photo_count <= 80):
            return jsonify({"error": "Photo count must be between 15 and 80"}), 400
        pattern = build_pattern(photo_count, num_years)
        log.info(f"Pattern: {pattern['pattern_id']}  {pattern['photo_pages']}p")
        return jsonify(pattern)
    except Exception as e:
        log.error(f"get_pattern: {e}")
        return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════════════════════
# API — SLOTS
# ══════════════════════════════════════════════════════════

@lifebound_bp.route("/api/slots", methods=["POST"])
def get_slots():
    """
    Recibe: pattern (objeto completo) + year_grouping {ano: count} + dpr
    Enriquece el patron con plan + identity_map y lo devuelve.
    """
    try:
        data          = request.get_json()
        dpr           = float(data.get("dpr", 1))
        pattern       = data.get("pattern", {})
        year_grouping = data.get("year_grouping", {})
        PT_TO_PX      = (150 * dpr) / 72

        template_sequence = pattern.get("template_sequence", [])
        color_sequence    = pattern.get("color_scheme", {}).get("page_colors", [])

        # Cola lineal de IDs por ano
        queue = []
        for year in sorted(year_grouping.keys(), key=lambda y: int(y)):
            for i in range(1, int(year_grouping[year]) + 1):
                queue.append({"photo_id": f"y{year}-f{i}", "year": int(year)})

        plan, identity_map, cursor = [], {}, 0

        for page_idx, tid in enumerate(template_sequence):
            slots_pt   = TEMPLATE_SLOTS_PT.get(tid, [{"w":468,"h":432}])
            page_slots = []
            for slot_idx, sp in enumerate(slots_pt):
                if cursor >= len(queue): break
                photo  = queue[cursor]; cursor += 1
                w_px   = round(sp["w"] * PT_TO_PX / 2) * 2
                h_px   = round(sp["h"] * PT_TO_PX / 2) * 2
                page_slots.append({
                    "slot":     slot_idx + 1,
                    "photo_id": photo["photo_id"],
                    "year":     photo["year"],
                    "w":        w_px,
                    "h":        h_px,
                })
                identity_map[photo["photo_id"]] = {
                    "w":    w_px, "h":    h_px,
                    "year": photo["year"],
                    "page": page_idx + 1,
                    "slot": slot_idx + 1,
                }
            plan.append({
                "page":     page_idx + 1,
                "template": tid,
                "color":    color_sequence[page_idx] if page_idx < len(color_sequence) else "white",
                "slots":    page_slots,
            })

        # Devolver patron enriquecido
        enriched = {
            **pattern,
            "plan":         plan,
            "identity_map": identity_map,
            "total_photos": len(identity_map),
        }
        log.info(f"Slots: {len(identity_map)} photos  {len(plan)} pages  dpr={dpr}")
        return jsonify(enriched)

    except Exception as e:
        log.error(f"get_slots: {e}")
        return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════════════════════
# API — GENERATE PDF
# ══════════════════════════════════════════════════════════

@lifebound_bp.route("/api/generate", methods=["POST"])
def generate_album():
    t0 = time.time()
    try:
        sid       = request.form.get("session_id")
        payload   = json.loads(request.form.get("payload", "{}"))
        plan      = payload.get("plan", [])
        app_info  = payload.get("applicant_info", {})
        q_data    = payload.get("questionnaire_data", {})
        name      = app_info.get("name", "Unknown")

        if not plan:
            return jsonify({"error": "No plan provided"}), 400

        # Obtener fotos de la sesion
        photo_map = _session_get_photos(sid) if sid and _session_exists(sid) else {}
        log.info(f"Generate: {name}  {len(plan)} pages  {len(photo_map)} photos")

        cover_data = {
            "field_office_name":    app_info.get("office", "USCIS Field Office"),
            "field_office_address": app_info.get("address", ""),
            "attention":            "Attn: I-751/N-400 Interview",
            "applicant_name":       name,
            "spouse_name":          app_info.get("spouse", ""),
            "address":              app_info.get("address", ""),
            "n400_receipt":         app_info.get("receipt_n400", "IOE0000000000"),
            "i751_receipt":         app_info.get("receipt_i751", "IOE0000000000"),
            "interview_date":       app_info.get("interview_date", ""),
            "interview_time":       app_info.get("interview_time", ""),
            "applicant_number":     app_info.get("a_number", ""),
        }

        buffers = []
        for doc_id in ("cover_page", "cover_letter", "identification_page"):
            buffers.append(template_manager.get_template_instance(doc_id).generate(cover_data))

        ok = err = 0
        for page in plan:
            tid      = page["template"]
            pn       = page["page"]
            pdata    = {k: q_data[f"page_{pn}_{k}"]
                        for k in ("date","location","description","title")
                        if q_data.get(f"page_{pn}_{k}")}
            pdata["background_color"] = page.get("color", "white")
            for slot in page["slots"]:
                pid = slot["photo_id"]
                if pid in photo_map:
                    pdata[f"photo_{slot['slot']}"] = BytesIO(photo_map[pid])
            try:
                buffers.append(template_manager.get_template_instance(tid).generate(pdata))
                ok += 1
            except Exception as e:
                err += 1
                log.warning(f"Page {pn} [{tid}] FAILED: {e}")

        if sid: _session_delete(sid)

        final = pdf_merger.merge_pages(buffers)
        ms    = (time.time() - t0) * 1000
        log.info(f"PDF: {len(final)//1024}KB  {ms:.0f}ms  {ok}ok {err}err")

        return send_file(
            BytesIO(final), mimetype="application/pdf",
            as_attachment=True,
            download_name=f"USCIS_Album_{name.replace(' ','_')}.pdf"
        )

    except Exception as e:
        import traceback
        log.error(f"generate_album CRASHED: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════════════════════
# API — PREVIEW
# ══════════════════════════════════════════════════════════

@lifebound_bp.route("/api/preview", methods=["POST"])
def preview_page():
    try:
        body = request.get_json()
        tid  = body.get("template_id")
        data = body.get("data", {})
        pdf  = template_manager.get_template_instance(tid).generate(data)
        return send_file(BytesIO(pdf), mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 500
