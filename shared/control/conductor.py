# shared/control/conductor.py
# ══════════════════════════════════════════════════════════════════════════════
# El Orquestador del sistema de control AUREON.
#
# Cambios respecto a la versión anterior:
#   - Integrado con BreakerRegistry y GateRegistry (subsistema de control)
#   - register_product() implementado (lo espera wiring.py)
#   - call() — ejecuta funciones protegidas por breaker + gate
#   - all_snapshots() — estado completo para healthcheck
#   - BaseGate / BaseBreaker / BaseRegistry mantenidos para compatibilidad
#     con componentes ya registrados vía register_gate / register_breaker
# ══════════════════════════════════════════════════════════════════════════════

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from shared.control.alert   import Alert, Impact, Recovery, Origin, Severity
from shared.control.gate    import BaseGate
from shared.control.breaker import BaseBreaker
from shared.control.registry import BaseRegistry

from shared.control.registries.base import BreakerRegistry, GateRegistry
from shared.control.breakers.base   import CircuitBreaker, BreakerOpenError, BreakerSnapshot
from shared.control.gates.base      import Gate, GateClosed, GateSnapshot

log = logging.getLogger("aureon.control.conductor")


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
    """
    Orquestador central del sistema de control AUREON.

    Dos modos de operación que conviven:

    Modo evento (original):
        Gate detecta problema → emite Alert → conductor.receive(alert)
        → decide acción → ordena al Breaker si aplica

    Modo llamada protegida (nuevo):
        conductor.call("breaker_name", "gate_name", func, *args, **kwargs)
        → comprueba gate → ejecuta bajo breaker → reporta resultado
    """

    def __init__(self):
        # Componentes legacy (BaseGate / BaseBreaker / BaseRegistry)
        self._gates:      Dict[str, BaseGate]     = {}
        self._breakers:   Dict[str, BaseBreaker]  = {}
        self._registries: Dict[str, BaseRegistry] = {}

        # Productos registrados desde wiring.py
        self._products:   Dict[str, dict]         = {}

        self._callbacks:  List[Callable[[Alert, Decision], None]] = []
        self._decisions:  List[Decision]          = []
        self._ready       = False

    # ══════════════════════════════════════════════════════
    # WIRING — registro de componentes (Fase 2)
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
        """
        Registra un producto y sus componentes de control.
        Llamado desde cada módulo en su wiring.py.

        meta esperado:
            {
                "status":   "active",
                "version":  "1.0",
                "healthy":  True,
                "breakers": ["google_oauth", "email_send", ...],
                "gates":    ["oauth_google", "registration", ...],
            }
        """
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
    # LLAMADA PROTEGIDA — modo nuevo
    # ══════════════════════════════════════════════════════

    def call(
        self,
        breaker_name: str,
        gate_name:    str,
        func:         Callable,
        *args:        Any,
        **kwargs:     Any,
    ) -> Any:
        """
        Ejecuta func(*args, **kwargs) protegida por gate + breaker.

        Orden:
            1. Comprueba el gate — si está cerrado lanza GateClosed
            2. Ejecuta bajo el breaker — si está abierto lanza BreakerOpenError
            3. Cualquier excepción de func se propaga normalmente

        Si gate_name o breaker_name no existen en sus registries,
        la llamada pasa sin protección (fail-open) y se loguea una
        advertencia — mejor que romper en producción por config faltante.

        Uso desde oauth.py:
            result = conductor.call(
                "google_oauth", "oauth_google",
                google_client.fetch_token, code=code,
            )
        """
        # 1. Gate
        gate: Gate | None = GateRegistry.get(gate_name) if gate_name in GateRegistry else None
        if gate is not None:
            gate.check()           # lanza GateClosed si está desactivado
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
    # RECEPCIÓN DE ALERTAS — modo original
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
        """
        ┌─────────────┬─────────────┬──────────────────────┐
        │ Impact      │ Recovery    │ Action               │
        ├─────────────┼─────────────┼──────────────────────┤
        │ *           │ AUTO        │ LOG_AND_PASS         │
        │ REQUEST     │ RUNTIME/+   │ BLOCK_REQUEST        │
        │ MODULE      │ RUNTIME/+   │ TRIP_MODULE          │
        │ GLOBAL      │ RUNTIME/+   │ TRIP_GLOBAL          │
        │ GLOBAL      │ FATAL       │ SHUTDOWN             │
        └─────────────┴─────────────┴──────────────────────┘
        """
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
            pass  # el Gate maneja BLOCK_REQUEST con GateResult.fail()

        elif action == Action.TRIP_MODULE:
            self._trip_module(alert)

        elif action == Action.TRIP_GLOBAL:
            self._trip_all(alert)

        elif action == Action.SHUTDOWN:
            self._shutdown(alert)

    def _trip_module(self, alert: Alert) -> None:
        """
        Intenta abrir el breaker del módulo.
        Busca primero en BreakerRegistry (nuevo), luego en _breakers (legacy).
        """
        module = alert.module

        # Nuevo subsistema
        if module in BreakerRegistry:
            BreakerRegistry.get(module).trip()
            return

        # Legacy
        breaker = self._breakers.get(module)
        if breaker:
            breaker.trip(alert)
        else:
            log.warning("Conductor: No hay breaker para módulo '%s'", module)

    def _trip_all(self, alert: Alert) -> None:
        log.critical("Conductor: TRIP GLOBAL — abriendo todos los breakers. [%s]", alert.code)

        # Nuevo subsistema
        for name in BreakerRegistry.names():
            BreakerRegistry.get(name).trip()

        # Legacy
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
        """Estado completo del sistema para healthcheck y auditoría."""
        return {
            "ready":      self._ready,
            "products":   self._products,
            "breakers":   {
                # nuevo subsistema
                **{s.name: s.__dict__ for s in BreakerRegistry.all_snapshots()},
                # legacy
                **{n: b.to_dict() for n, b in self._breakers.items()},
            },
            "gates": {
                # nuevo subsistema
                **{s.name: s.__dict__ for s in GateRegistry.all_snapshots()},
                # legacy
                **{n: str(g) for n, g in self._gates.items()},
            },
            "registries":    {n: r.snapshot() for n, r in self._registries.items()},
            "decisions":     len(self._decisions),
            "last_decision": (
                self._decisions[-1].to_dict() if self._decisions else None
            ),
        }

    def all_snapshots(self) -> dict:
        """
        Snapshot ligero para un endpoint /health o /admin/control.
        Solo incluye el nuevo subsistema (BreakerRegistry + GateRegistry).
        """
        return {
            "breakers": [s.__dict__ for s in BreakerRegistry.all_snapshots()],
            "gates":    [s.__dict__ for s in GateRegistry.all_snapshots()],
            "products": self._products,
        }

    def get_breaker(self, name: str) -> Optional[CircuitBreaker]:
        """Busca en BreakerRegistry primero, luego en legacy."""
        if name in BreakerRegistry:
            return BreakerRegistry.get(name)
        return self._breakers.get(name)  # type: ignore[return-value]

    def get_gate(self, name: str) -> Optional[Gate]:
        """Busca en GateRegistry primero, luego en legacy."""
        if name in GateRegistry:
            return GateRegistry.get(name)
        return self._gates.get(name)  # type: ignore[return-value]

    def reset_breaker(self, name: str) -> bool:
        """Cierra un breaker manualmente desde admin."""
        breaker = self.get_breaker(name)
        if not breaker:
            return False
        breaker.reset()
        log.info("Conductor: Breaker '%s' reseteado manualmente", name)
        return True

    def set_gate(self, name: str, enabled: bool) -> bool:
        """Activa o desactiva un gate manualmente desde admin."""
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