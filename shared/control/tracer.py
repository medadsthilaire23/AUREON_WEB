# shared/control/tracer.py
# ══════════════════════════════════════════════════════════════════════════════
# Trace ID con detección de ciclos — AUREON Shared Control
#
# Formato del ID
# ──────────────
#     Sin parent:   req_7f3a
#     Con parent:   req_7f3a.cb_4d1e
#     Con hops:     req_7f3a:oam1-rou2-mw3
#
# Detección de ciclos
# ───────────────────
#     Si un módulo aparece dos veces en el mismo trace → TraceLoopError.
#     El Conductor recibe una Alert(REQUEST / RUNTIME / INTERNAL).
#     El errorhandler global de app.py devuelve 508 Loop Detected.
#
# Integración — Fase 2 (app.py)
# ──────────────────────────────
#     from shared.control.tracer import Tracer, register_tracer
#     tracer = Tracer(conductor)
#     register_tracer(tracer)
#     app.before_request(tracer.begin)
#     app.after_request(tracer.finish)
#     app.register_error_handler(TraceLoopError, tracer.loop_error_handler)
#
# Uso desde cualquier módulo
# ──────────────────────────
#     from shared.control.tracer import checkpoint
#     checkpoint("oam")   # oauth_middleware
#     checkpoint("rou")   # routes
#     checkpoint("cbk")   # oauth callback
#     checkpoint("mw")    # auth_middleware
#     checkpoint("db")    # capa de base de datos
#
# Regla arquitectónica
# ────────────────────
#     Este módulo NO importa nada de products/.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from flask import g, jsonify, request as flask_request

from shared.control.alert import Alert, Impact, Recovery, Origin

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
    path:       tuple[str, ...]     # ("oam1", "rou2", "mw3")
    started_at: float               # perf_counter
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
    step:       int       = 0
    hops:       list[str] = field(default_factory=list)   # ["oam1", "rou2"]
    visited:    set[str]  = field(default_factory=set)    # {"oam", "rou"}
    had_loop:   bool      = False

    def next_hop(self, module_key: str) -> str:
        """
        Registra el módulo y devuelve el hop formateado.
        Lanza TraceLoopError si el módulo ya fue visitado.
        """
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

    Recibe el conductor directamente — usa conductor.receive(alert)
    en lugar de un handler genérico, igual que el resto del sistema.
    """

    MAX_HISTORY = 200   # ring buffer de traces completados

    def __init__(self, conductor) -> None:
        self._conductor = conductor
        self._lock      = threading.Lock()
        self._history:  list[TraceRecord] = []

    # ══════════════════════════════════════════════════════
    # HOOKS DE FLASK
    # ══════════════════════════════════════════════════════

    def begin(self) -> None:
        """
        before_request — inicializa el trace en flask.g.
        Si la request trae X-Trace-ID lo usa como parent_id
        para correlacionar flujos multi-request (OAuth, etc.).
        """
        parent_id = flask_request.headers.get("X-Trace-ID")
        trace_id  = self._new_id(parent_id)

        g._trace = _ActiveTrace(
            trace_id   = trace_id,
            parent_id  = parent_id,
            started_at = time.perf_counter(),
        )

        log.debug("[Tracer] begin  trace=%s  parent=%s  path=%s",
                  trace_id, parent_id, flask_request.path)

    def finish(self, response):
        """
        after_request — cierra el trace, lo archiva
        y adjunta X-Trace-ID al header de respuesta.
        """
        trace: Optional[_ActiveTrace] = getattr(g, "_trace", None)
        if trace is None:
            return response

        ended_at = time.perf_counter()
        record   = TraceRecord(
            trace_id   = trace.trace_id,
            parent_id  = trace.parent_id,
            path       = tuple(trace.hops),
            started_at = trace.started_at,
            ended_at   = ended_at,
            had_loop   = trace.had_loop,
            http_path  = flask_request.path,
            status     = response.status_code,
        )

        with self._lock:
            self._history.append(record)
            if len(self._history) > self.MAX_HISTORY:
                self._history.pop(0)

        response.headers["X-Trace-ID"] = trace.current_id

        log.debug(
            "[Tracer] finish  trace=%s  path=%s  status=%s  dur=%.1fms  hops=%s",
            trace.trace_id, flask_request.path,
            response.status_code, record.duration_ms,
            " → ".join(trace.hops) or "(sin checkpoints)",
        )

        return response

    def loop_error_handler(self, exc: TraceLoopError):
        """
        Errorhandler global para TraceLoopError.
        Registrar en app.py:
            app.register_error_handler(TraceLoopError, tracer.loop_error_handler)
        """
        log.error("[Tracer] 508  trace=%s  module=%s  path=%s",
                  exc.trace_id, exc.module_key, exc.path)
        return jsonify({
            "error":    "Loop detectado — request cancelada",
            "trace_id": exc.trace_id,
            "module":   exc.module_key,
            "path":     exc.path,
        }), 508

    # ══════════════════════════════════════════════════════
    # CHECKPOINT — registrar un módulo en el trace activo
    # ══════════════════════════════════════════════════════

    def checkpoint(self, module_key: str) -> str:
        """
        Registra que `module_key` está siendo visitado en este trace.
        Devuelve el hop formateado ("oam1", "rou2", ...).

        Si detecta loop:
            1. Emite Alert al Conductor (REQUEST / RUNTIME / INTERNAL)
            2. Lanza TraceLoopError → capturada por loop_error_handler → 508

        Claves de módulo estándar:
            "mw"   auth_middleware
            "oam"  oauth_middleware
            "rou"  routes principales
            "cbk"  oauth callback
            "psk"  passkey
            "db"   capa de base de datos
            "eml"  email
        """
        trace: Optional[_ActiveTrace] = getattr(g, "_trace", None)
        if trace is None:
            # Fuera de contexto Flask — no crashear
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
    # API DE CONSULTA
    # ══════════════════════════════════════════════════════

    def current_trace_id(self) -> Optional[str]:
        """Trace ID activo en esta request, o None."""
        trace: Optional[_ActiveTrace] = getattr(g, "_trace", None)
        return trace.current_id if trace else None

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return [r.to_dict() for r in self._history[-limit:]]

    def loops_detected(self) -> list[dict]:
        with self._lock:
            return [r.to_dict() for r in self._history if r.had_loop]

    def snapshot(self) -> dict:
        """Para /auth/control/status y /health."""
        with self._lock:
            total = len(self._history)
            loops = sum(1 for r in self._history if r.had_loop)
        return {
            "total_traced": total,
            "loops_detected": loops,
            "history_size": self.MAX_HISTORY,
        }

    # ══════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════

    @staticmethod
    def _new_id(parent_id: Optional[str]) -> str:
        """
        req_7f3a          — sin parent
        req_7f3a.cb_4d1e  — hijo de req_7f3a
        """
        short = secrets.token_hex(2)
        if parent_id:
            base = parent_id.split(".")[0]
            return f"{base}.cb_{short}"
        return f"req_{short}"


# ══════════════════════════════════════════════════════════
# SINGLETON Y ATAJO GLOBAL
# ══════════════════════════════════════════════════════════

_tracer_instance: Optional[Tracer] = None


def register_tracer(tracer: Tracer) -> None:
    """Llamar desde app.py en Fase 2 después de crear el Tracer."""
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