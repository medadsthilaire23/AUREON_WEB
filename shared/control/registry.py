"""
shared/control/registry.py
==========================
Contrato base universal para todos los Registries del sistema AUREON.

Un Registry es la memoria del sistema de control — almacena
el historial de alertas, el estado de los breakers, y el
registro de gates activos. Es la fuente de verdad para
auditoría en tiempo real.

Regla arquitectónica:
    registry.py NO importa nada de products/.
    Solo almacena y consulta — nunca decide ni actúa.
    Las decisiones son responsabilidad del Conductor.

Jerarquía:
    BaseRegistry  (este archivo)         — contrato universal
        └── RegistryBase (registries/base.py) — lógica común
                ├── AlertRegistry        — historial de alertas
                ├── BreakerRegistry      — estado de breakers
                └── GateRegistry         — registro de gates activos
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Generic, Iterator, List, Optional, TypeVar

log = logging.getLogger("aureon.control.registry")

# Tipo genérico para los entries del registry
T = TypeVar("T")


# ══════════════════════════════════════════════════════════
# REGISTRY ENTRY — unidad de almacenamiento
# ══════════════════════════════════════════════════════════

class RegistryEntry(Generic[T]):
    """
    Unidad atómica de almacenamiento en un Registry.

    Envuelve cualquier dato con metadatos de auditoría:
        entry_id   — identificador único
        data       — el dato almacenado
        recorded_at — cuándo fue registrado
        tags        — etiquetas para filtrado rápido
    """

    def __init__(
        self,
        data: T,
        tags: Optional[Dict[str, str]] = None,
    ):
        import uuid
        self.entry_id    = str(uuid.uuid4())
        self.data        = data
        self.recorded_at = datetime.now(timezone.utc)
        self.tags        = tags or {}

    def matches(self, **filters) -> bool:
        """
        Verifica si este entry coincide con los filtros dados.
        Compara contra los tags del entry.

        Ejemplo:
            entry.matches(module="auth", severity="critical")
        """
        for key, value in filters.items():
            if self.tags.get(key) != value:
                return False
        return True

    def to_dict(self) -> dict:
        data = self.data
        if hasattr(data, "to_dict"):
            data = data.to_dict()
        return {
            "entry_id":    self.entry_id,
            "data":        data,
            "recorded_at": self.recorded_at.isoformat(),
            "tags":        self.tags,
        }

    def __repr__(self) -> str:
        return (
            f"<RegistryEntry id={self.entry_id[:8]} "
            f"recorded_at={self.recorded_at.isoformat()} "
            f"tags={self.tags}>"
        )


# ══════════════════════════════════════════════════════════
# BASE REGISTRY — contrato universal
# ══════════════════════════════════════════════════════════

class BaseRegistry(ABC, Generic[T]):
    """
    Contrato universal para todos los Registries de AUREON.

    Define qué ES un Registry — su identidad y sus operaciones
    fundamentales de almacenamiento y consulta.

    Propiedades que todo Registry debe tener:
        name       — identificador único del registry
        max_size   — límite de entries en memoria
        _store     — almacenamiento interno (list)

    Métodos que todo Registry debe implementar:
        record()   — almacenar un entry
        query()    — consultar entries con filtros
        clear()    — limpiar el historial

    Métodos con implementación base (pueden ser sobreescritos):
        count()    — total de entries
        latest()   — entries más recientes
        snapshot() — estado actual completo para auditoría
    """

    DEFAULT_MAX_SIZE = 1000  # entries máximos en memoria

    def __init__(self, name: str, max_size: int = DEFAULT_MAX_SIZE):
        self.name     = name
        self.max_size = max_size
        self._store:  List[RegistryEntry[T]] = []
        self._index:  Dict[str, RegistryEntry[T]] = {}  # entry_id → entry

    # ── Identidad ─────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"name={self.name!r} "
            f"entries={len(self._store)}/{self.max_size}>"
        )

    def __len__(self) -> int:
        return len(self._store)

    def __iter__(self) -> Iterator[RegistryEntry[T]]:
        return iter(self._store)

    # ── Almacenamiento — contrato obligatorio ─────────────

    @abstractmethod
    def record(self, data: T, tags: Optional[Dict[str, str]] = None) -> RegistryEntry[T]:
        """
        Almacena un dato en el registry.

        Args:
            data — el dato a almacenar (Alert, Breaker state, etc.)
            tags — etiquetas para filtrado posterior

        Returns:
            RegistryEntry creado

        Implementación sugerida:
            entry = RegistryEntry(data, tags)
            self._store_entry(entry)
            return entry
        """
        ...

    # ── Consulta — contrato obligatorio ───────────────────

    @abstractmethod
    def query(self, **filters) -> List[RegistryEntry[T]]:
        """
        Consulta entries que coincidan con los filtros.

        Args:
            **filters — pares clave=valor que se comparan
                        contra los tags de cada entry

        Returns:
            Lista de RegistryEntry que coinciden

        Ejemplo:
            registry.query(severity="critical", module="auth")
        """
        ...

    # ── Limpieza — contrato obligatorio ───────────────────

    @abstractmethod
    def clear(self) -> int:
        """
        Limpia todos los entries del registry.

        Returns:
            Número de entries eliminados
        """
        ...

    # ── Consultas con implementación base ─────────────────

    def count(self, **filters) -> int:
        """Total de entries, con filtros opcionales."""
        if not filters:
            return len(self._store)
        return len(self.query(**filters))

    def latest(self, n: int = 10, **filters) -> List[RegistryEntry[T]]:
        """
        Retorna los N entries más recientes.
        Si se pasan filtros, los aplica primero.
        """
        entries = self.query(**filters) if filters else list(self._store)
        return sorted(
            entries,
            key=lambda e: e.recorded_at,
            reverse=True,
        )[:n]

    def get(self, entry_id: str) -> Optional[RegistryEntry[T]]:
        """Busca un entry por su ID único."""
        return self._index.get(entry_id)

    def snapshot(self) -> dict:
        """
        Estado completo del registry para auditoría en tiempo real.
        Retorna un dict serializable.
        """
        return {
            "name":      self.name,
            "total":     len(self._store),
            "max_size":  self.max_size,
            "latest":    [e.to_dict() for e in self.latest(n=5)],
        }

    # ── Helpers para hijos ────────────────────────────────

    def _store_entry(self, entry: RegistryEntry[T]) -> None:
        """
        Almacena un entry respetando el límite max_size.
        Si se supera el límite, elimina los más antiguos (FIFO).
        Llamar desde record() en los hijos.
        """
        if len(self._store) >= self.max_size:
            removed = self._store.pop(0)
            self._index.pop(removed.entry_id, None)
            log.debug(
                "Registry[%s] límite alcanzado — entry más antiguo eliminado",
                self.name,
            )

        self._store.append(entry)
        self._index[entry.entry_id] = entry

    def _filter_entries(self, **filters) -> List[RegistryEntry[T]]:
        """
        Filtra entries por tags.
        Llamar desde query() en los hijos.
        """
        if not filters:
            return list(self._store)
        return [e for e in self._store if e.matches(**filters)]