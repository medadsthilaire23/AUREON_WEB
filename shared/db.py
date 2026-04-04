# shared/db.py
# ══════════════════════════════════════════════════════════════════════════════
# Gestión de base de datos — AUREON v3.0
#
# Producción: PostgreSQL (obligatorio)
# Desarrollo: SQLite fallback
#
# Cambios v3:
#   - Eliminado conductor.boot_gate() — ese método no existe en Conductor v3
#   - db_gate sigue siendo opcional — en Fase 1 llega None (el gate se crea
#     en Fase 2). El BootGate de app.py captura el resultado del paso.
#   - Si db_gate está presente (llamada manual post-wiring), registra en
#     EventRegistry vía record_ok / record_fail.
# ══════════════════════════════════════════════════════════════════════════════

import os
import logging
from flask_sqlalchemy import SQLAlchemy

db  = SQLAlchemy()
log = logging.getLogger("aureon.db")


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def _get_sqlite_fallback() -> str:
    base_dir    = os.path.dirname(os.path.abspath(__file__))
    sqlite_path = os.path.join(base_dir, "..", "aureon_dev.db")
    return f"sqlite:///{os.path.abspath(sqlite_path)}"


def init_db(app, db_gate=None):
    """
    Inicializa la base de datos.

    Args:
        app     → Flask app
        db_gate → (opcional) DbGate concreto — si está presente registra
                  el resultado en EventRegistry (OP009_001).
                  En Fase 1 siempre es None — el BootGate captura el paso.
                  Puede pasarse en tests o en llamadas post-wiring.
    """
    database_url  = os.environ.get("DATABASE_URL", "").strip()
    is_production = os.environ.get("FLASK_ENV") == "production"

    # ── Resolver URL ──────────────────────────────────────

    if database_url:
        database_url = _normalize_database_url(database_url)
    else:
        if is_production:
            raise RuntimeError("DATABASE_URL is required in production")
        database_url = _get_sqlite_fallback()

    # ── Config base ───────────────────────────────────────

    app.config["SQLALCHEMY_DATABASE_URI"]        = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # ── Config avanzada (PostgreSQL) ──────────────────────

    if not database_url.startswith("sqlite"):
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "pool_pre_ping": True,
            "pool_recycle":  280,
            "pool_size":     3,
            "max_overflow":  2,
            "pool_timeout":  30,
            "connect_args":  {"sslmode": "require"},
        }

    # ── Init + verificación de conexión ───────────────────

    try:
        db.init_app(app)

        with app.app_context():
            db.engine.connect()

        # Registrar en EventRegistry si DbGate está disponible
        if db_gate is not None:
            db_gate.record_ok("OP009_001")

        log.info("[db] conexión establecida — %s",
                 "postgresql" if not database_url.startswith("sqlite") else "sqlite")

    except Exception as e:
        # Registrar fallo si DbGate está disponible
        if db_gate is not None:
            db_gate.record_fail("OP009_001", error=str(e))

        raise RuntimeError(f"Database initialization failed: {e}")