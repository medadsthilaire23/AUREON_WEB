"""add_role_to_users

Revision ID: 001
Revises:
Create Date: 2026-04-02

Añade la columna `role` a la tabla `users`.
Columna requerida por el modelo User (products/auth/models.py).
"""

from alembic import op
import sqlalchemy as sa

# ── Identificadores de revisión ────────────────────────────────────────────
revision  = "001"
down_revision = None   # primera migración — sin padre
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # Verifica si la columna ya existe antes de crearla
    # (seguro de correr en DBs que ya la tienen por ALTER TABLE manual)
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name  = 'users'
              AND column_name = 'role'
            """
        )
    ).fetchone()

    if result is None:
        op.add_column(
            "users",
            sa.Column(
                "role",
                sa.String(20),
                nullable=False,
                server_default="user",   # valor para filas existentes
            ),
        )


def downgrade() -> None:
    op.drop_column("users", "role")