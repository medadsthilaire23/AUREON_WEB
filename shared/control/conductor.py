# shared/control/conductor.py
# ══════════════════════════════════════════════════════════════════════════════
# El Orquestador del sistema de control AUREON.
#
# Cambios:
#   - _notify_sentry() — integración con Sentry para TRIP_MODULE,
#     TRIP_GLOBAL y SHUTDOWN. Solo en producción. Opcional si el SDK
#     no está instalado o SENTRY_DSN no está definido.
# ══════════════════════════════════════════════════════════════════════════════

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from shared.control.alert    import Alert, Impact, Recovery, Origin, Severity
from shared.control.gate     import BaseGate
from shared.control.breaker  import BaseBreaker
from shared.control.registry import BaseRegistry

from shared.control.registries.base import BreakerRegistry, GateRegistry
from shared.control.breakers.base   import CircuitBreaker, BreakerOpenError, BreakerSnapshot
from shared.control.gates.base      import Gate, GateClosed, GateSnapshot

log = logging.getLogger("aureon.control.conductor")

# Sentry — import opcional
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

    # ══════════════════════════════════════════════════════
    # WIRING
    # ══════════════════════════════════════════════════════

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
    # LLAMADA PROTEGIDA
    # ══════════════════════════════════════════════════════

    def call(
        self,
        breaker_name: str,
        gate_name:    str,
        func:         Callable,
        *args:        Any,
        **kwargs:     Any,
    ) -> Any:
        # 1. Gate
        gate: Gate | None = (
            GateRegistry.get(gate_name) if gate_name in GateRegistry else None
        )
        if gate is not None:
            gate.check()
        elif gate_name:
            log.warning("Conductor.call: gate '%s' no encontrado — fail-open", gate_name)

        # 2. Breaker
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
    # RECEPCIÓN DE ALERTAS
    # ══════════════════════════════════════════════════════

    def receive(self, alert: Alert) -> Decision:
        log.warning("Conductor recibe: %s", alert)

        self._record_alert(alert)
        decision = self._decide(alert)
        self._execute(decision)
        self._decisions.append(decision)

        for cb in self._callbacks:
            try:
                cb(alert, decision)
            except Exception as e:
                log.error("Conductor callback error: %s", e)

        log.info("Conductor decide: %s", decision)
        return decision

    # ══════════════════════════════════════════════════════
    # TABLA DE DECISIÓN
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
    # EJECUCIÓN DE DECISIONES
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
    # SENTRY — notificación para acciones críticas
    # ══════════════════════════════════════════════════════

    def _notify_sentry(self, decision: Decision) -> None:
        """
        Envía un evento a Sentry cuando el Conductor toma una decisión
        crítica (TRIP_MODULE, TRIP_GLOBAL, SHUTDOWN).

        Solo se ejecuta en producción — en desarrollo solo se loguea.
        No lanza excepciones — si Sentry falla, el sistema continúa.

        Formato en Sentry:
            Mensaje:  [AUREON] TRIP_MODULE — google_oauth
            Contexto: alert, breakers activos, gates activos, productos
        """
        if not _SENTRY:
            return

        # Solo en producción
        if os.environ.get("FLASK_ENV") != "production":
            log.debug("[Sentry] skipped — not production (action=%s)", decision.action.value)
            return

        try:
            alert = decision.alert

            # Nivel Sentry según acción
            level_map = {
                Action.TRIP_MODULE: "warning",
                Action.TRIP_GLOBAL: "error",
                Action.SHUTDOWN:    "fatal",
            }
            level = level_map.get(decision.action, "warning")

            # Snapshot de breakers para contexto
            breaker_context = {
                s.name: {
                    "state":    s.state.value,
                    "failures": s.failure_count,
                }
                for s in BreakerRegistry.all_snapshots()
            }

            # Snapshot de gates para contexto
            gate_context = {
                s.name: s.enabled
                for s in GateRegistry.all_snapshots()
            }

            with sentry_sdk.push_scope() as scope:
                # Tags — aparecen en el dashboard y permiten filtrar
                scope.set_tag("aureon.action",   decision.action.value)
                scope.set_tag("aureon.module",   alert.module or "global")
                scope.set_tag("aureon.impact",   alert.impact.value)
                scope.set_tag("aureon.recovery", alert.recovery.value)
                scope.set_tag("aureon.severity", alert.severity.value)
                scope.set_tag("aureon.origin",   alert.origin.value)

                # Contexto completo — visible al abrir el evento en Sentry
                scope.set_context("alert", {
                    "code":     alert.code,
                    "message":  alert.message,
                    "module":   alert.module,
                    "alert_id": alert.alert_id,
                })
                scope.set_context("breakers", breaker_context)
                scope.set_context("gates",    gate_context)
                scope.set_context("products", self._products)

                scope.set_level(level)

                sentry_sdk.capture_message(
                    f"[AUREON] {decision.action.value.upper()} — "
                    f"{alert.module or 'global'} | {alert.code}"
                )

            log.info(
                "[Sentry] evento enviado — action=%s module=%s level=%s",
                decision.action.value, alert.module, level,
            )

        except Exception as e:
            # Sentry no puede romper el sistema de control
            log.error("[Sentry] error al notificar: %s", e)

    # ══════════════════════════════════════════════════════
    # REGISTRO
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
            "ready":      self._ready,
            "products":   self._products,
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