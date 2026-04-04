# shared/control/conductor.py
# ══════════════════════════════════════════════════════════════════════════════
# CONDUCTOR — AUREON Sistema de Control v3.0
#
# Cambios respecto a v2:
#   - Lee el EventRegistry para correlacionar IDs — no recibe alertas crudas
#   - Integra el Timer para cierre seguro de gates
#   - Mantiene la tabla Impact × Recovery sin cambios
#   - Mantiene compatibilidad total con conductor.call() y conductor.receive()
#     para que el código existente no se rompa durante la migración
#
# Flujo v3:
#   Gate registra FAILED en EventRegistry
#       ↓
#   Conductor.scan_registry() detecta la entrada FAILED
#       ↓
#   Decide acción (tabla Impact × Recovery)
#       ↓
#   Timer.watch(gate_name, on_drain=breaker.close)
#       ↓
#   Timer espera cola = 0 → Breaker cierra el gate
#       ↓
#   EventRegistry.transition(event_id, op_id, FINISH)
#
# Compatibilidad v2:
#   conductor.receive(alert) sigue funcionando — traduce la alerta
#   a una entrada en EventRegistry y continúa el flujo normal.
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
from shared.control.event_state import EventState

from shared.control.registries.base import BreakerRegistry, GateRegistry, EventRegistry
from shared.control.breakers.base   import CircuitBreaker, BreakerOpenError, BreakerSnapshot
from shared.control.gates.base      import Gate, GateClosed, GateSnapshot

log = logging.getLogger("aureon.control.conductor")

try:
    import sentry_sdk
    _SENTRY = True
except ImportError:
    _SENTRY = False


# ══════════════════════════════════════════════════════════
# DECISION
# ══════════════════════════════════════════════════════════

class Action(str, Enum):
    CONTINUE       = "continue"
    LOG_AND_PASS   = "log_and_pass"
    BLOCK_REQUEST  = "block_request"
    TRIP_MODULE    = "trip_module"
    TRIP_GLOBAL    = "trip_global"
    SHUTDOWN       = "shutdown"


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
        self._timer       = None   # inyectado en Fase 2 vía wire_timer()
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
            "Conductor listo — Gates: %d | Breakers: %d | Registries: %d | Productos: %d",
            len(self._gates),
            len(self._breakers),
            len(self._registries),
            len(self._products),
        )

    # ══════════════════════════════════════════════════════
    # LLAMADA PROTEGIDA (v2 — sin cambios)
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
    # v3 — LECTURA DEL REGISTRY
    # ══════════════════════════════════════════════════════

    def scan_registry(self) -> List[Decision]:
        """
        Lee el EventRegistry y procesa todas las entradas en FAILED.
        Llamar periódicamente o desde un hook de after_request.

        Para cada entrada FAILED:
            1. Transiciona a PROCESSING
            2. Decide la acción (tabla Impact × Recovery)
            3. Ejecuta la acción (puede iniciar el Timer)
            4. Transiciona a FINISH

        Retorna la lista de decisiones tomadas en este scan.
        """
        failed_entries = EventRegistry.get_failed()
        decisions      = []

        for entry in failed_entries:
            # Construir una Alert sintética desde la entrada
            alert = Alert(
                code     = f"REGISTRY_FAILED_{entry.op_id.replace('_', '')}",
                message  = entry.error or f"Operación {entry.op_id} falló",
                impact   = self._infer_impact(entry),
                recovery = self._infer_recovery(entry),
                origin   = Origin.INTERNAL,
                module   = entry.module,
                context  = {
                    "event_id":   entry.event_id,
                    "op_id":      entry.op_id,
                    "gate":       entry.gate,
                    "duration_ms": round(entry.duration_ms, 2),
                },
            )

            # FAILED → PROCESSING
            EventRegistry.transition(
                entry.event_id, entry.op_id, EventState.PROCESSING
            )

            decision = self._decide(alert)
            self._execute_v3(decision, entry)
            decisions.append(decision)

            # PROCESSING → FINISH
            EventRegistry.transition(
                entry.event_id, entry.op_id, EventState.FINISH
            )

            log.info("[Conductor] scan: %s", decision)

        return decisions

    def _infer_impact(self, entry) -> Impact:
        """Infiere el impacto desde el gate y la operación."""
        from shared.control.operation_gates import OPERATIONS
        op = OPERATIONS.get(entry.op_id, {})
        gates = op.get("gates", [])

        if "BootGate" in gates:
            return Impact.GLOBAL
        if "DbGate" in gates and len(gates) == 1:
            return Impact.MODULE
        if "ModuleGate" in gates and len(gates) == 1:
            return Impact.MODULE
        return Impact.REQUEST

    def _infer_recovery(self, entry) -> Recovery:
        """Infiere la recuperabilidad desde la operación."""
        from shared.control.operation_gates import OPERATIONS
        op = OPERATIONS.get(entry.op_id, {})
        gates = op.get("gates", [])

        if "BootGate" in gates:
            return Recovery.FATAL
        if entry.gate in ("DbGate", "ModuleGate"):
            return Recovery.RUNTIME
        return Recovery.AUTO

    def _execute_v3(self, decision: Decision, entry) -> None:
        """
        Ejecuta la decisión del Conductor usando el Timer.
        Diferencia clave vs v2: el cierre del gate ocurre vía Timer,
        no directamente — espera que la cola drene.
        """
        action = decision.action
        alert  = decision.alert

        if action in (Action.CONTINUE, Action.LOG_AND_PASS, Action.BLOCK_REQUEST):
            return

        gate_name = entry.gate

        if action == Action.TRIP_MODULE:
            self._schedule_close(gate_name, entry.event_id, entry.op_id)
            self._notify_sentry(decision)

        elif action == Action.TRIP_GLOBAL:
            # Cerrar todos los gates vía Timer
            all_gates = {"HttpGate", "DbGate", "ModuleGate"}
            for gname in all_gates:
                self._schedule_close(gname, entry.event_id, entry.op_id)
            self._notify_sentry(decision)

        elif action == Action.SHUTDOWN:
            self._shutdown(alert)
            self._notify_sentry(decision)

    def _schedule_close(
        self,
        gate_name:    str,
        trigger_event: str,
        trigger_op:    str,
    ) -> None:
        """
        Pide al Timer que observe la cola del gate y lo cierre cuando drene.
        Si no hay Timer inyectado, cierra directamente (fallback v2).
        """
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
        """Cierra el gate directamente — fallback o forzado."""
        # Intentar en los gates concretos registrados
        gate = self._gates.get(gate_name)
        if gate and hasattr(gate, "close"):
            gate.close()
            return

        # Intentar en GateRegistry (feature flags)
        if gate_name in GateRegistry:
            GateRegistry.get(gate_name).set_enabled(False)

    # ══════════════════════════════════════════════════════
    # RECEPCIÓN DE ALERTAS (v2 — compatibilidad)
    # ══════════════════════════════════════════════════════

    def receive(self, alert: Alert) -> Decision:
        """
        Compatibilidad v2 — sigue funcionando igual.
        Adicionalmente registra el evento en EventRegistry.
        """
        log.warning("Conductor recibe: %s", alert)

        # Registrar en EventRegistry para trazabilidad
        event_id = generate_event_id()
        EventRegistry.record(
            event_id = event_id,
            op_id    = "OP000",       # op_id genérico para alertas v2
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

        # Marcar como FINISH en el Registry
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
    # EJECUCIÓN v2 (compatibilidad)
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
    # SENTRY
    # ══════════════════════════════════════════════════════

    def _notify_sentry(self, decision: Decision) -> None:
        if not _SENTRY:
            return
        if os.environ.get("FLASK_ENV") != "production":
            return
        try:
            alert = decision.alert
            level_map = {
                Action.TRIP_MODULE: "warning",
                Action.TRIP_GLOBAL: "error",
                Action.SHUTDOWN:    "fatal",
            }
            level = level_map.get(decision.action, "warning")

            registry_snap = EventRegistry.snapshot()

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
                scope.set_context("registry", registry_snap)
                scope.set_context("breakers", {
                    s.name: {"state": s.state.value, "failures": s.failure_count}
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
    # REGISTRO DE ALERTAS
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
    # CONSULTAS DE ESTADO
    # ══════════════════════════════════════════════════════

    def status(self) -> dict:
        return {
            "ready":         self._ready,
            "products":      self._products,
            "timer_watching": self._timer.watching() if self._timer else [],
            "registry":      EventRegistry.snapshot(),
            "breakers": {
                **{s.name: s.__dict__ for s in BreakerRegistry.all_snapshots()},
                **{n: b.to_dict() for n, b in self._breakers.items()},
            },
            "gates": {
                **{s.name: s.__dict__ for s in GateRegistry.all_snapshots()},
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
            "breakers": [s.__dict__ for s in BreakerRegistry.all_snapshots()],
            "gates":    [s.__dict__ for s in GateRegistry.all_snapshots()],
            "products": self._products,
            "registry": EventRegistry.snapshot(),
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