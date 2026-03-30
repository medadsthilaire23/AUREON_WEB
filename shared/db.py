"""
shared/db.py
============
Conexión a base de datos compartida para todos los productos AUREON.

Producción : PostgreSQL via DATABASE_URL en variables de entorno
Desarrollo : SQLite automático si DATABASE_URL no está configurado
"""

import os
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def init_db(app):
    database_url = os.environ.get("DATABASE_URL", "")

    # Render entrega URLs con postgres:// — SQLAlchemy necesita postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    # Fallback a SQLite para desarrollo local
    if not database_url:
        base_dir     = os.path.dirname(os.path.abspath(__file__))
        sqlite_path  = os.path.join(base_dir, "..", "aureon_dev.db")
        database_url = f"sqlite:///{os.path.abspath(sqlite_path)}"

    app.config["SQLALCHEMY_DATABASE_URI"]        = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Engine options solo para PostgreSQL (SQLite no las soporta)
    if not database_url.startswith("sqlite"):
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "pool_pre_ping":  True,
            "pool_recycle":   300,
            "pool_size":      5,
            "max_overflow":   10,
            "connect_args":   {"sslmode": "require"},  # Requerido para NeonDB
        }

    db.init_app(app)