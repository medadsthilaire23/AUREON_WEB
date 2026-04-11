# shared/control/logic/gate_resolver.py
# ══════════════════════════════════════════════════════════════════════════════
# Gate Resolver — AUREON v4.0 Hito 2
#
# El Resolver es el "peaje inteligente" del sistema. Antes de que cualquier
# operación se ejecute, el Resolver verifica recursivamente que toda la
# jerarquía de gates esté OPEN y que ningún ancestro haya fallado.
#
# Flujo de resolución:
#   HttpGate.scan() → resolve_op_id() → GateResolver.resolve()
#       → 1. ¿Es operación XX (Discovery)? → ANOMALY inmediato
#       → 2. ¿Algún ancestro está bloqueado en EventRegistry? → GB (Gate Bloqueado)
#       → 3. ¿Los gates de infraestructura están OPEN? → verificar cada uno
#       → 4. ¿Algún Breaker está activo? → verificar estado
#       → 5. ¿Gate en HALF_OPEN (WATCHING)? → permitir petición de prueba
#       → 6. Todo OK → ALLOWED, evolucionar event_id con alias del gate
#
# Contrato de retorno (ResolverResult):
#   {
#     "allowed":     bool,
#     "state":       str,          ← "allowed" | "blocked" | "anomaly" | "probe"
#     "fail_id":     str | None,   ← gate o prefijo que causó el bloqueo
#     "gate_origin": str | None,   ← gate concreto donde se detectó el fallo
#     "policy":      str,          ← log_policy de la operación
#     "evolved_id":  str,          ← event_id con el rastro de gates tatuado
#     "alert_level": str | None,   ← nivel de alerta si es anomalía
#   }
#
# Regla arquitectónica:
#   Este módulo NO importa nada de products/.
#   Consulta en memoria — sin I/O, sin DB, sin red.
#   Decisiones en microsegundos.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from shared.control.event_id    import evolve_id, get_root_id
from shared.control.event_state import EventState, is_anomaly_op, get_alert_level
from shared.control.operation_gates import (
    XX_OP_ID,
    get_operation,
    get_gates_for,
    get_ancestors,
    resolve_log_policy,
    resolve_module,
    exists as op_exists,
)

if TYPE_CHECKING:
    from shared.control.registries.base import EventRegistryType, GateRegistryType, BreakerRegistryType

log = logging.getLogger("aureon.control.logic.gate_resolver")


# ══════════════════════════════════════════════════════════════════════════════
# RESULTADO DEL RESOLVER
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ResolverResult:
    """
    Resultado atómico de la resolución de un evento.

    Campos:
        allowed     — True si la operación puede ejecutarse
        state       — "allowed" | "blocked" | "anomaly" | "probe"
        fail_id     — identificador del elemento que causó el bloqueo
                      (nombre del gate, prefijo de anomalía, etc.)
        gate_origin — gate concreto donde se detectó el problema
        policy      — log_policy de la operación (SUMMARY/ON_ERROR/AUDIT)
        evolved_id  — event_id con el rastro de gates tatuado
        alert_level — nivel de alerta si es anomalía (None si allowed)
        reason      — descripción legible del resultado
    """
    allowed:     bool
    state:       str
    fail_id:     Optional[str]
    gate_origin: Optional[str]
    policy:      str
    evolved_id:  str
    alert_level: Optional[str] = None
    reason:      str = ""

    def to_dict(self) -> dict:
        return {
            "allowed":     self.allowed,
            "state":       self.state,
            "fail_id":     self.fail_id,
            "gate_origin": self.gate_origin,
            "policy":      self.policy,
            "evolved_id":  self.evolved_id,
            "alert_level": self.alert_level,
            "reason":      self.reason,
        }

    @classmethod
    def allow(cls, evolved_id: str, policy: str) -> "ResolverResult":
        return cls(
            allowed     = True,
            state       = "allowed",
            fail_id     = None,
            gate_origin = None,
            policy      = policy,
            evolved_id  = evolved_id,
            alert_level = None,
            reason      = "Jerarquía validada — operación autorizada",
        )

    @classmethod
    def allow_probe(cls, evolved_id: str, policy: str, gate_name: str) -> "ResolverResult":
        """HALF_OPEN — petición de prueba permitida."""
        return cls(
            allowed     = True,
            state       = "probe",
            fail_id     = gate_name,
            gate_origin = gate_name,
            policy      = policy,
            evolved_id  = evolved_id,
            alert_level = "NARANJA",
            reason      = f"Gate '{gate_name}' en modo prueba (HALF_OPEN) — petición de verificación",
        )

    @classmethod
    def block(cls, event_id: str, policy: str, fail_id: str, gate_origin: str, reason: str) -> "ResolverResult":
        return cls(
            allowed     = False,
            state       = "blocked",
            fail_id     = fail_id,
            gate_origin = gate_origin,
            policy      = policy,
            evolved_id  = event_id,
            alert_level = "ROJA",
            reason      = reason,
        )

    @classmethod
    def anomaly(cls, event_id: str, op_id: str, policy: str) -> "ResolverResult":
        level = get_alert_level(op_id) or "ROJA_CRITICA"
        prefix = op_id[:2] if len(op_id) >= 2 else op_id
        return cls(
            allowed     = False,
            state       = "anomaly",
            fail_id     = prefix,
            gate_origin = None,
            policy      = "AUDIT",
            evolved_id  = event_id,
            alert_level = level,
            reason      = f"Prefijo de anomalía '{prefix}' detectado — alerta {level}",
        )


# ══════════════════════════════════════════════════════════════════════════════
# GATE RESOLVER
# ══════════════════════════════════════════════════════════════════════════════

class GateResolver:
    """
    Validador recursivo de jerarquía de gates.

    Una instancia singleton — creada en Fase 2 e inyectada donde se necesite.
    Todas las consultas son en memoria — sin I/O.

    Wiring:
        from shared.control.logic.gate_resolver import GateResolver
        resolver = GateResolver()
        resolver.wire(
            event_registry  = event_registry,
            gate_registry   = GateRegistry,
            breaker_registry = BreakerRegistry,
            conductor_gates = conductor._gates,  # gates concretos
        )
    """

    def __init__(self) -> None:
        self._events:   Optional["EventRegistryType"]   = None
        self._gates:    Optional["GateRegistryType"]    = None
        self._breakers: Optional["BreakerRegistryType"] = None
        self._concrete: dict = {}   # gates concretos: nombre → instancia
        self._wired     = False
        self._lock      = threading.Lock()

    # ── Wiring ────────────────────────────────────────────────────────────────

    def wire(
        self,
        event_registry:   "EventRegistryType",
        gate_registry:    "GateRegistryType",
        breaker_registry: "BreakerRegistryType",
        conductor_gates:  dict,
    ) -> None:
        """
        Inyecta las dependencias necesarias.
        Llamar desde app.py Fase 2 después del Conductor.
        """
        self._events   = event_registry
        self._gates    = gate_registry
        self._breakers = breaker_registry
        self._concrete = conductor_gates
        self._wired    = True
        log.info("[GateResolver] wired — listo para resolver jerarquías")

    # ── Resolución principal ──────────────────────────────────────────────────

    def resolve(self, op_id: str, event_id: str) -> ResolverResult:
        """
        Punto de entrada principal.

        Valida recursivamente que la operación puede ejecutarse:
          1. Detecta anomalías (XX, AD, etc.) → ANOMALY inmediato
          2. Verifica ancestros bloqueados en EventRegistry
          3. Verifica estado de gates de infraestructura
          4. Verifica Breakers
          5. Detecta HALF_OPEN → petición de prueba

        Retorna ResolverResult con el event_id evolucionado.

        Nunca lanza excepción — siempre retorna un resultado válido.
        """
        if not self._wired:
            log.warning("[GateResolver] No está wired — permitiendo por defecto (fail-open)")
            return ResolverResult.allow(event_id, "SUMMARY")

        try:
            return self._resolve_internal(op_id, event_id)
        except Exception as e:
            log.error("[GateResolver] error inesperado en resolve: %s", e)
            return ResolverResult.allow(event_id, "SUMMARY")

    def _resolve_internal(self, op_id: str, event_id: str) -> ResolverResult:
        policy = resolve_log_policy(op_id)

        # ── 1. Detectar anomalía (XX o prefijos de crisis) ─────────────────
        if op_id == XX_OP_ID or is_anomaly_op(op_id):
            log.warning("[GateResolver] ANOMALY op_id=%s event=%s", op_id, event_id)
            return ResolverResult.anomaly(event_id, op_id, policy)

        # ── 2. Verificar que la operación existe ───────────────────────────
        if not op_exists(op_id):
            log.warning("[GateResolver] op_id desconocido: %s → tratando como XX", op_id)
            return ResolverResult.anomaly(event_id, XX_OP_ID, policy)

        # ── 3. Verificar ancestros bloqueados en EventRegistry ─────────────
        if self._events is not None:
            blocked_result = self._check_ancestors(op_id, event_id, policy)
            if blocked_result is not None:
                return blocked_result

        # ── 4. Obtener los gates requeridos por esta operación ─────────────
        required_gates = get_gates_for(op_id)

        # ── 5. Verificar cada gate requerido ───────────────────────────────
        evolved = event_id
        for gate_name in required_gates:
            gate_result = self._check_gate(gate_name, evolved, policy)
            if gate_result is not None:
                return gate_result
            # Gate OK — tatuar el alias en el event_id
            evolved = evolve_id(evolved, gate_name)

        # ── 6. Todo validado ───────────────────────────────────────────────
        if resolve_log_policy(op_id) == "AUDIT":
            log.debug("[GateResolver] ALLOWED op=%s event=%s evolved=%s", op_id, event_id, evolved)

        return ResolverResult.allow(evolved_id=evolved, policy=policy)

    # ── Verificación de ancestros ─────────────────────────────────────────────

    def _check_ancestors(
        self,
        op_id:    str,
        event_id: str,
        policy:   str,
    ) -> Optional[ResolverResult]:
        """
        Verifica que ningún ancestro del op_id esté bloqueado.
        Si lo está, retorna un ResolverResult de bloqueo con prefijo GB.
        """
        ancestors = get_ancestors(op_id)
        for ancestor_id in ancestors:
            # Buscar en EventRegistry si el ancestro tiene entradas en crisis
            if self._events.is_blocked(op_id):
                log.warning(
                    "[GateResolver] BLOCKED — ancestro '%s' bloqueado para op=%s event=%s",
                    ancestor_id, op_id, event_id,
                )
                return ResolverResult.block(
                    event_id   = event_id,
                    policy     = policy,
                    fail_id    = f"GB_{ancestor_id}",
                    gate_origin = ancestor_id,
                    reason     = f"Operación bloqueada: ancestro '{ancestor_id}' en estado de crisis",
                )
        return None

    # ── Verificación de un gate individual ────────────────────────────────────

    def _check_gate(
        self,
        gate_name: str,
        event_id:  str,
        policy:    str,
    ) -> Optional[ResolverResult]:
        """
        Verifica el estado de un gate.
        Retorna None si el gate está OK.
        Retorna ResolverResult de bloqueo o prueba si hay problema.
        """
        # ── Verificar gate concreto (HttpGate, DbGate, etc.) ───────────────
        concrete = self._concrete.get(gate_name)
        if concrete is not None:
            return self._check_concrete_gate(gate_name, concrete, event_id, policy)

        # ── Verificar feature flag (oauth_google, registration, etc.) ──────
        if self._gates is not None and gate_name in self._gates:
            feature_gate = self._gates.get(gate_name)
            if hasattr(feature_gate, "enabled") and not feature_gate.enabled:
                log.warning(
                    "[GateResolver] BLOCKED — feature gate '%s' desactivado event=%s",
                    gate_name, event_id,
                )
                return ResolverResult.block(
                    event_id    = event_id,
                    policy      = policy,
                    fail_id     = f"GB_{gate_name}",
                    gate_origin = gate_name,
                    reason      = f"Feature gate '{gate_name}' desactivado",
                )

        return None

    def _check_concrete_gate(
        self,
        gate_name: str,
        gate:      Any,
        event_id:  str,
        policy:    str,
    ) -> Optional[ResolverResult]:
        """
        Verifica un gate concreto (HttpGate, DbGate, ModuleGate, BootGate).

        Estados posibles:
          - active=True, enabled=True  → OK
          - active=False               → BLOCKED
          - Breaker WATCHING           → petición de prueba (probe)
          - Breaker CLOSED/FORCED      → BLOCKED
        """
        # ── Verificar si el gate está activo ──────────────────────────────
        is_enabled = True
        if hasattr(gate, "_enabled"):
            import threading as _t
            with gate._lock if hasattr(gate, "_lock") else _t.Lock():
                is_enabled = gate._enabled
        elif hasattr(gate, "active"):
            is_enabled = gate.active

        if not is_enabled:
            log.warning(
                "[GateResolver] BLOCKED — gate '%s' cerrado event=%s",
                gate_name, event_id,
            )
            return ResolverResult.block(
                event_id    = event_id,
                policy      = policy,
                fail_id     = f"GB_{gate_name}",
                gate_origin = gate_name,
                reason      = f"Gate '{gate_name}' está cerrado (OPEN state)",
            )

        # ── Verificar Breaker asociado ─────────────────────────────────────
        if self._breakers is not None and gate_name in self._breakers:
            breaker = self._breakers.get(gate_name)
            breaker_result = self._check_breaker(gate_name, breaker, event_id, policy)
            if breaker_result is not None:
                return breaker_result

        return None

    def _check_breaker(
        self,
        gate_name: str,
        breaker:   Any,
        event_id:  str,
        policy:    str,
    ) -> Optional[ResolverResult]:
        """
        Verifica el estado del Breaker asociado a un gate.

        BreakerState v3.x:
          STANDBY  → sin intervención → OK
          WATCHING → Timer observando cola → petición de prueba (probe)
          CLOSED   → gate cerrado por Conductor → BLOCKED
          FORCED   → cierre de emergencia → BLOCKED
        """
        from shared.control.breakers.base import BreakerState

        with breaker._lock if hasattr(breaker, "_lock") else __import__("threading").Lock():
            state = breaker._state if hasattr(breaker, "_state") else None

        if state is None:
            return None

        if state == BreakerState.STANDBY:
            return None

        if state == BreakerState.WATCHING:
            # El Timer está observando la cola — permitir petición de prueba
            log.info(
                "[GateResolver] PROBE — breaker '%s' WATCHING event=%s",
                gate_name, event_id,
            )
            evolved = evolve_id(event_id, gate_name)
            return ResolverResult.allow_probe(
                evolved_id = evolved,
                policy     = policy,
                gate_name  = gate_name,
            )

        if state in (BreakerState.CLOSED, BreakerState.FORCED):
            label = "FORCED" if state == BreakerState.FORCED else "CLOSED"
            log.warning(
                "[GateResolver] BLOCKED — breaker '%s' %s event=%s",
                gate_name, label, event_id,
            )
            return ResolverResult.block(
                event_id    = event_id,
                policy      = policy,
                fail_id     = f"GB_{gate_name}",
                gate_origin = gate_name,
                reason      = f"Breaker '{gate_name}' en estado {label} — gate bloqueado por el Conductor",
            )

        return None

    # ── Consultas de estado ───────────────────────────────────────────────────

    def is_gate_available(self, gate_name: str) -> bool:
        """
        Consulta rápida: ¿está disponible un gate?
        Usado por Sub-Gates para verificar sus dependencias.
        """
        result = self._check_gate(gate_name, "_check_only_", "SUMMARY")
        return result is None

    def snapshot(self) -> dict:
        """Estado del resolver para el dashboard."""
        return {
            "wired":   self._wired,
            "gates_monitored": list(self._concrete.keys()),
        }


# ══════════════════════════════════════════════════════════════════════════════
# SINGLETON
# ══════════════════════════════════════════════════════════════════════════════

gate_resolver = GateResolver()