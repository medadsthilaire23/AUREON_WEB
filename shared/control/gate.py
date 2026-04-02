"""
shared/control/gate.py
======================
Contrato base universal para todos los Gates del sistema AUREON.

Un Gate es un sensor — detecta irregularidades y emite Alerts.
No decide qué hacer con ellas. Esa responsabilidad es del Conductor.

Regla arquitectónica:
    gate.py NO importa nada de products/.
    Los Gates concretos en gates/ tampoco deben hacerlo.
    Todo lo que un Gate necesita de un producto le llega
    como parámetro en el momento de la validación.

Jerarquía:
    BaseGate  (este archivo)   — contrato universal, nunca cambia
        └── GateBase (gates/base.py) — lógica común, puede evolucionar
                ├── HttpGate
                ├── BootGate
                ├── ModuleGate
                └── DbGate
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from shared.control.alert import Alert, Impact, Recovery, Origin

log = logging.getLogger("aureon.control.gate")


# ══════════════════════════════════════════════════════════
# GATE RESULT — lo que devuelve toda validación
# ══════════════════════════════════════════════════════════

class GateResult:
    """
    Resultado de una validación de Gate.

    passed  → True si el dato/estado es válido
    alert   → Alert emitida si hay problema (None si passed=True)
    value   → el valor corregido si recovery=AUTO, o el original
    """

    def __init__(
        self,
        passed: bool,
        alert: Optional[Alert] = None,
        value: Any = None,
    ):
        self.passed = passed
        self.alert  = alert
        self.value  = value

    @classmethod
    def ok(cls, value: Any = None) -> "GateResult":
        """Validación exitosa — sin alerta."""
        return cls(passed=True, value=value)

    @classmethod
    def fail(cls, alert: Alert, value: Any = None) -> "GateResult":
        """Validación fallida — con alerta."""
        return cls(passed=False, alert=alert, value=value)

    @classmethod
    def corrected(cls, alert: Alert, value: Any) -> "GateResult":
        """
        Validación fallida pero auto-corregida.
        passed=True porque el sistema puede continuar.
        La alerta se emite de todas formas para registro.
        """
        return cls(passed=True, alert=alert, value=value)

    def __bool__(self) -> bool:
        return self.passed

    def __str__(self) -> str:
        status = "OK" if self.passed else "FAIL"
        if self.alert:
            return f"GateResult({status}) → {self.alert}"
        return f"GateResult({status})"


# ══════════════════════════════════════════════════════════
# BASE GATE — contrato universal
# ══════════════════════════════════════════════════════════

class BaseGate(ABC):
    """
    Contrato universal para todos los Gates de AUREON.

    Define qué ES un Gate — su identidad, no su implementación.
    Nunca cambia. Los hijos extienden GateBase (gates/base.py),
    no este archivo directamente.

    Propiedades que todo Gate debe tener:
        name        — identificador único del gate
        description — qué valida este gate
        active      — si está activo o fue deshabilitado

    Métodos que todo Gate debe implementar:
        validate()  — la validación concreta
        emit()      — cómo reporta la alerta al Conductor
    """

    def __init__(self, name: str, description: str = ""):
        self.name        = name
        self.description = description
        self.active      = True
        self._conductor  = None   # se inyecta en Fase 2
        self._on_alert: Optional[Callable[[Alert], None]] = None

    # ── Identidad ─────────────────────────────────────────

    def __repr__(self) -> str:
        status = "active" if self.active else "disabled"
        return f"<{self.__class__.__name__} name={self.name!r} {status}>"

    # ── Ciclo de vida ──────────────────────────────────────

    def enable(self) -> None:
        """Activa el gate."""
        self.active = True
        log.info("Gate habilitado: %s", self.name)

    def disable(self) -> None:
        """
        Desactiva el gate — las validaciones pasan sin revisión.
        Útil durante mantenimiento o pruebas.
        """
        self.active = False
        log.warning("Gate deshabilitado: %s", self.name)

    # ── Wiring ────────────────────────────────────────────

    def set_conductor(self, conductor) -> None:
        """
        Fase 2 — Wiring.
        El Conductor se inyecta aquí para que el Gate
        pueda reportarle alertas directamente.
        """
        self._conductor = conductor

    def on_alert(self, callback: Callable[[Alert], None]) -> None:
        """
        Registra un callback alternativo para alertas.
        Útil en tests o cuando no hay Conductor disponible.
        """
        self._on_alert = callback

    # ── Emisión de alertas ────────────────────────────────

    def emit(self, alert: Alert) -> None:
        """
        Reporta una alerta.
        Primero al Conductor si está disponible,
        luego al callback si existe,
        siempre al log.
        """
        log.warning("Gate[%s] alerta: %s", self.name, alert)

        if self._conductor:
            self._conductor.receive(alert)
        elif self._on_alert:
            self._on_alert(alert)

    # ── Validación — contrato obligatorio ─────────────────

    @abstractmethod
    def validate(self, value: Any, **kwargs) -> GateResult:
        """
        Valida un valor o estado.

        Args:
            value   — el dato a validar
            **kwargs — contexto adicional específico de cada gate

        Returns:
            GateResult.ok()         si la validación pasa
            GateResult.fail()       si falla sin corrección posible
            GateResult.corrected()  si falla pero se auto-corrigió
        """
        ...

    # ── Método de conveniencia ────────────────────────────

    def check(self, value: Any, **kwargs) -> GateResult:
        """
        Punto de entrada principal.
        Si el gate está inactivo, pasa sin validar.
        Si falla, emite la alerta automáticamente.
        """
        if not self.active:
            return GateResult.ok(value=value)

        result = self.validate(value, **kwargs)

        if result.alert:
            self.emit(result.alert)

        return result

    # ── Helpers para construir alertas ────────────────────

    def _alert(
        self,
        code: str,
        message: str,
        impact: Impact,
        recovery: Recovery,
        origin: Origin,
        context: Optional[dict] = None,
    ) -> Alert:
        """Construye una Alert con el módulo del gate ya asignado."""
        return Alert(
            code=code,
            message=message,
            impact=impact,
            recovery=recovery,
            origin=origin,
            module=self.name,
            context=context or {},
        )