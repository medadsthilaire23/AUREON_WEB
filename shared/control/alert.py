"""
shared/control/alert.py
=======================
Definición del sistema de alertas del Órgano de Control AUREON.

Toda alerta tiene tres dimensiones:
    Impacto      — qué tan amplio es el daño
    Recovery     — qué tan recuperable es el problema
    Origin       — de dónde viene el problema

Estas tres dimensiones combinadas determinan la acción
que el Conductor tomará al recibir la alerta.

Uso:
    from shared.control.alert import Alert, Impact, Recovery, Origin, Severity

    alert = Alert(
        code="DB_CONNECTION_FAILED",
        message="No se pudo conectar a la base de datos",
        impact=Impact.GLOBAL,
        recovery=Recovery.RESTART,
        origin=Origin.SYSTEM,
    )
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ══════════════════════════════════════════════════════════
# DIMENSIÓN 1 — IMPACTO
# Qué tan amplio es el daño si no se atiende.
# ══════════════════════════════════════════════════════════

class Impact(str, Enum):
    GLOBAL  = "global"   # Afecta todo el sistema
    MODULE  = "module"   # Afecta solo un módulo/producto
    REQUEST = "request"  # Afecta solo la operación actual


# ══════════════════════════════════════════════════════════
# DIMENSIÓN 2 — RECOVERY
# Qué tan recuperable es el problema sin intervención humana.
# ══════════════════════════════════════════════════════════

class Recovery(str, Enum):
    AUTO    = "auto"     # El sistema puede corregirlo solo
    RUNTIME = "runtime"  # Se puede arreglar sin reiniciar
    RESTART = "restart"  # Requiere reiniciar el servidor
    FATAL   = "fatal"    # No tiene solución en runtime


# ══════════════════════════════════════════════════════════
# DIMENSIÓN 3 — ORIGIN
# De dónde viene el problema.
# ══════════════════════════════════════════════════════════

class Origin(str, Enum):
    EXTERNAL = "external"  # Datos del usuario / HTTP
    INTERNAL = "internal"  # Comunicación entre módulos
    SYSTEM   = "system"    # Bootstrap / DB / infraestructura


# ══════════════════════════════════════════════════════════
# SEVERIDAD — derivada de las tres dimensiones
# No se asigna manualmente — la calcula el sistema.
# ══════════════════════════════════════════════════════════

class Severity(str, Enum):
    LOW      = "low"      # Sin riesgo real, solo informativo
    MEDIUM   = "medium"   # Requiere atención pero no es urgente
    HIGH     = "high"     # Impacto significativo, acción requerida
    CRITICAL = "critical" # Sistema en riesgo, acción inmediata


def calculate_severity(impact: Impact, recovery: Recovery) -> Severity:
    """
    Calcula la severidad automáticamente a partir del impacto
    y la recuperabilidad. El origen no afecta la severidad
    pero sí la acción del Conductor.

    Tabla de decisión:
        GLOBAL  + FATAL/RESTART → CRITICAL
        GLOBAL  + RUNTIME       → HIGH
        GLOBAL  + AUTO          → MEDIUM
        MODULE  + FATAL/RESTART → HIGH
        MODULE  + RUNTIME       → MEDIUM
        MODULE  + AUTO          → LOW
        REQUEST + cualquiera    → LOW / MEDIUM
    """
    if impact == Impact.GLOBAL:
        if recovery in (Recovery.FATAL, Recovery.RESTART):
            return Severity.CRITICAL
        if recovery == Recovery.RUNTIME:
            return Severity.HIGH
        return Severity.MEDIUM

    if impact == Impact.MODULE:
        if recovery in (Recovery.FATAL, Recovery.RESTART):
            return Severity.HIGH
        if recovery == Recovery.RUNTIME:
            return Severity.MEDIUM
        return Severity.LOW

    # Impact.REQUEST
    if recovery in (Recovery.FATAL, Recovery.RESTART):
        return Severity.MEDIUM
    return Severity.LOW


# ══════════════════════════════════════════════════════════
# ALERT — la unidad de información del sistema de control
# ══════════════════════════════════════════════════════════

@dataclass
class Alert:
    """
    Unidad de información que viaja desde un Gate hasta el Conductor.

    Campos obligatorios:
        code     — identificador único del tipo de alerta (ej. "DB_CONN_FAILED")
        message  — descripción legible del problema
        impact   — Impact.GLOBAL | MODULE | REQUEST
        recovery — Recovery.AUTO | RUNTIME | RESTART | FATAL
        origin   — Origin.EXTERNAL | INTERNAL | SYSTEM

    Campos opcionales:
        module   — nombre del módulo que emite la alerta
        context  — datos extra para diagnóstico (dict libre)

    Campos automáticos:
        severity  — calculado a partir de impact + recovery
        timestamp — momento exacto en que se creó la alerta
        alert_id  — identificador único de esta instancia
    """

    # Obligatorios
    code:     str
    message:  str
    impact:   Impact
    recovery: Recovery
    origin:   Origin

    # Opcionales
    module:  Optional[str] = None
    context: Optional[dict] = field(default_factory=dict)

    # Automáticos — no se asignan manualmente
    severity:  Severity = field(init=False)
    timestamp: datetime = field(init=False)
    alert_id:  str      = field(init=False)

    def __post_init__(self):
        import uuid
        self.severity  = calculate_severity(self.impact, self.recovery)
        self.timestamp = datetime.now(timezone.utc)
        self.alert_id  = str(uuid.uuid4())

    def to_dict(self) -> dict:
        return {
            "alert_id":  self.alert_id,
            "code":      self.code,
            "message":   self.message,
            "impact":    self.impact.value,
            "recovery":  self.recovery.value,
            "origin":    self.origin.value,
            "severity":  self.severity.value,
            "module":    self.module,
            "context":   self.context,
            "timestamp": self.timestamp.isoformat(),
        }

    def __str__(self) -> str:
        return (
            f"[{self.severity.value.upper()}] {self.code} "
            f"| impact={self.impact.value} "
            f"| recovery={self.recovery.value} "
            f"| origin={self.origin.value} "
            f"| {self.message}"
        )