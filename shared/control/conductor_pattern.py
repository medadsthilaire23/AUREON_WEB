# shared/control/conductor_pattern.py
# ══════════════════════════════════════════════════════════════════════════════
# Patrón de integración: GateResolver → Tracer (Opción B)
#
# Este archivo documenta el contrato que el Conductor debe implementar
# al orquestar una operación. NO es código de producción — es la plantilla
# que el Conductor importa como referencia de diseño.
#
# Flujo completo por operación:
#
#   1. GateResolver.resolve(op_id)
#      → Valida la jerarquía de gates de forma pura (sin tocar flask.g)
#      → Devuelve ResolveResult con gates_ordered
#
#   2. Si ALLOWED:
#      → Conductor llama checkpoint(gate) por cada gate en gates_ordered
#      → El Tracer tatúa g.event_id en cada paso
#      → Al final: g.event_id = "20260408112034847_H_D_M"
#
#   3. Si BLOCKED:
#      → Conductor registra el fallo con blocked_by
#      → El event_id NO evoluciona más allá del último gate aprobado
#      → El estado transiciona a ANOMALY si el gate bloqueado es SecurityGate
#
#   4. Si DISCOVERY (XX):
#      → Conductor emite alerta ROJA_CRITICA al Management
#      → El event_id permanece en su estado base (sin evolución)
#      → El estado transiciona directamente a ANOMALY
#
# Garantías del contrato:
#   - El GateResolver nunca toca flask.g
#   - El Tracer es el único que llama evolve_id
#   - El Conductor es el único que conoce a ambos
#   - Un gate nunca se tatúa si el resolver no lo aprobó primero
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import TYPE_CHECKING

from shared.control.event_state  import EventState, is_anomaly_op, get_alert_level
from shared.control.tracer       import checkpoint
from shared.control.logic.gate_resolver import ResolveStatus

if TYPE_CHECKING:
    from shared.control.logic.gate_resolver import GateResolver, ResolveResult


def execute_with_gate_check(
    op_id:    str,
    resolver: "GateResolver",
) -> "ResolveResult":
    """
    Patrón estándar de ejecución con verificación de gates.

    El Conductor llama esta función antes de ejecutar cualquier operación.
    Si el resultado es ALLOWED, los gates ya están tatuados en g.event_id.

    Uso en el Conductor:
        result = execute_with_gate_check("OP001_002", gate_resolver)

        if result.allowed:
            # g.event_id ya evolucionó — ejecutar la operación
            do_operation()
        elif result.status == ResolveStatus.BLOCKED:
            # abortar — result.blocked_by dice quién bloqueó
            return abort_with_blocked(result)
        elif result.status == ResolveStatus.DISCOVERY:
            # op desconocida — alerta ROJA_CRITICA
            return abort_with_discovery(result)
    """
    result = resolver.resolve(op_id)

    if result.status == ResolveStatus.ALLOWED:
        # ── Tatuar el event_id con cada gate aprobado ─────
        # gates_ordered garantiza: únicos, en orden de validación, sin repetidos.
        # El Tracer detectaría un loop si intentáramos tatuar el mismo gate dos veces,
        # por eso usamos gates_ordered y no gates (que puede tener repetidos por herencia).
        for gate_name in result.gates_ordered:
            checkpoint(gate_name)

    elif result.status == ResolveStatus.BLOCKED:
        # El event_id permanece en su último estado válido.
        # El estado del evento transiciona a FAILED → PROCESSING.
        # Si el gate que bloqueó es SecurityGate → ANOMALY directamente.
        pass

    elif result.status == ResolveStatus.DISCOVERY:
        # op_id desconocida → XX.
        # El estado transiciona a ANOMALY.
        # La alerta ya fue emitida por el GateResolver (log WARNING).
        # El Conductor debe escalarla al Management con nivel ROJA_CRITICA.
        pass

    return result


# ══════════════════════════════════════════════════════════════════════════════
# TABLA DE TRANSICIONES DE ESTADO POR RESULTADO
# ══════════════════════════════════════════════════════════════════════════════
#
# ResolveStatus  │ EventState destino  │ Notas
# ───────────────┼─────────────────────┼──────────────────────────────────────
# ALLOWED        │ VALIDATING          │ El resolver aprobó — listo para EXECUTING
# BLOCKED        │ FAILED → PROCESSING │ Gate cerrado — Conductor analiza
# BLOCKED (S)    │ ANOMALY             │ SecurityGate bloqueó — alerta ROJA
# DISCOVERY (XX) │ ANOMALY             │ Op desconocida — alerta ROJA_CRITICA
# ERROR          │ FAILED              │ Error interno del resolver — FA prefix
#
# La transición VALIDATING → EXECUTING la hace el gate que inicia
# la operación de negocio real (DbGate.scan, ModuleGate.call, etc.)
# ══════════════════════════════════════════════════════════════════════════════

STATE_BY_RESOLVE: dict[ResolveStatus, EventState] = {
    ResolveStatus.ALLOWED:   EventState.VALIDATING,
    ResolveStatus.BLOCKED:   EventState.FAILED,
    ResolveStatus.DISCOVERY: EventState.ANOMALY,
    ResolveStatus.ERROR:     EventState.FAILED,
}


def resolve_to_state(result: "ResolveResult") -> EventState:
    """
    Traduce un ResolveResult al EventState correspondiente.

    Caso especial: BLOCKED por SecurityGate → ANOMALY (no FAILED).
    El SecurityGate no es un fallo técnico — es una detección activa.
    """
    if result.status == ResolveStatus.BLOCKED and result.blocked_by == "SecurityGate":
        return EventState.ANOMALY

    return STATE_BY_RESOLVE.get(result.status, EventState.FAILED)