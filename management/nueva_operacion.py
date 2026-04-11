#!/usr/bin/env python3
# management/nueva_operacion.py
# ══════════════════════════════════════════════════════════════════════════════
# CLI de Aduana — AUREON v4.0
#
# Registra nuevas operaciones en tabla_operacion.json antes de hacer deploy.
# Valida prefijos, sugiere op_ids disponibles y actualiza el JSON atómicamente.
#
# Uso:
#   cd AUREON_WEB/management
#   python nueva_operacion.py
#
# Flujo:
#   1. Seleccionar módulo (auth, lifebound, context, core, dashboard)
#   2. Ingresar nombre descriptivo de la operación
#   3. Definir rutas HTTP (método + path)
#   4. Seleccionar gates requeridos
#   5. Asignar op_id (sugerido automáticamente o manual)
#   6. Confirmar y escribir en tabla_operacion.json
#   7. Hacer git commit + deploy
#
# Regla: nunca modifica JSON en runtime — solo en local antes del deploy.
# ══════════════════════════════════════════════════════════════════════════════

import json
import os
import sys
from datetime import datetime

# ── Rutas ────────────────────────────────────────────────────────────────────
_DIR       = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR  = os.path.join(_DIR, "data")
_JSON_PATH = os.path.join(_DATA_DIR, "tabla_operacion.json")
_PREF_PATH = os.path.join(_DATA_DIR, "prefijos.json")

# ── Rangos por módulo ─────────────────────────────────────────────────────────
RANGOS = {
    "auth":      (1,   99),
    "context":   (300, 399),
    "lifebound": (400, 599),
    "dashboard": (99,  99),   # solo OP099_*
    "core":      (900, 999),
    "system":    (9,   10),   # OP009, OP010
}

GATES_DISPONIBLES = ["HttpGate", "DbGate", "ModuleGate", "BootGate"]

LOG_POLICIES = {
    "1": ("SUMMARY",  "Operaciones exitosas — contadores en memoria"),
    "2": ("ON_ERROR", "Solo registra en caso de fallo"),
    "3": ("AUDIT",    "Registro completo — gates especiales y seguridad"),
}

COLORES = {
    "verde":    "\033[92m",
    "rojo":     "\033[91m",
    "amarillo": "\033[93m",
    "azul":     "\033[94m",
    "cyan":     "\033[96m",
    "reset":    "\033[0m",
    "bold":     "\033[1m",
}


def c(texto: str, color: str) -> str:
    return f"{COLORES.get(color,'')}{texto}{COLORES['reset']}"


def titulo(texto: str) -> None:
    print(f"\n{c('══════════════════════════════════════', 'azul')}")
    print(f"  {c(texto, 'bold')}")
    print(f"{c('══════════════════════════════════════', 'azul')}")


def ok(texto: str) -> None:
    print(f"  {c('✓', 'verde')} {texto}")


def warn(texto: str) -> None:
    print(f"  {c('⚠', 'amarillo')} {texto}")


def error(texto: str) -> None:
    print(f"  {c('✗', 'rojo')} {texto}")


def preguntar(prompt: str, default: str = "") -> str:
    valor = input(f"  {c('?', 'cyan')} {prompt} [{default}]: ").strip()
    return valor if valor else default


def preguntar_lista(prompt: str, opciones: list[str]) -> list[str]:
    print(f"\n  {c('?', 'cyan')} {prompt}")
    for i, op in enumerate(opciones, 1):
        print(f"    {i}. {op}")
    seleccion = input("  Números separados por coma (ej: 1,3): ").strip()
    indices   = [int(x.strip()) - 1 for x in seleccion.split(",") if x.strip().isdigit()]
    return [opciones[i] for i in indices if 0 <= i < len(opciones)]


# ── Cargar/guardar JSON ────────────────────────────────────────────────────────

def cargar_tabla() -> dict:
    if not os.path.exists(_JSON_PATH):
        error(f"tabla_operacion.json no encontrado en {_JSON_PATH}")
        sys.exit(1)
    with open(_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_tabla(data: dict) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    # Escritura atómica — escribir a .tmp y renombrar
    tmp_path = _JSON_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, _JSON_PATH)


# ── Sugerir op_id disponible ───────────────────────────────────────────────────

def sugerir_op_id(modulo: str, tabla: dict, es_hijo: bool = False, padre_id: str = "") -> str:
    ops_existentes = set(tabla.get("operaciones", {}).keys())

    if es_hijo and padre_id:
        # Buscar el siguiente hijo disponible
        nivel = padre_id.count("_") + 2
        for n in range(1, 100):
            candidato = f"{padre_id}_{n:03d}"
            if candidato not in ops_existentes:
                return candidato
        return f"{padre_id}_001"

    # Buscar el siguiente número raíz disponible en el rango del módulo
    rango = RANGOS.get(modulo, (1, 99))
    for n in range(rango[0], rango[1] + 1):
        candidato = f"OP{n:03d}"
        if candidato not in ops_existentes:
            return candidato

    return f"OP{rango[0]:03d}"


# ── Validaciones ──────────────────────────────────────────────────────────────

def validar_op_id(op_id: str, tabla: dict) -> tuple[bool, str]:
    ops = tabla.get("operaciones", {})

    if op_id == "XX":
        return False, "XX es el prefijo de Discovery — no se puede registrar como operación"

    if op_id in ops:
        return False, f"'{op_id}' ya existe: {ops[op_id].get('nombre', '')}"

    if not op_id.startswith("OP"):
        return False, "El op_id debe comenzar con 'OP'"

    # Verificar que el padre existe si es hijo
    if "_" in op_id:
        padre = op_id.rsplit("_", 1)[0]
        if padre not in ops:
            return False, f"El padre '{padre}' no existe en tabla_operacion.json"

    return True, "ok"


def validar_rutas(rutas: list[dict]) -> list[str]:
    metodos_validos = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
    errores = []
    for i, ruta in enumerate(rutas):
        if ruta["method"] not in metodos_validos:
            errores.append(f"Ruta {i+1}: método '{ruta['method']}' inválido")
        if not ruta["path"].startswith("/"):
            errores.append(f"Ruta {i+1}: path debe empezar con '/'")
    return errores


# ── Flujo principal ────────────────────────────────────────────────────────────

def main():
    titulo("AUREON v4.0 — Aduana de Operaciones")
    print(f"  {c('nueva_operacion.py', 'cyan')} — Registrar nueva operación en tabla_operacion.json")
    print(f"  Archivo destino: {c(_JSON_PATH, 'amarillo')}\n")

    tabla = cargar_tabla()
    ops   = tabla.get("operaciones", {})

    print(f"  Operaciones actuales: {c(str(len(ops)), 'verde')}")

    # ── 1. Módulo ─────────────────────────────────────────────────────────────
    titulo("Paso 1 — Módulo")
    modulos = list(RANGOS.keys())
    for i, m in enumerate(modulos, 1):
        rango = RANGOS[m]
        print(f"    {i}. {c(m, 'cyan')} (rango OP{rango[0]:03d}-OP{rango[1]:03d})")

    mod_idx = preguntar("Número de módulo", "1")
    try:
        modulo = modulos[int(mod_idx) - 1]
    except (ValueError, IndexError):
        modulo = "auth"
    ok(f"Módulo: {modulo}")

    # ── 2. ¿Es hijo de otra operación? ────────────────────────────────────────
    titulo("Paso 2 — Jerarquía")
    es_hijo_str = preguntar("¿Es hijo de otra operación? (s/n)", "n").lower()
    es_hijo     = es_hijo_str in ("s", "si", "sí", "y", "yes")
    padre_id    = ""

    if es_hijo:
        padre_id = preguntar("Op ID del padre (ej: OP001)").upper()
        if padre_id not in ops:
            error(f"'{padre_id}' no existe. Verifica el ID.")
            sys.exit(1)
        ok(f"Padre: {padre_id} — {ops[padre_id].get('nombre', '')}")

    # ── 3. Nombre y descripción ────────────────────────────────────────────────
    titulo("Paso 3 — Identidad")
    nombre      = preguntar("Nombre técnico (snake_case, ej: user_profile_update)")
    descripcion = preguntar("Descripción legible")

    if not nombre:
        error("El nombre es obligatorio")
        sys.exit(1)

    # ── 4. Op ID ──────────────────────────────────────────────────────────────
    titulo("Paso 4 — Op ID")
    sugerido = sugerir_op_id(modulo, tabla, es_hijo, padre_id)
    print(f"  Sugerido: {c(sugerido, 'verde')}")
    op_id_raw = preguntar("Op ID (Enter para usar el sugerido)", sugerido).upper()
    op_id     = op_id_raw if op_id_raw else sugerido

    valido, msg = validar_op_id(op_id, tabla)
    if not valido:
        error(f"Op ID inválido: {msg}")
        sys.exit(1)
    ok(f"Op ID: {op_id}")

    # ── 5. Rutas HTTP ─────────────────────────────────────────────────────────
    titulo("Paso 5 — Rutas HTTP")
    rutas   = []
    agregar = True

    while agregar:
        metodo = preguntar("Método HTTP (GET/POST/PUT/DELETE, vacío para terminar)", "").upper()
        if not metodo:
            break
        path = preguntar("Path (ej: /api/nuevo/endpoint)")
        if path:
            rutas.append({"method": metodo, "path": path})
            ok(f"{metodo} {path}")

    errores_ruta = validar_rutas(rutas)
    if errores_ruta:
        for e_r in errores_ruta:
            error(e_r)
        sys.exit(1)

    if not rutas:
        warn("Sin rutas HTTP — esta operación será solo interna (ej: sub-proceso)")

    # ── 6. Gates ──────────────────────────────────────────────────────────────
    titulo("Paso 6 — Gates requeridos")
    gates = preguntar_lista("Selecciona los gates que necesita esta operación:", GATES_DISPONIBLES)
    if not gates:
        gates = ["HttpGate"]
        warn("Sin gates seleccionados — usando HttpGate por defecto")
    ok(f"Gates: {', '.join(gates)}")

    # ── 7. Log policy ─────────────────────────────────────────────────────────
    titulo("Paso 7 — Política de logs")
    for k, (policy, desc) in LOG_POLICIES.items():
        print(f"    {k}. {c(policy, 'cyan')} — {desc}")
    policy_idx    = preguntar("Política (1/2/3)", "1")
    log_policy, _ = LOG_POLICIES.get(policy_idx, LOG_POLICIES["1"])
    ok(f"Log policy: {log_policy}")

    # ── 8. Resumen y confirmación ─────────────────────────────────────────────
    titulo("Resumen")
    nueva_op = {
        "nombre":      nombre,
        "descripcion": descripcion,
        "modulo":      modulo,
        "nivel":       (padre_id.count("_") + 2) if es_hijo else 1,
        "gates":       gates,
        "padre":       padre_id if es_hijo else None,
        "log_policy":  log_policy,
    }
    if rutas:
        nueva_op["rutas"] = rutas

    print(json.dumps({op_id: nueva_op}, indent=4, ensure_ascii=False))

    confirmar = preguntar(f"\n{c('¿Registrar esta operación?', 'bold')} (s/n)", "n").lower()
    if confirmar not in ("s", "si", "sí", "y", "yes"):
        warn("Operación cancelada — tabla_operacion.json sin cambios")
        sys.exit(0)

    # ── 9. Escribir en JSON ───────────────────────────────────────────────────
    tabla["operaciones"][op_id] = nueva_op

    # Mantener meta actualizado
    if "_meta" not in tabla:
        tabla["_meta"] = {}
    tabla["_meta"]["ultima_actualizacion"] = datetime.now().isoformat()

    guardar_tabla(tabla)

    titulo("¡Operación registrada!")
    ok(f"'{op_id}' agregado a tabla_operacion.json")
    ok(f"Total operaciones: {len(tabla['operaciones'])}")
    print(f"\n  {c('Próximos pasos:', 'bold')}")
    print(f"    1. {c('git add management/data/tabla_operacion.json', 'amarillo')}")
    print(f"    2. {c('git commit -m \"feat: add operation {op_id} — {nombre}\"', 'amarillo')}")
    print(f"    3. {c('git push → Render deploy automático', 'amarillo')}")
    print(f"\n  El sistema cargará la nueva operación en el próximo arranque.")
    print(f"  Hasta entonces, la ruta aparecerá como {c('XX (Discovery)', 'rojo')} en el dashboard.\n")


if __name__ == "__main__":
    main()