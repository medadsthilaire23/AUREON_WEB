# migrations/env.py — AUREON
# ══════════════════════════════════════════════════════════════════════════════
# Punto de entrada de Alembic.
# Conecta los modelos SQLAlchemy con el motor de migraciones.
#
# Uso:
#   alembic revision --autogenerate -m "descripcion"
#   alembic upgrade head
#   alembic downgrade -1
# ══════════════════════════════════════════════════════════════════════════════

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from dotenv import load_dotenv

# ── Cargar .env ────────────────────────────────────────────────────────────
load_dotenv()

# ── Paths — permite importar shared y products desde la raíz ──────────────
_HERE     = os.path.dirname(os.path.abspath(__file__))
_ROOT     = os.path.dirname(_HERE)
_SHARED   = os.path.join(_ROOT, "shared")
_PRODUCTS = os.path.join(_ROOT, "products")

for _path in [_ROOT, _SHARED, _PRODUCTS]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

# ── Importar modelos para que Alembic los detecte en autogenerate ──────────
# IMPORTANTE: importar db primero, luego todos los modelos.
# Si agregas nuevos modelos en el futuro, impórtalos aquí también.
from shared.db import db                              # noqa: E402
from products.auth.models import (                    # noqa: E402
    User,
    UserIdentity,
    UserDevice,
    UserSession,
    UserPasskey,
    UserProduct,
    UserActivity,
)

target_metadata = db.metadata

# ── Config de Alembic ──────────────────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Inyectar DATABASE_URL desde entorno ───────────────────────────────────
def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL no está definida. "
            "Agrégala al .env o como variable de entorno."
        )
    # Render/Heroku usan postgres://, SQLAlchemy necesita postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


# ══════════════════════════════════════════════════════════════════════════════
# MODO OFFLINE — genera SQL sin conectarse a la DB
# ══════════════════════════════════════════════════════════════════════════════

def run_migrations_offline() -> None:
    url = _get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ══════════════════════════════════════════════════════════════════════════════
# MODO ONLINE — se conecta a la DB y aplica migraciones
# ══════════════════════════════════════════════════════════════════════════════

def run_migrations_online() -> None:
    url = _get_database_url()

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"sslmode": "require"},
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


# ── Entry point ────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()