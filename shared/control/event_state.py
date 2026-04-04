# shared/control/event_state.py
# ══════════════════════════════════════════════════════════════════════════════
# Estados de un evento — AUREON Sistema de Control v3.0
#
# Todo evento que pasa por el sistema tiene exactamente uno
# de estos 5 estados en cada punto de la cadena.
#
# Flujo normal:
#     CREATE → PENDING → PENDING → FINISH
#
# Flujo con fallo:
#     CREATE → PENDING → FAILED → PROCESSING → FINISH
#
# Regla arquitectónica:
#     Este módulo NO importa nada de products/ ni de otros
#     módulos de control. Es la base — no tiene dependencias.
# ══════════════════════════════════════════════════════════════════════════════

from enum import Enum


class EventState(str, Enum):
    """
    Los 5 estados posibles de un evento en el sistema de control.

    CREATE
        El Gate escaneó el evento y le asignó un ID.
        Es el estado inicial — todo evento nace aquí.

    PENDING
        El evento está en tránsito por la cadena.
        Puede pasar por múltiples puntos en PENDING
        antes de llegar a FINISH o FAILED.

    FAILED
        Algo falló en este punto de la cadena.
        El evento no puede continuar por esta rama.
        El fallo se propaga hacia abajo — nunca hacia arriba.
        Después de FAILED siempre viene PROCESSING.

    PROCESSING
        El Conductor está analizando el fallo.
        El Timer está calculando cuándo cerrar el gate.
        Es un estado transitorio — siempre termina en FINISH.

    FINISH
        El evento completó su ciclo.
        Puede ser con o sin intervención del Breaker.
        Es el estado terminal — no hay estado después de FINISH.
    """

    CREATE     = "create"
    PENDING    = "pending"
    FAILED     = "failed"
    PROCESSING = "processing"
    FINISH     = "finish"


# ── Transiciones válidas ───────────────────────────────────────────────────
#
# Define qué estados pueden seguir a cada estado.
# El Conductor usa esto para validar que el flujo es correcto.
#
# CREATE     → PENDING, FINISH (si la operación es instantánea)
# PENDING    → PENDING, FAILED, FINISH
# FAILED     → PROCESSING
# PROCESSING → FINISH
# FINISH     → (ninguno — estado terminal)

VALID_TRANSITIONS: dict[EventState, set[EventState]] = {
    EventState.CREATE:     {EventState.PENDING, EventState.FINISH},
    EventState.PENDING:    {EventState.PENDING, EventState.FAILED, EventState.FINISH},
    EventState.FAILED:     {EventState.PROCESSING},
    EventState.PROCESSING: {EventState.FINISH},
    EventState.FINISH:     set(),  # terminal
}


def is_valid_transition(current: EventState, next_state: EventState) -> bool:
    """
    Verifica si una transición de estado es válida.

    Uso:
        from shared.control.event_state import EventState, is_valid_transition

        ok = is_valid_transition(EventState.FAILED, EventState.PROCESSING)
        # → True

        ok = is_valid_transition(EventState.FINISH, EventState.PENDING)
        # → False — FINISH es terminal
    """
    return next_state in VALID_TRANSITIONS.get(current, set())


def is_terminal(state: EventState) -> bool:
    """
    Retorna True si el estado es terminal (no hay transición posible).
    Solo FINISH es terminal.
    """
    return state == EventState.FINISH


def is_active(state: EventState) -> bool:
    """
    Retorna True si el evento todavía está en curso.
    Un evento activo es el que no ha llegado a FINISH.
    """
    return state != EventState.FINISH


def needs_conductor(state: EventState) -> bool:
    """
    Retorna True si el estado requiere atención del Conductor.
    Solo FAILED requiere intervención del Conductor.
    """
    return state == EventState.FAILED