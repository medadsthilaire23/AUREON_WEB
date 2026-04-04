# shared/control/gates/http_gate.py
# ══════════════════════════════════════════════════════════════════════════════
# HTTP GATE — AUREON Sistema de Control v3.0
#
# Punto de entrada de toda request HTTP.
# Registrado en before_request vía register_http_gate() (auth_middleware.py).
#
# Contrato público (lo que auth_middleware.py espera):
#   result = gate.scan(request)   → ScanResult(event_id, allowed, op_id)
#   gate.record_pending(event_id, op_id)
#   gate.record_ok(event_id, op_id)
#   gate.record_fail(event_id, op_id, error="...")
#   gate.wire_registry(event_registry)
#
# Flujo en before_request:
#   1. scan(request) → genera event_id, registra CREATE en EventRegistry
#   2. Si gate CLOSED → ScanResult(allowed=False) → middleware retorna 503
#   3. Si gate OPEN   → ScanResult(allowed=True)  → g.event_id disponible
#
# Regla arquitectónica:
#   Este módulo NO importa nada de products/.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

from shared.control.gates.base  import GateBase
from shared.control.gate        import GateResult
from shared.control.event_id    import generate_event_id
from shared.control.event_state import EventState
from shared.control.alert       import Impact, Recovery, Origin

if TYPE_CHECKING:
    from shared.control.registries.base import EventRegistryType

log = logging.getLogger("aureon.control.gates.http")


# ══════════════════════════════════════════════════════════════════════════════
# RESULTADO DEL SCAN
# Contrato que auth_middleware.py espera en result.allowed y result.event_id
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ScanResult:
    """
    Resultado del escaneo de una request HTTP.

    event_id → ID único de 17 dígitos generado para esta request
    allowed  → False si el gate está CLOSED — middleware retorna 503
    op_id    → operación raíz detectada desde el path ("OP001", "OP003", ...)
    """
    event_id: str
    allowed:  bool
    op_id:    str


# ══════════════════════════════════════════════════════════════════════════════
# RESOLUCIÓN DE OP_ID DESDE PATH
# ══════════════════════════════════════════════════════════════════════════════

_URL_OP_MAP: list[tuple[str, str, str]] = [
    ("POST",   "/auth/login",                    "OP001"),
    ("POST",   "/auth/register",                 "OP002"),
    ("GET",    "/auth/oauth/google",              "OP003"),
    ("GET",    "/auth/oauth/google/callback",     "OP003"),
    ("GET",    "/auth/oauth/github",              "OP004"),
    ("GET",    "/auth/oauth/github/callback",     "OP004"),
    ("POST",   "/auth/passkey/register/begin",    "OP005"),
    ("POST",   "/auth/passkey/register/complete", "OP005"),
    ("POST",   "/auth/passkey/login/begin",       "OP006"),
    ("POST",   "/auth/passkey/login/complete",    "OP006"),
    ("POST",   "/auth/logout",                    "OP008"),
    ("POST",   "/auth/session/refresh",           "OP008"),
    ("DELETE", "/auth/session",                   "OP008"),
]

_DEFAULT_OP         = "OP001"
_ALLOWED_METHODS    = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
_SUSPICIOUS_HEADERS = {"x-forwarded-host", "x-original-url", "x-rewrite-url"}


def _resolve_op_id(method: str, path: str) -> str:
    for m, prefix, op_id in _URL_OP_MAP:
        if m == method and path.startswith(prefix):
            return op_id
    return _DEFAULT_OP


# ══════════════════════════════════════════════════════════════════════════════
# HTTP GATE
# ══════════════════════════════════════════════════════════════════════════════

class HttpGate(GateBase):
    """
    Gate de entrada HTTP. Una sola instancia para toda la app.

    OPEN   → acepta requests
    CLOSED → bloquea todo con 503
    """

    def __init__(self, name: str = "HttpGate"):
        super().__init__(name=name, description="Punto de entrada HTTP")
        self._registry: Optional["EventRegistryType"] = None
        self._enabled  = True
        self._lock     = threading.Lock()

    # ── Wiring ────────────────────────────────────────────────────────────────

    def wire_registry(self, registry: "EventRegistryType") -> None:
        """Inyecta el EventRegistry. Llamado desde wiring.py en Fase 2."""
        self._registry = registry
        log.info("[HttpGate] EventRegistry inyectado")

    # ── API principal — contrato de auth_middleware.py ────────────────────────

    def scan(self, request) -> ScanResult:
        """
        Escanea una request HTTP entrante.

        1. Genera event_id (timestamp compacto)
        2. Detecta op_id raíz desde path/método
        3. Si CLOSED → ScanResult(allowed=False) — no registra en EventRegistry
        4. Registra CREATE en EventRegistry
        5. Retorna ScanResult(allowed=True, event_id, op_id)

        Nunca lanza excepción — siempre retorna ScanResult (fail-open).
        """
        event_id = generate_event_id()

        try:
            op_id = _resolve_op_id(request.method, request.path)

            with self._lock:
                is_open = self._enabled

            if not is_open:
                log.warning(
                    "[HttpGate] CLOSED — bloqueando method=%s path=%s event=%s",
                    request.method, request.path, event_id,
                )
                return ScanResult(event_id=event_id, allowed=False, op_id=op_id)

            # Registrar CREATE en EventRegistry
            if self._registry is not None:
                self._registry.record(
                    event_id = event_id,
                    op_id    = op_id,
                    state    = EventState.CREATE,
                    gate     = self.name,
                )

            self._pass_count += 1
            log.debug(
                "[HttpGate] CREATE event=%s op=%s method=%s path=%s",
                event_id, op_id, request.method, request.path,
            )
            return ScanResult(event_id=event_id, allowed=True, op_id=op_id)

        except Exception as e:
            # Fail-open — el gate nunca debe romper la request
            log.error("[HttpGate] error en scan: %s", e)
            return ScanResult(event_id=event_id, allowed=True, op_id=_DEFAULT_OP)

    # ── record_* — trazabilidad de cada paso HTTP ─────────────────────────────

    def record_pending(self, event_id: str, op_id: str) -> None:
        """Marca el paso HTTP como en tránsito."""
        if self._registry is None:
            return
        try:
            self._registry.transition(event_id, op_id, EventState.PENDING)
        except Exception as e:
            log.error("[HttpGate] record_pending error: %s", e)

    def record_ok(self, event_id: str, op_id: str) -> None:
        """Marca el paso HTTP como completado exitosamente."""
        if self._registry is None:
            return
        try:
            self._registry.transition(event_id, op_id, EventState.FINISH)
        except Exception as e:
            log.error("[HttpGate] record_ok error: %s", e)

    def record_fail(self, event_id: str, op_id: str, error: str = "") -> None:
        """
        Marca el paso HTTP como fallido.
        El Conductor lo detectará en el próximo scan_registry().
        """
        if self._registry is None:
            return
        try:
            self._registry.transition(event_id, op_id, EventState.FAILED, error=error)
            self._fail_count += 1
            log.warning("[HttpGate] FAILED event=%s op=%s error=%s", event_id, op_id, error)
        except Exception as e:
            log.error("[HttpGate] record_fail error: %s", e)

    # ── Estado — llamado por Breaker/Conductor ────────────────────────────────

    def set_enabled(self, value: bool) -> None:
        with self._lock:
            self._enabled = value
        log.warning("[HttpGate] set_enabled=%s", value)

    def close(self) -> None:
        self.set_enabled(False)

    def open(self) -> None:
        self.set_enabled(True)

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._enabled

    # ── GateBase.validate (requerido por la clase base) ───────────────────────

    def validate(self, value: Any, **kwargs) -> GateResult:
        """
        Verifica si el gate está abierto.
        Para HttpGate el punto de entrada real es scan() —
        este método existe para satisfacer el contrato de GateBase.
        """
        with self._lock:
            is_open = self._enabled

        if not is_open:
            self._fail_count += 1
            alert = self._alert(
                code     = "HTTP_GATE_CLOSED",
                message  = "HttpGate CLOSED — sistema HTTP no disponible",
                impact   = Impact.GLOBAL,
                recovery = Recovery.RUNTIME,
                origin   = Origin.SYSTEM,
                context  = {},
            )
            return GateResult.fail(alert=alert, value=value)

        self._pass_count += 1
        return GateResult.ok(value=value)

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        with self._lock:
            enabled = self._enabled
        return {
            "name":       self.name,
            "enabled":    enabled,
            "pass_count": self._pass_count,
            "fail_count": self._fail_count,
        }