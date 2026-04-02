"""
shared/control/breaker.py
=========================
Contrato base universal para todos los Breakers del sistema AUREON.

Un Breaker es un disyuntor — corta el flujo de un módulo o del
sistema completo cuando el Conductor lo ordena, sin romper
los módulos que siguen funcionando correctamente.

Estados del Breaker:
    CLOSED    — funcionando normal, tráfico pasa
    OPEN      — cortado, tráfico bloqueado, devuelve error controlado
    HALF_OPEN — en prueba, permite una operación para verificar
                si el módulo se recuperó

Regla arquitectónica:
    breaker.py NO importa nada de products/.
    El Conductor es el único que puede ordenar OPEN/CLOSE.
    Los módulos solo consultan si el breaker está abierto.

Jerarquía:
    BaseBreaker  (este archivo)       — contrato universal
        └── BreakerBase (breakers/base.py) — lógica común
                ├── ModuleBreaker     — corta un producto específico
                └── GlobalBreaker    — corta el sistema completo
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Callable, Optional

from shared.control.alert import Alert, Severity

log = logging.getLogger("aureon.control.breaker")


# ══════════════════════════════════════════════════════════
# BREAKER STATE — los tres estados del disyuntor
# ══════════════════════════════════════════════════════════

class BreakerState(str, Enum):
    CLOSED    = "closed"     # Normal — tráfico pasa
    OPEN      = "open"       # Cortado — tráfico bloqueado
    HALF_OPEN = "half_open"  # En prueba — una operación permitida


# ══════════════════════════════════════════════════════════
# BREAKER RESULT — lo que devuelve toda consulta al breaker
# ══════════════════════════════════════════════════════════

class BreakerResult:
    """
    Resultado de consultar si un Breaker permite el paso.

    allowed  → True si la operación puede continuar
    state    → estado actual del breaker
    reason   → mensaje explicativo si fue bloqueado
    """

    def __init__(
        self,
        allowed: bool,
        state: BreakerState,
        reason: Optional[str] = None,
    ):
        self.allowed = allowed
        self.state   = state
        self.reason  = reason

    @classmethod
    def allow(cls, state: BreakerState) -> "BreakerResult":
        """Operación permitida."""
        return cls(allowed=True, state=state)

    @classmethod
    def block(cls, state: BreakerState, reason: str) -> "BreakerResult":
        """Operación bloqueada."""
        return cls(allowed=False, state=state, reason=reason)

    def __bool__(self) -> bool:
        return self.allowed

    def __str__(self) -> str:
        if self.allowed:
            return f"BreakerResult(ALLOW | state={self.state.value})"
        return f"BreakerResult(BLOCK | state={self.state.value} | {self.reason})"


# ══════════════════════════════════════════════════════════
# BASE BREAKER — contrato universal
# ══════════════════════════════════════════════════════════

class BaseBreaker(ABC):
    """
    Contrato universal para todos los Breakers de AUREON.

    Define qué ES un Breaker — su identidad y sus transiciones
    de estado. No define qué corta ni cómo — eso es trabajo
    de los hijos en breakers/base.py y sus implementaciones.

    Propiedades que todo Breaker debe tener:
        name            — identificador único del breaker
        state           — estado actual (CLOSED/OPEN/HALF_OPEN)
        recovery_timeout — segundos antes de pasar a HALF_OPEN
        opened_at       — cuándo fue abierto (None si CLOSED)
        last_alert      — última alerta que lo abrió

    Métodos que todo Breaker debe implementar:
        trip()          — abrir el breaker (cortar)
        reset()         — cerrar el breaker (restaurar)
        probe()         — intentar HALF_OPEN
        is_allowed()    — consultar si el tráfico puede pasar
    """

    # Tiempo por defecto antes de intentar recuperación (segundos)
    DEFAULT_RECOVERY_TIMEOUT = 30

    def __init__(
        self,
        name: str,
        recovery_timeout: int = DEFAULT_RECOVERY_TIMEOUT,
    ):
        self.name             = name
        self.state            = BreakerState.CLOSED
        self.recovery_timeout = recovery_timeout
        self.opened_at:   Optional[datetime] = None
        self.closed_at:   Optional[datetime] = None
        self.last_alert:  Optional[Alert]    = None
        self._on_trip:    Optional[Callable] = None
        self._on_reset:   Optional[Callable] = None

    # ── Identidad ─────────────────────────────────────────

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} state={self.state.value}>"

    # ── Callbacks ─────────────────────────────────────────

    def on_trip(self, callback: Callable[["BaseBreaker", Alert], None]) -> None:
        """Callback ejecutado cuando el breaker se abre."""
        self._on_trip = callback

    def on_reset(self, callback: Callable[["BaseBreaker"], None]) -> None:
        """Callback ejecutado cuando el breaker se cierra."""
        self._on_reset = callback

    # ── Transiciones de estado ────────────────────────────

    @abstractmethod
    def trip(self, alert: Alert) -> None:
        """
        Abre el breaker — corta el flujo.
        Llamado por el Conductor cuando recibe una alerta
        de severidad suficiente.

        Debe:
            1. Cambiar state a OPEN
            2. Registrar opened_at y last_alert
            3. Ejecutar la lógica de corte específica
            4. Llamar _on_trip si existe
        """
        ...

    @abstractmethod
    def reset(self) -> None:
        """
        Cierra el breaker — restaura el flujo.
        Llamado por el Conductor cuando el módulo se recuperó.

        Debe:
            1. Cambiar state a CLOSED
            2. Registrar closed_at
            3. Ejecutar la lógica de restauración específica
            4. Llamar _on_reset si existe
        """
        ...

    @abstractmethod
    def probe(self) -> bool:
        """
        Intenta pasar a HALF_OPEN para probar si el módulo
        se recuperó. Retorna True si la prueba fue exitosa
        y el breaker puede cerrarse.
        """
        ...

    # ── Consulta de estado ────────────────────────────────

    def is_allowed(self) -> BreakerResult:
        """
        Punto de entrada principal para módulos que quieren
        saber si pueden operar.

        Lógica:
            CLOSED    → permite siempre
            OPEN      → verifica timeout, si expiró intenta HALF_OPEN
            HALF_OPEN → permite una operación de prueba
        """
        if self.state == BreakerState.CLOSED:
            return BreakerResult.allow(BreakerState.CLOSED)

        if self.state == BreakerState.OPEN:
            if self._timeout_expired():
                log.info(
                    "Breaker[%s] timeout expirado — intentando HALF_OPEN",
                    self.name,
                )
                self.state = BreakerState.HALF_OPEN
                return BreakerResult.allow(BreakerState.HALF_OPEN)

            return BreakerResult.block(
                state=BreakerState.OPEN,
                reason=f"Breaker '{self.name}' abierto desde {self.opened_at}. "
                       f"Recuperación en {self._seconds_remaining()}s.",
            )

        # HALF_OPEN — permite pasar para probar
        return BreakerResult.allow(BreakerState.HALF_OPEN)

    # ── Estado público ────────────────────────────────────

    @property
    def is_open(self) -> bool:
        return self.state == BreakerState.OPEN

    @property
    def is_closed(self) -> bool:
        return self.state == BreakerState.CLOSED

    @property
    def is_probing(self) -> bool:
        return self.state == BreakerState.HALF_OPEN

    def to_dict(self) -> dict:
        return {
            "name":             self.name,
            "state":            self.state.value,
            "recovery_timeout": self.recovery_timeout,
            "opened_at":        self.opened_at.isoformat() if self.opened_at else None,
            "closed_at":        self.closed_at.isoformat() if self.closed_at else None,
            "last_alert":       self.last_alert.to_dict() if self.last_alert else None,
            "seconds_remaining": self._seconds_remaining(),
        }

    # ── Helpers internos ──────────────────────────────────

    def _timeout_expired(self) -> bool:
        """Verifica si el timeout de recuperación expiró."""
        if not self.opened_at:
            return True
        elapsed = datetime.now(timezone.utc) - self.opened_at
        return elapsed >= timedelta(seconds=self.recovery_timeout)

    def _seconds_remaining(self) -> int:
        """Segundos restantes hasta intentar recuperación."""
        if not self.opened_at or self.state == BreakerState.CLOSED:
            return 0
        elapsed = datetime.now(timezone.utc) - self.opened_at
        remaining = self.recovery_timeout - elapsed.total_seconds()
        return max(0, int(remaining))

    # ── Helpers para hijos ────────────────────────────────

    def _do_trip(self, alert: Alert) -> None:
        """Lógica común de apertura — llamar desde trip() en hijos."""
        self.state      = BreakerState.OPEN
        self.opened_at  = datetime.now(timezone.utc)
        self.closed_at  = None
        self.last_alert = alert
        log.warning(
            "Breaker[%s] ABIERTO por alerta: %s",
            self.name, alert.code,
        )
        if self._on_trip:
            self._on_trip(self, alert)

    def _do_reset(self) -> None:
        """Lógica común de cierre — llamar desde reset() en hijos."""
        self.state     = BreakerState.CLOSED
        self.closed_at = datetime.now(timezone.utc)
        log.info("Breaker[%s] CERRADO — flujo restaurado", self.name)
        if self._on_reset:
            self._on_reset(self)