# shared/control/gates/boot_gate.py
# ══════════════════════════════════════════════════════════════════════════════
# BOOT GATE — AUREON Sistema de Control v3.0
#
# Valida cada peldaño del arranque del sistema en app.py.
# Inicializado antes de Fase 1 — cierra cuando el sistema está listo.
#
# Contrato público:
#   gate.wire_registry(event_registry)
#   gate.mark_ready()          ← al final de Fase 2
#
#   with gate.step("OP010_001", "db_init") as event_id:
#       init_db(app)
#
# Estado:
#   OPEN   → arranque completó — sistema operativo
#   CLOSED → arranque en progreso o fallido
#
# El gate empieza CLOSED y solo pasa a OPEN cuando mark_ready() es llamado
# al final de Fase 2 sin pasos fallidos.
#
# Regla arquitectónica:
#   Este módulo NO importa nada de products/.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator, List, Optional, TYPE_CHECKING

from shared.control.gates.base  import GateBase
from shared.control.gate        import GateResult
from shared.control.event_id    import generate_event_id
from shared.control.event_state import EventState
from shared.control.alert       import Impact, Recovery, Origin

if TYPE_CHECKING:
    from shared.control.registries.base import EventRegistryType

log = logging.getLogger("aureon.control.gates.boot")


# ══════════════════════════════════════════════════════════════════════════════
# REGISTRO DE UN PASO
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class BootStep:
    op_id:      str
    name:       str
    event_id:   str
    state:      EventState
    started_at: float
    ended_at:   Optional[float] = None
    error:      Optional[str]   = None

    @property
    def duration_ms(self) -> float:
        end = self.ended_at or time.perf_counter()
        return (end - self.started_at) * 1000

    def to_dict(self) -> dict:
        return {
            "op_id":       self.op_id,
            "name":        self.name,
            "event_id":    self.event_id,
            "state":       self.state.value,
            "duration_ms": round(self.duration_ms, 2),
            "error":       self.error,
        }


# ══════════════════════════════════════════════════════════════════════════════
# BOOT GATE
# ══════════════════════════════════════════════════════════════════════════════

class BootGate(GateBase):
    """
    Valida cada peldaño del arranque del sistema.

    Empieza CLOSED — abre solo cuando mark_ready() confirma
    que todos los pasos completaron sin error.
    """

    def __init__(self, name: str = "BootGate"):
        super().__init__(name=name, description="Valida cada paso del arranque")
        self._registry: Optional["EventRegistryType"] = None
        # BootGate empieza cerrado — el sistema no está listo hasta Fase 2
        self._enabled    = False
        self._lock       = threading.Lock()
        self._steps:     List[BootStep] = []
        self._steps_lock = threading.Lock()

    # ── Wiring ────────────────────────────────────────────────────────────────

    def wire_registry(self, registry: "EventRegistryType") -> None:
        """Inyecta el EventRegistry. Llamado desde wiring.py en Fase 2."""
        self._registry = registry
        log.info("[BootGate] EventRegistry inyectado")

    # ── Context manager — uso principal ──────────────────────────────────────

    @contextmanager
    def step(self, op_id: str, name: str) -> Generator[str, None, None]:
        """
        Envuelve un paso del arranque con trazabilidad completa.

        Uso:
            with boot_gate.step("OP010_001", "db_init") as event_id:
                init_db(app)

            with boot_gate.step("OP010_002", "blueprints") as event_id:
                register_blueprints(app)

        Si el paso falla, el error queda registrado y mark_ready()
        no podrá abrir el gate.
        """
        event_id  = generate_event_id()
        boot_step = BootStep(
            op_id      = op_id,
            name       = name,
            event_id   = event_id,
            state      = EventState.CREATE,
            started_at = time.perf_counter(),
        )

        with self._steps_lock:
            self._steps.append(boot_step)

        # Registrar CREATE → PENDING en EventRegistry
        if self._registry is not None:
            try:
                self._registry.record(
                    event_id = event_id,
                    op_id    = op_id,
                    state    = EventState.CREATE,
                    gate     = self.name,
                )
                self._registry.transition(event_id, op_id, EventState.PENDING)
            except Exception as e:
                log.error("[BootGate] step registry error: %s", e)

        boot_step.state = EventState.PENDING
        log.info("[BootGate] step BEGIN op=%s name=%s", op_id, name)

        try:
            yield event_id

            boot_step.ended_at = time.perf_counter()
            boot_step.state    = EventState.FINISH
            self._pass_count  += 1

            if self._registry is not None:
                try:
                    self._registry.transition(event_id, op_id, EventState.FINISH)
                except Exception as e:
                    log.error("[BootGate] step finish error: %s", e)

            log.info(
                "[BootGate] step OK op=%s name=%s duration=%.0fms",
                op_id, name, boot_step.duration_ms,
            )

        except Exception as exc:
            boot_step.ended_at = time.perf_counter()
            boot_step.error    = str(exc)
            boot_step.state    = EventState.FAILED
            self._fail_count  += 1

            if self._registry is not None:
                try:
                    self._registry.transition(
                        event_id, op_id, EventState.FAILED, error=str(exc)
                    )
                except Exception as e:
                    log.error("[BootGate] step fail-transition error: %s", e)

            log.error(
                "[BootGate] step FAILED op=%s name=%s duration=%.0fms exc=%s",
                op_id, name, boot_step.duration_ms, exc,
            )
            raise

    # ── record_* — compatibilidad con el contrato v3 ─────────────────────────
    #
    # Permiten usar BootGate con el mismo patrón que los demás gates
    # cuando el op_id y event_id ya son conocidos.

    def record_pending(self, event_id: str, op_id: str) -> None:
        if self._registry is None:
            return
        try:
            self._registry.transition(event_id, op_id, EventState.PENDING)
        except Exception as e:
            log.error("[BootGate] record_pending error: %s", e)

    def record_ok(self, event_id: str, op_id: str) -> None:
        if self._registry is None:
            return
        try:
            self._registry.transition(event_id, op_id, EventState.FINISH)
            self._pass_count += 1
        except Exception as e:
            log.error("[BootGate] record_ok error: %s", e)

    def record_fail(self, event_id: str, op_id: str, error: str = "") -> None:
        if self._registry is None:
            self._fail_count += 1
            return
        try:
            self._registry.transition(event_id, op_id, EventState.FAILED, error=error)
            self._fail_count += 1
        except Exception as e:
            log.error("[BootGate] record_fail error: %s", e)

    # ── mark_ready — abre el gate al final de Fase 2 ─────────────────────────

    def mark_ready(self) -> None:
        """
        Abre el BootGate — sistema listo para recibir requests.
        Llamar al final de Fase 2 cuando todo el wiring completó.
        Si hay pasos fallidos, no abre y loguea el error.
        """
        failed = self._get_failed_steps()
        if failed:
            names = [s.name for s in failed]
            log.error(
                "[BootGate] mark_ready ignorado — pasos fallidos: %s", names
            )
            return

        total_ms = sum(
            s.duration_ms for s in self._steps
            if s.state == EventState.FINISH
        )

        with self._lock:
            self._enabled = True

        log.info(
            "[BootGate] OPEN — %d pasos completados en %.0fms total",
            self._pass_count, total_ms,
        )

    # ── Estado ────────────────────────────────────────────────────────────────

    def set_enabled(self, value: bool) -> None:
        with self._lock:
            self._enabled = value
        log.warning("[BootGate] set_enabled=%s", value)

    def close(self) -> None:
        self.set_enabled(False)

    def open(self) -> None:
        """Para BootGate usa mark_ready() en lugar de open()."""
        self.mark_ready()

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._enabled

    @property
    def is_ready(self) -> bool:
        """Alias de is_open — semántica más clara para el arranque."""
        return self.is_open

    # ── Consultas ─────────────────────────────────────────────────────────────

    def _get_failed_steps(self) -> List[BootStep]:
        with self._steps_lock:
            return [s for s in self._steps if s.state == EventState.FAILED]

    def all_steps(self) -> List[dict]:
        with self._steps_lock:
            return [s.to_dict() for s in self._steps]

    # ── GateBase.validate (requerido por la clase base) ───────────────────────

    def validate(self, value: Any, **kwargs) -> GateResult:
        failed = self._get_failed_steps()

        if failed:
            self._fail_count += 1
            names = [s.name for s in failed]
            alert = self._alert(
                code     = "BOOT_STEPS_FAILED",
                message  = f"Arranque incompleto — pasos fallidos: {names}",
                impact   = Impact.GLOBAL,
                recovery = Recovery.RESTART,
                origin   = Origin.SYSTEM,
                context  = {"failed_steps": [s.to_dict() for s in failed]},
            )
            return GateResult.fail(alert=alert, value=value)

        with self._lock:
            is_open = self._enabled

        if not is_open:
            self._fail_count += 1
            alert = self._alert(
                code     = "BOOT_NOT_READY",
                message  = "Sistema todavía no completó el arranque",
                impact   = Impact.GLOBAL,
                recovery = Recovery.RUNTIME,
                origin   = Origin.SYSTEM,
                context  = {"steps_completed": self._pass_count},
            )
            return GateResult.fail(alert=alert, value=value)

        self._pass_count += 1
        return GateResult.ok(value=value)

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        with self._steps_lock:
            steps = list(self._steps)
        with self._lock:
            enabled = self._enabled

        return {
            "name":            self.name,
            "enabled":         enabled,
            "steps_total":     len(steps),
            "steps_completed": sum(1 for s in steps if s.state == EventState.FINISH),
            "steps_failed":    sum(1 for s in steps if s.state == EventState.FAILED),
            "pass_count":      self._pass_count,
            "fail_count":      self._fail_count,
            "steps":           [s.to_dict() for s in steps],
        }