"""
products/auth/middleware.py
===========================
Re-exporta los decorators de autenticación desde shared/auth_middleware.py.

Permite importar desde productos usando la ruta corta:
    from products.auth.middleware import require_auth
    from products.auth.middleware import optional_auth
    from products.auth.middleware import require_verified

O directamente desde shared (ambas rutas funcionan igual):
    from shared.auth_middleware import require_auth
"""

from shared.auth_middleware import require_auth, optional_auth, require_verified

__all__ = ["require_auth", "optional_auth", "require_verified"]