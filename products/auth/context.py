# products/auth/context.py
# ══════════════════════════════════════════════════════════════════════════════
# Contenedor de dependencias inyectadas para el módulo auth.
#
# Evita imports directos en routes.py y rompe ciclos.
# Se llena en Fase 2 (wiring.py).
# ══════════════════════════════════════════════════════════════════════════════

import inspect


class AuthContext:

    # ═══════════════════════════════════════════════════════
    # MODELOS
    # ═══════════════════════════════════════════════════════
    User                        = None
    UserIdentity                = None
    UserDevice                  = None
    UserSession                 = None
    UserProduct                 = None

    # ═══════════════════════════════════════════════════════
    # TOKENS / SEGURIDAD
    # ═══════════════════════════════════════════════════════
    create_access_token         = None
    create_refresh_token        = None
    decode_token                = None
    hash_token                  = None

    # ═══════════════════════════════════════════════════════
    # PASSWORDS
    # ═══════════════════════════════════════════════════════
    hash_password               = None
    verify_password             = None
    validate_password_strength  = None

    # ═══════════════════════════════════════════════════════
    # DISPOSITIVOS
    # ═══════════════════════════════════════════════════════
    parse_device                = None
    is_new_device               = None

    # ═══════════════════════════════════════════════════════
    # EMAIL
    # ═══════════════════════════════════════════════════════
    send_verification_email     = None
    send_new_device_alert       = None
    send_reset_password_email   = None
    send_sessions_revoked_email = None

    # ═══════════════════════════════════════════════════════
    # CONTROL / OBSERVABILIDAD
    # ═══════════════════════════════════════════════════════
    conductor                   = None
    breaker_registry            = None
    gate_registry               = None

    # ═══════════════════════════════════════════════════════
    # VALIDACIÓN
    # ═══════════════════════════════════════════════════════

    def validate(self) -> None:
        """
        Verifica que todas las dependencias fueron inyectadas.

        Usa vars(type(self)) en lugar de self.__dict__ para inspeccionar
        atributos declarados en la clase — self.__dict__ solo ve los
        asignados sobre la instancia y silencia los None de clase
        que nunca fueron inyectados.
        """
        missing = [
            name
            for name, value in vars(type(self)).items()
            if not name.startswith("_")
            and not inspect.isfunction(value)
            and getattr(self, name) is None
        ]

        if missing:
            raise RuntimeError(
                f"[AuthContext] Wiring incompleto. "
                f"Faltan {len(missing)} dependencias: {missing}"
            )

    # ═══════════════════════════════════════════════════════
    # UTILIDADES DE INSPECCIÓN
    # ═══════════════════════════════════════════════════════

    def is_ready(self) -> bool:
        """Versión no-lanzable de validate(). Útil en healthchecks."""
        try:
            self.validate()
            return True
        except RuntimeError:
            return False

    def snapshot(self) -> dict:
        """
        Estado actual del contexto para debugging y /health.
        No expone los valores — solo qué está inyectado y qué falta.
        """
        fields = {
            name: getattr(self, name)
            for name, value in vars(type(self)).items()
            if not name.startswith("_")
            and not inspect.isfunction(value)
        }

        return {
            "ready":    all(v is not None for v in fields.values()),
            "injected": [k for k, v in fields.items() if v is not None],
            "missing":  [k for k, v in fields.items() if v is None],
        }


# Singleton controlado — se llena en products/auth/wiring.py
auth_context = AuthContext()