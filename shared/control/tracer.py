# shared/control/tracer.py — AUREON v4.0.1
# Fix: finish() ya NO bloquea la respuesta en anomalías XX de frontend.
# Solo registra en el EventRegistry y continúa.
# El 503 solo ocurre si HttpGate.scan() retorna allowed=False.

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from flask import g, jsonify, request as flask_request

from shared.control.alert      import Alert, Impact, Recovery, Origin
from shared.control.event_id   import (
    generate_event_id,
    evolve_id,
    get_root_id,
    get_path_aliases,
    gate_alias,
)
from shared.control.event_state import is_anomaly_op, get_alert_level
from shared.control.operation_gates import XX_OP_ID, _FRONTEND_FALLBACK_OP

log = logging.getLogger("aureon.tracer")


class TraceLoopError(RuntimeError):
    def __init__(self, trace_id: str, gate_name: str, path: list[str]) -> None:
        self.trace_id  = trace_id
        self.gate_name = gate_name
        self.path      = path
        self.prefix    = "GB"
        self.alert_level = "ROJA"
        super().__init__(
            f"Loop detectado en trace '{trace_id}': "
            f"gate '{gate_name}' ya visitado. Camino: {' → '.join(path)}"
        )


@dataclass(frozen=True)
class TraceRecord:
    trace_id:    str
    parent_root: Optional[str]
    path:        tuple[str, ...]
    final_id:    str
    started_at:  float
    ended_at:    float
    had_loop:    bool
    had_anomaly: bool
    http_path:   str
    status:      Optional[int]
    op_id:       Optional[str]

    @property
    def duration_ms(self) -> float:
        return (self.ended_at - self.started_at) * 1000

    def to_dict(self) -> dict:
        return {
            "trace_id":    self.trace_id,
            "parent_root": self.parent_root,
            "path":        list(self.path),
            "final_id":    self.final_id,
            "duration_ms": round(self.duration_ms, 2),
            "had_loop":    self.had_loop,
            "had_anomaly": self.had_anomaly,
            "http_path":   self.http_path,
            "status":      self.status,
            "op_id":       self.op_id,
        }


@dataclass
class _ActiveTrace:
    root_id:     str
    started_at:  float
    op_id:       Optional[str]       = None
    hops:        list[str]           = field(default_factory=list)
    visited:     set[str]            = field(default_factory=set)
    had_loop:    bool                = False
    had_anomaly: bool                = False
    parent_root: Optional[str]       = None

    def stamp(self, gate_name: str, current_event_id: str) -> str:
        if gate_name in self.visited:
            raise TraceLoopError(
                trace_id  = current_event_id,
                gate_name = gate_name,
                path      = list(self.hops),
            )
        evolved = evolve_id(current_event_id, gate_name)
        alias   = gate_alias(gate_name)
        self.hops.append(alias)
        self.visited.add(gate_name)
        return evolved

    @property
    def current_path(self) -> list[str]:
        return self.hops


class Tracer:
    MAX_HISTORY = 200

    def __init__(self, conductor) -> None:
        self._conductor = conductor
        self._http_gate = None
        self._lock      = threading.Lock()
        self._history:  list[TraceRecord] = []

    def wire_http_gate(self, http_gate) -> None:
        self._http_gate = http_gate
        log.info("[Tracer] HttpGate inyectado — eventos se cerrarán en finish()")

    def begin(self) -> None:
        raw_event_id  = getattr(g, "event_id", None)
        op_id         = getattr(g, "op_id",    None)
        parent_header = flask_request.headers.get("X-Trace-ID")

        if parent_header:
            parent_root = get_root_id(parent_header)
            event_id    = evolve_id(parent_root, "HttpGate")
        elif raw_event_id:
            event_id    = raw_event_id
            parent_root = None
        else:
            event_id    = generate_event_id()
            parent_root = None

        g._trace = _ActiveTrace(
            root_id     = get_root_id(event_id),
            started_at  = time.perf_counter(),
            op_id       = op_id,
            parent_root = parent_root,
        )
        g.event_id = event_id

    def finish(self, response):
        """
        after_request — cierra el trace.

        v4.0.1 fix:
          - XX en rutas de frontend (modulo=frontend/system) → record_ok()
            No son anomalías reales — son páginas sin registro en la tabla.
          - XX en rutas de API (/auth/, /lifebound/api/) → record_anomaly()
            Estas SÍ son descubrimientos reales que deben alertar.
          - La respuesta NUNCA se modifica aquí — el 503 solo viene
            de HttpGate.scan() cuando allowed=False.
        """
        trace: Optional[_ActiveTrace] = getattr(g, "_trace", None)
        if trace is None:
            return response

        ended_at = time.perf_counter()
        status   = response.status_code
        final_id = getattr(g, "event_id", trace.root_id)
        op_id    = trace.op_id

        if self._http_gate is not None:
            try:
                # Determinar si es anomalía real o frontend sin registrar
                is_real_anomaly = (
                    op_id is not None
                    and is_anomaly_op(op_id)
                    and op_id != _FRONTEND_FALLBACK_OP  # OP030 nunca es anomalía
                )

                if is_real_anomaly:
                    alert_level = get_alert_level(op_id) or "ROJA"
                    self._http_gate.record_anomaly(final_id, op_id, alert_level=alert_level)
                    trace.had_anomaly = True
                elif status >= 500:
                    self._http_gate.record_fail(final_id, op_id, error=f"HTTP {status}")
                else:
                    self._http_gate.record_ok(final_id, op_id)

            except Exception as e:
                log.error("[Tracer] finish — error cerrando evento: %s", e)

        record = TraceRecord(
            trace_id    = trace.root_id,
            parent_root = trace.parent_root,
            path        = tuple(trace.hops),
            final_id    = final_id,
            started_at  = trace.started_at,
            ended_at    = ended_at,
            had_loop    = trace.had_loop,
            had_anomaly = trace.had_anomaly,
            http_path   = flask_request.path,
            status      = status,
            op_id       = op_id,
        )

        with self._lock:
            self._history.append(record)
            if len(self._history) > self.MAX_HISTORY:
                self._history.pop(0)

        response.headers["X-Trace-ID"] = final_id

        log.debug(
            "[Tracer] finish  final_id=%s  path=%s  status=%s  dur=%.1fms",
            final_id,
            " → ".join(trace.hops) or "(sin gates)",
            status,
            record.duration_ms,
        )

        return response

    def loop_error_handler(self, exc: TraceLoopError):
        log.error("[Tracer] 508 GB  trace=%s  gate=%s  path=%s",
                  exc.trace_id, exc.gate_name, exc.path)
        return jsonify({
            "error":       "Loop de gates detectado — request cancelada",
            "prefix":      exc.prefix,
            "alert_level": exc.alert_level,
            "trace_id":    exc.trace_id,
            "gate":        exc.gate_name,
            "path":        exc.path,
        }), 508

    def checkpoint(self, gate_name: str) -> str:
        trace: Optional[_ActiveTrace] = getattr(g, "_trace", None)
        if trace is None:
            log.warning("[Tracer] checkpoint('%s') sin trace activo", gate_name)
            return gate_name

        current_id = getattr(g, "event_id", trace.root_id)

        try:
            evolved    = trace.stamp(gate_name, current_id)
            g.event_id = evolved
            log.debug("[Tracer] checkpoint  gate=%s  id=%s → %s", gate_name, current_id, evolved)
            return evolved

        except TraceLoopError as exc:
            trace.had_loop = True
            alert = Alert(
                code     = "GATE_LOOP_DETECTED",
                message  = str(exc),
                impact   = Impact.REQUEST,
                recovery = Recovery.RUNTIME,
                origin   = Origin.INTERNAL,
                module   = "tracer",
                context  = {
                    "prefix":      "GB",
                    "alert_level": "ROJA",
                    "trace_id":    current_id,
                    "gate_name":   gate_name,
                    "path":        list(trace.hops),
                },
            )
            self._conductor.receive(alert)
            raise

    def current_event_id(self) -> Optional[str]:
        return getattr(g, "event_id", None)

    def current_path(self) -> list[str]:
        trace: Optional[_ActiveTrace] = getattr(g, "_trace", None)
        return trace.hops if trace else []

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return [r.to_dict() for r in self._history[-limit:]]

    def loops_detected(self) -> list[dict]:
        with self._lock:
            return [r.to_dict() for r in self._history if r.had_loop]

    def anomalies_detected(self) -> list[dict]:
        with self._lock:
            return [r.to_dict() for r in self._history if r.had_anomaly]

    def snapshot(self) -> dict:
        with self._lock:
            total     = len(self._history)
            loops     = sum(1 for r in self._history if r.had_loop)
            anomalies = sum(1 for r in self._history if r.had_anomaly)
        return {
            "total_traced":       total,
            "loops_detected":     loops,
            "anomalies_detected": anomalies,
            "history_size":       self.MAX_HISTORY,
            "http_gate_wired":    self._http_gate is not None,
        }


_tracer_instance: Optional[Tracer] = None


def register_tracer(tracer: Tracer) -> None:
    global _tracer_instance
    _tracer_instance = tracer


def checkpoint(gate_name: str) -> str:
    if _tracer_instance is None:
        log.warning("[Tracer] checkpoint('%s') — tracer no registrado", gate_name)
        return gate_name
    return _tracer_instance.checkpoint(gate_name)