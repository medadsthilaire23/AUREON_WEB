# shared/control/gates/base.py
# ══════════════════════════════════════════════════════════════════════════════
# Lógica común para todos los Gates concretos de AUREON.
#
# Cambios:
#   - Añadidos Gate y GateSnapshot — usados por registries/base.py
#     y conductor.py para el subsistema de control de auth
#   - GateBase y SchemaField sin cambios — compatibilidad total
#
# Jerarquía completa:
#     Gate      (este archivo) — gate simple con enabled/disabled
#     BaseGate  (gate.py)      — contrato universal con conductor
#         └── GateBase (este archivo) — lógica común con schema/stats
#                 ├── HttpGate
#                 ├── BootGate
#                 ├── ModuleGate
#                 └── DbGate
# ══════════════════════════════════════════════════════════════════════════════

import logging
import re
import threading
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type

from shared.control.gate  import BaseGate, GateResult
from shared.control.alert import Alert, Impact, Recovery, Origin

log = logging.getLogger("aureon.control.gates")


# ══════════════════════════════════════════════════════════
# GATE — feature flag / killswitch simple
# Usado por GateRegistry y conductor.call()
# ══════════════════════════════════════════════════════════

class GateClosed(Exception):
    """
    Lanzada cuando un Gate está desactivado y se intenta pasar.
    conductor.call() la propaga — el llamador decide cómo manejarla.
    """
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Gate '{name}' está cerrado — operación desactivada")


@dataclass(frozen=True)
class GateSnapshot:
    """Estado puntual de un Gate — para métricas y healthcheck."""
    name:    str
    enabled: bool


class Gate:
    """
    Feature flag / killswitch thread-safe.

    Uso:
        gate = Gate("oauth_google", enabled=True)
        gate.check()          # lanza GateClosed si disabled
        gate.set_enabled(False)
        snap = gate.snapshot()
    """

    def __init__(self, name: str, enabled: bool = True):
        self.name     = name
        self._enabled = enabled
        self._lock    = threading.Lock()

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def check(self) -> None:
        """Lanza GateClosed si el gate está desactivado."""
        with self._lock:
            if not self._enabled:
                raise GateClosed(self.name)

    def set_enabled(self, value: bool) -> None:
        with self._lock:
            self._enabled = value
        log.info("gate.set_enabled name=%s enabled=%s", self.name, value)

    def snapshot(self) -> GateSnapshot:
        with self._lock:
            return GateSnapshot(name=self.name, enabled=self._enabled)

    def __contains__(self, name: str) -> bool:
        return self.name == name


# ══════════════════════════════════════════════════════════
# SCHEMA FIELD — definición de un campo esperado
# ══════════════════════════════════════════════════════════

class SchemaField:
    """
    Define las reglas de validación para un campo.

    Uso:
        SchemaField("email", required=True, type_=str, pattern=r".+@.+")
        SchemaField("age",   required=True, type_=int, min_val=0, max_val=150)
        SchemaField("name",  required=False, type_=str, max_length=255)
    """

    def __init__(
        self,
        name:       str,
        required:   bool = True,
        type_:      Optional[Type] = None,
        min_val:    Optional[float] = None,
        max_val:    Optional[float] = None,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        pattern:    Optional[str] = None,
        allowed:    Optional[List[Any]] = None,
    ):
        self.name       = name
        self.required   = required
        self.type_      = type_
        self.min_val    = min_val
        self.max_val    = max_val
        self.min_length = min_length
        self.max_length = max_length
        self.pattern    = re.compile(pattern) if pattern else None
        self.allowed    = allowed

    def validate(self, value: Any) -> Optional[str]:
        """
        Valida un valor contra las reglas del campo.
        Retorna None si es válido, o un mensaje de error.
        """
        if value is None or value == "":
            if self.required:
                return f"Campo '{self.name}' es requerido"
            return None

        if self.type_ and not isinstance(value, self.type_):
            return (
                f"Campo '{self.name}' debe ser {self.type_.__name__}, "
                f"recibido {type(value).__name__}"
            )

        if self.min_val is not None and value < self.min_val:
            return f"Campo '{self.name}' debe ser >= {self.min_val}"
        if self.max_val is not None and value > self.max_val:
            return f"Campo '{self.name}' debe ser <= {self.max_val}"

        if isinstance(value, str):
            if self.min_length and len(value) < self.min_length:
                return f"Campo '{self.name}' debe tener al menos {self.min_length} caracteres"
            if self.max_length and len(value) > self.max_length:
                return f"Campo '{self.name}' no puede superar {self.max_length} caracteres"

        if self.pattern and isinstance(value, str):
            if not self.pattern.match(value):
                return f"Campo '{self.name}' no tiene el formato esperado"

        if self.allowed and value not in self.allowed:
            return f"Campo '{self.name}' debe ser uno de: {self.allowed}"

        return None


# ══════════════════════════════════════════════════════════
# GATE BASE — lógica común para gates concretos con conductor
# ══════════════════════════════════════════════════════════

class GateBase(BaseGate):
    """
    Extiende BaseGate con schema, estadísticas y helpers de alerta.
    Los gates concretos (HttpGate, BootGate, etc.) heredan de aquí.
    """

    def __init__(
        self,
        name:        str,
        description: str = "",
        strict_mode: bool = True,
    ):
        super().__init__(name=name, description=description)
        self.strict_mode = strict_mode
        self._fail_count = 0
        self._pass_count = 0
        self._schema:    List[SchemaField] = []

    # ── Schema ────────────────────────────────────────────

    def define_schema(self, *fields: SchemaField) -> "GateBase":
        self._schema = list(fields)
        return self

    def validate_schema(
        self,
        data:   Dict[str, Any],
        impact: Impact = Impact.REQUEST,
        origin: Origin = Origin.EXTERNAL,
    ) -> GateResult:
        if not self._schema:
            return GateResult.ok(value=data)

        for field in self._schema:
            error = field.validate(data.get(field.name))
            if error:
                self._fail_count += 1
                alert = self._alert(
                    code=f"SCHEMA_INVALID_{field.name.upper()}",
                    message=error,
                    impact=impact,
                    recovery=Recovery.AUTO,
                    origin=origin,
                    context={"field": field.name, "data": str(data)},
                )
                return GateResult.fail(alert=alert, value=data)

        self._pass_count += 1
        return GateResult.ok(value=data)

    # ── Estadísticas ──────────────────────────────────────

    @property
    def fail_count(self) -> int:
        return self._fail_count

    @property
    def pass_count(self) -> int:
        return self._pass_count

    @property
    def total_count(self) -> int:
        return self._fail_count + self._pass_count

    @property
    def error_rate(self) -> float:
        if self.total_count == 0:
            return 0.0
        return self._fail_count / self.total_count

    def stats(self) -> dict:
        return {
            "name":        self.name,
            "active":      self.active,
            "strict_mode": self.strict_mode,
            "pass_count":  self._pass_count,
            "fail_count":  self._fail_count,
            "total":       self.total_count,
            "error_rate":  round(self.error_rate, 4),
        }

    # ── Helpers de alerta rápida ──────────────────────────

    def alert_missing_config(
        self,
        key:      str,
        impact:   Impact   = Impact.GLOBAL,
        recovery: Recovery = Recovery.FATAL,
    ) -> Alert:
        return self._alert(
            code=f"CONFIG_MISSING_{key.upper()}",
            message=f"Variable de configuración requerida ausente: '{key}'",
            impact=impact,
            recovery=recovery,
            origin=Origin.SYSTEM,
            context={"key": key},
        )

    def alert_type_error(
        self,
        field:    str,
        expected: str,
        received: str,
        impact:   Impact = Impact.REQUEST,
    ) -> Alert:
        return self._alert(
            code=f"TYPE_ERROR_{field.upper()}",
            message=f"Campo '{field}' esperaba {expected}, recibió {received}",
            impact=impact,
            recovery=Recovery.AUTO,
            origin=Origin.EXTERNAL,
            context={"field": field, "expected": expected, "received": received},
        )

    def alert_format_error(
        self,
        field:  str,
        detail: str,
        impact: Impact = Impact.REQUEST,
    ) -> Alert:
        return self._alert(
            code=f"FORMAT_ERROR_{field.upper()}",
            message=f"Formato inválido en '{field}': {detail}",
            impact=impact,
            recovery=Recovery.AUTO,
            origin=Origin.EXTERNAL,
            context={"field": field, "detail": detail},
        )

    def alert_connection_error(
        self,
        target:   str,
        detail:   str,
        impact:   Impact   = Impact.GLOBAL,
        recovery: Recovery = Recovery.RESTART,
    ) -> Alert:
        return self._alert(
            code=f"CONNECTION_ERROR_{target.upper()}",
            message=f"Error de conexión a '{target}': {detail}",
            impact=impact,
            recovery=recovery,
            origin=Origin.SYSTEM,
            context={"target": target, "detail": detail},
        )

    def alert_module_error(
        self,
        module:   str,
        detail:   str,
        impact:   Impact   = Impact.MODULE,
        recovery: Recovery = Recovery.RUNTIME,
    ) -> Alert:
        return self._alert(
            code=f"MODULE_ERROR_{module.upper()}",
            message=f"Fallo en módulo '{module}': {detail}",
            impact=impact,
            recovery=recovery,
            origin=Origin.INTERNAL,
            context={"module": module, "detail": detail},
        )

    # ── Validate — abstracto ──────────────────────────────

    @abstractmethod
    def validate(self, value: Any, **kwargs) -> GateResult:
        """Validación concreta — cada gate define la suya."""
        ...