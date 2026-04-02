# shared/control/registries/base.py
# ══════════════════════════════════════════════════════════════════════════════
# REGISTRY BASE — AUREON Shared Control
#
# Catálogo central de CircuitBreakers y Gates. Permite que conductor.py
# y cualquier parte del sistema localice, cree o inspeccione instancias
# por nombre sin acoplamiento directo.
#
# Características:
#   - Registro lazy: la instancia se crea la primera vez que se solicita
#   - Thread-safe: un único lock protege el dict interno
#   - Snapshots: exporta el estado de todos los componentes para métricas
#   - Separado por tipo: BreakerRegistry / GateRegistry comparten esta base
#
# Uso:
#   from shared.control.registries.base import BreakerRegistry
#
#   breaker = BreakerRegistry.get("google_oauth")          # crea si no existe
#   breaker = BreakerRegistry.get("passkey_verify",        # con config custom
#                                  failure_threshold=3,
#                                  recovery_timeout=30)
#   snapshots = BreakerRegistry.all_snapshots()            # para métricas
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import threading
from typing import Any, Generic, TypeVar

from shared.control.breakers.base import CircuitBreaker, BreakerSnapshot
from shared.control.gates.base     import Gate, GateSnapshot

T = TypeVar("T")


# ── Base genérica ──────────────────────────────────────────────────────────

class _Registry(Generic[T]):
    """
    Registro thread-safe de instancias identificadas por nombre.
    No instanciar directamente — usar BreakerRegistry o GateRegistry.
    """

    def __init__(self, factory: type[T]) -> None:
        self._factory  = factory
        self._store:   dict[str, T] = {}
        self._lock     = threading.Lock()

    def get(self, name: str, **kwargs: Any) -> T:
        """
        Devuelve la instancia registrada bajo `name`.
        Si no existe, la crea con `factory(name=name, **kwargs)`.
        kwargs solo se aplican en la creación — llamadas posteriores
        con el mismo nombre los ignoran.
        """
        with self._lock:
            if name not in self._store:
                self._store[name] = self._factory(name=name, **kwargs)
            return self._store[name]

    def register(self, instance: T) -> T:
        """
        Registra una instancia ya construida.
        Lanza ValueError si el nombre ya está en uso.
        """
        name = instance.name  # type: ignore[attr-defined]
        with self._lock:
            if name in self._store:
                raise ValueError(f"'{name}' ya está registrado en {type(self).__name__}")
            self._store[name] = instance
        return instance

    def remove(self, name: str) -> None:
        """Elimina la entrada (útil en tests para limpiar estado)."""
        with self._lock:
            self._store.pop(name, None)

    def clear(self) -> None:
        """Vacía el registro completo."""
        with self._lock:
            self._store.clear()

    def names(self) -> list[str]:
        with self._lock:
            return list(self._store.keys())

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self._store

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


# ── BreakerRegistry ────────────────────────────────────────────────────────

class _BreakerRegistry(_Registry[CircuitBreaker]):

    def __init__(self) -> None:
        super().__init__(CircuitBreaker)

    def all_snapshots(self) -> list[BreakerSnapshot]:
        """Estado actual de todos los breakers — para métricas y admin."""
        with self._lock:
            instances = list(self._store.values())
        return [b.snapshot() for b in instances]

    def reset_all(self) -> None:
        """Fuerza todos los breakers a CLOSED. Usar con cuidado."""
        with self._lock:
            instances = list(self._store.values())
        for b in instances:
            b.reset()


# ── GateRegistry ──────────────────────────────────────────────────────────

class _GateRegistry(_Registry[Gate]):

    def __init__(self) -> None:
        super().__init__(Gate)

    def all_snapshots(self) -> list[GateSnapshot]:
        """Estado actual de todos los gates — para métricas y admin."""
        with self._lock:
            instances = list(self._store.values())
        return [g.snapshot() for g in instances]


# ── Singletons públicos ────────────────────────────────────────────────────

BreakerRegistry = _BreakerRegistry()
GateRegistry    = _GateRegistry()