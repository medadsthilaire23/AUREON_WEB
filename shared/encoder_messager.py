# shared/encoder_messager.py
# ══════════════════════════════════════════════════════════════════════════════
# Canal de comunicación con Sentry.
#
# Recibe únicamente EncodedEvent — nunca datos crudos.
# El SDK de Sentry ya fue inicializado en app.py antes de create_app().
# Este módulo NO lo reinicializa — solo usa sentry_sdk.capture_message().
#
# Fail-closed:
#   Si el Breaker "encoder" está OPEN → descarta sin tocar la red.
#   Si el envío falla → incrementa el Breaker.
#   Tras 3 fallos consecutivos → Breaker abierto → cero envíos hasta recovery.
#
# Integración en app.py (Fase 2 — después del Conductor):
#   from shared.encoder_messager import configure_messager
#   configure_messager(conductor)
#
# Uso desde cualquier módulo:
#   from shared.encoder_messager import send
#   send(event)   # fire-and-forget
#
# Regla Arquitectónica:
#   Este módulo NO importa nada de products/.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import logging
import threading
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from shared.encoder import EncodedEvent

log = logging.getLogger("aureon.encoder_messager")

# Estado inyectado en Fase 2
_conductor    = None
_breaker_name = "encoder"   # nombre en BreakerRegistry


def configure_messager(conductor) -> None:
    """
    Fase 2 — Wiring.
    Registra el Breaker del Encoder en BreakerRegistry si no existe.

        from shared.encoder_messager import configure_messager
        configure_messager(conductor)
    """
    global _conductor
    _conductor = conductor

    # Registrar el Breaker del Encoder si no existe todavía
    from shared.control.registries.base import BreakerRegistry
    if _breaker_name not in BreakerRegistry:
        BreakerRegistry.get(
            _breaker_name,
            failure_threshold = 3,     # 3 fallos de envío → breaker abierto
            recovery_timeout  = 120.0, # 2 minutos hasta HALF_OPEN
        )

    log.info("[Messager] Conductor inyectado — breaker='%s'", _breaker_name)


# ══════════════════════════════════════════════════════════
# API PÚBLICA
# ══════════════════════════════════════════════════════════

def send(event: Optional["EncodedEvent"]) -> None:
    """
    Envía un EncodedEvent a Sentry de forma asíncrona.

    Descarta silenciosamente si:
        - event es None (encode() falló una regla)
        - El Breaker 'encoder' está OPEN
        - El SDK de Sentry no está disponible
    """
    if event is None:
        return

    # Breaker check — fail-closed
    from shared.control.registries.base import BreakerRegistry
    if _breaker_name in BreakerRegistry:
        breaker = BreakerRegistry.get(_breaker_name)
        result  = breaker.is_allowed()
        if not result.allowed:
            log.warning("[Messager] Breaker abierto — descartado: %s", event.code)
            return

    # Fire-and-forget
    threading.Thread(
        target = _send_to_sentry,
        args   = (event,),
        daemon = True,
        name   = f"messager-{event.code}",
    ).start()


# ══════════════════════════════════════════════════════════
# ENVÍO INTERNO
# ══════════════════════════════════════════════════════════

def _send_to_sentry(event: "EncodedEvent") -> None:
    """
    Corre en hilo daemon.
    Usa el SDK ya inicializado en app.py — no lo reinicializa.
    Si falla → notifica al Conductor y registra el fallo en el Breaker.
    """
    try:
        import sentry_sdk
    except ImportError:
        log.debug("[Messager] sentry_sdk no instalado — evento ignorado: %s", event.code)
        return

    try:
        sentry_dict = event.to_sentry_dict()

        with sentry_sdk.push_scope() as scope:
            scope.set_tag("aureon.code",    event.code)
            scope.set_extra("aureon.data",  sentry_dict)

            sentry_sdk.capture_message(
                event.code,   # mensaje opaco — nunca el meaning
                level = "info",
                scope = scope,
            )

        log.debug("[Messager] enviado → %s", event.code)

        # Éxito — si el breaker estaba en HALF_OPEN, cerrarlo
        _on_success()

    except Exception as exc:
        log.error("[Messager] fallo al enviar %s: %s", event.code, exc)
        _on_failure(event.code, str(exc))


# ══════════════════════════════════════════════════════════
# FEEDBACK AL BREAKER Y AL CONDUCTOR
# ══════════════════════════════════════════════════════════

def _on_success() -> None:
    from shared.control.registries.base import BreakerRegistry
    if _breaker_name in BreakerRegistry:
        BreakerRegistry.get(_breaker_name).reset()


def _on_failure(code: str, reason: str) -> None:
    # 1. Incrementar el breaker
    from shared.control.registries.base import BreakerRegistry
    if _breaker_name in BreakerRegistry:
        breaker = BreakerRegistry.get(_breaker_name)
        # Simular un fallo en la función vacía para que el breaker lo cuente
        try:
            breaker.call(_raise_dummy)
        except Exception:
            pass  # el breaker ya contó el fallo internamente

    # 2. Notificar al Conductor async
    if _conductor is None:
        return

    conductor = _conductor

    def _fire() -> None:
        try:
            from shared.control.alert import Alert, Impact, Recovery, Origin
            conductor.receive(Alert(
                code     = "ENCODER_MESSAGER_FAILED",
                message  = f"Fallo al enviar {code} a Sentry: {reason}",
                impact   = Impact.MODULE,
                recovery = Recovery.RUNTIME,
                origin   = Origin.SYSTEM,
                module   = "encoder_messager",
                context  = {"code": code, "reason": reason},
            ))
        except Exception as exc:
            log.debug("[Messager] Notificación al Conductor falló (ignorado): %s", exc)

    threading.Thread(target=_fire, daemon=True, name="messager-notify").start()


def _raise_dummy():
    raise RuntimeError("sentry_send_failed")