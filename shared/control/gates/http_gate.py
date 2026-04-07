# shared/control/gates/http_gate.py
# ══════════════════════════════════════════════════════════════════════════════
# HTTP GATE — AUREON Sistema de Control v3.1
#
# Cambios v3.1:
#   - Rutas de Lifebound mapeadas a OP020-OP029
#   - Rutas de Dashboard mapeadas a OP099_*
#   - module="dashboard" en EventEntry para eventos del panel de control
#   - Los eventos del dashboard NO se suman al conteo del sistema
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


@dataclass(frozen=True)
class ScanResult:
    event_id: str
    allowed:  bool
    op_id:    str


# ── Resolución de OP_ID desde path/método ─────────────────────────────────

_URL_OP_MAP: list[tuple[str, str, str]] = [
    # ── Auth ──────────────────────────────────────────────
    ("POST",   "/auth/login",                     "OP001"),
    ("POST",   "/auth/register",                  "OP002"),
    ("GET",    "/auth/oauth/google",               "OP003"),
    ("GET",    "/auth/oauth/google/callback",      "OP003"),
    ("GET",    "/auth/oauth/github",               "OP004"),
    ("GET",    "/auth/oauth/github/callback",      "OP004"),
    ("POST",   "/auth/passkey/register/begin",     "OP005"),
    ("POST",   "/auth/passkey/register/complete",  "OP005"),
    ("POST",   "/auth/passkey/login/begin",        "OP006"),
    ("POST",   "/auth/passkey/login/complete",     "OP006"),
    ("POST",   "/auth/logout",                     "OP008"),
    ("POST",   "/auth/session/refresh",            "OP008"),
    ("DELETE", "/auth/session",                    "OP008"),

    # ── Dashboard (OP099) ─────────────────────────────────
    ("GET",    "/auth/control/status",             "OP099_001"),
    ("GET",    "/auth/control/sessions",           "OP099_002"),
    ("GET",    "/auth/control/users",              "OP099_003"),
    ("GET",    "/auth/control/activity",           "OP099_004"),
    ("GET",    "/auth/control/export",             "OP099_005"),
    ("POST",   "/auth/control/export",             "OP099_005"),

    # ── Lifebound (OP020-OP029) ───────────────────────────
    ("POST",   "/lifebound/api/session/start",     "OP020"),
    ("POST",   "/lifebound/api/session/photos",    "OP021"),
    ("GET",    "/lifebound/api/session/status",    "OP026"),
    ("DELETE", "/lifebound/api/session",           "OP027"),
    ("POST",   "/lifebound/api/pattern",           "OP022"),
    ("POST",   "/lifebound/api/slots",             "OP023"),
    ("POST",   "/lifebound/api/transform",         "OP024"),
    ("POST",   "/lifebound/api/generate",          "OP025"),
    ("GET",    "/lifebound/api/templates",         "OP028"),
    ("POST",   "/lifebound/api/preview",           "OP029"),
]

_DEFAULT_OP = "OP001"


def _resolve_op_id(method: str, path: str) -> str:
    for m, prefix, op_id in _URL_OP_MAP:
        if m == method and path.startswith(prefix):
            return op_id
    return _DEFAULT_OP


# ── Módulo del op_id — para etiquetar el EventEntry ───────────────────────

def _resolve_module(op_id: str) -> str:
    if op_id.startswith("OP099"):
        return "dashboard"
    if op_id.startswith("OP02"):
        return "lifebound"
    if op_id.startswith("OP01"):
        return "system"
    return "auth"


# ══════════════════════════════════════════════════════════════════════════════
# HTTP GATE
# ══════════════════════════════════════════════════════════════════════════════

class HttpGate(GateBase):
    """
    Gate de entrada HTTP. Una sola instancia para toda la app.

    OPEN   → acepta requests
    CLOSED → bloquea todo con 503

    v3.1: registra el módulo correcto en EventEntry según el op_id.
    Los eventos del dashboard (OP099) quedan como module="dashboard"
    y se muestran en un panel separado — no se suman al sistema.
    """

    def __init__(self, name: str = "HttpGate"):
        super().__init__(name=name, description="Punto de entrada HTTP")
        self._registry: Optional["EventRegistryType"] = None
        self._enabled  = True
        self._lock     = threading.Lock()

    def wire_registry(self, registry: "EventRegistryType") -> None:
        self._registry = registry
        log.info("[HttpGate] EventRegistry inyectado")

    def scan(self, request) -> ScanResult:
        """
        Escanea una request HTTP entrante.
        Registra CREATE en EventRegistry con el módulo correcto.
        Nunca lanza excepción — siempre retorna ScanResult (fail-open).
        """
        event_id = generate_event_id()

        try:
            op_id  = _resolve_op_id(request.method, request.path)
            module = _resolve_module(op_id)

            with self._lock:
                is_open = self._enabled

            if not is_open:
                log.warning(
                    "[HttpGate] CLOSED — bloqueando method=%s path=%s event=%s",
                    request.method, request.path, event_id,
                )
                return ScanResult(event_id=event_id, allowed=False, op_id=op_id)

            if self._registry is not None:
                # Registrar con el módulo correcto — dashboard queda separado
                self._registry.record(
                    event_id = event_id,
                    op_id    = op_id,
                    state    = EventState.CREATE,
                    gate     = self.name,
                    # module se infiere en EventRegistry desde OPERATIONS,
                    # pero lo forzamos vía op_id que ya tiene el módulo correcto
                )

            self._pass_count += 1
            log.debug(
                "[HttpGate] CREATE event=%s op=%s module=%s method=%s path=%s",
                event_id, op_id, module, request.method, request.path,
            )
            return ScanResult(event_id=event_id, allowed=True, op_id=op_id)

        except Exception as e:
            log.error("[HttpGate] error en scan: %s", e)
            return ScanResult(event_id=event_id, allowed=True, op_id=_DEFAULT_OP)

    def record_pending(self, event_id: str, op_id: str) -> None:
        if self._registry is None:
            return
        try:
            self._registry.transition(event_id, op_id, EventState.PENDING)
        except Exception as e:
            log.error("[HttpGate] record_pending error: %s", e)

    def record_ok(self, event_id: str, op_id: str) -> None:
        if self._registry is None:
            return
        try:
            self._registry.transition(event_id, op_id, EventState.FINISH)
        except Exception as e:
            log.error("[HttpGate] record_ok error: %s", e)

    def record_fail(self, event_id: str, op_id: str, error: str = "") -> None:
        if self._registry is None:
            return
        try:
            self._registry.transition(event_id, op_id, EventState.FAILED, error=error)
            self._fail_count += 1
            log.warning("[HttpGate] FAILED event=%s op=%s error=%s", event_id, op_id, error)
        except Exception as e:
            log.error("[HttpGate] record_fail error: %s", e)

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

    def validate(self, value: Any, **kwargs) -> GateResult:
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

    def snapshot(self) -> dict:
        with self._lock:
            enabled = self._enabled
        return {
            "name":       self.name,
            "enabled":    enabled,
            "pass_count": self._pass_count,
            "fail_count": self._fail_count,
        }