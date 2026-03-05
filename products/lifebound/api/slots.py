"""
api/slots.py
POST /lifebound/api/slots
Recibe patrón + year_grouping + dpr.
Genera IDs, asigna fotos a slots, convierte pt→px.
Enriquece y devuelve el patrón completo.
"""
from flask import Blueprint, request, jsonify

slots_bp = Blueprint("slots", __name__)

# Dimensiones en puntos tipográficos por plantilla
TEMPLATE_SLOTS_PT = {
    "evidence_single_moment_v1":  [{"w": 468, "h": 432}],
    "evidence_single_moment_v2":  [{"w": 468, "h": 360}],
    "evidence_milestone_v1":      [{"w": 468, "h": 396}],
    "evidence_comparison_v1":     [{"w": 234, "h": 396}, {"w": 234, "h": 396}],
    "evidence_comparison_v2":     [{"w": 468, "h": 198}, {"w": 468, "h": 198}],
    "evidence_before_after_v1":   [{"w": 234, "h": 396}, {"w": 234, "h": 396}],
    "evidence_sequence_v1":       [{"w": 156, "h": 360}] * 3,
    "evidence_sequence_v2":       [{"w": 288, "h": 396}, {"w": 180, "h": 192}, {"w": 180, "h": 192}],
    "evidence_event_timeline_v1": [{"w": 156, "h": 288}] * 3,
    "evidence_grid_v1":           [{"w": 234, "h": 198}] * 4,
    "evidence_grid_v2":           [{"w": 117, "h": 360}] * 4,
    "evidence_daily_life_v1":     [{"w": 288, "h": 396}, {"w": 180, "h": 126}, {"w": 180, "h": 126}, {"w": 180, "h": 126}],
}

@slots_bp.route("/api/slots", methods=["POST"])
def get_slots():
    data          = request.get_json()
    dpr           = float(data.get("dpr", 1))
    pattern       = data.get("pattern", {})
    year_grouping = data.get("year_grouping", {})  # {"2020": 5, "2021": 8}
    PT_TO_PX      = (150 * dpr) / 72

    # Cola lineal de IDs
    queue = []
    for year in sorted(year_grouping.keys(), key=lambda y: int(y)):
        for i in range(1, int(year_grouping[year]) + 1):
            queue.append({"photo_id": f"y{year}-f{i}", "year": int(year)})

    plan         = []
    identity_map = {}
    cursor       = 0
    template_seq = pattern.get("template_sequence", [])
    color_seq    = pattern.get("color_scheme", {}).get("page_colors", [])

    for page_idx, tid in enumerate(template_seq):
        slots_pt   = TEMPLATE_SLOTS_PT.get(tid, [{"w": 468, "h": 432}])
        page_slots = []
        for slot_idx, sp in enumerate(slots_pt):
            if cursor >= len(queue):
                break
            photo  = queue[cursor]; cursor += 1
            w_px   = round(sp["w"] * PT_TO_PX / 2) * 2
            h_px   = round(sp["h"] * PT_TO_PX / 2) * 2
            entry  = {"slot": slot_idx+1, "photo_id": photo["photo_id"],
                      "year": photo["year"], "w": w_px, "h": h_px}
            page_slots.append(entry)
            identity_map[photo["photo_id"]] = {
                "w": w_px, "h": h_px, "year": photo["year"],
                "page": page_idx+1, "slot": slot_idx+1
            }
        plan.append({
            "page": page_idx+1, "template": tid,
            "color": color_seq[page_idx] if page_idx < len(color_seq) else "white",
            "slots": page_slots
        })

    # Enriquecer patrón
    enriched = {**pattern, "plan": plan, "identity_map": identity_map,
                "total_photos": len(identity_map)}
    return jsonify(enriched)
