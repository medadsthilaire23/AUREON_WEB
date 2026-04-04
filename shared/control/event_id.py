# shared/control/event_id.py
# ══════════════════════════════════════════════════════════════════════════════
# Generador del ID de evento — AUREON Sistema de Control v3.0
#
# El ID de evento es el identificador único de cada evento que pasa
# por el sistema de control. Lo genera el Gate en el momento del escaneo.
#
# Formato:
#     YYYYMMDDHHMMSSMMM
#     20260404143022847
#
#     Año:     2026
#     Mes:     04
#     Día:     04
#     Hora:    14
#     Minuto:  30
#     Segundo: 22
#     Ms:      847
#
# Propiedades:
#     - Ordenable cronológicamente sin campo extra
#     - Legible — el timestamp es el diagnóstico
#     - Único — la cadena es secuencial, no paralela
#     - Compacto — 17 caracteres, sin separadores
#
# Regla arquitectónica:
#     Este módulo NO importa nada de products/ ni de otros
#     módulos de control. Es la base — no tiene dependencias.
# ══════════════════════════════════════════════════════════════════════════════

from datetime import datetime


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
    Parsea un ID de evento y devuelve sus componentes.

    Útil para el Conductor cuando necesita correlacionar
    eventos por rango de tiempo.

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
    if len(event_id) != 17 or not event_id.isdigit():
        raise ValueError(
            f"ID de evento inválido: '{event_id}'. "
            f"Formato esperado: YYYYMMDDHHMMSSMMM (17 dígitos)"
        )

    return {
        "year":   int(event_id[0:4]),
        "month":  int(event_id[4:6]),
        "day":    int(event_id[6:8]),
        "hour":   int(event_id[8:10]),
        "minute": int(event_id[10:12]),
        "second": int(event_id[12:14]),
        "ms":     int(event_id[14:17]),
        "raw":    event_id,
    }


def event_id_to_datetime(event_id: str) -> datetime:
    """
    Convierte un ID de evento a un objeto datetime.

    Útil para el Timer cuando necesita calcular
    cuánto tiempo lleva un evento en un estado.
    """
    parts = parse_event_id(event_id)
    return datetime(
        year=parts["year"],
        month=parts["month"],
        day=parts["day"],
        hour=parts["hour"],
        minute=parts["minute"],
        second=parts["second"],
        microsecond=parts["ms"] * 1000,
    )


def event_id_age_ms(event_id: str) -> int:
    """
    Calcula cuántos milisegundos han pasado desde que
    se generó el ID de evento.

    Útil para el Conductor para detectar eventos
    que llevan demasiado tiempo en PENDING.
    """
    created_at = event_id_to_datetime(event_id)
    delta      = datetime.now() - created_at
    return int(delta.total_seconds() * 1000)