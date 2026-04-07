# products/lifebound/wiring.py
# ══════════════════════════════════════════════════════════════════════════════
# Fase 2 (Wiring) del módulo Lifebound — AUREON v3.1
#
# Patrón idéntico a products/auth/wiring.py.
# Llamar desde app.py en Fase 2, después de wire_auth():
#
#     from products.lifebound.wiring import wire_lifebound
#     wire_lifebound(app, conductor)
#
# Responsabilidades:
#   - Inyectar ModuleGate en generate.py (generación de PDF vía IA)
#   - Registrar Lifebound en el Conductor
#   - No toca HttpGate ni DbGate — Lifebound no tiene DB propia
# ══════════════════════════════════════════════════════════════════════════════

from shared.control.registries.base import GateRegistry, event_registry


def wire_lifebound(app, conductor) -> None:
    """
    Inyecta los gates de Lifebound y registra el producto en el Conductor.
    Llamar desde app.py en Fase 2.
    """

    # ── ModuleGate — ya creado por auth/wiring.py ──────────────────────────
    # Lifebound reutiliza el mismo ModuleGate global para las llamadas
    # a servicios externos (generación de PDF, IA).
    # No creamos uno nuevo — el gate es compartido por toda la app.

    if "ModuleGate" not in GateRegistry:
        app.logger.warning(
            "  [!] Lifebound wiring: ModuleGate no encontrado en GateRegistry. "
            "Asegúrate de llamar wire_auth() antes de wire_lifebound()."
        )
        module_gate = None
    else:
        module_gate = GateRegistry.get("ModuleGate")
        app.logger.info("  [✓] Lifebound: ModuleGate reutilizado desde GateRegistry")

    # ── Inyectar ModuleGate en generate.py ────────────────────────────────
    if module_gate is not None:
        try:
            from products.lifebound.api.generate import set_module_gate
            set_module_gate(module_gate)
            app.logger.info("  [✓] Lifebound: ModuleGate → generate.py")
        except Exception as e:
            app.logger.error("  [✗] Lifebound: inyección de ModuleGate falló: %s", e)

    # ── Registrar en el Conductor ──────────────────────────────────────────
    conductor.register_product("lifebound", {
        "status":  "active",
        "version": "1.0",
        "healthy": True,
        "gates":   ["HttpGate", "ModuleGate"],
    })

    app.logger.info("  [✓] Lifebound wired")