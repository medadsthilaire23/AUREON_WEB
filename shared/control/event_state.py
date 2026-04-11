# shared/control/event_state.py
# ══════════════════════════════════════════════════════════════════════════════
# Gestor de Ciclo de Vida — AUREON v4.0
#
# El event_state es el "semáforo" o "expediente" del evento.
# Es volátil — vive en el Registry y puede cambiar en cada paso.
# El event_id (el "papel") no sabe qué dice el semáforo.
#
# Filosofía v4.0:
#   Los estados se dividen en dos familias:
#
#   FAMILIA NOMINAL (flujo exitoso):
#     CREATE → VALIDATING → EXECUTING → FINISH
#
#   FAMILIA DE CRISIS (flujo con anomalía):
#     CREATE → VALIDATING → FAILED → PROCESSING → FINISH
#                         ↘ ANOMALY (estado especial para prefijos XX/AD/UR/etc.)
#
# Cambios v4.0 vs v3.x:
#   + VALIDATING  — nuevo: el gate_resolver está verificando la jerarquía
#   + EXECUTING   — nuevo: la operación está siendo procesada activamente
#   + ANOMALY     — nuevo: estado especial para eventos con prefijo de crisis
#   ~ PENDING     — deprecated (mantenido para compatibilidad v3.x)
#   ~ PROCESSING  — mantenido (el Conductor analiza el fallo)
#
# Integración con prefijos de anomalía:
#   Cuando un evento recibe op_id="XX" (Discovery) o cualquier prefijo de crisis,
#   su estado transiciona a ANOMALY. El Conductor luego lo mueve a PROCESSING
#   para análisis y finalmente a FINISH.
#
# Regla arquitectónica:
#   Este módulo NO importa nada de products/ ni de otros módulos de control.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from enum import Enum
from typing import Optional


# ══════════════════════════════════════════════════════════════════════════════
# ESTADOS
# ══════════════════════════════════════════════════════════════════════════════

class EventState(str, Enum):
    """
    Los 7 estados del ciclo de vida de un evento en AUREON v4.0.

    ── FAMILIA NOMINAL ──────────────────────────────────────────
    CREATE
        El HttpGate escaneó la request y asignó un ID.
        Estado inicial — todo evento nace aquí.

    VALIDATING  [NUEVO v4.0]
        El gate_resolver está verificando la jerarquía de gates.
        ¿Los gates padre están OPEN? ¿El Sub-Gate puede ejecutar?
        Estado transitorio — dura microsegundos.

    EXECUTING   [NUEVO v4.0]
        La operación de negocio está siendo procesada.
        DbGate ejecuta la query, ModuleGate llama al servicio externo.
        Estado activo — puede durar ms o segundos.

    FINISH
        El evento completó su ciclo con o sin intervención del Breaker.
        Estado terminal — no hay transición posible desde aquí.

    ── FAMILIA DE CRISIS ─────────────────────────────────────────
    FAILED
        Algo falló en este punto de la cadena.
        El fallo se propaga hacia abajo — nunca hacia arriba.
        Después de FAILED siempre viene PROCESSING o ANOMALY.

    PROCESSING
        El Conductor está analizando el fallo.
        El Timer está calculando cuándo cerrar el gate.
        Estado transitorio — siempre termina en FINISH.

    ANOMALY     [NUEVO v4.0]
        Estado especial para eventos con prefijo de crisis:
        XX (Discovery), AD (Admin), UR (Usuario), FL (Falso Loc),
        GB (Gate Bloqueado), FA (Fallo Técnico), TM (Timeout), SA (Saturación).
        El dashboard muestra estos eventos en el panel de crisis con alerta ROJA.
        Transiciona a PROCESSING para análisis del Conductor.

    ── COMPATIBILIDAD v3.x ───────────────────────────────────────
    PENDING
        Mantenido para compatibilidad con código v3.x existente.
        Equivale semánticamente a EXECUTING en v4.0.
        En v5.0 será eliminado.
    """

    CREATE     = "create"
    VALIDATING = "validating"   # nuevo v4.0
    EXECUTING  = "executing"    # nuevo v4.0
    PENDING    = "pending"      # deprecated — compatibilidad v3.x
    FAILED     = "failed"
    PROCESSING = "processing"
    ANOMALY    = "anomaly"      # nuevo v4.0
    FINISH     = "finish"


# ══════════════════════════════════════════════════════════════════════════════
# TRANSICIONES VÁLIDAS
# ══════════════════════════════════════════════════════════════════════════════

VALID_TRANSITIONS: dict[EventState, set[EventState]] = {
    # Flujo nominal
    EventState.CREATE:     {EventState.VALIDATING, EventState.EXECUTING, EventState.PENDING, EventState.FINISH, EventState.FAILED, EventState.ANOMALY},
    EventState.VALIDATING: {EventState.EXECUTING,  EventState.FAILED,    EventState.ANOMALY},
    EventState.EXECUTING:  {EventState.FINISH,      EventState.FAILED,    EventState.ANOMALY},

    # Compatibilidad v3.x
    EventState.PENDING:    {EventState.EXECUTING,   EventState.PENDING,   EventState.FAILED,  EventState.FINISH, EventState.ANOMALY},

    # Flujo de crisis
    EventState.FAILED:     {EventState.PROCESSING,  EventState.ANOMALY},
    EventState.PROCESSING: {EventState.FINISH},
    EventState.ANOMALY:    {EventState.PROCESSING},

    # Terminal
    EventState.FINISH:     set(),
}


def is_valid_transition(current: EventState, next_state: EventState) -> bool:
    """
    Verifica si una transición de estado es válida.

    Ejemplos:
        is_valid_transition(EventState.CREATE, EventState.VALIDATING) → True
        is_valid_transition(EventState.FINISH, EventState.PENDING)    → False
        is_valid_transition(EventState.CREATE, EventState.ANOMALY)    → True
    """
    return next_state in VALID_TRANSITIONS.get(current, set())


def is_terminal(state: EventState) -> bool:
    """True si el estado es terminal (FINISH)."""
    return state == EventState.FINISH


def is_active(state: EventState) -> bool:
    """True si el evento todavía está en curso (no ha llegado a FINISH)."""
    return state != EventState.FINISH


def is_crisis(state: EventState) -> bool:
    """
    True si el evento está en estado de crisis.
    Usado por el Conductor para priorizar análisis.
    """
    return state in (EventState.FAILED, EventState.ANOMALY)


def needs_conductor(state: EventState) -> bool:
    """
    True si el estado requiere atención del Conductor.
    FAILED y ANOMALY requieren intervención.
    """
    return state in (EventState.FAILED, EventState.ANOMALY)


# ══════════════════════════════════════════════════════════════════════════════
# INTEGRACIÓN CON PREFIJOS DE ANOMALÍA
# ══════════════════════════════════════════════════════════════════════════════

# Prefijos que disparan transición automática a ANOMALY
ANOMALY_PREFIXES: set[str] = {"XX", "AD", "UR", "FL", "GB", "FA", "TM", "SA"}

# Nivel de alerta por prefijo
ANOMALY_ALERT_LEVEL: dict[str, str] = {
    "XX": "ROJA_CRITICA",   # Discovery — operación desconocida
    "AD": "ROJA",           # Admin — acción no autorizada
    "FL": "ROJA",           # Falso Loc — IP/GPS manipulado
    "GB": "ROJA",           # Gate Bloqueado — intento de bypass
    "SA": "ROJA",           # Saturación — DDoS
    "FA": "NARANJA",        # Fallo Técnico — Python exception
    "TM": "NARANJA",        # Timeout — latencia crítica
    "UR": "AMARILLA",       # Usuario — error de input
}


def is_anomaly_op(op_id: str) -> bool:
    """
    True si el op_id corresponde a un prefijo de anomalía.
    Estos eventos deben transicionar a ANOMALY automáticamente.

    Ejemplos:
        is_anomaly_op("XX")         → True
        is_anomaly_op("AD100_001")  → True
        is_anomaly_op("OP001")      → False
    """
    prefix = op_id[:2] if len(op_id) >= 2 else op_id
    return prefix in ANOMALY_PREFIXES


def get_alert_level(op_id: str) -> Optional[str]:
    """
    Retorna el nivel de alerta para un op_id de anomalía.
    None si no es un prefijo de anomalía.

    Ejemplos:
        get_alert_level("XX")     → "ROJA_CRITICA"
        get_alert_level("FA001")  → "NARANJA"
        get_alert_level("OP001")  → None
    """
    prefix = op_id[:2] if len(op_id) >= 2 else op_id
    return ANOMALY_ALERT_LEVEL.get(prefix)


def resolve_initial_state(op_id: str) -> EventState:
    """
    Determina el estado inicial correcto para un evento según su op_id.

    Para operaciones normales (OP*): CREATE
    Para operaciones de anomalía (XX, AD, etc.): CREATE también,
    pero el gate_resolver transitará inmediatamente a ANOMALY.

    Esta función es usada por el HttpGate en scan() para establecer
    el estado correcto desde el primer registro.
    """
    return EventState.CREATE


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS DE CICLO DE VIDA
# ══════════════════════════════════════════════════════════════════════════════

class StateTransitionError(Exception):
    """Lanzada cuando se intenta una transición de estado inválida."""
    def __init__(self, current: EventState, attempted: EventState, event_id: str = ""):
        self.current   = current
        self.attempted = attempted
        self.event_id  = event_id
        super().__init__(
            f"Transición inválida: {current.value} → {attempted.value}"
            + (f" (event_id={event_id})" if event_id else "")
        )


def safe_transition(
    current:    EventState,
    next_state: EventState,
    event_id:   str = "",
    strict:     bool = False,
) -> Optional[EventState]:
    """
    Intenta una transición de estado de forma segura.

    Si strict=True y la transición es inválida, lanza StateTransitionError.
    Si strict=False, retorna None en caso de transición inválida (fail-soft).

    Uso:
        new_state = safe_transition(EventState.CREATE, EventState.VALIDATING)
        if new_state is None:
            log.warning("Transición inválida ignorada")
    """
    if is_valid_transition(current, next_state):
        return next_state

    if strict:
        raise StateTransitionError(current, next_state, event_id)

    return None


# ══════════════════════════════════════════════════════════════════════════════
# DISPLAY — para el dashboard
# ══════════════════════════════════════════════════════════════════════════════

STATE_COLORS: dict[EventState, str] = {
    EventState.CREATE:     "blue",
    EventState.VALIDATING: "cyan",
    EventState.EXECUTING:  "purple",
    EventState.PENDING:    "yellow",    # compatibilidad v3.x
    EventState.FAILED:     "red",
    EventState.PROCESSING: "orange",
    EventState.ANOMALY:    "red_critical",
    EventState.FINISH:     "green",
}

STATE_LABELS: dict[EventState, str] = {
    EventState.CREATE:     "CREATE",
    EventState.VALIDATING: "VALIDATING",
    EventState.EXECUTING:  "EXECUTING",
    EventState.PENDING:    "PENDING",
    EventState.FAILED:     "FAILED",
    EventState.PROCESSING: "PROCESSING",
    EventState.ANOMALY:    "ANOMALY ⚠",
    EventState.FINISH:     "FINISH",
}


def state_color(state: EventState) -> str:
    """Color del estado para el dashboard."""
    return STATE_COLORS.get(state, "gray")


def state_label(state: EventState) -> str:
    """Etiqueta del estado para el dashboard."""
    return STATE_LABELS.get(state, state.value.upper())