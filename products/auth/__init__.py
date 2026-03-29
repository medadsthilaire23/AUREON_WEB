"""
products/auth/__init__.py
=========================
Exporta el blueprint principal de auth.

oauth_bp y passkey_bp se registran directamente en la app Flask
para evitar problemas de rutas anidadas con url_prefix.

Rutas finales:
    /auth/*          → auth_bp  (routes.py)
    /auth/passkey/*  → passkey_bp
    /auth/oauth/*    → oauth_bp
"""

import os
from products.auth.routes  import auth_bp
from products.auth.passkey import passkey_bp
from products.auth.oauth   import oauth_bp, init_oauth

_AUTH_DIR = os.path.dirname(os.path.abspath(__file__))

# Configurar template_folder y static_folder en auth_bp
auth_bp.template_folder = os.path.join(_AUTH_DIR, "templates")
auth_bp.static_folder   = os.path.join(_AUTH_DIR, "static")
auth_bp.static_url_path = "/auth/static"


def init_auth(app):
    """
    Inicializa OAuth y registra los tres blueprints directamente en la app.
    Llamar desde app.py antes de register_blueprint.
    """
    init_oauth(app)

    # Registrar directamente en la app — no como sub-blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(passkey_bp)
    app.register_blueprint(oauth_bp)


__all__ = ["auth_bp", "init_auth"]