# shared/control/timer.py
# ══════════════════════════════════════════════════════════════════════════════
# Temporizador inteligente — AUREON Sistema de Control v3.0
#
# El Timer no es un timer de tiempo fijo.
# Es un observador de cola — espera que los eventos pendientes
# de un gate drenen antes de ordenar al Breaker que cierre.
#
# Problema que resuelve:
#     Si un gate se cierra mientras hay eventos en cola que lo necesitan,
#     esos eventos quedan corruptos — nunca llegan a FINISH.
#
# Solución:
#     Cuando un gate recibe un FAILED, el Timer:
#         1. Anota el gate y el ID del evento fallido
#         2. Observa el Registry — ¿cuántos eventos en PENDING
#            tienen ese gate en sus dependencias?
#         3. Espera hasta que esa cola llegue a cero
#         4. Cuando la cola está vacía → ordena al Breaker cerrar ese gate
#
# El cierre ocurre en el punto exacto donde salió el FAILED:
#     FAILED en DbGate → el Timer observa la cola de DbGate
#     FAILED en ModuleGate → el Timer observa la cola de ModuleGate
#
# Regla arquitectónica:
#     Este módulo NO importa nada de products/.
#     Recibe el Registry y el Breaker por inyección.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Optional

from shared.control.event_state import EventState

if TYPE_CHECKING:
    pass

log = logging.getLogger("aureon.control.timer")


# ══════════════════════════════════════════════════════════
# TIMER ENTRY — un gate bajo observación
# ══════════════════════════════════════════════════════════

@dataclass
class TimerEntry:
    """
    Representa un gate que el Timer está observando.

    gate_name       → nombre del gate a cerrar cuando la cola drene
    trigger_event   → ID del evento que causó el FAILED
    trigger_op      → ID de operación donde ocurrió el FAILED
    started_at      → cuándo empezó la observación
    on_drain        → callback a ejecutar cuando la cola llegue a cero
    max_wait_ms     → tiempo máximo de espera antes de cerrar de todas formas
                      (seguro contra colas que nunca drenan)
    """
    gate_name:     str
    trigger_event: str
    trigger_op:    str
    started_at:    datetime      = field(default_factory=datetime.now)
    on_drain:      Optional[Callable[[], None]] = None
    max_wait_ms:   int           = 30_000        # 30 segundos por defecto

    @property
    def age_ms(self) -> int:
        delta = datetime.now() - self.started_at
        return int(delta.total_seconds() * 1000)

    @property
    def timed_out(self) -> bool:
        return self.age_ms >= self.max_wait_ms


# ══════════════════════════════════════════════════════════
# TIMER
# ══════════════════════════════════════════════════════════

class Timer:
    """
    Temporizador inteligente basado en cola, no en tiempo.

    Se inicializa una vez en Fase 2 (wiring).
    Corre en un hilo de fondo — no bloquea el sistema.

    Uso:
        timer = Timer(registry=registry, poll_interval_ms=500)
        timer.start()

        # Cuando un gate recibe FAILED:
        timer.watch(
            gate_name="DbGate",
            trigger_event="20260404143022847",
            trigger_op="OP001_002",
            on_drain=lambda: breaker.close("DbGate"),
        )
    """

    def __init__(
        self,
        registry,                    # EventRegistry — inyectado en Fase 2
        poll_interval_ms: int = 500, # cada cuántos ms revisa la cola
    ):
        self._registry        = registry
        self._poll_interval   = poll_interval_ms / 1000.0  # a segundos
        self._entries:        dict[str, TimerEntry] = {}   # gate_name → entry
        self._lock            = threading.Lock()
        self._running         = False
        self._thread:         Optional[threading.Thread] = None

    # ══════════════════════════════════════════════════════
    # CICLO DE VIDA
    # ══════════════════════════════════════════════════════

    def start(self) -> None:
        """Inicia el hilo de observación en segundo plano."""
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop,
            name="aureon.timer",
            daemon=True,
        )
        self._thread.start()
        log.info("[Timer] iniciado (poll=%dms)", self._poll_interval * 1000)

    def stop(self) -> None:
        """Detiene el hilo de observación."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        log.info("[Timer] detenido")

    # ══════════════════════════════════════════════════════
    # API PÚBLICA
    # ══════════════════════════════════════════════════════

    def watch(
        self,
        gate_name:     str,
        trigger_event: str,
        trigger_op:    str,
        on_drain:      Callable[[], None],
        max_wait_ms:   int = 30_000,
    ) -> None:
        """
        Comienza a observar la cola de un gate.
        Cuando la cola llegue a cero, ejecuta on_drain.

        Si ya hay una entrada para ese gate, la sobreescribe
        (el nuevo FAILED es más reciente y más relevante).

        Args:
            gate_name     → gate a observar (ej. "DbGate")
            trigger_event → ID del evento que causó el FAILED
            trigger_op    → ID de operación del FAILED
            on_drain      → callback a ejecutar cuando cola = 0
            max_wait_ms   → tiempo máximo de espera (seguridad)
        """
        entry = TimerEntry(
            gate_name     = gate_name,
            trigger_event = trigger_event,
            trigger_op    = trigger_op,
            on_drain      = on_drain,
            max_wait_ms   = max_wait_ms,
        )
        with self._lock:
            self._entries[gate_name] = entry

        log.info(
            "[Timer] observando gate=%s trigger=%s op=%s max_wait=%dms",
            gate_name, trigger_event, trigger_op, max_wait_ms,
        )

    def cancel(self, gate_name: str) -> None:
        """
        Cancela la observación de un gate.
        Útil si el gate se recuperó antes de que la cola drenara.
        """
        with self._lock:
            removed = self._entries.pop(gate_name, None)
        if removed:
            log.info("[Timer] observación cancelada gate=%s", gate_name)

    def watching(self) -> list[str]:
        """Devuelve los nombres de los gates bajo observación."""
        with self._lock:
            return list(self._entries.keys())

    def snapshot(self) -> list[dict]:
        """Estado actual del Timer para healthcheck."""
        with self._lock:
            return [
                {
                    "gate":          e.gate_name,
                    "trigger_event": e.trigger_event,
                    "trigger_op":    e.trigger_op,
                    "age_ms":        e.age_ms,
                    "max_wait_ms":   e.max_wait_ms,
                    "timed_out":     e.timed_out,
                    "queue_size":    self._queue_size(e.gate_name),
                }
                for e in self._entries.values()
            ]

    # ══════════════════════════════════════════════════════
    # HILO DE FONDO
    # ══════════════════════════════════════════════════════

    def _loop(self) -> None:
        """
        Corre en segundo plano.
        Cada poll_interval revisa si la cola de cada gate observado
        llegó a cero o si el max_wait expiró.
        """
        while self._running:
            time.sleep(self._poll_interval)
            self._tick()

    def _tick(self) -> None:
        """
        Una iteración del loop.
        Procesa cada gate bajo observación.
        """
        with self._lock:
            entries = list(self._entries.items())

        drained = []

        for gate_name, entry in entries:
            queue_size = self._queue_size(gate_name)

            if queue_size == 0 or entry.timed_out:

                if entry.timed_out and queue_size > 0:
                    log.warning(
                        "[Timer] timeout gate=%s — cola no drenó (%d pendientes). "
                        "Cerrando de todas formas.",
                        gate_name, queue_size,
                    )
                else:
                    log.info(
                        "[Timer] cola drenada gate=%s age=%dms — ejecutando on_drain",
                        gate_name, entry.age_ms,
                    )

                drained.append(gate_name)

                if entry.on_drain:
                    try:
                        entry.on_drain()
                    except Exception as e:
                        log.error(
                            "[Timer] error en on_drain gate=%s: %s",
                            gate_name, e,
                        )

        with self._lock:
            for gate_name in drained:
                self._entries.pop(gate_name, None)

    # ══════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════

    def _queue_size(self, gate_name: str) -> int:
        """
        Cuenta cuántos eventos en PENDING o CREATE
        tienen ese gate en sus dependencias.

        Consulta el Registry — que es la fuente de verdad
        de todos los eventos activos.
        """
        try:
            return self._registry.count_active_for_gate(gate_name)
        except Exception as e:
            log.error("[Timer] error consultando registry: %s", e)
            return 0