# shared/control/gates/http_gate.py
# ══════════════════════════════════════════════════════════════════════════════
# HTTP GATE — AUREON v4.0
#
# Cambios v4.0:
#   - resolve_op_id() → usa operation_gates.resolve_op_id() (loader dinámico)
#     NUNCA cae a "OP001" — rutas desconocidas reciben "XX" (Discovery)
#   - record_anomaly() → nuevo método que el Tracer.finish() llama cuando
#     is_anomaly_op(op_id) es True. Transiciona el evento a ANOMALY.
#   - _resolve_module() → usa resolve_module() del loader dinámico
#   - ScanResult incluye module — el middleware lo expone en g.module
#
# Contrato con Tracer:
#   scan()           → CREATE en registry, retorna ScanResult
#   record_ok()      → FINISH (request exitoso)
#   record_fail()    → FAILED (HTTP 5xx sin prefijo de anomalía)
#   record_anomaly() → ANOMALY (prefijo XX/AD/FL/GB/FA/TM/SA/UR)
#
# Regla arquitectónica:
#   Este módulo NO importa nada de products/.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

from shared.control.gates.base  import GateBase
from shared.control.gate        import GateResult
from shared.control.event_id    import generate_event_id
from shared.control.event_state import EventState, is_anomaly_op, get_alert_level
from shared.control.alert       import Impact, Recovery, Origin
from shared.control.operation_gates import (
    resolve_op_id  as _dyn_resolve_op_id,
    resolve_module as _dyn_resolve_module,
    XX_OP_ID,
)

if TYPE_CHECKING:
    from shared.control.registries.base import EventRegistryType

log = logging.getLogger("aureon.control.gates.http")


@dataclass(frozen=True)
class ScanResult:
    """
    Resultado del escaneo de una request HTTP.

    event_id — ID generado (17 dígitos base)
    allowed  — True si el gate está OPEN
    op_id    — operación detectada ("OP001", "XX", etc.)
    module   — módulo ("auth", "lifebound", "discovery", etc.)
    """
    event_id: str
    allowed:  bool
    op_id:    str
    module:   str = "auth"


class HttpGate(GateBase):
    """
    Gate de entrada HTTP — AUREON v4.0.
    Una sola instancia para toda la app, creada en wiring.py.
    """

    def __init__(self, name: str = "HttpGate"):
        super().__init__(name=name, description="Punto de entrada HTTP")
        self._registry: Optional["EventRegistryType"] = None
        self._enabled   = True
        self._lock      = threading.Lock()

        self._skip_registry = (
            "/static/",
            "/favicon",
            "/health",
            "/lifebound/static/",
            "/auth/static/",
        )

    def wire_registry(self, registry: "EventRegistryType") -> None:
        self._registry = registry
        log.info("[HttpGate] EventRegistry inyectado")

    # ── Escaneo ───────────────────────────────────────────────────────────────

    def scan(self, request) -> ScanResult:
        """
        Escanea una request HTTP entrante.

        v4.0: resolve_op_id() usa el loader dinámico.
        Rutas no registradas → op_id = "XX" → module = "discovery".
        Nunca lanza excepción — fail-open.
        """
        event_id = generate_event_id()

        try:
            method = request.method
            path   = request.path

            op_id  = _dyn_resolve_op_id(method, path)
            module = _dyn_resolve_module(op_id)

            with self._lock:
                is_open = self._enabled

            if not is_open:
                log.warning(
                    "[HttpGate] CLOSED — bloqueando %s %s event=%s",
                    method, path, event_id,
                )
                return ScanResult(
                    event_id = event_id,
                    allowed  = False,
                    op_id    = op_id,
                    module   = module,
                )

            skip = any(path.startswith(p) for p in self._skip_registry)
            if self._registry is not None and not skip:
                self._registry.record(
                    event_id = event_id,
                    op_id    = op_id,
                    state    = EventState.CREATE,
                    gate     = self.name,
                )

            self._pass_count += 1

            if op_id == XX_OP_ID:
                log.warning(
                    "[HttpGate] XX Discovery — %s %s event=%s",
                    method, path, event_id,
                )
            else:
                log.debug(
                    "[HttpGate] CREATE event=%s op=%s module=%s %s %s",
                    event_id, op_id, module, method, path,
                )

            return ScanResult(event_id=event_id, allowed=True, op_id=op_id, module=module)

        except Exception as e:
            log.error("[HttpGate] error en scan: %s", e)
            return ScanResult(event_id=event_id, allowed=True, op_id=XX_OP_ID, module="discovery")

    # ── Cierre de eventos — llamados por Tracer.finish() ──────────────────────

    def record_ok(self, event_id: str, op_id: Optional[str]) -> None:
        """FINISH — request exitoso (status < 500, sin prefijo de anomalía)."""
        if self._registry is None or op_id is None:
            return
        try:
            self._registry.transition(event_id, op_id, EventState.FINISH)
        except Exception as e:
            log.error("[HttpGate] record_ok error: %s", e)

    def record_fail(self, event_id: str, op_id: Optional[str], error: str = "") -> None:
        """FAILED — error técnico (HTTP 5xx sin prefijo de anomalía)."""
        if self._registry is None or op_id is None:
            return
        try:
            self._registry.transition(event_id, op_id, EventState.FAILED, error=error)
            self._fail_count += 1
            log.warning("[HttpGate] FAILED event=%s op=%s error=%s", event_id, op_id, error)
        except Exception as e:
            log.error("[HttpGate] record_fail error: %s", e)

    def record_anomaly(
        self,
        event_id:    str,
        op_id:       Optional[str],
        alert_level: str = "ROJA",
    ) -> None:
        """
        ANOMALY — prefijo de crisis detectado por el Tracer.

        Llamado cuando is_anomaly_op(op_id) es True — independiente del HTTP status.
        Un SecurityGate puede disparar ANOMALY con status 200.

        Prefijos que disparan ANOMALY:
            XX → Discovery    AD → Admin       UR → Usuario
            FL → Falso Loc    GB → Gate Bloq.  FA → Fallo Técnico
            TM → Timeout      SA → Saturación
        """
        if self._registry is None or op_id is None:
            return
        try:
            self._registry.transition(
                event_id,
                op_id,
                EventState.ANOMALY,
                error=f"Prefijo de anomalía detectado — alerta {alert_level}",
            )
            self._fail_count += 1
            log.warning(
                "[HttpGate] ANOMALY event=%s op=%s alert=%s",
                event_id, op_id, alert_level,
            )
        except Exception as e:
            log.error("[HttpGate] record_anomaly error: %s", e)

    # ── Control del gate ──────────────────────────────────────────────────────

    def set_enabled(self, value: bool) -> None:
        with self._lock:
            self._enabled = value
        log.warning("[HttpGate] set_enabled=%s", value)

    def close(self) -> None:
        self.set_enabled(False)

    def open(self) -> None:
        self.set_enabled(True)

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._enabled

    def validate(self, value: Any, **kwargs) -> GateResult:
        with self._lock:
            is_open = self._enabled
        if not is_open:
            self._fail_count += 1
            alert = self._alert(
                code     = "HTTP_GATE_CLOSED",
                message  = "HttpGate CLOSED — sistema HTTP no disponible",
                impact   = Impact.GLOBAL,
                recovery = Recovery.RUNTIME,
                origin   = Origin.SYSTEM,
                context  = {},
            )
            return GateResult.fail(alert=alert, value=value)
        self._pass_count += 1
        return GateResult.ok(value=value)

    def snapshot(self) -> dict:
        with self._lock:
            enabled = self._enabled
        return {
            "name":           self.name,
            "enabled":        enabled,
            "pass_count":     self._pass_count,
            "fail_count":     self._fail_count,
            "avg_latency_ms": None,
            "active_ops":     None,
        }