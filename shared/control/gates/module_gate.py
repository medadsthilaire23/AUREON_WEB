# shared/control/gates/module_gate.py
# ══════════════════════════════════════════════════════════════════════════════
# MODULE GATE — AUREON Sistema de Control v3.1
#
# Cambios v3.1:
#   - call() acepta parent_event_id (desde g.event_id) y construye
#     el event_id hijo usando build_child_event_id().
#   - El evento hijo queda registrado como "20260404143022847_D_M"
#     cuando es llamado desde dentro de un DbGate, o "20260404143022847_M"
#     cuando es llamado directamente desde una ruta HTTP.
#   - Compatibilidad total hacia atrás: si no se pasa parent_event_id
#     genera uno nuevo.
#
# Contrato público:
#   gate.wire_registry(event_registry)
#   gate.record_pending(event_id, op_id)
#   gate.record_ok(event_id, op_id)
#   gate.record_fail(event_id, op_id, error="...")
#
# Uso con context manager:
#   from flask import g
#   with module_gate.call("OP003_002_001", parent_event_id=g.event_id) as child_id:
#       token = oauth.google.authorize_access_token()
#   # child_id = "20260404143022847_M"
#
# Regla arquitectónica:
#   Este módulo NO importa nada de products/.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Any, Generator, Optional, TYPE_CHECKING

from shared.control.gates.base  import GateBase
from shared.control.gate        import GateResult
from shared.control.event_id    import generate_event_id, build_child_event_id
from shared.control.event_state import EventState
from shared.control.alert       import Impact, Recovery, Origin

if TYPE_CHECKING:
    from shared.control.registries.base import EventRegistryType

log = logging.getLogger("aureon.control.gates.module")

_WARN_LATENCY_MS = 5_000


class ModuleGateClosedError(Exception):
    """Lanzada cuando el ModuleGate está CLOSED."""
    def __init__(self, name: str = "ModuleGate"):
        self.gate_name = name
        super().__init__(
            f"ModuleGate '{name}' CLOSED — servicio externo no disponible"
        )


class ModuleGate(GateBase):
    """
    Gate para llamadas a servicios externos.
    Una instancia compartida por toda la aplicación.

    OPEN   → servicios externos disponibles
    CLOSED → servicios externos no disponibles
    """

    def __init__(self, name: str = "ModuleGate"):
        super().__init__(name=name, description="Envuelve llamadas a servicios externos")
        self._registry: Optional["EventRegistryType"] = None
        self._enabled       = True
        self._lock          = threading.Lock()
        self._active_calls  = 0
        self._calls_lock    = threading.Lock()
        self._total_latency = 0.0
        self._call_count    = 0

    # ── Wiring ────────────────────────────────────────────────────────────────

    def wire_registry(self, registry: "EventRegistryType") -> None:
        """Inyecta el EventRegistry. Llamado desde wiring.py en Fase 2."""
        self._registry = registry
        log.info("[ModuleGate] EventRegistry inyectado")

    # ── record_* — contrato v3 ────────────────────────────────────────────────

    def record_pending(self, event_id: str, op_id: str) -> None:
        """Registra PENDING — llamada en tránsito."""
        if self._registry is None:
            return
        try:
            self._registry.transition(event_id, op_id, EventState.PENDING)
            with self._calls_lock:
                self._active_calls += 1
        except Exception as e:
            log.error("[ModuleGate] record_pending error: %s", e)

    def record_ok(self, event_id: str, op_id: str) -> None:
        """Registra FINISH — llamada completada exitosamente."""
        if self._registry is None:
            return
        try:
            self._registry.transition(event_id, op_id, EventState.FINISH)
            self._pass_count += 1
            with self._calls_lock:
                self._active_calls = max(0, self._active_calls - 1)
        except Exception as e:
            log.error("[ModuleGate] record_ok error: %s", e)

    def record_fail(self, event_id: str, op_id: str, error: str = "") -> None:
        """Registra FAILED — llamada fallida."""
        if self._registry is None:
            self._fail_count += 1
            log.error("[ModuleGate] FAILED op=%s error=%s (sin registry)", op_id, error)
            return
        try:
            self._registry.transition(event_id, op_id, EventState.FAILED, error=error)
            self._fail_count += 1
            with self._calls_lock:
                self._active_calls = max(0, self._active_calls - 1)
            log.error(
                "[ModuleGate] FAILED event=%s op=%s error=%s",
                event_id, op_id, error,
            )
        except Exception as e:
            log.error("[ModuleGate] record_fail error: %s", e)

    # ── Context manager ───────────────────────────────────────────────────────

    @contextmanager
    def call(
        self,
        op_id:           str,
        parent_event_id: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """
        Context manager que envuelve una llamada a servicio externo.

        v3.1: acepta parent_event_id para construir el event_id hijo
        con el camino acumulado.

        Uso:
            from flask import g

            # Con trazabilidad de camino (recomendado desde rutas):
            with module_gate.call("OP003_002_001", parent_event_id=g.event_id) as child_id:
                token = oauth.google.authorize_access_token()
            # child_id = "20260404143022847_M"

            # Anidado dentro de DbGate:
            # g.event_id ya es "20260404143022847_D"
            with module_gate.call("OP003_002_001", parent_event_id=g.event_id) as child_id:
                ...
            # child_id = "20260404143022847_D_M"

        Registra CREATE → PENDING al entrar.
        Al salir registra FINISH (ok) o FAILED si hay excepción.
        Lanza ModuleGateClosedError si el gate está CLOSED.
        """
        with self._lock:
            is_open = self._enabled

        if not is_open:
            self._fail_count += 1
            raise ModuleGateClosedError(self.name)

        # Construir event_id hijo si hay padre, o generar uno nuevo
        if parent_event_id is not None:
            event_id = build_child_event_id(parent_event_id, self.name)
        else:
            event_id = generate_event_id()

        started = time.perf_counter()

        # Registrar CREATE si es un evento nuevo (sin padre externo)
        # o directamente PENDING si el padre ya lo creó
        if self._registry is not None:
            try:
                self._registry.record(
                    event_id = event_id,
                    op_id    = op_id,
                    state    = EventState.CREATE,
                    gate     = self.name,
                )
            except Exception as e:
                log.error("[ModuleGate] call create error: %s", e)

        self.record_pending(event_id, op_id)

        log.debug(
            "[ModuleGate] BEGIN op=%s event=%s parent=%s",
            op_id, event_id, parent_event_id,
        )

        try:
            yield event_id

            elapsed_ms = (time.perf_counter() - started) * 1000
            self._total_latency += elapsed_ms
            self._call_count    += 1

            if elapsed_ms >= _WARN_LATENCY_MS:
                log.warning(
                    "[ModuleGate] latencia alta op=%s event=%s %.0fms",
                    op_id, event_id, elapsed_ms,
                )

            self.record_ok(event_id, op_id)
            log.debug(
                "[ModuleGate] OK op=%s event=%s %.0fms",
                op_id, event_id, elapsed_ms,
            )

        except ModuleGateClosedError:
            raise

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            self._total_latency += elapsed_ms
            self._call_count    += 1

            self.record_fail(event_id, op_id, error=str(exc))
            log.error(
                "[ModuleGate] FAILED op=%s event=%s %.0fms exc=%s",
                op_id, event_id, elapsed_ms, exc,
            )
            raise

    # ── Estado ────────────────────────────────────────────────────────────────

    def set_enabled(self, value: bool) -> None:
        with self._lock:
            self._enabled = value
        log.warning("[ModuleGate] set_enabled=%s", value)

    def close(self) -> None:
        self.set_enabled(False)

    def open(self) -> None:
        self.set_enabled(True)

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._enabled

    def count_active_calls(self) -> int:
        with self._calls_lock:
            return self._active_calls

    @property
    def avg_latency_ms(self) -> float:
        if self._call_count == 0:
            return 0.0
        return self._total_latency / self._call_count

    # ── GateBase.validate ─────────────────────────────────────────────────────

    def validate(self, value: Any, **kwargs) -> GateResult:
        with self._lock:
            is_open = self._enabled

        if not is_open:
            self._fail_count += 1
            alert = self._alert(
                code     = "MODULE_GATE_CLOSED",
                message  = f"ModuleGate '{self.name}' CLOSED — servicio externo no disponible",
                impact   = Impact.MODULE,
                recovery = Recovery.RUNTIME,
                origin   = Origin.EXTERNAL,
                context  = {"op_id": value},
            )
            return GateResult.fail(alert=alert, value=value)

        self._pass_count += 1
        return GateResult.ok(value=value)

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        with self._lock:
            enabled = self._enabled
        with self._calls_lock:
            active = self._active_calls
        return {
            "name":           self.name,
            "enabled":        enabled,
            "pass_count":     self._pass_count,
            "fail_count":     self._fail_count,
            "active_calls":   active,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
        }