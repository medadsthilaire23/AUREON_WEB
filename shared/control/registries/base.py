# shared/control/registries/base.py
# ══════════════════════════════════════════════════════════════════════════════
# REGISTRY BASE — AUREON Sistema de Control v3.0
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Generic, List, Optional, TypeVar

from shared.control.breakers.base import BreakerBase, BreakerSnapshot
from shared.control.gates.base     import Gate, GateSnapshot
from shared.control.event_state    import EventState, is_valid_transition
from shared.control.operation_gates import (
    OPERATIONS, get_parent, get_gates_for, is_descendant_of,
)

T = TypeVar("T")


# ══════════════════════════════════════════════════════════════════════════════
# EVENTO REGISTRADO
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class EventEntry:
    event_id:    str
    op_id:       str
    state:       EventState
    gate:        str
    module:      str
    recorded_at: float = field(default_factory=time.perf_counter)
    finished_at: Optional[float] = None
    error:       Optional[str]   = None

    @property
    def duration_ms(self) -> float:
        end = self.finished_at or time.perf_counter()
        return (end - self.recorded_at) * 1000

    @property
    def is_active(self) -> bool:
        return self.state != EventState.FINISH

    @property
    def key(self) -> tuple[str, str]:
        return (self.event_id, self.op_id)

    def to_dict(self) -> dict:
        return {
            "event_id":    self.event_id,
            "op_id":       self.op_id,
            "state":       self.state.value,
            "gate":        self.gate,
            "module":      self.module,
            "duration_ms": round(self.duration_ms, 2),
            "error":       self.error,
        }


# ══════════════════════════════════════════════════════════════════════════════
# EVENT REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

class _EventRegistry:

    MAX_EVENTS = 5_000

    def __init__(self):
        self._entries: OrderedDict[tuple[str, str], EventEntry] = OrderedDict()
        self._lock    = threading.Lock()

    # ── Escritura ──────────────────────────────────────────────────────────

    def record(
        self,
        event_id: str,
        op_id:    str,
        state:    EventState,
        gate:     str,
        error:    Optional[str] = None,
    ) -> EventEntry:
        key = (event_id, op_id)
        op  = OPERATIONS.get(op_id, {})
        mod = op.get("module", "unknown")

        with self._lock:
            if key in self._entries:
                entry = self._entries[key]
                if is_valid_transition(entry.state, state):
                    entry.state = state
                    entry.error = error
                    if state == EventState.FINISH:
                        entry.finished_at = time.perf_counter()
                    self._entries.move_to_end(key)
            else:
                entry = EventEntry(
                    event_id = event_id,
                    op_id    = op_id,
                    state    = state,
                    gate     = gate,
                    module   = mod,
                    error    = error,
                )
                if state == EventState.FINISH:
                    entry.finished_at = time.perf_counter()
                self._entries[key] = entry
                self._evict_if_needed()

        return entry

    def transition(
        self,
        event_id:  str,
        op_id:     str,
        new_state: EventState,
        error:     Optional[str] = None,
    ) -> Optional[EventEntry]:
        key = (event_id, op_id)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if not is_valid_transition(entry.state, new_state):
                return None
            entry.state = new_state
            entry.error = error
            if new_state == EventState.FINISH:
                entry.finished_at = time.perf_counter()
            self._entries.move_to_end(key)
        return entry

    # ── Lectura — Conductor ────────────────────────────────────────────────

    def get(self, event_id: str, op_id: str) -> Optional[EventEntry]:
        with self._lock:
            return self._entries.get((event_id, op_id))

    def get_by_event(self, event_id: str) -> List[EventEntry]:
        with self._lock:
            return [e for (eid, _), e in self._entries.items() if eid == event_id]

    def get_by_op(self, op_id: str) -> List[EventEntry]:
        with self._lock:
            return [e for (_, oid), e in self._entries.items() if oid == op_id]

    def get_failed(self) -> List[EventEntry]:
        with self._lock:
            return [e for e in self._entries.values() if e.state == EventState.FAILED]

    def get_processing(self) -> List[EventEntry]:
        with self._lock:
            return [e for e in self._entries.values() if e.state == EventState.PROCESSING]

    def get_active(self) -> List[EventEntry]:
        with self._lock:
            return [e for e in self._entries.values() if e.is_active]

    # ── Lectura — Timer ────────────────────────────────────────────────────

    def count_active_for_gate(self, gate_name: str) -> int:
        with self._lock:
            return sum(
                1 for e in self._entries.values()
                if e.gate == gate_name and e.is_active
            )

    def count_active_for_op(self, op_id: str) -> int:
        with self._lock:
            return sum(
                1 for (_, oid), e in self._entries.items()
                if oid == op_id and e.is_active
            )

    # ── Propagación de fallo ───────────────────────────────────────────────

    def get_blocked_by(self, failed_op_id: str) -> List[str]:
        return [
            op_id for op_id in OPERATIONS
            if is_descendant_of(op_id, failed_op_id)
        ]

    def is_blocked(self, op_id: str) -> bool:
        from shared.control.operation_gates import get_ancestors
        ancestors = get_ancestors(op_id)
        with self._lock:
            for ancestor_id in ancestors:
                for (_, oid), e in self._entries.items():
                    if oid == ancestor_id and e.state == EventState.FAILED:
                        return True
        return False

    # ── Snapshot y métricas ────────────────────────────────────────────────

    def snapshot(self) -> dict:
        with self._lock:
            entries = list(self._entries.values())

        by_state  = {s.value: 0 for s in EventState}
        by_gate:   dict[str, int] = {}
        by_module: dict[str, int] = {}

        for e in entries:
            by_state[e.state.value] += 1
            by_gate[e.gate]          = by_gate.get(e.gate, 0) + 1
            by_module[e.module]      = by_module.get(e.module, 0) + 1

        return {
            "total":     len(entries),
            "active":    sum(1 for e in entries if e.is_active),
            "by_state":  by_state,
            "by_gate":   by_gate,
            "by_module": by_module,
            "capacity":  self.MAX_EVENTS,
        }

    def recent(self, limit: int = 50) -> List[dict]:
        with self._lock:
            entries = list(self._entries.values())
        return [e.to_dict() for e in reversed(entries[-limit:])]

    def recent_failed(self, limit: int = 20) -> List[dict]:
        with self._lock:
            failed = [e for e in self._entries.values() if e.state == EventState.FAILED]
        return [e.to_dict() for e in reversed(failed[-limit:])]

    # ── Limpieza ───────────────────────────────────────────────────────────

    def _evict_if_needed(self) -> None:
        if len(self._entries) <= self.MAX_EVENTS:
            return
        to_remove = []
        for key, entry in self._entries.items():
            if not entry.is_active:
                to_remove.append(key)
            if len(self._entries) - len(to_remove) <= self.MAX_EVENTS:
                break
        for key in to_remove:
            del self._entries[key]

    def clear_finished(self) -> int:
        with self._lock:
            to_remove = [k for k, e in self._entries.items() if not e.is_active]
            for k in to_remove:
                del self._entries[k]
        return len(to_remove)

    def clear_all(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS INTERNOS
# ══════════════════════════════════════════════════════════════════════════════

def _snapshot_to_dict(snap: Any) -> dict:
    """
    Normaliza cualquier snapshot a dict.

    Los gates concretos (HttpGate, DbGate, ModuleGate, BootGate)
    devuelven dicts planos desde snapshot().
    Los feature-flag gates (Gate) devuelven GateSnapshot (dataclass frozen).
    Esta función acepta ambos sin romperse.
    """
    if isinstance(snap, dict):
        return snap
    if hasattr(snap, "to_dict"):
        return snap.to_dict()
    # Fallback — dataclass sin to_dict
    try:
        return snap.__dict__
    except AttributeError:
        # dataclass frozen — usar dataclasses.asdict
        import dataclasses
        return dataclasses.asdict(snap)


# ══════════════════════════════════════════════════════════════════════════════
# CATÁLOGO GENÉRICO
# ══════════════════════════════════════════════════════════════════════════════

class _Catalog(Generic[T]):
    def __init__(self, factory: type) -> None:
        self._factory = factory
        self._store:  dict[str, Any] = {}
        self._lock    = threading.Lock()

    def get(self, name: str, **kwargs: Any) -> T:
        with self._lock:
            if name not in self._store:
                self._store[name] = self._factory(name=name, **kwargs)
            return self._store[name]

    def register(self, instance: T) -> T:
        name = instance.name  # type: ignore[attr-defined]
        with self._lock:
            if name in self._store:
                raise ValueError(f"'{name}' ya está registrado en {type(self).__name__}")
            self._store[name] = instance
        return instance

    def remove(self, name: str) -> None:
        with self._lock:
            self._store.pop(name, None)

    def clear(self) -> None:
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


class _BreakerCatalog(_Catalog[BreakerBase]):
    def __init__(self) -> None:
        super().__init__(BreakerBase)

    def all_snapshots(self) -> list[dict]:
        """Devuelve todos los snapshots normalizados como dicts."""
        with self._lock:
            instances = list(self._store.values())
        return [_snapshot_to_dict(b.snapshot()) for b in instances]

    def reset_all(self) -> None:
        with self._lock:
            instances = list(self._store.values())
        for b in instances:
            b.reset()


class _GateCatalog(_Catalog[Gate]):
    def __init__(self) -> None:
        super().__init__(Gate)

    def all_snapshots(self) -> list[dict]:
        """
        Devuelve todos los snapshots normalizados como dicts.

        Los gates concretos (HttpGate, DbGate, ModuleGate, BootGate)
        tienen snapshot() → dict con campos extendidos.
        Los feature-flag gates (Gate simple) tienen snapshot() → GateSnapshot.
        _snapshot_to_dict() maneja ambos casos.
        """
        with self._lock:
            instances = list(self._store.values())
        return [_snapshot_to_dict(g.snapshot()) for g in instances]


# ══════════════════════════════════════════════════════════════════════════════
# ALIAS DE TIPO PÚBLICOS
# ══════════════════════════════════════════════════════════════════════════════

EventRegistryType   = _EventRegistry
BreakerRegistryType = _BreakerCatalog
GateRegistryType    = _GateCatalog


# ══════════════════════════════════════════════════════════════════════════════
# SINGLETONS PÚBLICOS
# ══════════════════════════════════════════════════════════════════════════════

event_registry   = _EventRegistry()
BreakerRegistry  = _BreakerCatalog()
GateRegistry     = _GateCatalog()

EventRegistry = event_registry