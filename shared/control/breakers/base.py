# products/auth/breakers/base.py
# ══════════════════════════════════════════════════════════════════════════════
# CIRCUIT BREAKER BASE — AUREON Auth
#
# Protege operaciones críticas (login, OAuth, WebAuthn) contra fallos en
# cascada. Implementa el patrón estándar de tres estados:
#
#   CLOSED   → operación fluye con normalidad; se cuentan fallos
#   OPEN     → operación bloqueada; se devuelve fallo rápido (fast-fail)
#   HALF_OPEN → prueba si el servicio recuperó; un éxito cierra, un fallo reabre
#
# Uso:
#   from products.auth.breakers.base import CircuitBreaker, BreakerOpenError
#
#   breaker = CircuitBreaker("google_oauth", failure_threshold=5, recovery_timeout=60)
#
#   try:
#       result = breaker.call(google_oauth_service.exchange_code, code=code)
#   except BreakerOpenError:
#       raise AuthError("SERVICE_UNAVAILABLE", "Servicio temporalmente no disponible")
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Estados ────────────────────────────────────────────────────────────────

class BreakerState(str, Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


# ── Excepción pública ──────────────────────────────────────────────────────

class BreakerOpenError(Exception):
    """
    Lanzada cuando el circuit breaker está OPEN y rechaza la llamada.
    El handler de auth debe traducirla a una respuesta 503 con retry-after.
    """
    def __init__(self, name: str, retry_after: float):
        self.name        = name
        self.retry_after = retry_after  # segundos hasta que pase a HALF_OPEN
        super().__init__(f"Circuit breaker '{name}' open — retry after {retry_after:.1f}s")


# ── Snapshot de estado (para registry / métricas) ──────────────────────────

@dataclass(frozen=True)
class BreakerSnapshot:
    name:             str
    state:            BreakerState
    failure_count:    int
    success_count:    int
    last_failure_at:  float | None   # unix timestamp
    opened_at:        float | None   # unix timestamp
    retry_after:      float | None   # segundos restantes hasta HALF_OPEN, o None


# ── Implementación ─────────────────────────────────────────────────────────

@dataclass
class CircuitBreaker:
    """
    Circuit breaker thread-safe para operaciones de auth.

    Parámetros
    ----------
    name                Identificador único (ej. "google_oauth", "passkey_verify")
    failure_threshold   Fallos consecutivos para abrir el circuito          (default 5)
    recovery_timeout    Segundos en OPEN antes de pasar a HALF_OPEN         (default 60)
    half_open_max_calls Llamadas permitidas en HALF_OPEN antes de decidir   (default 1)
    expected_exceptions Excepciones que cuentan como fallo; None = todas    (default None)
    """

    name:                 str
    failure_threshold:    int                     = 5
    recovery_timeout:     float                   = 60.0
    half_open_max_calls:  int                     = 1
    expected_exceptions:  tuple[type[Exception]]  | None = None

    # Estado interno — no inicializar desde fuera
    _state:             BreakerState = field(default=BreakerState.CLOSED, init=False, repr=False)
    _failure_count:     int          = field(default=0,     init=False, repr=False)
    _success_count:     int          = field(default=0,     init=False, repr=False)
    _half_open_calls:   int          = field(default=0,     init=False, repr=False)
    _last_failure_at:   float | None = field(default=None,  init=False, repr=False)
    _opened_at:         float | None = field(default=None,  init=False, repr=False)
    _lock:              threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    # ── Propiedad de estado ────────────────────────────────────────────────

    @property
    def state(self) -> BreakerState:
        with self._lock:
            return self._evaluate_state()

    # ── Llamada protegida ──────────────────────────────────────────────────

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        Ejecuta `func(*args, **kwargs)` bajo protección del breaker.

        - CLOSED    → ejecuta normalmente
        - OPEN      → lanza BreakerOpenError sin ejecutar
        - HALF_OPEN → ejecuta la llamada de prueba; éxito cierra, fallo reabre
        """
        with self._lock:
            state = self._evaluate_state()

            if state == BreakerState.OPEN:
                retry_after = self._seconds_until_half_open()
                raise BreakerOpenError(self.name, retry_after)

            if state == BreakerState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    raise BreakerOpenError(self.name, 0.0)
                self._half_open_calls += 1

        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            if self._counts_as_failure(exc):
                self._on_failure()
            raise
        else:
            self._on_success()
            return result

    # ── Snapshot público ───────────────────────────────────────────────────

    def snapshot(self) -> BreakerSnapshot:
        with self._lock:
            state = self._evaluate_state()
            retry = self._seconds_until_half_open() if state == BreakerState.OPEN else None
            return BreakerSnapshot(
                name            = self.name,
                state           = state,
                failure_count   = self._failure_count,
                success_count   = self._success_count,
                last_failure_at = self._last_failure_at,
                opened_at       = self._opened_at,
                retry_after     = retry,
            )

    # ── Control manual (útil en tests y admin panel) ───────────────────────

    def reset(self) -> None:
        """Fuerza el breaker a CLOSED y reinicia contadores."""
        with self._lock:
            self._transition_to_closed()
        logger.info("breaker.reset name=%s", self.name)

    def trip(self) -> None:
        """Fuerza el breaker a OPEN manualmente (ej. mantenimiento)."""
        with self._lock:
            self._transition_to_open()
        logger.warning("breaker.tripped_manually name=%s", self.name)

    # ── Internals ──────────────────────────────────────────────────────────

    def _evaluate_state(self) -> BreakerState:
        """
        Debe llamarse dentro de `_lock`.
        Promueve OPEN → HALF_OPEN si pasó el recovery_timeout.
        """
        if self._state == BreakerState.OPEN:
            if time.monotonic() - self._opened_at >= self.recovery_timeout:
                self._transition_to_half_open()
        return self._state

    def _counts_as_failure(self, exc: Exception) -> bool:
        if self.expected_exceptions is None:
            return True
        return isinstance(exc, self.expected_exceptions)

    def _on_failure(self) -> None:
        with self._lock:
            self._failure_count   += 1
            self._last_failure_at  = time.monotonic()

            if self._state == BreakerState.HALF_OPEN:
                logger.warning("breaker.half_open_failed name=%s", self.name)
                self._transition_to_open()

            elif self._failure_count >= self.failure_threshold:
                logger.error(
                    "breaker.opened name=%s failures=%d",
                    self.name, self._failure_count,
                )
                self._transition_to_open()

    def _on_success(self) -> None:
        with self._lock:
            self._success_count += 1

            if self._state == BreakerState.HALF_OPEN:
                logger.info("breaker.closed_after_recovery name=%s", self.name)
                self._transition_to_closed()

            elif self._state == BreakerState.CLOSED:
                # Reset del contador de fallos consecutivos en cada éxito
                self._failure_count = 0

    def _transition_to_open(self) -> None:
        self._state           = BreakerState.OPEN
        self._opened_at       = time.monotonic()
        self._half_open_calls = 0

    def _transition_to_half_open(self) -> None:
        self._state           = BreakerState.HALF_OPEN
        self._half_open_calls = 0
        logger.info("breaker.half_open name=%s", self.name)

    def _transition_to_closed(self) -> None:
        self._state         = BreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at     = None
        self._last_failure_at = None

    def _seconds_until_half_open(self) -> float:
        if self._opened_at is None:
            return 0.0
        elapsed = time.monotonic() - self._opened_at
        return max(0.0, self.recovery_timeout - elapsed)