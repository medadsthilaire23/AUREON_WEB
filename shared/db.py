"""
shared/db.py
============

Gestión de base de datos para AUREON.

- Producción: PostgreSQL (obligatorio)
- Desarrollo: SQLite fallback
- Integrado con Conductor (opcional)
"""

import os
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def _normalize_database_url(url: str) -> str:
    """Corrige esquema postgres:// → postgresql://"""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def _get_sqlite_fallback() -> str:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    sqlite_path = os.path.join(base_dir, "..", "aureon_dev.db")
    return f"sqlite:///{os.path.abspath(sqlite_path)}"


def init_db(app, conductor=None):
    """
    Inicializa la base de datos.

    Args:
        app: Flask app
        conductor: (opcional) sistema de control central
    """

    database_url = os.environ.get("DATABASE_URL", "").strip()
    is_production = os.environ.get("FLASK_ENV") == "production"

    # =========================
    # 🔹 RESOLVER URL
    # =========================
    if database_url:
        database_url = _normalize_database_url(database_url)
    else:
        if is_production:
            raise RuntimeError("DATABASE_URL is required in production")
        database_url = _get_sqlite_fallback()

    # =========================
    # 🔹 CONFIG BASE
    # =========================
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # =========================
    # 🔹 CONFIG AVANZADA (PostgreSQL)
    # =========================
    if not database_url.startswith("sqlite"):
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "pool_pre_ping": True,        # evita conexiones muertas
            "pool_recycle": 280,          # evita timeouts de Render/Neon
            "pool_size": 3,               # optimizado para free tier
            "max_overflow": 2,
            "pool_timeout": 30,
            "connect_args": {
                "sslmode": "require"
            },
        }

    # =========================
    # 🔹 INIT
    # =========================
    try:
        db.init_app(app)

        # Test de conexión en arranque
        with app.app_context():
            db.engine.connect()

        if conductor:
            conductor.boot_gate("db_connection", True)

    except Exception as e:
        if conductor:
            conductor.boot_gate("db_connection", False)
        raise RuntimeError(f"Database initialization failed: {e}")