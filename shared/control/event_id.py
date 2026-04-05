# shared/control/event_id.py
# ══════════════════════════════════════════════════════════════════════════════
# Generador del ID de evento — AUREON Sistema de Control v3.1
#
# Cambios v3.1:
#   - GATE_ALIASES — tabla central de alias cortos por gate
#   - gate_alias() — resuelve alias con fallback automático
#   - build_child_event_id() — construye el ID hijo acumulando el camino
#
# Formato base (sin cambios):
#     YYYYMMDDHHMMSSMMM
#     20260404143022847
#
# Formato con camino (nuevo):
#     20260404143022847_H          ← HttpGate (raíz, lo pone el Tracer)
#     20260404143022847_H_D        ← DbGate hijo
#     20260404143022847_H_D_M      ← ModuleGate nieto
#     20260404143022847_H_D_M_H    ← HttpGate bisnieto (callback interno)
#
# Regla arquitectónica:
#     Este módulo NO importa nada de products/ ni de otros
#     módulos de control. Es la base — no tiene dependencias.
# ══════════════════════════════════════════════════════════════════════════════

from datetime import datetime


# ══════════════════════════════════════════════════════════
# ALIAS DE GATES
#
# Tabla central — un solo lugar para cambiar.
# Los gates NO conocen su propio alias.
# Fallback automático: primeras 3 letras en mayúscula.
# ══════════════════════════════════════════════════════════

GATE_ALIASES: dict[str, str] = {
    # Gates de infraestructura
    "HttpGate":     "H",
    "DbGate":       "D",
    "ModuleGate":   "M",
    "BootGate":     "B",

    # Gates de autenticación (feature flags)
    "oauth_google":  "OG",
    "oauth_github":  "OGH",
    "passkey_login": "PL",
    "registration":  "R",
}


def gate_alias(gate_name: str) -> str:
    """
    Resuelve el alias corto de un gate.

    Si el gate no tiene alias registrado, usa las primeras 3 letras
    en mayúscula como fallback — nunca rompe el sistema.

    Ejemplos:
        gate_alias("HttpGate")   → "H"
        gate_alias("DbGate")     → "D"
        gate_alias("ModuleGate") → "M"
        gate_alias("NuevoGate")  → "NUE"   ← fallback automático
    """
    return GATE_ALIASES.get(gate_name, gate_name[:3].upper())


# ══════════════════════════════════════════════════════════
# CONSTRUCCIÓN DE EVENT_ID HIJO
#
# El event_id padre ya contiene el camino acumulado.
# El hijo simplemente añade su alias al final.
#
# Ejemplos:
#   padre = "20260404143022847"       gate = "DbGate"
#   hijo  = "20260404143022847_D"
#
#   padre = "20260404143022847_D"     gate = "ModuleGate"
#   hijo  = "20260404143022847_D_M"
#
#   padre = "20260404143022847_D_M"   gate = "HttpGate"
#   hijo  = "20260404143022847_D_M_H"
# ══════════════════════════════════════════════════════════

def build_child_event_id(parent_event_id: str, gate_name: str) -> str:
    """
    Construye el event_id hijo añadiendo el alias del gate al padre.

    Parámetros:
        parent_event_id — el event_id del contexto actual (g.event_id)
        gate_name       — nombre del gate que crea el hijo

    Retorna:
        Cadena con el camino acumulado, ej. "20260404143022847_D_M"

    Nunca lanza excepción — si algo falla retorna el padre sin modificar.
    """
    try:
        alias = gate_alias(gate_name)
        return f"{parent_event_id}_{alias}"
    except Exception:
        return parent_event_id


def parse_event_path(event_id: str) -> dict:
    """
    Parsea un event_id con camino y devuelve sus partes.

    Ejemplos:
        parse_event_path("20260404143022847_D_M")
        → {
            "root":  "20260404143022847",
            "path":  ["D", "M"],
            "depth": 2,
            "raw":   "20260404143022847_D_M"
          }

        parse_event_path("20260404143022847")
        → {
            "root":  "20260404143022847",
            "path":  [],
            "depth": 0,
            "raw":   "20260404143022847"
          }
    """
    parts = event_id.split("_")
    root  = parts[0]
    path  = parts[1:] if len(parts) > 1 else []
    return {
        "root":  root,
        "path":  path,
        "depth": len(path),
        "raw":   event_id,
    }


# ══════════════════════════════════════════════════════════
# GENERADOR BASE (sin cambios)
# ══════════════════════════════════════════════════════════

def generate_event_id() -> str:
    """
    Genera un ID de evento basado en el timestamp actual.

    Formato: YYYYMMDDHHMMSSMMM (17 caracteres)

    Ejemplo:
        20260404143022847

    Uso:
        from shared.control.event_id import generate_event_id
        event_id = generate_event_id()
    """
    now = datetime.now()
    ms  = now.microsecond // 1000
    return now.strftime("%Y%m%d%H%M%S") + f"{ms:03d}"


def parse_event_id(event_id: str) -> dict:
    """
    Parsea el ID raíz (17 dígitos) y devuelve sus componentes.

    Retorna:
        {
            "year":   2026,
            "month":  4,
            "day":    4,
            "hour":   14,
            "minute": 30,
            "second": 22,
            "ms":     847,
            "raw":    "20260404143022847"
        }
    """
    root = event_id.split("_")[0]   # ignora el camino si lo tiene

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
    """
    Convierte un event_id (o event_id con camino) a datetime.
    Solo usa el root — ignora el camino.
    """
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
    Calcula cuántos milisegundos han pasado desde que
    se generó el ID de evento. Solo usa el root.
    """
    created_at = event_id_to_datetime(event_id)
    delta      = datetime.now() - created_at
    return int(delta.total_seconds() * 1000)