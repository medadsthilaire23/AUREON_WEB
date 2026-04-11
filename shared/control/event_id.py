# shared/control/event_id.py
# ══════════════════════════════════════════════════════════════════════════════
# Motor de Identidad — AUREON v4.0
#
# El event_id es el ADN digital de cada evento. Es inmutable en su origen
# (timestamp) y acumulativo en su trayectoria (rastro de gates).
#
# Filosofía v4.0: "El papel no sabe qué dice el semáforo"
#   - La IDENTIDAD (event_id) es inmutable — nace con el timestamp
#   - El ESTADO (event_state) es volátil — vive en el Registry
#   - El RASTRO (path aliases) crece a medida que el evento atraviesa gates
#
# Formato del event_id:
#   BASE:     YYYYMMDDHHMMSSMMM          (17 dígitos — 1000 ranuras/segundo)
#   EVOLUCIÓN: BASE_H_D_M               (base + aliases de gates atravesados)
#
# Ejemplos:
#   20260408112034847                   ← evento recién creado (HttpGate)
#   20260408112034847_H                 ← pasó por HttpGate
#   20260408112034847_H_D               ← pasó por HttpGate + DbGate
#   20260408112034847_H_D_M             ← pasó por HttpGate + DbGate + ModuleGate
#   20260408112034847_H_D_M_S           ← SecurityGate detectó anomalía
#
# Aliases de gates (tabla central — un solo lugar para cambiar):
#   H  → HttpGate
#   D  → DbGate
#   M  → ModuleGate
#   B  → BootGate
#   S  → SecurityGate  (v4.0)
#   LG → LoginGate     (v4.0 Sub-Gate)
#   AG → AccessGate    (v4.0 Sub-Gate)
#   VG → VerificacionGate (v4.0 Sub-Gate)
#
# Prefijos de anomalía (no son aliases de gates — son prefijos de diagnóstico):
#   AD, UR, FL, GB, FA, TM, SA, XX
#   Estos prefijos se registran en el EventRegistry como op_id de anomalía,
#   NO como sufijos del event_id.
#
# Regla arquitectónica:
#   Este módulo NO importa nada de products/ ni de otros módulos de control.
#   Es la base — no tiene dependencias.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from datetime import datetime
from typing import Optional


# ══════════════════════════════════════════════════════════════════════════════
# ALIASES DE GATES — tabla central
# ══════════════════════════════════════════════════════════════════════════════

GATE_ALIASES: dict[str, str] = {
    # Nivel 1 — Gates de Infraestructura
    "HttpGate":         "H",
    "DbGate":           "D",
    "ModuleGate":       "M",
    "BootGate":         "B",

    # Nivel 2 — Sub-Gates de Dominio (v4.0)
    "LoginGate":        "LG",
    "AccessGate":       "AG",
    "VerificacionGate": "VG",

    # Nivel 3 — Gates Especiales (v4.0)
    "SecurityGate":     "S",

    # Feature flags de auth
    "oauth_google":     "OG",
    "oauth_github":     "OGH",
    "passkey_login":    "PL",
    "registration":     "R",
}

# Índice inverso: alias → nombre completo del gate
ALIAS_TO_GATE: dict[str, str] = {v: k for k, v in GATE_ALIASES.items()}


def gate_alias(gate_name: str) -> str:
    """
    Resuelve el alias corto de un gate.
    Fallback: primeras 3 letras en mayúscula — nunca rompe el sistema.

    Ejemplos:
        gate_alias("HttpGate")   → "H"
        gate_alias("DbGate")     → "D"
        gate_alias("SecurityGate") → "S"
        gate_alias("NuevoGate")  → "NUE"   ← fallback automático
    """
    return GATE_ALIASES.get(gate_name, gate_name[:3].upper())


def gate_from_alias(alias: str) -> str:
    """
    Resuelve el nombre completo desde un alias.
    Retorna el alias mismo si no está registrado.

    Ejemplos:
        gate_from_alias("H")  → "HttpGate"
        gate_from_alias("D")  → "DbGate"
        gate_from_alias("LG") → "LoginGate"
    """
    return ALIAS_TO_GATE.get(alias, alias)


# ══════════════════════════════════════════════════════════════════════════════
# GENERACIÓN DE ID BASE
# ══════════════════════════════════════════════════════════════════════════════

def generate_event_id() -> str:
    """
    Genera el ID base de un evento — timestamp de 17 dígitos.

    Formato: YYYYMMDDHHMMSSMMM
    Garantiza 1,000 ranuras de identidad por segundo.
    Ordenable cronológicamente sin campos extra.

    Ejemplo:
        20260408112034847

    Uso:
        from shared.control.event_id import generate_event_id
        event_id = generate_event_id()
    """
    now = datetime.now()
    ms  = now.microsecond // 1000
    return now.strftime("%Y%m%d%H%M%S") + f"{ms:03d}"


# ══════════════════════════════════════════════════════════════════════════════
# EVOLUCIÓN DEL ID — tatuar el rastro de gates
# ══════════════════════════════════════════════════════════════════════════════

def evolve_id(current_event_id: str, gate_name: str) -> str:
    """
    Tatúa el alias de un gate al event_id existente.
    El ID crece a medida que el evento atraviesa puertas.

    Este es el corazón del "Rastro de Puertas" (Path Aliases).
    El gate_resolver.py llama esta función en cada validación exitosa.

    Parámetros:
        current_event_id — el event_id actual (base o ya evolucionado)
        gate_name        — nombre del gate que acaba de ser atravesado

    Retorna:
        El event_id con el nuevo alias tatuado al final.
        Nunca lanza excepción — si algo falla retorna el ID sin cambios.

    Ejemplos:
        evolve_id("20260408112034847", "HttpGate")
        → "20260408112034847_H"

        evolve_id("20260408112034847_H", "DbGate")
        → "20260408112034847_H_D"

        evolve_id("20260408112034847_H_D", "ModuleGate")
        → "20260408112034847_H_D_M"

        evolve_id("20260408112034847_H_D_M", "SecurityGate")
        → "20260408112034847_H_D_M_S"
    """
    try:
        alias = gate_alias(gate_name)
        return f"{current_event_id}_{alias}"
    except Exception:
        return current_event_id


def build_child_event_id(parent_event_id: str, gate_name: str) -> str:
    """
    Alias de evolve_id() — mantiene compatibilidad con v3.x.

    Uso en DbGate.scan() y ModuleGate.call():
        child_id = build_child_event_id(g.event_id, "DbGate")
        # → "20260408112034847_H_D"
    """
    return evolve_id(parent_event_id, gate_name)


# ══════════════════════════════════════════════════════════════════════════════
# ANÁLISIS DEL RASTRO
# ══════════════════════════════════════════════════════════════════════════════

def parse_event_path(event_id: str) -> dict:
    """
    Descompone un event_id en sus partes: base temporal y rastro de gates.

    Retorna:
        {
            "root":        "20260408112034847",   ← ID base inmutable
            "path":        ["H", "D", "M"],       ← aliases de gates atravesados
            "gates":       ["HttpGate", "DbGate", "ModuleGate"],  ← nombres completos
            "depth":       3,                     ← profundidad del rastro
            "raw":         "20260408112034847_H_D_M"
        }

    Ejemplos:
        parse_event_path("20260408112034847")
        → { "root": "20260408112034847", "path": [], "gates": [], "depth": 0, ... }

        parse_event_path("20260408112034847_H_D_M")
        → { "root": "20260408112034847", "path": ["H","D","M"],
            "gates": ["HttpGate","DbGate","ModuleGate"], "depth": 3, ... }
    """
    parts = event_id.split("_")
    root  = parts[0]
    path  = parts[1:] if len(parts) > 1 else []
    gates = [gate_from_alias(alias) for alias in path]

    return {
        "root":  root,
        "path":  path,
        "gates": gates,
        "depth": len(path),
        "raw":   event_id,
    }


def get_root_id(event_id: str) -> str:
    """Extrae el ID base (17 dígitos) ignorando el rastro de gates."""
    return event_id.split("_")[0]


def get_path_aliases(event_id: str) -> list[str]:
    """Retorna la lista de aliases de gates del rastro."""
    parts = event_id.split("_")
    return parts[1:] if len(parts) > 1 else []


def get_last_gate(event_id: str) -> Optional[str]:
    """
    Retorna el nombre del último gate que tocó el evento.
    None si el evento está en su estado base (sin rastro).

    Ejemplo:
        get_last_gate("20260408112034847_H_D") → "DbGate"
        get_last_gate("20260408112034847")     → None
    """
    aliases = get_path_aliases(event_id)
    if not aliases:
        return None
    return gate_from_alias(aliases[-1])


def shares_root(event_id_a: str, event_id_b: str) -> bool:
    """
    True si dos event_ids comparten el mismo root — son del mismo request.

    Ejemplo:
        shares_root("20260408112034847_H", "20260408112034847_H_D") → True
        shares_root("20260408112034847_H", "20260408112034848_H")   → False
    """
    return get_root_id(event_id_a) == get_root_id(event_id_b)


# ══════════════════════════════════════════════════════════════════════════════
# TIMESTAMPS — análisis temporal del ID base
# ══════════════════════════════════════════════════════════════════════════════

def parse_event_id(event_id: str) -> dict:
    """
    Parsea el ID base y retorna sus componentes temporales.
    Ignora el rastro de gates si lo tiene.

    Retorna:
        {
            "year": 2026, "month": 4, "day": 8,
            "hour": 11, "minute": 20, "second": 34, "ms": 847,
            "raw": "20260408112034847"
        }
    """
    root = get_root_id(event_id)

    if len(root) != 17 or not root.isdigit():
        raise ValueError(
            f"ID de evento inválido: '{root}'. "
            f"Formato esperado: YYYYMMDDHHMMSSMMM (17 dígitos)"
        )

    return {
        "year":   int(root[0:4]),
        "month":  int(root[4:6]),
        "day":    int(root[6:8]),
        "hour":   int(root[8:10]),
        "minute": int(root[10:12]),
        "second": int(root[12:14]),
        "ms":     int(root[14:17]),
        "raw":    root,
    }


def event_id_to_datetime(event_id: str) -> datetime:
    """Convierte un event_id a datetime. Ignora el rastro de gates."""
    parts = parse_event_id(event_id)
    return datetime(
        year        = parts["year"],
        month       = parts["month"],
        day         = parts["day"],
        hour        = parts["hour"],
        minute      = parts["minute"],
        second      = parts["second"],
        microsecond = parts["ms"] * 1000,
    )


def event_id_age_ms(event_id: str) -> int:
    """
    Milisegundos transcurridos desde que se generó el evento.
    Útil para el Timer y el Conductor para detectar eventos lentos.
    """
    created_at = event_id_to_datetime(event_id)
    delta      = datetime.now() - created_at
    return int(delta.total_seconds() * 1000)


def format_event_id_human(event_id: str) -> str:
    """
    Formato legible para logs y dashboard.

    Ejemplo:
        "20260408112034847_H_D_M"
        → "08/04/2026 11:20:34.847 [H→D→M]"
    """
    try:
        p     = parse_event_id(event_id)
        path  = get_path_aliases(event_id)
        ts    = f"{p['day']:02d}/{p['month']:02d}/{p['year']} {p['hour']:02d}:{p['minute']:02d}:{p['second']:02d}.{p['ms']:03d}"
        trail = f" [{' → '.join(path)}]" if path else ""
        return f"{ts}{trail}"
    except Exception:
        return event_id