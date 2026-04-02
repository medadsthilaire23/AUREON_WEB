"""
products/auth/__init__.py
=========================

Exporta los blueprints sin registrarlos.
Registro ocurre en app.py (Fase 1).
"""

import os

from products.auth.routes import auth_bp
from products.auth.passkey import passkey_bp
from products.auth.oauth import oauth_bp, init_oauth
from products.auth.account import account_bp

_AUTH_DIR = os.path.dirname(os.path.abspath(__file__))

# Configuración de assets
auth_bp.template_folder = os.path.join(_AUTH_DIR, "templates")
auth_bp.static_folder = os.path.join(_AUTH_DIR, "static")
auth_bp.static_url_path = "/static"


def create_auth_blueprint():
    """
    Devuelve TODOS los blueprints de auth.
    """
    return [auth_bp, passkey_bp, oauth_bp, account_bp]


def configure_auth(app):
    """
    Fase 2: inicializa OAuth u otros sistemas.
    """
    init_oauth(app)


__all__ = ["create_auth_blueprint", "configure_auth"]