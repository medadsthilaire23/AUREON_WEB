# shared/control/breakers/base.py
# ══════════════════════════════════════════════════════════════════════════════
# CIRCUIT BREAKER BASE — AUREON Sistema de Control v3.0
#
# Cambios respecto a v2 (products/auth/breakers/base.py):
#
#   ELIMINADO  — activación directa por fallo consecutivo
#   ELIMINADO  — failure_threshold / recovery_timeout como parámetros de instancia
#   ELIMINADO  — estado HALF_OPEN (el Conductor decide cuándo reabrir)
#   MANTENIDO  — BreakerState, BreakerOpenError, BreakerSnapshot (interfaz pública)
#   MANTENIDO  — reset() y trip() para control manual y compatibilidad v2
#   NUEVO      — schedule_close(gate_name, event_id, op_id)
#   NUEVO      — force_close(gate_name, event_id, op_id)
#   NUEVO      — reopen(gate_name) — solo el Conductor puede reabrir
#
# Flujo de intervención normal:
#   Conductor._schedule_close(gate_name, event_id, op_id)
#       → BreakerBase.schedule_close(...)
#           → Timer.watch(gate_name, on_drain=_execute_close)
#               → _execute_close(gate_name, event_id, op_id, forced=False)
#                   → GateRegistry.get(gate_name).set_enabled(False)
#                   → EventRegistry.transition(event_id, op_id, FINISH)
#
# Flujo de emergencia (BootGate caído, timeout del Timer, señal OS):
#   BreakerBase.force_close(gate_name, event_id, op_id)
#       → _execute_close(..., forced=True)
#       → cierre inmediato sin esperar cola
#
# Regla arquitectónica:
#   Este módulo NO importa nada de products/.
#   Recibe EventRegistry y GateRegistry por inyección en __init__.
#   El Timer se inyecta en Fase 2 vía wire_timer().
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

from shared.control.event_state import EventState

if TYPE_CHECKING:
    from shared.control.registries.base import EventRegistryType, GateRegistryType
    from shared.control.timer import Timer

log = logging.getLogger("aureon.control.breaker")


# ══════════════════════════════════════════════════════════════════════════════
# ESTADOS
# ══════════════════════════════════════════════════════════════════════════════

class BreakerState(str, Enum):
    """
    Estados del Breaker en v3.

    STANDBY  → en espera, sin ninguna orden activa.
    WATCHING → el Timer está observando la cola de un gate.
               El gate sigue abierto — los eventos pendientes aún fluyen.
    CLOSED   → el gate fue cerrado por decisión del Conductor (cola drenada).
    FORCED   → cierre inmediato por emergencia (BootGate, timeout, señal OS).
    """
    STANDBY  = "standby"
    WATCHING = "watching"
    CLOSED   = "closed"
    FORCED   = "forced"


# ══════════════════════════════════════════════════════════════════════════════
# EXCEPCIÓN PÚBLICA — compatible con v2
# ══════════════════════════════════════════════════════════════════════════════

class BreakerOpenError(Exception):
    """
    Lanzada cuando se intenta ejecutar una operación cuyo gate está cerrado.
    El handler correspondiente debe traducirla en una respuesta 503.

    Compatible con v2 — mismo nombre, mismo contrato.
    En v3 ya no incluye retry_after (el Conductor decide cuándo reabrir).
    """
    def __init__(self, gate_name: str):
        self.gate_name = gate_name
        super().__init__(f"Gate '{gate_name}' cerrado — operación bloqueada por Breaker")


# ══════════════════════════════════════════════════════════════════════════════
# SNAPSHOT — compatible con v2
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class BreakerSnapshot:
    """
    Estado del Breaker en un momento dado.
    Compatible con v2 — mismo nombre, campos extendidos para v3.
    """
    name:            str
    state:           BreakerState
    gate_name:       Optional[str]    # gate bajo control activo
    trigger_event:   Optional[str]    # event_id que disparó la orden
    trigger_op:      Optional[str]    # op_id donde ocurrió el FAILED
    closed_at:       Optional[float]  # unix timestamp del cierre real
    forced:          bool             # True si fue un force_close


# ══════════════════════════════════════════════════════════════════════════════
# BREAKER BASE
# ══════════════════════════════════════════════════════════════════════════════

class BreakerBase:
    """
    Interruptor del sistema de control v3.

    Una instancia por módulo o gate — la granularidad la decide wiring.py.

    Responsabilidades:
      - Recibir la orden de cierre del Conductor (schedule_close).
      - Pasar al estado WATCHING y delegar el cierre al Timer.
      - Ejecutar el cierre cuando el Timer confirma que la cola drenó.
      - Ejecutar cierre inmediato en emergencias (force_close).
      - Registrar el cierre en GateRegistry y EventRegistry.
      - Permitir reapertura controlada por el Conductor (reopen).
    """

    def __init__(
        self,
        name:           str,
        event_registry: "EventRegistryType",
        gate_registry:  "GateRegistryType",
    ) -> None:
        self.name    = name
        self._events = event_registry
        self._gates  = gate_registry

        # Timer inyectado en Fase 2 vía wire_timer()
        self._timer: Optional["Timer"] = None

        # Estado interno
        self._state:         BreakerState   = BreakerState.STANDBY
        self._gate_name:     Optional[str]  = None
        self._trigger_event: Optional[str]  = None
        self._trigger_op:    Optional[str]  = None
        self._closed_at:     Optional[float] = None
        self._forced:        bool            = False

        self._lock = threading.Lock()

    # ══════════════════════════════════════════════════════
    # WIRING — inyección del Timer en Fase 2
    # ══════════════════════════════════════════════════════

    def wire_timer(self, timer: "Timer") -> None:
        """
        Inyecta el Timer. Llamado por el Conductor en Fase 2.
        Hasta que el Timer esté inyectado, schedule_close
        cae en force_close como fallback seguro.
        """
        self._timer = timer
        log.info("[Breaker:%s] Timer inyectado", self.name)

    # ══════════════════════════════════════════════════════
    # API PÚBLICA — llamada por el Conductor
    # ══════════════════════════════════════════════════════

    def schedule_close(
        self,
        gate_name:     str,
        trigger_event: str,
        trigger_op:    str,
        max_wait_ms:   int = 30_000,
    ) -> None:
        """
        Programa el cierre del gate cuando su cola drene.
        Llamado exclusivamente por Conductor._schedule_close().

        Si no hay Timer inyectado, cae en force_close (fallback v2).

        Args:
            gate_name     → gate a cerrar ("DbGate", "ModuleGate", etc.)
            trigger_event → event_id del evento que llegó a FAILED
            trigger_op    → op_id donde ocurrió el FAILED
            max_wait_ms   → tiempo máximo antes de force_close por timeout
        """
        if self._timer is None:
            log.warning(
                "[Breaker:%s] Sin Timer — force_close inmediato en gate='%s'",
                self.name, gate_name,
            )
            self.force_close(gate_name, trigger_event, trigger_op)
            return

        with self._lock:
            self._gate_name     = gate_name
            self._trigger_event = trigger_event
            self._trigger_op    = trigger_op
            self._forced        = False
            self._state         = BreakerState.WATCHING

        def _on_drain() -> None:
            self._execute_close(gate_name, trigger_event, trigger_op, forced=False)

        self._timer.watch(
            gate_name     = gate_name,
            trigger_event = trigger_event,
            trigger_op    = trigger_op,
            on_drain      = _on_drain,
            max_wait_ms   = max_wait_ms,
        )

        log.info(
            "[Breaker:%s] WATCHING gate='%s' trigger=%s op=%s max_wait=%dms",
            self.name, gate_name, trigger_event, trigger_op, max_wait_ms,
        )

    def force_close(
        self,
        gate_name:     str,
        trigger_event: str,
        trigger_op:    str,
    ) -> None:
        """
        Cierre inmediato del gate sin esperar al Timer.

        Usado en:
          - BootGate caído (el sistema no puede arrancar)
          - Timeout del Timer (cola nunca drenó en max_wait_ms)
          - Señal OS de shutdown
          - Fallback cuando no hay Timer inyectado

        Args:
            gate_name     → gate a cerrar
            trigger_event → event_id que originó la orden
            trigger_op    → op_id del FAILED
        """
        log.warning(
            "[Breaker:%s] force_close gate='%s' trigger=%s op=%s",
            self.name, gate_name, trigger_event, trigger_op,
        )
        self._execute_close(gate_name, trigger_event, trigger_op, forced=True)

    def reopen(self, gate_name: str) -> bool:
        """
        Reabre un gate cerrado por el Breaker.
        Solo el Conductor puede llamar a esto.

        Args:
            gate_name → gate a reabrir

        Retorna:
            True  → gate reabierto
            False → el Breaker no estaba en estado CLOSED/FORCED
        """
        with self._lock:
            if self._state not in (BreakerState.CLOSED, BreakerState.FORCED):
                log.warning(
                    "[Breaker:%s] reopen solicitado pero estado actual es '%s'",
                    self.name, self._state.value,
                )
                return False

            self._open_gate(gate_name)

            self._state         = BreakerState.STANDBY
            self._gate_name     = None
            self._trigger_event = None
            self._trigger_op    = None
            self._closed_at     = None
            self._forced        = False

        log.info("[Breaker:%s] gate='%s' reabierto", self.name, gate_name)
        return True

    # ══════════════════════════════════════════════════════
    # CONTROL MANUAL — compatibilidad v2
    # ══════════════════════════════════════════════════════

    def trip(self, gate_name: str = "") -> None:
        """
        Cierre manual con IDs sintéticos.
        Mantiene compatibilidad con conductor._trip_module() de v2.
        """
        target = gate_name or self._gate_name or "unknown"
        self.force_close(
            gate_name     = target,
            trigger_event = "MANUAL",
            trigger_op    = "MANUAL",
        )

    def reset(self) -> None:
        """
        Resetea el Breaker a STANDBY sin reabrir el gate.
        Para reabrir el gate usar reopen().
        Útil en tests y admin panel.
        """
        with self._lock:
            self._state         = BreakerState.STANDBY
            self._gate_name     = None
            self._trigger_event = None
            self._trigger_op    = None
            self._closed_at     = None
            self._forced        = False
        log.info("[Breaker:%s] reseteado a STANDBY", self.name)

    @property
    def is_open(self) -> bool:
        """
        True si el Breaker ha intervenido y el gate está cerrado.
        Nombre heredado de v2 — semántica: ¿el circuito está cortado?
        """
        with self._lock:
            return self._state in (BreakerState.CLOSED, BreakerState.FORCED)

    # ══════════════════════════════════════════════════════
    # SNAPSHOT Y SERIALIZACIÓN
    # ══════════════════════════════════════════════════════

    def snapshot(self) -> BreakerSnapshot:
        with self._lock:
            return BreakerSnapshot(
                name          = self.name,
                state         = self._state,
                gate_name     = self._gate_name,
                trigger_event = self._trigger_event,
                trigger_op    = self._trigger_op,
                closed_at     = self._closed_at,
                forced        = self._forced,
            )

    def to_dict(self) -> dict:
        s = self.snapshot()
        return {
            "name":          s.name,
            "state":         s.state.value,
            "gate_name":     s.gate_name,
            "trigger_event": s.trigger_event,
            "trigger_op":    s.trigger_op,
            "closed_at":     s.closed_at,
            "forced":        s.forced,
        }

    # ══════════════════════════════════════════════════════
    # EJECUCIÓN INTERNA
    # ══════════════════════════════════════════════════════

    def _execute_close(
        self,
        gate_name:     str,
        trigger_event: str,
        trigger_op:    str,
        forced:        bool,
    ) -> None:
        """
        Ejecuta el cierre real del gate.

        Orden de operaciones:
          1. Cerrar el gate en GateRegistry
          2. Transicionar el evento a FINISH en EventRegistry
             (el Conductor ya lo habrá llevado a PROCESSING antes)
          3. Actualizar estado interno del Breaker
          4. Loguear

        Llamado por:
          - _on_drain() → callback del Timer → forced=False
          - force_close()                    → forced=True
        """
        # 1. Cerrar el gate
        self._close_gate(gate_name)

        # 2. Marcar el evento como FINISH en el Registry
        self._events.transition(trigger_event, trigger_op, EventState.FINISH)

        # 3. Estado interno
        with self._lock:
            self._state     = BreakerState.FORCED if forced else BreakerState.CLOSED
            self._closed_at = time.time()
            self._forced    = forced

        label = "force_close" if forced else "scheduled_close"
        log.warning(
            "[Breaker:%s] %s — gate='%s' trigger=%s op=%s",
            self.name, label, gate_name, trigger_event, trigger_op,
        )

    def _close_gate(self, gate_name: str) -> None:
        """
        Cierra el gate en GateRegistry.
        Tolerante a gates no encontrados — loguea y continúa.
        """
        try:
            if gate_name not in self._gates:
                log.warning(
                    "[Breaker:%s] gate='%s' no encontrado en GateRegistry",
                    self.name, gate_name,
                )
                return
            gate = self._gates.get(gate_name)
            if hasattr(gate, "set_enabled"):
                gate.set_enabled(False)
            elif hasattr(gate, "close"):
                gate.close()
            else:
                log.warning(
                    "[Breaker:%s] gate='%s' no tiene set_enabled ni close",
                    self.name, gate_name,
                )
        except Exception as e:
            log.error(
                "[Breaker:%s] error cerrando gate='%s': %s",
                self.name, gate_name, e,
            )

    def _open_gate(self, gate_name: str) -> None:
        """
        Reabre el gate en GateRegistry.
        Llamado dentro del lock de reopen().
        """
        try:
            if gate_name not in self._gates:
                return
            gate = self._gates.get(gate_name)
            if hasattr(gate, "set_enabled"):
                gate.set_enabled(True)
            elif hasattr(gate, "open"):
                gate.open()
        except Exception as e:
            log.error(
                "[Breaker:%s] error reabriendo gate='%s': %s",
                self.name, gate_name, e,
            )

# Alias de compatibilidad — conductor.py importa CircuitBreaker
CircuitBreaker = BreakerBase
