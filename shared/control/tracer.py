# shared/control/tracer.py
# ══════════════════════════════════════════════════════════════════════════════
# Tracer — AUREON Sistema de Control v3.1
#
# Cambios v3.1:
#   - finish() ahora llama http_gate.record_ok() para transicionar
#     el evento de CREATE → FINISH en el EventRegistry.
#     Sin esto los eventos se acumulan en CREATE indefinidamente.
#   - wire_http_gate() inyecta el HttpGate desde wiring.py (Fase 2).
#   - Si el status de respuesta >= 500, llama record_fail() en lugar de record_ok().
#
# Cambios v3.0 (conservados):
#   - trace_id unificado con event_id del HttpGate
#   - Si HttpGate no generó event_id genera uno propio con generate_event_id()
#   - X-Trace-ID en respuesta expone el event_id
#   - Parent tracking via X-Trace-ID para flujos OAuth multi-step
#
# Regla arquitectónica:
#   Este módulo NO importa nada de products/.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from flask import g, jsonify, request as flask_request

from shared.control.alert    import Alert, Impact, Recovery, Origin
from shared.control.event_id import generate_event_id

log = logging.getLogger("aureon.tracer")


# ══════════════════════════════════════════════════════════
# EXCEPCIÓN PÚBLICA
# ══════════════════════════════════════════════════════════

class TraceLoopError(RuntimeError):
    """
    Lanzada cuando un módulo aparece dos veces en el mismo trace.
    Capturada por el errorhandler global → respuesta 508.
    """
    def __init__(self, trace_id: str, module_key: str, path: list[str]) -> None:
        self.trace_id   = trace_id
        self.module_key = module_key
        self.path       = path
        super().__init__(
            f"Loop detectado en trace '{trace_id}': "
            f"módulo '{module_key}' ya visitado. Camino: {' → '.join(path)}"
        )


# ══════════════════════════════════════════════════════════
# TRACE RECORD — snapshot inmutable de un trace completado
# ══════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TraceRecord:
    trace_id:   str
    parent_id:  Optional[str]
    path:       tuple[str, ...]
    started_at: float
    ended_at:   float
    had_loop:   bool
    http_path:  str
    status:     Optional[int]

    @property
    def duration_ms(self) -> float:
        return (self.ended_at - self.started_at) * 1000

    def to_dict(self) -> dict:
        return {
            "trace_id":    self.trace_id,
            "parent_id":   self.parent_id,
            "path":        list(self.path),
            "duration_ms": round(self.duration_ms, 2),
            "had_loop":    self.had_loop,
            "http_path":   self.http_path,
            "status":      self.status,
        }


# ══════════════════════════════════════════════════════════
# ACTIVE TRACE — estado mutable, vive en flask.g
# ══════════════════════════════════════════════════════════

@dataclass
class _ActiveTrace:
    trace_id:   str
    parent_id:  Optional[str]
    started_at: float
    op_id:      str = "OP001"   # op_id detectado por HttpGate.scan()
    step:       int       = 0
    hops:       list[str] = field(default_factory=list)
    visited:    set[str]  = field(default_factory=set)
    had_loop:   bool      = False

    def next_hop(self, module_key: str) -> str:
        if module_key in self.visited:
            raise TraceLoopError(self.trace_id, module_key, list(self.hops))
        self.step += 1
        hop = f"{module_key}{self.step}"
        self.hops.append(hop)
        self.visited.add(module_key)
        return hop

    @property
    def current_id(self) -> str:
        if not self.hops:
            return self.trace_id
        return f"{self.trace_id}:{'-'.join(self.hops)}"


# ══════════════════════════════════════════════════════════
# TRACER
# ══════════════════════════════════════════════════════════

class Tracer:
    """
    Instancia única creada en Fase 2 (app.py).

    El trace_id es el event_id generado por HttpGate.scan() en before_request.
    Si HttpGate no lo generó (ruta sin scan, health, static), genera uno propio
    con el mismo formato para mantener consistencia en los logs.

    Flujo por request:
        HttpGate.scan()  → g.event_id = "20260404143022847"  (CREATE en registry)
        Tracer.begin()   → g._trace.trace_id = g.event_id
        checkpoint("mw") → g._trace.hops = ["mw1"]
        Tracer.finish()  → http_gate.record_ok() → FINISH en registry
                         → X-Trace-ID: 20260404143022847:mw1
    """

    MAX_HISTORY = 200

    def __init__(self, conductor) -> None:
        self._conductor  = conductor
        self._http_gate  = None   # inyectado en Fase 2 via wire_http_gate()
        self._lock       = threading.Lock()
        self._history:   list[TraceRecord] = []

    # ══════════════════════════════════════════════════════
    # WIRING
    # ══════════════════════════════════════════════════════

    def wire_http_gate(self, http_gate) -> None:
        """
        Inyecta el HttpGate para que finish() pueda llamar
        record_ok() / record_fail() y cerrar el evento en el registry.
        Llamado desde wiring.py en Fase 2, después de wire_auth().
        """
        self._http_gate = http_gate
        log.info("[Tracer] HttpGate inyectado — eventos se cerrarán en finish()")

    # ══════════════════════════════════════════════════════
    # HOOKS DE FLASK
    # ══════════════════════════════════════════════════════

    def begin(self) -> None:
        """
        before_request — inicializa el trace en flask.g.

        Reutiliza g.event_id si HttpGate ya lo generó.
        Si no existe (ruta estática, health), genera uno propio.
        """
        event_id  = getattr(g, "event_id", None) or generate_event_id()
        op_id     = getattr(g, "op_id",    None) or "OP001"
        parent_id = flask_request.headers.get("X-Trace-ID")

        if parent_id:
            trace_id = f"{parent_id}.cb_{event_id[-4:]}"
        else:
            trace_id = event_id

        g._trace = _ActiveTrace(
            trace_id   = trace_id,
            parent_id  = parent_id,
            started_at = time.perf_counter(),
            op_id      = op_id,
        )

        g.event_id = trace_id

        log.debug(
            "[Tracer] begin  trace=%s  parent=%s  path=%s",
            trace_id, parent_id, flask_request.path,
        )

    def finish(self, response):
        """
        after_request — cierra el trace, transiciona el evento en el registry
        a FINISH (o FAILED si status >= 500), y adjunta X-Trace-ID.

        FIX v3.1: sin esta llamada los eventos quedan en CREATE para siempre.
        """
        trace: Optional[_ActiveTrace] = getattr(g, "_trace", None)
        if trace is None:
            return response

        ended_at = time.perf_counter()
        status   = response.status_code

        # ── Cerrar el evento en EventRegistry ────────────────────────────
        if self._http_gate is not None:
            event_id = trace.trace_id
            op_id    = trace.op_id
            try:
                if status >= 500:
                    self._http_gate.record_fail(
                        event_id, op_id,
                        error=f"HTTP {status}"
                    )
                else:
                    self._http_gate.record_ok(event_id, op_id)
            except Exception as e:
                log.error("[Tracer] finish — error cerrando evento: %s", e)

        # ── Archivar el TraceRecord ───────────────────────────────────────
        record = TraceRecord(
            trace_id   = trace.trace_id,
            parent_id  = trace.parent_id,
            path       = tuple(trace.hops),
            started_at = trace.started_at,
            ended_at   = ended_at,
            had_loop   = trace.had_loop,
            http_path  = flask_request.path,
            status     = status,
        )

        with self._lock:
            self._history.append(record)
            if len(self._history) > self.MAX_HISTORY:
                self._history.pop(0)

        response.headers["X-Trace-ID"] = trace.current_id

        log.debug(
            "[Tracer] finish  trace=%s  path=%s  status=%s  dur=%.1fms  hops=%s",
            trace.trace_id, flask_request.path,
            status, record.duration_ms,
            " → ".join(trace.hops) or "(sin checkpoints)",
        )

        return response

    def loop_error_handler(self, exc: TraceLoopError):
        """Errorhandler global para TraceLoopError → 508."""
        log.error(
            "[Tracer] 508  trace=%s  module=%s  path=%s",
            exc.trace_id, exc.module_key, exc.path,
        )
        return jsonify({
            "error":    "Loop detectado — request cancelada",
            "trace_id": exc.trace_id,
            "module":   exc.module_key,
            "path":     exc.path,
        }), 508

    # ══════════════════════════════════════════════════════
    # CHECKPOINT
    # ══════════════════════════════════════════════════════

    def checkpoint(self, module_key: str) -> str:
        """
        Registra que `module_key` está siendo visitado en este trace.
        Devuelve el hop formateado ("mw1", "rou2", ...).

        Claves estándar:
            "mw"   auth_middleware
            "oam"  oauth_middleware
            "rou"  routes
            "cbk"  oauth callback
            "psk"  passkey
            "db"   capa de base de datos
            "eml"  email
        """
        trace: Optional[_ActiveTrace] = getattr(g, "_trace", None)
        if trace is None:
            return f"{module_key}?"

        try:
            hop = trace.next_hop(module_key)
            log.debug("[Tracer] checkpoint  hop=%s  trace=%s", hop, trace.trace_id)
            return hop

        except TraceLoopError as exc:
            trace.had_loop = True

            alert = Alert(
                code     = "TRACE_LOOP_DETECTED",
                message  = str(exc),
                impact   = Impact.REQUEST,
                recovery = Recovery.RUNTIME,
                origin   = Origin.INTERNAL,
                module   = "tracer",
                context  = {
                    "trace_id":   trace.trace_id,
                    "module_key": module_key,
                    "path":       list(trace.hops),
                },
            )
            self._conductor.receive(alert)
            raise

    # ══════════════════════════════════════════════════════
    # CONSULTAS
    # ══════════════════════════════════════════════════════

    def current_trace_id(self) -> Optional[str]:
        trace: Optional[_ActiveTrace] = getattr(g, "_trace", None)
        return trace.current_id if trace else None

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return [r.to_dict() for r in self._history[-limit:]]

    def loops_detected(self) -> list[dict]:
        with self._lock:
            return [r.to_dict() for r in self._history if r.had_loop]

    def snapshot(self) -> dict:
        with self._lock:
            total = len(self._history)
            loops = sum(1 for r in self._history if r.had_loop)
        return {
            "total_traced":   total,
            "loops_detected": loops,
            "history_size":   self.MAX_HISTORY,
        }


# ══════════════════════════════════════════════════════════
# SINGLETON Y ATAJO GLOBAL
# ══════════════════════════════════════════════════════════

_tracer_instance: Optional[Tracer] = None


def register_tracer(tracer: Tracer) -> None:
    global _tracer_instance
    _tracer_instance = tracer


def checkpoint(module_key: str) -> str:
    """
    Atajo global — uso desde cualquier módulo:

        from shared.control.tracer import checkpoint
        checkpoint("mw")
    """
    if _tracer_instance is None:
        return f"{module_key}?"
    return _tracer_instance.checkpoint(module_key)