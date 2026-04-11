#!/usr/bin/env python3
# management/generar_matriz.py
# ══════════════════════════════════════════════════════════════════════════════
# Script relámpago — genera management/data/matriz_26x26.json
# Corre una sola vez en local antes del deploy inicial de v4.0.
#
# Uso:
#   cd AUREON_WEB/management
#   python generar_matriz.py
# ══════════════════════════════════════════════════════════════════════════════

import json
import os
import string

_DIR      = os.path.dirname(os.path.abspath(__file__))
_OUT_PATH = os.path.join(_DIR, "data", "matriz_26x26.json")

# Prefijos reservados por el sistema — no disponibles para nuevas operaciones
_RESERVADOS = {
    "OP",   # Operation (prefijo estándar de negocio)
    "AD",   # Anomalía Admin
    "UR",   # Anomalía Usuario
    "FL",   # Anomalía Falso Loc
    "GB",   # Anomalía Gate Bloqueado
    "FA",   # Anomalía Fallo Técnico
    "TM",   # Anomalía Timeout
    "SA",   # Anomalía Saturación
    "XX",   # Discovery — reservado permanentemente
}

# Prefijos con uso especial documentado
_ESPECIALES = {
    "OP": "Operation Success — prefijo estándar de operaciones de negocio",
    "AD": "Anomalía Admin — acciones no autorizadas",
    "UR": "Anomalía Usuario — errores de input o permisos",
    "FL": "Anomalía Falso Loc — IP/GPS manipulado",
    "GB": "Anomalía Gate Bloqueado — saltarse puerta obligatoria",
    "FA": "Anomalía Fallo Técnico — Python exception",
    "TM": "Anomalía Timeout — latencia crítica",
    "SA": "Anomalía Saturación — DDoS o rate limit",
    "XX": "Discovery — operación no registrada (ROJA_CRITICA)",
}

letras = string.ascii_uppercase  # A-Z


def generar():
    matriz = {
        "_meta": {
            "version":     "4.0",
            "description": "Inventario de 676 combinaciones de prefijos AA-ZZ",
            "total":       676,
            "reservados":  sorted(_RESERVADOS),
            "estados": {
                "LIBRE":     "Disponible para nuevas operaciones",
                "RESERVADO": "En uso por el sistema — no disponible",
                "ESPECIAL":  "Prefijo de anomalía o sistema con significado fijo",
            }
        },
        "combinaciones": {}
    }

    libre    = 0
    reservado = 0

    for l1 in letras:
        for l2 in letras:
            prefijo = f"{l1}{l2}"

            if prefijo in _RESERVADOS:
                estado      = "RESERVADO" if prefijo == "OP" else "ESPECIAL"
                descripcion = _ESPECIALES.get(prefijo, "Reservado por el sistema")
                reservado  += 1
            else:
                estado      = "LIBRE"
                descripcion = "Disponible"
                libre      += 1

            matriz["combinaciones"][prefijo] = {
                "estado":      estado,
                "descripcion": descripcion,
            }

    matriz["_meta"]["libre"]     = libre
    matriz["_meta"]["reservado"] = reservado

    os.makedirs(os.path.dirname(_OUT_PATH), exist_ok=True)
    with open(_OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(matriz, f, indent=2, ensure_ascii=False)

    print(f"✓ matriz_26x26.json generado: {libre} libres, {reservado} reservados/especiales")
    print(f"  → {_OUT_PATH}")


if __name__ == "__main__":
    generar()