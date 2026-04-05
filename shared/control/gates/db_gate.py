# shared/control/gates/db_gate.py
# ══════════════════════════════════════════════════════════════════════════════
# DB GATE — AUREON Sistema de Control v3.1
#
# Cambios v3.1:
#   - scan() acepta parent_event_id (desde g.event_id) y construye
#     el event_id hijo usando build_child_event_id().
#   - El evento hijo queda registrado como "20260404143022847_D"
#     en lugar de un timestamp nuevo desconectado.
#   - Compatibilidad total hacia atrás: si no se pasa parent_event_id
#     genera uno nuevo (comportamiento de boot/arranque).
#
# Contrato público:
#   gate.wire_registry(event_registry)
#   gate.record_ok(op_id)                       ← db.py (boot, sin event_id)
#   gate.record_fail(op_id, error="...")         ← db.py (boot, sin event_id)
#   gate.record_pending(event_id, op_id)         ← uso normal desde rutas
#   gate.record_ok(event_id, op_id)              ← uso normal desde rutas
#   gate.record_fail(event_id, op_id, ...)       ← uso normal desde rutas
#
# Uso normal desde rutas (context manager):
#   from flask import g
#   with db_gate.scan("OP001_002", parent_event_id=g.event_id) as child_id:
#       user = User.query.filter_by(email=email).first()
#   # child_id = "20260404143022847_D"
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

log = logging.getLogger("aureon.control.gates.db")

_LATENCY_WARNING_MS  =   500
_LATENCY_CRITICAL_MS = 2_000


class DbGateClosedError(Exception):
    """Lanzada cuando se intenta operar con DbGate CLOSED."""
    def __init__(self):
        super().__init__("DbGate CLOSED — operación de base de datos no disponible")


class DbGate(GateBase):
    """
    Gate de base de datos. Una sola instancia compartida.

    OPEN   → DB operativa, operaciones fluyen
    CLOSED → DB no disponible, nuevas operaciones bloqueadas
    """

    def __init__(self, name: str = "DbGate"):
        super().__init__(name=name, description="Envuelve toda operación de base de datos")
        self._registry: Optional["EventRegistryType"] = None
        self._enabled       = True
        self._lock          = threading.Lock()
        self._active_ops    = 0
        self._ops_lock      = threading.Lock()
        self._total_latency = 0.0
        self._op_count      = 0

    # ── Wiring ────────────────────────────────────────────────────────────────

    def wire_registry(self, registry: "EventRegistryType") -> None:
        """Inyecta el EventRegistry. Llamado desde wiring.py en Fase 2."""
        self._registry = registry
        log.info("[DbGate] EventRegistry inyectado")

    # ── record_* de boot — llamados desde db.py sin event_id ─────────────────

    def record_ok(self, op_id: str, event_id: Optional[str] = None) -> None:
        """
        Registra FINISH para un op_id.
        Sin event_id (boot) → genera uno interno.
        """
        eid = event_id or generate_event_id()
        self._pass_count += 1

        if self._registry is None:
            return
        try:
            self._registry.record(
                event_id = eid,
                op_id    = op_id,
                state    = EventState.FINISH,
                gate     = self.name,
            )
            log.debug("[DbGate] record_ok op=%s event=%s", op_id, eid)
        except Exception as e:
            log.error("[DbGate] record_ok error: %s", e)

    def record_fail(
        self,
        op_id:    str,
        error:    str = "",
        event_id: Optional[str] = None,
    ) -> None:
        """
        Registra FAILED para un op_id.
        Sin event_id (boot) → genera uno interno.
        """
        eid = event_id or generate_event_id()
        self._fail_count += 1

        if self._registry is None:
            log.error("[DbGate] record_fail op=%s error=%s (sin registry)", op_id, error)
            return
        try:
            self._registry.record(
                event_id = eid,
                op_id    = op_id,
                state    = EventState.FAILED,
                gate     = self.name,
                error    = error,
            )
            log.error("[DbGate] FAILED op=%s event=%s error=%s", op_id, eid, error)
        except Exception as e:
            log.error("[DbGate] record_fail error: %s", e)

    def record_pending(self, event_id: str, op_id: str) -> None:
        """Registra PENDING — op en tránsito (uso normal desde rutas)."""
        if self._registry is None:
            return
        try:
            self._registry.transition(event_id, op_id, EventState.PENDING)
        except Exception as e:
            log.error("[DbGate] record_pending error: %s", e)

    # ── Context manager — uso normal desde rutas ──────────────────────────────

    @contextmanager
    def scan(
        self,
        op_id:            str,
        parent_event_id:  Optional[str] = None,
    ) -> Generator[str, None, None]:
        """
        Envuelve una operación de DB con trazabilidad completa.

        v3.1: acepta parent_event_id para construir el event_id hijo
        con el camino acumulado.

        Uso:
            from flask import g

            # Con trazabilidad de camino (recomendado desde rutas):
            with db_gate.scan("OP001_002", parent_event_id=g.event_id) as child_id:
                user = User.query.filter_by(email=email).first()
            # child_id = "20260404143022847_D"

            # Sin parent (boot / contexto sin request):
            with db_gate.scan("OP009_001") as event_id:
                db.create_all()

        Registra CREATE → PENDING al entrar, FINISH al salir o FAILED si hay excepción.
        Lanza DbGateClosedError si el gate está CLOSED.
        """
        with self._lock:
            is_open = self._enabled

        if not is_open:
            raise DbGateClosedError()

        # Construir event_id hijo si hay padre, o generar uno nuevo
        if parent_event_id is not None:
            event_id = build_child_event_id(parent_event_id, self.name)
        else:
            event_id = generate_event_id()

        started = time.perf_counter()

        with self._ops_lock:
            self._active_ops += 1

        # Registrar CREATE → PENDING
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
                log.error("[DbGate] scan registry error: %s", e)

        log.debug(
            "[DbGate] BEGIN op=%s event=%s parent=%s",
            op_id, event_id, parent_event_id,
        )

        try:
            yield event_id

            elapsed_ms = (time.perf_counter() - started) * 1000
            self._pass_count    += 1
            self._total_latency += elapsed_ms
            self._op_count      += 1

            if elapsed_ms >= _LATENCY_CRITICAL_MS:
                log.error(
                    "[DbGate] latencia crítica op=%s event=%s %.0fms",
                    op_id, event_id, elapsed_ms,
                )
            elif elapsed_ms >= _LATENCY_WARNING_MS:
                log.warning(
                    "[DbGate] latencia alta op=%s event=%s %.0fms",
                    op_id, event_id, elapsed_ms,
                )
            else:
                log.debug(
                    "[DbGate] OK op=%s event=%s %.0fms",
                    op_id, event_id, elapsed_ms,
                )

            if self._registry is not None:
                try:
                    self._registry.transition(event_id, op_id, EventState.FINISH)
                except Exception as e:
                    log.error("[DbGate] scan finish error: %s", e)

        except DbGateClosedError:
            raise

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            self._fail_count    += 1
            self._total_latency += elapsed_ms
            self._op_count      += 1

            log.error(
                "[DbGate] FAILED op=%s event=%s %.0fms exc=%s",
                op_id, event_id, elapsed_ms, exc,
            )

            if self._registry is not None:
                try:
                    self._registry.transition(
                        event_id, op_id, EventState.FAILED, error=str(exc)
                    )
                except Exception as e:
                    log.error("[DbGate] scan fail-transition error: %s", e)

            raise

        finally:
            with self._ops_lock:
                self._active_ops = max(0, self._active_ops - 1)

    # ── Estado ────────────────────────────────────────────────────────────────

    def set_enabled(self, value: bool) -> None:
        with self._lock:
            self._enabled = value
        log.warning("[DbGate] set_enabled=%s", value)

    def close(self) -> None:
        self.set_enabled(False)

    def open(self) -> None:
        self.set_enabled(True)

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._enabled

    def count_active_ops(self) -> int:
        with self._ops_lock:
            return self._active_ops

    @property
    def avg_latency_ms(self) -> float:
        if self._op_count == 0:
            return 0.0
        return self._total_latency / self._op_count

    # ── GateBase.validate ─────────────────────────────────────────────────────

    def validate(self, value: Any, **kwargs) -> GateResult:
        with self._lock:
            is_open = self._enabled

        if not is_open:
            self._fail_count += 1
            alert = self._alert(
                code     = "DB_GATE_CLOSED",
                message  = "DbGate CLOSED — operación bloqueada",
                impact   = Impact.MODULE,
                recovery = Recovery.RUNTIME,
                origin   = Origin.SYSTEM,
                context  = {"op_id": value},
            )
            return GateResult.fail(alert=alert, value=value)

        self._pass_count += 1
        return GateResult.ok(value=value)

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        with self._lock:
            enabled = self._enabled
        with self._ops_lock:
            active = self._active_ops
        return {
            "name":           self.name,
            "enabled":        enabled,
            "pass_count":     self._pass_count,
            "fail_count":     self._fail_count,
            "active_ops":     active,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
        }