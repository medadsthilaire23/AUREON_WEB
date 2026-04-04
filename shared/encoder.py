# shared/encoder.py
# ══════════════════════════════════════════════════════════════════════════════
# El Órgano de sanitización.
#
# Recibe un evento (meaning + datos crudos), aplica las 4 Reglas de Oro
# en orden estricto y, si pasa todas, devuelve un EncodedEvent listo
# para que el Messager lo envíe a Sentry.
#
# 4 Reglas de Oro:
#   1. EXISTENCIA    — el meaning debe estar en REVERSE del Codebook
#   2. PROHIBICIÓN   — ningún campo del payload en FORBIDDEN_FIELDS
#   3. SUSTITUCIÓN   — todos los campos en SUBSTITUTIONS son transformados
#   4. EJECUCIÓN     — el EncodedEvent debe ser serializable
#
# Si falla cualquier regla → devuelve None y notifica al Conductor
# de forma asíncrona (fire-and-forget) para no introducir latencia.
#
# Integración en app.py (Fase 2 — después del Conductor):
#   from shared.encoder import configure_encoder
#   configure_encoder(conductor)
#
# Uso desde cualquier módulo:
#   from shared.encoder import encode
#   event = encode("oauth_google_success", {"email": email})
#   if event:
#       send(event)   # encoder_messager.send()
#
# Regla Arquitectónica:
#   Este módulo NO importa nada de products/.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from shared.codebook import REVERSE, SUBSTITUTIONS, FORBIDDEN_FIELDS

log = logging.getLogger("aureon.encoder")

# Conductor inyectado en Fase 2
_conductor = None


def configure_encoder(conductor) -> None:
    """
    Fase 2 — Wiring.
    Inyecta el Conductor para notificaciones async.

        from shared.encoder import configure_encoder
        configure_encoder(conductor)
    """
    global _conductor
    _conductor = conductor
    log.info("[Encoder] Conductor inyectado")


# ══════════════════════════════════════════════════════════
# ENCODED EVENT — resultado de un encode exitoso
# ══════════════════════════════════════════════════════════

@dataclass(frozen=True)
class EncodedEvent:
    """
    Evento ya sanitizado y codificado.
    Solo contiene el código opaco — el meaning nunca sale del sistema.
    """
    code:      str              # Código opaco ej. "GCB2Z7K"
    meaning:   str              # Significado interno ej. "oauth_google_success"
    data:      dict[str, Any]   # Datos ya sanitizados
    timestamp: float = field(default_factory=time.time)

    def to_sentry_dict(self) -> dict:
        """
        Formato final hacia Sentry.
        El campo 'event' es el código opaco — nunca el meaning.
        """
        return {
            "event":     self.code,
            "timestamp": self.timestamp,
            **self.data,
        }


# ══════════════════════════════════════════════════════════
# API PÚBLICA
# ══════════════════════════════════════════════════════════

def encode(meaning: str, data: dict[str, Any] | None = None) -> Optional[EncodedEvent]:
    """
    Punto de entrada principal.

    Parámetros:
        meaning — nombre legible del evento, debe existir en REVERSE
                  ej. "oauth_google_success"
        data    — datos del evento (crudos, sin sanitizar)

    Retorna:
        EncodedEvent si pasa las 4 reglas.
        None si es descartado — el motivo se notifica al Conductor async.
    """
    raw_data = dict(data or {})

    # ── Regla 1: EXISTENCIA ──────────────────────────────────────────────────
    code = REVERSE.get(meaning)
    if code is None:
        _notify_async(
            code    = "ENCODER_CODEBOOK_MISS",
            message = f"Meaning desconocido: '{meaning}'",
            module  = "encoder",
            context = {"meaning": meaning},
        )
        log.warning("[Encoder] R1 MISS — meaning desconocido: %s", meaning)
        return None

    # ── Regla 2: PROHIBICIÓN ─────────────────────────────────────────────────
    forbidden_found = FORBIDDEN_FIELDS & raw_data.keys()
    if forbidden_found:
        _notify_async(
            code    = "ENCODER_FORBIDDEN_DETECTED",
            message = f"Campos prohibidos en '{meaning}': {sorted(forbidden_found)}",
            module  = "encoder",
            context = {"meaning": meaning, "fields": sorted(forbidden_found)},
        )
        log.warning("[Encoder] R2 FORBIDDEN — %s en '%s'", forbidden_found, meaning)
        return None

    # ── Regla 3: SUSTITUCIÓN ─────────────────────────────────────────────────
    try:
        sanitized = _substitute(raw_data)
    except Exception as exc:
        _notify_async(
            code    = "ENCODER_SANITIZATION_FAILED",
            message = f"Error de sustitución en '{meaning}': {exc}",
            module  = "encoder",
            context = {"meaning": meaning, "error": str(exc)},
        )
        log.error("[Encoder] R3 SANITIZATION_ERR — '%s': %s", meaning, exc)
        return None

    # ── Regla 4: EJECUCIÓN ───────────────────────────────────────────────────
    try:
        event = EncodedEvent(code=code, meaning=meaning, data=sanitized)
        event.to_sentry_dict()   # fuerza serialización — detecta objetos no-JSON
    except Exception as exc:
        _notify_async(
            code    = "ENCODER_EXECUTION_FAILED",
            message = f"Error de ejecución en '{meaning}': {exc}",
            module  = "encoder",
            context = {"meaning": meaning, "error": str(exc)},
        )
        log.error("[Encoder] R4 EXECUTION_ERR — '%s': %s", meaning, exc)
        return None

    # ── Éxito ────────────────────────────────────────────────────────────────
    log.debug("[Encoder] OK — %s → %s", meaning, code)
    return event


# ══════════════════════════════════════════════════════════
# SANITIZACIÓN
# ══════════════════════════════════════════════════════════

def _substitute(data: dict[str, Any]) -> dict[str, Any]:
    """
    Aplica SUBSTITUTIONS a cada campo listado en el codebook.
    Campos no listados pasan tal cual.
    Lanza ValueError si una transformación retorna None.
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        transform = SUBSTITUTIONS.get(key)
        if transform is None:
            result[key] = value
        else:
            transformed = transform(str(value) if value is not None else "")
            if transformed is None:
                raise ValueError(f"Sustitución de '{key}' retornó None")
            result[key] = transformed
    return result


# ══════════════════════════════════════════════════════════
# NOTIFICACIÓN ASYNC AL CONDUCTOR
# ══════════════════════════════════════════════════════════

def _notify_async(
    code:    str,
    message: str,
    module:  str,
    context: dict,
) -> None:
    """
    Fire-and-forget — lanza un hilo daemon que llama a conductor.receive().
    No bloquea al caller bajo ninguna circunstancia.
    Si el hilo falla, la excepción se captura y se descarta.
    """
    if _conductor is None:
        log.debug("[Encoder] Sin Conductor — evento local: %s", code)
        return

    conductor = _conductor  # captura local para el closure

    def _fire() -> None:
        try:
            from shared.control.alert import Alert, Impact, Recovery, Origin

            # Clasificar por código
            if "FORBIDDEN" in code:
                impact   = Impact.REQUEST
                recovery = Recovery.RUNTIME
                origin   = Origin.EXTERNAL
            elif "SANITIZATION" in code or "EXECUTION" in code:
                impact   = Impact.MODULE
                recovery = Recovery.RUNTIME
                origin   = Origin.INTERNAL
            else:  # CODEBOOK_MISS
                impact   = Impact.REQUEST
                recovery = Recovery.AUTO
                origin   = Origin.INTERNAL

            alert = Alert(
                code     = code,
                message  = message,
                impact   = impact,
                recovery = recovery,
                origin   = origin,
                module   = module,
                context  = context,
            )
            conductor.receive(alert)
        except Exception as exc:
            log.debug("[Encoder] Notificación async falló (ignorado): %s", exc)

    threading.Thread(target=_fire, daemon=True, name="encoder-notify").start()