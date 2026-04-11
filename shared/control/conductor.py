# shared/control/conductor.py
# ══════════════════════════════════════════════════════════════════════════════
# CONDUCTOR — AUREON v4.0
#
# Cambios v4.0 vs v3.0:
#
#   wire_resolver()
#     Inyecta el GateResolver en Fase 2. El Conductor es el único
#     que conoce tanto al Resolver como al Tracer — es el orquestador.
#
#   operate(op_id) — método central de v4.0
#     Implementa el ciclo completo: resolver → tatuar gates → transicionar
#     estados → ejecutar → cerrar. Reemplaza el uso directo de call()
#     para operaciones registradas en tabla_operacion.json.
#     Retorna OperateResult — el Conductor nunca lanza excepciones
#     al código de negocio, solo informa.
#
#   scan_registry() ampliado
#     Ahora procesa FAILED y ANOMALY — ambos requieren atención del
#     Conductor según needs_conductor() de event_state.py.
#     Ya no importa operation_gates.py — usa GateResolver como
#     fuente de verdad única para inferir impacto y recovery.
#
#   Compatibilidad v3.x total:
#     call(), receive(), _decide(), _execute() sin cambios.
#     El código existente no se rompe durante la migración.
#
# Regla arquitectónica:
#   Este módulo NO importa nada de products/.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from shared.control.alert       import Alert, Impact, Recovery, Origin, Severity
from shared.control.gate        import BaseGate
from shared.control.breaker     import BaseBreaker
from shared.control.registry    import BaseRegistry
from shared.control.event_id    import generate_event_id
from shared.control.event_state import (
    EventState,
    is_anomaly_op,
    get_alert_level,
    needs_conductor,
    safe_transition,
)
from shared.control.tracer import checkpoint as tracer_checkpoint

from shared.control.registries.base import BreakerRegistry, GateRegistry, EventRegistry
from shared.control.breakers.base   import CircuitBreaker, BreakerOpenError, BreakerSnapshot
from shared.control.gates.base      import Gate, GateClosed, GateSnapshot

# GateResolver importado con TYPE_CHECKING para evitar ciclos en bootstrap
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from shared.control.logic.gate_resolver import GateResolver, ResolveResult

log = logging.getLogger("aureon.control.conductor")

try:
    import sentry_sdk
    _SENTRY = True
except ImportError:
    _SENTRY = False


# ══════════════════════════════════════════════════════════
# DECISION (sin cambios v3.0)
# ══════════════════════════════════════════════════════════

class Action(str, Enum):
    CONTINUE      = "continue"
    LOG_AND_PASS  = "log_and_pass"
    BLOCK_REQUEST = "block_request"
    TRIP_MODULE   = "trip_module"
    TRIP_GLOBAL   = "trip_global"
    SHUTDOWN      = "shutdown"


@dataclass
class Decision:
    action:    Action
    alert:     Alert
    message:   str
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "action":    self.action.value,
            "alert":     self.alert.to_dict(),
            "message":   self.message,
            "timestamp": self.timestamp.isoformat(),
        }

    def __str__(self) -> str:
        return f"Decision({self.action.value}) ← {self.alert.code} | {self.message}"


# ══════════════════════════════════════════════════════════
# OPERATE RESULT — v4.0
# ══════════════════════════════════════════════════════════

@dataclass
class OperateResult:
    """
    Resultado de operate() — el Conductor nunca lanza al código de negocio.

    allowed       — True si todos los gates aprobaron y se puede ejecutar.
    event_id      — event_id final evolucionado (con aliases tatuados).
    op_id         — op_id resuelto.
    op_name       — nombre legible de la operación.
    gates_stamped — aliases tatuados en orden: ["H", "D", "M"].
    blocked_by    — gate que bloqueó (solo si not allowed).
    is_discovery  — True si op_id no estaba en tabla_operacion.json.
    alert_level   — nivel de alerta si hay anomalía (None si flujo nominal).
    state         — EventState actual del evento tras operate().
    reason        — mensaje descriptivo del resultado.
    """
    allowed:       bool
    event_id:      str
    op_id:         str
    op_name:       str           = "unknown"
    gates_stamped: list[str]     = field(default_factory=list)
    blocked_by:    Optional[str] = None
    is_discovery:  bool          = False
    alert_level:   Optional[str] = None
    state:         EventState    = EventState.CREATE
    reason:        str           = ""

    def to_dict(self) -> dict:
        return {
            "allowed":       self.allowed,
            "event_id":      self.event_id,
            "op_id":         self.op_id,
            "op_name":       self.op_name,
            "gates_stamped": self.gates_stamped,
            "blocked_by":    self.blocked_by,
            "is_discovery":  self.is_discovery,
            "alert_level":   self.alert_level,
            "state":         self.state.value,
            "reason":        self.reason,
        }


# ══════════════════════════════════════════════════════════
# CONDUCTOR
# ══════════════════════════════════════════════════════════

class Conductor:

    def __init__(self):
        self._gates:      Dict[str, BaseGate]     = {}
        self._breakers:   Dict[str, BaseBreaker]  = {}
        self._registries: Dict[str, BaseRegistry] = {}
        self._products:   Dict[str, dict]         = {}
        self._callbacks:  List[Callable[[Alert, Decision], None]] = []
        self._decisions:  List[Decision]          = []
        self._ready       = False
        self._timer       = None     # inyectado en Fase 2 vía wire_timer()
        self._resolver    = None     # inyectado en Fase 2 vía wire_resolver()
        self._lock        = threading.Lock()

    # ══════════════════════════════════════════════════════
    # WIRING
    # ══════════════════════════════════════════════════════

    def wire_timer(self, timer) -> None:
        """
        Inyecta el Timer en Fase 2.
        El Timer es el único que puede ordenar el cierre de un gate.
        """
        self._timer = timer
        log.info("[Conductor] Timer inyectado")

    def wire_resolver(self, resolver: "GateResolver") -> None:
        """
        Inyecta el GateResolver en Fase 2.
        Llamar después de wire_timer() y antes de mark_ready().

        El Conductor es el único punto que conoce tanto al Resolver
        como al Tracer — es el orquestador del ciclo completo v4.0.
        """
        self._resolver = resolver
        log.info(
            "[Conductor] GateResolver inyectado — %d operaciones disponibles",
            len(resolver.all_op_ids()),
        )

    def register_gate(self, gate: BaseGate) -> None:
        self._gates[gate.name] = gate
        gate.set_conductor(self)
        log.info("Conductor: Gate registrado — %s", gate.name)

    def register_breaker(self, breaker: BaseBreaker) -> None:
        self._breakers[breaker.name] = breaker
        log.info("Conductor: Breaker registrado — %s", breaker.name)

    def register_registry(self, registry: BaseRegistry) -> None:
        self._registries[registry.name] = registry
        log.info("Conductor: Registry registrado — %s", registry.name)

    def register_product(self, name: str, meta: dict) -> None:
        self._products[name] = {
            **meta,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
        log.info(
            "Conductor: Producto registrado — %s (breakers=%s gates=%s)",
            name,
            meta.get("breakers", []),
            meta.get("gates",    []),
        )

    def on_decision(self, callback: Callable[[Alert, Decision], None]) -> None:
        self._callbacks.append(callback)

    def mark_ready(self) -> None:
        self._ready = True
        log.info(
            "Conductor listo — Gates: %d | Breakers: %d | Registries: %d"
            " | Productos: %d | Resolver: %s",
            len(self._gates),
            len(self._breakers),
            len(self._registries),
            len(self._products),
            "✓" if self._resolver else "✗ (sin GateResolver)",
        )

    # ══════════════════════════════════════════════════════
    # OPERATE — ciclo completo v4.0
    # ══════════════════════════════════════════════════════

    def operate(self, op_id: str) -> OperateResult:
        """
        Ciclo completo de una operación en v4.0.

        Pasos:
            1. Resolver.resolve(op_id) — validar jerarquía de gates
            2. Si ALLOWED: tatuar gates con checkpoint() → g.event_id evoluciona
            3. Transicionar EventState según el resultado
            4. Si BLOCKED o DISCOVERY: emitir alerta al Conductor

        El código de negocio recibe OperateResult y decide si ejecutar:

            result = conductor.operate("OP001_002")
            if result.allowed:
                do_operation()   # g.event_id ya evolucionó
            else:
                return error_response(result)

        Fail-open si no hay GateResolver inyectado:
            Retorna allowed=True para no bloquear el sistema durante bootstrap.
            El event_id no evoluciona en ese caso.
        """
        from flask import g

        event_id = getattr(g, "event_id", generate_event_id())

        # ── Fail-open sin resolver ────────────────────────
        if self._resolver is None:
            log.warning(
                "[Conductor] operate('%s') sin GateResolver — fail-open",
                op_id,
            )
            return OperateResult(
                allowed  = True,
                event_id = event_id,
                op_id    = op_id,
                state    = EventState.EXECUTING,
                reason   = "Sin GateResolver — fail-open durante bootstrap",
            )

        # ── Paso 1: Resolver ──────────────────────────────
        result = self._resolver.resolve(op_id)

        # ── Paso 2: Tatuar gates o gestionar anomalía ─────
        from shared.control.logic.gate_resolver import ResolveStatus

        if result.status == ResolveStatus.ALLOWED:
            return self._operate_allowed(result, event_id)

        elif result.status == ResolveStatus.BLOCKED:
            return self._operate_blocked(result, event_id)

        elif result.status == ResolveStatus.DISCOVERY:
            return self._operate_discovery(result, event_id)

        else:
            # ResolveStatus.ERROR — error interno del resolver
            return self._operate_error(result, event_id)

    def _operate_allowed(self, result: "ResolveResult", event_id: str) -> OperateResult:
        """
        Flujo nominal: todos los gates OPEN.
        Tatúa gates_ordered en g.event_id vía checkpoint().
        Transiciona CREATE → VALIDATING.
        """
        gates_stamped = []

        for gate_name in result.gates_ordered:
            try:
                new_id = tracer_checkpoint(gate_name)
                gates_stamped.append(gate_name)
                event_id = new_id
            except Exception as e:
                # Loop detectado por el Tracer — tratar como BLOCKED
                log.error(
                    "[Conductor] operate: loop en gate '%s': %s",
                    gate_name, e,
                )
                return OperateResult(
                    allowed    = False,
                    event_id   = event_id,
                    op_id      = result.op_id,
                    op_name    = result.op_name,
                    gates_stamped = gates_stamped,
                    blocked_by = gate_name,
                    state      = EventState.ANOMALY,
                    alert_level = "ROJA",
                    reason     = f"Loop de gates detectado en '{gate_name}' (GB)",
                )

        # Transicionar → VALIDATING (el gate de negocio lo moverá a EXECUTING)
        EventRegistry.transition(event_id, result.op_id, EventState.VALIDATING)

        log.debug(
            "[Conductor] ALLOWED op=%s gates=%s event_id=%s",
            result.op_id, gates_stamped, event_id,
        )

        return OperateResult(
            allowed       = True,
            event_id      = event_id,
            op_id         = result.op_id,
            op_name       = result.op_name,
            gates_stamped = gates_stamped,
            state         = EventState.VALIDATING,
            reason        = result.reason,
        )

    def _operate_blocked(self, result: "ResolveResult", event_id: str) -> OperateResult:
        """
        Un gate padre está CLOSED.
        SecurityGate bloqueado → ANOMALY.
        Cualquier otro gate → FAILED → PROCESSING.
        """
        blocked_by  = result.blocked_by
        is_security = blocked_by == "SecurityGate"
        state       = EventState.ANOMALY if is_security else EventState.FAILED
        alert_level = "ROJA" if is_security else None

        EventRegistry.transition(event_id, result.op_id, state)

        # Emitir alerta al Conductor para que _decide() actúe
        alert = Alert(
            code     = f"GATE_BLOCKED_{(blocked_by or 'UNKNOWN').upper()}",
            message  = result.reason,
            impact   = self._infer_impact(result),
            recovery = self._infer_recovery(result),
            origin   = Origin.INTERNAL,
            module   = result.modulo,
            context  = {
                "op_id":       result.op_id,
                "blocked_by":  blocked_by,
                "chain":       result.blocked_chain,
                "alert_level": alert_level,
                "prefix":      "GB" if is_security else None,
            },
        )
        self._record_alert(alert)
        decision = self._decide(alert)
        self._execute(decision)

        log.info(
            "[Conductor] BLOCKED op=%s gate=%s security=%s",
            result.op_id, blocked_by, is_security,
        )

        return OperateResult(
            allowed     = False,
            event_id    = event_id,
            op_id       = result.op_id,
            op_name     = result.op_name,
            blocked_by  = blocked_by,
            state       = state,
            alert_level = alert_level,
            reason      = result.reason,
        )

    def _operate_discovery(self, result: "ResolveResult", event_id: str) -> OperateResult:
        """
        op_id no registrado en tabla_operacion.json → XX Discovery.
        Transiciona directamente a ANOMALY.
        Emite alerta ROJA_CRITICA al Management.
        """
        EventRegistry.transition(event_id, result.op_id, EventState.ANOMALY)

        alert = Alert(
            code     = "XX_DISCOVERY",
            message  = result.reason,
            impact   = Impact.REQUEST,
            recovery = Recovery.RUNTIME,
            origin   = Origin.INTERNAL,
            module   = "management",
            context  = {
                "op_id":       result.op_id,
                "alert_level": "ROJA_CRITICA",
                "prefix":      "XX",
                "action":      "Registrar en tabla_operacion.json via Aduana",
            },
        )
        self._record_alert(alert)
        # XX siempre pasa por _decide() — el Conductor decide si bloquear o loggear
        decision = self._decide(alert)
        self._execute(decision)

        log.warning(
            "[Conductor] XX DISCOVERY op_id='%s' — registrar en Aduana",
            result.op_id,
        )

        return OperateResult(
            allowed      = False,
            event_id     = event_id,
            op_id        = result.op_id,
            op_name      = "XX_DISCOVERY",
            is_discovery = True,
            state        = EventState.ANOMALY,
            alert_level  = "ROJA_CRITICA",
            reason       = result.reason,
        )

    def _operate_error(self, result: "ResolveResult", event_id: str) -> OperateResult:
        """
        Error interno del GateResolver — prefijo FA (Fallo Técnico).
        Fail-open: retorna allowed=True para no bloquear el sistema.
        """
        log.error(
            "[Conductor] ERROR en resolver op='%s': %s",
            result.op_id, result.reason,
        )
        return OperateResult(
            allowed     = True,     # fail-open — error del resolver no bloquea
            event_id    = event_id,
            op_id       = result.op_id,
            state       = EventState.EXECUTING,
            alert_level = "NARANJA",
            reason      = f"FA — Error interno del resolver: {result.reason}",
        )

    # ══════════════════════════════════════════════════════
    # LLAMADA PROTEGIDA (v2/v3 — sin cambios)
    # ══════════════════════════════════════════════════════

    def call(
        self,
        breaker_name: str,
        gate_name:    str,
        func:         Callable,
        *args:        Any,
        **kwargs:     Any,
    ) -> Any:
        gate: Gate | None = (
            GateRegistry.get(gate_name) if gate_name in GateRegistry else None
        )
        if gate is not None:
            gate.check()
        elif gate_name:
            log.warning("Conductor.call: gate '%s' no encontrado — fail-open", gate_name)

        breaker: CircuitBreaker | None = (
            BreakerRegistry.get(breaker_name)
            if breaker_name in BreakerRegistry else None
        )
        if breaker is not None:
            return breaker.call(func, *args, **kwargs)
        else:
            if breaker_name:
                log.warning("Conductor.call: breaker '%s' no encontrado — fail-open", breaker_name)
            return func(*args, **kwargs)

    # ══════════════════════════════════════════════════════
    # SCAN REGISTRY — v4.0 (ampliado)
    # ══════════════════════════════════════════════════════

    def scan_registry(self) -> List[Decision]:
        """
        Lee el EventRegistry y procesa entradas que requieren atención.

        v4.0: procesa FAILED y ANOMALY — ambos activan needs_conductor().
        v3.0: solo procesaba FAILED.

        Para cada entrada:
            FAILED  → PROCESSING → (acción) → FINISH
            ANOMALY → PROCESSING → (acción) → FINISH
        """
        entries_needing_action = (
            EventRegistry.get_failed() +
            EventRegistry.get_anomaly()
        )

        decisions = []

        for entry in entries_needing_action:
            alert = Alert(
                code     = self._alert_code_for(entry),
                message  = entry.error or f"Operación {entry.op_id} requiere atención",
                impact   = self._infer_impact_from_entry(entry),
                recovery = self._infer_recovery_from_entry(entry),
                origin   = Origin.INTERNAL,
                module   = entry.module,
                context  = {
                    "event_id":    entry.event_id,
                    "op_id":       entry.op_id,
                    "gate":        entry.gate,
                    "duration_ms": round(entry.duration_ms, 2),
                    "state":       entry.state,
                    "alert_level": get_alert_level(entry.op_id),
                },
            )

            # → PROCESSING
            EventRegistry.transition(
                entry.event_id, entry.op_id, EventState.PROCESSING,
            )

            decision = self._decide(alert)
            self._execute_v3(decision, entry)
            decisions.append(decision)

            # → FINISH
            EventRegistry.transition(
                entry.event_id, entry.op_id, EventState.FINISH,
            )

            log.info("[Conductor] scan: %s", decision)

        return decisions

    def _alert_code_for(self, entry) -> str:
        """Construye el código de alerta desde la entrada del registry."""
        if is_anomaly_op(entry.op_id):
            prefix = entry.op_id[:2].upper()
            return f"{prefix}_ANOMALY_{entry.op_id.replace('_', '')}"
        return f"REGISTRY_FAILED_{entry.op_id.replace('_', '')}"

    def _infer_impact_from_entry(self, entry) -> Impact:
        """
        Infiere el impacto usando el GateResolver como fuente de verdad.
        Fallback al método v3 basado en el gate si no hay resolver.
        """
        if self._resolver:
            op = self._resolver.get_op(entry.op_id)
            if op:
                gates = op.get("gates", [])
                if "BootGate" in gates:
                    return Impact.GLOBAL
                if len(gates) == 1 and gates[0] in ("DbGate", "ModuleGate"):
                    return Impact.MODULE
                return Impact.REQUEST

        # Fallback v3 — inferir desde el gate directamente
        return self._infer_impact_legacy(entry)

    def _infer_recovery_from_entry(self, entry) -> Recovery:
        """
        Infiere la recuperabilidad usando el GateResolver como fuente de verdad.
        Fallback al método v3 si no hay resolver.
        """
        if self._resolver:
            op = self._resolver.get_op(entry.op_id)
            if op:
                gates = op.get("gates", [])
                if "BootGate" in gates:
                    return Recovery.FATAL
                if entry.gate in ("DbGate", "ModuleGate"):
                    return Recovery.RUNTIME
                return Recovery.AUTO

        # Fallback v3
        return self._infer_recovery_legacy(entry)

    def _infer_impact_legacy(self, entry) -> Impact:
        """Inferencia v3 — solo cuando no hay GateResolver."""
        if entry.gate == "BootGate":
            return Impact.GLOBAL
        if entry.gate in ("DbGate", "ModuleGate"):
            return Impact.MODULE
        return Impact.REQUEST

    def _infer_recovery_legacy(self, entry) -> Recovery:
        """Inferencia v3 — solo cuando no hay GateResolver."""
        if entry.gate == "BootGate":
            return Recovery.FATAL
        if entry.gate in ("DbGate", "ModuleGate"):
            return Recovery.RUNTIME
        return Recovery.AUTO

    # ── Métodos v3 legacy (conservados por compatibilidad) ──

    def _infer_impact(self, result: "ResolveResult") -> Impact:
        """Inferencia desde ResolveResult — para operate()."""
        gates = result.gates_ordered
        if "BootGate" in gates:
            return Impact.GLOBAL
        if len(gates) == 1 and gates[0] in ("DbGate", "ModuleGate"):
            return Impact.MODULE
        return Impact.REQUEST

    def _infer_recovery(self, result: "ResolveResult") -> Recovery:
        """Recuperabilidad desde ResolveResult — para operate()."""
        gates = result.gates_ordered
        if "BootGate" in gates:
            return Recovery.FATAL
        if result.blocked_by in ("DbGate", "ModuleGate"):
            return Recovery.RUNTIME
        return Recovery.AUTO

    def _execute_v3(self, decision: Decision, entry) -> None:
        """
        Ejecuta la decisión usando el Timer.
        Sin cambios respecto a v3.0.
        """
        action    = decision.action
        gate_name = entry.gate

        if action in (Action.CONTINUE, Action.LOG_AND_PASS, Action.BLOCK_REQUEST):
            return

        if action == Action.TRIP_MODULE:
            self._schedule_close(gate_name, entry.event_id, entry.op_id)
            self._notify_sentry(decision)

        elif action == Action.TRIP_GLOBAL:
            for gname in {"HttpGate", "DbGate", "ModuleGate"}:
                self._schedule_close(gname, entry.event_id, entry.op_id)
            self._notify_sentry(decision)

        elif action == Action.SHUTDOWN:
            self._shutdown(decision.alert)
            self._notify_sentry(decision)

    def _schedule_close(
        self,
        gate_name:     str,
        trigger_event: str,
        trigger_op:    str,
    ) -> None:
        if self._timer is None:
            log.warning(
                "[Conductor] Sin Timer — cerrando gate '%s' directamente",
                gate_name,
            )
            self._close_gate_direct(gate_name)
            return

        def _on_drain():
            self._close_gate_direct(gate_name)
            log.info("[Conductor] Gate '%s' cerrado por Timer (cola drenada)", gate_name)

        self._timer.watch(
            gate_name     = gate_name,
            trigger_event = trigger_event,
            trigger_op    = trigger_op,
            on_drain      = _on_drain,
            max_wait_ms   = 30_000,
        )
        log.info("[Conductor] Timer observando gate='%s'", gate_name)

    def _close_gate_direct(self, gate_name: str) -> None:
        gate = self._gates.get(gate_name)
        if gate and hasattr(gate, "close"):
            gate.close()
            return
        if gate_name in GateRegistry:
            GateRegistry.get(gate_name).set_enabled(False)

    # ══════════════════════════════════════════════════════
    # RECEPCIÓN DE ALERTAS (v2 — sin cambios)
    # ══════════════════════════════════════════════════════

    def receive(self, alert: Alert) -> Decision:
        """Compatibilidad v2 — sin cambios."""
        log.warning("Conductor recibe: %s", alert)

        event_id = generate_event_id()
        EventRegistry.record(
            event_id = event_id,
            op_id    = "OP000",
            state    = EventState.FAILED,
            gate     = alert.module or "unknown",
            error    = alert.message,
        )

        self._record_alert(alert)
        decision = self._decide(alert)
        self._execute(decision)
        self._decisions.append(decision)

        for cb in self._callbacks:
            try:
                cb(alert, decision)
            except Exception as e:
                log.error("Conductor callback error: %s", e)

        EventRegistry.transition(event_id, "OP000", EventState.FINISH)

        log.info("Conductor decide: %s", decision)
        return decision

    # ══════════════════════════════════════════════════════
    # TABLA DE DECISIÓN (sin cambios)
    # ══════════════════════════════════════════════════════

    def _decide(self, alert: Alert) -> Decision:
        impact   = alert.impact
        recovery = alert.recovery

        if recovery == Recovery.AUTO:
            return Decision(
                action  = Action.LOG_AND_PASS,
                alert   = alert,
                message = f"Auto-recuperable — registrado y continuando. [{alert.code}]",
            )
        if impact == Impact.REQUEST:
            return Decision(
                action  = Action.BLOCK_REQUEST,
                alert   = alert,
                message = f"Request bloqueado por validación fallida. [{alert.code}]",
            )
        if impact == Impact.MODULE:
            return Decision(
                action  = Action.TRIP_MODULE,
                alert   = alert,
                message = f"Módulo '{alert.module}' cortado por fallo. [{alert.code}]",
            )
        if impact == Impact.GLOBAL and recovery == Recovery.FATAL:
            return Decision(
                action  = Action.SHUTDOWN,
                alert   = alert,
                message = f"Fallo fatal global — iniciando shutdown controlado. [{alert.code}]",
            )
        return Decision(
            action  = Action.TRIP_GLOBAL,
            alert   = alert,
            message = f"Sistema en modo seguro por fallo global. [{alert.code}]",
        )

    # ══════════════════════════════════════════════════════
    # EJECUCIÓN v2 (compatibilidad — sin cambios)
    # ══════════════════════════════════════════════════════

    def _execute(self, decision: Decision) -> None:
        action = decision.action
        alert  = decision.alert

        if action in (Action.CONTINUE, Action.LOG_AND_PASS, Action.BLOCK_REQUEST):
            pass
        elif action == Action.TRIP_MODULE:
            self._trip_module(alert)
            self._notify_sentry(decision)
        elif action == Action.TRIP_GLOBAL:
            self._trip_all(alert)
            self._notify_sentry(decision)
        elif action == Action.SHUTDOWN:
            self._shutdown(alert)
            self._notify_sentry(decision)

    def _trip_module(self, alert: Alert) -> None:
        module = alert.module
        if module in BreakerRegistry:
            BreakerRegistry.get(module).trip()
            return
        breaker = self._breakers.get(module)
        if breaker:
            breaker.trip(alert)
        else:
            log.warning("Conductor: No hay breaker para módulo '%s'", module)

    def _trip_all(self, alert: Alert) -> None:
        log.critical("Conductor: TRIP GLOBAL — abriendo todos los breakers. [%s]", alert.code)
        for name in BreakerRegistry.names():
            BreakerRegistry.get(name).trip()
        for breaker in self._breakers.values():
            if not breaker.is_open:
                breaker.trip(alert)

    def _shutdown(self, alert: Alert) -> None:
        log.critical(
            "Conductor: SHUTDOWN CONTROLADO iniciado. [%s] %s",
            alert.code, alert.message,
        )
        self._trip_all(alert)

    # ══════════════════════════════════════════════════════
    # SENTRY (sin cambios)
    # ══════════════════════════════════════════════════════

    def _notify_sentry(self, decision: Decision) -> None:
        if not _SENTRY:
            return
        if os.environ.get("FLASK_ENV") != "production":
            return
        try:
            alert     = decision.alert
            level_map = {
                Action.TRIP_MODULE: "warning",
                Action.TRIP_GLOBAL: "error",
                Action.SHUTDOWN:    "fatal",
            }
            level            = level_map.get(decision.action, "warning")
            registry_snap    = EventRegistry.snapshot()

            with sentry_sdk.push_scope() as scope:
                scope.set_tag("aureon.action",   decision.action.value)
                scope.set_tag("aureon.module",   alert.module or "global")
                scope.set_tag("aureon.impact",   alert.impact.value)
                scope.set_tag("aureon.recovery", alert.recovery.value)
                scope.set_tag("aureon.severity", alert.severity.value)
                scope.set_context("alert", {
                    "code":     alert.code,
                    "message":  alert.message,
                    "module":   alert.module,
                    "alert_id": alert.alert_id,
                })
                scope.set_context("registry",  registry_snap)
                scope.set_context("breakers", {
                    s["name"]: {
                        "state":    s.get("state"),
                        "failures": s.get("failure_count", 0),
                    }
                    for s in BreakerRegistry.all_snapshots()
                })
                scope.set_context("products", self._products)
                scope.set_level(level)
                sentry_sdk.capture_message(
                    f"[AUREON] {decision.action.value.upper()} — "
                    f"{alert.module or 'global'} | {alert.code}"
                )
        except Exception as e:
            log.error("[Sentry] error al notificar: %s", e)

    # ══════════════════════════════════════════════════════
    # REGISTRO DE ALERTAS (sin cambios)
    # ══════════════════════════════════════════════════════

    def _record_alert(self, alert: Alert) -> None:
        registry = self._registries.get("alerts")
        if registry:
            try:
                registry.record(alert, tags={
                    "severity": alert.severity.value,
                    "impact":   alert.impact.value,
                    "recovery": alert.recovery.value,
                    "origin":   alert.origin.value,
                    "module":   alert.module or "",
                })
            except Exception as e:
                log.error("Conductor: error al registrar alerta: %s", e)

    # ══════════════════════════════════════════════════════
    # CONSULTAS DE ESTADO (sin cambios)
    # ══════════════════════════════════════════════════════

    def status(self) -> dict:
        return {
            "ready":          self._ready,
            "products":       self._products,
            "timer_watching": self._timer.watching() if self._timer else [],
            "registry":       EventRegistry.snapshot(),
            "resolver":       self._resolver.snapshot() if self._resolver else None,
            "breakers": {
                **{s["name"]: s for s in BreakerRegistry.all_snapshots()},
                **{n: b.to_dict() for n, b in self._breakers.items()},
            },
            "gates": {
                **{s["name"]: s for s in GateRegistry.all_snapshots()},
                **{n: str(g) for n, g in self._gates.items()},
            },
            "registries":    {n: r.snapshot() for n, r in self._registries.items()},
            "decisions":     len(self._decisions),
            "last_decision": (
                self._decisions[-1].to_dict() if self._decisions else None
            ),
        }

    def all_snapshots(self) -> dict:
        return {
            "breakers": BreakerRegistry.all_snapshots(),
            "gates":    GateRegistry.all_snapshots(),
            "products": self._products,
            "registry": EventRegistry.snapshot(),
            "resolver": self._resolver.snapshot() if self._resolver else None,
        }

    def get_breaker(self, name: str) -> Optional[CircuitBreaker]:
        if name in BreakerRegistry:
            return BreakerRegistry.get(name)
        return self._breakers.get(name)

    def get_gate(self, name: str) -> Optional[Gate]:
        if name in GateRegistry:
            return GateRegistry.get(name)
        return self._gates.get(name)

    def reset_breaker(self, name: str) -> bool:
        breaker = self.get_breaker(name)
        if not breaker:
            return False
        breaker.reset()
        log.info("Conductor: Breaker '%s' reseteado manualmente", name)
        return True

    def set_gate(self, name: str, enabled: bool) -> bool:
        gate = self.get_gate(name)
        if not gate:
            return False
        gate.set_enabled(enabled)
        log.info("Conductor: Gate '%s' → enabled=%s", name, enabled)
        return True


# ══════════════════════════════════════════════════════════
# SINGLETON
# ══════════════════════════════════════════════════════════

conductor = Conductor()