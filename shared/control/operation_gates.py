# shared/control/operation_gates.py
# ══════════════════════════════════════════════════════════════════════════════
# Mapa estático de operaciones — AUREON Sistema de Control v3.0
#
# Define TODAS las operaciones del sistema con sus IDs estáticos,
# dependencias de gates y jerarquía padre/hijo.
#
# Reglas de los IDs:
#     OP001            ← raíz (0 guiones) — operación completa
#     OP001_001        ← proceso de primer nivel (1 guión)
#     OP001_001_001    ← subproceso (2 guiones)
#
# Regla de existencia:
#     Un nodo existe solo si él mismo y su padre están OPEN.
#     padre(OP001_002_001) = OP001_002
#     padre(OP001_002)     = OP001
#     padre(OP001)         = None (es raíz)
#
# Regla de propagación:
#     El fallo se propaga siempre hacia abajo, nunca hacia arriba.
#     OP001_002 CLOSED → sus hijos no existen.
#     OP001 sigue OPEN. OP002, OP003... no se enteran.
#
# Regla de escalabilidad:
#     Cada producto nuevo añade su rango de OPs aquí.
#     El sistema de control no cambia — solo crece este archivo.
#
# Rangos por módulo:
#     OP001 - OP009   → auth
#     OP010           → system (boot)
#     OP020 - OP029   → lifebound (fase siguiente)
#     OP030+          → productos futuros
#
# Regla arquitectónica:
#     Este módulo NO importa nada de products/.
#     Es solo datos — sin lógica, sin imports externos.
# ══════════════════════════════════════════════════════════════════════════════


# ── Helpers de jerarquía ───────────────────────────────────────────────────

def get_parent(op_id: str) -> str | None:
    """
    Devuelve el ID del padre de una operación.
    El padre es el nodo anterior — el ID sin el último _XXX.

    Ejemplos:
        get_parent("OP001_002_001") → "OP001_002"
        get_parent("OP001_002")     → "OP001"
        get_parent("OP001")         → None  (es raíz)
    """
    if "_" not in op_id:
        return None
    return op_id.rsplit("_", 1)[0]


def get_depth(op_id: str) -> int:
    """
    Devuelve la profundidad del nodo en el árbol.
    La raíz tiene profundidad 0.

    Ejemplos:
        get_depth("OP001")         → 0
        get_depth("OP001_001")     → 1
        get_depth("OP001_001_001") → 2
    """
    return op_id.count("_")


def get_ancestors(op_id: str) -> list[str]:
    """
    Devuelve todos los ancestros de un nodo, del más cercano al más lejano.

    Ejemplo:
        get_ancestors("OP001_002_001") → ["OP001_002", "OP001"]
    """
    ancestors = []
    current   = op_id
    while True:
        parent = get_parent(current)
        if parent is None:
            break
        ancestors.append(parent)
        current = parent
    return ancestors


def is_descendant_of(op_id: str, ancestor_id: str) -> bool:
    """
    Retorna True si op_id es descendiente de ancestor_id.

    Ejemplo:
        is_descendant_of("OP001_002_001", "OP001_002") → True
        is_descendant_of("OP001_002_001", "OP001")     → True
        is_descendant_of("OP001_002_001", "OP002")     → False
    """
    return op_id.startswith(ancestor_id + "_")


# ── Mapa de operaciones ────────────────────────────────────────────────────

OPERATIONS: dict[str, dict] = {

    # ══════════════════════════════════════════════════════
    # AUTH — OP001 a OP009
    # ══════════════════════════════════════════════════════

    # ── OP001 — LOGIN (email + password) ──────────────────
    "OP001": {
        "name":   "login",
        "gates":  ["HttpGate", "DbGate"],
        "module": "auth",
    },
    "OP001_001": {
        "name":   "login_http_validate",
        "gates":  ["HttpGate"],
        "module": "auth",
    },
    "OP001_002": {
        "name":   "login_db_user_lookup",
        "gates":  ["DbGate"],
        "module": "auth",
    },
    "OP001_003": {
        "name":   "login_db_session_create",
        "gates":  ["DbGate"],
        "module": "auth",
    },
    "OP001_004": {
        "name":   "login_email_new_device",
        "gates":  ["ModuleGate"],
        "module": "auth",
    },

    # ── OP002 — REGISTER ──────────────────────────────────
    "OP002": {
        "name":   "register",
        "gates":  ["HttpGate", "DbGate"],
        "module": "auth",
    },
    "OP002_001": {
        "name":   "register_http_validate",
        "gates":  ["HttpGate"],
        "module": "auth",
    },
    "OP002_002": {
        "name":   "register_db_user_create",
        "gates":  ["DbGate"],
        "module": "auth",
    },
    "OP002_003": {
        "name":   "register_db_identity_create",
        "gates":  ["DbGate"],
        "module": "auth",
    },
    "OP002_004": {
        "name":   "register_db_session_create",
        "gates":  ["DbGate"],
        "module": "auth",
    },
    "OP002_005": {
        "name":   "register_email_verification",
        "gates":  ["ModuleGate"],
        "module": "auth",
    },

    # ── OP003 — OAUTH GOOGLE ──────────────────────────────
    "OP003": {
        "name":   "oauth_google",
        "gates":  ["HttpGate", "DbGate", "ModuleGate"],
        "module": "auth",
    },
    "OP003_001": {
        "name":   "oauth_google_redirect",
        "gates":  ["HttpGate"],
        "module": "auth",
    },
    "OP003_002": {
        "name":   "oauth_google_token_exchange",
        "gates":  ["ModuleGate"],
        "module": "auth",
    },
    "OP003_002_001": {
        "name":   "oauth_google_token_fetch",
        "gates":  ["ModuleGate"],
        "module": "auth",
    },
    "OP003_002_002": {
        "name":   "oauth_google_userinfo",
        "gates":  ["ModuleGate"],
        "module": "auth",
    },
    "OP003_003": {
        "name":   "oauth_google_db_user",
        "gates":  ["DbGate"],
        "module": "auth",
    },
    "OP003_003_001": {
        "name":   "oauth_google_db_user_lookup",
        "gates":  ["DbGate"],
        "module": "auth",
    },
    "OP003_003_002": {
        "name":   "oauth_google_db_identity_link",
        "gates":  ["DbGate"],
        "module": "auth",
    },
    "OP003_004": {
        "name":   "oauth_google_session_create",
        "gates":  ["DbGate"],
        "module": "auth",
    },

    # ── OP004 — OAUTH GITHUB ──────────────────────────────
    "OP004": {
        "name":   "oauth_github",
        "gates":  ["HttpGate", "DbGate", "ModuleGate"],
        "module": "auth",
    },
    "OP004_001": {
        "name":   "oauth_github_redirect",
        "gates":  ["HttpGate"],
        "module": "auth",
    },
    "OP004_002": {
        "name":   "oauth_github_token_exchange",
        "gates":  ["ModuleGate"],
        "module": "auth",
    },
    "OP004_002_001": {
        "name":   "oauth_github_token_fetch",
        "gates":  ["ModuleGate"],
        "module": "auth",
    },
    "OP004_002_002": {
        "name":   "oauth_github_profile_fetch",
        "gates":  ["ModuleGate"],
        "module": "auth",
    },
    "OP004_002_003": {
        "name":   "oauth_github_email_fetch",
        "gates":  ["ModuleGate"],
        "module": "auth",
    },
    "OP004_003": {
        "name":   "oauth_github_db_user",
        "gates":  ["DbGate"],
        "module": "auth",
    },
    "OP004_004": {
        "name":   "oauth_github_session_create",
        "gates":  ["DbGate"],
        "module": "auth",
    },

    # ── OP005 — PASSKEY REGISTER ──────────────────────────
    "OP005": {
        "name":   "passkey_register",
        "gates":  ["HttpGate", "DbGate", "ModuleGate"],
        "module": "auth",
    },
    "OP005_001": {
        "name":   "passkey_register_begin",
        "gates":  ["HttpGate", "DbGate"],
        "module": "auth",
    },
    "OP005_001_001": {
        "name":   "passkey_register_user_lookup",
        "gates":  ["DbGate"],
        "module": "auth",
    },
    "OP005_001_002": {
        "name":   "passkey_register_options_generate",
        "gates":  ["ModuleGate"],
        "module": "auth",
    },
    "OP005_002": {
        "name":   "passkey_register_complete",
        "gates":  ["HttpGate", "DbGate", "ModuleGate"],
        "module": "auth",
    },
    "OP005_002_001": {
        "name":   "passkey_register_verify",
        "gates":  ["ModuleGate"],
        "module": "auth",
    },
    "OP005_002_002": {
        "name":   "passkey_register_db_save",
        "gates":  ["DbGate"],
        "module": "auth",
    },

    # ── OP006 — PASSKEY LOGIN ─────────────────────────────
    "OP006": {
        "name":   "passkey_login",
        "gates":  ["HttpGate", "DbGate", "ModuleGate"],
        "module": "auth",
    },
    "OP006_001": {
        "name":   "passkey_login_begin",
        "gates":  ["HttpGate"],
        "module": "auth",
    },
    "OP006_002": {
        "name":   "passkey_login_complete",
        "gates":  ["HttpGate", "DbGate", "ModuleGate"],
        "module": "auth",
    },
    "OP006_002_001": {
        "name":   "passkey_login_credential_lookup",
        "gates":  ["DbGate"],
        "module": "auth",
    },
    "OP006_002_002": {
        "name":   "passkey_login_verify",
        "gates":  ["ModuleGate"],
        "module": "auth",
    },
    "OP006_002_003": {
        "name":   "passkey_login_session_create",
        "gates":  ["DbGate"],
        "module": "auth",
    },

    # ── OP007 — EMAIL TRANSACCIONAL ───────────────────────
    "OP007": {
        "name":   "email_send",
        "gates":  ["ModuleGate"],
        "module": "auth",
    },
    "OP007_001": {
        "name":   "email_verification",
        "gates":  ["ModuleGate"],
        "module": "auth",
    },
    "OP007_002": {
        "name":   "email_new_device_alert",
        "gates":  ["ModuleGate"],
        "module": "auth",
    },
    "OP007_003": {
        "name":   "email_reset_password",
        "gates":  ["ModuleGate"],
        "module": "auth",
    },
    "OP007_004": {
        "name":   "email_sessions_revoked",
        "gates":  ["ModuleGate"],
        "module": "auth",
    },

    # ── OP008 — SESSION MANAGEMENT ────────────────────────
    "OP008": {
        "name":   "session_management",
        "gates":  ["HttpGate", "DbGate"],
        "module": "auth",
    },
    "OP008_001": {
        "name":   "session_logout",
        "gates":  ["DbGate"],
        "module": "auth",
    },
    "OP008_002": {
        "name":   "session_refresh",
        "gates":  ["HttpGate", "DbGate"],
        "module": "auth",
    },
    "OP008_003": {
        "name":   "session_revoke_single",
        "gates":  ["DbGate"],
        "module": "auth",
    },
    "OP008_004": {
        "name":   "session_revoke_all",
        "gates":  ["DbGate", "ModuleGate"],
        "module": "auth",
    },

    # ── OP009 — DATABASE ──────────────────────────────────
    "OP009": {
        "name":   "db_init",
        "gates":  ["BootGate", "DbGate"],
        "module": "system",
    },
    "OP009_001": {
        "name":   "db_connection",
        "gates":  ["DbGate"],
        "module": "system",
    },
    "OP009_002": {
        "name":   "db_migrations",
        "gates":  ["DbGate"],
        "module": "system",
    },
    "OP009_003": {
        "name":   "db_tables_verify",
        "gates":  ["DbGate"],
        "module": "system",
    },

    # ══════════════════════════════════════════════════════
    # SYSTEM — OP010
    # ══════════════════════════════════════════════════════

    # ── OP010 — BOOT ──────────────────────────────────────
    "OP010": {
        "name":   "system_boot",
        "gates":  ["BootGate"],
        "module": "system",
    },
    "OP010_001": {
        "name":   "boot_phase1_db",
        "gates":  ["BootGate"],
        "module": "system",
    },
    "OP010_002": {
        "name":   "boot_phase1_blueprints",
        "gates":  ["BootGate"],
        "module": "system",
    },
    "OP010_003": {
        "name":   "boot_phase2_oauth",
        "gates":  ["BootGate"],
        "module": "system",
    },
    "OP010_004": {
        "name":   "boot_phase2_conductor",
        "gates":  ["BootGate"],
        "module": "system",
    },
    "OP010_005": {
        "name":   "boot_phase2_tracer",
        "gates":  ["BootGate"],
        "module": "system",
    },

    # ══════════════════════════════════════════════════════
    # LIFEBOUND — OP020 a OP029 (fase siguiente)
    # ══════════════════════════════════════════════════════
    # Se añaden en la siguiente fase de implementación.

}


# ── API de consulta ────────────────────────────────────────────────────────

def get_operation(op_id: str) -> dict | None:
    """
    Devuelve la definición de una operación por su ID.
    Retorna None si el ID no existe.
    """
    return OPERATIONS.get(op_id)


def get_gates_for(op_id: str) -> list[str]:
    """
    Devuelve los gates que necesita una operación.
    Si el ID no existe, retorna lista vacía.
    """
    op = OPERATIONS.get(op_id)
    return op["gates"] if op else []


def needs_gate(op_id: str, gate_name: str) -> bool:
    """
    Retorna True si la operación necesita ese gate.

    Ejemplo:
        needs_gate("OP001_002", "DbGate") → True
        needs_gate("OP001_002", "HttpGate") → False
    """
    return gate_name in get_gates_for(op_id)


def get_operations_by_gate(gate_name: str) -> list[str]:
    """
    Devuelve todos los IDs de operación que usan ese gate.
    Útil para el Conductor cuando un gate cambia a CLOSED —
    sabe exactamente qué operaciones no pueden ejecutarse.
    """
    return [
        op_id
        for op_id, op in OPERATIONS.items()
        if gate_name in op["gates"]
    ]


def get_operations_by_module(module: str) -> list[str]:
    """
    Devuelve todos los IDs de operación de un módulo.
    """
    return [
        op_id
        for op_id, op in OPERATIONS.items()
        if op["module"] == module
    ]


def exists(op_id: str) -> bool:
    """Retorna True si el ID de operación está definido en el sistema."""
    return op_id in OPERATIONS