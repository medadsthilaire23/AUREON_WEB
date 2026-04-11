# shared/control/operation_gates.py
# ══════════════════════════════════════════════════════════════════════════════
# Loader dinámico de operaciones — AUREON v4.0
#
# Fix v4.0.1:
#   - resolve_op_id() ahora distingue rutas de frontend (modulo="frontend")
#     de rutas de API. Las rutas XX de frontend se loguean como DEBUG,
#     no como WARNING — evita falsos positivos en el dashboard.
#   - _FRONTEND_PREFIXES: rutas que nunca son XX aunque no estén en la tabla.
#     Se asignan a OP030 (frontend_home) para que el tracer las cierre OK.
#   - Las rutas de API (/auth/, /lifebound/api/) siguen generando WARNING XX
#     si no están registradas — eso es comportamiento correcto.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import logging
import os
from typing import Optional

log = logging.getLogger("aureon.control.operation_gates")

_BASE_DIR  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_JSON_PATH = os.path.join(_BASE_DIR, "management", "data", "tabla_operacion.json")

XX_OP_ID    = "XX"
XX_OPERATION = {
    "name":       "discovery",
    "gates":      ["HttpGate"],
    "module":     "discovery",
    "nivel":      0,
    "padre":      None,
    "log_policy": "AUDIT",
    "alerta":     "ROJA_CRITICA",
}

# Rutas que NUNCA son XX — son frontend legítimo sin registro en tabla.
# Se tratan como OP030 (frontend genérico) para que el tracer las cierre OK.
_FRONTEND_FALLBACK_OP = "OP030"
_FRONTEND_PREFIXES = (
    "/static/",
    "/favicon",
    "/health",
    "/lifebound/static/",
    "/auth/static/",
)

# Rutas de API — si no están en la tabla SÍ son XX (alerta real)
_API_PREFIXES = ("/auth/", "/lifebound/api/", "/api/")

OPERATIONS: dict[str, dict] = {}
_URL_MAP:   list[tuple[str, str, str]] = []
_loaded     = False


def _load() -> None:
    global OPERATIONS, _URL_MAP, _loaded

    if not os.path.exists(_JSON_PATH):
        log.warning("[OperationGates] tabla_operacion.json no encontrado en %s — modo emergencia", _JSON_PATH)
        _load_emergency_fallback()
        return

    try:
        with open(_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        url_map = []
        for op_id, op in data.get("operaciones", {}).items():
            OPERATIONS[op_id] = {
                "name":       op.get("nombre", op_id),
                "gates":      op.get("gates", ["HttpGate"]),
                "module":     op.get("modulo", "auth"),
                "nivel":      op.get("nivel", 1),
                "padre":      op.get("padre"),
                "log_policy": op.get("log_policy", "SUMMARY"),
            }
            for ruta in op.get("rutas", []):
                method = ruta.get("method", "").upper()
                path   = ruta.get("path", "")
                if method and path:
                    url_map.append((method, path, op_id))

        # Rutas más específicas primero
        _URL_MAP = sorted(url_map, key=lambda x: len(x[1]), reverse=True)
        _loaded  = True
        log.info(
            "[OperationGates] %d operaciones, %d rutas — %s",
            len(OPERATIONS), len(_URL_MAP), _JSON_PATH,
        )

    except Exception as e:
        log.error("[OperationGates] Error cargando JSON: %s", e)
        _load_emergency_fallback()


def _load_emergency_fallback() -> None:
    global OPERATIONS, _URL_MAP, _loaded
    OPERATIONS = {
        "OP010":     {"name":"system_boot","gates":["BootGate"],"module":"system","nivel":1,"padre":None,"log_policy":"AUDIT"},
        "OP010_001": {"name":"boot_phase1_db","gates":["BootGate"],"module":"system","nivel":2,"padre":"OP010","log_policy":"AUDIT"},
        "OP010_002": {"name":"boot_phase1_blueprints","gates":["BootGate"],"module":"system","nivel":2,"padre":"OP010","log_policy":"AUDIT"},
        "OP010_003": {"name":"boot_phase2_oauth","gates":["BootGate"],"module":"system","nivel":2,"padre":"OP010","log_policy":"AUDIT"},
        "OP010_004": {"name":"boot_phase2_conductor","gates":["BootGate"],"module":"system","nivel":2,"padre":"OP010","log_policy":"AUDIT"},
        "OP010_005": {"name":"boot_phase2_tracer","gates":["BootGate"],"module":"system","nivel":2,"padre":"OP010","log_policy":"AUDIT"},
        "OP030":     {"name":"frontend_home","gates":["HttpGate"],"module":"frontend","nivel":1,"padre":None,"log_policy":"SUMMARY"},
        "OP099_001": {"name":"dashboard_status","gates":["HttpGate"],"module":"dashboard","nivel":2,"padre":"OP099","log_policy":"AUDIT"},
    }
    _URL_MAP = [
        ("GET", "/auth/control/status", "OP099_001"),
        ("GET", "/", "OP030"),
    ]
    _loaded  = True
    log.warning("[OperationGates] Modo emergencia — solo operaciones críticas")


def resolve_op_id(method: str, path: str) -> str:
    """
    Resuelve op_id desde método + path.

    Prioridad:
      1. Match exacto en _URL_MAP (más específico primero)
      2. Rutas de assets/health → _FRONTEND_FALLBACK_OP (sin alerta)
      3. Rutas de API no registradas → XX (alerta ROJA_CRITICA)
      4. Rutas desconocidas que no son API → _FRONTEND_FALLBACK_OP (debug)
    """
    # 1. Buscar en la tabla
    for m, prefix, op_id in _URL_MAP:
        if m == method and path.startswith(prefix):
            return op_id

    # 2. Assets y health — nunca XX
    if any(path.startswith(p) for p in _FRONTEND_PREFIXES):
        return _FRONTEND_FALLBACK_OP

    # 3. Rutas de API no registradas → XX real
    if any(path.startswith(p) for p in _API_PREFIXES):
        log.warning(
            "[OperationGates] XX DISCOVERY (API) — %s %s",
            method, path,
        )
        return XX_OP_ID

    # 4. Resto (páginas frontend no registradas) → fallback silencioso
    log.debug(
        "[OperationGates] frontend sin registro — %s %s → %s",
        method, path, _FRONTEND_FALLBACK_OP,
    )
    return _FRONTEND_FALLBACK_OP


def resolve_module(op_id: str) -> str:
    if op_id == XX_OP_ID:
        return "discovery"
    return OPERATIONS.get(op_id, {}).get("module", "auth")


def resolve_log_policy(op_id: str) -> str:
    if op_id == XX_OP_ID:
        return "AUDIT"
    return OPERATIONS.get(op_id, {}).get("log_policy", "SUMMARY")


def validate_boot() -> dict:
    KNOWN_GATES = {"HttpGate", "DbGate", "ModuleGate", "BootGate"}
    warnings    = []
    for op_id, op in OPERATIONS.items():
        for gate in op.get("gates", []):
            if gate not in KNOWN_GATES:
                warnings.append(f"{op_id}: gate '{gate}' no reconocido")
    result = {"ok": len(warnings) == 0, "total": len(OPERATIONS), "warnings": warnings}
    if warnings:
        for w in warnings:
            log.warning("  [OperationGates] ⚠ %s", w)
    else:
        log.info("[OperationGates] validate_boot OK — %d operaciones válidas", len(OPERATIONS))
    return result


# ── API pública ────────────────────────────────────────────────────────────────

def get_operation(op_id: str) -> Optional[dict]:
    if op_id == XX_OP_ID:
        return XX_OPERATION
    return OPERATIONS.get(op_id)


def get_gates_for(op_id: str) -> list[str]:
    if op_id == XX_OP_ID:
        return XX_OPERATION["gates"]
    return OPERATIONS.get(op_id, {}).get("gates", [])


def needs_gate(op_id: str, gate_name: str) -> bool:
    return gate_name in get_gates_for(op_id)


def exists(op_id: str) -> bool:
    return op_id in OPERATIONS and op_id != XX_OP_ID


def get_operations_by_gate(gate_name: str) -> list[str]:
    return [oid for oid, op in OPERATIONS.items() if gate_name in op.get("gates", [])]


def get_operations_by_module(module: str) -> list[str]:
    return [oid for oid, op in OPERATIONS.items() if op.get("module") == module]


def get_parent(op_id: str) -> Optional[str]:
    if op_id == XX_OP_ID:
        return None
    op = OPERATIONS.get(op_id, {})
    if "padre" in op:
        return op["padre"]
    if "_" not in op_id:
        return None
    return op_id.rsplit("_", 1)[0]


def get_depth(op_id: str) -> int:
    return 0 if op_id == XX_OP_ID else op_id.count("_")


def get_ancestors(op_id: str) -> list[str]:
    ancestors, current = [], op_id
    while True:
        parent = get_parent(current)
        if parent is None:
            break
        ancestors.append(parent)
        current = parent
    return ancestors


def is_descendant_of(op_id: str, ancestor_id: str) -> bool:
    return op_id.startswith(ancestor_id + "_")


_load()