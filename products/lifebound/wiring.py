# products/lifebound/wiring.py
# ══════════════════════════════════════════════════════════════════════════════
# Fase 2 (Wiring) del módulo Lifebound — AUREON v4.0
#
# Cambios v4.0 vs v3.1:
#
#   gate_resolver ya wired por wire_auth()
#     wire_auth() conectó GateResolver ← GateRegistry antes de llegar aquí.
#     Lifebound solo necesita verificar que las ops de su módulo
#     están cargadas en la tabla — no hace wiring propio del resolver.
#
#   Verificación de ops de Lifebound
#     Si tabla_operacion.json está cargada, comprobamos que las ops
#     OP020–OP029 están registradas. Si alguna está ausente → warning.
#     Esto activa el Protocolo XX (Discovery) en runtime si alguien
#     intenta ejecutarlas, pero no bloquea el arranque.
#
# Precondición:
#   wire_auth(app, conductor) debe llamarse antes.
#   wire_lifebound depende de ModuleGate y GateResolver ya disponibles.
#
# Orden de wiring en Fase 2 (app.py):
#   wire_auth(app, conductor)       ← crea gates + conecta resolver + tracer
#   wire_lifebound(app, conductor)  ← reutiliza gates, verifica ops propias
#   conductor.mark_ready()          ← sistema listo
# ══════════════════════════════════════════════════════════════════════════════

from shared.control.registries.base import GateRegistry, event_registry

# Op IDs propias de Lifebound — para verificación en arranque
_LIFEBOUND_OPS = [
    "OP020", "OP021", "OP022", "OP023", "OP024",
    "OP025", "OP025_001", "OP025_002", "OP025_003",
    "OP026", "OP027", "OP028", "OP029",
]


def wire_lifebound(app, conductor) -> None:
    """
    Inyecta los gates de Lifebound y registra el producto en el Conductor.
    Llamar desde app.py en Fase 2, después de wire_auth().
    """

    # ═══════════════════════════════════════════════════════
    # MÓDULE GATE — reutilizado desde wire_auth()
    # ═══════════════════════════════════════════════════════

    if "ModuleGate" not in GateRegistry:
        app.logger.warning(
            "  [!] Lifebound wiring: ModuleGate no encontrado en GateRegistry. "
            "Asegúrate de llamar wire_auth() antes de wire_lifebound()."
        )
        module_gate = None
    else:
        module_gate = GateRegistry.get("ModuleGate")
        app.logger.info("  [✓] Lifebound: ModuleGate reutilizado desde GateRegistry")

    # ═══════════════════════════════════════════════════════
    # INYECCIÓN EN MÓDULOS
    # ═══════════════════════════════════════════════════════

    if module_gate is not None:
        try:
            from products.lifebound.api.generate import set_module_gate
            set_module_gate(module_gate)
            app.logger.info("  [✓] Lifebound: ModuleGate → generate.py")
        except Exception as e:
            app.logger.error(
                "  [✗] Lifebound: inyección de ModuleGate falló: %s", e
            )

    # ═══════════════════════════════════════════════════════
    # VERIFICACIÓN DE OPS EN TABLA — v4.0
    # ═══════════════════════════════════════════════════════
    # Si tabla_operacion.json no tiene las ops de Lifebound,
    # el GateResolver las tratará como XX Discovery en runtime.
    # Aquí solo advertimos — no bloqueamos el arranque.

    try:
        from shared.control.logic.gate_resolver import gate_resolver

        missing = [
            op_id for op_id in _LIFEBOUND_OPS
            if gate_resolver.get_op(op_id) is None
        ]

        if missing:
            app.logger.warning(
                "  [!] Lifebound: %d op(s) no registradas en tabla_operacion.json "
                "→ serán XX Discovery en runtime: %s",
                len(missing),
                missing,
            )
        else:
            app.logger.info(
                "  [✓] Lifebound: %d ops verificadas en GateResolver",
                len(_LIFEBOUND_OPS),
            )

    except Exception as e:
        app.logger.warning(
            "  [!] Lifebound: no se pudo verificar ops en GateResolver: %s", e
        )

    # ═══════════════════════════════════════════════════════
    # REGISTRO EN CONDUCTOR
    # ═══════════════════════════════════════════════════════

    conductor.register_product("lifebound", {
        "status":  "active",
        "version": "1.0",
        "healthy": True,
        "gates":   ["HttpGate", "ModuleGate"],
        "ops":     _LIFEBOUND_OPS,
    })

    app.logger.info("  [✓] Lifebound wired (v4.0)")